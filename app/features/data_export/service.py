"""GL-P10: one readable export of every record a business holds.

The export is a ZIP streamed to the browser while it is built, so a large organisation
never sits in memory whole:

* ``tables/<table>.csv`` — one CSV per tenant table, rows filtered by ``org_id`` alone;
* ``files/<table>/<column>/<id>`` — binary columns (portal documents) as real files, the CSV
  cell holding the path instead of the bytes;
* ``summary/*.csv`` — plain-language views (stock, batches) with names, not UUIDs;
* ``README.txt`` — what each file is, its columns and what they reference.

Every table carrying an ``org_id`` must be classified here: exported, or excluded with a
reason. Every column whose name looks secret must be dropped or declared safe. The tests
enumerate ``Base.metadata``, so a new table or a new ``*_token`` column fails the build
until someone decides what it is.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import LargeBinary, MetaData, Table, select, text, true
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.core.utils.time import utc_now

# Whole tables left out, with the reason a reader of the README sees.
EXCLUDED_TABLES: dict[str, str] = {
    "api_idempotency_keys": "internal duplicate-request protection, not a business record",
    "contract_portal_sessions": "customer portal sign-in sessions (security internals)",
    "trusted_devices": "remembered-device sign-in tokens (security internals)",
    "two_factor_backup_codes": "two-factor backup codes (secrets)",
    "xero_oauth_tokens": "Xero access tokens (secrets)",
    "user_identities": "Google sign-in links (security internals)",
    "system_findings_cache": "a cache of computed notifications, rebuilt from the other records",
    "admin_org_notes": "Biz-E staff's internal account notes",
    "admin_org_documents": "Biz-E staff's internal account documents",
}

# Tables with no org_id: either the organisation itself (exported, filtered by id) or
# shared/legacy tables that belong to no single business.
ORG_TABLE = "organisations"
NON_TENANT_TABLES: dict[str, str] = {
    "customers": "legacy table with no organisation; holds no business's records",
}

# Columns dropped from an exported table: secrets and duplicate-request internals.
EXCLUDED_COLUMNS: dict[tuple[str, str], str] = {
    ("users", "password_hash"): "secret",
    ("users", "totp_secret"): "secret",
    ("users", "invite_token_hash"): "secret",
    ("contract_portal_invites", "token_hash"): "secret",
    ("contract_portal_principals", "password_hash"): "secret",
    ("contract_material_receipts", "idempotency_key"): "internal",
    ("contract_material_receipts", "request_hash"): "internal",
    ("site_stock_receipts", "idempotency_key"): "internal",
    ("site_stock_receipts", "request_hash"): "internal",
    ("site_stock_transfers", "idempotency_key"): "internal",
    ("site_stock_transfers", "request_hash"): "internal",
    ("tastings", "dispatch_key"): "internal",
    ("tastings", "dispatch_hash"): "internal",
    ("tastings", "finalise_hash"): "internal",
}

# Columns whose names look secret but hold ordinary business data.
SAFE_LOOKING_SECRET: dict[tuple[str, str], str] = {
    ("cost_flows", "source_key"): "which stock write a cost movement came from",
    ("purchase_lines", "line_key"): "which Xero line a purchase line came from",
    ("crm_sales_fifo_allocations", "xero_line_key"): "which Xero invoice line a sale came from",
    ("crm_sales_traceability_config", "matching_key"): "which product field sales are matched on",
    ("feature_subscriptions", "feature_key"): "the name of a plan feature",
    ("planning_workflow_settings", "workflow_fingerprint"): "a hash of the workflow, to notice edits",
    ("xero_credit_note_lines", "line_key"): "which Xero credit-note line this is",
}

SECRET_NAME = re.compile(r"token|secret|hash|password|passwd|key|salt|otp|credential|encrypt|fingerprint", re.I)

# Rows per table before the file is cut short (named in the README). Far above any
# real small manufacturer; it keeps a runaway table from producing an unbounded download.
MAX_ROWS_PER_TABLE = 1_000_000
FETCH_BATCH = 1_000
FILE_BATCH = 4  # portal documents are up to 5 MiB each
FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")


def org_table_names(conn: Connection) -> set[str]:
    """Every table in the live schema with an org_id column.

    Read from the database, not ``Base.metadata``: some models are imported lazily, and a
    table a migration created must not be skipped because no module happened to load it.
    """
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND column_name = 'org_id'"
        )
    )
    return set(rows.scalars())


def tenant_tables(conn: Connection) -> list[Table]:
    """Tables exported for one organisation, reflected from the database, sorted by name."""
    names = sorted((org_table_names(conn) | {ORG_TABLE}) - set(EXCLUDED_TABLES) - set(NON_TENANT_TABLES))
    meta = MetaData()
    meta.reflect(bind=conn, only=names)
    return [meta.tables[name] for name in names]


def exported_columns(table: Table) -> list:
    return [c for c in table.c if (table.name, c.name) not in EXCLUDED_COLUMNS]


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, dict | list):
        return json.dumps(value, default=str, sort_keys=True)
    if hasattr(value, "value"):  # Enum
        value = value.value
    text_value = str(value)
    # Text a spreadsheet would run as a formula (=, +, -, @, tab, CR) is prefixed with an
    # apostrophe so it opens as text. Numbers are never str here, so -3.5 stays a number.
    if isinstance(value, str) and text_value[:1] in FORMULA_LEADS:
        return "'" + text_value
    return text_value


class _Pipe(io.RawIOBase):
    """Write-only stream ZipFile writes into; the generator drains it between chunks."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._pos = 0

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:
        data = bytes(b)
        self._chunks.append(data)
        self._pos += len(data)
        return len(data)

    def tell(self) -> int:  # ZipFile asks for offsets; it never seeks on an unseekable stream
        return self._pos

    def drain(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


@dataclass
class ExportStats:
    rows: dict[str, int] = field(default_factory=dict)
    truncated: list[str] = field(default_factory=list)
    files: int = 0


def _readme(org_name: str, generated_at: datetime, tables: list[Table], stats: ExportStats) -> str:
    lines = [
        f"All records for {org_name}",
        f"Generated {generated_at.isoformat(timespec='seconds')} (UTC) by Biz-E.",
        "",
        "How this export is laid out",
        "  summary/   Plain-language views with names instead of IDs. Start here.",
        "  tables/    One CSV per kind of record: every row this business holds, nothing else.",
        "  files/     Documents stored in the database (customer portal documents).",
        "",
        "Reading the CSVs",
        "  The first row names the columns. Every row has an 'id'; a column ending '_id'",
        "  points at the 'id' of a row in another file, named below. Dates and times are",
        "  ISO 8601 in UTC. Structured details are JSON. An empty cell means no value.",
        "  Text that starts with = + - or @ has an apostrophe in front, so a spreadsheet",
        "  shows it as text instead of running it as a formula.",
        "",
        "Left out on purpose",
        "  Passwords, two-factor secrets, sign-in and Xero tokens, and duplicate-request",
        "  internals are never exported. Whole files left out:",
    ]
    lines += [f"    {name}: {reason}" for name, reason in sorted(EXCLUDED_TABLES.items())]
    lines += [
        "  Uploaded photos and attachments stored outside the database (batch evidence,",
        "  NP3 record files, workflow documents) are listed with name, size and checksum in",
        "  execution_evidence.csv, compliance_record_files.csv and process_step_documents.csv;",
        "  download them from their pages.",
    ]
    if stats.truncated:
        lines += ["", f"Cut short at {MAX_ROWS_PER_TABLE:,} rows (contact support for the rest):"]
        lines += [f"  {name}" for name in stats.truncated]
    lines += ["", "Files"]
    for table in tables:
        lines.append(f"  tables/{table.name}.csv ({stats.rows.get(table.name, 0):,} rows)")
        for col in exported_columns(table):
            refs = sorted({fk.column.table.name for fk in col.foreign_keys})
            note = f" -> {', '.join(refs)}.csv" if refs else ""
            if isinstance(col.type, LargeBinary):
                note = " (path of the file under files/)"
            lines.append(f"      {col.name}{note}")
    return "\n".join(lines) + "\n"


SUMMARIES = {
    "summary/stock.csv": (
        ["Item", "Label", "Quantity", "Unit", "Type", "Site", "Location", "Supplier", "Expires", "Added"],
        """
        SELECT i.name, i.display_label, i.quantity, i.unit, i.inventory_type, s.name, l.name,
               i.supplier, i.expiry_date, i.created_at
          FROM inventory_items i
          LEFT JOIN sites s ON s.id = i.site_id AND s.org_id = i.org_id
          LEFT JOIN stock_locations l ON l.id = i.location_id AND l.org_id = i.org_id
         WHERE i.org_id = :org_id
         ORDER BY i.name, i.created_at
        """,
    ),
    "summary/batches.csv": (
        ["Workflow", "Status", "Site", "Steps", "Started", "Completed"],
        """
        SELECT p.name, e.status, s.name, e.total_steps, e.started_at, e.completed_at
          FROM executions e
          LEFT JOIN processes p ON p.id = e.process_id AND p.org_id = e.org_id
          LEFT JOIN sites s ON s.id = e.site_id AND s.org_id = e.org_id
         WHERE e.org_id = :org_id
         ORDER BY e.started_at DESC NULLS LAST, e.created_at DESC
        """,
    ),
}


def _csv_line(values) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerow(values)
    return buf.getvalue().encode("utf-8")


def stream_export(session: Session, org_id: UUID, org_name: str, stats: ExportStats | None = None) -> Iterator[bytes]:
    """Yield the ZIP for ``org_id`` chunk by chunk. ``stats`` is filled in as it goes."""
    stats = stats if stats is not None else ExportStats()
    generated_at = utc_now()
    tables = tenant_tables(session.connection())
    pipe = _Pipe()
    # Streaming is set per statement: Connection.execution_options() would change the session's
    # shared connection in place and turn later INSERTs into server-side cursors.
    conn = session.connection()
    rows_opts = {"stream_results": True, "yield_per": FETCH_BATCH}

    with zipfile.ZipFile(pipe, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, (headers, sql) in SUMMARIES.items():
            with zf.open(path, "w", force_zip64=True) as out:
                out.write(b"\xef\xbb\xbf" + _csv_line(headers))  # BOM: Excel opens UTF-8 correctly
                for row in conn.execute(text(sql).execution_options(**rows_opts), {"org_id": org_id}):
                    out.write(_csv_line(_cell(v) for v in row))
                    if len(pipe._chunks) > 64:
                        yield pipe.drain()
            yield pipe.drain()

        for table in tables:
            cols = exported_columns(table)
            key = table.c.id if table.name == ORG_TABLE else table.c.org_id
            pk = list(table.primary_key.columns) or cols[:1]
            # Binary columns are never read in the CSV pass: only whether a file is there.
            binary = {c.name for c in cols if isinstance(c.type, LargeBinary)}
            selected = [c.isnot(None).label(c.name) if c.name in binary else c for c in cols]
            query = select(*selected).where(key == org_id).order_by(*pk).limit(MAX_ROWS_PER_TABLE + 1)
            count = 0
            last_id = None  # the last row written, so files never run past a cut-short CSV
            with zf.open(f"tables/{table.name}.csv", "w", force_zip64=True) as out:
                out.write(b"\xef\xbb\xbf" + _csv_line(c.name for c in cols))
                for row in conn.execute(query.execution_options(**rows_opts)):
                    if count == MAX_ROWS_PER_TABLE:
                        stats.truncated.append(table.name)
                        break
                    count += 1
                    last_id = getattr(row, "id", None)
                    values = [
                        (f"files/{table.name}/{column.name}/{row.id}" if value else None)
                        if column.name in binary
                        else value
                        for column, value in zip(cols, row, strict=True)
                    ]
                    out.write(_csv_line(_cell(v) for v in values))
                    if len(pipe._chunks) > 64:
                        yield pipe.drain()
            stats.rows[table.name] = count
            yield pipe.drain()
            # Files follow their CSV (ZipFile writes one member at a time). One query per column,
            # read through a server-side cursor a few rows at a time: memory stays at a handful of
            # files however many there are, and there is no query per file.
            for column in sorted(binary):
                query = (
                    select(table.c.id, table.c[column])
                    .where(key == org_id, table.c[column].isnot(None))
                    .where(table.c.id <= last_id if table.name in stats.truncated else true())
                    .order_by(table.c.id)
                    .limit(MAX_ROWS_PER_TABLE)
                )
                for row in conn.execute(query.execution_options(stream_results=True, yield_per=FILE_BATCH)):
                    zf.writestr(f"files/{table.name}/{column}/{row.id}", bytes(row[1]))
                    stats.files += 1
                    yield pipe.drain()

        zf.writestr("README.txt", _readme(org_name, generated_at, tables, stats))
    yield pipe.drain()
