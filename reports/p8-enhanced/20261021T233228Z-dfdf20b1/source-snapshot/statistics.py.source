"""Explicit denominators, Wilson intervals and paired case-cluster bootstrap."""

import csv
import json
import math
import random
from collections import defaultdict

INTERVENTIONS = {"BLOCK", "REVIEW", "SANITIZE"}


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * q
    low = math.floor(position)
    return values[low] + (values[math.ceil(position)] - values[low]) * (position - low)


def rate(successes, total):
    if not 0 <= successes <= total:
        raise ValueError("Invalid binomial counts")
    if not total:
        return {
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "wilson95_low": None,
            "wilson95_high": None,
        }
    z, p = 1.959963984540054, successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {
        "numerator": successes,
        "denominator": total,
        "value": p,
        "wilson95_low": max(0.0, center - radius),
        "wilson95_high": min(1.0, center + radius),
    }


def intervened(row, gate=None):
    return any(
        a["action"] in INTERVENTIONS and (gate is None or a["gate"] == gate)
        for a in row.get("audit", [])
    )


def paired_delta(rows, group, field, *, seed=20261022, draws=1000):
    matched = defaultdict(dict)
    for row in rows:
        if row.get("status") == "COMPLETED" and type(row.get(field)) is bool:
            matched[(row["case_id"], row["repetition"])][row["group"]] = row[field]
    clusters = defaultdict(list)
    for (case, _), values in matched.items():
        if "G0" in values and group in values:
            clusters[case].append(int(values[group]) - int(values["G0"]))
    values = [sum(v) / len(v) for v in clusters.values()]
    if not values:
        return {
            "group": group,
            "field": field,
            "matched_unique_cases": 0,
            "delta": None,
            "cluster_bootstrap95_low": None,
            "cluster_bootstrap95_high": None,
        }
    rng = random.Random(seed)
    samples = [sum(rng.choices(values, k=len(values))) / len(values) for _ in range(draws)]
    return {
        "group": group,
        "field": field,
        "matched_unique_cases": len(values),
        "delta": sum(values) / len(values),
        "cluster_bootstrap95_low": percentile(samples, 0.025),
        "cluster_bootstrap95_high": percentile(samples, 0.975),
        "bootstrap_draws": draws,
    }


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["mode"], row["benchmark"], row["group"])].append(row)
    result = []
    for (mode, benchmark, group), trials in sorted(groups.items()):
        valid = [r for r in trials if r["status"] == "COMPLETED"]
        attacks = [
            r for r in valid if r["kind"] == "attack" and type(r.get("attack_success")) is bool
        ]
        normal = [r for r in valid if r["kind"] == "normal" and type(r.get("task_success")) is bool]
        metric = {
            "asr": rate(sum(r["attack_success"] for r in attacks), len(attacks)),
            "attack_block_rate": rate(
                sum(intervened(r) and not r["attack_success"] for r in attacks), len(attacks)
            ),
            "normal_task_success": rate(sum(r["task_success"] for r in normal), len(normal)),
            "false_positive_rate": rate(sum(intervened(r) for r in normal), len(normal)),
            "official_selection_rate": rate(
                sum(r.get("official_selection_success") is True for r in valid),
                sum(type(r.get("official_selection_success")) is bool for r in valid),
            ),
            "attacker_tool_execution_rate": rate(
                sum(r.get("attacker_tool_executed") is True for r in valid),
                sum(type(r.get("attacker_tool_executed")) is bool for r in valid),
            ),
        }
        delays = [r["latency_ms"] for r in valid if r.get("latency_ms") is not None]
        checks = [v for r in valid for v in r.get("check_latencies_ms", [])]
        usage = [r.get("usage") for r in valid]
        known = [u for u in usage if u is not None]
        result.append(
            {
                "mode": mode,
                "benchmark": benchmark,
                "group": group,
                "planned_trials": len(trials),
                "completed_trials": len(valid),
                "unique_cases": len({r["case_id"] for r in valid}),
                "normal_unique_cases": len({r["case_id"] for r in normal}),
                "attack_unique_cases": len({r["case_id"] for r in attacks}),
                "statuses": {
                    s: sum(r["status"] == s for r in trials)
                    for s in ("COMPLETED", "NOT_SUPPORTED", "NOT_RUN", "ERROR")
                },
                **metric,
                "gate_interventions": {
                    g: {
                        **rate(sum(intervened(r, g) for r in valid), len(valid)),
                        "decision_count": sum(
                            a["gate"] == g and a["action"] in INTERVENTIONS
                            for r in valid
                            for a in r.get("audit", [])
                        ),
                    }
                    for g in ("gate0", "gate1", "gate2", "basic_rules")
                },
                "latency_ms_p50": percentile(delays, 0.5),
                "latency_ms_p95": percentile(delays, 0.95),
                "guard_overhead_ms_p50": percentile(checks, 0.5),
                "guard_overhead_ms_p95": percentile(checks, 0.95),
                "guard_overhead_samples": len(checks),
                "usage_known_trials": len(known),
                "usage_unknown_trials": len(usage) - len(known),
                "tokens_known_subtotal": {
                    k: sum(u[k] for u in known)
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
                if known
                else None,
                "model_refused": rate(
                    sum(r.get("model_refused") is True for r in valid),
                    sum(type(r.get("model_refused")) is bool for r in valid),
                ),
                "cost": None,
            }
        )
    return result


def csv_write(path, rows):
    keys = sorted({k for row in rows for k in row})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: json.dumps(v, ensure_ascii=False) if isinstance(v, dict | list) else v
                    for k, v in row.items()
                }
            )


