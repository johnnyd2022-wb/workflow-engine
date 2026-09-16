"""Regression tests for the deterministic merge-request test selector."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "select_relevant_tests.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("select_relevant_tests", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


selector = _load_module()


def test_inventory_ui_selects_database_free_frontend_regressions():
    plan = selector.select(["app/core/frontend/inventory/inventory.js"])

    assert plan["mode"] == "selected"
    assert "tests/test_execution_modal_frontend_assets.py" in plan["tests"]
    assert "tests/test_inventory_csv_validation.py" in plan["tests"]
    assert plan["needs_browser"] is False
    assert plan["needs_server"] is False
    assert plan["needs_database"] is False
    assert (
        "Inventory UI: app/core/frontend/inventory/inventory.js"
        in plan["reasons"]["tests/test_inventory_csv_validation.py"]
    )


def test_changed_test_is_run_even_without_a_source_mapping():
    plan = selector.select(["tests/test_whistlebird_replay_timeline.py"])

    assert plan["mode"] == "selected"
    assert plan["tests"] == ["tests/test_whistlebird_replay_timeline.py"]
    assert plan["needs_browser"] is False
    assert plan["needs_server"] is False


def test_shared_ci_or_migration_change_uses_the_full_suite():
    for path in (".gitlab-ci.yml", "app/core/db/migrations/versions/next.py", "tests/conftest.py"):
        plan = selector.select([path])
        assert plan["mode"] == "full"
        assert plan["tests"] == ["tests/"]
        assert plan["needs_e2e"] is False
        assert plan["needs_database"] is True


def test_unmapped_application_code_falls_back_to_the_full_suite():
    plan = selector.select(["app/brand_new_feature/service.py"])

    assert plan["mode"] == "full"
    assert plan["reasons"]["tests/"] == ["unmapped code path: app/brand_new_feature/service.py"]


def test_docs_only_change_runs_no_pytest_suite():
    plan = selector.select(["docs/architecture.md", ".agents/plans/ci.md"])

    assert plan["mode"] == "none"
    assert plan["tests"] == []


def test_conventional_script_companion_is_selected():
    plan = selector.select(["scripts/test_map_check.py"])

    assert plan["mode"] == "selected"
    assert plan["tests"] == ["tests/test_test_map_check.py"]


def test_frontend_source_does_not_select_a_same_named_python_test():
    plan = selector.select(["app/core/frontend/inventory/inventory.js"])

    assert "tests/test_inventory.py" not in plan["tests"]


def test_node_requirement_is_precise():
    plan = selector.select(["app/core/frontend/js/execution-shared-utils.js"])

    assert plan["needs_node"] is True
    assert plan["needs_database"] is False
