"""The LangChain integration: ``guard`` and ``guard_tools``.

Wrapping a tool produces a new tool that is *indistinguishable to the agent* — same
name, description, and args schema — but routes risky calls through a policy and (when
needed) a human before the real tool runs.

The wrapper subclasses :class:`~langchain_core.tools.BaseTool` and delegates to the
inner tool's public ``invoke``/``ainvoke``. Delegating through the public path (rather
than poking at ``.func``/``.coroutine``) preserves the inner tool's own input
validation, callbacks, and error handling, and works whether the tool implements sync,
async, or both.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Union

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool

from .audit import AuditLog
from .channels.base import ApprovalChannel
from .channels.cli import CLIChannel
from .core import Action, Decision, denial_message, guard_error_message
from .function import _wrap_callable
from .policy import ApprovalPolicy


class ApprovalWrappedTool(BaseTool):
    """A :class:`BaseTool` that gates an inner tool behind a policy + approval channel.

    You normally create these with :func:`guard` / :func:`guard_tools` rather than
    constructing them directly.
    """

    # Non-pydantic collaborators live on the model; allow them.
    model_config = {"arbitrary_types_allowed": True}

    inner_tool: BaseTool
    policy: ApprovalPolicy
    channel: ApprovalChannel
    audit: AuditLog

    # ---- decision + bookkeeping shared by the sync and async paths ----------

    def _action(self, kwargs: dict[str, Any]) -> Action:
        return Action(
            tool_name=self.name,
            args=dict(kwargs),
            tool_description=self.description,
        )

    def _needs_approval(self, action: Action) -> bool:
        return self.policy.needs_approval(action.args)

    def _on_denied(self, action: Action, decision: Decision) -> str:
        self.audit.record(
            action=action,
            needed_approval=True,
            decision=decision,
            executed=False,
        )
        return denial_message(action, decision)

    def _on_guard_error(self, action: Action, error: Exception) -> str:
        self.audit.record(
            action=action,
            needed_approval=True,
            decision=None,
            executed=False,
            error=error,
        )
        return guard_error_message(action, error)

    def _on_result(
        self,
        action: Action,
        *,
        needed_approval: bool,
        decision: Optional[Decision],
        result: Any = None,
        error: Any = None,
    ) -> None:
        # Post-execution: the inner tool has already run (or raised). A failure to write
        # this record must not turn a completed action into an error the agent retries,
        # so record best-effort and warn rather than raising. (The pre-execution denial
        # and guard-error records stay strict — they fail closed before anything runs.)
        self.audit.record_safely(
            action=action,
            needed_approval=needed_approval,
            decision=decision,
            executed=error is None,
            result=result,
            error=error,
        )

    @staticmethod
    def _child_config(run_manager: Optional[Any]) -> Optional[dict[str, Any]]:
        # Forward callbacks so the inner tool's run nests under ours in tracing.
        if run_manager is None:
            return None
        return {"callbacks": run_manager.get_child()}

    # ---- sync path ----------------------------------------------------------

    def _run(
        self,
        *args: Any,
        run_manager: Optional[CallbackManagerForToolRun] = None,
        **kwargs: Any,
    ) -> Any:
        action = self._action(kwargs)

        # Fail CLOSED: if evaluating the policy or asking for approval raises, the
        # irreversible action must not run. Record the error and tell the agent.
        try:
            needed = self._needs_approval(action)
            decision: Optional[Decision] = self.channel.request_approval(action) if needed else None
        except Exception as exc:
            return self._on_guard_error(action, exc)

        if needed and not decision.approved:
            return self._on_denied(action, decision)

        config = self._child_config(run_manager)
        try:
            result = self.inner_tool.invoke(kwargs, config=config)
        except Exception as exc:
            self._on_result(action, needed_approval=needed, decision=decision, error=exc)
            raise
        self._on_result(action, needed_approval=needed, decision=decision, result=result)
        return result

    # ---- async path ---------------------------------------------------------

    async def _arun(
        self,
        *args: Any,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
        **kwargs: Any,
    ) -> Any:
        action = self._action(kwargs)

        # Fail CLOSED, same as the sync path (see _run).
        try:
            needed = self._needs_approval(action)
            decision: Optional[Decision] = None
            if needed:
                # Channels are synchronous (and may block on input/network); run off
                # the event loop so we don't stall everything else awaiting concurrently.
                decision = await asyncio.to_thread(self.channel.request_approval, action)
        except Exception as exc:
            return self._on_guard_error(action, exc)

        if needed and not decision.approved:
            return self._on_denied(action, decision)

        config = self._child_config(run_manager)
        try:
            result = await self.inner_tool.ainvoke(kwargs, config=config)
        except Exception as exc:
            self._on_result(action, needed_approval=needed, decision=decision, error=exc)
            raise
        self._on_result(action, needed_approval=needed, decision=decision, result=result)
        return result


def _wrap_one(
    tool: BaseTool,
    *,
    policy: ApprovalPolicy,
    channel: ApprovalChannel,
    audit: AuditLog,
) -> ApprovalWrappedTool:
    if not isinstance(tool, BaseTool):
        raise TypeError(
            "guard expects a LangChain tool (a BaseTool / @tool-decorated function); "
            f"got {type(tool).__name__}. If you have a plain function, decorate it with "
            "@tool first."
        )
    # Some BaseTool subclasses leave args_schema=None and infer their schema from the
    # _run signature. Copying that None would make the wrapper infer from ITS own
    # (*args, **kwargs) signature and expose a bogus schema, so derive a real one.
    args_schema = tool.args_schema if tool.args_schema is not None else tool.get_input_schema()

    return ApprovalWrappedTool(
        # Identical model-facing surface → the agent cannot tell it was wrapped.
        name=tool.name,
        description=tool.description,
        args_schema=args_schema,
        return_direct=tool.return_direct,
        metadata=tool.metadata,
        tags=tool.tags,
        inner_tool=tool,
        policy=policy,
        channel=channel,
        audit=audit,
    )


def _resolve_policy(policy: Optional[ApprovalPolicy]) -> ApprovalPolicy:
    # No policy → the safe default: require approval for everything.
    return policy if policy is not None else ApprovalPolicy()


def _resolve_channel(channel: Optional[ApprovalChannel]) -> ApprovalChannel:
    return channel if channel is not None else CLIChannel()


def _resolve_audit(audit: Optional[Union[AuditLog, str]]) -> AuditLog:
    if isinstance(audit, AuditLog):
        return audit
    if audit is None:
        return AuditLog()
    return AuditLog(audit)  # treat a string/path as an audit file location


def guard(
    target: Optional[Any] = None,
    *,
    policy: Optional[ApprovalPolicy] = None,
    channel: Optional[ApprovalChannel] = None,
    audit: Optional[Union[AuditLog, str]] = None,
    on_denied: str = "raise",
) -> Any:
    """Wrap a tool *or any callable* so risky calls pause for human approval.

    Works on a LangChain ``BaseTool`` / ``@tool`` function **and** on any plain Python
    callable. The behaviour adapts to what it wraps:

    - **A LangChain tool** → returns a guarded tool that is identical to the agent
      (same name/description/args schema). A denied call returns a denial *message* to
      the agent (so the agent loop continues).
    - **Any other callable** → returns a function of the same shape (sync or async). A
      denied call **raises** :class:`ApprovalDenied` by default, or returns the denial
      string if ``on_denied="return"``.

    Usable directly or as a parameterised decorator::

        @guard(policy=ApprovalPolicy(require_if=lambda a: a["amount"] > 100))
        @tool
        def refund_customer(amount: float, customer_id: str) -> str: ...

        @guard(policy=ApprovalPolicy(require_always=True))   # plain function — no LangChain
        def delete_user(user_id: str) -> None: ...

        safe = guard(refund_customer, policy=my_policy)       # or call it directly

    Parameters
    ----------
    target:
        The tool or callable to wrap. Omit it to use ``guard`` as a parameterised decorator.
    policy:
        When to require approval. Defaults to "require approval for every call".
    channel:
        Where the human answers. Defaults to :class:`CLIChannel` (a terminal prompt).
    audit:
        An :class:`AuditLog`, a path string, or ``None`` for the default log file.
    on_denied:
        For plain callables only: ``"raise"`` (default) to raise :class:`ApprovalDenied`
        on denial, or ``"return"`` to return the denial message string instead. Ignored
        for LangChain tools (they always return the message to the agent).
    """
    resolved_policy = _resolve_policy(policy)
    resolved_channel = _resolve_channel(channel)
    resolved_audit = _resolve_audit(audit)

    def decorator(obj: Any) -> Any:
        if isinstance(obj, BaseTool):
            return _wrap_one(
                obj,
                policy=resolved_policy,
                channel=resolved_channel,
                audit=resolved_audit,
            )
        if callable(obj):
            return _wrap_callable(
                obj,
                policy=resolved_policy,
                channel=resolved_channel,
                audit=resolved_audit,
                on_denied=on_denied,
            )
        raise TypeError(
            "guard expects a LangChain tool or any callable; "
            f"got {type(obj).__name__}, which is not callable."
        )

    if target is not None:
        return decorator(target)
    return decorator


def guard_tools(
    tools: list[BaseTool],
    *,
    policy: Optional[ApprovalPolicy] = None,
    channel: Optional[ApprovalChannel] = None,
    audit: Optional[Union[AuditLog, str]] = None,
) -> list[BaseTool]:
    """Wrap many tools at once, sharing one policy, channel, and audit log.

    Returns a new list; the originals are left untouched, so you can hand the guarded
    list straight to your agent constructor::

        guarded = guard_tools(my_tools, policy=my_policy)
        agent = create_agent(llm, guarded)
    """
    resolved_policy = _resolve_policy(policy)
    resolved_channel = _resolve_channel(channel)
    resolved_audit = _resolve_audit(audit)
    return [
        _wrap_one(
            tool,
            policy=resolved_policy,
            channel=resolved_channel,
            audit=resolved_audit,
        )
        for tool in tools
    ]
