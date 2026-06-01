"""actionguard quickstart — watch a risky action get halted for approval.

Run it:

    pip install actionguard
    python 01_quickstart.py

No LLM or API key needed: we simulate the agent deciding to issue a refund, so you
can see actionguard pause the call and ask *you* to approve it at the terminal. Try
denying the second (duplicate) refund.
"""

from langchain_core.tools import tool

from actionguard import guard


# With no policy given, actionguard uses the safe default: every call needs approval.
@guard()
@tool
def refund_customer(amount: float, customer_id: str) -> str:
    """Issue a refund to a customer's card."""
    # In a real app this would call Stripe/your billing system — irreversible!
    return f"Refunded ${amount:.2f} to {customer_id}"


if __name__ == "__main__":
    print("Agent: the customer asked for a refund, issuing it now...\n")
    print(refund_customer.invoke({"amount": 4000.0, "customer_id": "cus_123"}))

    print("\nAgent: hmm, did that go through? Let me try again to be safe...\n")
    # This is the dangerous duplicate. Deny it at the prompt!
    print(refund_customer.invoke({"amount": 4000.0, "customer_id": "cus_123"}))

    print("\nDone. See actionguard_audit.jsonl for the full record of what happened.")
