"""``workflow costing ...`` (live-cogs 8.1a)."""

from uuid import UUID

import click

from app.core.db import db_session
from app.core.db.models.organisation import Organisation
from app.core.security.tenant_scope import tenant_scope, unscoped


@click.group(name="costing")
def costing():
    """Live cost engine maintenance."""


@costing.command(name="backfill-flows")
@click.option("--org-id", default=None, help="Organisation ID")
@click.option("--all", "all_orgs", is_flag=True, help="Every organisation")
def backfill_flows_command(org_id, all_orgs):
    """Reconstruct stock-flow history for lots made before the cost engine. Idempotent."""
    from app.features.costing.backfill import backfill_flows

    if bool(org_id) == bool(all_orgs):
        raise click.UsageError("Give exactly one of --org-id or --all")
    db = db_session()
    try:
        with unscoped():
            if all_orgs:
                org_ids = [row[0] for row in db.query(Organisation.id).all()]
            else:
                try:
                    wanted = UUID(org_id)
                except ValueError:
                    raise click.UsageError("--org-id must be a UUID") from None
                if db.query(Organisation.id).filter(Organisation.id == wanted).first() is None:
                    click.echo(f"❌ No organisation {org_id}", err=True)
                    raise SystemExit(1)
                org_ids = [wanted]
        for oid in org_ids:
            with tenant_scope(oid):
                result = backfill_flows(db, oid)
                db.commit()
            click.echo(f"{oid}: {result['inserted']} flows added, {result['skipped_inputs']} inputs skipped")
    except (SystemExit, click.UsageError):
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        click.echo(f"❌ Backfill failed: {e}", err=True)
        raise SystemExit(1) from e
    finally:
        db.close()
