"""Real local fixture I/O for P3; no API, Agent framework or benchmark."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from agentguard.audit import SQLiteAudit
from agentguard.contracts import SecurityContext, ToolCallEvent
from agentguard.executor import GuardedExecutor
from agentguard.policies import PathRule, ToolBinding

ROOT = Path(__file__).resolve().parents[1]


def main():
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="p3-example-", dir=cache) as directory:
        base = Path(directory)
        public = base / "public"
        public.mkdir()
        (public / "sample.txt").write_text("public fixture", encoding="utf-8")
        executions = []

        def read_file(path):
            executions.append(path)
            return Path(path).read_text(encoding="utf-8")

        binding = ToolBinding(
            tool_id="reader",
            name="read_file",
            handler=read_file,
            parameters_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            permissions=("file.read",),
            task_authorizations=("task.read",),
            paths=(PathRule("path", "resource.public", public),),
        )
        context_claims = dict(
            schema_version="1.0",
            context_id="context.1",
            user_id="user.1",
            session_id="session.1",
            task_authorization="task.read",
            allowed_resources=["resource.public"],
            permissions=["file.read"],
            budget={"max_calls": 2, "calls_used": 0},
        )
        context = SecurityContext.from_backend(**context_claims)

        def call(index, path="sample.txt"):
            return ToolCallEvent(
                schema_version="1.0",
                event_type="tool_call",
                event_id=f"event.{index}",
                timestamp=datetime.now(UTC),
                trace_id="trace.1",
                session_id="session.1",
                tool_id="reader",
                name="read_file",
                metadata_digest=binding.metadata_digest,
                tool_call_id=f"call.{index}",
                arguments={"path": path},
                source="example.backend",
                context_ref="context.1",
            )

        from agentguard.policies import PolicyEngine

        class ReviewSecond:
            def evaluate(self, event, context, findings):
                return PolicyEngine(
                    review_tools={"reader"} if event.tool_call_id == "call.3" else set()
                ).evaluate(event, context, findings)

        executor = GuardedExecutor(
            [binding], audit=SQLiteAudit(base / "audit.sqlite3"), policy=ReviewSecond()
        )
        allowed = executor.execute(call(1), context)
        denied = executor.execute(call(2, "../outside.txt"), context)
        reviewed_call = call(3)
        review = executor.execute(reviewed_call, context)
        waited = len(executions) == 1 and not review.executed
        approver = SecurityContext.from_backend(
            **{
                **context_claims,
                "user_id": "reviewer",
                "permissions": ["guard.approve"],
            }
        )
        executor.approve(review.approval_ref, approver=approver)
        approved = executor.execute(reviewed_call, context)
        print(
            json.dumps(
                {
                    "allowed": allowed.executed and allowed.value == "public fixture",
                    "blocked": denied.decision.action == "BLOCK" and not denied.executed,
                    "review_waited": waited,
                    "approved": approved.executed,
                    "actual_executions": len(executions),
                }
            )
        )


if __name__ == "__main__":
    main()
