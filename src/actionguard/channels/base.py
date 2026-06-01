"""The approval-channel contract.

A channel is anything that can take a proposed :class:`~actionguard.core.Action` and
come back with a :class:`~actionguard.core.Decision`. The CLI channel asks at the
terminal; the Slack channel posts to a webhook. You can write your own by subclassing
:class:`ApprovalChannel` and implementing a single method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..core import Action, Decision


class ApprovalChannel(ABC):
    """Base class for approval channels.

    Implement :meth:`request_approval`: given an :class:`Action`, return a
    :class:`Decision`. The method may block (the CLI channel waits for a keypress;
    the Slack channel polls). It is always called from a synchronous context — the
    async tool path runs it in a worker thread for you — so you do not need to make
    it awaitable.
    """

    #: Short identifier recorded in the audit log (override in subclasses).
    name: str = "channel"

    @abstractmethod
    def request_approval(self, action: Action) -> Decision:
        """Ask a human about ``action`` and return their :class:`Decision`."""
        raise NotImplementedError
