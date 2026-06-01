"""Only refunds over $100 need approval.

Small, routine refunds run untouched; large ones pause for a human. Run it:

    python 02_policy_threshold.py

The $50 refund runs immediately. The $4,000 refund halts and waits for you.
"""

from langchain_core.tools import tool

from actionguard import ApprovalPolicy, guard

policy = ApprovalPolicy(amount_over={"arg": "amount", "threshold": 100})
# Equivalent predicate form:
#   ApprovalPolicy(require_if=lambda args: args.get("amount", 0) > 100)


@guard(policy=policy)
@tool
def refund_customer(amount: float, customer_id: str) -> str:
    """Issue a refund to a customer's card."""
    return f"Refunded ${amount:.2f} to {customer_id}"


if __name__ == "__main__":
    print("Small refund ($50) — under threshold, runs without asking:\n")
    print(refund_customer.invoke({"amount": 50.0, "customer_id": "cus_1"}))

    print("\nLarge refund ($4,000) — over threshold, needs your approval:\n")
    print(refund_customer.invoke({"amount": 4000.0, "customer_id": "cus_2"}))
