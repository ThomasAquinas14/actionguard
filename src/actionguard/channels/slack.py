"""Slack approval channel (v0).

Posts the proposed action to a Slack **incoming webhook** so a human can see it, then
waits for a decision. Incoming webhooks are one-way (Slack can receive the message but
cannot send a button click back to your process), so the approve/deny signal comes from
a ``poll_fn`` you provide — anything that can tell us "has a human answered yet?".

If you do not provide a ``poll_fn``, the channel posts the notification and then blocks
until ``timeout`` seconds elapse, at which point it returns ``on_timeout`` (deny by
default). That is intentionally conservative: a Slack message nobody acted on must not
silently approve an irreversible action.

Full interactive Slack (Block Kit buttons wired to a request URL, threaded replies,
identity of the approver) is on the roadmap — see ROADMAP.md. The ``poll_fn`` hook is
the seam where that, or your own store/queue, plugs in today.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Callable, Optional

from ..core import Action, Decision, sanitize_for_display
from .base import ApprovalChannel

PollFn = Callable[[Action], Optional[Decision]]


def _slack_safe(text: str) -> str:
    """Make a string safe to drop into Slack mrkdwn without forging the message.

    Slack treats ``&``, ``<`` and ``>`` as metacharacters, and a backtick inside an
    inline-code span closes it — an argument value containing one could otherwise break
    out and alter the approval message's formatting. We neutralize control characters,
    HTML-escape the three metacharacters, and swap backticks for a visually similar
    character (U+02CB) that cannot terminate a code span.
    """
    text = sanitize_for_display(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("`", "ˋ")


class SlackChannel(ApprovalChannel):
    """Notify Slack about a pending action and wait for a decision.

    Parameters
    ----------
    webhook_url:
        A Slack incoming-webhook URL. The proposed action is POSTed here.
    poll_fn:
        ``fn(action) -> Decision | None``. Called repeatedly until it returns a
        :class:`Decision` (or the timeout is hit). Return ``None`` to keep waiting.
        This is where you read whatever store your Slack app writes approvals to.
        If omitted, the channel just waits for the timeout.
    timeout:
        Maximum seconds to wait for a decision before returning ``on_timeout``.
    poll_interval:
        Seconds between ``poll_fn`` calls.
    on_timeout:
        ``"deny"`` (default, safe) or ``"approve"`` — what to decide if no answer
        arrives before ``timeout``.
    post_timeout:
        Per-request network timeout (seconds) for the webhook POST, so a hung Slack
        connection can't block an approval indefinitely.
    session:
        Optional ``requests``-style session (must expose ``.post(url, json=...)``).
        Injectable for testing; defaults to the ``requests`` module.
    """

    name = "slack"

    def __init__(
        self,
        webhook_url: str,
        *,
        poll_fn: Optional[PollFn] = None,
        timeout: float = 300.0,
        poll_interval: float = 5.0,
        on_timeout: str = "deny",
        post_timeout: float = 10.0,
        session: Optional[object] = None,
    ) -> None:
        if on_timeout not in {"deny", "approve"}:
            raise ValueError("on_timeout must be 'deny' or 'approve'")
        self.webhook_url = webhook_url
        self.poll_fn = poll_fn
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.on_timeout = on_timeout
        self.post_timeout = post_timeout
        self._session = session

    def _poster(self):
        if self._session is not None:
            return self._session
        try:
            import requests  # noqa: PLC0415 — optional dependency, imported lazily
        except ImportError as exc:  # pragma: no cover - exercised via message only
            raise ImportError(
                "SlackChannel needs the 'requests' package. Install it with "
                "`pip install actionguard[slack]` (or `pip install requests`)."
            ) from exc
        return requests

    def _post(self, action: Action) -> None:
        about = (
            f"*About:* {_slack_safe(action.tool_description.strip().splitlines()[0])}\n"
            if action.tool_description
            else ""
        )
        text = (
            f":rotating_light: *actionguard — approval required*\n"
            f"*Tool:* `{_slack_safe(action.tool_name)}`\n"
            + about
            + "*Arguments:*\n"
            + "\n".join(
                f"• `{_slack_safe(k)}` = `{_slack_safe(repr(v))}`" for k, v in action.args.items()
            )
        )
        response = self._poster().post(
            self.webhook_url, json={"text": text}, timeout=self.post_timeout
        )
        # Fail closed: if Slack didn't accept the message, the human never saw it, so we
        # must not fall through to waiting for / reading a decision as though they had.
        # The raised error propagates to the wrapper, which fails closed (the action does
        # not run). Guarded with getattr so injected test sessions need not provide it.
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            raise_for_status()

    def request_approval(self, action: Action) -> Decision:
        self._post(action)

        if self.poll_fn is None:
            # Nothing to read decisions from; wait out the clock, then fail safe.
            time.sleep(self.timeout)
            return self._timeout_decision()

        deadline = time.monotonic() + self.timeout
        while True:
            decision = self.poll_fn(action)
            if decision is not None:
                # Backfill the source without mutating the caller's Decision object.
                if decision.source is None:
                    decision = replace(decision, source=self.name)
                return decision
            if time.monotonic() >= deadline:
                return self._timeout_decision()
            remaining = deadline - time.monotonic()
            time.sleep(min(self.poll_interval, max(0.0, remaining)))

    def _timeout_decision(self) -> Decision:
        approved = self.on_timeout == "approve"
        return Decision(
            approved=approved,
            comment=f"no response within {self.timeout:g}s; defaulted to {self.on_timeout}",
            source=self.name,
        )
