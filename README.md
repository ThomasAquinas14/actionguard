![actionguard halting an AI agent's duplicate refund for human approval](docs/demo.gif)

# actionguard

**Catch your LangChain agent's risky actions before they run, and route them to a human for approval — in 3 lines.**

```python
from actionguard import guard, ApprovalPolicy
from langchain_core.tools import tool

@guard(policy=ApprovalPolicy(amount_over={"arg": "amount", "threshold": 100}))
@tool
def refund_customer(amount: float, customer_id: str) -> str:
    """Issue a refund."""
    ...
```

When your agent calls `refund_customer(amount=4000, ...)`, execution **pauses**, a human is asked to approve or deny, and the refund only runs if approved. Denied calls return a clear message to the agent instead of doing anything. Every decision is written to an append-only audit log.

[![PyPI](https://img.shields.io/pypi/v/actionguard.svg?cacheSeconds=3600)](https://pypi.org/project/actionguard/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/actionguard.svg?cacheSeconds=3600)](https://pypi.org/project/actionguard/)
[![CI](https://github.com/ThomasAquinas14/actionguard/actions/workflows/ci.yml/badge.svg)](https://github.com/ThomasAquinas14/actionguard/actions/workflows/ci.yml)

## Why

AI agents are great until one does something it can't take back — double-charging a card, deleting production data, emailing the wrong customer, issuing a duplicate refund. Automated checks can't catch every irreversible action, and you don't want to babysit the agent for the 1% of calls that actually matter. `actionguard` lets you keep the agent autonomous for routine work while putting a human in the loop for exactly the calls you decide are dangerous.

## Install

```bash
pip install actionguard
```

The only required dependency is `langchain-core`. Slack support adds `requests`:

```bash
pip install "actionguard[slack]"
```

## Quickstart (5 minutes)

No LLM or API key needed — this simulates the agent deciding to refund, so you can watch the call get halted at your terminal:

```python
from langchain_core.tools import tool

from actionguard import guard

# With no policy given, actionguard uses the safe default: every call needs approval.
@guard()
@tool
def refund_customer(amount: float, customer_id: str) -> str:
    """Issue a refund to a customer's card."""
    return f"✅ Refunded ${amount:.2f} to {customer_id}"


if __name__ == "__main__":
    print("Agent: issuing the refund now...")
    print(refund_customer.invoke({"amount": 4000.0, "customer_id": "cus_123"}))

    print("Agent: did that go through? Trying again to be safe...")
    # The dangerous duplicate — deny it at the prompt!
    print(refund_customer.invoke({"amount": 4000.0, "customer_id": "cus_123"}))
```

You'll see a prompt like this and the call will wait for your answer:

```
──────────────────────────────────────────────────────────────
 🛑 actionguard — approval required
──────────────────────────────────────────────────────────────
 Tool:   refund_customer
 About:  Issue a refund to a customer's card.
 Args:
    amount = 4000.0
    customer_id = 'cus_123'
──────────────────────────────────────────────────────────────
Approve this action? [y/N]
```

Deny it, and the agent receives a `DENIED: ...` message instead of issuing a duplicate refund.

To guard tools at the agent level, use `guard_tools` and hand the result to your agent:

```python
from actionguard import guard_tools

guarded = guard_tools(my_tools, policy=my_policy)   # returns a new list
agent = create_agent(llm, guarded)                  # the agent sees identical tools
```

## Policies — decide *what* needs approval

An `ApprovalPolicy` looks at a tool call's arguments and answers one question: does a human need to approve this? Rules combine with OR — if any rule fires, the call is held.

```python
from actionguard import ApprovalPolicy

# Threshold: only refunds over $100 need approval
ApprovalPolicy(amount_over={"arg": "amount", "threshold": 100})

# Regex: only touch production customers needs approval
ApprovalPolicy(match_args={"customer_id": r"^prod-"})

# Arbitrary predicate over the args dict
ApprovalPolicy(require_if=lambda args: args["amount"] > 100 and args["currency"] == "USD")

# Always require approval (e.g. for a delete tool)
ApprovalPolicy(require_always=True)

# Safe default: ApprovalPolicy() with no rules requires approval for EVERY call.
ApprovalPolicy()
```

## Approval channels — decide *who* approves and *how*

The channel is where the human's yes/no comes from. `CLIChannel` is the default and needs zero setup.

```python
from actionguard import guard, CLIChannel, SlackChannel

# CLI (default) — a blocking terminal prompt. Works in any script or notebook.
guard(my_tool, channel=CLIChannel())

# Slack (v0) — posts the action to an incoming webhook and waits for a decision.
guard(my_tool, channel=SlackChannel(
    webhook_url="https://hooks.slack.com/services/...",
    poll_fn=my_decision_poller,   # how actionguard learns the human answered
    timeout=300,                  # seconds to wait
    on_timeout="deny",            # safe default if nobody answers
))
```

**Write your own** by subclassing `ApprovalChannel` and implementing one method:

```python
from actionguard import ApprovalChannel
from actionguard.core import Action, Decision

class EmailChannel(ApprovalChannel):
    name = "email"

    def request_approval(self, action: Action) -> Decision:
        # ...notify a human, block until they answer...
        return Decision(approved=True, source=self.name)
```

> **Note on Slack:** incoming webhooks are one-way, so the v0 Slack channel posts the
> action and then waits for your `poll_fn` to report the decision (poll a DB, a queue, a
> file — whatever your Slack app writes to). Native Block Kit buttons wired to a request
> URL are on the [roadmap](ROADMAP.md). CLI works out of the box with nothing to set up.

## Audit log

Every intercepted call writes exactly one JSON line to `actionguard_audit.jsonl` (configurable). This is the trust surface — what the agent tried, whether policy held it, what the human decided, and what happened:

```json
{"timestamp": "2026-06-01T12:00:00+00:00", "tool": "refund_customer", "args": {"amount": 4000.0, "customer_id": "cus_123"}, "needed_approval": true, "approved": false, "decision_source": "cli", "decision_comment": null, "executed": false, "result": null, "error": null}
```

Point it wherever you like:

```python
from actionguard import guard, AuditLog
guard(my_tool, audit=AuditLog("logs/approvals.jsonl"))
# or just a path:
guard(my_tool, audit="logs/approvals.jsonl")
```

> The audit log records tool arguments **verbatim** and is written to disk with your
> default file permissions. If your tools take secrets or PII as arguments, point the log
> at a restricted location (or disable it with `AuditLog(enabled=False)`). Automatic
> secret redaction is on the [roadmap](ROADMAP.md), not in v0.

## Scope — what this is (and is *not*, yet)

actionguard v0 is a focused **human-in-the-loop approval gate for irreversible actions**. That's it. It is **not** a security sandbox and makes no security guarantees beyond "this call won't run until a human says yes."

It deliberately does **not** (yet) do: sandboxing, SSRF protection, secret redaction, code/AST verification, durable/resumable approval state, retries, or planning. Those are real and useful — they're just not v0. See [ROADMAP.md](ROADMAP.md) for what's intentionally cut and what's coming.

If you need a full guardrails platform today, that's not this. If you want to stop your agent from double-refunding a customer in the next five minutes, you're in the right place.

## Contributing

Issues and PRs welcome. To set up a dev environment:

```bash
pip install -e ".[dev]"
pytest
ruff check . && black --check .
```

Keep changes small and aligned with the scope above — actionguard's whole value is being the smallest thing that solves the irreversible-action problem.

## License

MIT — see [LICENSE](LICENSE).
