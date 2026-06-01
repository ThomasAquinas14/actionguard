"""Append-only JSONL audit log.

This is the trust surface. Every intercepted call produces exactly one record so you
can answer, after the fact: what did the agent try to do, did policy hold it, what did
the human decide, did it run, and what happened. One JSON object per line.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Optional, Union

from .core import Action, Decision

DEFAULT_AUDIT_PATH = "actionguard_audit.jsonl"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_repr(value: Any, limit: int = 2000) -> Optional[str]:
    """Render a result/error to a short, JSON-safe string (or None)."""
    if value is None:
        return None
    try:
        text = value if isinstance(value, str) else repr(value)
    except Exception:  # pragma: no cover - defensive
        text = "<unrepresentable>"
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


class AuditLog:
    """Append-only JSONL writer for intercepted tool calls.

    Parameters
    ----------
    path:
        File to append records to. Defaults to ``actionguard_audit.jsonl`` in the
        current working directory.
    enabled:
        Set ``False`` to turn auditing off (records become no-ops). Handy in tests.

    The writer is thread-safe and flushes after every record. A denied call is recorded
    before control returns; an executed call is recorded immediately after the tool
    returns (so the result/error can be captured in the same record).
    """

    def __init__(
        self,
        path: Union[str, os.PathLike[str]] = DEFAULT_AUDIT_PATH,
        *,
        enabled: bool = True,
    ) -> None:
        self.path = os.fspath(path)
        self.enabled = enabled
        self._lock = threading.Lock()
        if self.enabled:
            # Create the parent directory up front, so a missing dir surfaces here
            # rather than as a crash *after* an irreversible action has already run.
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)

    def record(
        self,
        *,
        action: Action,
        needed_approval: bool,
        decision: Optional[Decision],
        executed: bool,
        result: Any = None,
        error: Any = None,
    ) -> dict[str, Any]:
        """Write one audit record and return it.

        Returns the record dict even when auditing is disabled, so callers/tests can
        inspect what *would* have been written.
        """
        record: dict[str, Any] = {
            "timestamp": _utc_now_iso(),
            "tool": action.tool_name,
            "args": action.args,
            "needed_approval": needed_approval,
            "approved": None if decision is None else decision.approved,
            "decision_source": None if decision is None else decision.source,
            "decision_comment": None if decision is None else decision.comment,
            "executed": executed,
            "result": _safe_repr(result),
            "error": _safe_repr(error),
        }
        if not self.enabled:
            return record

        line = json.dumps(record, default=self._fallback) + "\n"
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
        return record

    @staticmethod
    def _fallback(obj: Any) -> str:
        """Last-resort JSON encoder for non-serialisable argument values."""
        if hasattr(obj, "__dataclass_fields__"):
            try:
                return asdict(obj)  # type: ignore[return-value]
            except Exception:  # pragma: no cover - defensive
                pass
        return repr(obj)
