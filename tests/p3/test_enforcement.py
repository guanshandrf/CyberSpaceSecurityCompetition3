import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from agentguard.contracts import Gate, SecurityContext
from agentguard.executor import GuardedExecutor
from agentguard.gates import Gate1
from agentguard.policies import PolicyEngine
from agentguard.policies.engine import decision_for

pytestmark = pytest.mark.p3


def blocked(result, harness, reason=None):
    assert result.decision.action == "BLOCK"
    assert result.executed is False
    assert harness.count == []
    if reason:
        assert result.decision.reason_codes == (reason,)


def test_authorized_read_really_executes_and_audits(harness):
    executor = harness.executor()
    assert isinstance(executor.gate, Gate)
    assert executor.before_tool(harness.call(), harness.context()).action == "ALLOW"
    assert harness.count == []
    result = executor.execute(harness.call(), harness.context())
    assert result.executed and result.decision.action == "ALLOW"
    assert result.value == "public fixture"
    assert harness.count == [str(harness.root / "sample.txt")]
    assert [r["stage"] for r in harness.audit.records()] == ["started", "completed"]


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "/outside.txt",
        "C:/outside.txt",
        "C:outside.txt",
        "\\\\server\\share",
        "folder\\sample.txt",
        "sample.txt:stream",
        "./sample.txt",
        "folder//sample.txt",
        "",
        "sample.txt.",
        "sample.txt ",
        "CON",
        "NUL.txt",
        "LPT1.txt",
        "bad\x00file",
        "a*",
        "a?",
        "missing.txt",
        "folder/../../outside.txt",
    ],
)
def test_path_escape_and_windows_aliases_execute_zero_times(harness, path):
    blocked(
        harness.executor().execute(harness.call(arguments={"path": path}), harness.context()),
        harness,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"path": 1},
        {"path": True},
        {"path": None},
        {"path": ["sample.txt"]},
        {"path": "sample.txt", "admin": True},
    ],
)
def test_schema_invalid_executes_zero_times(harness, arguments):
    blocked(
        harness.executor().execute(harness.call(arguments=arguments), harness.context()),
        harness,
        "schema.invalid",
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"permissions": []}, "permission.denied"),
        ({"allowed_resources": []}, "resource.denied"),
        ({"task_authorization": "task.other"}, "task.denied"),
        ({"budget": {"max_calls": 1, "calls_used": 1}}, "budget.exhausted"),
        ({"budget": {"max_calls": 1, "calls_used": 4}}, "budget.exhausted"),
        ({"session_id": "session.other"}, "context.invalid"),
        ({"context_id": "context.other"}, "context.invalid"),
    ],
)
def test_hard_denials_dominate_permissive_policy(harness, changes, reason):
    class AlwaysAllow:
        def evaluate(self, event, context, findings):
            return decision_for(event, "ALLOW", "low.risk")

    blocked(
        harness.executor(policy=AlwaysAllow()).execute(harness.call(), harness.context(**changes)),
        harness,
        reason,
    )


@pytest.mark.parametrize("context_kind", ["none", "dict", "constructed"])
def test_missing_or_forged_context_denied(harness, context_kind):
    context = {
        "none": None,
        "dict": harness.claims,
        "constructed": SecurityContext.model_construct(**harness.claims),
    }[context_kind]
    blocked(harness.executor().execute(harness.call(), context), harness, "context.invalid")


@pytest.mark.parametrize(
    "change",
    [
        {"tool_id": "unknown"},
        {"name": "other"},
        {"metadata_digest": "b" * 64},
    ],
)
def test_backend_binding_must_match(harness, change):
    blocked(harness.executor().execute(harness.call(**change), harness.context()), harness)


@pytest.mark.parametrize("failure", ["raise", "none", "stale", "forged", "sanitize"])
def test_policy_failure_denies(harness, failure):
    class Broken:
        def evaluate(self, event, context, findings):
            if failure == "raise":
                raise RuntimeError("synthetic-sensitive-exception")
            if failure == "none":
                return None
            decision = decision_for(event, "ALLOW", "fixture.allow")
            if failure == "stale":
                return decision.model_copy(update={"event_id": "stale.event"})
            if failure == "sanitize":
                return decision.model_copy(update={"action": "SANITIZE"})
            return decision.model_copy(update={"action": "invented"})

    blocked(
        harness.executor(policy=Broken()).execute(harness.call(), harness.context()),
        harness,
        "check.failed",
    )


