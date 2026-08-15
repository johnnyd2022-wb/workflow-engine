"""Tests for scripts/test_map_check.py's structural checks on .agents/test-map.md.

Pure over inline markdown fixtures: no filesystem dependency on the real map, so these
stay valid however the real file's rows evolve. The point is `stale_gap_refs` — the
"Known highest-value gaps" section citing a row the table above it already marks
`covered` — findings-sweep found this drift (2026-08-16) undetected because the script
only checked file references, not gaps-vs-table consistency.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "test_map_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("test_map_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


test_map_check = _load_module()

_TABLE = """
| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 6 | Org read | org_routes.py | test_org_routes.py | covered | now proven |
| 7 | Org membership | org_routes.py | test_org_routes.py | covered | now proven |
| 13 | Execution lineage | dagtraversal.py | test_dag_traversal.py | partial | still gapped |
"""


def test_row_statuses_reads_the_status_column():
    statuses = test_map_check.row_statuses(_TABLE)
    assert statuses == {6: "covered", 7: "covered", 13: "partial"}


def test_stale_gap_refs_flags_a_covered_row_still_cited_as_a_gap():
    """Red case: the gaps section cites Row 6, but the table already marks it covered."""
    text = _TABLE + "\n## Known highest-value gaps\n\n1. **Row 6** — org CRUD untested.\n"
    assert test_map_check.stale_gap_refs(text) == ["Row 6"]


def test_stale_gap_refs_flags_every_row_in_a_slash_separated_group():
    text = _TABLE + "\n## Known highest-value gaps\n\n1. **Row 6 / 7** — org stuff.\n"
    assert test_map_check.stale_gap_refs(text) == ["Row 6", "Row 7"]


def test_stale_gap_refs_is_clean_when_the_cited_row_is_still_partial():
    """Green case: citing a genuinely non-covered row is not stale."""
    text = _TABLE + "\n## Known highest-value gaps\n\n1. **Row 13** — lineage untested.\n"
    assert test_map_check.stale_gap_refs(text) == []


def test_stale_gap_refs_stops_at_the_next_heading():
    """A `**Row 6**`-shaped mention after the gaps section (e.g. in 'Not in this map')
    must not be swept in — only bullets inside the gaps section itself count."""
    text = (
        _TABLE
        + "\n## Known highest-value gaps\n\n1. **Row 13** — lineage untested.\n"
        + "\n## Not in this map (owned elsewhere)\n\n- unrelated mention of **Row 6** here.\n"
    )
    assert test_map_check.stale_gap_refs(text) == []


def test_stale_gap_refs_empty_when_section_absent():
    assert test_map_check.stale_gap_refs(_TABLE) == []


def test_analyse_against_the_real_map_has_no_stale_gap_refs():
    """The real .agents/test-map.md, as findings-sweep left it (2026-08-16): the gaps
    section must only cite rows the table doesn't already call `covered`."""
    report = test_map_check.analyse()
    assert report["problems"]["stale_gap_refs"] == []
