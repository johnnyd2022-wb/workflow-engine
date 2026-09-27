"""Maintenance CLI commands intended to run on a schedule (cron / systemd timer)."""

import click

from app.core.db import db_session
from app.core.security.tenant_scope import unscoped


@click.command(name="warm-system-findings")
def warm_system_findings() -> None:
    """Recompute nightly system findings for active orgs.

    The `expired_materials` check rolls over at Pacific/Auckland midnight; the first
    /core load after that pays the ~1s DAG traversal. Run this just after NZ midnight so
    a real user never does. This also audits stock arithmetic and unmatched sales
    for every active live tenant; a quiet tenant must not lose its nightly check.

    Cron (server local time = Pacific/Auckland):
        5 0 * * *  cd /app && uv run workflow warm-system-findings >> /var/log/warm.log 2>&1
    """
    from sqlalchemy.orm import configure_mappers

    # No create_app() here, so import the model modules whose mappers the checks touch
    # (models/__init__.py doesn't pull these two in; the web app gets them via backend.py).
    from app.core.db.models import inventory_movement as _im  # noqa: F401
    from app.core.db.models import inventory_wastage as _iw  # noqa: F401
    from app.core.db.models.organisation import Organisation, OrganisationStatus
    from app.features.compliance_checks.system_findings_cache import prewarm

    configure_mappers()
    db = db_session()
    warmed = failed = skipped = 0
    try:
        with unscoped():
            org_ids = [
                row[0]
                for row in db.query(Organisation.id).filter(Organisation.status == OrganisationStatus.ACTIVE).all()
            ]
            click.echo(f"warming system-findings cache for {len(org_ids)} active org(s)...")
            for org_id in org_ids:
                try:
                    result = prewarm(org_id, db)
                    if result is True:
                        warmed += 1
                    elif result is False:
                        failed += 1
                    else:
                        skipped += 1
                except Exception as exc:  # noqa: BLE001 -- one bad org must not stop the batch
                    db.rollback()
                    failed += 1
                    click.echo(f"  ! {org_id}: {exc}", err=True)
        click.echo(f"warmed {warmed}, failed {failed}, already running {skipped}")
        if failed:
            raise click.ClickException(f"Nightly system checks failed for {failed} organisation(s)")
    finally:
        db.close()