def test_detector_exception_denies(harness):
    class Broken:
        def detect(self, event, context):
            raise RuntimeError("synthetic-secret")

    blocked(
        harness.executor(detectors=[Broken()]).execute(harness.call(), harness.context()),
        harness,
        "check.failed",
    )


def test_hardlink_fixture_denied(harness):
    os.link(harness.root.parent / "outside.txt", harness.root / "alias.txt")
    blocked(
        harness.executor().execute(
            harness.call(arguments={"path": "alias.txt"}), harness.context()
        ),
        harness,
        "path.denied",
    )


@pytest.mark.parametrize("location", ["child", "root"])
def test_real_directory_link_rejected_before_read(harness, location):
    target = harness.root.parent / "external-fixture"
    target.mkdir()
    (target / "sample.txt").write_text("public external fixture", encoding="utf-8")
    if location == "root":
        (harness.root / "sample.txt").unlink()
        harness.root.rmdir()
        link = harness.root
        argument = "sample.txt"
    else:
        link = harness.root / "linked"
        argument = "linked/sample.txt"
    if os.name == "nt":
        process = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert process.returncode == 0, "Could not create isolated junction fixture"
    else:
        link.symlink_to(target, target_is_directory=True)
    blocked(
        harness.executor().execute(harness.call(arguments={"path": argument}), harness.context()),
        harness,
        "path.denied",
    )


def test_invalid_detector_output_cannot_be_ignored_by_allow_policy(harness):
    class Broken:
        def detect(self, event, context):
            return ({"code": "not-a-finding"},)

    class AlwaysAllow:
        def evaluate(self, event, context, findings):
            return decision_for(event, "ALLOW", "fixture.allow")

    blocked(
        harness.executor(detectors=[Broken()], policy=AlwaysAllow()).execute(
            harness.call(), harness.context()
        ),
        harness,
        "check.failed",
    )


def test_default_policy_blocks_valid_detector_findings(harness):
    from agentguard.contracts import SecurityFinding

    class Detector:
        def detect(self, event, context):
            return (
                SecurityFinding(
                    code="fixture.risk",
                    severity="high",
                    evidence_ref="evidence.1",
                    detector_id="fixture.detector",
                ),
            )

    blocked(
        harness.executor(detectors=[Detector()]).execute(harness.call(), harness.context()),
        harness,
        "policy.denied",
    )


def test_real_directory_is_not_a_file(harness):
    (harness.root / "folder").mkdir()
    blocked(
        harness.executor().execute(harness.call(arguments={"path": "folder"}), harness.context()),
        harness,
        "path.denied",
    )


def test_configured_policy_block_dominates_review(harness):
    policy = PolicyEngine(blocked_tools={"reader"}, review_tools={"reader"})
    blocked(
        harness.executor(policy=policy).execute(harness.call(), harness.context()),
        harness,
        "policy.denied",
    )


def test_mutating_plugin_cannot_change_executed_arguments(harness):
    class Mutating:
        def evaluate(self, event, context, findings):
            event.arguments["path"] = "../outside.txt"
            return decision_for(event, "ALLOW", "fixture.allow")

    result = harness.executor(policy=Mutating()).execute(harness.call(), harness.context())
    assert result.value == "public fixture"
    assert len(harness.count) == 1


def test_parameter_mutation_revalidated_at_execution(harness):
    call = harness.call()
    executor = harness.executor()
    assert executor.before_tool(call, harness.context()).action == "ALLOW"
    call.arguments["path"] = "../outside.txt"
    blocked(executor.execute(call, harness.context()), harness, "path.denied")


@pytest.mark.parametrize("invalid", [None, {}, {"event_type": "tool_call"}])
def test_invalid_events_have_no_execution(harness, invalid):
    result = harness.executor().execute(invalid, harness.context())
    assert result.error_code == "event.invalid" and result.decision is None
    assert not result.executed and not harness.count


