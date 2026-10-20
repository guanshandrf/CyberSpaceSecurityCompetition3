import json

import pytest

pytestmark = pytest.mark.p1


def test_fake_defaults_do_not_need_credentials_or_create_http_client(monkeypatch):
    import httpx
    from agentguard_demo.providers import FakeChatModel, make_provider
    from agentguard_demo.settings import DemoSettings

    def unexpected(*args, **kwargs):
        raise AssertionError("Fake provider must not construct an HTTP client")

    monkeypatch.setattr(httpx, "Client", unexpected)
    settings = DemoSettings.from_env().model_copy(update={"enable_baseline": True})
    provider = make_provider(settings)
    assert isinstance(provider, FakeChatModel)
    assert provider.invoke("hello").content == "Fake 第 1 轮：hello"


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"enable_baseline": True, "provider": "deepseek"},
        {"enable_baseline": True, "provider": "deepseek", "enable_real_api": True},
        {"enable_baseline": True, "provider": "deepseek", "api_key": "synthetic-test-value"},
        {"enable_baseline": True, "provider": "fake", "enable_real_api": True},
    ],
)
def test_provider_configuration_rejects_missing_authorization(overrides):
    from agentguard_demo.providers import make_provider
    from agentguard_demo.settings import DemoSettings

    with pytest.raises(ValueError):
        make_provider(DemoSettings(**overrides))


def test_deepseek_protocol_uses_bounded_request_and_parses_tool_call_with_fake_transport(tmp_path):
    import httpx
    from agentguard_demo.providers import make_provider
    from agentguard_demo.settings import DemoSettings
    from agentguard_demo.tools import SandboxTools
    from langchain_core.messages import HumanMessage, ToolMessage

    requests = []

    def respond(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-test-value"
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "offline_call",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"sample.txt"}',
                        },
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": "offline final"}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    settings = DemoSettings(
        enable_baseline=True,
        provider="deepseek",
        enable_real_api=True,
        api_key="synthetic-test-value",
        max_tokens=32,
    )
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        provider = make_provider(settings, http_client=client)
        bound = provider.bind_tools(SandboxTools(tmp_path / "in", tmp_path / "notes").as_tools())
        first = bound.invoke([HumanMessage(content="read sample")])
        assert first.tool_calls[0]["args"] == {"path": "sample.txt"}
        final = bound.invoke(
            [
                HumanMessage(content="read sample"),
                first,
                ToolMessage(content="sample", tool_call_id="offline_call"),
            ]
        )
    assert final.content == "offline final"
    assert requests[0]["max_tokens"] == 32
    assert requests[0]["stream"] is False
    assert requests[0]["temperature"] == 0
    assert len(requests[0]["tools"]) == 2
    assert requests[1]["messages"][-1]["tool_call_id"] == "offline_call"
    assert "synthetic-test-value" not in repr(provider) + provider.model_dump_json() + repr(
        settings
    )


@pytest.mark.parametrize("response_kind", ["http_error", "malformed_json", "invalid_tool_args"])
def test_deepseek_errors_are_generic_and_never_retry(response_kind):
    import httpx
    from agentguard_demo.providers import make_provider
    from agentguard_demo.settings import DemoSettings

    calls = []

    def respond(request):
        calls.append(request)
        if response_kind == "http_error":
            return httpx.Response(429, text="synthetic-private-response")
        if response_kind == "malformed_json":
            return httpx.Response(200, text="synthetic-private-response")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "x",
                                    "function": {"name": "read_file", "arguments": "[]"},
                                }
                            ]
                        }
                    }
                ]
            },
        )

    settings = DemoSettings(
        enable_baseline=True,
        provider="deepseek",
        enable_real_api=True,
        api_key="synthetic-test-value",
    )
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(RuntimeError, match="^provider_request_failed$"):
            make_provider(settings, http_client=client).invoke("hello")
    assert len(calls) == 1


def test_environment_configuration_is_explicit_and_bounded(monkeypatch):
    from agentguard_demo.settings import DemoSettings

    monkeypatch.setenv("AGENTGUARD_ENABLE_BASELINE", "maybe")
    with pytest.raises(ValueError):
        DemoSettings.from_env()
    with pytest.raises(ValueError):
        DemoSettings(max_provider_calls=0)
    with pytest.raises(ValueError):
        DemoSettings(max_tokens=1025)
