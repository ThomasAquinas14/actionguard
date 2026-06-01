"""Route approvals to Slack instead of the terminal.

actionguard's Slack channel (v0) posts the proposed action to a Slack incoming webhook,
then waits for a decision. Because incoming webhooks are one-way, the approve/deny
signal comes from a `poll_fn` you supply — here we poll a local file so the example is
fully runnable. (Wiring real Slack buttons to your process is on the roadmap.)

Run it:

    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/XXX/YYY/ZZZ"
    python 03_slack_approval.py

Then, in another terminal, approve the pending refund by writing a decision file:

    echo '{"approved": true}' > slack_decision.json     # or {"approved": false}

If SLACK_WEBHOOK_URL is unset, the example still runs and just prints what it *would*
post (so you can see the shape without a workspace).
"""

import json
import os

from langchain_core.tools import tool

from actionguard import ApprovalPolicy, SlackChannel, guard
from actionguard.core import Decision

DECISION_FILE = "slack_decision.json"


def poll_local_decision(action):
    """Return a Decision once someone writes slack_decision.json, else None."""
    if not os.path.exists(DECISION_FILE):
        return None
    with open(DECISION_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    os.remove(DECISION_FILE)  # consume it
    return Decision(approved=bool(data.get("approved")), comment=data.get("comment"))


class _PrintOnlySession:
    """Stands in for `requests` when no webhook is configured — just prints."""

    def post(self, url, json=None):
        print(f"[would POST to Slack webhook]\n{json['text']}\n")


webhook = os.environ.get("SLACK_WEBHOOK_URL")
channel = SlackChannel(
    webhook or "https://hooks.slack.test/not-configured",
    poll_fn=poll_local_decision,
    timeout=120,
    poll_interval=2,
    on_timeout="deny",  # safe default if nobody answers in time
    session=None if webhook else _PrintOnlySession(),
)


@guard(policy=ApprovalPolicy(amount_over={"arg": "amount", "threshold": 100}), channel=channel)
@tool
def refund_customer(amount: float, customer_id: str) -> str:
    """Issue a refund to a customer's card."""
    return f"Refunded ${amount:.2f} to {customer_id}"


if __name__ == "__main__":
    print("Issuing a $4,000 refund — posting to Slack and waiting for approval...")
    print("(approve with:  echo '{\"approved\": true}' > slack_decision.json )\n")
    print(refund_customer.invoke({"amount": 4000.0, "customer_id": "cus_2"}))