def test_unknown_schema_keyword_fails_configuration(harness):
    with pytest.raises(ValueError, match="Unsupported"):
        harness.binding(parameters_schema={**harness.schema, "$ref": "https://invalid/schema"})


def test_replay_and_new_id_cannot_evade_budget(harness):
    executor = harness.executor()
    assert executor.execute(harness.call(), harness.context()).executed
    assert executor.execute(harness.call(), harness.context()).decision.reason_codes == (
        "call.replayed",
    )
    assert executor.execute(harness.call(2), harness.context()).executed
    result = executor.execute(
        harness.call(3, context_ref="context.new"),
        harness.context(context_id="context.new", budget={"max_calls": 100, "calls_used": 0}),
    )
    assert not result.executed and result.decision.reason_codes == ("budget.exhausted",)
    assert len(harness.count) == 2


@pytest.mark.parametrize("reuse", ["call", "event"])
def test_reusing_either_identifier_blocks(harness, reuse):
    executor = harness.executor()
    assert executor.execute(harness.call(), harness.context()).executed
    changes = {"tool_call_id": "call.1"} if reuse == "call" else {"event_id": "event.1"}
    result = executor.execute(harness.call(2, **changes), harness.context())
    assert not result.executed and result.decision.reason_codes == ("call.replayed",)
    assert len(harness.count) == 1


def test_seen_trusted_budget_exhaustion_cannot_be_reset_by_old_context(harness):
    executor = harness.executor()
    old_context = harness.context()
    exhausted = harness.context(budget={"max_calls": 2, "calls_used": 2})
    denied = executor.execute(harness.call(), exhausted)
    assert denied.decision.reason_codes == ("budget.exhausted",)
    blocked(executor.execute(harness.call(2), old_context), harness, "budget.exhausted")


@pytest.mark.parametrize("same_call", [True, False])
def test_concurrent_calls_cannot_reuse_allow_or_overspend(harness, same_call):
    executor = harness.executor()
    context = harness.context(budget={"max_calls": 1, "calls_used": 0})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda i: executor.execute(harness.call(1 if same_call else i), context),
                range(1, 17),
            )
        )
    assert sum(result.executed for result in results) == 1
    assert len(harness.count) == 1
    assert sum(r.decision.action == "BLOCK" for r in results) == 15


def test_tool_exception_is_generic_consumes_budget_and_prevents_retry(harness):
    def failing(path):
        harness.count.append(path)
        raise RuntimeError("synthetic-sensitive-value")

    tool = harness.binding(handler=failing)
    executor = harness.executor(tools=[tool])
    result = executor.execute(harness.call(selected=tool), harness.context())
    assert result.executed and result.error_code == "tool.failed" and result.value is None
    assert "sensitive" not in repr(result)
    assert not executor.execute(harness.call(selected=tool), harness.context()).executed
    assert len(harness.count) == 1


def test_audit_failure_before_execution_is_closed(harness):
    class BrokenAudit:
        def append(self, *args, **kwargs):
            raise RuntimeError("synthetic-secret")

    blocked(
        GuardedExecutor([harness.tool], audit=BrokenAudit()).execute(
            harness.call(), harness.context()
        ),
        harness,
        "audit.failed",
    )


def test_post_execution_audit_failure_is_reported_truthfully(harness):
    class FailsAfterStart:
        def append(self, decision, *, stage, duration_ms):
            if stage == "completed":
                raise RuntimeError("synthetic-secret")

    result = GuardedExecutor([harness.tool], audit=FailsAfterStart()).execute(
        harness.call(), harness.context()
    )
    assert result.executed and len(harness.count) == 1
    assert result.error_code == "audit.failed_after_execution" and result.value is None


def test_session_identity_cannot_change(harness):
    executor = harness.executor()
    assert executor.execute(harness.call(), harness.context()).executed
    result = executor.execute(harness.call(2), harness.context(user_id="user.other"))
    assert not result.executed and result.decision.reason_codes == ("session.mismatch",)
    assert len(harness.count) == 1


def test_gate_does_not_implement_future_stages():
    assert hasattr(Gate1, "before_tool") and not hasattr(Gate1, "after_tool")
    assert not hasattr(Gate1, "register")
