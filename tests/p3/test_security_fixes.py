"""P3 audit regressions: real local I/O, bounded records and deterministic thread barriers."""

import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import pytest

from agentguard.policies import PathRule, PolicyEngine
from agentguard.policies.engine import decision_for

pytestmark = pytest.mark.p3


def reviewed(harness, **options):
    return harness.executor(policy=PolicyEngine(review_tools={"reader"}), **options)


def reviewer(harness):
    return harness.context(user_id="reviewer", permissions=["guard.approve"])


def test_pending_global_and_session_capacity_are_enforced(harness):
    executor = reviewed(harness, max_pending_approvals=4, max_pending_per_session=2)
    results = []
    for index in range(12):
        session = f"session.{index // 6}"
        results.append(
            executor.execute(
                harness.call(index, session_id=session), harness.context(session_id=session)
            )
        )
    assert len(executor._pending) == 4
    assert sum(r.decision.action == "REVIEW" for r in results) == 4
    assert sum(r.decision.action == "BLOCK" for r in results) == 8
    assert all(not r.executed for r in results) and not harness.count


@pytest.mark.parametrize("different_sessions", [False, True])
def test_concurrent_pending_creation_stays_within_global_limit(harness, different_sessions):
    executor = reviewed(harness, max_pending_approvals=3, max_pending_per_session=3)

    def request(i):
        session = f"s.{i}" if different_sessions else "session.1"
        return executor.execute(
            harness.call(i, session_id=session), harness.context(session_id=session)
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(request, range(24)))
    assert len(executor._pending) == 3
    assert sum(r.decision.action == "REVIEW" for r in results) == 3
    assert sum(r.decision.action == "BLOCK" for r in results) == 21
    assert all(not r.executed for r in results) and not harness.count


def test_expiry_cleanup_frees_capacity_and_invalidates_old_token(harness, monkeypatch):
    import agentguard.executor.guarded as module

    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    executor = reviewed(harness, approval_ttl=5, max_pending_approvals=2)
    first = executor.execute(harness.call(), harness.context())
    executor.approve(first.approval_ref, approver=reviewer(harness))
    executor.execute(harness.call(2), harness.context())
    now[0] = 105.0
    assert executor.cleanup_expired_approvals() == 2
    assert len(executor._pending) == 0 and len(executor._approval_tokens) == 0
    with pytest.raises(ValueError, match="Approval rejected"):
        executor.approve(first.approval_ref, approver=reviewer(harness))
    result = executor.execute(harness.call(3), harness.context())
    assert result.decision.action == "REVIEW" and result.approval_ref != first.approval_ref
    assert not result.executed and not harness.count


