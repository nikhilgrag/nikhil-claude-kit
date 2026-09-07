"""Tests for check_workflow_permissions.

The failure-direction cases matter most: this guard's whole value is refusing
to report success when it could not look. Each writes synthetic workflows under
tmp_path; none reads the real .github/workflows tree.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from check_workflow_permissions import Unauditable, audit, main  # noqa: E402

CALLEE_NEEDS_ID_TOKEN = """
name: callee
on:
  workflow_call:
jobs:
  build:
    permissions:
      contents: read
      id-token: write
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""


def write(directory: Path, **files: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (directory / name.replace("__", ".")).write_text(body, encoding="utf-8")
    return directory


def caller(perms: str) -> str:
    return f"""
name: caller
on:
  push:
    branches: [dev]
jobs:
  gate:
{perms}
    uses: ./.github/workflows/callee.yml
"""


def test_missing_scope_is_reported(tmp_path):
    """Callee wants id-token; caller grants three other scopes."""
    d = write(
        tmp_path,
        caller__yml=caller("    permissions:\n      contents: read\n      checks: write\n"),
        callee__yml=CALLEE_NEEDS_ID_TOKEN,
    )
    findings = audit(d)
    assert len(findings) == 1
    assert "id-token: write" in findings[0]
    assert "caller.yml job `gate`" in findings[0]


def test_satisfied_chain_is_clean(tmp_path):
    d = write(
        tmp_path,
        caller__yml=caller("    permissions:\n      contents: read\n      id-token: write\n"),
        callee__yml=CALLEE_NEEDS_ID_TOKEN,
    )
    assert audit(d) == []


def test_reusable_caller_without_a_block_is_not_flagged(tmp_path):
    """The middle of a three-deep chain passes its caller's token through.

    An intermediate reusable workflow is commonly this shape. Flagging it is a
    false positive, and false positives get guards switched off.
    """
    d = write(
        tmp_path,
        top__yml="""
name: top
on:
  push:
    branches: [dev]
jobs:
  gate:
    permissions:
      contents: read
      id-token: write
    uses: ./.github/workflows/middle.yml
""",
        middle__yml="""
name: middle
on:
  workflow_call:
jobs:
  gate:
    uses: ./.github/workflows/callee.yml
""",
        callee__yml=CALLEE_NEEDS_ID_TOKEN,
    )
    assert audit(d) == []


def test_requirement_is_traced_through_the_middle(tmp_path):
    """A scope needed two hops down must be granted at the top."""
    d = write(
        tmp_path,
        top__yml="""
name: top
on:
  push:
    branches: [dev]
jobs:
  gate:
    permissions:
      contents: read
    uses: ./.github/workflows/middle.yml
""",
        middle__yml="""
name: middle
on:
  workflow_call:
jobs:
  gate:
    uses: ./.github/workflows/callee.yml
""",
        callee__yml=CALLEE_NEEDS_ID_TOKEN,
    )
    findings = audit(d)
    assert len(findings) == 1
    assert "id-token: write" in findings[0]


def test_read_does_not_satisfy_write(tmp_path):
    d = write(
        tmp_path,
        caller__yml=caller("    permissions:\n      contents: read\n      checks: read\n"),
        callee__yml="""
name: callee
on:
  workflow_call:
jobs:
  build:
    permissions:
      checks: write
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
""",
    )
    findings = audit(d)
    assert len(findings) == 1 and "checks: write" in findings[0]


def test_write_all_satisfies_everything(tmp_path):
    d = write(
        tmp_path,
        caller__yml=caller("    permissions: write-all\n"),
        callee__yml=CALLEE_NEEDS_ID_TOKEN,
    )
    assert audit(d) == []


def test_read_all_does_not_satisfy_a_write(tmp_path):
    d = write(
        tmp_path,
        caller__yml=caller("    permissions: read-all\n"),
        callee__yml=CALLEE_NEEDS_ID_TOKEN,
    )
    assert len(audit(d)) == 1


def test_workflow_level_grant_is_used_when_the_job_has_none(tmp_path):
    d = write(
        tmp_path,
        caller__yml="""
name: caller
on:
  push:
    branches: [dev]
permissions:
  contents: read
  id-token: write
jobs:
  gate:
    uses: ./.github/workflows/callee.yml
""",
        callee__yml=CALLEE_NEEDS_ID_TOKEN,
    )
    assert audit(d) == []


def test_top_level_caller_with_no_block_anywhere_is_flagged(tmp_path):
    d = write(
        tmp_path,
        caller__yml="""
name: caller
on:
  push:
    branches: [dev]
jobs:
  gate:
    uses: ./.github/workflows/callee.yml
""",
        callee__yml=CALLEE_NEEDS_ID_TOKEN,
    )
    findings = audit(d)
    assert len(findings) == 1
    assert "no permissions block anywhere" in findings[0]


# ── failure direction: these must fail, never pass ──────────────────────


def test_unparseable_workflow_fails(tmp_path):
    d = write(tmp_path, broken__yml="jobs:\n  a:\n   - [unclosed\n")
    with pytest.raises(Unauditable, match="not parseable YAML"):
        audit(d)


def test_missing_callee_fails(tmp_path):
    d = write(tmp_path, caller__yml=caller("    permissions:\n      contents: read\n"))
    with pytest.raises(Unauditable, match="was not found"):
        audit(d)


def test_empty_directory_fails(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(Unauditable, match="no workflow files"):
        audit(d)


def test_absent_directory_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["x", str(tmp_path / "nope")])
    assert main() == 1
    assert "not a directory" in capsys.readouterr().out


def test_unauditable_exits_nonzero_rather_than_reporting_ok(tmp_path, monkeypatch, capsys):
    d = write(tmp_path, broken__yml="a:\n - [unclosed\n")
    monkeypatch.setattr(sys, "argv", ["x", str(d)])
    assert main() == 1
    out = capsys.readouterr().out
    assert "could not run" in out and "OK:" not in out


def test_main_exits_zero_only_when_clean(tmp_path, monkeypatch, capsys):
    d = write(
        tmp_path,
        caller__yml=caller("    permissions:\n      contents: read\n      id-token: write\n"),
        callee__yml=CALLEE_NEEDS_ID_TOKEN,
    )
    monkeypatch.setattr(sys, "argv", ["x", str(d)])
    assert main() == 0
    assert "OK:" in capsys.readouterr().out
