# Changelog

## 0.4.0 — Unreleased

- Removed `codex:fable-harness`; retain two agents, two commands, and the routing/audit hooks.
- Aligned marketplace/plugin version and role descriptions.
- Updated CLI examples for codex-cli 0.159.2: target reviews omit incompatible trailing prompts; custom instructions route through oracle, review sandbox is explicit, and failures stop the shell block.
- Quoted hook paths for checkout paths containing spaces.
- Scope auditing compares task-start fingerprints, catching changes to already-dirty files and preserving raw filenames. Baseline copying includes untracked files in directories and preserves symlinks. Missing audit data is reported.
- Removed automatic fallback/stall retries; retained logs, explicit run/thread paths, and actual model/effort for one optional corrective resume. Background jobs use Read/TaskStop; audits run after every execution and verification.
- Normalized repository paths, reviewed changes against task-start copies, and made uncertain recovery report-only.
- Added isolated hook regressions and documented validation limits.

## 0.3.0 — 2026-07-10

- Trimmed to two agents: removed `codex:explorer` and `codex:librarian` — exploration and research stay with Claude itself; Codex is reserved for implementation (`codex:fixer`) and deep review (`codex:oracle`). Routing nudge updated to match.
- Model bump: all Codex calls now use `gpt-5.6-sol`; `codex:oracle` and `codex:fixer` run at max effort (fallbacks xhigh / high).
- New skill: `codex:fable-harness` — drives Codex through a Fable-5-style multi-pass protocol (decompose → plan-gate → implement → adversarial self-verify → independent Claude review) for hard or high-stakes tasks.

## 0.2.0 — 2026-06-11

- Four agents: `codex:fixer` (write, gatekeeper workflow with baseline snapshot + scope audit + verification), `codex:explorer`, `codex:librarian`, `codex:oracle` (read-only, effort-tiered).
- Commands: `/codex-implement`, `/codex-review`.
- Hooks: soft routing nudge on every prompt, post-edit nudge when direct edits accumulate, warn-only `SubagentStop` scope audit after fixer runs.
- Public-repo polish: rewritten README, head-to-head benchmark against [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) ([docs/BENCHMARK.md](docs/BENCHMARK.md)), reproducible harness in `benchmarks/`.
- Pinned to codex-cli 0.136.0 flag semantics (`--json`, `-o`, `-c`, `-s`, `--skip-git-repo-check`).

## 0.1.0

- Initial soft-routing plugin: fixer/explorer/librarian/oracle agents and routing hooks.
