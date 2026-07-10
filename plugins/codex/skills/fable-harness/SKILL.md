---
name: fable-harness
description: Drive GPT-5.6-sol (Codex CLI) through a Fable-5-style multi-pass protocol — decompose, plan-gate, implement, adversarially self-verify, then independently review — to recover Fable-like rigor on hard tasks. Use when delegating a hard, ambiguous, or multi-step task to Codex where one-shot quality isn't enough (hard bugs, cross-cutting changes, design-sensitive work, high-stakes answers). Not for small mechanical changes — the multi-pass overhead isn't worth it there; use codex:fixer or a direct edit instead.
---

# Fable Harness

One-shot GPT-5.6-sol is a strong implementer but, compared to Fable 5, it tends to: act before fully decomposing, silently guess APIs/flags/schemas instead of checking, declare success without re-reading the acceptance criteria against actual output, skip the adversarial "how could this be wrong" pass, and pad or hedge its reports. This skill compensates **by procedure, not by model**: a single resumed Codex thread is driven through explicit plan / implement / verify passes, with Claude gating between passes and independently re-verifying at the end.

You (Claude) are the gatekeeper. Codex does all reasoning-heavy and code-writing work inside one thread (so context persists across passes); you review each pass's output before unlocking the next, and you never skip the final independent check.

## When to use

- Hard or uncertain bug fixes, cross-cutting refactors, design-sensitive implementation.
- High-stakes analysis/answers where a wrong confident answer is costly (use Answer mode below).
- Any task where the user asked for "Fable-quality" output from Codex.

When NOT to use: small mechanical edits (direct edit), routine well-specified implementation (codex:fixer), pure lookup (codex:librarian). The harness costs 3–4 Codex calls; spend them where rigor pays.

## Behavior rules — embed this block VERBATIM in every Codex prompt

```text
Behavior rules (follow exactly):
1. Decompose before acting: list subtasks, unknowns, and assumptions first. If a load-bearing assumption can be checked by reading the repo or running a read-only command, check it instead of assuming.
2. Never silently guess an API, flag, schema, or invariant. Mark every assumption VERIFIED (cite the file/command that proves it) or UNVERIFIED.
3. Make the smallest correct change; match the surrounding code's style, naming, and comment density. No drive-by refactors or cleanup outside scope.
4. After finishing, re-read the acceptance criteria one by one and check each against the ACTUAL diff/output — quote the evidence; never assert from memory.
5. Adversarial pass: actively try to refute your own work. Consider edge cases (empty, boundary, error paths, concurrency, encoding), call sites you may have broken, and behavior the diff changed unintentionally.
6. Report failures plainly: if a test fails or a criterion is unmet, say FAIL with the verbatim output. Never claim success you did not observe. Never weaken a test, type, or criterion to make it pass.
7. Output rules: first line is PASS, FAIL, or BLOCKED plus a one-sentence summary. Then evidence: commands run and the relevant verbatim output. Complete sentences; no filler, hedging, or apologies.
8. If the task is underspecified or you are blocked, stop and return BLOCKED with the specific question — do not improvise scope.
9. git is read-only — never run git stash/checkout/restore/reset/clean/add/commit/rebase/merge/pull and never restore any file toward HEAD content.
```

## Phase 0 — Task card (Claude, no Codex)

Write a task card before any delegation. If you cannot fill in testable acceptance criteria, ask the user first — the harness amplifies a clear spec and garbage-amplifies a vague one.

```text
Goal: <one sentence>
Scope: edit ONLY these files: <explicit list, or "read-only — Answer mode">
Acceptance criteria: <numbered, each independently checkable>
Run: <verification command, or "none — state what you checked instead">
Constraints: <style, compat, perf, anything task-specific>
```

## Phase 1 — PLAN (read-only, high effort)

Send the task card + behavior rules + this phase instruction. Read-only sandbox so planning cannot mutate the tree.

```text
PHASE: PLAN. Do not change any files in this phase.
Produce exactly these sections:
GOAL (restated in your own words) / SUBTASKS (ordered, each mapped to the acceptance criteria it serves) / FILES (to read and to edit, with why) / ASSUMPTIONS (each marked VERIFIED with evidence, or UNVERIFIED) / EDGE CASES / RISKS (what could make this approach wrong) / VERIFICATION PLAN / OPEN QUESTIONS (empty section if none).
Verify every assumption you can by reading the repo now, in this phase.
```

```bash
PROMPT="$(cat <<'CODEX_PROMPT'
<task card>

<behavior rules block, verbatim>

<PLAN phase instruction, verbatim>
CODEX_PROMPT
)"
OUT="$(mktemp -t fable-plan.XXXXXX.md)"
EVT="$(mktemp -t fable-plan.XXXXXX.jsonl)"
ERR="$(mktemp -t fable-plan.XXXXXX.err)"
codex exec --skip-git-repo-check -s read-only -C "$PWD" \
  -m gpt-5.6-sol \
  -c 'model_reasoning_effort="high"' \
  -c 'service_tier="fast"' \
  --json -o "$OUT" \
  "$PROMPT" </dev/null >"$EVT" 2>"$ERR" || {
    if grep -qiE 'not supported|unknown model|invalid model|model.*not.*found|invalid_request_error|effort' "$EVT" "$ERR"; then
      codex exec --skip-git-repo-check -s read-only -C "$PWD" \
        -m gpt-5.6-sol \
        -c 'model_reasoning_effort="medium"' \
        -c 'service_tier="fast"' \
        --json -o "$OUT" \
        "$PROMPT" </dev/null >"$EVT" 2>"$ERR"
    else
      tail -n 5 "$EVT" >&2; cat "$ERR" >&2; false
    fi
  }
[ -s "$OUT" ] || { echo "fable: no final message; last events:" >&2; tail -n 5 "$EVT" >&2; false; }
THREAD_ID="$(head -n1 "$EVT" | sed -n 's/.*"thread_id":"\([^"]*\)".*/\1/p')"
```

