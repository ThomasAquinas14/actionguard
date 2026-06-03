"""Core flow: approve -> executes + audited; deny -> blocked + audited."""

from __future__ import annotations

import json

import pytest
from langchain_core.tools import tool

from actionguard import ApprovalPolicy, guard
from actionguard.audit import AuditLog
from actionguard.core import Action, Decision, denial_message


def _read_records(path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ---- core data types --------------------------------------------------------


def test_action_pretty():
    action = Action(tool_name="refund", args={"amount": 50, "id": "c1"})
    assert action.pretty() == "refund(amount=50, id='c1')"


def test_decision_helpers():
    assert Decision.approve("ok").approved is True
    assert Decision.deny("no").approved is False


def test_denial_message_mentions_tool_and_comment():
    action = Action(tool_name="refund", args={"amount": 50})
    msg = denial_message(action, Decision.deny("too risky"))
    assert "DENIED" in msg
    assert "refund(amount=50)" in msg
    assert "too risky" in msg


# ---- audit log ---------------------------------------------------------------


def test_audit_log_writes_one_jsonl_record(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    action = Action(tool_name="t", args={"x": 1})
    log.record(
        action=action,
        needed_approval=True,
        decision=Decision(approved=True, source="cli"),
        executed=True,
        result="done",
    )
    records = _read_records(tmp_path / "a.jsonl")
    assert len(records) == 1
    rec = records[0]
    assert rec["tool"] == "t"
    assert rec["args"] == {"x": 1}
    assert rec["needed_approval"] is True
    assert rec["approved"] is True
    assert rec["decision_source"] == "cli"
    assert rec["executed"] is True
    assert rec["result"] == "done"
    assert rec["error"] is None
    assert "timestamp" in rec


def test_audit_log_appends(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    action = Action(tool_name="t", args={})
    log.record(action=action, needed_approval=False, decision=None, executed=True)
    log.record(action=action, needed_approval=False, decision=None, executed=True)
    assert len(_read_records(tmp_path / "a.jsonl")) == 2


def test_audit_creates_missing_parent_dir(tmp_path):
    # A missing log dir must not cause a crash *after* an action has run.
    nested = tmp_path / "logs" / "deep" / "audit.jsonl"
    log = AuditLog(nested)
    log.record(
        action=Action(tool_name="t", args={}), needed_approval=False, decision=None, executed=True
    )
    assert nested.exists()
    assert len(_read_records(nested)) == 1


def test_audit_disabled_is_noop_but_returns_record(tmp_path):
    path = tmp_path / "a.jsonl"
    log = AuditLog(path, enabled=False)
    rec = log.record(
        action=Action(tool_name="t", args={}),
        needed_approval=False,
        decision=None,
        executed=True,
    )
    assert rec["tool"] == "t"
    assert not path.exists()


def test_audit_preflight_fails_fast_on_unwritable_sink(tmp_path):
    # An unwritable audit sink must surface at construction time — before any guarded
    # action can run — not as a crash after an irreversible action has executed.
    # A directory path can't be opened for append, so it stands in for "unwritable".
    with pytest.raises(OSError):
        AuditLog(tmp_path)  # tmp_path is a directory


def test_post_execution_audit_failure_does_not_mask_completed_action(tmp_path, auto_approve):
    # If the sink goes bad *after* the tool runs, the caller must still see the result
    # (not an error that would make an agent retry an irreversible action). A loud
    # RuntimeWarning is emitted instead.
    @tool
    def do_thing(x: int) -> str:
        """Do."""
        return f"did {x}"

    audit = AuditLog(tmp_path / "audit.jsonl")

    def boom(**_kwargs):
        raise PermissionError("sink went away mid-run")

    audit.record = boom  # type: ignore[method-assign]
    guarded = guard(
        do_thing, policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit
    )

    with pytest.warns(RuntimeWarning, match="DID execute"):
        result = guarded.invoke({"x": 7})
    assert result == "did 7"  # completed action is reported as success, not retried


# ---- end-to-end interception: approve runs it, deny blocks it ---------------


def test_approve_executes_and_audits(tmp_path, auto_approve):
    calls = []

    @tool
    def do_thing(x: int) -> str:
        """Do the thing."""
        calls.append(x)
        return f"did {x}"

    audit = AuditLog(tmp_path / "audit.jsonl")
    guarded = guard(
        do_thing, policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit
    )

    result = guarded.invoke({"x": 7})

    assert result == "did 7"  # underlying tool ran
    assert calls == [7]
    assert len(auto_approve.requests) == 1
    rec = _read_records(tmp_path / "audit.jsonl")[0]
    assert rec["needed_approval"] is True
    assert rec["approved"] is True
    assert rec["executed"] is True
    assert rec["result"] == "did 7"


def test_deny_blocks_and_audits(tmp_path, auto_deny):
    calls = []

    @tool
    def do_thing(x: int) -> str:
        """Do the thing."""
        calls.append(x)
        return f"did {x}"

    audit = AuditLog(tmp_path / "audit.jsonl")
    guarded = guard(
        do_thing, policy=ApprovalPolicy(require_always=True), channel=auto_deny, audit=audit
    )

    result = guarded.invoke({"x": 7})

    assert calls == []  # underlying tool did NOT run
    assert "DENIED" in result  # agent gets a clear denial string
    rec = _read_records(tmp_path / "audit.jsonl")[0]
    assert rec["needed_approval"] is True
    assert rec["approved"] is False
    assert rec["executed"] is False


def test_policy_says_no_approval_needed_runs_without_channel(tmp_path):
    calls = []

    @tool
    def do_thing(x: int) -> str:
        """Do the thing."""
        calls.append(x)
        return f"did {x}"

    # require_always=False => never ask; the (denying) channel must not be consulted.
    audit = AuditLog(tmp_path / "audit.jsonl")
    from tests.conftest import AutoDenyChannel

    channel = AutoDenyChannel()
    guarded = guard(
        do_thing, policy=ApprovalPolicy(require_always=False), channel=channel, audit=audit
    )

    result = guarded.invoke({"x": 1})
    assert result == "did 1"
    assert channel.requests == []  # never asked for approval
    rec = _read_records(tmp_path / "audit.jsonl")[0]
    assert rec["needed_approval"] is False
    assert rec["approved"] is None
    assert rec["executed"] is True


def test_audit_records_tool_error(tmp_path, auto_approve):
    @tool
    def boom(x: int) -> str:
        """Raise."""
        raise RuntimeError("kaboom")

    audit = AuditLog(tmp_path / "audit.jsonl")
    guarded = guard(
        boom, policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit
    )

    with pytest.raises(RuntimeError):
        guarded.invoke({"x": 1})

    rec = _read_records(tmp_path / "audit.jsonl")[0]
    assert rec["executed"] is False
    assert "kaboom" in rec["error"]
