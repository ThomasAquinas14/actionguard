# Changelog

All notable changes to actionguard are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.1] — fail-closed hardening

Security and robustness fixes for the approval gate. No API changes; upgrading is
recommended for anyone on 0.2.0.

### Fixed
- **Threshold bypass via numeric strings.** `amount_over` now parses numeric-string
  arguments (e.g. `"4000"`) and compares them, and **fails closed** (holds the call)
  when the configured argument is present but not a number. Previously a plain callable
  receiving an unconverted string — which has no schema to coerce it — could slip a
  large value past the threshold without approval.
- **Slack webhook failures no longer pass silently.** The webhook POST now uses a
  network timeout and checks the HTTP status; a failed delivery (the human never saw
  the request) fails closed instead of falling through to wait for a decision.
- **Audit writes can no longer mask a completed action.** The audit sink is preflighted
  at construction (a bad path/permissions fails before any action runs), and a
  post-execution audit-write failure now warns loudly rather than surfacing as a tool
  error — so a successfully executed, irreversible action is never reported as failed
  (which could trigger a duplicate retry).
- **Approval display hardened against argument spoofing.** Argument values are now
  sanitized (the CLI escapes control characters from a malicious `__repr__`; Slack
  escapes mrkdwn metacharacters and backticks) so a crafted argument can't break out of
  its formatting and forge the approval banner.

## [0.2.0] — framework-agnostic guard

`guard` now wraps **any Python callable**, not just LangChain tools — the capability a
framework's built-in approval hook structurally can't offer.

### Added
- `guard` accepts any callable. A LangChain `BaseTool` behaves exactly as before; any
  other callable (plain function, method, async function, other frameworks' tools) is
  wrapped to pause for approval the same way. The wrapped callable preserves the
  original's name, docstring, and signature.
- `ApprovalDenied` exception: a denied call to a guarded plain callable raises it (it
  carries the `Action` and `Decision`). Set `guard(..., on_denied="return")` to return
  the denial message string instead of raising.
- Policy arguments for callables are bound by name (defaults applied, `self`/`cls`
  dropped, `**kwargs` flattened), so the same `ApprovalPolicy` rules work unchanged.

### Unchanged
- The LangChain path (`guard` on a tool, `guard_tools`) is byte-for-byte identical.
  This release is fully backward-compatible.

## [0.1.0] — initial release

First public release. A deliberately minimal v0: human-in-the-loop approval for an
agent's irreversible tool calls, and nothing more.

### Added
- `guard` decorator and `guard_tools` helper to wrap LangChain `BaseTool`s. The guarded
  tool preserves the inner tool's name, description, and args schema, so it is
  indistinguishable to the agent. Works on sync and async execution paths.
- `ApprovalPolicy` with `require_if`, `require_always`, `amount_over`, and `match_args`
  rules (combined with OR). Safe default: an unconfigured policy requires approval for
  every call.
- `ApprovalChannel` interface with two implementations: `CLIChannel` (default, zero-setup
  terminal prompt) and `SlackChannel` (v0: posts to an incoming webhook and waits on a
  caller-supplied `poll_fn`, failing closed on timeout).
- Append-only JSONL audit log (`AuditLog`) recording one record per intercepted call.
- Fails **closed**: if a policy predicate or approval channel raises, the action is
  blocked, the error is recorded, and the agent is told the guard could not decide.
- Control characters in tool names, descriptions, and argument keys are neutralized
  before being shown to a human approver, so a malicious tool cannot forge the banner.

[Unreleased]: https://github.com/ThomasAquinas14/actionguard/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/ThomasAquinas14/actionguard/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/ThomasAquinas14/actionguard/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ThomasAquinas14/actionguard/releases/tag/v0.1.0
