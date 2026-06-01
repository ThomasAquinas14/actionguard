"""Policy logic: predicates, thresholds, regex, and the safe default."""

from __future__ import annotations

import re

import pytest

from actionguard import ApprovalPolicy


def test_empty_policy_requires_approval_for_everything():
    # The safe default: no rules => hold every call.
    policy = ApprovalPolicy()
    assert policy.needs_approval({}) is True
    assert policy.needs_approval({"amount": 0}) is True


def test_require_always_true():
    policy = ApprovalPolicy(require_always=True)
    assert policy.needs_approval({"amount": 1}) is True


def test_require_always_false_is_an_allow_all_escape_hatch():
    policy = ApprovalPolicy(require_always=False)
    assert policy.needs_approval({"amount": 999999}) is False


def test_require_if_predicate():
    policy = ApprovalPolicy(require_if=lambda a: a.get("amount", 0) > 100)
    assert policy.needs_approval({"amount": 4000}) is True
    assert policy.needs_approval({"amount": 5}) is False
    assert policy.needs_approval({}) is False


def test_amount_over_threshold():
    policy = ApprovalPolicy(amount_over={"arg": "amount", "threshold": 100})
    assert policy.needs_approval({"amount": 100.01}) is True
    assert policy.needs_approval({"amount": 100}) is False  # strictly greater
    assert policy.needs_approval({"amount": 5}) is False
    assert policy.needs_approval({"amount": "lots"}) is False  # non-numeric ignored
    assert policy.needs_approval({}) is False  # missing arg ignored


def test_amount_over_ignores_bools():
    # True == 1 in Python; make sure a boolean flag doesn't trip a numeric threshold.
    policy = ApprovalPolicy(amount_over={"arg": "flag", "threshold": 0})
    assert policy.needs_approval({"flag": True}) is False


def test_amount_over_requires_valid_config():
    with pytest.raises(ValueError):
        ApprovalPolicy(amount_over={"threshold": 100})
    with pytest.raises(ValueError):
        ApprovalPolicy(amount_over={"arg": "amount"})


def test_amount_over_threshold_must_be_numeric():
    # Caught at construction, not at the moment an agent is about to act.
    with pytest.raises(ValueError):
        ApprovalPolicy(amount_over={"arg": "amount", "threshold": "100"})
    with pytest.raises(ValueError):
        ApprovalPolicy(amount_over={"arg": "amount", "threshold": True})


def test_match_args_regex():
    policy = ApprovalPolicy(match_args={"customer_id": r"^prod-"})
    assert policy.needs_approval({"customer_id": "prod-123"}) is True
    assert policy.needs_approval({"customer_id": "test-123"}) is False
    assert policy.needs_approval({}) is False


def test_match_args_coerces_non_strings():
    policy = ApprovalPolicy(match_args={"account": r"42"})
    assert policy.needs_approval({"account": 4242}) is True


def test_bad_regex_fails_at_construction_time():
    with pytest.raises(re.error):
        ApprovalPolicy(match_args={"x": "([unclosed"})


def test_rules_are_ored_together():
    policy = ApprovalPolicy(
        amount_over={"arg": "amount", "threshold": 100},
        match_args={"customer_id": r"^prod-"},
    )
    # amount triggers
    assert policy.needs_approval({"amount": 200, "customer_id": "test-1"}) is True
    # regex triggers
    assert policy.needs_approval({"amount": 1, "customer_id": "prod-9"}) is True
    # neither triggers
    assert policy.needs_approval({"amount": 1, "customer_id": "test-1"}) is False
