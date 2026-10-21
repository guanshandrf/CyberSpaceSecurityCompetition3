import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.p6


def admin(claims, permissions=("tool.register", "fixture.use")):
    from agentguard.contracts import SecurityContext

    return SecurityContext.from_backend(
        **claims, context_id="admin.current", permissions=permissions
    )


@pytest.fixture
def clock(monkeypatch):
    import agentguard.registry.tools as registry_module

    now = [100.0]
    monkeypatch.setattr(registry_module.time, "monotonic", lambda: now[0])
    return now


def test_long_session_renews_through_gate0_without_resetting_budget_or_replay(
    adapter_case, framework_call, clock
):
    adapter, calls, audit, claims = adapter_case(ttl=1, budget=2)
    original = adapter.registrations[0].event
    assert adapter.invoke(framework_call, trace_id="trace.first").status == "success"
    for i in (2, 3):
        clock[0] += 2
        assert not adapter.tools(trace_id=f"trace.{i}")
        renewed = adapter.refresh_registrations(admin(claims))
        assert len(renewed) == 1 and renewed[0].decision.action == "ALLOW"
        event = renewed[0].event
        assert (event.tool_id, event.metadata_digest, event.version, event.permissions) == (
            original.tool_id,
            original.metadata_digest,
            original.version,
            original.permissions,
        )
        assert event.event_id != original.event_id
        result = adapter.invoke({**framework_call, "id": f"call.{i}"}, trace_id=f"trace.{i}")
        assert (result.status == "success") == (i == 2)
    assert len(calls) == 2
    assert adapter.invoke(framework_call, trace_id="trace.replay").status == "error"
    assert len([r for r in audit.records() if r["gate"] == "gate0"]) == 3


@pytest.mark.parametrize("failure", ["permission", "exception", "review", "audit"])
def test_failed_renewal_never_executes_or_reuses_old_approval(
    adapter_case, framework_call, clock, failure
):
    from agentguard.gates import Gate0
    from agentguard.gates.gate0 import registration_decision

    state = {"renewal": False}

    class ChangingGate:
        def evaluate(self, event, context):
            if state["renewal"]:
                if failure == "exception":
                    raise RuntimeError("synthetic-private-data")
                if failure == "review":
                    return registration_decision(event, "REVIEW", "registry.review")
            return Gate0().evaluate(event, context)

    adapter, calls, audit, claims = adapter_case(ttl=1, gate0=ChangingGate())
    clock[0] += 2
    state["renewal"] = True
    if failure == "audit":

        def failed_record(*args, **kwargs):
            raise RuntimeError("synthetic-private-data")

        audit.append = failed_record
    authority = admin(claims, permissions=()) if failure == "permission" else admin(claims)
    results = adapter.refresh_registrations(authority)
    assert results[0].decision.action in {"BLOCK", "REVIEW"}
    assert not adapter.tools(trace_id="trace.denied")
    assert adapter.invoke(framework_call, trace_id="trace.denied").status == "error" and not calls


def test_revoked_tool_stays_revoked_after_expiry_and_renewal(adapter_case, framework_call, clock):
    adapter, calls, _, claims = adapter_case(ttl=1)
    adapter.revoke("fixture.echo", registration_context=admin(claims))
    clock[0] += 2
    # Exercise expiry resolution first; it must not erase revocation state.
    assert adapter.invoke(framework_call, trace_id="trace.expired").status == "error"
    assert adapter.refresh_registrations(admin(claims))[0].decision.action == "BLOCK"
    assert not adapter.tools(trace_id="trace.revoked") and not calls


def test_revocation_during_slow_renewal_wins(adapter_case, framework_call, clock):
    from agentguard.gates import Gate0

    entered, release = threading.Event(), threading.Event()
    state = {"renewal": False}

    class SlowGate:
        def evaluate(self, event, context):
            if state["renewal"]:
                entered.set()
                assert release.wait(5)
            return Gate0().evaluate(event, context)

    adapter, calls, _, claims = adapter_case(ttl=1, gate0=SlowGate())
    clock[0] += 2
    state["renewal"] = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(adapter.refresh_registrations, admin(claims))
        try:
            assert entered.wait(2)
            adapter.revoke("fixture.echo", registration_context=admin(claims))
            assert adapter.invoke(framework_call, trace_id="trace.checking").status == "error"
        finally:
            release.set()
        assert future.result(timeout=5)[0].decision.action == "BLOCK"
    assert not adapter.tools(trace_id="trace.revoked") and not calls


@pytest.mark.parametrize("field", ["expected_digest", "expected_version"])
def test_renewal_rejects_metadata_or_version_mismatch(adapter_case, clock, field):
    adapter, calls, _, claims = adapter_case(ttl=1)
    event = adapter.registrations[0].event
    clock[0] += 2
    expected = dict(expected_digest=event.metadata_digest, expected_version=event.version)
    expected[field] = "wrong"
    result = adapter._registry.renew(event.tool_id, admin(claims), **expected)
    assert result.decision.action == "BLOCK"
    assert result.decision.reason_codes == ("registry.mismatch",) and not calls


def test_concurrent_renewal_checks_once_and_keeps_one_live_registration(adapter_case, clock):
    adapter, calls, audit, claims = adapter_case(ttl=1)
    clock[0] += 2
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: adapter.refresh_registrations(admin(claims)), range(8)))
    assert sum(bool(outcome) for outcome in outcomes) == 1
    assert len(adapter.tools(trace_id="trace.live")) == 1 and not calls
    assert len([r for r in audit.records() if r["gate"] == "gate0"]) == 2


def test_demo_long_session_automatically_uses_backend_renewal(tmp_path, clock):
    from agentguard_demo.providers import make_provider
    from agentguard_demo.service import ChatService
    from agentguard_demo.settings import DemoSettings

    settings = DemoSettings(enable_protection=True, sandbox_root=tmp_path / "sandbox")
    service = ChatService(settings, make_provider(settings))
    session = service.create_session()
    first = list(service.events(session, 'write_note {"name":"first.txt","content":"x"}'))
    assert first[2]["data"]["result"]["ok"]
    clock[0] += 301
    second = list(service.events(session, 'write_note {"name":"second.txt","content":"y"}'))
    assert second[2]["data"]["result"]["ok"]
    assert second[-1]["data"]["ok"]
    assert len(list(settings.sandbox_root.rglob("*.txt"))) == 2
    assert len([r for r in service.audit.records() if r["gate"] == "gate0"]) == 4
