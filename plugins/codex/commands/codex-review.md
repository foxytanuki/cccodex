---
name: codex-review
description: "Get a Codex second-opinion code review of the current diff; Claude triages each finding against the actual diff."
argument-hint: "[uncommitted|base <branch>|commit <sha>] [extra review instructions]"
---

# /codex-review

Run Codex CLI's built-in reviewer (`codex exec review`) over the current changes, then triage its findings. Claude remains the final reviewer.

## Instructions

Given `$ARGUMENTS`:

1. Map the arguments to a review target: empty or `uncommitted` → `--uncommitted`; `base <branch>` → `--base <branch>`; `commit <sha>` → `--commit <sha>`. Any remaining free text becomes the trailing prompt (custom review instructions).
2. Run the review. Flag placement matters: `--skip-git-repo-check` and `-C` are exec-level flags and must come BEFORE the `review` subcommand; `review` accepts no `-s` flag (it is read-only by design). No `-m` is passed, so the user's `~/.codex/config.toml` default model applies.

```bash
OUT="$(mktemp -t codex-review.XXXXXX.md)"
EVT="$(mktemp -t codex-review.XXXXXX.jsonl)"
codex exec --skip-git-repo-check -C "$PWD" review --uncommitted \
  --json -o "$OUT" \
  "<optional custom review instructions>" </dev/null >"$EVT" 2>&1
[ -s "$OUT" ] || { tail -n 5 "$EVT" >&2; false; }
```

3. Read `$OUT` and verify each reported finding against the actual diff using read-only git only (`git diff`, `git diff --cached`, `git show` — never stash/checkout/restore/reset). Drop or correct findings that do not match the diff.
4. Present the result clearly labeled as a Codex second opinion, with Claude's triage verdict per finding (confirmed / corrected / rejected, with evidence).
