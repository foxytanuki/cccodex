#!/usr/bin/env bash
# Reproducible benchmark: cccodex fixer delegation primitive (codex exec)
# vs openai/codex-plugin-cc rescue delegation primitive (codex-companion.mjs task).
#
# Both paths end up at the same Codex backend. This harness measures the
# delegation machinery each plugin actually runs, on identical fixture tasks,
# pinned to the same model/effort/tier so the comparison is apples-to-apples.
#
# Requirements:
#   - codex CLI installed and logged in (`codex login`)
#   - node >= 18.18
#   - a clone of https://github.com/openai/codex-plugin-cc (set COMPANION_REPO)
#
# Usage:
#   COMPANION_REPO=/path/to/codex-plugin-cc ./benchmarks/run-benchmark.sh
#
# Results land in $BENCH_DIR/results/results.txt (default /tmp/ccbench).
set -u

BENCH_DIR="${BENCH_DIR:-/tmp/ccbench}"
COMPANION_REPO="${COMPANION_REPO:?set COMPANION_REPO to a clone of openai/codex-plugin-cc}"
COMPANION="$COMPANION_REPO/plugins/codex/scripts/codex-companion.mjs"
MODEL="${BENCH_MODEL:-gpt-5.5}"
EFFORT="${BENCH_EFFORT:-medium}"
RES="$BENCH_DIR/results"

[ -f "$COMPANION" ] || { echo "codex-companion.mjs not found at $COMPANION" >&2; exit 1; }
mkdir -p "$RES"

now() { date +%s.%N; }
verify() { ( cd "$1" && timeout 60 python3 -m unittest -q >/dev/null 2>&1 ) && echo PASS || echo FAIL; }
diffstat() { ( cd "$1" && git diff --shortstat ); }

