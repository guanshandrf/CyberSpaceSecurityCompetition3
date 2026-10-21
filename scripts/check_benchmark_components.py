"""OFFLINE official-component integration probes; NOT model/benchmark performance results."""

import json
from pathlib import Path

from agentguard_bench.components import RUNNERS

from agentguard.detectors import Redactor


class FixtureProvider:
    provider_id = "offline-fixture-NOT-real-model"
    last_usage = None

    def redact(self, value):
        return Redactor().redact(value)

    def complete(self, messages, *, tools):
        names = [t["function"]["name"] for t in tools]
        if names[0] == "get_most_recent_transactions":
            if messages[-1]["role"] == "tool":
                return {"role": "assistant", "content": "You spent 200 on the gift."}
            name, args = names[0], {"n": 100}
        elif names[0] == "transfer_to_human_agents":
            if messages[-1]["role"] == "tool":
                return {"role": "assistant", "content": "Transferred to a human."}
            name, args = names[0], {"summary": "The task needs a human representative."}
        elif names[0] == "Paper_Search":
            name, args = (
                "write_file",
                {"path": "/sandbox/output/probe.txt", "content": "0123456789"},
            )
        else:
            selected = tools[-1]["function"]
            name = selected["name"]
            properties = selected["parameters"]["properties"]
            args = {
                k: {"boolean": True, "integer": 1, "number": 1.0}.get(v["type"], "fixture")
                for k, v in properties.items()
                if k in selected["parameters"]["required"]
            }
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "fixture.call",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ],
        }


def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / ".cache/p8-component-smoke"
    directory.mkdir(exist_ok=True)
    results = []
    for name, runner in RUNNERS.items():
        for mode in ("baseline", "full"):
            try:
                options = (
                    {"run_directory": directory / (name + "-" + mode)} if name == "msb" else {}
                )
                result = runner(root, FixtureProvider(), mode=mode, **options)
                assert result["official_judge"]
                if name == "agentdojo":
                    assert result["task_success"] is True
                if mode == "full" and name == "injecagent":
                    assert result["attack_effect_executed"] is False
                results.append(
                    {
                        "benchmark": name,
                        "mode": mode,
                        "component_probe": "PASS",
                        "provider": "offline fixture; NOT performance measurement",
                    }
                )
                print(name, mode, "component probe PASS", flush=True)
            except Exception as exc:
                results.append(
                    {
                        "benchmark": name,
                        "mode": mode,
                        "component_probe": "FAIL",
                        "error_type": type(exc).__name__,
                    }
                )
                print(name, mode, "component probe FAIL", type(exc).__name__, flush=True)
    report = {
        "conclusion": "PASS" if all(r["component_probe"] == "PASS" for r in results) else "FAIL",
        "scope": "offline component integration; NOT benchmark/API results",
        "probes": results,
    }
    (root / "reports/generated/P8-component-smoke.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if report["conclusion"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
