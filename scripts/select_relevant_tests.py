#!/usr/bin/env python3
"""Select the smallest safe pytest target set for a changed file set.

The selector is deliberately deterministic and auditable: it uses an explicit map of
repository areas to regression suites, always includes a changed test itself, and
prints the reason each suite was selected. It never silently under-tests an unfamiliar
application change: shared CI/config/migration changes and unmapped ``app/`` or
``scripts/`` changes fall back to ``tests/``.

Usage:
    python3 scripts/select_relevant_tests.py --base origin/main --head HEAD
    python3 scripts/select_relevant_tests.py --paths app/core/frontend/inventory/main.js
    python3 scripts/select_relevant_tests.py --format pytest --base "$CI_MERGE_REQUEST_DIFF_BASE_SHA"
"""

from __future__ import annotations

import argparse
import configparser
import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
NO_TESTS = "__NO_TESTS__"
FAST_CONFIG_PATHS = frozenset({"app/config/local.ini", "app/config/local.ini.template"})
FAST_TEST = "tests/test_config_google_secrets.py"
FAST_CONFIG_KEYS = frozenset({"keepass_client_id_entry", "keepass_client_secret_entry"})
# Stdlib-only CI gate scripts that never ship in the app, each with the focused test that
# covers it. A ci::fast MR touching only these runs those tests and nothing else. Add a
# script here only together with a database-free test of its own.
FAST_CI_SCRIPTS = {"scripts/check_main_pipeline.py": "tests/test_check_main_pipeline.py"}


@dataclass(frozen=True)
class Rule:
    """One transparent source-area to regression-suite mapping."""

    name: str
    patterns: tuple[str, ...]
    tests: tuple[str, ...]


RULES = (
    Rule(
        "Core execution engine",
        (
            "app/core/backend/**",
            "app/core/domain/**",
            "app/core/db/repositories/execution*",
            "app/core/db/models/execution*",
        ),
        (
            "tests/test_executions.py",
            "tests/test_complete_step_payload.py",
            "tests/test_process_design.py",
            "tests/test_dag_traversal.py",
            "tests/test_traceability.py",
        ),
    ),
    Rule(
        "Inventory domain",
        ("app/core/db/models/inventory*", "app/core/db/repositories/inventory*", "app/core/utils/**"),
        (
            "tests/test_inventory.py",
            "tests/test_inventory_quantity.py",
            "tests/test_inventory_quantity_guard.py",
            "tests/test_inventory_repo.py",
            "tests/test_inventory_wastage_quantity.py",
            "tests/test_unit_conversion.py",
            "tests/test_wastage.py",
        ),
    ),
    Rule(
        "Core API routes",
        ("app/api/routes/**", "app/features/compliance_checks/checks/**"),
        (
            "tests/test_corechecks.py",
            "tests/test_corechecks_routes.py",
            "tests/test_multi_tenant_isolation.py",
            "tests/test_org_routes.py",
        ),
    ),
    Rule(
        "Authentication and tenant security",
        ("app/core/security/**", "app/api/middleware/**"),
        (
            "tests/test_2fa_totp_optimized.py",
            "tests/test_auth_login_security.py",
            "tests/test_auth_password_session.py",
            "tests/test_auth_rate_limit_gating.py",
            "tests/test_login_2fa_flow.py",
            "tests/test_multi_tenant_isolation.py",
            "tests/test_session_interface.py",
            "tests/test_tenant_filter.py",
        ),
    ),
    Rule(
        "Core overview and workflow UI",
        ("app/core/frontend/core/**", "app/core/frontend/dashboard/**", "app/core/frontend/processes/**"),
        (
            "tests/test_dashboard_summary.py",
            "tests/test_execution_modal_frontend_assets.py",
            "tests/test_execution_shared_utils_js.py",
            "tests/test_hub_overview.py",
            "tests/test_process_design.py",
        ),
    ),
    Rule(
        "Inventory UI",
        ("app/core/frontend/inventory/**", "app/core/frontend/inventory_static/**"),
        (
            "tests/test_execution_modal_frontend_assets.py",
            "tests/test_inventory_csv_validation.py",
        ),
    ),
    Rule(
        "Shared frontend UI",
        ("app/core/frontend/css/**", "app/core/frontend/js/**", "app/ui/**"),
        (
            "tests/test_execution_modal_frontend_assets.py",
            "tests/test_execution_shared_utils_js.py",
            "tests/test_ui_shared_access_denied.py",
        ),
    ),
    Rule(
        "Compliant product",
        ("app/features/compliant/**",),
        (
            "tests/test_compliant_catalog.py",
            "tests/test_compliant_dilution.py",
            "tests/test_compliant_frontend_assets.py",
            "tests/test_compliant_module_pages.py",
            "tests/test_compliant_routes.py",
            "tests/test_compliant_subscription_gate.py",
            "tests/test_compliant_tools.py",
            "tests/test_feature_subscriptions.py",
        ),
    ),
    Rule("CRM product", ("app/features/crm/**",), ("tests/test_crm.py",)),
    Rule(
        "Operational cases product",
        ("app/features/operational_cases/**",),
        ("tests/test_operational_cases.py", "tests/test_changes_feed.py"),
    ),
    Rule(
        "Process templates product",
        ("app/features/process_templates/**",),
        ("tests/test_process_templates.py", "tests/test_process_design.py"),
    ),
    Rule("Demo data product", ("app/features/demo_data/**",), ("tests/test_demo_data.py",)),
    Rule(
        "Observability",
        ("app/observability/**",),
        (
            "tests/test_observability_cli.py",
            "tests/test_observability_config.py",
            "tests/test_observability_context.py",
            "tests/test_observability_logging_config.py",
            "tests/test_observability_logging_redaction.py",
            "tests/test_observability_resource.py",
            "tests/test_observability_telemetry_ingress.py",
            "tests/test_observability_tracing.py",
        ),
    ),
)

