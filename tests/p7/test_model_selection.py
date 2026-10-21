"""Offline model-selection tests: HTTP transport is synthetic, never real DeepSeek."""

import json

import pytest

pytestmark = pytest.mark.p7


@pytest.fixture
def selection_case(tmp_path, monkeypatch):
    import httpx
    from agentguard_demo import api
    from agentguard_demo.providers import make_provider
    from agentguard_demo.settings import DemoSettings
    from fastapi.testclient import TestClient

    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Synthetic DeepSeek transport reply",
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(
        api, "make_provider", lambda settings: make_provider(settings, http_client=client)
    )

    def make(**changes):
        settings = DemoSettings(
            **{
                "enable_protection": True,
                "enable_model_selection": True,
                "enable_real_api": True,
                "api_key": "synthetic-model-selection-key",
                "sandbox_root": tmp_path / "sandbox",
                **changes,
            }
        )
        return TestClient(api.create_app(settings)), requests

    yield make
    client.close()


def test_model_catalog_is_safe_and_fake_and_deepseek_sessions_are_fixed(selection_case):
    client, requests = selection_case()
    with client:
        catalog = client.get("/models").json()
        assert catalog["selectable"] and catalog["default_provider"] == "fake"
        assert all(m["available"] for m in catalog["models"])
        assert "synthetic-model-selection-key" not in json.dumps(catalog)
        fake = client.post("/sessions", json={"provider": "fake"}).json()["session_id"]
        real = client.post("/sessions", json={"provider": "deepseek"}).json()["session_id"]
        assert not requests  # Selection and session creation never perform a paid call.
        for sid, expected in [
            (fake, "Fake 第 1 轮：hello"),
            (real, "Synthetic DeepSeek transport reply"),
        ]:
            events = client.post(f"/sessions/{sid}/chat", json={"message": "hello"}).json()[
                "events"
            ]
            assert next(e["data"]["content"] for e in events if e["event"] == "message") == expected
            assert events[-1]["data"]["ok"]
        assert len(requests) == 1 and requests[0]["max_tokens"] == 256
        assert client.get(f"/sessions/{fake}/history").json()["provider"] == "fake"
        assert client.get(f"/sessions/{real}/history").json()["provider"] == "deepseek"
        assert client.get("/health").json()["guard"] == "enabled"


@pytest.mark.parametrize("changes", [{"api_key": ""}, {"enable_real_api": False}])
def test_unconfigured_deepseek_is_disabled_and_cannot_be_forced(selection_case, changes):
    client, requests = selection_case(**changes)
    with client:
        assert client.get("/models").json()["models"][1] == {"id": "deepseek", "available": False}
        assert client.post("/sessions", json={"provider": "deepseek"}).status_code == 403
        assert not requests


def test_clients_cannot_enable_selection_or_supply_keys_permissions_or_endpoints(selection_case):
    client, requests = selection_case(enable_model_selection=False, enable_real_api=False)
    with client:
        assert client.post("/sessions", json={"provider": "deepseek"}).status_code == 403
        for body in [
            {"provider": "other-model"},
            {"provider": "fake", "api_key": "private input"},
            {"provider": "fake", "enable_protection": False},
            {"provider": "fake", "permissions": ["root"]},
            {"provider": "fake", "endpoint": "http://attacker.invalid"},
        ]:
            response = client.post("/sessions", json=body)
            assert response.status_code == 422 and "private input" not in response.text
        assert not requests


def test_all_models_and_new_sessions_share_budget(selection_case):
    client, requests = selection_case(max_total_provider_calls=1)
    with client:
        first = client.post("/sessions", json={"provider": "fake"}).json()["session_id"]
        client.post(f"/sessions/{first}/chat", json={"message": "hello"})
        second = client.post("/sessions", json={"provider": "deepseek"}).json()["session_id"]
        result = client.post(f"/sessions/{second}/chat", json={"message": "hello"}).json()["events"]
        assert result[-2]["data"]["code"] == "total_provider_call_limit" and not requests
        assert client.get("/models").json()["limits"]["used_calls"] == 1


def test_cross_origin_selection_and_chat_model_override_are_rejected(selection_case):
    client, requests = selection_case()
    with client:
        assert (
            client.post(
                "/sessions",
                json={"provider": "deepseek"},
                headers={"Origin": "https://attacker.invalid"},
            ).status_code
            == 403
        )
        sid = client.post("/sessions", json={"provider": "fake"}).json()["session_id"]
        assert (
            client.post(
                f"/sessions/{sid}/chat", json={"message": "hi", "provider": "deepseek"}
            ).status_code
            == 422
        )
        assert not requests


def test_model_selection_still_enforces_gate1_zero_effects(selection_case):
    client, requests = selection_case(guard_permissions=())
    with client:
        sid = client.post("/sessions", json={"provider": "fake"}).json()["session_id"]
        events = client.post(
            f"/sessions/{sid}/chat",
            json={"message": 'write_note {"name":"blocked.txt","content":"public"}'},
        ).json()["events"]
        assert any(
            e["event"] == "audit"
            and e["data"]["gate"] == "gate1"
            and e["data"]["execution"] == "not_executed"
            for e in events
        )
        assert not list(client.app.state.chat.settings.sandbox_root.rglob("blocked.txt"))
        assert not requests


def test_unprotected_model_selection_configuration_is_rejected():
    from agentguard_demo.settings import DemoSettings

    with pytest.raises(ValueError):
        DemoSettings(enable_baseline=True, enable_model_selection=True)
