---
name: codex-review
description: "Get a Codex second-opinion code review of the current diff; Claude triages each finding against the actual diff."
argument-hint: "[uncommitted|base <branch>|commit <sha>] [extra review instructions]"
---

# /codex-review

Run Codex CLI's built-in reviewer (`codex exec review`) over the current changes, then triage its findings. Claude remains the final reviewer.

## Instructions

Given `$ARGUMENTS`:

1. Map the arguments to a review target: empty or `uncommitted` → `--uncommitted`; `base <branch>` → `--base <branch>`; `commit <sha>` → `--commit <sha>`. Validate that a branch/SHA follows `base`/`commit`, and shell-quote it as one argument.
2. If there are extra review instructions, use `codex:oracle` instead: give it the selected target, the extra instructions, and the relevant diff (staged, unstaged, and untracked files for `uncommitted`; merge-base diff for `base`; the commit patch for `commit`). Do not silently drop the target or instructions. Current Codex CLI rejects a trailing prompt together with `--uncommitted`, `--base`, or `--commit`.
3. Otherwise run the built-in review without a trailing prompt, using Bash `run_in_background: true`. Record the returned task/output path and Read that output file for the exact run paths printed by the block; do not guess filenames. Flag placement matters: `--skip-git-repo-check` and `-C` are exec-level flags and must come BEFORE the `review` subcommand; `review` accepts no `-s` flag. Set the sandbox with `-c` explicitly. No `-m` is passed, so the user's configured review/default model applies. Use the mapped target flag in place of `--uncommitted` when needed.

```bash
OUT="$(mktemp -t codex-review.XXXXXX.md)"
EVT="$(mktemp -t codex-review.XXXXXX.jsonl)"
printf 'OUT=%s\nEVT=%s\n' "$OUT" "$EVT"
if ! codex exec --skip-git-repo-check -C "$PWD" \
  -c 'sandbox_mode="read-only"' review --uncommitted \
  --json -o "$OUT" </dev/null >"$EVT" 2>&1; then
  tail -n 5 "$EVT" >&2
  exit 1
fi
[ -s "$OUT" ] || { tail -n 5 "$EVT" >&2; exit 1; }
cat "$OUT"
```

4. Verify findings against the same target: for `uncommitted`, inspect staged/unstaged diffs and untracked files; for `base`, use the merge-base-to-HEAD diff; for `commit`, inspect that commit's patch. Validate refs with `git rev-parse --verify --end-of-options` before using them, and shell-quote them as single arguments. Use read-only Git only; never stash/checkout/restore/reset. Drop or correct findings that do not match the selected target.
5. Present the result clearly labeled as a Codex second opinion, with Claude's triage verdict per finding (confirmed / corrected / rejected, with evidence).
