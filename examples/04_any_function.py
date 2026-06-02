"""actionguard works on ANY callable — not just LangChain tools.

Wrap a plain function and risky calls pause for approval exactly the same way. Because a
plain function has no agent to hand a message to, a denied call raises `ApprovalDenied`
(or set `on_denied="return"` to get the denial string back instead).

Run it:

    python 04_any_function.py

Approve the first delete, then DENY the second.
"""

from actionguard import ApprovalDenied, ApprovalPolicy, guard


@guard(policy=ApprovalPolicy(require_always=True))
def delete_user(user_id: str) -> str:
    """Permanently delete a user account."""
    # In a real app this is irreversible — the whole point of guarding it.
    return f"Deleted {user_id}"


if __name__ == "__main__":
    for user_id in ("u_001", "u_002"):
        try:
            print(delete_user(user_id))
        except ApprovalDenied as denied:
            print(f"Blocked: {denied.action.pretty()} was not executed.")

    print("\nDone. See actionguard_audit.jsonl for the record of what happened.")
