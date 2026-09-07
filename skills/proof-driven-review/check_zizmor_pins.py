#!/usr/bin/env python3
"""Assert every line-pinned zizmor suppression still lands on its finding.

A zizmor `ignore` entry may be a bare filename (whole-file) or an anchor of the
form `file.yml:LINE[:COL]`. Anchoring is the safer choice -- a new finding in
the same file still fails the gate -- but it couples the config to line numbers
in another file, with nothing keeping them in step. Insert a line anywhere
above the anchor and it silently points at the wrong code: the suppressed
finding returns, and it surfaces on whichever unrelated PR next runs the lint.

Checking that the line merely exists is not enough -- drift usually leaves the
anchor on a real line. So each rule is matched against what could actually
produce it: a `template-injection` anchor must fall inside a `${{ ... }}`
expression, an `unpinned-uses` anchor must sit on a `uses:` line. Rules with no
known shape are checked for line existence only, and named in the output as
unverified rather than counted as clean.

Usage:  check_zizmor_pins.py [<zizmor config>] [<workflows dir>]

Exits 1 on a stale anchor, and on anything that stops the check doing its job
(unparseable config, missing workflow, unreadable file) -- a drift check that
cannot read the files must fail, not report success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

EXPR = re.compile(r"\$\{\{.*?\}\}")
ANCHOR = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+)(?::(?P<col>\d+))?$")


class Unauditable(Exception):
    """The check could not do its job. Never downgraded to a pass."""


def expects_expression(line, col):
    """A template-injection anchor must land inside a ${{ ... }} span.

    Column, not just presence: zizmor points at the expression body, and the
    offset from `${{` varies with internal spacing, so demanding an exact
    column would be brittle in the opposite direction.
    """
    spans = [m.span() for m in EXPR.finditer(line)]
    if not spans:
        return False
    if col is None:
        return True
    return any(start < col <= end for start, end in spans)


def expects_uses(line, col):
    return "uses:" in line


SHAPES = {
    "template-injection": expects_expression,
    "unpinned-uses": expects_uses,
}


def anchors(config: Path):
    """Yield (rule, filename, line, col) for every line-pinned ignore entry."""
    try:
        doc = yaml.safe_load(config.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise Unauditable(f"{config} is not parseable YAML: {e}") from e
    if not isinstance(doc, dict):
        raise Unauditable(f"{config} does not parse to a mapping")

    for rule, body in (doc.get("rules") or {}).items():
        for entry in ((body or {}).get("ignore") or []):
            m = ANCHOR.match(str(entry))
            if m:  # bare filenames are whole-file suppressions; nothing to drift
                yield rule, m["file"], int(m["line"]), int(m["col"]) if m["col"] else None


def audit(config: Path, workflows: Path):
    findings, unverified = [], []
    for rule, name, line_no, col in anchors(config):
        target = workflows / name
        if not target.is_file():
            raise Unauditable(f"{rule} pins {name}:{line_no}, but {target} does not exist")
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            raise Unauditable(f"cannot read {target}: {e}") from e

        where = f"{name}:{line_no}" + (f":{col}" if col else "")
        if not 1 <= line_no <= len(lines):
            findings.append(f"{rule} pins {where}, but {name} has only {len(lines)} lines")
            continue

        line = lines[line_no - 1]
        shape = SHAPES.get(rule)
        if shape is None:
            unverified.append(f"{rule} pins {where} (no known shape for this rule)")
        elif not shape(line, col):
            findings.append(
                f"{rule} pins {where}, but that line cannot produce the finding: "
                f"{line.strip()[:70]!r} -- the anchor has drifted"
            )
    return findings, unverified


def main() -> int:
    config = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/zizmor.yml")
    workflows = Path(sys.argv[2] if len(sys.argv) > 2 else ".github/workflows")
    if not config.is_file():
        print(f"::error::{config} not found; cannot check zizmor anchors")
        return 1
    if not workflows.is_dir():
        print(f"::error::{workflows} is not a directory; cannot check zizmor anchors")
        return 1
    try:
        findings, unverified = audit(config, workflows)
    except Unauditable as e:
        print(f"::error::zizmor anchor check could not run: {e}")
        return 1

    for u in unverified:
        print(f"::warning::{u}")
    for f in findings:
        print(f"::error::{f}")
    if findings:
        print(
            f"\n{len(findings)} stale anchor(s). A drifted anchor suppresses nothing "
            "and returns the finding on the next run of the lint. Re-run zizmor and "
            "update the line:col."
        )
        return 1
    print(f"OK: every line-pinned anchor in {config} still lands on its finding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