def test_expiry_is_swept_automatically_on_new_requests(harness, monkeypatch):
    import agentguard.executor.guarded as module

    now = [10.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    executor = reviewed(harness, approval_ttl=1, max_pending_approvals=1)
    old = executor.execute(harness.call(), harness.context())
    now[0] = 11.0
    new = executor.execute(harness.call(2), harness.context())
    assert new.decision.action == "REVIEW" and len(executor._pending) == 1
    assert old.approval_ref not in executor._approval_tokens
    assert not harness.count


def test_creation_rate_limit_survives_expiry_recycling(harness, monkeypatch):
    import agentguard.executor.guarded as module

    now = [10.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    executor = reviewed(harness, approval_ttl=1, max_approval_creations=2, approval_window=10)
    assert executor.execute(harness.call(), harness.context()).decision.action == "REVIEW"
    now[0] = 12.0
    assert executor.execute(harness.call(2), harness.context()).decision.action == "REVIEW"
    now[0] = 14.0
    denied = executor.execute(harness.call(3), harness.context())
    assert denied.decision.reason_codes == ("approval.rate_limited",)
    assert not denied.executed and not harness.count
    now[0] = 20.0
    assert executor.execute(harness.call(4), harness.context()).decision.action == "REVIEW"


def test_repeated_pending_request_does_not_consume_another_slot_or_rate_unit(harness):
    executor = reviewed(harness, max_pending_approvals=1, max_approval_creations=1)
    first = executor.execute(harness.call(), harness.context())
    second = executor.execute(harness.call(), harness.context())
    assert first.approval_ref == second.approval_ref and len(executor._pending) == 1
    executor.approve(first.approval_ref, approver=reviewer(harness))
    result = executor.execute(harness.call(), harness.context())
    assert result.executed and result.value == "public fixture" and len(harness.count) == 1
    assert not executor._pending and not executor._approval_tokens


def test_approval_lookup_does_not_scan_pending_values(harness):
    executor = reviewed(harness)
    first = executor.execute(harness.call(), harness.context())
    executor.execute(harness.call(2), harness.context())

    class NoScan(OrderedDict):
        def values(self):
            raise AssertionError("Linear scan of approval records")

    executor._pending = NoScan(executor._pending)
    executor.approve(first.approval_ref, approver=reviewer(harness))
    assert executor.execute(harness.call(), harness.context()).executed


def test_expired_records_do_not_accumulate_with_default_executor(harness, monkeypatch):
    import agentguard.executor.guarded as module

    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    executor = reviewed(harness, approval_ttl=1)
    for index in range(12):
        result = executor.execute(harness.call(index), harness.context())
        assert result.decision.action == "REVIEW" and not result.executed
        now[0] += 2
    assert len(executor._pending) == 1 and not harness.count


def test_global_capacity_is_shared_between_independent_sessions(harness):
    executor = reviewed(harness, max_pending_approvals=2)
    results = [
        executor.execute(harness.call(i, session_id=f"s.{i}"), harness.context(session_id=f"s.{i}"))
        for i in range(8)
    ]
    assert sum(r.decision.action == "REVIEW" for r in results) == 2
    assert len(executor._pending) == 2 and not harness.count


def test_completed_approval_releases_its_session_slot(harness):
    executor = reviewed(harness, max_pending_per_session=1)
    first = executor.execute(harness.call(), harness.context())
    assert executor.execute(harness.call(2), harness.context()).decision.action == "BLOCK"
    executor.approve(first.approval_ref, approver=reviewer(harness))
    assert executor.execute(harness.call(), harness.context()).executed
    assert executor.execute(harness.call(2), harness.context()).decision.action == "REVIEW"
    assert len(executor._pending) == 1 and len(harness.count) == 1


def test_approval_audit_failure_leaves_call_unapproved(harness, monkeypatch):
    executor = reviewed(harness)
    result = executor.execute(harness.call(), harness.context())
    original = harness.audit.append

    def append(decision, *, stage, duration_ms):
        if stage == "approved":
            raise RuntimeError("synthetic audit failure")
        original(decision, stage=stage, duration_ms=duration_ms)

    monkeypatch.setattr(harness.audit, "append", append)
    with pytest.raises(ValueError, match="Approval rejected"):
        executor.approve(result.approval_ref, approver=reviewer(harness))
    retry = executor.execute(harness.call(), harness.context())
    assert retry.decision.action == "REVIEW" and not retry.executed and not harness.count


def test_expiry_during_execution_intent_audit_cannot_run_tool(harness, monkeypatch):
    import agentguard.executor.guarded as module

    now = [10.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    executor = reviewed(harness, approval_ttl=5)
    first = executor.execute(harness.call(), harness.context())
    executor.approve(first.approval_ref, approver=reviewer(harness))
    original = harness.audit.append

    def append(decision, *, stage, duration_ms):
        if stage == "started":
            now[0] = 15.0
        original(decision, stage=stage, duration_ms=duration_ms)

    monkeypatch.setattr(harness.audit, "append", append)
    result = executor.execute(harness.call(), harness.context())
    assert result.decision.reason_codes == ("approval.expired",)
    assert not result.executed and not harness.count


def test_approving_state_has_no_side_effects(harness, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    executor = reviewed(harness)
    first = executor.execute(harness.call(), harness.context())
    original = harness.audit.append

    def append(decision, *, stage, duration_ms):
        if stage == "approved":
            entered.set()
            assert release.wait(5)
        original(decision, stage=stage, duration_ms=duration_ms)

    monkeypatch.setattr(harness.audit, "append", append)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(executor.approve, first.approval_ref, approver=reviewer(harness))
        try:
            assert entered.wait(2)
            waiting = executor.execute(harness.call(), harness.context())
            assert (
                waiting.decision.action == "REVIEW" and not waiting.executed and not harness.count
            )
        finally:
            release.set()
        future.result(timeout=2)
    assert executor.execute(harness.call(), harness.context()).executed


@pytest.mark.parametrize(
    "options",
    [
        {"max_pending_approvals": 0},
        {"max_pending_approvals": True},
        {"max_pending_per_session": -1},
        {"max_approval_creations": 0},
        {"approval_window": float("nan")},
        {"approval_window": float("inf")},
    ],
)
def test_invalid_approval_limits_fail_configuration(harness, options):
    with pytest.raises(ValueError):
        reviewed(harness, **options)


@pytest.mark.parametrize("slow_kind", ["detector", "policy"])
def test_slow_analysis_does_not_block_independent_session(harness, slow_kind):
    entered, release = threading.Event(), threading.Event()

    def pause(event):
        if event.session_id == "session.slow":
            entered.set()
            assert release.wait(5), "test barrier not released"

    class Detector:
        def detect(self, event, context):
            if slow_kind == "detector":
                pause(event)
            return ()

    class Policy:
        def evaluate(self, event, context, findings):
            if slow_kind == "policy":
                pause(event)
            return decision_for(event, "ALLOW", "checks.passed")

    executor = harness.executor(detectors=[Detector()], policy=Policy())
    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(
            executor.execute,
            harness.call(session_id="session.slow"),
            harness.context(session_id="session.slow"),
        )
        try:
            assert entered.wait(2)
            fast = pool.submit(
                executor.execute,
                harness.call(2, session_id="session.fast"),
                harness.context(session_id="session.fast"),
            )
            assert fast.result(timeout=2).executed
            assert not slow.done()
        finally:
            release.set()
        assert slow.result(timeout=2).executed
    assert len(harness.count) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"permissions": []},
        {"allowed_resources": []},
        {"task_authorization": "task.revoked"},
        {"budget": {"max_calls": 1, "calls_used": 1}},
    ],
)
def test_backend_revocation_during_detection_cannot_execute(harness, changes):
    entered, release = threading.Event(), threading.Event()

    class Detector:
        def detect(self, event, context):
            entered.set()
            assert release.wait(5)
            return ()

    executor = harness.executor(detectors=[Detector()])
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(executor.execute, harness.call(), harness.context())
        try:
            assert entered.wait(2)
            executor.update_context(harness.context(**changes))
        finally:
            release.set()
        result = future.result(timeout=2)
    assert result.decision.action == "BLOCK" and not result.executed and not harness.count


def test_revocation_during_audit_is_rechecked_before_reservation(harness, monkeypatch):
    executor = harness.executor()
    original = harness.audit.append

    def append(decision, *, stage, duration_ms):
        if stage == "started":
            executor.update_context(harness.context(permissions=[]))
        original(decision, stage=stage, duration_ms=duration_ms)

    monkeypatch.setattr(harness.audit, "append", append)
    result = executor.execute(harness.call(), harness.context())
    assert result.decision.reason_codes == ("context.changed",)
    assert not result.executed and not harness.count


def test_old_context_cannot_restore_published_permissions(harness):
    executor = harness.executor()
    executor.update_context(harness.context(permissions=[]))
    result = executor.execute(harness.call(), harness.context())
    assert result.decision.reason_codes == ("permission.denied",)
    assert not result.executed and not harness.count


def test_context_update_requires_backend_provenance_and_same_identity(harness):
    executor = harness.executor()
    executor.update_context(harness.context())
    for context in [harness.claims, None, harness.context(user_id="another.user")]:
        with pytest.raises(ValueError, match="Context update rejected"):
            executor.update_context(context)
    assert executor.execute(harness.call(), harness.context()).executed


@pytest.mark.parametrize("same_call", [True, False])
def test_simultaneous_analysis_completion_cannot_replay_or_overspend(harness, same_call):
    barrier = threading.Barrier(8)

    class Detector:
        def detect(self, event, context):
            barrier.wait(timeout=5)
            return ()

    executor = harness.executor(detectors=[Detector()])
    context = harness.context(budget={"max_calls": 1, "calls_used": 0})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda i: executor.execute(harness.call(1 if same_call else i), context), range(8)
            )
        )
    assert sum(r.executed for r in results) == 1
    assert sum(r.decision.action == "BLOCK" for r in results) == 7
    assert len(harness.count) == 1


