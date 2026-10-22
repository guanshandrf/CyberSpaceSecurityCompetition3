"""Experiment-only group composition. No modifications to SDK gates/executor."""

import re
import time
from uuid import uuid4

from agentguard.contracts import SecurityContext
from agentguard.executor import ExecutionResult, GuardedExecutor, ResultHandler
from agentguard.policies import ToolBinding
from agentguard.registry import ToolRegistry
from agentguard_bench.guard import GuardBridge, MemoryAudit

GROUPS = {
    "G0": {"gate0": False, "gate1": False, "gate2": False, "basic_rules": False},
    "G1": {"gate0": False, "gate1": False, "gate2": False, "basic_rules": True},
    "G2": {"gate0": True, "gate1": True, "gate2": True, "basic_rules": False},
    "G3": {"gate0": False, "gate1": True, "gate2": True, "basic_rules": False},
    "G4": {"gate0": True, "gate1": False, "gate2": True, "basic_rules": False},
    "G5": {"gate0": True, "gate1": True, "gate2": False, "basic_rules": False},
}
# Deliberately simple result-only lexical baseline, not another "full" SDK.
BASIC = re.compile(
    r"ignore (?:all |the )?previous instructions|new user query|strictly adhere", re.I
)


class ExperimentGuard(GuardBridge):
    def __init__(self, tools, *, group):
        if group not in GROUPS:
            raise ValueError("Unknown experimental group")
        self.config = GROUPS[group]
        self.group = group
        self.audit = MemoryAudit()
        session = "experiment." + uuid4().hex
        claims = dict(
            schema_version="1.0",
            session_id=session,
            task_authorization="task.benchmark",
            allowed_resources=(),
            budget={"max_calls": 16, "calls_used": 0},
        )
        self.context = SecurityContext.from_backend(
            **claims,
            context_id="ctx." + session,
            user_id="benchmark.user",
            permissions=("bench.user",),
        )
        admin = SecurityContext.from_backend(
            **claims,
            context_id="admin." + session,
            user_id="benchmark.catalog",
            permissions=("tool.register", "bench.user", "bench.attack"),
        )
        self.counts = {t["name"]: 0 for t in tools}
        self.handlers, self.bindings, self.registrations = {}, {}, {}
        self.registry = ToolRegistry(audit=self.audit, ttl=3600)
        self._visible = []
        self.check_timings = []
        self.handler_ms = 0.0
        for tool in tools:
            name = tool["name"]

            def observed(_name=name, _handler=tool["handler"], **kwargs):
                self.counts[_name] += 1
                started = time.perf_counter()
                try:
                    return _handler(**kwargs)
                finally:
                    self.handler_ms += (time.perf_counter() - started) * 1000

            self.handlers[name] = observed
            binding = ToolBinding(
                tool_id="bench." + name,
                name=name,
                handler=observed,
                parameters_schema=tool["schema"],
                permissions=(tool.get("permission", "bench.user"),),
                task_authorizations=("task.benchmark",),
            )
            self.bindings[name] = binding
            if self.config["gate0"]:
                started = time.perf_counter()
                result = self.registry.register(
                    binding,
                    admin,
                    description=tool.get("description", "Bounded benchmark tool"),
                    capabilities=tool.get("capabilities", ()),
                    version=tool.get("version", "1"),
                )
                self.audit.actions[-1]["duration_ms"] = (time.perf_counter() - started) * 1000
                self.registrations[name] = result
                if result.decision.action != "ALLOW":
                    continue
            self._visible.append(tool)
        self.executor = GuardedExecutor(
            [] if self.config["gate0"] else list(self.bindings.values()),
            audit=self.audit,
            registry=self.registry if self.config["gate0"] else None,
        )
        self.results = ResultHandler(audit=self.audit)
        self.mode = "full" if self.config["gate0"] else "without_gate0"

    def visible_tools(self):
        return list(self._visible)

    def invoke(self, name, arguments, *, call_id=None, trace_id=None):
        if name not in {t["name"] for t in self._visible}:
            return {"error": "tool.not_admitted"}
        started = time.perf_counter()
        handler_before = self.handler_ms
        call = (
            self.call_event(name, arguments, call_id=call_id, trace_id=trace_id)
            if (self.config["gate1"] or self.config["gate2"])
            else None
        )
        if self.config["gate1"]:
            execution = self.executor.execute(call, self.context)
        else:
            try:
                execution = ExecutionResult(
                    None, executed=True, value=self.handlers[name](**arguments)
                )
            except Exception:
                execution = ExecutionResult(None, executed=True, error_code="tool.failed")
        if self.config["gate2"]:
            value = self.results.handle_execution(
                execution, self.context, call=call
            ).safe_event.content
        else:
            value = (
                execution.value
                if execution.executed and not execution.error_code
                else {"error": "tool.not_executed"}
            )
            value = self.basic_result(value)
        self.check_timings.append(
            max(0.0, (time.perf_counter() - started) * 1000 - (self.handler_ms - handler_before))
        )
        return value

    def basic_result(self, content):
        import json

        started = time.perf_counter()
        if self.config["basic_rules"] and BASIC.search(json.dumps(content, ensure_ascii=False)):
            self.audit.actions.append(
                {
                    "gate": "basic_rules",
                    "action": "BLOCK",
                    "reason_codes": ["baseline.lexical"],
                    "stage": "handled",
                    "duration_ms": (time.perf_counter() - started) * 1000,
                }
            )
            return {"error": "baseline.result_blocked"}
        return content

    def review_content(self, name, arguments, content):
        started = time.perf_counter()
        try:
            if self.config["gate2"]:
                return super().review_content(name, arguments, content)
            return self.basic_result(content)
        finally:
            self.check_timings.append((time.perf_counter() - started) * 1000)
