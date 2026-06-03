"""actionguard — human-approval guardrail for LangChain agents.

Catch your agent's risky actions before they run, and route them to a human for
approval, in three lines::

    from actionguard import guard, ApprovalPolicy

    @guard(policy=ApprovalPolicy(amount_over={"arg": "amount", "threshold": 100}))
    @tool
    def refund_customer(amount: float, customer_id: str) -> str:
        ...

When the agent calls a guarded tool and the policy says "ask first", execution pauses,
a human approves or denies (at the terminal by default), and the call only runs if
approved. Every decision is written to an append-only audit log.
"""

from .audit import AuditLog
from .channels import ApprovalChannel, CLIChannel, SlackChannel
from .core import Action, Decision
from .function import ApprovalDenied
from .langchain import ApprovalWrappedTool, guard, guard_tools
from .policy import ApprovalPolicy

__version__ = "0.2.1"

__all__ = [
    "guard",
    "guard_tools",
    "ApprovalPolicy",
    "ApprovalChannel",
    "CLIChannel",
    "SlackChannel",
    "AuditLog",
    "Action",
    "Decision",
    "ApprovalDenied",
    "ApprovalWrappedTool",
    "__version__",
]
