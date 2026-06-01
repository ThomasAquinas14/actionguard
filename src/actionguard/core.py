"""Core data types shared across actionguard.

An :class:`Action` is a proposed tool call that has not run yet. A :class:`Decision`
is a human's answer about whether it may run. Approval channels turn the former into
the latter; the LangChain wrapper enforces the result and records it to the audit log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Control characters (C0 + C1, incl. ESC/CR/backspace) that could be used to forge or
# hide what an approver sees in a terminal or chat client. We escape them before display.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sanitize_for_display(value: Any) -> str:
    """Render ``value`` as a single-line string with control characters neutralized.

    The approval banner is the human's entire basis for a yes/no, so a tool name,
    description, or argument key carrying ``\\x1b[2K`` or ``\\r`` must not be able to
    overwrite or hide the displayed action. Argument *values* are shown via ``repr``
    (which already escapes control characters); this helper covers the rest.
    """
    return _CONTROL_CHARS.sub(lambda m: f"\\x{ord(m.group()):02x}", str(value))


@dataclass
class Action:
    """A proposed tool call awaiting a decision.

    This is what gets shown to a human (and written to the audit log). It is the
    state of the world *before* anything irreversible happens.
    """

    tool_name: str
    args: dict[str, Any]
    tool_description: Optional[str] = None

    def pretty(self) -> str:
        """A compact, human-readable rendering of the proposed call."""
        arg_str = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
        return f"{self.tool_name}({arg_str})"


@dataclass
class Decision:
    """A human's answer to an approval request."""

    approved: bool
    comment: Optional[str] = None
    # Which channel produced this decision (e.g. "cli", "slack"). Useful in audits.
    source: Optional[str] = None
    # Free-form extra context a channel may attach (who approved, message ts, ...).
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def approve(cls, comment: Optional[str] = None, **kw: Any) -> "Decision":
        return cls(approved=True, comment=comment, **kw)

    @classmethod
    def deny(cls, comment: Optional[str] = None, **kw: Any) -> "Decision":
        return cls(approved=False, comment=comment, **kw)


def denial_message(action: Action, decision: Optional[Decision]) -> str:
    """The string returned *to the agent* when a call is blocked.

    It is phrased so the model understands the action did not happen and why, and
    can choose a different course rather than blindly retrying.
    """
    base = (
        f"DENIED: the action `{action.pretty()}` was blocked by a human reviewer "
        f"and was NOT executed."
    )
    if decision is not None and decision.comment:
        base += f" Reviewer note: {decision.comment}"
    base += " Do not retry it unchanged; consider an alternative or ask the user."
    return base


def guard_error_message(action: Action, error: Exception) -> str:
    """The string returned *to the agent* when the guard itself errors.

    If evaluating the policy or asking for approval raises, actionguard fails **closed**:
    the action is not executed, the error is recorded to the audit log, and the agent is
    told plainly that the guard could not make a decision.
    """
    return (
        f"BLOCKED: actionguard could not evaluate approval for `{action.pretty()}` "
        f"(internal guard error: {type(error).__name__}: {error}). The action was NOT "
        f"executed. This is a configuration/guard problem, not a denial — surface it to "
        f"the operator rather than retrying."
    )
