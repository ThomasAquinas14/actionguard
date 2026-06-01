"""Approval channels: where the human yes/no comes from."""

from .base import ApprovalChannel
from .cli import CLIChannel
from .slack import SlackChannel

__all__ = ["ApprovalChannel", "CLIChannel", "SlackChannel"]
