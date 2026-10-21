"""Pinned upstream source access. Component imports are NOT full upstream CLI runs."""

import importlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

PINS = {
    "agentdojo": ("ethz-spylab/agentdojo", "089ed468cf3ed0322acc66b0211f26d9d90dbf60"),
    "injecagent": ("uiuc-kang-lab/InjecAgent", "f19c9f2c79a41046eb13c03c51a24c567a8ffa07"),
    "msb": ("dongsenzhang/MSB", "c1d6a70171e4d2c44c87a2ae909d13df00c6aa8d"),
    "tau3": ("sierra-research/tau2-bench", "fc0055dc4e0a316c3f83133267fbd6faaa770992"),
}


def source(root, benchmark):
    if benchmark not in PINS:
        raise ValueError("Unsupported benchmark")
    root = Path(root)
    path = root / ".cache" / "p8-checkouts" / benchmark
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.is_symlink() or getattr(current.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked upstream source rejected")
    head = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != PINS[benchmark][1]:
        raise ValueError("Unpinned upstream version")
    clean = subprocess.run(["git", "-C", str(path), "diff", "--quiet", "HEAD"], cwd=root)
    if clean.returncode:
        raise ValueError("Modified upstream source")
    return path


def namespace(name, directory):
    """Skip eager provider/runner __init__ imports, never substitute implementation/judges."""
    if name in sys.modules:
        if list(getattr(sys.modules[name], "__path__", [])) != [str(directory)]:
            raise ValueError("Conflicting upstream module")
        return
    module = types.ModuleType(name)
    module.__path__ = [str(directory)]
    module.__package__ = name
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    module.__spec__.submodule_search_locations = module.__path__
    sys.modules[name] = module


def component_import(root, benchmark):
    path = source(root, benchmark)
    # Upstream tau2.utils otherwise calls load_dotenv() with parent discovery.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    if benchmark == "agentdojo":
        prefix = path / "src" / "agentdojo"
        packages = (
            "",
            "agent_pipeline",
            "agent_pipeline.llms",
            "task_suite",
            "default_suites",
            "default_suites.v1",
            "default_suites.v1.banking",
            "default_suites.v1.tools",
        )
        for suffix in packages:
            namespace(
                "agentdojo" + ("." + suffix if suffix else ""),
                prefix.joinpath(*suffix.split(".")) if suffix else prefix,
            )
    elif benchmark == "tau3":
        prefix = path / "src" / "tau2"
        os.environ["TAU2_DATA_DIR"] = str(path / "data")
        for suffix in ("", "data_model", "environment", "evaluator", "domains", "domains.retail"):
            namespace(
                "tau2" + ("." + suffix if suffix else ""),
                prefix.joinpath(*suffix.split(".")) if suffix else prefix,
            )
    return path


def load_json(path):
    if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("Linked case file rejected")
    data = path.read_bytes()
    if len(data) > 32 * 1024 * 1024:
        raise ValueError("Oversized benchmark file")
    return json.loads(data)


def injecagent_judge(root):
    import ast

    path = source(root, "injecagent") / "src" / "output_parsing.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "evaluate_output_finetuned"
    )
    # The official finetuned judge is self-contained; no NLTK/provider imports or stubs.
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[node.name]
