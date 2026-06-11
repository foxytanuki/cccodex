#!/usr/bin/env python3
"""Nudge Claude back toward Codex after substantial direct edits."""
import json
import os
import re
import sys
import tempfile


MIN_CHANGED_LINES = 20
CUMULATIVE_LINES = 60
MULTI_FILE_THRESHOLD = 3


def changed_lines(tool_input):
    if not isinstance(tool_input, dict):
        return 0

    if "new_source" in tool_input:
        if tool_input.get("edit_mode") == "delete":
            return 0
        return str(tool_input.get("new_source") or "").count("\n") + 1

    if "content" in tool_input:
        return str(tool_input.get("content") or "").count("\n") + 1

    if "new_string" in tool_input or "old_string" in tool_input:
        old = str(tool_input.get("old_string") or "")
        new = str(tool_input.get("new_string") or "")
        return max(old.count("\n") + 1, new.count("\n") + 1)

    edits = tool_input.get("edits")
    if isinstance(edits, list):
        total = 0
        for edit in edits:
            if isinstance(edit, dict):
                total += changed_lines(edit)
        return total

    return 0


def load_state(state_file):
    try:
        with open(state_file) as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            return data
    except Exception:
        pass
    return {"files": {}}


def save_state(state_file, state):
    try:
        tmp_dir = os.path.dirname(state_file)
        fd, tmp_path = tempfile.mkstemp(dir=tmp_dir)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
            os.replace(tmp_path, state_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    tool_input = payload.get("tool_input") or payload.get("toolInput")
    n = changed_lines(tool_input)
    # Zero-line events (notebook cell deletes, unknown payload shapes) must not
    # create accumulator entries — they would inflate the multi-file trigger.
    if n <= 0:
        return

    sid = re.sub(r"[^A-Za-z0-9._-]", "", str(payload.get("session_id") or "default"))[:64]
    state_file = os.path.join(tempfile.gettempdir(), "codex-postedit-" + sid + ".json")
    state = load_state(state_file)
    files = state.get("files", {})

    path = (
        (tool_input.get("file_path") if isinstance(tool_input, dict) else None)
        or (tool_input.get("notebook_path") if isinstance(tool_input, dict) else None)
        or "<unknown>"
    )

    if "content" in (tool_input or {}):
        files[path] = max(files.get(path, 0), n)
    else:
        files[path] = files.get(path, 0) + n

    total = sum(files.values())
    count = len(files)

    single_trigger = n >= MIN_CHANGED_LINES
    cumulative_trigger = total >= CUMULATIVE_LINES
    multifile_trigger = count >= MULTI_FILE_THRESHOLD

    if single_trigger or cumulative_trigger or multifile_trigger:
        save_state(state_file, {"files": {}})

        if single_trigger and not (cumulative_trigger or multifile_trigger):
            first_line = "[Codex] Post-edit nudge"
        else:
            first_line = (
                f"[Codex] Post-edit nudge — direct edits are accumulating "
                f"(~{total} changed lines across {count} file(s) this session)."
            )

        context = (
            first_line + "\n"
            "If this remains a tiny mechanical edit, continue. If the change is expanding "
            "beyond one small file, needs tests, involves design uncertainty, or is becoming "
            "feature/refactor work, stop direct editing and delegate implementation to "
            "the codex:fixer subagent. Claude should then review the Codex diff and verify."
        )

        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            }
        }))
    else:
        save_state(state_file, {"files": files})


if __name__ == "__main__":
    main()
