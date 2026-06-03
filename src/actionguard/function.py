"""Framework-agnostic guarding: wrap *any* Python callable, not just LangChain tools.

This is the same idea as the LangChain wrapper, but for a plain function: evaluate the
policy on the call's arguments, ask a human if needed, then run the function or block.
Because a plain function has no agent loop to hand a message back to, a denied call
**raises** :class:`ApprovalDenied` by default (set ``on_denied="return"`` to get the
denial string back instead).

The wrapper preserves the function's identity with :func:`functools.wraps` (name,
docstring, and — via ``__wrapped__`` — its signature), so other frameworks that
introspect the callable still see the original.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from typing import Any, Callable, Optional

from .audit import AuditLog
from .channels.base import ApprovalChannel
from .core import Action, Decision, denial_message
from .policy import ApprovalPolicy


class ApprovalDenied(Exception):
    """Raised when a guarded callable's action is denied by a human reviewer.

    Carries the :class:`~actionguard.core.Action` and :class:`~actionguard.core.Decision`
    so a caller can inspect what was blocked and why.
    """

    def __init__(
        self,
        message: str,
        *,
        action: Action,
        decision: Optional[Decision] = None,
    ) -> None:
        super().__init__(message)
        self.action = action
        self.decision = decision


def _policy_args(func: Callable[..., Any], args: tuple, kwargs: dict) -> dict[str, Any]:
    """Build a flat ``{name: value}`` dict of the call's arguments for the policy.

    Mirrors what a LangChain tool's policy sees: argument names mapped to values, with
    defaults applied. ``self``/``cls`` are dropped, and a ``**kwargs`` catch-all is
    flattened to the top level so a predicate like ``args["amount"]`` works whether
    ``amount`` is a declared parameter or passed through ``**kwargs``.
    """
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
    except (TypeError, ValueError):
        # Signature couldn't be resolved/bound (e.g. a builtin, or a bad call that the
        # real invocation will reject anyway). Fall back to the explicit kwargs.
        return dict(kwargs)
    bound.apply_defaults()

    out: dict[str, Any] = {}
    for name, value in bound.arguments.items():
        if name in ("self", "cls"):
            continue
        param = sig.parameters.get(name)
        if (
            param is not None
            and param.kind is inspect.Parameter.VAR_KEYWORD
            and isinstance(value, dict)
        ):
            out.update(value)  # flatten **kwargs
            continue
        out[name] = value
    return out


def _wrap_callable(
    func: Callable[..., Any],
    *,
    policy: ApprovalPolicy,
    channel: ApprovalChannel,
    audit: AuditLog,
    on_denied: str = "raise",
) -> Callable[..., Any]:
    """Wrap ``func`` so risky calls pause for approval. Returns a callable of the same
    shape (sync wraps sync, async wraps async)."""
    if on_denied not in ("raise", "return"):
        raise ValueError("on_denied must be 'raise' or 'return'")

    name = getattr(func, "__name__", None) or repr(func)
    doc = inspect.getdoc(func)
    description = doc.splitlines()[0] if doc else None

    def _action(args: tuple, kwargs: dict) -> Action:
        return Action(
            tool_name=name,
            args=_policy_args(func, args, kwargs),
            tool_description=description,
        )

    def _denied(action: Action, decision: Decision) -> Any:
        audit.record(action=action, needed_approval=True, decision=decision, executed=False)
        message = denial_message(action, decision)
        if on_denied == "return":
            return message
        raise ApprovalDenied(message, action=action, decision=decision)

    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def awrapper(*args: Any, **kwargs: Any) -> Any:
            action = _action(args, kwargs)
            # Fail closed: a guard error must not let the action run (see langchain.py).
            try:
                needed = policy.needs_approval(action.args)
                decision: Optional[Decision] = (
                    await asyncio.to_thread(channel.request_approval, action) if needed else None
                )
            except Exception as exc:
                audit.record(
                    action=action, needed_approval=True, decision=None, executed=False, error=exc
                )
                raise
            if needed and not decision.approved:
                return _denied(action, decision)
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                # Post-execution: the call was attempted, so record best-effort and let
                # the *original* error surface — never let an audit write mask it.
                audit.record_safely(
                    action=action,
                    needed_approval=needed,
                    decision=decision,
                    executed=False,
                    error=exc,
                )
                raise
            audit.record_safely(
                action=action,
                needed_approval=needed,
                decision=decision,
                executed=True,
                result=result,
            )
            return result

        return awrapper

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        action = _action(args, kwargs)
        try:
            needed = policy.needs_approval(action.args)
            decision: Optional[Decision] = channel.request_approval(action) if needed else None
        except Exception as exc:
            audit.record(
                action=action, needed_approval=True, decision=None, executed=False, error=exc
            )
            raise
        if needed and not decision.approved:
            return _denied(action, decision)
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            # Post-execution: record best-effort and re-raise the original error (see
            # the async path above) — an audit failure must not look like a tool failure.
            audit.record_safely(
                action=action, needed_approval=needed, decision=decision, executed=False, error=exc
            )
            raise
        audit.record_safely(
            action=action, needed_approval=needed, decision=decision, executed=True, result=result
        )
        return result

    return wrapper
