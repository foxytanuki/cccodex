#!/usr/bin/env python3
"""Warn-only deterministic backstop for the fixer agent's scope audit.

Contract with fixer.md: each fixer run writes a manifest JSON
{"snap_dir": "<dir>", "cwd": "<abs path>", "scope_files": ["..."]}
into "${TMPDIR:-/tmp}/codex-fixer-manifests/" named "<epoch>-<pid>.json";
snap_dir contains "fingerprints-before.json", captured with --capture before
delegation, plus task-start copies of dirty and in-scope files.

This hook fires on SubagentStop, parses the newest applicable manifest,
compares file content/mode/link/presence before vs after, and prints a warning
if any out-of-scope paths changed, including already-dirty files.

Accepted limitation: two concurrent fixer runs in the same cwd can
cross-attribute via the newest-manifest heuristic — harmless because warn-only.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time


def repository_root(cwd):
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                            capture_output=True, text=True, check=True, timeout=5)
    return str(Path(result.stdout.strip()).resolve())


def fingerprints(cwd, scope_files):
    """Hash tracked/untracked files, modes and symlink targets, using raw paths."""
    cwd = repository_root(cwd)
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=cwd, capture_output=True, check=True, timeout=5,
    )
    paths = {os.fsdecode(p) for p in result.stdout.split(b"\0") if p}
    paths.update(scope_files)
    values = {}
    for relative in paths:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Scope paths must be relative to the repository")
        path = Path(cwd) / path
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            values[relative] = "absent"
            continue
        if stat.S_ISLNK(mode):
            values[relative] = "link:" + os.readlink(path)
        elif stat.S_ISREG(mode):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            values[relative] = str(stat.S_IMODE(mode)) + ":" + digest.hexdigest()
        else:
            # Submodule/directory contents need separate verification.
            values[relative] = "directory-or-special"
    return values


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    try:
        for key in ("agent_type", "subagent_type", "agentType"):
            val = payload.get(key)
            if val is not None:
                if str(val) not in ("fixer", "codex:fixer"):
                    return
                break

        manifest_dir = os.path.join(tempfile.gettempdir(), "codex-fixer-manifests")
        if not os.path.isdir(manifest_dir):
            return

        cwd = repository_root(payload.get("cwd") or os.getcwd())
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
                if repository_root(data.get("cwd")) == cwd and mtime > best_mtime:
                    best_manifest = fpath
                    best_mtime = mtime
                    best_data = data
            except Exception:
                continue

        if best_manifest is None:
            return

        snap_dir = best_data.get("snap_dir", "")
        scope_files = set(best_data.get("scope_files", []))

        before_file = os.path.join(snap_dir, "fingerprints-before.json")
        try:
            with open(before_file) as f:
                before = json.load(f)
            after = fingerprints(cwd, scope_files)
            changed = {p for p in before.keys() | after.keys()
                       if before.get(p, "absent") != after.get(p, "absent")} - scope_files
            warnings = (["Out-of-scope paths changed since task start: " + ", ".join(sorted(changed))]
                        if changed else [])
        except Exception:
            warnings = ["Scope audit unavailable: baseline or current fingerprints could not be read. Do not report a clean audit."]

        if warnings:
            warnings.append(f"Snapshot dir: {snap_dir}")
            warnings.append(
                "Sanctioned remedy: restore out-of-scope modified files from "
                '"<snap_dir>/files/<path>" only when a snapshot exists (never from HEAD); '
                "delete out-of-scope created files only when their baseline was absent; "
                "if no snapshot exists, report the change instead of reconstructing content; "
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
    if len(sys.argv) > 1 and sys.argv[1] == "--capture":
        destination = Path(sys.argv[2]) / "fingerprints-before.json"
        destination.write_text(json.dumps(fingerprints(os.getcwd(), sys.argv[3:])) + "\n")
    else:
        main()
