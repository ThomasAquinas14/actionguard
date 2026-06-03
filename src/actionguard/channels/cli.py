"""The default approval channel: a blocking terminal y/n prompt.

Zero setup, no network, no accounts. Works in any plain Python script, REPL, or
notebook with a console. This is what every example uses.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional, TextIO

from ..core import Action, Decision, sanitize_for_display
from .base import ApprovalChannel


def _emit(stream: TextIO, text: str) -> None:
    """Print to ``stream`` without ever crashing on a non-UTF-8 console.

    Windows consoles default to cp1252, which cannot encode the box-drawing and emoji
    characters in the banner. Rather than let an approval prompt die with a
    ``UnicodeEncodeError`` (which would be far worse than ugly output), fall back to a
    best-effort re-encoding that drops only the characters the console can't render.
    """
    try:
        print(text, file=stream, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe, file=stream, flush=True)


class CLIChannel(ApprovalChannel):
    """Ask for approval at the terminal.

    Prints the proposed tool call and its arguments, then reads a single ``y``/``n``
    from stdin. Anything that is not an affirmative answer is treated as a denial —
    the safe default — so an empty line or an EOF (piped/non-interactive stdin) blocks
    the call rather than letting it through.

    Parameters
    ----------
    stream:
        Where to print the prompt. Defaults to ``sys.stderr`` so the prompt does not
        get tangled up with a program's stdout.
    input_fn:
        The function used to read the answer. Defaults to the builtin :func:`input`;
        override it in tests or to wire up a custom reader.
    """

    name = "cli"

    def __init__(
        self,
        *,
        stream: Optional[TextIO] = None,
        input_fn: Callable[[str], str] = input,
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._input_fn = input_fn

    def request_approval(self, action: Action) -> Decision:
        # Everything shown is sanitized so a malicious tool/arg can't forge the banner
        # the human is deciding on (see core.sanitize_for_display). repr() escapes
        # control chars inside *str* values, but an object argument can carry a custom
        # __repr__ with raw escapes, so we sanitize the repr output too.
        args_block = (
            "\n".join(
                f"    {sanitize_for_display(k)} = {sanitize_for_display(repr(v))}"
                for k, v in action.args.items()
            )
            if action.args
            else "    (no arguments)"
        )
        banner = (
            "\n"
            "──────────────────────────────────────────────────────────────\n"
            " 🛑 actionguard — approval required\n"
            "──────────────────────────────────────────────────────────────\n"
            f" Tool:   {sanitize_for_display(action.tool_name)}\n"
        )
        if action.tool_description:
            about = sanitize_for_display(action.tool_description.strip().splitlines()[0])
            banner += f" About:  {about}\n"
        banner += (
            " Args:\n"
            f"{args_block}\n"
            "──────────────────────────────────────────────────────────────"
        )
        _emit(self._stream, banner)

        try:
            answer = self._input_fn("Approve this action? [y/N] ")
        except EOFError:
            # Non-interactive stdin (piped input that ran out): fail safe.
            _emit(self._stream, " No input available — denying.")
            return Decision.deny(comment="no input available (non-interactive)", source=self.name)

        approved = answer.strip().lower() in {"y", "yes"}
        verdict = " ✅ approved" if approved else " ⛔ denied"
        _emit(self._stream, verdict)
        return Decision(approved=approved, source=self.name)