# These files define the test environment or the application's cross-cutting wiring.
# Running a subset after changing one would create a false sense of safety.
FULL_SUITE_PATTERNS = (
    ".gitlab-ci.yml",
    "ci/**",
    "pyproject.toml",
    "uv.lock",
    "alembic.ini",
    "app/config/**",
    "app/api/app_factory.py",
    "app/app.py",
    "app/core/db/migrations/**",
    "tests/conftest.py",
    "tests/e2e/conftest.py",
)

# These checks inspect frontend assets or use pure utility code. Keeping this allow-list
# small means a new or misclassified test still gets a database by default.
DATABASE_FREE_TESTS = frozenset(
    {
        "tests/test_execution_modal_frontend_assets.py",
        "tests/test_execution_shared_utils_js.py",
        "tests/test_inventory_csv_validation.py",
        "tests/test_ui_shared_access_denied.py",
        FAST_TEST,
        *FAST_CI_SCRIPTS.values(),
    }
)
NODE_TESTS = frozenset({"tests/test_execution_shared_utils_js.py"})


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _existing_test(path: str) -> bool:
    return (REPO_ROOT / path).is_file()


def _configured_test_paths() -> set[str]:
    return {test for rule in RULES for test in rule.tests}


def _validate_rules() -> None:
    missing = sorted(test for test in _configured_test_paths() if not _existing_test(test))
    if missing:
        raise RuntimeError(f"test-selection map names missing tests: {', '.join(missing)}")


