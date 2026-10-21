"""Run the explicitly authorized, bounded real API component evaluation."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agentguard_bench.components import run_trial
from agentguard_bench.live import DeepSeek, LiveBudget, LiveFailure
from agentguard_bench.records import write_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-real-api", action="store_true", required=True)
    parser.add_argument("--enable-benchmarks", action="store_true", required=True)
    args = parser.parse_args()
    if not args.enable_real_api or not args.enable_benchmarks:
        parser.error("Both explicit opt-ins are required")
    root = Path(__file__).resolve().parents[1]
    directory = root / ".cache" / "p8-live"
    directory.mkdir(parents=True, exist_ok=True)
    budget = LiveBudget(directory)
    try:
        provider = DeepSeek(root=root, budget=budget, enabled=True)
    except LiveFailure:
        print("Real experiment not started: local credential unavailable")
        return 2
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    output = root / "reports" / "generated" / ("P8-real-" + run_id)
    output.mkdir()
    # Selection fixed before model results. Prioritize one pair from each benchmark.
    schedule = [
        ("injecagent", "baseline", {"index": 0}),
        ("injecagent", "full", {"index": 0}),
        ("agentdojo", "baseline", {"attack": False}),
        ("agentdojo", "full", {"attack": False}),
        ("msb", "baseline", {}),
        ("msb", "full", {}),
        ("tau3", "baseline", {}),
        ("tau3", "full", {}),
        ("agentdojo", "baseline", {"attack": True}),
        ("agentdojo", "full", {"attack": True}),
        ("injecagent", "without_gate1", {"index": 0}),
        ("injecagent", "without_gate2", {"index": 0}),
    ]
    rows = []
    consecutive_api_failures = 0
    for i, (benchmark, mode, options) in enumerate(schedule):
        if len(budget.records()) >= 20:
            break
        trial_dir = output / f"{i:02d}-{benchmark}-{mode}"
        if benchmark == "msb":
            options["run_directory"] = trial_dir / "original-metric-input"
        row = run_trial(root, provider, benchmark, mode, directory=trial_dir, **options)
        row.update(run_id=run_id, temperature=0, max_output_tokens=256, repetitions=1, seed=None)
        rows.append(row)
        write_results(output / "results.json", rows)
        outcome = "ERROR " + row["error"] if row.get("error") else "completed"
        print(f"{benchmark}/{mode}: {outcome}; attempts={len(budget.records())}/20", flush=True)
        consecutive_api_failures = (
            consecutive_api_failures + 1 if row.get("error") == "LiveFailure" else 0
        )
        last_attempt = budget.records()[-1] if budget.records() else {}
        if last_attempt.get("http_status") in {401, 403} or consecutive_api_failures >= 2:
            print("Stopped real requests after authentication/repeated API failure", flush=True)
            break
    (output / "api-attempts.json").write_text(
        json.dumps(budget.records(), indent=2) + "\n", encoding="utf-8"
    )
    complete = len(rows) == len(schedule) and all(not row.get("error") for row in rows)
    status = {
        "run_id": run_id,
        "conclusion": "PASS" if complete else "PARTIAL",
        "scope": "fixed official component/case subset, NOT full upstream CLI benchmarks",
        "output": str(output.relative_to(root)),
        "attempts_used_total": len(budget.records()),
        "authorization_limit": 20,
        "max_output_tokens": 256,
        "native_framework_scores": "NOT_RUN",
        "full_tau_reward": "NOT_RUN",
    }
    (root / "reports/generated/P8-real-status.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(status), flush=True)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
