# Codex Plugin

Claude Code plugin that keeps Claude as the interface/orchestrator while softly nudging non-trivial implementation work to Codex CLI.

It is intentionally softer than a fixed `/implement` pipeline:

- Claude can still make tiny direct edits.
- Feature work, refactors, multi-file changes, tests, and uncertain fixes are nudged toward `codex:fixer`.
- Read-only exploration, research, and deep advisory work can route to `codex:explorer`, `codex:librarian`, or `codex:oracle`.
- `codex:fixer` has no edit tools; it delegates implementation to `codex exec`, then reviews the diff and verifies. If Codex is unavailable for a tiny fully-specified edit, fixer returns the exact edit in its report and the lead applies it.
- The routing rules live inside the plugin, not in root `CLAUDE.md` or project settings.

## Install

From GitHub, inside Claude Code:

```text
/plugin marketplace add foxytanuki/cccodex
/plugin install codex@cccodex
```

The repo is private, so the machine needs git credentials that can clone it (`gh auth login` or an SSH key).

For local development, register a clone's working tree instead — the install live-references it, so hook edits take effect immediately and agent edits on the next session:

```text
/plugin marketplace add ~/dev/personal/cccodex
/plugin install codex@cccodex
```

Requirements:

- `codex` is installed and on `PATH`.
- `codex login` has been completed with ChatGPT auth.
- Tested with codex-cli 0.136.0 (check with `codex --version`). The agents depend on that release's `codex exec` flag semantics — `--json` (JSONL events on stdout), `-o`/`--output-last-message`, `-c key=value`, `-s` sandbox modes, `--skip-git-repo-check` — so if your version differs, run one agent's `codex exec` command manually first to confirm the flags behave the same.

## What It Adds

- Agent: `codex:fixer` (Claude Opus orchestrator, Codex `gpt-5.5`, medium, fallback `gpt-5.5` low)
- Agent: `codex:explorer` (Claude Sonnet orchestrator, Codex `gpt-5.5`, low, read-only)
- Agent: `codex:librarian` (Claude Sonnet orchestrator, Codex `gpt-5.5`, low, read-only, requests live web search via `-c 'web_search="live"'`)
- Agent: `codex:oracle` (Claude Sonnet orchestrator, Codex `gpt-5.5`, xhigh, fallback `gpt-5.5` high, read-only)
- Command: `/codex-implement <task>`
- Command: `/codex-review [uncommitted|base <branch>|commit <sha>] [instructions]` — Codex second-opinion review of a diff via `codex exec review`; Claude triages each finding
- Hook: `UserPromptSubmit` soft routing reminder (skipped for empty prompts and slash commands)
- Hook: `PostToolUse` nudge after `Edit`, `Write`, `MultiEdit`, or `NotebookEdit` — fires on a single ~20+ line change, or when small edits accumulate in a session (~60+ lines or 3+ files since the last nudge)
- Hook: `SubagentStop` warn-only scope audit — after a `codex:fixer` run, deterministically diffs `git status` against the fixer's task-start baseline and warns about out-of-scope changes (backstop for the prompt-enforced working-tree policy; never blocks)

## Intended Behavior

Use Claude Code normally. For small obvious edits, Claude can proceed. When the task becomes implementation-heavy, Claude should spawn the `codex:fixer` subagent (the spawn tool is named Task or Agent depending on Claude Code version):

```text
codex:fixer
```

The plugin does not deny Claude's edit tools. If routing is still too weak, add project-local permissions later; keep that separate from this plugin.

## Optional strict mode (not installed by the plugin)

Add to `.claude/settings.json` (or `.claude/settings.local.json` to keep it personal/uncommitted):

```json
{
  "permissions": {
    "ask": ["Edit", "Write", "MultiEdit"]
  }
}
```

"ask" keeps a human approval in the loop for Claude's direct edits without hard-denying them, so tiny edits remain possible under supervision; `codex:fixer` is unaffected because it has no edit tools, making delegation the friction-free path. A hard "deny" variant exists (replace "ask" with "deny") but works against this plugin's soft-routing intent. The plugin never ships this enabled; deleting the snippet returns you to pure soft routing.
