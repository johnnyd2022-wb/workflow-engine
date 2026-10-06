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


def _request_fast(monkeypatch):
    monkeypatch.setenv("CI_PIPELINE_SOURCE", "merge_request_event")
    monkeypatch.setenv("CI_MERGE_REQUEST_LABELS", "bug,ci::fast")


def test_fast_docs_have_no_runtime_requirements(monkeypatch):
    _request_fast(monkeypatch)
    plan = selector.fast_plan(["docs/go-live-checklist.md"], "base", "head")
    assert plan["mode"] == "fast"
    assert plan["tests"] == []
    assert not any(plan[key] for key in plan if key.startswith("needs_"))


def test_fast_google_pointer_change_runs_focused_config_tests(monkeypatch):
    _request_fast(monkeypatch)
    old = {("google_sign_in", "keepass_client_id_entry"): "old", ("app", "debug"): "true"}
    new = {**old, ("google_sign_in", "keepass_client_id_entry"): "workflow-engine/GOOGLE_CLIENT_ID"}
    monkeypatch.setattr(selector, "_config_snapshot", lambda ref, path: old if ref == "base" else new)
    plan = selector.fast_plan(["app/config/local.ini", selector.FAST_TEST], "base", "head")
    assert plan["mode"] == "fast"
    assert plan["tests"] == [selector.FAST_TEST]
    assert not plan["needs_database"]
    assert not plan["needs_browser"]


def test_fast_tooling_change_runs_only_its_own_test(monkeypatch):
    """A change to the red-main gate should not wait on the browser smoke or a database."""
    _request_fast(monkeypatch)
    script, test = "scripts/check_main_pipeline.py", "tests/test_check_main_pipeline.py"
    assert selector.FAST_TOOLING[script] == test
    for paths in ([script], [test], [script, test], [script, test, "docs/ci-relevant-test-selection.md"]):
        plan = selector.fast_plan(paths, "base", "head")
        assert plan["mode"] == "fast"
        assert plan["tests"] == [test]
        assert plan["reasons"][test] == [f"ci::fast: non-app tooling {script} / its focused test"]
        assert not any(plan[key] for key in plan if key.startswith("needs_"))


def test_fast_tooling_covers_gates_agent_tooling_and_replay_tooling(monkeypatch):
    _request_fast(monkeypatch)
    paths = ["scripts/whistlebird_replay.py", "scripts/skill_metrics.py", "tests/test_worktree_sweep.py"]
    plan = selector.fast_plan(paths, "base", "head")
    assert plan["tests"] == [
        "tests/test_skill_metrics.py",
        "tests/test_whistlebird_replay.py",
        "tests/test_worktree_sweep.py",
    ]


def test_fast_tooling_scripts_each_have_a_database_free_test_that_exists():
    assert len(selector.FAST_TOOLING) == 19
    for script, test in selector.FAST_TOOLING.items():
        assert (selector.REPO_ROOT / script).is_file() and (selector.REPO_ROOT / test).is_file()
        assert test in selector.DATABASE_FREE_TESTS


def test_fast_tooling_tests_never_reach_for_the_app_or_a_database():
    """The fast path starts no database, so a listed test must not need one."""
    needs_runtime = ("db_session", "create_app", "flask_app", "from app.", "import app", "psycopg", "live_server")
    for test in selector.FAST_TOOLING.values():
        source = (selector.REPO_ROOT / test).read_text(encoding="utf-8")
        assert not [marker for marker in needs_runtime if marker in source], test


def test_fast_never_covers_the_selector_or_scripts_without_a_focused_test(monkeypatch):
    _request_fast(monkeypatch)
    for path in (
        "scripts/select_relevant_tests.py",
        "tests/test_select_relevant_tests.py",
        "scripts/check_backend_size.py",
        "scripts/check_feature_index_routes.py",
        "scripts/whistlebird_migration.py",
        "scripts/whistlebird_np3.py",
        "scripts/database_recovery.py",
        "scripts/run_prod.sh",
        "docs/whistlebird-recent-batches-source.json",
    ):
        assert selector.fast_plan([path], "base", "head") is None, path


def test_fast_tooling_mixed_with_app_or_ci_code_uses_normal_ci(monkeypatch):
    _request_fast(monkeypatch)
    script = "scripts/check_main_pipeline.py"
    for other in (
        "scripts/check_backend_size.py",
        "app/core/security/staff_site_endpoint_registry.py",
        ".gitlab-ci.yml",
    ):
        assert selector.fast_plan([script, other], "base", "head") is None