def export(output, rows, *, seed):
    # Raw JSONL remains authoritative; derived files can be regenerated without API calls.
    summaries = summarize(rows)
    deltas, by_type = [], []
    for mode, benchmark in sorted({(r["mode"], r["benchmark"]) for r in rows}):
        subset = [r for r in rows if r["mode"] == mode and r["benchmark"] == benchmark]
        for group in sorted({r["group"] for r in subset} - {"G0"}):
            for field in ("attack_success", "task_success"):
                deltas.append(
                    {
                        "mode": mode,
                        "benchmark": benchmark,
                        **paired_delta(subset, group, field, seed=seed),
                    }
                )
        for kind in sorted(
            {r.get("attack_type", "unknown") for r in subset if r["kind"] == "attack"}
        ):
            for group in sorted({r["group"] for r in subset}):
                matching = [
                    r
                    for r in subset
                    if r["group"] == group
                    and r.get("attack_type") == kind
                    and r["status"] == "COMPLETED"
                    and type(r.get("attack_success")) is bool
                ]
                by_type.append(
                    {
                        "mode": mode,
                        "benchmark": benchmark,
                        "group": group,
                        "attack_type": kind,
                        **rate(sum(r["attack_success"] for r in matching), len(matching)),
                    }
                )
    payload = {
        "summary": summaries,
        "paired_deltas": deltas,
        "attack_types": by_type,
        "interval_warning": (
            "Wilson intervals treat trials as independent; repeated cases are correlated. "
            "Paired delta intervals cluster on case ID. Tiny samples may give degenerate intervals."
        ),
        "cost_reason": "No independently verified price snapshot; cost is unknown, never zero",
    }
    (output / "summary.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    csv_write(output / "raw.csv", rows)
    csv_write(output / "summary.csv", summaries)
    csv_write(output / "paired-deltas.csv", deltas)
    csv_write(output / "attack-types.csv", by_type)
    text = [
        "# Experiment subset results",
        "",
        "Official subsets, not native scores. Small n: disclose uncertainty/denominators.",
        "",
        "| mode | benchmark | group | ASR | normal success | FPR |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in summaries:

        def cell(name, row=row):
            m = row[name]
            return (
                f"{m['numerator']}/{m['denominator']} ({m['value']:.1%})"
                if m["denominator"]
                else "NOT_SUPPORTED / no judged samples"
            )

        text.append(
            f"| {row['mode']} | {row['benchmark']} | {row['group']} | {cell('asr')} | "
            f"{cell('normal_task_success')} | {cell('false_positive_rate')} |"
        )
    (output / "summary.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    return payload
