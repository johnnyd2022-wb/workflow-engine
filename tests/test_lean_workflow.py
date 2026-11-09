"""The lean workflow's tooling (!671): risk-tier floor, tree-bound receipts, trial report,
and the switch that keeps the classic chain one edit away."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import receipt  # noqa: E402
import risk_tier  # noqa: E402
import workflow_trial  # noqa: E402

# --- risk tier floor ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("paths", "tier"),
    [
        (["docs/guide.md", "app/ui/shared/styles2.css"], "A"),
        (["app/features/crm/frontend/templates/crm/overview.html"], "B"),
        (["tests/test_something.py"], "B"),
        (["app/core/db/migrations/versions/x_001.py"], "C"),
        (["app/core/security/access_policy.py"], "C"),
        (["app/features/compliant/modules/nz_alcohol/wine/register.py"], "C"),
        (["app/features/compliant/modules/nz_alcohol/excise.py"], "C"),
        ([".gitlab-ci.yml"], "C"),
        (["uv.lock"], "C"),
        (["docs/a.md", "app/core/db/migrations/versions/y.py"], "C"),
        ([], "A"),
    ],
)
def test_paths_set_the_floor(paths, tier):
    assert risk_tier.classify(paths)["tier"] == tier


def test_an_unknown_code_path_is_never_tier_a():
    assert risk_tier.classify(["app/features/brand_new/thing.py"])["tier"] == "B"


@pytest.mark.parametrize(
    "line",
    [
        "    .filter(Item.org_id == org_id)",
        "        item.quantity = 0",
        "    with allow_inventory_quantity_write(reason):",
        "        .with_for_update()",
        'db.execute(text("select 1"))',
        "@requires_auth",
        "    amount = Decimal(value)",
    ],
)
def test_a_one_line_risky_change_in_an_ordinary_file_is_tier_c(line):
    result = risk_tier.classify(
        ["app/features/crm/routes/page_routes.py"], {"app/features/crm/routes/page_routes.py": [line]}
    )
    assert result["tier"] == "C" and result["reasons"]


@pytest.mark.parametrize("path", ["tests/test_x.py", "scripts/some_tool.py"])
def test_tests_and_scripts_mentioning_org_id_stay_b(path):
    assert risk_tier.classify([path], {path: ["assert row.org_id == org.id"]})["tier"] == "B"


def test_the_cli_classifies_paths():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts/risk_tier.py"), "--paths", "app/core/security/x.py", "--json"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert json.loads(out.stdout)["tier"] == "C"


# --- receipts -------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "code.py").write_text("x = 1\n")
    return tmp_path


def test_a_passing_receipt_goes_stale_when_the_tree_changes(repo):
    store = repo / ".agents" / "tmp" / "receipts"
    first = receipt.run("unit", [sys.executable, "-c", "pass"], cwd=repo, store=store)
    assert first["verdict"] == "passed"
    assert [r["state"] for r in receipt.status(cwd=repo, store=store)] == ["passed"]
    (repo / "code.py").write_text("x = 2\n")
    assert [r["state"] for r in receipt.status(cwd=repo, store=store)] == ["stale"]


def test_failures_and_no_tests_are_not_passes(repo):
    store = repo / ".agents" / "tmp" / "receipts"
    assert (
        receipt.run("bad", [sys.executable, "-c", "raise SystemExit(1)"], cwd=repo, store=store)["verdict"] == "failed"
    )
    assert (
        receipt.run("empty", [sys.executable, "-c", "raise SystemExit(5)"], cwd=repo, store=store)["verdict"]
        == "no-tests"
    )


def test_receipts_do_not_change_the_tree_they_describe(repo):
    store = repo / ".agents" / "tmp" / "receipts"
    before = receipt.tree_digest(repo)
    receipt.run("unit", [sys.executable, "-c", "pass"], cwd=repo, store=store)
    assert receipt.tree_digest(repo) == before


# --- trial report ---------------------------------------------------------------------


def test_trial_report_groups_by_workflow_and_tier():
    runs = [
        {
            "skill": "lean-change",
            "notes": "workflow=lean kind=bug tier=B rounds=1",
            "duration_s": 1800,
            "findings": 1,
            "ref": "!1",
        },
        {
            "skill": "lean-change",
            "notes": "workflow=lean tier=B rounds=2",
            "duration_s": 3000,
            "findings": 3,
            "ref": "!2",
        },
        {"skill": "fix-bug", "notes": "", "duration_s": 5400, "findings": 4, "ref": "!3"},
        {"skill": "security-audit", "notes": "", "ref": "!4"},
    ]
    outcomes = [{"ref": "!1", "outcome": "merged"}, {"ref": "!3", "outcome": "amended"}]
    report = workflow_trial.summarize(runs, outcomes)
    assert set(report) == {"lean/B", "classic/?"}
    lean = report["lean/B"]
    assert lean["runs"] == 2 and lean["median_rounds"] == 1.5 and lean["median_minutes"] == 40.0
    assert lean["merged"] == 1 and lean["no_outcome_yet"] == 1
    assert report["classic/?"]["amended"] == 1 and report["classic/?"]["median_rounds"] is None


# --- the switch ------------------------------------------------------------------------


def test_the_switch_is_one_value_and_the_classic_chain_is_untouched():
    mode = json.loads((ROOT / ".agents/workflow-mode.json").read_text())
    assert mode["mode"] in ("lean", "classic")
    for skill in ("new-feature", "fix-bug", "review-feature"):
        assert (ROOT / ".claude/skills" / skill / "SKILL.md").exists()
    entry = (ROOT / ".claude/skills/entrypoint/SKILL.md").read_text()
    assert "workflow-mode.json" in entry and "lean-change" in entry


def test_lean_routing_keeps_the_reviewer_read_only():
    import agent_launch

    routing = json.loads((ROOT / ".agents/model-routing.json").read_text())
    assert routing["stages"]["lean-review"]["access"] == "read"
    assert agent_launch.check(routing) == []
    routing["stages"]["lean-review"]["access"] = "write"
    assert any("lean-review" in p for p in agent_launch.check(routing))


def test_committing_the_same_content_keeps_a_receipt_fresh(repo):
    """The digest is the tree's content, not HEAD: a commit with no file change isn't stale."""
    store = repo / ".agents" / "tmp" / "receipts"
    receipt.run("unit", [sys.executable, "-c", "pass"], cwd=repo, store=store)
    subprocess.run(["git", "add", "code.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "same"], cwd=repo, check=True
    )
    assert [r["state"] for r in receipt.status(cwd=repo, store=store)] == ["passed"]
