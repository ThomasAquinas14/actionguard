"""Framework-agnostic guard: wrapping any plain callable (no LangChain)."""

from __future__ import annotations

import asyncio
import json

import pytest

from actionguard import ApprovalDenied, ApprovalPolicy, guard
from actionguard.audit import AuditLog

# ---- sync callables ---------------------------------------------------------


def test_plain_function_runs_when_approved(auto_approve, audit_log):
    @guard(policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit_log)
    def charge(amount: float, customer_id: str) -> str:
        return f"charged {amount} to {customer_id}"

    assert charge(50.0, "c1") == "charged 50.0 to c1"
    # policy/audit saw the bound argument names, like a LangChain tool would
    assert auto_approve.requests[0].args == {"amount": 50.0, "customer_id": "c1"}


def test_plain_function_raises_when_denied(auto_deny, audit_log):
    @guard(policy=ApprovalPolicy(require_always=True), channel=auto_deny, audit=audit_log)
    def delete_user(user_id: str) -> None:
        raise AssertionError("must not run when denied")

    with pytest.raises(ApprovalDenied) as exc:
        delete_user("u1")
    assert exc.value.action.tool_name == "delete_user"
    assert exc.value.decision is not None and exc.value.decision.approved is False


def test_on_denied_return_gives_message_instead_of_raising(auto_deny, audit_log):
    @guard(
        policy=ApprovalPolicy(require_always=True),
        channel=auto_deny,
        audit=audit_log,
        on_denied="return",
    )
    def delete_user(user_id: str) -> str:
        raise AssertionError("must not run when denied")

    out = delete_user("u1")
    assert isinstance(out, str)
    assert "DENIED" in out


def test_bad_on_denied_rejected(auto_deny, audit_log):
    with pytest.raises(ValueError):

        @guard(channel=auto_deny, audit=audit_log, on_denied="maybe")
        def f(x: int) -> int:
            return x


# ---- policy sees real args (defaults, positional, keyword, **kwargs) --------


def test_policy_threshold_on_plain_function(auto_deny, audit_log):
    @guard(
        policy=ApprovalPolicy(amount_over={"arg": "amount", "threshold": 100}),
        channel=auto_deny,
        audit=audit_log,
    )
    def charge(amount: float, currency: str = "USD") -> str:
        return f"charged {amount} {currency}"

    # under threshold: runs, channel not consulted; default applied
    assert charge(5.0) == "charged 5.0 USD"
    assert auto_deny.requests == []
    # over threshold: denied
    with pytest.raises(ApprovalDenied):
        charge(amount=4000.0)
    assert len(auto_deny.requests) == 1


def test_kwargs_catch_all_is_flattened(auto_approve, audit_log):
    @guard(policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit_log)
    def call_api(endpoint: str, **params) -> str:
        return endpoint

    call_api("/charge", amount=999, idempotency_key="k1")
    seen = auto_approve.requests[0].args
    assert seen["endpoint"] == "/charge"
    assert seen["amount"] == 999  # flattened from **params
    assert seen["idempotency_key"] == "k1"


def test_method_self_is_stripped(auto_approve, audit_log):
    class Billing:
        @guard(policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit_log)
        def refund(self, amount: float) -> str:
            return f"refunded {amount}"

    assert Billing().refund(10.0) == "refunded 10.0"
    assert "self" not in auto_approve.requests[0].args
    assert auto_approve.requests[0].args == {"amount": 10.0}


# ---- identity preservation --------------------------------------------------


def test_wraps_preserves_name_and_doc(auto_approve, audit_log):
    @guard(policy=ApprovalPolicy(require_always=False), channel=auto_approve, audit=audit_log)
    def my_action(x: int) -> int:
        """Do the thing."""
        return x

    assert my_action.__name__ == "my_action"
    assert my_action.__doc__ == "Do the thing."


# ---- async callables --------------------------------------------------------


def test_async_function_runs_when_approved(auto_approve, audit_log):
    @guard(policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit_log)
    async def send(to: str) -> str:
        return f"sent to {to}"

    assert asyncio.run(send("a@b.com")) == "sent to a@b.com"


def test_async_function_raises_when_denied(auto_deny, audit_log):
    @guard(policy=ApprovalPolicy(require_always=True), channel=auto_deny, audit=audit_log)
    async def send(to: str) -> str:
        raise AssertionError("must not run")

    with pytest.raises(ApprovalDenied):
        asyncio.run(send("a@b.com"))


# ---- fail-closed + audit ----------------------------------------------------


def test_fails_closed_when_predicate_raises(tmp_path):
    def boom(_a):
        raise ValueError("buggy predicate")

    ran = []

    @guard(policy=ApprovalPolicy(require_if=boom), audit=AuditLog(tmp_path / "a.jsonl"))
    def act(x: int) -> int:
        ran.append(x)
        return x

    # guard error fails closed: function not run, original error surfaced + audited
    with pytest.raises(ValueError):
        act(1)
    assert ran == []
    rec = json.loads((tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["executed"] is False
    assert "buggy predicate" in rec["error"]


def test_audit_records_approved_run(tmp_path, auto_approve):
    audit = AuditLog(tmp_path / "a.jsonl")

    @guard(policy=ApprovalPolicy(require_always=True), channel=auto_approve, audit=audit)
    def act(x: int) -> str:
        return f"did {x}"

    act(7)
    rec = json.loads((tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["tool"] == "act"
    assert rec["args"] == {"x": 7}
    assert rec["approved"] is True
    assert rec["executed"] is True
    assert rec["result"] == "did 7"
