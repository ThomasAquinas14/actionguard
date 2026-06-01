"""Approval policies: decide whether a given tool call needs a human's sign-off.

A policy looks at the *arguments* a tool is about to be called with and answers a
single yes/no question: does a human need to approve this before it runs?

The safe default is **yes**. An :class:`ApprovalPolicy` with no rules configured
requires approval for every call, so wrapping a tool without thinking about it can
never make that tool *less* safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ApprovalPolicy:
    """Decide whether a tool call requires human approval.

    All configured rules are combined with OR semantics: if *any* rule says
    "needs approval", the call is held. The rules, in the order they are checked:

    - ``require_always``: when ``True``, every call needs approval. When ``False``,
      it is an explicit "never require" escape hatch (other rules still apply).
    - ``require_if``: an arbitrary predicate ``fn(args_dict) -> bool``.
    - ``amount_over``: e.g. ``{"arg": "amount", "threshold": 100}`` — hold the call
      when the named numeric argument is strictly greater than ``threshold``.
    - ``match_args``: e.g. ``{"customer_id": r"^prod-"}`` — hold the call when the
      named argument's string form matches the given regular expression.

    If **no** rules are configured at all, the policy defaults to requiring
    approval for every call (the safe default).

    Examples
    --------
    >>> ApprovalPolicy(require_always=True).needs_approval({})
    True
    >>> p = ApprovalPolicy(amount_over={"arg": "amount", "threshold": 100})
    >>> p.needs_approval({"amount": 4000})
    True
    >>> p.needs_approval({"amount": 5})
    False
    >>> ApprovalPolicy().needs_approval({"anything": 1})  # default-deny
    True
    """

    require_if: Optional[Callable[[dict[str, Any]], bool]] = None
    require_always: Optional[bool] = None
    amount_over: Optional[dict[str, Any]] = None
    match_args: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.amount_over is not None:
            if "arg" not in self.amount_over or "threshold" not in self.amount_over:
                raise ValueError(
                    "amount_over must be a dict with 'arg' and 'threshold' keys, "
                    f"e.g. {{'arg': 'amount', 'threshold': 100}}; got {self.amount_over!r}"
                )
            threshold = self.amount_over["threshold"]
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                raise ValueError(
                    "amount_over['threshold'] must be a number (int or float); "
                    f"got {threshold!r}. This is validated now rather than at the moment "
                    "an agent is about to act."
                )
        # Pre-compile regexes early so a bad pattern fails loudly at construction
        # time rather than at the moment an agent is about to act.
        self._compiled = {name: re.compile(pat) for name, pat in self.match_args.items()}

    @property
    def _has_rules(self) -> bool:
        return (
            self.require_if is not None
            or self.require_always is not None
            or self.amount_over is not None
            or bool(self.match_args)
        )

    def needs_approval(self, args: dict[str, Any]) -> bool:
        """Return ``True`` if a call with these ``args`` must be approved by a human."""
        # Safe default: an empty policy holds everything.
        if not self._has_rules:
            return True

        if self.require_always is True:
            return True

        if self.require_if is not None and self.require_if(args):
            return True

        if self.amount_over is not None:
            value = args.get(self.amount_over["arg"])
            threshold = self.amount_over["threshold"]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if value > threshold:
                    return True

        for name, pattern in self._compiled.items():
            value = args.get(name)
            if value is not None and pattern.search(str(value)):
                return True

        return False
