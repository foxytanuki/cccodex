---
name: codex-implement
description: Manually delegate implementation work to Codex CLI through the codex:fixer agent.
argument-hint: "<goal, scope, acceptance criteria, and Run: command>"
---

# /codex-implement

Delegate the requested implementation to Codex while Claude remains responsible for orchestration, diff review, and verification.

## Usage

```text
/codex-implement <goal, scope, acceptance criteria, and Run: command>
```

## Instructions

Given `$ARGUMENTS`:

1. If the task is ambiguous, ask one concise clarification question.
2. Spawn the `codex:fixer` subagent with `$ARGUMENTS` as the full subagent prompt and a short description like "Implement with Codex". (The spawn tool is named Task or Agent depending on Claude Code version.)
3. Require the agent to report changed files, diff summary, verification output, its codex thread_id, and its stall-fallback / out-of-scope-restoration disclosures (an explicit 'none' counts — it attests the audit ran). If the agent returns a stall-fallback edit spec (Codex was unavailable), apply that edit directly yourself — tiny direct edits are the lead's prerogative — and disclose in your summary that it was hand-applied because Codex was unavailable.