# ---------------------------------------------------------------- fixtures
make_t1() { # buggy median(): even-length lists must average the middle pair
  local d="$1"; rm -rf "$d"; mkdir -p "$d"; cd "$d"
  cat > stats.py <<'EOF'
def median(values):
    """Return the median of a non-empty list of numbers."""
    if not values:
        raise ValueError("median of empty list")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return s[mid]  # BUG: even-length lists must average the two middle values


def mean(values):
    if not values:
        raise ValueError("mean of empty list")
    return sum(values) / len(values)
EOF
  cat > test_stats.py <<'EOF'
import unittest
from stats import median, mean


class TestMedian(unittest.TestCase):
    def test_odd(self):
        self.assertEqual(median([3, 1, 2]), 2)

    def test_even(self):
        self.assertEqual(median([1, 2, 3, 4]), 2.5)

    def test_even_unsorted(self):
        self.assertEqual(median([7, 1]), 4.0)

    def test_single(self):
        self.assertEqual(median([5]), 5)

    def test_empty(self):
        with self.assertRaises(ValueError):
            median([])


class TestMean(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(mean([1, 2, 3]), 2.0)


if __name__ == "__main__":
    unittest.main()
EOF
  git init -q && git add -A && git -c user.email=b@b -c user.name=bench commit -qm init
}

make_t2() { # implement slugify() against pre-written failing tests
  local d="$1"; rm -rf "$d"; mkdir -p "$d"; cd "$d"
  cat > textutil.py <<'EOF'
"""Text utilities."""


def truncate(text, limit):
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
EOF
  cat > test_textutil.py <<'EOF'
import unittest
from textutil import slugify, truncate


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_punctuation(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_multiple_spaces(self):
        self.assertEqual(slugify("a   b\t c"), "a-b-c")

    def test_leading_trailing(self):
        self.assertEqual(slugify("  --Hello--  "), "hello")

    def test_unicode_stripped(self):
        self.assertEqual(slugify("café au lait"), "caf-au-lait")

    def test_numbers_kept(self):
        self.assertEqual(slugify("Top 10 Tips"), "top-10-tips")

    def test_empty(self):
        self.assertEqual(slugify(""), "")

    def test_collapse_hyphens(self):
        self.assertEqual(slugify("a -- b"), "a-b")


class TestTruncate(unittest.TestCase):
    def test_no_truncate(self):
        self.assertEqual(truncate("abc", 5), "abc")


if __name__ == "__main__":
    unittest.main()
EOF
  git init -q && git add -A && git -c user.email=b@b -c user.name=bench commit -qm init
}

make_t3() { # multi-file change: new store methods + new CLI command
  local d="$1"; rm -rf "$d"; mkdir -p "$d/taskdb"; cd "$d"
  cat > taskdb/__init__.py <<'EOF'
from taskdb.core import TaskStore
EOF
  cat > taskdb/core.py <<'EOF'
class TaskStore:
    """In-memory task store."""

    def __init__(self):
        self._tasks = {}
        self._next_id = 1

    def add(self, title):
        task_id = self._next_id
        self._next_id += 1
        self._tasks[task_id] = {"id": task_id, "title": title, "done": False}
        return task_id

    def get(self, task_id):
        return self._tasks[task_id]

    def list_tasks(self):
        return sorted(self._tasks.values(), key=lambda t: t["id"])
EOF
  cat > taskdb/cli.py <<'EOF'
import sys

from taskdb.core import TaskStore


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    store = TaskStore()
    if not argv:
        print("usage: taskdb add <title>")
        return 1
    if argv[0] == "add":
        task_id = store.add(" ".join(argv[1:]))
        print(f"added task {task_id}")
        return 0
    print(f"unknown command: {argv[0]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
EOF
  cat > test_taskdb.py <<'EOF'
import unittest

from taskdb.core import TaskStore
from taskdb.cli import main


class TestComplete(unittest.TestCase):
    def test_complete_marks_done(self):
        store = TaskStore()
        tid = store.add("write docs")
        store.complete(tid)
        self.assertTrue(store.get(tid)["done"])

    def test_complete_unknown_raises(self):
        store = TaskStore()
        with self.assertRaises(KeyError):
            store.complete(99)

    def test_pending_excludes_done(self):
        store = TaskStore()
        a = store.add("a")
        b = store.add("b")
        store.complete(a)
        pending = store.pending()
        self.assertEqual([t["id"] for t in pending], [b])


class TestCliDone(unittest.TestCase):
    def test_done_command_output(self):
        self.assertEqual(main(["done"]), 1)


if __name__ == "__main__":
    unittest.main()
EOF
  git init -q && git add -A && git -c user.email=b@b -c user.name=bench commit -qm init
}

for v in a b; do
  make_t1 "$BENCH_DIR/T1-$v"
  make_t2 "$BENCH_DIR/T2-$v"
  make_t3 "$BENCH_DIR/T3-$v"
done
cd "$BENCH_DIR"

# ---------------------------------------------------------------- prompts
# Path A gets the fixer prompt template; Path B gets the same task content
# phrased the way a user would hand it to /codex:rescue. Same information,
# each plugin's own scaffolding — the scaffolding is part of the product.
cat > "$RES/t1a.prompt" <<'EOF'
Goal: Fix the bug in stats.py so that all tests in test_stats.py pass.
Scope: edit ONLY these files: stats.py
Acceptance criteria: `python3 -m unittest -q` passes (6 tests, 0 failures).
Verify with: python3 -m unittest -q
Constraints: match surrounding style; make the smallest correct change; do not rewrite unrelated code; git is read-only — never run `git stash/checkout/restore/reset/clean/add/commit/rebase/merge/pull` and never restore any file toward HEAD content.
EOF
cat > "$RES/t1b.prompt" <<'EOF'
Fix the bug in stats.py so that all tests in test_stats.py pass. Verify with `python3 -m unittest -q` (6 tests, 0 failures). Edit only stats.py and make the smallest correct change.
EOF
cat > "$RES/t2a.prompt" <<'EOF'
Goal: Implement a slugify() function in textutil.py so that all tests in test_textutil.py pass.
Scope: edit ONLY these files: textutil.py
Acceptance criteria: `python3 -m unittest -q` passes (9 tests, 0 failures).
Verify with: python3 -m unittest -q
Constraints: match surrounding style; make the smallest correct change; do not rewrite unrelated code; git is read-only — never run `git stash/checkout/restore/reset/clean/add/commit/rebase/merge/pull` and never restore any file toward HEAD content.
EOF
cat > "$RES/t2b.prompt" <<'EOF'
Implement a slugify() function in textutil.py so that all tests in test_textutil.py pass. Verify with `python3 -m unittest -q` (9 tests, 0 failures). Edit only textutil.py and make the smallest correct change.
EOF
cat > "$RES/t3a.prompt" <<'EOF'
Goal: Add a complete(task_id) method and a pending() method to TaskStore in taskdb/core.py, and a `done` CLI command in taskdb/cli.py, so that all tests in test_taskdb.py pass.
Scope: edit ONLY these files: taskdb/core.py, taskdb/cli.py
Acceptance criteria: `python3 -m unittest -q` passes (4 tests, 0 failures).
Verify with: python3 -m unittest -q
Constraints: match surrounding style; make the smallest correct change; do not rewrite unrelated code; git is read-only — never run `git stash/checkout/restore/reset/clean/add/commit/rebase/merge/pull` and never restore any file toward HEAD content.
EOF
cat > "$RES/t3b.prompt" <<'EOF'
Add a complete(task_id) method and a pending() method to TaskStore in taskdb/core.py, and a `done` CLI command in taskdb/cli.py, so that all tests in test_taskdb.py pass. Verify with `python3 -m unittest -q` (4 tests, 0 failures). Edit only taskdb/core.py and taskdb/cli.py and make the smallest correct change.
EOF

# ---------------------------------------------------------------- runners
run_a() { # cccodex fixer primitive
  local name="$1" repo="$2" pf="$3"
  local OUT="$RES/$name.out.md" EVT="$RES/$name.evt.jsonl" ERR="$RES/$name.err"
  local t0 t1; t0=$(now)
  codex exec --skip-git-repo-check -s workspace-write -C "$repo" \
    -m "$MODEL" \
    -c "model_reasoning_effort=\"$EFFORT\"" \
    -c 'service_tier="fast"' \
    --json -o "$OUT" \
    "$(cat "$pf")" </dev/null >"$EVT" 2>"$ERR"
  local rc=$?; t1=$(now)
  local tokens; tokens=$(grep -o '"cached_input_tokens":[0-9]*\|"input_tokens":[0-9]*\|"output_tokens":[0-9]*' "$EVT" | tail -3 | tr '\n' ' ')
  echo "$name|A|rc=$rc|wall=$(echo "$t1 - $t0" | bc)|verify=$(verify "$repo")|diff=$(diffstat "$repo")|tokens=$tokens" >> "$RES/results.txt"
}

run_b() { # codex-plugin-cc rescue primitive
  local name="$1" repo="$2" pf="$3"
  local LOG="$RES/$name.log"
  local t0 t1; t0=$(now)
  ( cd "$repo" && node "$COMPANION" task --write --fresh "$(cat "$pf")" ) >"$LOG" 2>&1
  local rc=$?; t1=$(now)
  echo "$name|B|rc=$rc|wall=$(echo "$t1 - $t0" | bc)|verify=$(verify "$repo")|diff=$(diffstat "$repo")" >> "$RES/results.txt"
}

echo "=== run start $(date -Is) model=$MODEL effort=$EFFORT ===" >> "$RES/results.txt"

run_a T1 "$BENCH_DIR/T1-a" "$RES/t1a.prompt"
run_a T2 "$BENCH_DIR/T2-a" "$RES/t2a.prompt"
run_a T3 "$BENCH_DIR/T3-a" "$RES/t3a.prompt"

run_b T1 "$BENCH_DIR/T1-b" "$RES/t1b.prompt"
run_b T2 "$BENCH_DIR/T2-b" "$RES/t2b.prompt"
run_b T3 "$BENCH_DIR/T3-b" "$RES/t3b.prompt"

# ------------------------------------------- overhead microbenchmark
TRIV="Reply with the single word OK. Do not read files, do not make any changes."
for i in 1 2 3; do
  t0=$(now)
  codex exec --skip-git-repo-check -s read-only -C "$BENCH_DIR/T1-a" \
    -m "$MODEL" -c "model_reasoning_effort=\"$EFFORT\"" -c 'service_tier="fast"' \
    --json -o "$RES/triv-a-$i.out" "$TRIV" </dev/null >"$RES/triv-a-$i.evt" 2>/dev/null
  t1=$(now)
  echo "TRIV$i|A|wall=$(echo "$t1 - $t0" | bc)" >> "$RES/results.txt"
done
for i in 1 2 3; do
  t0=$(now)
  ( cd "$BENCH_DIR/T1-b" && node "$COMPANION" task --fresh "$TRIV" ) >"$RES/triv-b-$i.log" 2>&1
  t1=$(now)
  echo "TRIV$i|B|wall=$(echo "$t1 - $t0" | bc)" >> "$RES/results.txt"
done

echo "=== run end $(date -Is) ===" >> "$RES/results.txt"
echo "Results: $RES/results.txt"
