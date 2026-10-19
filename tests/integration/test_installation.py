import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.p0


def test_installed_sdk_imports_in_isolated_interpreter_without_web_or_agent_frameworks(tmp_path):
    # -I excludes cwd and PYTHONPATH. The package must really be installed.
    code = """
import importlib.abc
import importlib
import sys

forbidden = {'fastapi', 'starlette', 'langgraph', 'langchain', 'apps', 'benchmarks', 'vue'}
class DenyFrameworks(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in forbidden:
            raise AssertionError('SDK attempted a forbidden framework import')

sys.meta_path.insert(0, DenyFrameworks())
import agentguard
modules = ['contracts', 'core', 'gates', 'detectors', 'policies', 'executor', 'adapters', 'audit']
for name in modules:
    importlib.import_module('agentguard.' + name)
assert agentguard.__version__ == '0.0.0'
assert not forbidden.intersection(sys.modules)
print('isolated installed SDK import: OK')
"""
    process = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=tmp_path,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == "isolated installed SDK import: OK"
