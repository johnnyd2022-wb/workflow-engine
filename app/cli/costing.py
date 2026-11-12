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


@costing.command(name="enable")
@click.option("--org-id", required=True, help="Organisation ID")
@click.option("--history-from", default=None, help="Also load purchases from Xero back to this date (YYYY-MM-DD)")
def enable_command(org_id, history_from):
    """Switch live cost on for an organisation: the feature, new purchases from today, stock
    history rebuilt, and optionally earlier purchases from Xero. Safe to run again."""
    from datetime import date

    from app.features.costing.enable import enable_costing
    from app.features.costing.service import CostingError

    try:
        wanted = UUID(org_id)
    except ValueError:
        raise click.UsageError("--org-id must be a UUID") from None
    try:
        since = date.fromisoformat(history_from) if history_from else None
    except ValueError:
        raise click.UsageError("--history-from is YYYY-MM-DD") from None
    db = db_session()
    try:
        with unscoped():
            org = db.query(Organisation).filter(Organisation.id == wanted).one_or_none()
        if org is None:
            click.echo(f"❌ No organisation {org_id}", err=True)
            raise SystemExit(1)
        org_name = org.name
        with tenant_scope(wanted):
            result = enable_costing(db, wanted, history_from=since)
    except CostingError as e:
        db.rollback()
        raise click.UsageError(str(e)) from None
    except SystemExit:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        click.echo(f"❌ Enabling costing failed: {type(e).__name__}", err=True)
        raise SystemExit(1) from e
    finally:
        db.close()

    click.echo(f"✅ Live cost is on for {org_name}")
    click.echo(f"   New purchases count from {result['start_date']}")
    click.echo(
        f"   Stock history rebuilt: {result['flows_added']} movements added, {result['inputs_skipped']} inputs skipped"
    )
    history = result["history"]
    if history["status"] == "loaded":
        click.echo(
            f"   Earlier purchases loaded from Xero ({history['from']} to {history['to']}): {history['documents']} purchases"
        )
    elif history["status"] != "not_requested":
        click.echo(f"⚠️  Earlier purchases not loaded: {history['message']}")
    click.echo(f"   Products with a full cost: {result['products_ready']} of {result['products']}")
    for p in result["not_ready"][:10]:
        click.echo(f"     - {p['name']}: {p['costed']} of {p['of']} materials costed")
    click.echo(
        f"   Purchases to record: {result['purchases_to_record']} new, {result['earlier_purchases_to_record']} earlier"
    )
    if history["status"] in ("needs_reconnect", "failed"):
        raise SystemExit(2)
