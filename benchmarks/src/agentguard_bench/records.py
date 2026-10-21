"""Statistics preserve exclusions, unknown judgements and experiment provenance."""

import csv
import json
from collections import defaultdict
from statistics import median

BENCHMARKS = frozenset({"agentdojo", "injecagent", "msb", "tau3"})
MODES = frozenset({"baseline", "rules", "full", "without_gate0", "without_gate1", "without_gate2"})


def summarize(records):
    groups = defaultdict(list)
    for row in records:
        if row["benchmark"] not in BENCHMARKS or row["mode"] not in MODES:
            raise ValueError("Unsupported benchmark or mode")
        if row["scope"] not in {"official", "official_case_replay", "sdk_probe"}:
            raise ValueError("Experiment scope required")
        if row["scope"] == "official" and not row.get("official_judge"):
            raise ValueError("Official result requires original judge provenance")
        groups[(row["benchmark"], row["mode"], row["scope"])].append(row)
    result = []
    for (benchmark, mode, scope), rows in sorted(groups.items()):
        valid = [r for r in rows if r.get("error") is None]
        attacks = [
            r
            for r in valid
            if r.get("attack_success") in (True, False) and type(r.get("attack_success")) is bool
        ]
        normal = [
            r for r in valid if r.get("kind") == "normal" and type(r.get("task_success")) is bool
        ]
        result.append(
            {
                "benchmark": benchmark,
                "mode": mode,
                "scope": scope,
                "trials": len(rows),
                "excluded": len(rows) - len(valid),
                "attack_judged": len(attacks),
                "asr": sum(r["attack_success"] for r in attacks) / len(attacks)
                if attacks
                else None,
                "normal_judged": len(normal),
                "normal_success_rate": sum(r["task_success"] for r in normal) / len(normal)
                if normal
                else None,
                "guard_blocks": sum(r.get("guard_blocked") is True for r in valid),
                "model_refusal_judged": sum(type(r.get("model_refused")) is bool for r in valid),
                "model_refusals": sum(r.get("model_refused") is True for r in valid)
                if any(type(r.get("model_refused")) is bool for r in valid)
                else None,
                "median_latency_ms": median(
                    r["latency_ms"] for r in valid if r.get("latency_ms") is not None
                )
                if any(r.get("latency_ms") is not None for r in valid)
                else None,
                "cost": None,
            }
        )
    return result


def write_results(path, records):
    payload = {
        "records": records,
        "summary": summarize(records),
        "warning": "Scopes are separate: replay/probes are not official benchmark scores",
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    columns = [
        "benchmark",
        "upstream_commit",
        "run_id",
        "task_id",
        "attack_id",
        "mode",
        "scope",
        "provider",
        "kind",
        "attack_success",
        "task_success",
        "guard_blocked",
        "tool_execution_count",
        "latency_ms",
        "usage",
        "error",
        "official_judge",
    ]
    with path.with_suffix(".csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow(
                {
                    k: json.dumps(row.get(k), ensure_ascii=False)
                    if isinstance(row.get(k), dict | list)
                    else row.get(k)
                    for k in columns
                }
            )
