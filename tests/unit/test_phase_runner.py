import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.p0
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("phase_runner", ROOT / "scripts" / "check_phase.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_runner_preserves_actual_failing_subprocess_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "OUTPUT", tmp_path)
    step = runner.run_step(
        "failure-probe",
        [sys.executable, "-c", "raise SystemExit(7)"],
        tmp_path,
        runner.offline_environment(),
    )
    assert step["returncode"] == 7
    assert runner.conclusion([step], {}) == "FAIL"


def test_runner_records_missing_executable_as_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "OUTPUT", tmp_path)
    step = runner.run_step(
        "missing", [str(tmp_path / "nonexistent")], tmp_path, runner.offline_environment()
    )
    assert step["returncode"] != 0
    assert "check could not complete" in (tmp_path / "P0-missing.log").read_text()


def test_junit_parser_counts_pass_fail_error_and_skip(tmp_path):
    # Synthetic parser fixture, not project acceptance or real API results.
    report = tmp_path / "counts.xml"
    report.write_text(
        "<testsuites><testsuite><testcase/><testcase><failure/></testcase>"
        "<testcase><error/></testcase><testcase><skipped/></testcase>"
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    assert runner.junit_counts(report) == {
        "passed": 1,
        "failed": 1,
        "errors": 1,
        "skipped": 1,
        "total": 4,
    }


def test_junit_parser_rejects_empty_report(tmp_path):
    report = tmp_path / "empty.xml"
    report.write_text("<testsuites/>", encoding="utf-8")
    with pytest.raises(ValueError, match="no test cases"):
        runner.junit_counts(report)


@pytest.mark.parametrize("status", ["PASS", "FAIL", "PARTIAL"])
def test_summary_does_not_report_skipped_or_failed_tests_as_pass(status):
    count = {"passed": 1, "failed": 0, "errors": 0, "skipped": 0, "total": 1}
    if status == "FAIL":
        count.update(passed=0, failed=1)
    if status == "PARTIAL":
        count.update(passed=0, skipped=1)
    assert runner.conclusion([{"returncode": 0}], {"python": count, "web": count}) == status


def test_runner_removes_credentials_and_user_pytest_overrides(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-test-secret")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")
    monkeypatch.setenv("PYTHONPATH", "untrusted")
    env = runner.offline_environment()
    assert "DEEPSEEK_API_KEY" not in env
    assert "PYTEST_ADDOPTS" not in env
    assert "PYTHONPATH" not in env
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert env["npm_config_offline"] == "true"
    assert Path(env["TEMP"]).is_relative_to(ROOT)
    assert env["TMP"] == env["TEMP"]


def test_unauthorized_phase_is_rejected_without_running_checks():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_phase.py"), "P10"],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
