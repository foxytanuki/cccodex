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
3. Require the agent to report task-start changes, verification results, exact Codex thread/background task IDs and run paths, and post-run/post-verification audit outcomes. A failed delegation may leave partial edits: inspect those before any further work. Do not automatically restart the fixer. If the user explicitly requests a small direct correction, the lead may apply it and disclose that Codex was unavailable; ignore routing nudges for that recovery so it does not bounce back to a failed delegate.
