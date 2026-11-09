#!/usr/bin/env python3
"""The minimum risk tier a change can take (lean workflow, .agents/verification-tiers.md).

An agent picks the tier before building and may always go *higher*; this script sets the
floor it can't go below. It is deterministic on purpose: "it felt small" is exactly how a
one-line missing org_id filter ships, so the paths and the added lines decide.

    python3 scripts/risk_tier.py --base origin/main          # the working tree vs base
    python3 scripts/risk_tier.py --paths a.py b.css           # just these paths
    python3 scripts/risk_tier.py --base origin/main --json

Tiers: A mechanical (docs, copy, styling) · B ordinary behaviour · C high risk. An unknown
blast radius (a path that matches nothing) is B, never A.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Tier C: auth, tenancy, inventory quantities and lineage, money and compliance maths,
# migrations, public ingest, security and production config. Order is for the reason text.
TIER_C_PATHS: tuple[tuple[str, str], ...] = (
    ("app/core/db/migrations/*", "schema or data migration"),
    ("app/core/security/*", "auth, roles or access policy"),
    ("app/api/routes/auth_routes.py", "sign-in and 2FA"),
    ("app/core/db/models/tenant_mixin.py", "tenant scoping"),
    ("app/core/db/tenant*", "tenant scoping"),
    ("app/core/domain/inventory_quantity_guard.py", "inventory quantity guard"),
    ("app/core/db/repositories/inventory_repo.py", "inventory quantities"),
    ("app/core/db/repositories/execution_repo.py", "production records and lineage"),
    ("app/core/backend/execution_routes.py", "step completion and its constraints"),
    ("app/core/backend/dagtraversal.py", "lineage and trace"),
    ("app/core/utils/unit_conversion.py", "unit conversion"),
    ("app/core/services/lot_holds.py", "quality holds"),
    ("app/features/recalls/*", "recalls"),
    ("app/features/crm/services/sales_fifo*", "sales allocation to batches"),
    ("app/features/crm/services/*invoice*", "invoicing"),
    ("app/features/crm/services/*xero*", "Xero sync"),
    ("app/features/crm/services/sales_returns.py", "returns and credits"),
    ("app/features/compliant/modules/nz_alcohol/excise*", "excise duty"),
    ("app/features/compliant/modules/nz_alcohol/sales_excise.py", "excise duty"),
    ("app/features/compliant/modules/nz_alcohol/movement_excise.py", "excise duty"),
    ("app/features/compliant/modules/nz_alcohol/wine/*", "wine compliance (claims, export register)"),
    ("app/features/compliant/platform/workflow_rules.py", "production compliance constraints"),
    ("app/features/planning/start_service.py", "batch start and material claims"),
    ("app/features/planning/material_adapter.py", "material commitments"),
    ("app/features/data_export/*", "bulk data export"),
    ("app/features/contract_manufacturing/services/portal*", "customer portal (another tenant's view)"),
    ("app/observability/*telemetry*", "public telemetry ingest"),
    ("app/config/*.ini", "environment configuration"),
    (".gitlab-ci.yml", "CI and deploy pipeline"),
    ("ci/*", "CI and deploy scripts"),
    ("terraform/*", "infrastructure"),
    ("Dockerfile*", "production image"),
    ("docker-compose*.yml", "service configuration"),
    ("pyproject.toml", "dependencies"),
    ("uv.lock", "dependencies"),
)

# Lines that make any file Tier C: the tenant filter, quantity writes, row locks, raw SQL.
TIER_C_LINES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\borg_id\b"), "touches org_id scoping"),
    (re.compile(r"allow_inventory_quantity_write|\.quantity\s*=(?!=)"), "writes an inventory quantity"),
    (re.compile(r"with_for_update|pg_advisory"), "changes locking"),
    (re.compile(r"\btext\(\s*f?[\"']|execute\(\s*f?[\"']"), "raw SQL"),
    (re.compile(r"requires_auth|requires_org_scope|has_permission|csrf", re.I), "auth or CSRF"),
    (re.compile(r"\bDecimal\(|is_finite\("), "numeric correctness"),
)

# Tier A: nothing that runs. Anything else, including an unknown path, is at least B.
TIER_A_PATHS: tuple[str, ...] = (
    "*.md",
    "docs/*",
    ".agents/reports/*",
    ".agents/plans/*",
    ".agents/research/*",
    "*.css",
    "*.png",
    "*.jpg",
    "*.svg",
    "*.txt",
)


def _match(path: str, pattern: str) -> bool:
    return fnmatch(path, pattern) or fnmatch(path, pattern.rstrip("*") + "**")


def classify(paths: list[str], added_lines: dict[str, list[str]] | None = None) -> dict:
    """{"tier": "A"|"B"|"C", "reasons": [...]} for these changed paths and their added lines."""
    added_lines = added_lines or {}
    reasons: list[str] = []
    tier = "A"
    for path in paths:
        hit = next((why for pattern, why in TIER_C_PATHS if _match(path, pattern)), None)
        if hit:
            reasons.append(f"{path}: {hit}")
            tier = "C"
            continue
        is_code = not any(_match(path, pattern) for pattern in TIER_A_PATHS)
        if path.startswith("tests/"):
            # Tests can't break the product, but a weakened assertion can hide a break: B.
            is_code = True
        if is_code:
            for line in added_lines.get(path, []):
                why = next((why for rx, why in TIER_C_LINES if rx.search(line)), None)
                # Line rules are about application code: a script or test that *mentions*
                # org_id isn't changing tenant scoping.
                if why and path.startswith("app/"):
                    reasons.append(f"{path}: {why}")
                    tier = "C"
                    break
            else:
                if tier == "A":
                    tier = "B"
                if not any(r.startswith(path + ":") for r in reasons):
                    reasons.append(f"{path}: behaviour change")
    if not paths:
        reasons.append("no changes")
    return {"tier": tier, "reasons": list(dict.fromkeys(reasons))}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout


def changes_against(base: str) -> tuple[list[str], dict[str, list[str]]]:
    """Changed paths (committed, staged, unstaged and untracked) and each one's added lines."""
    merge_base = _git("merge-base", base, "HEAD").strip()
    paths = [p for p in _git("diff", "--name-only", merge_base).splitlines() if p]
    paths += [p for p in _git("ls-files", "--others", "--exclude-standard").splitlines() if p]
    paths = list(dict.fromkeys(paths))
    added: dict[str, list[str]] = {}
    current = None
    for line in _git("diff", "--unified=0", merge_base).splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and current:
            added.setdefault(current, []).append(line[1:])
    for path in paths:
        if path not in added and (REPO / path).is_file():
            try:
                added[path] = (REPO / path).read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                added[path] = []
    return paths, added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--paths", nargs="*", help="classify these paths instead of the diff (no line checks)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.paths is not None:
        result = classify(args.paths)
    else:
        result = classify(*changes_against(args.base))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Tier {result['tier']} (minimum)")
        for reason in result["reasons"][:20]:
            print(f"  - {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
