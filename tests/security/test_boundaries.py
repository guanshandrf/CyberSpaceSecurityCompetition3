import ast
import socket
from pathlib import Path

import pytest

pytestmark = pytest.mark.p0
ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = {
    "apps",
    "benchmarks",
    "fastapi",
    "starlette",
    "langgraph",
    "langchain",
    "langchain_core",
    "vue",
}


def imports(source):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def violations(source):
    return [
        name
        for name in imports(source)
        if name.split(".")[0] in FORBIDDEN or name.startswith("agentguard.adapters")
    ]


def test_sdk_core_source_has_no_framework_or_demo_imports():
    for path in (ROOT / "src" / "agentguard").rglob("*.py"):
        if "adapters" not in path.relative_to(ROOT / "src" / "agentguard").parts:
            assert violations(path.read_text(encoding="utf-8")) == [], path.relative_to(ROOT)


@pytest.mark.parametrize(
    "source",
    [
        "import fastapi",
        "from langgraph.graph import StateGraph",
        "from apps.api import agent",
        "import benchmarks.adapter",
        "from agentguard.adapters import langgraph",
    ],
)
def test_boundary_checker_recognizes_forbidden_imports(source):
    assert violations(source)


def test_boundary_checker_allows_standard_library_and_sdk_contract_imports():
    assert violations("from pathlib import Path\nfrom agentguard import contracts") == []


@pytest.mark.parametrize("operation", ["dns", "connect", "connect_ex", "create_connection"])
def test_offline_test_guard_blocks_network(operation):
    with pytest.raises(RuntimeError, match="forbid network"):
        if operation == "dns":
            socket.getaddrinfo("example.invalid", 443)
        elif operation == "create_connection":
            socket.create_connection(("example.invalid", 443))
        else:
            with socket.socket() as connection:
                getattr(connection, operation)(("127.0.0.1", 1))


def test_sample_config_contains_no_credential_and_external_runs_are_disabled():
    config = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert config["DEEPSEEK_API_KEY"] == ""
    assert config["AGENTGUARD_LLM_PROVIDER"] == "fake"
    for name in ["REAL_API", "BENCHMARKS", "BASELINE"]:
        assert config[f"AGENTGUARD_ENABLE_{name}"] == "false"
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {".env", ".env.*", "!.env.example"}.issubset(ignore)
