#!/usr/bin/env python3
"""Assert every reusable-workflow caller grants what its callee chain requests.

A called workflow may only NARROW its caller's permissions, never widen them.
A scope requested downstream but granted nowhere upstream makes GitHub reject
the entire run as a startup failure: zero jobs, no log, and no check run -- so
the commit still shows a green tick -- and no job for a failure notifier to run
in. The usual cause is a chain with two callers where only one gets updated.

actionlint does not catch this: it lints each workflow in isolation and does not
model cross-workflow permission narrowing.

Usage:  check_workflow_permissions.py [<workflows dir>]

Exits 1 on a shortfall, and also on anything that stops the check doing its job
(unparseable workflow, missing callee, no workflows found) -- an audit that
cannot read the workflows must fail, not report success.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

LOCAL_PREFIX = "./.github/workflows/"
RANK = {"none": 0, "read": 1, "write": 2}


class Unauditable(Exception):
    """The check could not do its job. Never downgraded to a pass."""


def load(directory: Path) -> dict:
    paths = sorted(p for p in directory.iterdir() if p.suffix in (".yml", ".yaml"))
    if not paths:
        raise Unauditable(f"no workflow files under {directory}")
    out = {}
    for p in paths:
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise Unauditable(f"{p.name} is not parseable YAML: {e}") from e
        if not isinstance(doc, dict):
            raise Unauditable(f"{p.name} does not parse to a mapping")
        out[p.name] = doc
    return out


def scopes(block):
    """A permissions block as {scope: level}. None means 'no block present'."""
    if block is None:
        return None
    if isinstance(block, str):
        if block == "write-all":
            return {"__ALL__": "write"}
        if block == "read-all":
            return {"__ALL__": "read"}
        raise Unauditable(f"unrecognised permissions shorthand: {block!r}")
    return {k: str(v) for k, v in block.items()}


def is_reusable(wf: dict) -> bool:
    # YAML 1.1 parses a bare `on:` key as the boolean True.
    on = wf.get("on", wf.get(True)) or {}
    if isinstance(on, str):
        return on == "workflow_call"
    if isinstance(on, list):
        return "workflow_call" in on
    return "workflow_call" in on


def requested(name: str, wfs: dict, seen=frozenset()) -> dict:
    """Every scope the chain rooted at `name` asks for, at its highest level."""
    if name in seen:
        return {}
    if name not in wfs:
        raise Unauditable(f"{name} is referenced by a `uses:` but was not found")
    seen = seen | {name}
    need: dict = {}

    def merge(pairs):
        for scope, level in (pairs or {}).items():
            if RANK.get(level, 0) > RANK.get(need.get(scope, "none"), 0):
                need[scope] = level

    wf = wfs[name]
    merge(scopes(wf.get("permissions")))
    for job in (wf.get("jobs") or {}).values():
        merge(scopes(job.get("permissions")))
        target = job.get("uses")
        if isinstance(target, str) and target.startswith(LOCAL_PREFIX):
            merge(requested(target[len(LOCAL_PREFIX):], wfs, seen))
    return need


def shortfall(grant, need: dict) -> dict:
    if grant and "__ALL__" in grant:
        ceiling = RANK[grant["__ALL__"]]
        return {s: l for s, l in need.items() if RANK.get(l, 0) > ceiling}
    return {
        scope: level
        for scope, level in need.items()
        if scope != "__ALL__"
        and RANK.get(level, 0) > 0
        and RANK.get((grant or {}).get(scope, "none"), 0) < RANK.get(level, 0)
    }


def audit(directory: Path) -> list:
    wfs = load(directory)
    findings = []
    for caller, wf in sorted(wfs.items()):
        for job_name, job in (wf.get("jobs") or {}).items():
            target = job.get("uses")
            if not (isinstance(target, str) and target.startswith(LOCAL_PREFIX)):
                continue
            callee = target[len(LOCAL_PREFIX):]
            need = requested(callee, wfs)

            if job.get("permissions") is not None:
                grant, origin = scopes(job["permissions"]), f"job `{job_name}`"
            elif wf.get("permissions") is not None:
                grant, origin = scopes(wf["permissions"]), f"{caller} workflow level"
            elif is_reusable(wf):
                # No block, and this workflow is itself called: its token is
                # whatever ITS caller granted, so a shortfall belongs to that
                # edge, not this one. Flagging here would be a false positive.
                continue
            else:
                grant, origin = None, f"{caller} (no permissions block anywhere)"

            missing = shortfall(grant, need)
            if missing:
                findings.append(
                    f"{caller} job `{job_name}` -> {callee}: "
                    f"{', '.join(f'{s}: {l}' for s, l in sorted(missing.items()))} "
                    f"requested downstream but not granted by {origin}"
                )
    return findings


def main() -> int:
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/workflows")
    if not directory.is_dir():
        print(f"::error::{directory} is not a directory; cannot audit permissions")
        return 1
    try:
        findings = audit(directory)
    except Unauditable as e:
        print(f"::error::permissions audit could not run: {e}")
        return 1

    for f in findings:
        print(f"::error::{f}")
    if findings:
        print(
            f"\n{len(findings)} caller(s) grant less than their callee chain "
            "requests. GitHub rejects such a run before scheduling any job, with "
            "no check run and no log. Add the scope to the calling job's "
            "`permissions` block."
        )
        return 1
    print(f"OK: every caller under {directory} grants what its chain requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
