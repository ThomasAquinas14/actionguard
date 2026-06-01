# Changelog

All notable changes to actionguard are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/ThomasAquinas14/actionguard/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ThomasAquinas14/actionguard/releases/tag/v0.1.0