@pytest.mark.parametrize("action", ["BLOCK", "REVIEW"])
def test_concurrent_denied_analysis_has_zero_side_effects(harness, action):
    barrier = threading.Barrier(8)

    class Policy:
        def evaluate(self, event, context, findings):
            barrier.wait(timeout=5)
            return decision_for(event, action, "fixture.deny")

    executor = harness.executor(policy=Policy())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda i: executor.execute(harness.call(i), harness.context()), range(8))
        )
    assert all(not r.executed and r.decision.action == action for r in results)
    assert not harness.count


@pytest.mark.parametrize(
    "name",
    [
        "CONIN$",
        "conin$.txt",
        "CONOUT$",
        "ConOut$.log",
        "COM¹",
        "com².txt",
        "CoM³.dat",
        "LPT¹",
        "lpt².log",
        "LPT³",
        "CON .txt",
        "nul .json",
        "COM1 .txt",
        "LPT9 .log",
    ],
)
def test_special_devices_rejected_lexically_before_any_filesystem_touch(harness, monkeypatch, name):
    import agentguard.policies.binding as module

    rule = PathRule("path", "resource.public", harness.root, must_exist=False)

    def forbidden_touch(path):
        raise AssertionError("Reserved device name reached filesystem checks")

    monkeypatch.setattr(module, "_check_node", forbidden_touch)
    with pytest.raises(ValueError, match="Invalid path"):
        rule.resolve_argument(name)


