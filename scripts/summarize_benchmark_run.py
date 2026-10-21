"""Derive per-trial usage from the original API ledger and logged attempt boundaries.

Preserves the raw real-run file, whose usage field originally captured only the
last response. Does not make additional API calls or alter original judgements.
"""

import json
import re
from pathlib import Path

from agentguard_bench.records import write_results


def main():
    root = Path(__file__).resolve().parents[1]
    status = json.loads((root / "reports/generated/P8-real-status.json").read_text())
    directory = root / status["output"]
    if not directory.resolve().is_relative_to(root / "reports/generated"):
        raise ValueError("Invalid run directory")
    original = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    requests = json.loads((directory / "api-attempts.json").read_text())
    boundaries = re.findall(
        r"^(\w+)/(\w+): completed; attempts=(\d+)/20$",
        (root / "reports/generated/P8-real-run.log").read_text(),
        re.M,
    )
    if len(boundaries) != len(original["records"]):
        raise ValueError("Cannot reconstruct incomplete/mismatched run boundaries")
    rows, previous = [], 0
    for row, (benchmark, mode, end) in zip(original["records"], boundaries, strict=True):
        assert (row["benchmark"], row["mode"]) == (benchmark, mode)
        end = int(end)
        actual = requests[previous:end]
        assert actual and all(a["status"] == "completed" for a in actual)
        rows.append(
            {
                **row,
                "last_response_usage_original": row.get("usage"),
                "usage": {
                    k: sum(a["usage"][k] for a in actual)
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                },
                "api_attempt_ids": [a["attempt"] for a in actual],
                "usage_scope": "derived from original ledger and logged trial boundaries",
            }
        )
        previous = end
    assert previous == len(requests)
    write_results(directory / "results-derived.json", rows)
    totals = {
        k: sum(a["usage"][k] for a in requests)
        for k in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    result = {
        "attempts": len(requests),
        "total_usage": totals,
        "raw_results_preserved": True,
        "original_judgements_unchanged": True,
        "derived_results": str((directory / "results-derived.json").relative_to(root)),
        "cost": None,
        "cost_reason": "verified provider pricing snapshot unavailable",
    }
    (root / "reports/generated/P8-usage-derived.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
