# Roadmap

actionguard v0 does one thing: pause an agent's risky tool calls and route them to a
human for approval, with an audit trail. Everything below is deliberately **out of
scope for v0** — listed here so the boundary is honest and so contributors know where
the project is headed.

## Intentionally cut from v0

These are valuable but are *not* what v0 is. We left them out to keep actionguard small,
trustworthy, and dependency-light:

- **Sandboxing / isolation** — running tool side effects in a constrained environment.
- **SSRF & network egress guards** — inspecting/limiting outbound requests a tool makes.
- **Secret redaction** — detecting and masking credentials in arguments or logs.
- **Code / AST verification** — statically analysing tool inputs (e.g. generated code or
  SQL) for danger before running them.
- **Retries / planning layers** — re-planning or auto-retrying after a denial.

If you find yourself wanting these, that's expected — they're real needs. They're just a
different product surface than "human approves the irreversible call."

## Coming next

Roughly in priority order. None of these change the v0 public API; they extend it.

1. **Durable / resumable approval state.** Today an approval blocks the running process.
   Next: persist a pending action so approval can happen later, across restarts, and the
   call resumes — the foundation for truly async, out-of-band approvals.
2. **Richer Slack interactivity.** v0 posts to an incoming webhook and waits on a
   `poll_fn`. Next: a proper Slack app with Block Kit approve/deny buttons wired to a
   request URL, threaded context, and the approver's identity captured in the audit log.
3. **More approval channels.** Email, Discord, PagerDuty, and a small local web approval
   UI — all behind the same `ApprovalChannel` interface.
4. **Multi-framework adapters.** Bring the same `guard` ergonomics to CrewAI,
   LlamaIndex, the OpenAI Agents SDK, and plain function calls — not just LangChain.
5. **Approval routing & policy composition.** Route different actions to different
   approvers, escalation/timeouts, and combine policies (all-of/any-of) cleanly.
6. **Audit sinks.** Pluggable destinations beyond JSONL (stdout, a webhook, a database)
   and helpers for reviewing/replaying the log.

## Non-goals

actionguard will not try to become a full agent-security platform or make security
guarantees it can't keep. Its job is the human-in-the-loop gate for irreversible
actions, done extremely well. If a feature would blur that focus, it probably belongs in
a different tool.

Have an opinion on the order, or a channel you need? Open an issue.
