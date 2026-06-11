#!/usr/bin/env python3
"""Inject a compact Codex routing reminder.

This is intentionally a nudge, not a hard router. It mirrors the useful part of
omo-slim: keep the routing rubric fresh without polluting project CLAUDE.md.

It also intentionally fires on every non-slash prompt, with no throttling or session state: context compaction can silently drop earlier copies, and the rubric must be present on exactly the turn a heavy implementation ask arrives — at ~60-80 tokens per turn that is cheaper than it being missing when it matters. Do not add an every-N throttle.
"""
import json
import re
import sys


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    prompt = (payload.get("prompt") or "").strip()
    if not prompt or re.match(r"^/[\w:-]+(\s|$)", prompt):
        return

    context = """[Codex] Routing nudge
Keep Claude Code as the interface/orchestrator. Tiny direct edits are OK. For implementation-heavy work, delegate to codex:fixer. For read-only codebase exploration, use codex:explorer. For docs/API research, use codex:librarian. For hard design/review judgment, use codex:oracle. Claude reviews, integrates, and verifies. For a pre-commit second opinion on a diff, use /codex-review."""

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    main()
