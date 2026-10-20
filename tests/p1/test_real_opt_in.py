import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.p1
ROOT = Path(__file__).resolve().parents[2]


def test_real_api_smoke_cannot_run_without_explicit_flag():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_deepseek.py")],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2
    assert "--enable-real-api" in result.stderr
    assert '"http_responses"' not in result.stdout
