"""
Core system checks for inventory, processes, and executions.

Provides a main runner (CoreChecksRunner) that different checks hook into, similar to
DAGTracer in dagtraversal.py: one entry point, pluggable checks. Used for compliance,
expiry, and preventing user mistakes. Results drive sourcemap highlighting, pre-execution
warnings in flows2.html, and top-level banners (e.g. expired materials with stock).

Checks register by id and return a CheckResult (flagged, message, data). The runner
exposes run_check(check_id) and run_all_checks() for APIs and UI.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Check result and runner
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Result of a single check. Used by APIs and UI (banner, warnings)."""

    check_id: str
    flagged: bool
    message: str | None = None
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"check_id": self.check_id, "flagged": self.flagged}
        if self.message is not None:
            out["message"] = self.message
        if self.data is not None:
            out["data"] = self.data
        return out


# Type for a check function: (org_id, session) -> CheckResult
CheckFn = Callable[[UUID, Session], CheckResult]


class CoreChecksRunner:
    """
    Main entry point for core system checks. Different checks register and run
    through this runner (similar to DAGTracer: one class, pluggable operations).
    """

    def __init__(self, org_id: UUID, session: Session):
        self.org_id = org_id
        self.session = session
        self._log = logging.getLogger(__name__)
        self._checks: dict[str, CheckFn] = {}
        self._register_builtin_checks()

    def _register_builtin_checks(self) -> None:
        """Register built-in checks so they can be run by id."""
        from app.core.backend.checks.expired_materials import run_expired_materials_check
        from app.core.backend.checks.output_expiry_check import run_output_expiry_check
        from app.core.backend.checks.output_ready_date_check import (
            CHECK_ID as OUTPUT_READY_DATE_CHECK_ID,
            run_output_ready_date_check,
        )
        from app.core.backend.checks.untracked_items import run_untracked_items_check

        self.register_check("expired_materials", run_expired_materials_check)
        self.register_check("untracked_items", run_untracked_items_check)
        self.register_check("output_expiry", run_output_expiry_check)
        self.register_check(OUTPUT_READY_DATE_CHECK_ID, run_output_ready_date_check)

    def register_check(self, check_id: str, fn: CheckFn) -> None:
        """Register a check so it can be run via run_check(check_id)."""
        self._checks[check_id] = fn

    def run_check(self, check_id: str) -> CheckResult | None:
        """Run a single check by id. Returns None if check_id is unknown."""
        fn = self._checks.get(check_id)
        if not fn:
            self._log.warning("Unknown check_id: %s", check_id)
            return None
        return fn(self.org_id, self.session)

    def run_all_checks(self) -> list[CheckResult]:
        """Run all registered checks. Used for banner and aggregate dashboards."""
        results: list[CheckResult] = []
        for check_id in self._checks:
            try:
                r = self.run_check(check_id)
                if r is not None:
                    results.append(r)
            except Exception as e:
                self._log.exception("Check %s failed: %s", check_id, e)
                results.append(
                    CheckResult(
                        check_id=check_id,
                        flagged=True,
                        message=f"Check failed: {e}",
                        data=None,
                    )
                )
        return results


def get_system_findings_by_item(org_id: UUID, session: Session) -> dict[str, list[dict[str, Any]]]:
    """
    Run all registered checks and return a map: inventory_item_id -> list of { check_id, reason }.
    Used to enrich the inventory list API so each item has system_findings for UI (red border + reasons).
    New checks: add an extractor below for the check's result.data shape; no change to check implementations.
    """
    from app.core.backend.checks.output_ready_date_check import CHECK_ID as OUTPUT_READY_DATE_CHECK_ID

    runner = CoreChecksRunner(org_id=org_id, session=session)
    results = runner.run_all_checks()
    out: dict[str, list[dict[str, Any]]] = {}

    def add(item_id: str, check_id: str, reason: str) -> None:
        if not item_id:
            return
        out.setdefault(item_id, []).append({"check_id": check_id, "reason": reason})

    for r in results:
        if r.data is None:
            continue
        if r.check_id == "untracked_items":
            for it in r.data.get("untracked_items") or []:
                iid = it.get("id") if isinstance(it, dict) else None
                reason = it.get("check_reason") if isinstance(it, dict) else "Untracked inventory item"
                add(str(iid) if iid else "", r.check_id, reason or "Untracked inventory item")
        elif r.check_id == "expired_materials":
            for it in r.data.get("expired_raw_materials") or []:
                iid = it.get("id") if isinstance(it, dict) else None
                add(str(iid) if iid else "", r.check_id, "Expired raw material with stock")
            for it in r.data.get("impacted_items") or []:
                iid = it.get("id") if isinstance(it, dict) else None
                add(str(iid) if iid else "", r.check_id, "Produced using expired raw material")
        elif r.check_id == "output_expiry":
            for it in r.data.get("output_expiry_items") or []:
                iid = it.get("inventory_item_id") if isinstance(it, dict) else None
                reason = it.get("message") if isinstance(it, dict) else "Custom output expiry"
                add(str(iid) if iid else "", r.check_id, reason or "Custom output expiry")
        elif r.check_id == OUTPUT_READY_DATE_CHECK_ID:
            for it in r.data.get("output_ready_date_items") or []:
                iid = it.get("inventory_item_id") if isinstance(it, dict) else None
                reason = it.get("message") if isinstance(it, dict) else None
                state = it.get("state") if isinstance(it, dict) else None
                reason = reason or (state or "Output not yet ready")
                add(str(iid) if iid else "", r.check_id, reason)

    return out


