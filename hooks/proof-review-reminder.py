#!/usr/bin/env python3
"""PreToolUse(Bash): remind to run proof-driven-review before pushing CI changes.

Advisory, not blocking. Prints to stdout (becomes agent context) and always
exits 0 — a bug in this reminder must never block real work. That is a
deliberate direction choice: this is a nudge, not a safety gate.
"""
import json
import re
import subprocess
import sys

# Paths whose failure mode is "green when broken".
WATCHED = re.compile(r"(^\.github/|\.ya?ml$|\.sh$|(^|/)Makefile$|\.bazel$)")

PUSH = re.compile(r"\bgit\s+(?:-\S+\s+)*push\b")
COMMIT = re.compile(r"\bgit\s+(?:-\S+\s+)*commit\b")


def sh(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=10).stdout
    except Exception:
        return ""


def changed_for_push() -> list:
    for rev in ("@{u}..HEAD", "origin/HEAD..HEAD"):
        out = sh("git", "diff", "--name-only", rev)
        if out.strip():
            return out.split()
    return sh("git", "diff", "--name-only", "HEAD~1..HEAD").split()


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") != "Bash":
        return 0

    cmd = (data.get("tool_input") or {}).get("command", "")
    if PUSH.search(cmd):
        files = changed_for_push()
    elif COMMIT.search(cmd):
        files = sh("git", "diff", "--cached", "--name-only").split()
    else:
        return 0

    hits = sorted({f for f in files if WATCHED.search(f)})
    if not hits:
        return 0

    print("proof-driven-review: this push/commit touches files whose failure "
          "mode is a green tick:")
    for f in hits[:15]:
        print(f"  - {f}")
    if len(hits) > 15:
        print(f"  ... and {len(hits) - 15} more")
    print("Invoke the proof-driven-review skill on the FINAL files (not the "
          "diff) before proceeding. If it already ran for this HEAD, say so "
          "and continue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
