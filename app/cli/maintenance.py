"""Maintenance CLI commands intended to run on a schedule (cron / systemd timer)."""

from datetime import UTC, datetime, timedelta

import click

from app.core.db import db_session
from app.core.security.tenant_scope import unscoped


@click.command(name="warm-system-findings")
@click.option(
    "--since-days",
    default=7,
    show_default=True,
    type=int,
    help="Only warm orgs that emitted an entity_event within this many days.",
)
def warm_system_findings(since_days: int) -> None:
    """Recompute the cached (DAG-heavy) system-findings slice for recently-active orgs.

    The `expired_materials` check rolls over at Pacific/Auckland midnight; the first
    /core load after that pays the ~1s DAG traversal. Run this just after NZ midnight so
    a real user never does.

    Cron (server local time = Pacific/Auckland):
        5 0 * * *  cd /app && uv run workflow warm-system-findings >> /var/log/warm.log 2>&1
    """
    from sqlalchemy import text
    from sqlalchemy.orm import configure_mappers

    # No create_app() here, so import the model modules whose mappers the checks touch
    # (models/__init__.py doesn't pull these two in; the web app gets them via backend.py).
    from app.core.db.models import inventory_movement as _im  # noqa: F401
    from app.core.db.models import inventory_wastage as _iw  # noqa: F401
    from app.features.compliance_checks.system_findings_cache import prewarm

    configure_mappers()
    db = db_session()
    cutoff = datetime.now(UTC) - timedelta(days=max(0, since_days))
    warmed = failed = 0
    try:
        with unscoped():
            org_ids = [
                row[0]
                for row in db.execute(
                    text("SELECT DISTINCT org_id FROM entity_events WHERE created_at >= :cutoff"),
                    {"cutoff": cutoff},
                ).fetchall()
            ]
            click.echo(f"warming system-findings cache for {len(org_ids)} active org(s)...")
            for org_id in org_ids:
                try:
                    prewarm(org_id, db)
                    warmed += 1
                except Exception as exc:  # noqa: BLE001 -- one bad org must not stop the batch
                    failed += 1
                    click.echo(f"  ! {org_id}: {exc}", err=True)
        click.echo(f"✅ warmed {warmed}, failed {failed}")
    finally:
        db.close()
