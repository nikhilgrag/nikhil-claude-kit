"""Tests for check_zizmor_pins.

The case that matters most is drift onto a line that still exists: that is what
real drift looks like, and a mere line-existence check would call it clean.
Each test writes synthetic files under tmp_path; none reads a real repo.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from check_zizmor_pins import Unauditable, audit, main  # noqa: E402

# Line 3 holds the interpolation; line 2 is a real but innocent line.
WORKFLOW = """jobs:
  a:
    run: echo "${{ github.actor }}"
    uses: actions/checkout@v4
"""


def setup(tmp_path, config_body, workflow=WORKFLOW):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir(exist_ok=True)
    (wf_dir / "w.yml").write_text(workflow, encoding="utf-8")
    config = tmp_path / "zizmor.yml"
    config.write_text(config_body, encoding="utf-8")
    return config, wf_dir


def test_anchor_on_the_interpolation_is_clean(tmp_path):
    col = WORKFLOW.splitlines()[2].index("github.actor") + 1
    cfg, wf = setup(tmp_path, f"rules:\n  template-injection:\n    ignore:\n      - w.yml:3:{col}\n")
    assert audit(cfg, wf) == ([], [])


def test_drift_onto_a_real_but_innocent_line_is_caught(tmp_path):
    """The live case: an inserted line moved the anchor onto an innocent line.

    The line exists, so existence alone would pass. It cannot produce a
    template-injection finding, so it must fail.
    """
    cfg, wf = setup(tmp_path, "rules:\n  template-injection:\n    ignore:\n      - w.yml:2:5\n")
    findings, _ = audit(cfg, wf)
    assert len(findings) == 1
    assert "drifted" in findings[0] and "w.yml:2:5" in findings[0]


def test_column_outside_the_expression_is_caught(tmp_path):
    """Right line, wrong column -- the anchor no longer covers the expression."""
    cfg, wf = setup(tmp_path, "rules:\n  template-injection:\n    ignore:\n      - w.yml:3:5\n")
    findings, _ = audit(cfg, wf)
    assert len(findings) == 1


def test_line_only_anchor_needs_no_column(tmp_path):
    cfg, wf = setup(tmp_path, "rules:\n  template-injection:\n    ignore:\n      - w.yml:3\n")
    assert audit(cfg, wf) == ([], [])


def test_line_past_end_of_file_is_caught(tmp_path):
    cfg, wf = setup(tmp_path, "rules:\n  template-injection:\n    ignore:\n      - w.yml:900:1\n")
    findings, _ = audit(cfg, wf)
    assert len(findings) == 1 and "only 4 lines" in findings[0]


def test_whole_file_ignores_are_left_alone(tmp_path):
    """A bare filename cannot drift, so it must not be reported."""
    cfg, wf = setup(tmp_path, "rules:\n  template-injection:\n    ignore:\n      - w.yml\n")
    assert audit(cfg, wf) == ([], [])


def test_unpinned_uses_anchor_checks_for_a_uses_line(tmp_path):
    ok = "rules:\n  unpinned-uses:\n    ignore:\n      - w.yml:4\n"
    bad = "rules:\n  unpinned-uses:\n    ignore:\n      - w.yml:1\n"
    cfg, wf = setup(tmp_path, ok)
    assert audit(cfg, wf) == ([], [])
    cfg.write_text(bad, encoding="utf-8")
    assert len(audit(cfg, wf)[0]) == 1


def test_unknown_rule_is_reported_as_unverified_not_clean(tmp_path):
    """Silence would imply the anchor was checked. Say it wasn't."""
    cfg, wf = setup(tmp_path, "rules:\n  some-future-rule:\n    ignore:\n      - w.yml:2:5\n")
    findings, unverified = audit(cfg, wf)
    assert findings == []
    assert len(unverified) == 1 and "no known shape" in unverified[0]


def test_config_without_rules_is_clean(tmp_path):
    cfg, wf = setup(tmp_path, "rules: {}\n")
    assert audit(cfg, wf) == ([], [])


# ── failure direction: these must fail, never pass ──────────────────────


def test_missing_workflow_fails(tmp_path):
    cfg, wf = setup(tmp_path, "rules:\n  template-injection:\n    ignore:\n      - gone.yml:3:5\n")
    with pytest.raises(Unauditable, match="does not exist"):
        audit(cfg, wf)


def test_unparseable_config_fails(tmp_path):
    cfg, wf = setup(tmp_path, "rules:\n  - [unclosed\n")
    with pytest.raises(Unauditable, match="not parseable YAML"):
        audit(cfg, wf)


def test_non_mapping_config_fails(tmp_path):
    cfg, wf = setup(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(Unauditable, match="does not parse to a mapping"):
        audit(cfg, wf)


def test_absent_config_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["x", str(tmp_path / "nope.yml"), str(tmp_path)])
    assert main() == 1
    assert "not found" in capsys.readouterr().out


def test_unauditable_exits_nonzero_rather_than_reporting_ok(tmp_path, monkeypatch, capsys):
    cfg, wf = setup(tmp_path, "rules:\n  template-injection:\n    ignore:\n      - gone.yml:1\n")
    monkeypatch.setattr(sys, "argv", ["x", str(cfg), str(wf)])
    assert main() == 1
    out = capsys.readouterr().out
    assert "could not run" in out and "OK:" not in out


def test_main_exits_zero_only_when_clean(tmp_path, monkeypatch, capsys):
    cfg, wf = setup(tmp_path, "rules:\n  template-injection:\n    ignore:\n      - w.yml:3\n")
    monkeypatch.setattr(sys, "argv", ["x", str(cfg), str(wf)])
    assert main() == 0
    assert "OK:" in capsys.readouterr().out
