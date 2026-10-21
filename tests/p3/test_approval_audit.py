import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agentguard.policies import PolicyEngine
from agentguard.policies.engine import decision_for

pytestmark = pytest.mark.p3


def test_standalone_local_example_runs_real_fixture_read(tmp_path):
    script = Path(__file__).resolve().parents[2] / "examples" / "guarded_read.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script)],
        cwd=tmp_path,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "allowed": True,
        "blocked": True,
        "review_waited": True,
        "approved": True,
        "actual_executions": 2,
    }


def review_setup(harness, **options):
    executor = harness.executor(policy=PolicyEngine(review_tools={"reader"}), **options)
    call, context = harness.call(), harness.context()
    result = executor.execute(call, context)
    assert result.decision.action == "REVIEW" and not result.executed and not harness.count
    assert result.approval_ref
    return executor, call, context, result.approval_ref


def approver(harness, **overrides):
    return harness.context(user_id="reviewer", permissions=["guard.approve"], **overrides)


def test_review_remains_without_side_effects_until_backend_approval(harness):
    executor, call, context, token = review_setup(harness)
    again = executor.execute(call, context)
    assert again.approval_ref == token and not again.executed and not harness.count
    executor.approve(token, approver=approver(harness))
    assert not harness.count  # Approval alone has no tool side effects.
    result = executor.execute(call, context)
    assert result.executed and result.value == "public fixture"
    assert result.decision.reason_codes == ("approval.approved",)
    assert not executor.execute(call, context).executed
    assert len(harness.count) == 1
    with pytest.raises(ValueError, match="Approval rejected"):
        executor.approve(token, approver=approver(harness))


@pytest.mark.parametrize("invalid_approver", ["none", "dict", "no_permission", "other_session"])
def test_model_cannot_approve(harness, invalid_approver):
    executor, call, context, token = review_setup(harness)
    identity = {
        "none": None,
        "dict": {**harness.claims, "permissions": ["guard.approve"]},
        "no_permission": context,
        "other_session": approver(harness, session_id="other.session"),
    }[invalid_approver]
    with pytest.raises(ValueError, match="Approval rejected"):
        executor.approve(token, approver=identity)
    assert not executor.execute(call, context).executed and not harness.count


def test_wrong_approval_token_does_not_execute(harness):
    executor, call, context, _ = review_setup(harness)
    with pytest.raises(ValueError, match="Approval rejected"):
        executor.approve("invented-token", approver=approver(harness))
    assert not executor.execute(call, context).executed and not harness.count


def test_explicit_rejection_never_executes(harness):
    executor, call, context, token = review_setup(harness)
    executor.approve(token, approver=approver(harness), approved=False)
    result = executor.execute(call, context)
    assert result.decision.reason_codes == ("approval.denied",)
    assert not result.executed and not harness.count


def test_expired_approval_cannot_execute(harness, monkeypatch):
    import agentguard.executor.guarded as module

    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    executor, call, context, token = review_setup(harness, approval_ttl=5)
    executor.approve(token, approver=approver(harness))
    now[0] = 105.0
    result = executor.execute(call, context)
    assert result.decision.reason_codes == ("approval.expired",)
    assert not result.executed and not harness.count


@pytest.mark.parametrize(
    "change", ["arguments", "event", "trace", "context", "permissions", "digest"]
)
def test_approval_binds_complete_call_and_context(harness, change):
    executor, call, context, token = review_setup(harness)
    executor.approve(token, approver=approver(harness))
    (harness.root / "other.txt").write_text("other public fixture", encoding="utf-8")
    if change == "arguments":
        call = harness.call(arguments={"path": "other.txt"})
    elif change == "event":
        call = harness.call(event_id="event.changed")
    elif change == "trace":
        call = harness.call(trace_id="trace.changed")
    elif change == "context":
        call, context = (
            harness.call(context_ref="context.2"),
            harness.context(context_id="context.2"),
        )
    elif change == "permissions":
        context = harness.context(permissions=[])
    else:
        call = harness.call(metadata_digest="b" * 64)
    result = executor.execute(call, context)
    assert not result.executed and result.decision.action == "BLOCK" and not harness.count


def test_review_does_not_reserve_budget_and_execution_rechecks_remaining(harness):
    executor, call, context, token = review_setup(harness)
    executor.approve(token, approver=approver(harness))
    result = executor.execute(call, harness.context(budget={"max_calls": 1, "calls_used": 1}))
    assert result.decision.reason_codes == ("budget.exhausted",)
    assert not result.executed and not harness.count


def test_concurrent_approved_retry_executes_once(harness):
    executor, call, context, token = review_setup(harness)
    executor.approve(token, approver=approver(harness))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: executor.execute(call, context), range(16)))
    assert sum(r.executed for r in results) == 1 and len(harness.count) == 1


def test_required_review_cannot_be_removed_by_allow_policy(harness):
    tool = harness.binding(requires_review=True)
    executor = harness.executor(tools=[tool])
    result = executor.execute(harness.call(selected=tool), harness.context())
    assert result.decision.action == "REVIEW" and not result.executed and not harness.count


def test_approved_call_rechecks_hard_path_boundary(harness):
    executor, call, context, token = review_setup(harness)
    executor.approve(token, approver=approver(harness))
    (harness.root / "sample.txt").unlink()
    result = executor.execute(call, context)
    assert result.decision.reason_codes == ("path.denied",)
    assert not result.executed and not harness.count


def test_approved_call_rechecks_current_policy(harness):
    class Revocable:
        denied = False

        def evaluate(self, event, context, findings):
            return decision_for(event, "BLOCK" if self.denied else "REVIEW", "fixture.policy")

    policy = Revocable()
    executor = harness.executor(policy=policy)
    call, context = harness.call(), harness.context()
    token = executor.execute(call, context).approval_ref
    executor.approve(token, approver=approver(harness))
    policy.denied = True
    result = executor.execute(call, context)
    assert result.decision.action == "BLOCK" and not result.executed and not harness.count


def test_audit_contains_no_sensitive_arguments_output_exception_identifiers_or_tokens(harness):
    secret = "synthetic-secret-DO-NOT-LOG"

    def handler(path):
        harness.count.append(path)
        return secret

    class CustomPolicy:
        def evaluate(self, event, context, findings):
            return decision_for(event, "ALLOW", secret)

    tool = harness.binding(handler=handler)
    executor = harness.executor(tools=[tool], policy=CustomPolicy())
    result = executor.execute(harness.call(selected=tool, trace_id=secret), harness.context())
    assert result.value == secret and secret not in repr(result)
    records = harness.audit.records()
    encoded = json.dumps(records)
    for sensitive in (secret, "sample.txt", str(harness.root), "user.1", "session.1", "reader"):
        assert sensitive not in encoded
    assert records[0]["reason_codes"] == ["policy.custom"]
    assert records[0]["trace_id"] == records[1]["trace_id"]
    assert len(records[0]["trace_id"]) == 64


def test_approval_reference_is_never_logged(harness):
    executor, call, context, token = review_setup(harness)
    executor.approve(token, approver=approver(harness))
    executor.execute(call, context)
    assert token not in json.dumps(harness.audit.records())


def test_no_external_decision_can_be_passed_to_executor(harness):
    executor = harness.executor()
    call, context = harness.call(), harness.context()
    old = executor.before_tool(call, context)
    with pytest.raises(TypeError):
        executor.execute(call, context, decision=old)
    assert not harness.count
