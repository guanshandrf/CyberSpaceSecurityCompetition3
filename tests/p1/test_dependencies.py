import ast
import os
import subprocess
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement

pytestmark = pytest.mark.p1
ROOT = Path(__file__).resolve().parents[2]


def test_demo_lock_matches_installed_and_direct_dependencies():
    locked = {}
    for filename in ["requirements-dev.lock", "requirements-demo.lock"]:
        for line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
            if line and not line.startswith(("#", "-r")):
                requirement = Requirement(line)
                locked[requirement.name] = str(requirement.specifier)
                if requirement.marker is None or requirement.marker.evaluate():
                    assert requirement.specifier.contains(version(requirement.name))
    project = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8"))
    for text in project["project"]["dependencies"]:
        requirement = Requirement(text)
        assert locked[requirement.name] == str(requirement.specifier)


def test_baseline_demo_does_not_depend_on_sdk_or_implement_guard(tmp_path):
    # P6 adds a lazy, optional integration module. Baseline remains independently
    # runnable; that module may only use the SDK's public integration surfaces.
    allowed = {
        "agentguard.adapters.langgraph",
        "agentguard.audit",
        "agentguard.contracts",
        "agentguard.detectors",  # P7 presentation reuses the public Redactor in protected.py only.
        "agentguard.policies",
    }
    for path in (ROOT / "apps/api/src/agentguard_demo").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != "agentguard" for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "agentguard":
                    assert path.name == "protected.py" and node.module in allowed
    code = """
import importlib.abc
import sys
from pathlib import Path
class DenySDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'agentguard':
            raise AssertionError('Baseline imported SDK')
sys.meta_path.insert(0, DenySDK())
from agentguard_demo.service import ChatService
from agentguard_demo.providers import make_provider
from agentguard_demo.settings import DemoSettings
settings = DemoSettings(enable_baseline=True, sandbox_root=Path('baseline'))
service = ChatService(settings, make_provider(settings))
session = service.create_session()
events = list(service.events(session, 'write_note {"name":"ok.txt","content":"offline"}'))
assert events[-1]['data']['ok']
assert (Path('baseline/notes') / session.session_id / 'ok.txt').read_text() == 'offline'
assert 'agentguard' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=tmp_path,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
