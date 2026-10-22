"""Unified bounded experiment runner: real API, deterministic replay, and preflight."""

import argparse
import hashlib
import json
import os
import random
import re
import stat
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agentguard.detectors import Redactor
from agentguard_bench.components import openai_tool
from agentguard_bench.experiment_budget import AUTHORIZATION, ExperimentBudget
from agentguard_bench.experiment_cases import build_case, digest
from agentguard_bench.experiment_guard import GROUPS, ExperimentGuard
from agentguard_bench.guard import as_json
from agentguard_bench.live import BudgetExhausted, DeepSeek, LiveFailure
from agentguard_bench.upstream import PINS, source


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    seed: int = Field(ge=0, le=2**32 - 1)
    groups: list[str]
    cases: list[dict]
    output: str = "reports/p8-enhanced"
    max_attempts: int = Field(default=180, ge=1, le=180)
    max_output_tokens: int = Field(default=512, ge=1, le=512)
    temperature: int = Field(default=0, ge=0, le=0)
    model: str = Field(default="deepseek-chat", pattern=r"^deepseek-chat$")


def safe_path(root, relative):
    if type(relative) is not str or PureWindowsPath(relative).drive:
        raise ValueError("Repository-relative path required")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Repository-relative path required")
    current = root
    for part in path.parts:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1)
        ):
            raise ValueError("Linked experiment paths rejected")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes repository")
    return current


def load_config(root, relative):
    path = safe_path(root, relative)
    config = ExperimentConfig.model_validate_json(path.read_text(encoding="utf-8"))
    if (
        not config.groups
        or len(set(config.groups)) != len(config.groups)
        or set(config.groups) - GROUPS.keys()
    ):
        raise ValueError("Distinct supported groups required")
    ids = []
    for case in config.cases:
        if set(case) - {
            "id",
            "benchmark",
            "kind",
            "task",
            "index",
            "variant",
            "steps",
            "repetitions",
        }:
            raise ValueError("Unknown case configuration fields")
        if case.get("benchmark") not in PINS or case.get("kind") not in {"normal", "attack"}:
            raise ValueError("Unsupported case")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", case.get("id", "")):
            raise ValueError("Safe case ID required")
        if type(case.get("steps")) is not int or not 1 <= case["steps"] <= 3:
            raise ValueError("Case steps must be 1..3")
        if type(case.get("repetitions", 1)) is not int or not 1 <= case.get("repetitions", 1) <= 3:
            raise ValueError("Repetitions must be 1..3")
        ids.append(case["id"])
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Distinct cases required")
    safe_path(root, config.output)
    return config


def schedule(config):
    rng = random.Random(config.seed)
    result = []
    # Finish matched primary groups before spending authorization on ablations.
    for candidates in (
        [g for g in config.groups if g in {"G0", "G1", "G2"}],
        [g for g in config.groups if g not in {"G0", "G1", "G2"}],
    ):
        for case in config.cases:
            for repetition in range(case.get("repetitions", 1)):
                order = list(candidates)
                rng.shuffle(order)
                result.extend((case, group, repetition) for group in order)
    return result


class Replay:
    provider_id = "deterministic_official_case_replay"
    response_metadata = {}

    def __init__(self, case):
        self.case, self.index = case, 0
        self.redactor = Redactor()

    def redact(self, value):
        return self.redactor.redact(value)

    def complete(self, messages, *, tools=()):
        # Reference trajectory control, explicitly not an LLM or benchmark score.
        if messages[-1]["role"] == "tool" and "blocked" in messages[-1].get("content", ""):
            return {"role": "assistant", "content": "Replay observed blocked content."}
        plan = self.case.scripted_calls
        if self.index < len(plan):
            item = plan[self.index]
            self.index += 1
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"replay.{self.index}",
                        "type": "function",
                        "function": {
                            "name": item["name"],
                            "arguments": json.dumps(item["arguments"]),
                        },
                    }
                ],
            }
        task = self.case.spec.get("task")
        final = {
            1: "Total spending was 1050.",
            7: "The gift cost 200.",
            9: "Please clarify the intended rent change.",
        }.get(task, "Deterministic replay finished.")
        return {"role": "assistant", "content": final}


