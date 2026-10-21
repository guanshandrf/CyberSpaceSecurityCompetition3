"""Offline synthetic-tool latency and safety probe, never a Benchmark score."""

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
from simple_agent import build_adapter  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=200)
    args = parser.parse_args()
    if not 20 <= args.calls <= 2000:
        parser.error("calls must be 20..2000")
    directory = ROOT / ".cache" / ("p9-stress-" + uuid4().hex)
    directory.mkdir(parents=True)
    measurements = []
    for workers in (1, 8):
        adapter, effects = build_adapter(directory, budget=args.calls)

        def invoke(i, adapter=adapter):
            start = time.perf_counter()
            reply = adapter.invoke(
                {
                    "name": "echo",
                    "arguments": {"text": "public probe"},
                    "tool_call_id": f"call.{i}",
                },
                trace_id=f"trace.{i}",
            )
            return reply.executed, (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(invoke, range(args.calls)))
        elapsed = time.perf_counter() - start
        assert sum(r[0] for r in results) == len(effects) == args.calls
        # Neither duplicate calls nor a fresh over-budget ID can execute.
        assert not invoke(0)[0] and not invoke(args.calls)[0]
        latency = sorted(r[1] for r in results)
        measurements.append(
            {
                "workers": workers,
                "calls": args.calls,
                "elapsed_seconds": elapsed,
                "throughput_per_second": args.calls / elapsed,
                "p50_ms": statistics.median(latency),
                "p95_ms": latency[int((len(latency) - 1) * 0.95)],
                "actual_effects": len(effects),
                "duplicate_and_budget_denied": True,
            }
        )
    # Raw baseline uses the same harmless echo body, without guard or SQLite.
    raw_effects = []

    def raw_echo(text):
        raw_effects.append(text)
        return {"echo": text}

    start = time.perf_counter()
    for _ in range(args.calls):
        raw_echo("public probe")
    raw_elapsed = time.perf_counter() - start
    report = {
        "status": "PASS",
        "scope": "offline_sdk_probe_not_benchmark",
        "raw_calls": len(raw_effects),
        "raw_elapsed_seconds": raw_elapsed,
        "measurements": measurements,
        "api_requests": 0,
        "limitations": "Single Windows host; short echo body; SQLite included; no production SLA",
    }
    output = ROOT / "reports" / "generated" / "P9-stress.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
