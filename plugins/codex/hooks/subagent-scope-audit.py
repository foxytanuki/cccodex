#!/usr/bin/env python3
"""Warn-only deterministic backstop for the fixer agent's scope audit.

Contract with fixer.md: each fixer run writes a manifest JSON
{"snap_dir": "<dir>", "cwd": "<abs path>", "scope_files": ["..."]}
into "${TMPDIR:-/tmp}/codex-fixer-manifests/" named "<epoch>-<pid>.json";
snap_dir contains "status-before.txt" (git status --porcelain at task start).

This hook fires on SubagentStop, parses the newest applicable manifest,
compares git status before vs after, and prints a warning if any out-of-scope
paths changed or disappeared (disappearance usually means restored toward HEAD).

Accepted limitation: two concurrent fixer runs in the same cwd can
cross-attribute via the newest-manifest heuristic — harmless because warn-only.
"""
import json
import os
import subprocess
import sys
import tempfile
import time


def parse_status_lines(text):
    """Parse git status --porcelain output into a set of paths."""
    paths = set()
    for line in text.splitlines():
        if not line:
            continue
        rest = line[3:]
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        rest = rest.strip().strip('"')
        paths.add(rest)
    return paths


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    try:
        for key in ("agent_type", "subagent_type", "agentType"):
            val = payload.get(key)
            if val is not None:
                if "fixer" not in str(val):
                    return
                break

        manifest_dir = os.path.join(tempfile.gettempdir(), "codex-fixer-manifests")
        if not os.path.isdir(manifest_dir):
            return

        cwd = payload.get("cwd") or os.getcwd()
        now = time.time()
        best_manifest = None
        best_mtime = 0
        best_data = None

        for fname in os.listdir(manifest_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(manifest_dir, fname)
            try:
                mtime = os.path.getmtime(fpath)
                if now - mtime > 86400:
                    try:
                        os.unlink(fpath)
                    except Exception:
                        pass
                    continue
                with open(fpath) as f:
                    data = json.load(f)
                if data.get("cwd") == cwd and mtime > best_mtime:
                    best_manifest = fpath
                    best_mtime = mtime
                    best_data = data
            except Exception:
                continue

        if best_manifest is None:
            return

        snap_dir = best_data.get("snap_dir", "")
        scope_files = set(best_data.get("scope_files", []))

        before_file = os.path.join(snap_dir, "status-before.txt")
        try:
            with open(before_file) as f:
                before_text = f.read()
        except Exception:
            os.replace(best_manifest, best_manifest + ".done")
            return

        before = parse_status_lines(before_text)

        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            after = parse_status_lines(result.stdout)
        except Exception:
            os.replace(best_manifest, best_manifest + ".done")
            return

        newly_dirty = after - before - scope_files
        vanished = before - after - scope_files

        if newly_dirty or vanished:
            warnings = []
            if newly_dirty:
                warnings.append(
                    "Out-of-scope paths newly changed: "
                    + ", ".join(sorted(newly_dirty))
                )
            if vanished:
                warnings.append(
                    "Paths that left the dirty set (possible restore-toward-HEAD / data loss): "
                    + ", ".join(sorted(vanished))
                )
            warnings.append(f"Snapshot dir: {snap_dir}")
            warnings.append(
                "Sanctioned remedy: restore out-of-scope modified files from "
                '"<snap_dir>/files/<path>" (task-start content, never from HEAD); '
                "delete out-of-scope created files; "
                "if the change might belong to another agent running alongside, leave it and report instead."
            )

            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "SubagentStop",
                    "additionalContext": "[Codex] fixer scope audit\n" + "\n".join(warnings),
                }
            }))

        os.replace(best_manifest, best_manifest + ".done")

    except Exception:
        pass


if __name__ == "__main__":
    main()