def run_loop(case, provider, group):
    bridge = ExperimentGuard(case.tools, group=group)
    messages = json.loads(json.dumps(case.messages))
    visible = bridge.visible_tools()
    admitted = {t["name"] for t in visible}
    if case.seed_observation:
        name, arguments, content = case.seed_observation
        content = (
            bridge.review_content(name, arguments, content)
            if name in admitted
            else {"error": "tool.not_admitted"}
        )
        messages += [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "seed.call",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "seed.call",
                "name": name,
                "content": json.dumps(content, ensure_ascii=False),
            },
        ]
    executed, outputs, proposed, metadata = [], [], [], []
    completed = False
    refusal = None
    for step in range(case.spec["steps"]):
        response = provider.complete(messages, tools=[openai_tool(t) for t in visible])
        metadata.append(dict(getattr(provider, "response_metadata", {})))
        calls = response.get("tool_calls") or []
        if type(calls) is not list or len(calls) > 4:
            raise ValueError("Invalid bounded tool-call batch")
        message = {"role": "assistant", "content": response.get("content")}
        if calls:
            message["tool_calls"] = calls
        messages.append(message)
        outputs.append(response.get("content") or "")
        if response.get("refusal"):
            refusal = True
        if not calls:
            completed = True
            break
        ids = [c.get("id") for c in calls if type(c) is dict]
        if (
            len(ids) != len(calls)
            or any(type(i) is not str for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("Uncorrelatable call IDs")
        for index, call in enumerate(calls):
            name = call["function"]["name"]
            proposed.append(name)
            try:
                arguments = json.loads(call["function"]["arguments"])
                if type(arguments) is not dict:
                    raise ValueError
            except (ValueError, TypeError):
                arguments = None
            before = bridge.counts.get(name, 0)
            result = (
                bridge.invoke(name, arguments, call_id=f"call.{step}.{index}")
                if arguments is not None
                else {"error": "invalid.arguments"}
            )
            if bridge.counts.get(name, 0) > before:
                executed.append({"name": name, "arguments": arguments})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": name,
                    "content": json.dumps(as_json(result), ensure_ascii=False),
                }
            )
    trial = {
        "messages": messages,
        "output": "\n".join(outputs),
        "completed": completed,
        "counts": bridge.counts,
        "executed_calls": executed,
        "proposed_tools": proposed,
        "audit": bridge.audit.actions,
        "check_latencies_ms": bridge.check_timings,
        "model_refused": refusal,
        "response_metadata": metadata,
    }
    return {**trial, **case.judge(trial)}


def preflight(root, config):
    manifest = []
    for spec in config.cases:
        try:
            case = build_case(root, spec)
            for group in config.groups:
                ExperimentGuard(case.tools, group=group)
            manifest.append(
                {
                    "spec": case.spec,
                    "status": "SUPPORTED_SUBSET",
                    "input_sha256": digest(
                        {
                            "messages": case.messages,
                            "tools": [
                                {k: v for k, v in t.items() if k != "handler"} for t in case.tools
                            ],
                            "seed": case.seed_observation,
                        }
                    ),
                    "attack_sha256": case.attack_hash,
                    "limitations": case.limits,
                }
            )
        except Exception as exc:
            manifest.append({"spec": spec, "status": "NOT_SUPPORTED", "reason": type(exc).__name__})
    return manifest


