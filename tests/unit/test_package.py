import importlib
import os
import tomllib
from importlib.metadata import metadata, version
from pathlib import Path

import pytest
from packaging.requirements import Requirement

pytestmark = pytest.mark.p0
ROOT = Path(__file__).resolve().parents[2]


def test_installed_package_metadata_matches_version():
    import agentguard

    assert agentguard.__version__ == version("agentguard") == "0.0.0"
    assert agentguard.__all__ == ["__version__"]
    assert "security enforcement" in metadata("agentguard")["Summary"]


@pytest.mark.parametrize(
    "module",
    ["contracts", "core", "gates", "detectors", "policies", "executor", "adapters", "audit"],
)
def test_reserved_modules_import_without_runtime_implementations(module):
    loaded = importlib.import_module(f"agentguard.{module}")
    assert not [name for name in vars(loaded) if not name.startswith("_")]


def test_sdk_dependency_metadata_has_only_pydantic_at_runtime():
    dependencies = [Requirement(item) for item in metadata("agentguard").get_all("Requires-Dist")]
    runtime = [item.name for item in dependencies if item.marker is None]
    assert runtime == ["pydantic"]
    assert version("pydantic").split(".")[0] == "2"


def test_dev_lock_matches_declared_direct_and_build_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    locked = {}
    for line in (ROOT / "requirements-dev.lock").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            requirement = Requirement(line)
            assert len(requirement.specifier) == 1
            assert next(iter(requirement.specifier)).operator == "=="
            locked[requirement.name] = str(requirement.specifier)
            if requirement.marker is None or requirement.marker.evaluate():
                assert requirement.specifier.contains(version(requirement.name))
    declared = (
        project["project"]["dependencies"]
        + project["project"]["optional-dependencies"]["dev"]
        + project["build-system"]["requires"]
    )
    for text in declared:
        requirement = Requirement(text)
        assert locked[requirement.name] == str(requirement.specifier)


def test_p0_runs_without_api_key_or_real_provider():
    assert "DEEPSEEK_API_KEY" not in os.environ
    assert os.environ["AGENTGUARD_LLM_PROVIDER"] == "fake"
    assert os.environ["AGENTGUARD_ENABLE_REAL_API"] == "false"
