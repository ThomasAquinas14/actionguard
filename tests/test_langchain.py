"""The guarded tool must be indistinguishable to the agent — sync and async."""

from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.tools import BaseTool, tool

from actionguard import ApprovalChannel, ApprovalPolicy, guard, guard_tools
from actionguard.langchain import ApprovalWrappedTool


@tool
def refund_customer(amount: float, customer_id: str) -> str:
    """Issue a refund to a customer."""
    return f"refunded {amount} to {customer_id}"


# ---- schema preservation: the agent can't tell it was wrapped ---------------


def test_wrapped_tool_preserves_name_description_and_schema(auto_approve, audit_log):
    guarded = guard(
        refund_customer,
        policy=ApprovalPolicy(require_always=False),
        channel=auto_approve,
        audit=audit_log,
    )

    assert isinstance(guarded, BaseTool)
    assert guarded.name == refund_customer.name
    assert guarded.description == refund_customer.description
    # Same args schema => the model sees an identical tool spec.
    assert guarded.args_schema is refund_customer.args_schema
    assert guarded.args == refund_customer.args


def test_wrapped_tool_is_a_basetool_instance(auto_approve, audit_log):
    guarded = guard(refund_customer, channel=auto_approve, audit=audit_log)
    assert isinstance(guarded, ApprovalWrappedTool)
    assert isinstance(guarded, BaseTool)


# ---- sync path --------------------------------------------------------------


def test_sync_invoke_runs_when_approved(auto_approve, audit_log):
    guarded = guard(
        refund_customer,
        policy=ApprovalPolicy(require_always=True),
        channel=auto_approve,
        audit=audit_log,
    )
    out = guarded.invoke({"amount": 5.0, "customer_id": "c1"})
    assert out == "refunded 5.0 to c1"
    assert auto_approve.requests[0].args == {"amount": 5.0, "customer_id": "c1"}


def test_sync_invoke_blocked_when_denied(auto_deny, audit_log):
    guarded = guard(
        refund_customer,
        policy=ApprovalPolicy(require_always=True),
        channel=auto_deny,
        audit=audit_log,
    )
    out = guarded.invoke({"amount": 5.0, "customer_id": "c1"})
    assert "DENIED" in out


# ---- async path -------------------------------------------------------------


def test_async_ainvoke_runs_when_approved(auto_approve, audit_log):
    guarded = guard(
        refund_customer,
        policy=ApprovalPolicy(require_always=True),
        channel=auto_approve,
        audit=audit_log,
    )
    out = asyncio.run(guarded.ainvoke({"amount": 9.0, "customer_id": "c2"}))
    assert out == "refunded 9.0 to c2"


def test_async_ainvoke_blocked_when_denied(auto_deny, audit_log):
    guarded = guard(
        refund_customer,
        policy=ApprovalPolicy(require_always=True),
        channel=auto_deny,
        audit=audit_log,
    )
    out = asyncio.run(guarded.ainvoke({"amount": 9.0, "customer_id": "c2"}))
    assert "DENIED" in out


def test_async_path_works_for_async_tool(auto_approve, audit_log):
    @tool
    async def async_send(to: str) -> str:
        """Send an email."""
        return f"sent to {to}"

    guarded = guard(
        async_send,
        policy=ApprovalPolicy(require_always=True),
        channel=auto_approve,
        audit=audit_log,
    )
    out = asyncio.run(guarded.ainvoke({"to": "a@b.com"}))
    assert out == "sent to a@b.com"


# ---- the policy actually gates ----------------------------------------------


def test_policy_threshold_only_gates_large_calls(auto_deny, audit_log):
    guarded = guard(
        refund_customer,
        policy=ApprovalPolicy(amount_over={"arg": "amount", "threshold": 100}),
        channel=auto_deny,
        audit=audit_log,
    )
    # Small refund: under threshold, runs without consulting the channel.
    assert guarded.invoke({"amount": 5.0, "customer_id": "c1"}) == "refunded 5.0 to c1"
    assert auto_deny.requests == []
    # Large refund: needs approval, denied -> blocked.
    out = guarded.invoke({"amount": 4000.0, "customer_id": "c1"})
    assert "DENIED" in out
    assert len(auto_deny.requests) == 1


