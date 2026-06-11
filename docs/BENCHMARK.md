# Benchmark: cccodex vs openai/codex-plugin-cc

A head-to-head measurement of the **delegation machinery** of two Claude Code → Codex plugins:

- **cccodex** (`codex@cccodex`, v0.2.0) — this repo. Soft routing via subagents; the `codex:fixer` agent wraps `codex exec` directly.
- **[openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc)** (`codex@openai-codex`, v1.0.4, commit `807e03a`) — OpenAI's official plugin. Slash commands; the `/codex:rescue` path wraps the Codex app server via a Node.js companion script (`codex-companion.mjs task`).

**TL;DR — both plugins drive the same Codex backend, and on identical tasks they produce equivalent results at equivalent cost: 30/30 tasks passed, mean wall-clock 18.4 s vs 18.6 s, near-identical token usage. The persistent app-server broker saves ~1.3 s of fixed overhead per call once warm (and costs ~5 s extra on the first call). The real difference is workflow architecture, not throughput — see [What actually differs](#what-actually-differs).**

## Methodology

Both plugins resolve to the **same model, effort, and tier** on this machine (`gpt-5.5`, `medium`, `fast` service tier — cccodex pins these flags explicitly; codex-plugin-cc inherits them from `~/.codex/config.toml`), so this is an apples-to-apples comparison of the delegation pipelines, not of models.

Three fixture tasks, each a fresh single-purpose git repo with pre-written `unittest` suites, two pristine copies per task (one per plugin path):

| Task | Shape | Acceptance |
|---|---|---|
| **T1 bugfix** | `median()` mishandles even-length lists; fix one line | 6 tests pass |
| **T2 feature** | implement `slugify()` against 8 pre-written failing tests | 9 tests pass |
| **T3 multi-file** | add `TaskStore.complete()`/`pending()` + a `done` CLI command across 2 files | 4 tests pass |

Each task ran through each plugin's **actual delegation primitive**:

- **Path A (cccodex)** — the exact `codex exec` invocation from `agents/fixer.md` (`--json -o`, workspace-write sandbox), with the fixer's prompt template (Goal / Scope / Acceptance / Verify / Constraints).
- **Path B (codex-plugin-cc)** — `node codex-companion.mjs task --write --fresh "<task>"` in the repo, the same command its `codex:codex-rescue` subagent runs, with the same task content phrased as a `/codex:rescue` request. Each plugin's own prompt scaffolding is part of what's being measured.

Success = the test suite passes in the repo afterwards, verified externally by the harness (not trusted from the model's own report). Tokens come from `codex exec --json` events (Path A) and Codex session rollout logs (Path B).

Harness: [`benchmarks/run-benchmark.sh`](../benchmarks/run-benchmark.sh). **Five trials per cell** (30 task runs total); fixtures are reset to their committed state between trials.

**Environment:** codex-cli 0.136.0 · Node v24.15.0 · Python 3.12.3 · Linux 6.8 · ChatGPT auth, fast service tier · 2026-06-11, all runs within a 15-minute window.

## Results

### Real tasks — wall time, mean of 5 trials (min–max)

| Task | cccodex (A) | codex-plugin-cc (B) | Outcome |
|---|---|---|---|
| T1 bugfix | 15.0 s (14.3–17.1) | 15.8 s (13.5–17.0) | 10/10 PASS, identical 1-line fix |
| T2 feature | 18.4 s (16.5–19.3) | 19.2 s (14.5–25.3) | 10/10 PASS |
| T3 multi-file | 21.8 s (18.1–25.6) | 20.9 s (19.1–22.0) | 10/10 PASS |
| **overall mean** | **18.4 s** | **18.6 s** | **30/30 PASS** |

Per-task means differ by well under one within-cell standard deviation in both directions (A faster on T1/T2, B faster on T3). With n=5 the conclusion is what n=1 already hinted at: **wall-clock is a wash; the variance is the model, not the plugin.**

### Real tasks — tokens, mean of 5 trials (input / output)

| Task | cccodex (A) | codex-plugin-cc (B) |
|---|---|---|
| T1 bugfix | 61,859 / 408 | 62,026 / 450 |
| T2 feature | 62,304 / 591 | 62,261 / 643 |
| T3 multi-file | 79,994 / 844 | 79,252 / 828 |

Token usage is effectively identical — same backend doing the same work. Note that codex-plugin-cc does not surface token usage to the caller (numbers above were recovered from `~/.codex/sessions` rollout logs); cccodex's `codex exec --json` stream reports usage directly in the captured event log.

### Fixed overhead — trivial no-op prompt ("reply OK"), read-only

| | cccodex (`codex exec`) | codex-plugin-cc (companion → app server) |
|---|---|---|
| warm, mean of 3 | 5.3 s | 4.0 s |
| cold broker spawn (first call in a session) | n/a (no daemon) | 8.8 s |

Once its broker is warm, codex-plugin-cc answers a trivial turn ~1.3 s faster than a fresh `codex exec` process; its first call in a session pays a ~4–5 s broker spawn that `codex exec` never pays. Both fixed overheads are dwarfed by model time on any real task.

### Hook latency (Claude Code session overhead)

| Plugin | Hook | Fires on | Avg latency |
|---|---|---|---|
| cccodex | `routing-nudge.py` | every user prompt | 18 ms |
| cccodex | `post-edit-nudge.py` | every Edit/Write | 21 ms |
| codex-plugin-cc | `session-lifecycle-hook.mjs` | session start/end only | 37 ms |
| codex-plugin-cc | `stop-review-gate-hook.mjs` | every Stop (opt-in gate) | runs a full Codex review (up to 900 s budget) |

Both are imperceptible in normal use. cccodex pays ~20 ms per prompt/edit to make routing ambient; codex-plugin-cc pays nothing per prompt unless the optional review gate is enabled, in which case every stop can trigger a full Codex review turn.

## What actually differs

The benchmark's headline is that **raw delegation performance is a wash** — same model, same tokens, wall-clock within model-sampling noise. Choosing between the plugins is choosing a workflow:

| | cccodex | openai/codex-plugin-cc |
|---|---|---|
| Trigger model | **ambient soft routing** — hooks nudge Claude to delegate on its own | **explicit slash commands** — you decide when Codex runs |
| Delegation transport | `codex exec` per task (no daemon) | persistent Codex app-server broker (Node.js) |
| After Codex finishes | Claude-side **gatekeeping**: fixer snapshots a baseline, audits scope, restores out-of-scope edits, reviews the diff, re-runs verification | output returned **verbatim** by design (the rescue agent is a "thin forwarder"); verification is on you |
| Role coverage | 4 specialized agents: fixer (write), explorer / librarian / oracle (read-only, effort-tiered low→xhigh) | task delegation + 2 review commands (`/codex:review`, `/codex:adversarial-review`) |
| Background jobs | no (Claude Code's own background agents apply) | yes — `/codex:status`, `/codex:result`, `/codex:cancel`, resumable threads |
| Safety rails | prompt-enforced git read-only policy, baseline snapshots, warn-only `SubagentStop` scope audit | sandboxed read-only reviews; optional Stop review gate |
| Runtime footprint | markdown + 3 small Python hooks | Node.js ≥ 18.18, broker process, job state |

Two consequences worth spelling out:

- **cccodex trades wall-clock for verification.** In real end-to-end use, the fixer's baseline snapshot, scope audit, diff review, and verification re-run add Claude-side time and tokens on top of the ~equal delegation cost measured here. That margin is the product: Codex's work gets independently checked before it reaches you. codex-plugin-cc returns Codex's answer faster because nothing reviews it.
- **codex-plugin-cc trades ambient routing for control.** Nothing happens unless you (or Claude, choosing the rescue agent proactively) invoke it, and long jobs are first-class (background, status, cancel, resume). cccodex instead biases every session toward delegation via ~20 ms hooks — less ceremony per task, less job management.

They also compose: nothing prevents installing both and using cccodex's routing for implementation work alongside `/codex:review` for second-opinion reviews — though both register the `codex:` plugin namespace, so expect overlapping agent lists.

## Caveats

- **n = 5 per cell.** Enough to see that per-task wall-clock differences (±1 s on an ~18 s task) sit inside within-cell variance (T2-B alone ranged 14.5–25.3 s). The 30/30 PASS and near-identical token counts are the robust findings.
- Tasks are small and fully specified. Long, ambiguous tasks would exercise the workflow differences (review gates, scope audits, background jobs) that this primitive-level benchmark deliberately holds constant.
- Claude-side orchestration (agent spin-up, fixer's review/verify passes) is **not** included in the timed paths; both plugins' Claude-side costs depend on session state and model choice.
- Both paths used one machine, one ChatGPT account, the same 15-minute window (the B trials re-ran a few minutes after the A trials following a harness fix — see below). Service-tier load may vary for you.
- **Incident worth knowing about:** an earlier sweep deleted and recreated the fixture repos between trials while a per-workspace app-server broker from a previous session was still alive with its cwd inside the deleted directory — after which every companion call failed instantly with `failed to load configuration`. Normal usage wouldn't delete a workspace out from under a live broker, but it is a concrete example of the stateful-daemon failure mode discussed in the README's design notes. The harness now kills stale brokers up front and resets fixtures in place (`git reset --hard` + `clean`) instead of recreating directories.

## Reproducing

```bash
git clone https://github.com/openai/codex-plugin-cc /tmp/codex-plugin-cc
TRIALS=5 COMPANION_REPO=/tmp/codex-plugin-cc ./benchmarks/run-benchmark.sh
cat /tmp/ccbench/results/results.txt
```

Requires `codex` (logged in), Node ≥ 18.18, Python 3. The harness creates fixture repos under `/tmp/ccbench`, runs all six task cells plus the overhead trials, and externally verifies each repo's test suite.