def execute(root, config, *, mode, enable_real=False):
    if mode == "real" and not enable_real:
        raise ValueError("Real API requires explicit opt-in")
    manifest = preflight(root, config)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    output = safe_path(root, config.output) / run_id
    output.mkdir(parents=True)

    def git(args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    metadata = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "git_commit": git(["rev-parse", "HEAD"]),
        "git_dirty": bool(git(["status", "--porcelain"])),
        "diff_sha256": digest(git(["diff", "HEAD"])),
        "config": config.model_dump(),
        "config_sha256": digest(config.model_dump()),
        "source_pins": PINS,
        "cases": manifest,
        "group_configurations": GROUPS,
        "model_seed": None,
        "seed_scope": "schedule and bootstrap only; provider seed unsupported",
        "authorization": AUTHORIZATION if mode == "real" else None,
    }
    metadata["experiment_sources_sha256"] = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (root / "benchmarks/src/agentguard_bench").glob("*.py")
    }
    (output / "manifest.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if mode == "preflight":
        print(
            json.dumps(
                {
                    "output": str(output.relative_to(root)),
                    "supported": sum(c["status"] == "SUPPORTED_SUBSET" for c in manifest),
                    "cases": len(manifest),
                }
            )
        )
        return output
    budget, live = None, None
    if mode == "real":
        ledger = safe_path(root, ".cache/p8-enhanced-live")
        ledger.mkdir(parents=True, exist_ok=True)
        budget = ExperimentBudget(ledger, limit=config.max_attempts)
        live = DeepSeek(
            root=root, budget=budget, enabled=True, max_output_tokens=config.max_output_tokens
        )
    statuses = {c["spec"]["id"]: c for c in manifest}
    rows, stopped, failures = [], False, 0
    for number, (spec, group, repetition) in enumerate(schedule(config)):
        record = {
            "run_id": run_id,
            "case_id": spec["id"],
            "benchmark": spec["benchmark"],
            "sample_id": spec.get("index", spec.get("task", spec["id"])),
            "kind": spec["kind"],
            "group": group,
            "repetition": repetition,
            "seed": config.seed,
            "mode": mode,
            "scope": "official_case_replay",
            "upstream_commit": PINS[spec["benchmark"]][1],
            "git_commit": metadata["git_commit"],
            "config_sha256": metadata["config_sha256"],
            "model": config.model if mode == "real" else Replay.provider_id,
            "temperature": 0,
            "max_output_tokens": config.max_output_tokens,
            "input_sha256": statuses[spec["id"]].get("input_sha256"),
            "task_success": None,
            "attack_success": None,
            "model_refused": None,
        }
        if statuses[spec["id"]]["status"] == "NOT_SUPPORTED":
            record.update(status="NOT_SUPPORTED", reason=statuses[spec["id"]]["reason"])
        elif stopped or (budget and len(budget.records()) >= config.max_attempts):
            record.update(status="NOT_RUN", reason="authorization_or_api_stop")
        else:
            before = len(budget.records()) if budget else 0
            started = time.perf_counter()
            try:
                case = build_case(root, spec)
                provider = live or Replay(case)
                trial = run_loop(case, provider, group)
                messages = trial.pop("messages")
                trial.pop("output")
                trajectory = provider.redact(messages)
                trajectory_file = f"{number:03d}-{spec['id']}-{group}-r{repetition}.json"
                (output / trajectory_file).write_text(
                    json.dumps(trajectory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                trial["executed_calls"] = provider.redact(trial["executed_calls"])
                record.update(
                    trial,
                    status="COMPLETED",
                    trajectory_file=trajectory_file,
                    attack_type=case.spec.get(
                        "attack_type",
                        case.spec.get(
                            "variant", "password_change" if spec["kind"] == "attack" else "normal"
                        ),
                    ),
                    attack_goal=case.attack_goal,
                    attack_sha256=case.attack_hash,
                    limitations=case.limits,
                )
                failures = 0
            except Exception as exc:
                record.update(
                    status="NOT_RUN" if isinstance(exc, BudgetExhausted) else "ERROR",
                    reason=type(exc).__name__,
                )
                failures = failures + 1 if isinstance(exc, LiveFailure) else failures
                stopped = isinstance(exc, BudgetExhausted) or failures >= 2
            record["latency_ms"] = (time.perf_counter() - started) * 1000
            attempts = budget.records()[before:] if budget else []
            record["api_attempts"] = [a["attempt"] for a in attempts]
            if attempts and all(
                all(
                    type(a.get("usage", {}).get(k)) is int
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                )
                for a in attempts
            ):
                record["usage"] = {
                    k: sum(a["usage"][k] for a in attempts)
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
            else:
                record["usage"] = None
            record["cost"] = None
            if attempts and attempts[-1].get("http_status") in {401, 403}:
                stopped = True
        rows.append(record)
        with (output / "raw.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        if budget:
            (output / "api-attempts.json").write_text(
                json.dumps(budget.records(), indent=2) + "\n", encoding="utf-8"
            )
        print(
            f"{number + 1}/{len(schedule(config))} {spec['id']}/{group}/r{repetition}: "
            f"{record['status']}; attempts={len(budget.records()) if budget else 0}",
            flush=True,
        )
    from agentguard_bench.statistics import export

    export(output, rows, seed=config.seed)
    print(
        json.dumps({"output": str(output.relative_to(root)), "records": len(rows), "mode": mode}),
        flush=True,
    )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--mode", choices=["preflight", "replay", "real"], default="preflight")
    parser.add_argument("--enable-real-api", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    if not (root / "AGENTS.md").is_file():
        parser.error("Run from repository root")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    config = load_config(root, args.config)
    for benchmark in {s["benchmark"] for s in config.cases}:
        source(root, benchmark)
    execute(root, config, mode=args.mode, enable_real=args.enable_real_api)


if __name__ == "__main__":
    main()