def test_fast_tooling_without_the_label_uses_normal_ci(monkeypatch):
    monkeypatch.setenv("CI_PIPELINE_SOURCE", "merge_request_event")
    monkeypatch.setenv("CI_MERGE_REQUEST_LABELS", "bug")
    assert selector.fast_plan(["scripts/check_main_pipeline.py"], "base", "head") is None


def test_fast_documentation_is_markdown_anywhere_and_images_under_docs(monkeypatch):
    _request_fast(monkeypatch)
    for path in ("CLAUDE.md", "DEPLOYMENT.md", "app/features/planning/README.md", "docs/img/board.png", "docs/a.pdf"):
        plan = selector.fast_plan([path], "base", "head")
        assert plan["mode"] == "fast" and plan["tests"] == [], path
    for path in ("app/static/logo.png", "docs/data.json", "docs/tool.py", "app/core/frontend/css/core2.css"):
        assert selector.fast_plan([path], "base", "head") is None, path


def test_fast_agent_workspace_change_runs_the_agent_tooling_tests(monkeypatch):
    """Skills, plans and reports cannot affect the app, but the tooling that reads them can break."""
    _request_fast(monkeypatch)
    for path in (".claude/skills/ci-gate/SKILL.md", ".agents/plans/feature-slicing-plan.md", ".agents/routing.json"):
        plan = selector.fast_plan([path], "base", "head")
        assert plan["mode"] == "fast"
        assert plan["tests"] == sorted(selector.FAST_AGENT_WORKSPACE_TESTS)
        assert not any(plan[key] for key in plan if key.startswith("needs_"))


def test_fast_label_cannot_bypass_unrelated_config_values(monkeypatch):
    _request_fast(monkeypatch)
    for key in (("app", "debug"), ("google_sign_in", "enabled"), ("DEFAULT", "password")):
        monkeypatch.setattr(selector, "_config_snapshot", lambda ref, path: {key: ref})
        assert selector.fast_plan(["app/config/local.ini"], "base", "head") is None


def test_fast_label_cannot_bypass_code_ci_dependencies_or_production(monkeypatch):
    _request_fast(monkeypatch)
    for path in (
        "app/config/prod.ini",
        "app/config/test.ini",
        "app/api/app_factory.py",
        "app/api/routes/auth_routes.py",
        "ci/setup_server.sh",
        ".gitlab-ci.yml",
        "uv.lock",
        "scripts/select_relevant_tests.py",
        "tests/conftest.py",
        "tests/test_auth_login_security.py",
        "docs/tool.py",
    ):
        assert selector.fast_plan(["docs/setup.md", path], "base", "head") is None


def test_fast_requires_exact_label_and_mr_pipeline(monkeypatch):
    for source, labels in (
        ("push", "ci::fast"),
        ("schedule", "ci::fast"),
        ("web", "ci::fast"),
        ("merge_request_event", ""),
        ("merge_request_event", "ci::fast-extra"),
    ):
        monkeypatch.setenv("CI_PIPELINE_SOURCE", source)
        monkeypatch.setenv("CI_MERGE_REQUEST_LABELS", labels)
        assert selector.fast_plan(["docs/setup.md"], "base", "head") is None


def test_fast_inspection_failure_falls_back(monkeypatch):
    _request_fast(monkeypatch)

    def unavailable(ref, path):
        raise RuntimeError("missing config revision")

    monkeypatch.setattr(selector, "_config_snapshot", unavailable)
    assert selector.fast_plan(["app/config/local.ini"], "base", "head") is None


def test_deleted_files_are_included_in_diff(monkeypatch):
    from types import SimpleNamespace

    commands = []

    def diff(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="app/api/routes/auth_routes.py\n", stderr="")

    monkeypatch.setattr(selector.subprocess, "run", diff)
    assert selector.changed_paths("base", "head") == ["app/api/routes/auth_routes.py"]
    assert not any(arg.startswith("--diff-filter") for arg in commands[0])
    assert "--no-renames" in commands[0]


def test_fast_eligibility_does_not_read_mr_diff_on_main(monkeypatch):
    monkeypatch.setenv("CI_PIPELINE_SOURCE", "push")
    monkeypatch.setenv("CI_MERGE_REQUEST_LABELS", "ci::fast")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--fast-eligible", "--base", ""])

    def unexpected(*args):
        raise AssertionError("main must not inspect an empty MR diff base")

    monkeypatch.setattr(selector, "changed_paths", unexpected)
    assert selector.main() == 1
