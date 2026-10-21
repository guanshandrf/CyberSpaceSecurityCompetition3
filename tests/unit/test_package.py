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

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert agentguard.__version__ == version("agentguard") == project["project"]["version"]
    assert agentguard.__all__ == ["__version__"]
    assert "security enforcement" in metadata("agentguard")["Summary"]


@pytest.mark.parametrize(
    "module",
    ["contracts", "core", "gates", "detectors", "policies", "executor", "adapters", "audit"],
)
def test_modules_expose_only_authorized_phase_implementations(module):
    loaded = importlib.import_module(f"agentguard.{module}")
    public = {name for name in vars(loaded) if not name.startswith("_")}
    if module == "contracts":
        assert {
            "SecurityEvent",
            "SecurityContext",
            "SecurityDecision",
            "Detector",
            "Policy",
            "Gate",
        } <= public
        assert not {"GuardedExecutor", "PolicyEngine"}.intersection(public)
    elif module in {"gates", "policies", "executor", "audit", "detectors"}:
        expected = {
            "gates": {"Gate0", "Gate1", "Gate2"},
            "policies": {"ToolBinding", "PathRule", "PolicyEngine"},
            "executor": {"GuardedExecutor", "ExecutionResult", "ResultHandler", "HandledResult"},
            "audit": {"SQLiteAudit"},
            "detectors": {"Redactor", "RuleResultDetector", "RegistrationDetector"},
        }
        assert set(loaded.__all__) == expected[module]
        assert expected[module] <= public
        assert not {"LangGraphAdapter"}.intersection(public)
    elif module == "adapters":
        # P6 may have explicitly imported the optional submodule earlier in this
        # process. Isolated import tests still forbid any eager framework imports.
        assert public <= {"langgraph"}
        if "langgraph" in public:
            assert loaded.langgraph.__name__ == "agentguard.adapters.langgraph"
    else:
        assert not public


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
