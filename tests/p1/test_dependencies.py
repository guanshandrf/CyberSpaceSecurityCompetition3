import ast
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


def test_baseline_demo_does_not_depend_on_sdk_or_implement_guard():
    for path in (ROOT / "apps/api/src/agentguard_demo").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != "agentguard" for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] != "agentguard"