# ---------------------------------------------------------------------------
# API route registration (called from backend.py to avoid circular imports)
# ---------------------------------------------------------------------------


def register_routes(bp):
    """Register core-checks API routes on the given Flask Blueprint."""
    from uuid import UUID

    from flask import g, jsonify

    from app.core.db import db_session
    from app.core.security.permissions import requires_auth

    @bp.route("/api/core/inventory/expired-materials", methods=["GET"])
    @requires_auth
    def list_expired_materials():
        """List expired raw materials and products made with expired ingredients.

        Uses CoreChecksRunner (expired_materials check) which delegates to DAG traversal
        for impacted items. Returns same shape for sourcemap and flows2.
        """
        org_id = UUID(g.org_id)
        runner = CoreChecksRunner(org_id=org_id, session=db_session())
        result = runner.run_check("expired_materials")
        if result is None or result.data is None:
            return jsonify({"expired_raw_materials": [], "impacted_items": [], "connections": []}), 200
        return jsonify(result.data), 200

    @bp.route("/api/core/inventory/untracked-items", methods=["GET"])
    @requires_auth
    def list_untracked_items():
        """List inventory items flagged as untracked (reconciliation required).

        Uses CoreChecksRunner (untracked_items check). Used by banners, sourcemap
        Check needed, and execution modal dropdown highlighting.
        """
        org_id = UUID(g.org_id)
        runner = CoreChecksRunner(org_id=org_id, session=db_session())
        result = runner.run_check("untracked_items")
        if result is None or result.data is None:
            return jsonify({"untracked_items": [], "connections": []}), 200
        return jsonify(result.data), 200

    @bp.route("/api/core/inventory/output-expiry", methods=["GET"])
    @requires_auth
    def list_output_expiry():
        """List custom output expiry findings (expired or near-expiry outputs).

        Uses CoreChecksRunner (output_expiry check). Used by system findings banner
        and sourcemap highlighting.
        """
        org_id = UUID(g.org_id)
        runner = CoreChecksRunner(org_id=org_id, session=db_session())
        result = runner.run_check("output_expiry")
        if result is None or result.data is None:
            return jsonify({"output_expiry_items": []}), 200
        return jsonify(result.data), 200

    @bp.route("/api/core/inventory/output-ready-date", methods=["GET"])
    @requires_auth
    def list_output_ready_date():
        """List output ready date findings (outputs not yet usable).

        Uses CoreChecksRunner (output_ready_date check). Used by system findings banner
        and sourcemap highlighting.
        """
        from app.core.backend.checks.output_ready_date_check import CHECK_ID as OUTPUT_READY_DATE_CHECK_ID

        org_id = UUID(g.org_id)
        runner = CoreChecksRunner(org_id=org_id, session=db_session())
        result = runner.run_check(OUTPUT_READY_DATE_CHECK_ID)
        if result is None or result.data is None:
            return jsonify({"output_ready_date_items": []}), 200
        return jsonify(result.data), 200

    @bp.route("/api/core/system-findings", methods=["GET"])
    @requires_auth
    def list_system_findings():
        """Run all registered checks and return banner-ready findings (flagged checks with messages).

        Single endpoint for the system-findings banner so the UI always reflects current checks.
        """
        org_id = UUID(g.org_id)
        runner = CoreChecksRunner(org_id=org_id, session=db_session())
        results = runner.run_all_checks()
        findings = []
        for r in results:
            if not r.flagged or not r.message:
                continue
            finding = {"text": r.message, "check_id": r.check_id}
            if r.data is not None:
                finding["data"] = r.data
            findings.append(finding)
        return jsonify({"findings": findings}), 200