Build `$PROMPT` with a quoted heredoc in the SAME Bash call as `codex exec` — variables don't survive across Bash tool calls, and backticks in double quotes are command substitution. Capture and keep `$THREAD_ID`; every later phase resumes it. For genuinely hard design work you may raise PLAN to `xhigh` (then treat silence up to ~10 min as normal).

**Gate (Claude) — do not proceed until all hold:**
- Every acceptance criterion is covered by at least one subtask.
- No UNVERIFIED assumption is load-bearing. If one is, send ONE revision turn via resume telling Codex to verify it; if it can only be resolved by the user, surface it and stop.
- OPEN QUESTIONS is empty, or you can answer each from the conversation (answer them in the next phase's prompt) — otherwise ask the user.
- Scope didn't grow beyond the task card. If the plan wants more files, decide deliberately and update the task card, don't let it drift.

## Phase 2 — IMPLEMENT (resume, workspace-write, medium effort)

Skip this phase in Answer mode. Before delegating any write, capture a baseline snapshot exactly as the `codex:fixer` agent does (snapshot every dirty file plus all in-scope files into a `mktemp -d` dir; see the fixer agent's step 2) — the working tree, not HEAD, is the canonical baseline, and the snapshot is your only sanctioned undo.

```text
PHASE: IMPLEMENT. Execute the approved plan.
<Claude's answers to OPEN QUESTIONS / gate revisions, if any>
Edit ONLY these files: <explicit list>.
Follow the behavior rules. After implementing, run: <Run: command> and include its verbatim output. First line of your reply: PASS/FAIL/BLOCKED.
```

```bash
OUT2="$(mktemp -t fable-impl.XXXXXX.md)"
EVT2="$(mktemp -t fable-impl.XXXXXX.jsonl)"
ERR2="$(mktemp -t fable-impl.XXXXXX.err)"
# resume accepts no -s/-C flags: sandbox goes via -c, and it runs in the current directory.
codex exec resume "$THREAD_ID" --skip-git-repo-check \
  -c 'sandbox_mode="workspace-write"' \
  -c 'model_reasoning_effort="medium"' \
  -c 'service_tier="fast"' \
  --json -o "$OUT2" \
  "$PHASE2_PROMPT" </dev/null >"$EVT2" 2>"$ERR2"
[ -s "$OUT2" ] || { tail -n 5 "$EVT2" >&2; false; }
```

Never use `resume --last` (parallel agents race for it). If `$THREAD_ID` is empty or resume fails, fall back to a fresh `codex exec` that re-includes the task card, behavior rules, and the full approved plan text.

## Phase 3 — SELF-VERIFY (resume, workspace-write, medium effort)

A separate turn, even though Phase 2 already ran the tests — the point is forcing the criterion-by-criterion re-read and the refutation pass that one-shot runs skip.

```text
PHASE: SELF-VERIFY. Do not add features.
1. Re-read the diff of your changes (git diff is allowed; git remains read-only otherwise).
2. For EACH acceptance criterion: PASS or FAIL, with quoted evidence from the diff or command output.
3. Refutation pass: list the 3 most plausible ways this change is wrong (edge cases, broken call sites, unintended behavior change) and check each one — show what you checked.
4. Re-run: <Run: command>. Verbatim output.
5. If you fix anything during this phase, disclose the fix and re-run the checks — a silent fix-and-claim is a FAIL.
First line: PASS only if every criterion passed and no refutation survived; otherwise FAIL/BLOCKED with the reason.
```

Same resume invocation shape as Phase 2. In Answer mode, replace steps 1–4 with: fact-check every claim in the answer against the repo/source it cites, mark each claim VERIFIED/UNVERIFIED, and attempt to refute the overall conclusion.

## Phase 4 — INDEPENDENT REVIEW (Claude, mandatory)

Codex grading its own homework is not the final word:

1. Re-run the `Run:` command yourself and compare against Codex's reported output. A mismatch is a finding, not a formality.
2. Review `git diff -- <scoped files>` against the acceptance criteria and the behavior rules (smallest change, style match, no weakened tests).
3. Audit scope against the baseline snapshot, fixer-style: out-of-scope files modified by this run → restore from the snapshot (never from HEAD); files created out of scope → delete.
4. Spot-check one refutation from Phase 3 yourself — pick the one you find most plausible.

## Stall & failure handling

- Liveness = growth of the `$EVT` file (`-o` is written only at completion) plus, in write phases, file changes in the tree. No growth for ~5 minutes at high effort (~10 at xhigh) → kill, retry that phase once via resume; if the retry also dies, report the failure with the phase outputs so far.
- Effort rejection appears in `$EVT`/`$ERR`, not as a clean error — the `grep` fallback in Phase 1 handles it; state explicitly in your report when a fallback effort ran.
- A FAIL from Phase 3 gets ONE correction turn (resume, tighter prompt naming the failed criterion). If it fails again, stop and report — do not loop.

## Report to the user

Lead with the outcome (criteria met or not, verification result). Then: files changed and why, per-criterion verdicts with Phase 4's independent confirmation, refutations attempted and their results, model/efforts used per phase (and any fallbacks), thread_id, and anything restored/deleted in the scope audit (an explicit "none" attests the audit ran).
