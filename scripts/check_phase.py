"""Run authorized phase checks and record real subprocess/JUnit results."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "generated"


def offline_environment() -> dict[str, str]:
    """Do not pass provider credentials or implicit pytest plugins to checks."""
    temporary = ROOT / ".cache" / "phase-temp"
    temporary.mkdir(parents=True, exist_ok=True)
    env = {
        name: value
        for name, value in os.environ.items()
        if not any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
        and name not in {"PYTEST_ADDOPTS", "PYTHONPATH"}
    }
    env.update(
        PYTHONUTF8="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        AGENTGUARD_LLM_PROVIDER="fake",
        AGENTGUARD_ENABLE_REAL_API="false",
        AGENTGUARD_ENABLE_BENCHMARKS="false",
        AGENTGUARD_ENABLE_BASELINE="false",
        AGENTGUARD_ENABLE_PROTECTION="false",
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
        npm_config_offline="true",
        npm_config_audit="false",
        npm_config_fund="false",
        npm_config_cache=str(ROOT / ".cache" / "npm"),
        TEMP=str(temporary),
        TMP=str(temporary),
    )
    return env


def run_step(name: str, command: list[str], cwd: Path, env: dict[str, str], phase="P0") -> dict:
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            check=False,
        )
        code, output = process.returncode, process.stdout + process.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, output = 1, f"{type(exc).__name__}: check could not complete"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    log = OUTPUT / f"{phase}-{name}.log"
    log.write_text(output, encoding="utf-8")
    print(f"{name}: {'PASS' if code == 0 else 'FAIL'}", flush=True)
    return {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "returncode": code,
        "duration_seconds": round(time.monotonic() - started, 3),
        "log": str(log.relative_to(ROOT)),
    }


def junit_counts(path: Path) -> dict[str, int]:
    cases = ET.parse(path).getroot().findall(".//testcase")
    if not cases:
        raise ValueError("JUnit report contains no test cases")
    failed = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    return {
        "passed": len(cases) - failed - errors - skipped,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "total": len(cases),
    }


def conclusion(steps: list[dict], counts: dict[str, dict]) -> str:
    if any(step["returncode"] for step in steps):
        return "FAIL"
    if any(count["failed"] or count["errors"] for count in counts.values()):
        return "FAIL"
    if len(counts) != 2 or any(count["skipped"] for count in counts.values()):
        return "PARTIAL"
    return "PASS"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"],
        help="Implemented: P0鈥揚8",
    )
    args = parser.parse_args(argv)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    junit = {
        "python": OUTPUT / f"{args.phase}-python-junit.xml",
        "web": OUTPUT / f"{args.phase}-web-junit.xml",
    }
    # Never treat an earlier successful test report as evidence for this run.
    for report in [*junit.values(), OUTPUT / f"{args.phase}-results.json"]:
        report.unlink(missing_ok=True)
    env = offline_environment()
    env["AGENTGUARD_CHECK_PHASE"] = args.phase
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or "npm"
    steps_to_run = [
        ("dependencies", [sys.executable, "-m", "pip", "check"], ROOT),
        ("lint", [sys.executable, "-m", "ruff", "check", "."], ROOT),
        ("format", [sys.executable, "-m", "ruff", "format", "--check", "."], ROOT),
        (
            "python-tests",
            [
                sys.executable,
                "-m",
                "pytest",
                "-m",
                {
                    "P0": "p0",
                    "P1": "p0 or p1",
                    "P2": "p0 or p1 or p2",
                    "P3": "p0 or p1 or p2 or p3",
                    "P4": "p0 or p1 or p2 or p3 or p4",
                    "P5": "p0 or p1 or p2 or p3 or p4 or p5",
                    "P6": "p0 or p1 or p2 or p3 or p4 or p5 or p6",
                    "P7": "p0 or p1 or p2 or p3 or p4 or p5 or p6 or p7",
                    "P8": "p0 or p1 or p2 or p3 or p4 or p5 or p6 or p7 or p8",
                    "P9": "p0 or p1 or p2 or p3 or p4 or p5 or p6 or p7 or p8 or p9",
                }[args.phase],
                f"--basetemp=.cache/pytest-{args.phase}",
                f"--junitxml={junit['python']}",
            ],
            ROOT,
        ),
        ("web-tests", [npm, "run", "test"], ROOT / "apps" / "web"),
        ("web-build", [npm, "run", "build"], ROOT / "apps" / "web"),
    ]
    steps = [run_step(name, command, cwd, env, args.phase) for name, command, cwd in steps_to_run]
    counts, report_errors = {}, []
    for name, path in junit.items():
        try:
            counts[name] = junit_counts(path)
        except (OSError, ET.ParseError, ValueError) as exc:
            report_errors.append(f"{name}: {type(exc).__name__}")
    status = conclusion(steps, counts)
    if report_errors:
        status = "FAIL"
    result = {
        "phase": args.phase,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "steps": steps,
        "tests": counts,
        "report_errors": report_errors,
        "external_runs": {"deepseek": "NOT_RUN", "benchmarks": "NOT_RUN"},
        "conclusion": status,
    }
    destination = OUTPUT / f"{args.phase}-results.json"
    destination.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"{status}: {destination}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
