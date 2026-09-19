"""One command: rebuild whistlebird_test from version control through the real API.

Runs the documented API-replay path end to end (docs/whistlebird-replay-plan.md):

    ensure tenant -> sync admin password -> scoped reset -> workflows -> Compliant setup
    -> replay (Core history, then CRM mappings, then NP3 evidence) -> timestamp pass -> verification

Requires the app running (`uv run workflow start`). Without --confirm-reset-whistlebird-test
it is a read-only preflight and prints what it would do.

Before anything destructive it (1) validates the NP3 manifest and (2) refuses to continue
if the database holds NP3 evidence, staff or profile settings the manifest does not --
i.e. evidence typed into the app since the last
`scripts/whistlebird_np3.py snapshot`. The reset deletes `compliance_records`; that
evidence would be gone. Override with --discard-unsnapshotted-np3 only when that is the
intent.

    uv run python scripts/whistlebird_rebuild_api.py --base-url https://localhost:8005 --insecure \\
        --target-url postgresql://workflow_rw:...@localhost:8401/workflow-engine-test \\
        --confirm-reset-whistlebird-test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
import urllib3
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).parent))
import whistlebird_legacy as legacy  # noqa: E402
import whistlebird_migration as wm  # noqa: E402
import whistlebird_np3 as np3  # noqa: E402
import whistlebird_replay as replay  # noqa: E402
import whistlebird_replay_correct_timestamps as correct  # noqa: E402

STEPS = (
    "ensure tenant and admin",
    "sync admin password",
    "scoped reset",
    "product workflows",
    "Compliant NZ-alcohol setup",
    "replay Core history, then CRM mappings, then NP3 evidence",
    "timestamp pass",
    "verify (Core counts, dates, wording, NP3)",
)


class RebuildRefusedError(RuntimeError):
    """A precondition failed; nothing destructive has run."""


def server_reachable(base_url: str, verify_tls: bool) -> str | None:
    """None when the app answers, else the reason it does not."""
    if not verify_tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        requests.get(f"{base_url.rstrip('/')}/auth/login", timeout=10, verify=verify_tls)
    except requests.RequestException as exc:
        return f"app not reachable at {base_url} ({type(exc).__name__}); start it with `uv run workflow start`"
    return None


def preflight(args: argparse.Namespace) -> list[str]:
    """Read-only. Every reason the rebuild must not start; empty means safe to go."""
    try:
        manifest = np3.load_np3_manifest(args.np3_manifest)
    except np3.Np3ManifestError as exc:
        return [f"NP3 manifest invalid: {exc}"]
    problems: list[str] = []
    try:
        with legacy.open_legacy(args.legacy_source):
            pass
    except (legacy.LegacySnapshotError, OSError, SQLAlchemyError) as exc:
        # Found here, before the reset: a legacy source that fails later would leave a wiped tenant.
        problems.append(f"legacy source unusable ({args.legacy_source}): {type(exc).__name__}: {exc}")
    if not args.discard_unsnapshotted_np3:
        unsnapshotted = np3.np3_unsnapshotted(args.target_url, args.org_name, manifest)
        if unsnapshotted:
            problems.append(
                "the reset would delete NP3 evidence the manifest does not hold "
                "(run `scripts/whistlebird_np3.py snapshot`, commit it, then retry):\n    "
                + "\n    ".join(unsnapshotted)
            )
    unreachable = server_reachable(args.base_url, not args.insecure)
    if unreachable:
        problems.append(unreachable)
    return problems


def rebuild(args: argparse.Namespace) -> dict[str, Any]:
    problems = preflight(args)
    if problems:
        raise RebuildRefusedError("\n  ".join(["refusing to rebuild:", *problems]))
    if not args.confirm_reset_whistlebird_test:
        return {"dry_run": True, "would_run": list(STEPS), "preflight": "ok"}

    report: dict[str, Any] = {}
    report["tenant"] = wm.ensure_target_org_admin(args.target_url, args.org_name, args.admin_email, args.admin_password)
    report["password_sync"] = wm.sync_whistlebird_test_admin_password(args.target_url, args.org_name, args.admin_email)
    report["reset"] = wm.reset_target_org(args.target_url, args.org_name)
    report["workflows"] = wm.setup_product_workflows(args.target_url, args.org_name)
    report["compliant_setup"] = wm.ensure_compliant_nz_alcohol_setup(args.target_url, args.org_name)
    report["replay"] = replay.run_replay(
        args.base_url,
        args.legacy_source,
        args.target_url,
        args.production_manifest,
        args.admin_email,
        args.admin_password,
        args.org_name,
        verify_tls=not args.insecure,
        np3_manifest_path=args.np3_manifest,
    )
    report["timestamps"] = correct.correct_timestamps(
        args.legacy_source, args.target_url, args.org_name, np3_manifest_path=args.np3_manifest
    )
    report["verification"] = wm.build_import_verification(
        args.legacy_source,
        args.target_url,
        args.org_name,
        args.production_manifest,
        np3_manifest_path=args.np3_manifest,
    )
    wm._require_matching_import(report["verification"], "API rebuild")
    return report


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="https://localhost:8005")
    parser.add_argument("--insecure", action="store_true", help="Skip TLS verification (self-signed local certs).")
    parser.add_argument(
        "--legacy-url",
        "--legacy-source",
        dest="legacy_source",
        default=legacy.DEFAULT_LEGACY_SNAPSHOT,
        help="Where the prior inventory data comes from: a path to a snapshot JSON (default: the committed "
        "docs/whistlebird-legacy-source.json) or a postgresql:// URL to read the live legacy database.",
    )
    parser.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    parser.add_argument("--production-manifest", type=Path, default=wm.DEFAULT_PRODUCTION_MANIFEST)
    parser.add_argument("--np3-manifest", type=Path, default=np3.DEFAULT_NP3_MANIFEST)
    parser.add_argument("--admin-email", default=wm.DEFAULT_TEST_ADMIN_EMAIL)
    parser.add_argument("--admin-password-env", default="WHISTLEBIRD_TEST_ADMIN_PASSWORD")
    parser.add_argument("--org-name", default=wm.RESET_ORG_NAME)
    parser.add_argument(
        "--confirm-reset-whistlebird-test",
        action="store_true",
        help="Actually reset and rebuild. Without it, only the read-only preflight runs.",
    )
    parser.add_argument(
        "--discard-unsnapshotted-np3",
        action="store_true",
        help="Proceed even though the database holds NP3 evidence the manifest lacks (it will be lost).",
    )
    args = parser.parse_args(argv)
    if not args.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    if args.org_name != wm.RESET_ORG_NAME:
        parser.error(f"--org-name must be exactly {wm.RESET_ORG_NAME!r}")
    args.admin_password = os.environ.get(args.admin_password_env)
    if not args.admin_password and args.confirm_reset_whistlebird_test:
        try:
            args.admin_password = wm._keepass_password(wm.WHISTLEBIRD_TEST_ADMIN_KEEPASS_ENTRY)
        except ValueError as exc:
            parser.error(f"{args.admin_password_env} is not set and KeePassXC fallback failed: {exc}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        report = rebuild(args)
    except RebuildRefusedError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
