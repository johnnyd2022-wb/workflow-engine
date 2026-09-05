"""Consistent, tenant-scoped case exports. Requires trusted operator shell access."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import click
from sqlalchemy import select, text

from app.core.db import engine
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.organisation import Organisation
from app.features.operational_cases.models.operational_case import OperationalCase
from app.features.operational_cases.models.operational_case_event import OperationalCaseEvent
from app.features.operational_cases.models.operational_case_link import OperationalCaseLink

_TABLES = (OperationalCase, OperationalCaseLink, OperationalCaseEvent, EntityEvent)


def _query(model, org_id):
    q = select(model.__table__).where(model.org_id == org_id)
    if model is EntityEvent:
        q = q.where(model.entity_type == "operational_case")
    return q


def export_cases(org_id: UUID, out_dir: Path) -> dict:
    """Write an exclusive export directory from one read-only repeatable snapshot."""
    out_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "org_id": str(org_id),
        "exported_at": datetime.now(UTC).isoformat(),
        "dependencies": "Restore into a database retaining this tenant, users and source records. Domain case events are included.",
        "files": {},
    }
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            if conn.execute(select(Organisation.id).where(Organisation.id == org_id)).first() is None:
                raise ValueError("organisation not found")
            for model in _TABLES:
                name = model.__tablename__
                checksum = hashlib.sha256()
                count = 0
                with (out_dir / (name + ".jsonl")).open("xb") as f:
                    rows = conn.execution_options(stream_results=True).execute(_query(model, org_id).order_by(model.id))
                    for batch in rows.mappings().partitions(500):
                        for row in batch:
                            encoded = (
                                json.dumps(dict(row), default=str, sort_keys=True, ensure_ascii=False) + "\n"
                            ).encode("utf-8")
                            f.write(encoded)
                            checksum.update(encoded)
                            count += 1
                manifest["files"][name] = {"path": name + ".jsonl", "row_count": count, "sha256": checksum.hexdigest()}
    with (out_dir / "manifest.json").open("x", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


@click.command(name="export")
@click.option("--org-id", required=True, type=click.UUID)
@click.option("--out-dir", required=True, type=click.Path(path_type=Path))
def export_operational_cases(org_id, out_dir):
    """Export one tenant to a NEW private directory; existing exports are never overwritten."""
    try:
        manifest = export_cases(org_id, out_dir)
    except Exception as exc:
        raise click.ClickException(f"Export failed; partial directory must not be used: {type(exc).__name__}") from exc
    click.echo(
        f"Exported {sum(f['row_count'] for f in manifest['files'].values())} rows; manifest: {out_dir / 'manifest.json'}"
    )


def rehearse_restore(directory: Path):
    """Restore exported IDs within a rolled-back transaction on an explicitly disposable DB."""
    from app.utils.config_loader import config

    if (
        config.environment != "local"
        or config.db_host not in {"localhost", "127.0.0.1"}
        or not config.db_name.startswith("oc_verify_")
    ):
        raise ValueError("restore rehearsal requires a local oc_verify_ disposable database")
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported export schema")
    org_id = UUID(manifest["org_id"])
    # Validate all bytes before performing any writes.
    for model in _TABLES:
        info = manifest["files"][model.__tablename__]
        path = directory / (model.__tablename__ + ".jsonl")
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as f:
            for line in f:
                digest.update(line)
                if UUID(json.loads(line)["org_id"]) != org_id:
                    raise ValueError("foreign tenant in export")
                count += 1
        if digest.hexdigest() != info["sha256"] or count != info["row_count"]:
            raise ValueError("export checksum/count mismatch")
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            for model in (OperationalCaseEvent, OperationalCaseLink, OperationalCase, EntityEvent):
                q = model.__table__.delete().where(model.org_id == org_id)
                if model is EntityEvent:
                    q = q.where(model.entity_type == "operational_case")
                conn.execute(q)
            for model in (EntityEvent, OperationalCase, OperationalCaseLink, OperationalCaseEvent):
                table = model.__table__
                with (directory / (model.__tablename__ + ".jsonl")).open() as f:
                    for line in f:
                        row = json.loads(line)
                        for column in table.columns:
                            value = row.get(column.name)
                            if value is None:
                                continue
                            if column.type.python_type is UUID:
                                row[column.name] = UUID(value)
                            elif column.type.python_type is datetime:
                                row[column.name] = datetime.fromisoformat(value)
                        if model is OperationalCase:
                            row["previous_case_id"] = None
                        conn.execute(table.insert().values(**row))
            with (directory / "operational_cases.jsonl").open() as f:
                for line in f:
                    row = json.loads(line)
                    if row["previous_case_id"]:
                        conn.execute(
                            OperationalCase.__table__.update()
                            .where(OperationalCase.org_id == org_id, OperationalCase.id == UUID(row["id"]))
                            .values(previous_case_id=UUID(row["previous_case_id"]))
                        )
            # Compare actual restored rows with the full original export, including UUIDs and history.
            for model in _TABLES:
                checksum = hashlib.sha256()
                count = 0
                for row in conn.execute(_query(model, org_id).order_by(model.id)).mappings():
                    checksum.update(
                        (json.dumps(dict(row), default=str, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
                    )
                    count += 1
                info = manifest["files"][model.__tablename__]
                if count != info["row_count"] or checksum.hexdigest() != info["sha256"]:
                    raise ValueError("restored data differs from export")
        finally:
            transaction.rollback()
    return True


@click.command(name="rehearse")
@click.option("--export-dir", required=True, type=click.Path(exists=True, path_type=Path))
def rehearse_operational_cases(export_dir):
    """Rehearse restoration on local oc_verify_* only; all database writes are rolled back."""
    try:
        rehearse_restore(export_dir)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Restore rehearsal passed; database restored to pre-rehearsal state by rollback.")