@pytest.mark.parametrize(
    "name",
    [
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM9",
        "LPT1",
        "LPT9",
        "CONIN$",
        "CONOUT$",
        "COM¹",
        "COM²",
        "COM³",
        "LPT¹",
        "LPT²",
        "LPT³",
    ],
)
def test_device_case_extension_trailing_dot_and_space_variants(harness, monkeypatch, name):
    import agentguard.policies.binding as module

    rule = PathRule("path", "resource.public", harness.root, must_exist=False)

    def forbidden_touch(path):
        raise AssertionError("Device alias reached filesystem checks")

    monkeypatch.setattr(module, "_check_node", forbidden_touch)
    for variant in [name.lower(), name + ".txt", name + " .log", name + ".", name + " "]:
        with pytest.raises(ValueError, match="Invalid path"):
            rule.resolve_argument(variant)


@pytest.mark.parametrize(
    "name", ["sample.txt", "CONIN-file.txt", "COM10.txt", "LPT0.txt", "myCOM¹.txt"]
)
def test_normal_names_still_allow_real_file_io(harness, name):
    (harness.root / name).write_text("normal public file", encoding="utf-8")
    result = harness.executor().execute(harness.call(arguments={"path": name}), harness.context())
    assert result.executed and result.value == "normal public file" and len(harness.count) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows stdlib device classification only")
def test_windows_actual_stdlib_reserved_name_classification():
    # No device handles are opened. Actual OS I/O is separately tested using normal fixtures.
    for name in ["CONIN$", "CONOUT$", "COM¹", "LPT².txt", "CON .txt", "nul.txt"]:
        assert os.path.isreserved(name)