def changed_paths(base: str, head: str) -> list[str]:
    """Return the committed files changed from ``base`` to ``head`` in stable order."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"could not diff {base}...{head}: {result.stderr.strip()}")
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def fast_requested() -> bool:
    """Only the exact opt-in label on an MR may request the fast path."""
    return os.environ.get("CI_PIPELINE_SOURCE") == "merge_request_event" and "ci::fast" in {
        label.strip() for label in os.environ.get("CI_MERGE_REQUEST_LABELS", "").split(",")
    }


def _config_snapshot(ref: str, path: str) -> dict[tuple[str, str], str]:
    result = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO_ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"cannot inspect config {path} at {ref}")
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(result.stdout)
    values = {("DEFAULT", key): value for key, value in config.defaults().items()}
    for section in config.sections():
        values.update({(section, key): value for key, value in config.items(section, raw=True)})
        # Preserve empty sections too, so unrelated structural changes are rejected.
        values[(section, "")] = ""
    return values


def fast_plan(paths: list[str], base: str, head: str) -> dict[str, Any] | None:
    """Allow Markdown docs, the local Google credential-entry pointers, or CI gate scripts.

    Content checks use committed snapshots, not the worktree. Unknown files, other
    config keys, additions/deletions of config files, and inspection errors fall back
    to the normal pipeline. The base is the MR diff base supplied by GitLab.
    """
    if not fast_requested() or not paths:
        return None
    if any(
        path not in FAST_CONFIG_PATHS
        and path != FAST_TEST
        and path not in FAST_CI_SCRIPTS
        and path not in FAST_CI_SCRIPTS.values()
        and path != "README.md"
        and not (path.startswith("docs/") and path.endswith(".md"))
        for path in paths
    ):
        return None
    try:
        for path in set(paths) & FAST_CONFIG_PATHS:
            before, after = _config_snapshot(base, path), _config_snapshot(head, path)
            changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
            if not changed.issubset({("google_sign_in", key) for key in FAST_CONFIG_KEYS}):
                return None
    except (RuntimeError, configparser.Error):
        return None
    reasons: dict[str, list[str]] = {}
    if set(paths) & (FAST_CONFIG_PATHS | {FAST_TEST}):
        reasons[FAST_TEST] = ["ci::fast: local Google credential pointers / focused config coverage"]
    for script, test in FAST_CI_SCRIPTS.items():
        if script in paths or test in paths:
            reasons[test] = [f"ci::fast: CI gate script {script} / its focused test"]
    tests = sorted(reasons)
    if any(not _existing_test(test) for test in tests):
        return None
    return {
        "changed_paths": sorted(paths),
        "mode": "fast",
        "tests": tests,
        "reasons": reasons,
        "needs_browser": False,
        "needs_server": False,
        "needs_e2e": False,
        "needs_database": False,
        "needs_node": False,
    }


def _direct_test_for_source(path: str) -> str | None:
    """Use the conventional ``tests/test_<module>.py`` companion when it exists."""
    if not path.endswith(".py"):
        return None
    stem = Path(path).stem
    candidate = f"tests/test_{stem}.py"
    return candidate if _existing_test(candidate) else None


def select(paths: list[str]) -> dict[str, Any]:
    """Return an auditable test plan for ``paths`` without running any tests."""
    _validate_rules()
    normalized = sorted({path.strip().removeprefix("./") for path in paths if path.strip()})
    selected: dict[str, set[str]] = {}
    full_suite_reasons: list[str] = []
    unmapped_code_paths: list[str] = []

    for path in normalized:
        if _matches(path, FULL_SUITE_PATTERNS):
            full_suite_reasons.append(path)
            continue
        if path.startswith("tests/") and path.endswith(".py") and _existing_test(path):
            selected.setdefault(path, set()).add(f"changed test: {path}")
            continue

        matched = False
        for rule in RULES:
            if _matches(path, rule.patterns):
                matched = True
                for test in rule.tests:
                    selected.setdefault(test, set()).add(f"{rule.name}: {path}")

        companion = _direct_test_for_source(path)
        if companion:
            matched = True
            selected.setdefault(companion, set()).add(f"conventional companion: {path}")

        if not matched and (path.startswith("app/") or path.startswith("scripts/")):
            unmapped_code_paths.append(path)

    if full_suite_reasons or unmapped_code_paths:
        reasons = [f"shared test environment: {path}" for path in full_suite_reasons]
        reasons += [f"unmapped code path: {path}" for path in unmapped_code_paths]
        return {
            "changed_paths": normalized,
            "mode": "full",
            "tests": ["tests/"],
            "reasons": {"tests/": reasons},
            # Match the established full-suite CI behaviour. tests/e2e is collected
            # but skipped under ENVIRONMENT=test; deployed smoke E2E remains the CD
            # gate rather than turning a broad fallback into a new, unproven browser
            # matrix.
            "needs_browser": False,
            "needs_server": False,
            "needs_e2e": False,
            "needs_database": True,
            "needs_node": True,
        }

    tests = sorted(selected)
    needs_e2e = any(test.startswith("tests/e2e/") for test in tests)
    needs_server = needs_e2e or any(
        "pytest.mark.live_server" in (REPO_ROOT / test).read_text(encoding="utf-8") for test in tests
    )
    return {
        "changed_paths": normalized,
        "mode": "selected" if tests else "none",
        "tests": tests,
        "reasons": {test: sorted(reasons) for test, reasons in sorted(selected.items())},
        "needs_browser": needs_e2e,
        "needs_server": needs_server,
        "needs_e2e": needs_e2e,
        "needs_database": bool(tests) and (needs_e2e or not set(tests).issubset(DATABASE_FREE_TESTS)),
        "needs_node": bool(set(tests) & NODE_TESTS),
    }


def _render(plan: dict[str, Any]) -> str:
    if plan["mode"] == "none":
        return "No runnable tests selected: documentation-only change."
    lines = [f"{plan['mode']} test run for {len(plan['changed_paths'])} changed file(s):"]
    for test in plan["tests"]:
        lines.append(f"  {test}")
        lines.extend(f"    - {reason}" for reason in plan["reasons"][test])
    requirements = ", ".join(
        label
        for enabled, label in (
            (plan["needs_server"], "app server"),
            (plan["needs_browser"], "Chromium"),
            (plan["needs_database"], "PostgreSQL"),
            (plan["needs_node"], "Node.js"),
        )
        if enabled
    )
    if requirements:
        lines.append(f"Requires: {requirements}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("CI_MERGE_REQUEST_DIFF_BASE_SHA", "origin/main"))
    parser.add_argument("--head", default=os.environ.get("CI_COMMIT_SHA", "HEAD"))
    parser.add_argument(
        "--paths", nargs="*", help="Use these paths instead of querying git; useful for local review/tests."
    )
    parser.add_argument("--format", choices=("human", "json", "pytest"), default="human")
    parser.add_argument(
        "--needs-server", action="store_true", help="Exit 0 only when the selection needs an app server."
    )
    parser.add_argument("--needs-browser", action="store_true", help="Exit 0 only when the selection needs Chromium.")
    parser.add_argument("--needs-e2e", action="store_true", help="Exit 0 only when the selection contains E2E tests.")
    parser.add_argument(
        "--needs-database", action="store_true", help="Exit 0 only when the selection needs PostgreSQL."
    )
    parser.add_argument("--needs-node", action="store_true", help="Exit 0 only when the selection needs Node.js.")
    parser.add_argument("--fast-eligible", action="store_true", help="Exit 0 only for an approved ci::fast MR diff.")
    args = parser.parse_args()

    if args.fast_eligible and not fast_requested():
        print("Normal CI: ci::fast requires an opted-in merge request.")
        return 1

    try:
        paths = args.paths if args.paths is not None else changed_paths(args.base, args.head)
        fast = fast_plan(paths, args.base, args.head)
        if args.fast_eligible:
            if fast:
                print("ci::fast: approved low-impact diff; expensive MR checks are omitted.")
                return 0
            print("Normal CI: ci::fast absent or diff outside the low-impact allow-list.")
            return 1
        plan = fast or select(paths)
    except RuntimeError as exc:
        print(f"test selection failed: {exc}", file=sys.stderr)
        return 2

    requested_requirement = (
        (args.needs_server, "needs_server"),
        (args.needs_browser, "needs_browser"),
        (args.needs_e2e, "needs_e2e"),
        (args.needs_database, "needs_database"),
        (args.needs_node, "needs_node"),
    )
    for requested, key in requested_requirement:
        if requested:
            return 0 if plan[key] else 1

    if args.format == "json":
        print(json.dumps(plan, indent=2, sort_keys=True))
    elif args.format == "pytest":
        print(" ".join(plan["tests"]) if plan["tests"] else NO_TESTS)
    else:
        print(_render(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