# ---- decorator forms & defaults ---------------------------------------------


def test_guard_as_parameterised_decorator(auto_approve, audit_log):
    @guard(policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit_log)
    @tool
    def send_email(to: str) -> str:
        """Send an email."""
        return f"sent to {to}"

    assert send_email.name == "send_email"
    assert send_email.invoke({"to": "x@y.com"}) == "sent to x@y.com"


def test_default_policy_requires_approval(auto_deny, audit_log):
    # No policy passed => safe default => everything is gated.
    guarded = guard(refund_customer, channel=auto_deny, audit=audit_log)
    out = guarded.invoke({"amount": 1.0, "customer_id": "c1"})
    assert "DENIED" in out
    assert len(auto_deny.requests) == 1


def test_guard_rejects_non_tool():
    with pytest.raises(TypeError):
        guard(lambda x: x, policy=ApprovalPolicy())


# ---- schema preservation for tools that infer their schema from _run ---------


def test_wraps_basetool_with_no_args_schema(auto_approve, audit_log):
    # A BaseTool subclass that leaves args_schema=None and infers from _run. The
    # wrapper must still expose the real parameters, not its own (*args, **kwargs).
    class EmailTool(BaseTool):
        name: str = "send_email"
        description: str = "Send an email."

        def _run(self, to: str, subject: str) -> str:
            return f"sent to {to}: {subject}"

    inner = EmailTool()
    assert inner.args_schema is None  # precondition for the bug this guards against

    guarded = guard(
        inner, policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit_log
    )
    assert set(guarded.args.keys()) == set(inner.args.keys()) == {"to", "subject"}
    assert guarded.invoke({"to": "a@b.com", "subject": "hi"}) == "sent to a@b.com: hi"


# ---- fail-closed when the guard itself errors --------------------------------


def test_fails_closed_when_policy_predicate_raises(tmp_path):
    from actionguard.audit import AuditLog

    def boom(_args):
        raise ValueError("predicate is buggy")

    ran = []

    @tool
    def do_thing(x: int) -> str:
        """Do."""
        ran.append(x)
        return "ran"

    audit = AuditLog(tmp_path / "audit.jsonl")
    guarded = guard(do_thing, policy=ApprovalPolicy(require_if=boom), audit=audit)
    out = guarded.invoke({"x": 1})
    assert "BLOCKED" in out  # fail closed, not a crash
    assert ran == []  # action did NOT run
    # the guard error must be recorded, not silently dropped
    rec = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["executed"] is False
    assert "predicate is buggy" in rec["error"]


def test_fails_closed_when_channel_raises(audit_log):
    class ExplodingChannel(ApprovalChannel):
        def request_approval(self, action):
            raise RuntimeError("channel down")

    ran = []

    @tool
    def do_thing(x: int) -> str:
        """Do."""
        ran.append(x)
        return "ran"

    guarded = guard(
        do_thing,
        policy=ApprovalPolicy(require_always=True),
        channel=ExplodingChannel(),
        audit=audit_log,
    )
    out = guarded.invoke({"x": 1})
    assert "BLOCKED" in out
    assert ran == []


# ---- guard_tools ------------------------------------------------------------


def test_guard_tools_wraps_each_and_shares_config(auto_approve, audit_log):
    @tool
    def a(x: int) -> int:
        """A."""
        return x

    @tool
    def b(x: int) -> int:
        """B."""
        return x + 1

    guarded = guard_tools(
        [a, b], policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit_log
    )
    assert [g.name for g in guarded] == ["a", "b"]
    assert all(isinstance(g, ApprovalWrappedTool) for g in guarded)
    assert guarded[0].invoke({"x": 1}) == 1
    assert guarded[1].invoke({"x": 1}) == 2
    assert len(auto_approve.requests) == 2
