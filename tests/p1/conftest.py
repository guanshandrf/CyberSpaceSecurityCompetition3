import pytest


@pytest.fixture
def demo_settings(tmp_path):
    from agentguard_demo.settings import DemoSettings

    return DemoSettings(enable_baseline=True, sandbox_root=tmp_path / "sandbox")


@pytest.fixture
def demo_client(demo_settings):
    from agentguard_demo.api import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(demo_settings)) as client:
        yield client
