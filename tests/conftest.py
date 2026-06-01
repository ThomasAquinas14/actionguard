"""Shared test doubles and fixtures."""

from __future__ import annotations

import pytest

from actionguard.audit import AuditLog
from actionguard.channels.base import ApprovalChannel
from actionguard.core import Action, Decision


class AutoApproveChannel(ApprovalChannel):
    """A channel that approves everything and records what it was asked."""

    name = "auto-approve"

    def __init__(self) -> None:
        self.requests: list[Action] = []

    def request_approval(self, action: Action) -> Decision:
        self.requests.append(action)
        return Decision(approved=True, source=self.name)


class AutoDenyChannel(ApprovalChannel):
    """A channel that denies everything and records what it was asked."""

    name = "auto-deny"

    def __init__(self, comment: str = "nope") -> None:
        self.comment = comment
        self.requests: list[Action] = []

    def request_approval(self, action: Action) -> Decision:
        self.requests.append(action)
        return Decision(approved=False, comment=self.comment, source=self.name)


@pytest.fixture
def auto_approve() -> AutoApproveChannel:
    return AutoApproveChannel()


@pytest.fixture
def auto_deny() -> AutoDenyChannel:
    return AutoDenyChannel()


@pytest.fixture
def audit_log(tmp_path) -> AuditLog:
    """An audit log writing to a throwaway file under the test's tmp dir."""
    return AuditLog(tmp_path / "audit.jsonl")
