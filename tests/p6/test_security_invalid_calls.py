import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.p6


@pytest.mark.parametrize(
    "change",
    [
        {"id": "invalid/id"},
        {"args": "{broken synthetic-private-parameter"},
        {"args": {"text": float("nan")}},
        {"context_ref": "admin"},
        {"type": "invalid_tool_call", "args": {"text": "synthetic-private-parameter"}},
    ],
)
def test_recoverable_invalid_call_has_matching_error_audit_and_zero_effects(
    adapter_case, framework_call, change, caplog
):
    adapter, calls, audit, _ = adapter_case()
    call = {**framework_call, **change}
    result = adapter.dispatch(call, trace_id="trace.invalid")
    assert result.status == "error" and result.tool_call_id == call["id"] and not calls
    assert json.loads(result.content) == {"error": "tool.not_executed"}
    records = audit.records()
    rejection = next(r for r in records if r["reason_codes"] == ["event.invalid"])
    assert (
        rejection["trace_id"] == hmac.new(audit._salt, b"trace.invalid", hashlib.sha256).hexdigest()
    )
    assert (
        rejection["tool_call_id"]
        == hmac.new(audit._salt, call["id"].encode(), hashlib.sha256).hexdigest()
    )
    assert "synthetic-private-parameter" not in result.content + json.dumps(records) + caplog.text


def test_strict_backend_invoke_still_raises_but_now_audits(adapter_case, framework_call):
    adapter, calls, audit, _ = adapter_case()
    with pytest.raises(ValueError, match="Invalid framework"):
        adapter.invoke({**framework_call, "args": "bad JSON"}, trace_id="trace.strict")
    assert audit.records()[-1]["reason_codes"] == ["event.invalid"] and not calls


@pytest.mark.parametrize("ids", [[None], ["same", "same"], ["\ud800"]])
def test_uncorrelatable_batch_is_rejected_before_any_handler(adapter_case, framework_call, ids):
    adapter, calls, audit, _ = adapter_case()
    batch = [{**framework_call, "id": call_id} for call_id in ids]
    with pytest.raises(ValueError, match="Invalid framework"):
        adapter.dispatch_many(batch, trace_id="trace.batch")
    assert not calls and audit.records()[-1]["reason_codes"] == ["event.invalid"]


def test_mixed_batch_returns_exactly_one_toolmessage_per_call(adapter_case, framework_call):
    adapter, calls, audit, _ = adapter_case()
    messages = adapter.dispatch_many(
        [framework_call, {**framework_call, "id": "call.bad", "args": "bad JSON"}],
        trace_id="trace.mixed",
    )
    assert [m.tool_call_id for m in messages] == ["call.1", "call.bad"]
    assert [m.status for m in messages] == ["success", "error"] and len(calls) == 1
    assert any(r["reason_codes"] == ["event.invalid"] for r in audit.records())


def test_parallel_invalid_calls_do_not_prevent_valid_execution_or_bypass_replay(
    adapter_case, framework_call
):
    adapter, calls, audit, _ = adapter_case()
    batch = [{**framework_call, "args": "bad JSON"}] * 6 + [framework_call] * 2
    with ThreadPoolExecutor(max_workers=8) as pool:
        messages = list(
            pool.map(lambda call: adapter.dispatch(call, trace_id="trace.concurrent"), batch)
        )
    assert len(calls) == 1 and sum(m.status == "success" for m in messages) == 1
    assert sum(r["reason_codes"] == ["event.invalid"] for r in audit.records()) == 6


def test_invalid_call_audit_failure_is_generic_and_zero_effects(adapter_case, framework_call):
    adapter, calls, _, _ = adapter_case()

    class BrokenAudit:
        def append(self, *args, **kwargs):
            raise RuntimeError("synthetic-private-error")

    adapter._audit = BrokenAudit()
    with pytest.raises(ValueError, match="Invalid framework") as error:
        adapter.dispatch({**framework_call, "args": "bad JSON"}, trace_id="trace.audit")
    assert "synthetic-private-error" not in str(error.value) and not calls


@pytest.mark.parametrize("missing_id", [False, True, "surrogate"])
def test_actual_langgraph_session_recovers_after_invalid_model_call(tmp_path, missing_id):
    from agentguard_demo.providers import FakeChatModel
    from agentguard_demo.service import ChatService
    from agentguard_demo.settings import DemoSettings
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class MalformedModel(FakeChatModel):
        def _generate(self, messages, *args, **kwargs):
            if messages[-1].content == "malformed":
                response = AIMessage(
                    content="",
                    invalid_tool_calls=[
                        {
                            "name": "write_note",
                            "args": "{synthetic-private-parameter",
                            "id": (
                                None
                                if missing_id is True
                                else "\ud800"
                                if missing_id == "surrogate"
                                else "bad/id"
                            ),
                            "error": "untrusted parser detail",
                            "type": "invalid_tool_call",
                        }
                    ],
                )
                return ChatResult(generations=[ChatGeneration(message=response)])
            return super()._generate(messages, *args, **kwargs)

    settings = DemoSettings(enable_protection=True, sandbox_root=tmp_path / "sandbox")
    service = ChatService(settings, MalformedModel())
    session = service.create_session()
    first = list(service.events(session, "malformed"))
    assert not list(settings.sandbox_root.rglob("*.txt"))
    if missing_id:
        assert first[-1]["data"]["ok"] is False and not session.messages
    else:
        assert first[-1]["data"]["ok"] is True
        results = [m for m in session.messages if isinstance(m, ToolMessage)]
        assert len(results) == 1 and results[0].tool_call_id == "bad/id"
    assert "synthetic-private-parameter" not in json.dumps(first) + json.dumps(
        service.audit.records()
    )
    second = list(service.events(session, 'write_note {"name":"recovered.txt","content":"x"}'))
    assert second[2]["data"]["result"]["ok"] and second[-1]["data"]["ok"]
    assert any(r["reason_codes"] == ["event.invalid"] for r in service.audit.records())
