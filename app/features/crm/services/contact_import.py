"""Preview and import local CRM contacts from a fixed CSV/TSV schema."""

import csv
from io import StringIO
from uuid import UUID

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.features.crm.models.crm_note import CRMNote
from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.services.contact_service import _clean_addresses, _clean_fields

HEADERS = (
    "name",
    "first_name",
    "last_name",
    "email_address",
    "phone_number",
    "address_line1",
    "address_line2",
    "address_city",
    "address_region",
    "address_postal_code",
    "address_country",
    "note",
)
ADDRESS_COLUMNS = {
    "address_line1": "line1",
    "address_line2": "line2",
    "address_city": "city",
    "address_region": "region",
    "address_postal_code": "postal_code",
    "address_country": "country",
}
MAX_BYTES = 1_000_000
MAX_ROWS = 500
MAX_NOTE = 10_000


def template() -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(HEADERS)
    return output.getvalue()


def _rows(db: Session, org_id: UUID, text: str, fmt: str):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Import text must be UTF-8 and at most 1 MB")
    if fmt not in {"csv", "tsv"}:
        raise ValueError("Choose CSV or spreadsheet paste")
    try:
        reader = csv.reader(
            StringIO(text.lstrip("\ufeff"), newline=""), delimiter="\t" if fmt == "tsv" else ",", strict=True
        )
        headers = next(reader, None)
        if not headers:
            raise ValueError("Add the template header row and at least one customer")
        headers = [column.strip() for column in headers]
        if len(headers) != len(set(headers)) or "name" not in headers or set(headers) - set(HEADERS):
            raise ValueError("Headers must include name, have no duplicates and use only template columns")
        existing = {
            name.strip().casefold() for (name,) in db.query(XeroContact.name).filter(XeroContact.org_id == org_id).all()
        }
        seen = set()
        ready = []
        problems = []
        count = 0
        for values in reader:
            if not any(value.strip() for value in values):
                continue
            count += 1
            if count > MAX_ROWS:
                raise ValueError(f"Import at most {MAX_ROWS} customers at a time")
            line = reader.line_num
            row = dict(zip(headers, values, strict=False))
            name = row.get("name", "").strip()
            try:
                if len(values) != len(headers):
                    raise ValueError("Column count does not match the header")
                fields = _clean_fields(
                    {
                        key: row[key]
                        for key in row
                        if key in {"name", "first_name", "last_name", "email_address", "phone_number"}
                    },
                    require_name=True,
                )
                key = name.casefold()
                if key in existing or key in seen:
                    raise ValueError("A customer with this name already exists")
                address = {part: row[column] for column, part in ADDRESS_COLUMNS.items() if row.get(column, "").strip()}
                if address:
                    fields["addresses"] = _clean_addresses([{"type": "POBOX", **address}], None)
                note = row.get("note", "").strip()
                if len(note) > MAX_NOTE:
                    raise ValueError(f"Note must be at most {MAX_NOTE} characters")
                ready.append((line, fields, note))
                seen.add(key)
            except ValueError as exc:
                problems.append({"row": line, "name": name, "error": str(exc), "data": row})
        if count == 0:
            raise ValueError("Add at least one customer below the header")
        return headers, ready, problems
    except csv.Error as exc:
        raise ValueError(f"Invalid {fmt.upper()} data: {exc}") from exc


def import_contacts(db: Session, org_id: UUID, text: str, fmt: str, *, commit: bool, actor_id: UUID | None):
    """Preview without writing, or revalidate and commit only valid rows atomically."""
    if commit:
        # Two simultaneous imports for this org must not both pass the same name check.
        db.execute(
            sql_text("SELECT pg_advisory_xact_lock(hashtext('crm-contact-import'), hashtext(:org_id))"),
            {"org_id": str(org_id)},
        )
    headers, ready, problems = _rows(db, org_id, text, fmt)
    created = 0
    if commit and ready:
        writer = EventWriter(db, org_id)
        for _, fields, note_text in ready:
            contact = XeroContact(
                org_id=org_id, source="bize", sync_to_xero=False, is_customer=True, is_supplier=False, **fields
            )
            db.add(contact)
            db.flush()
            writer.emit(
                event_type="crm_contact.imported",
                entity_type="crm_contact",
                entity_id=contact.id,
                payload={"name": contact.name, "source": fmt},
                diff=None,
                actor_id=actor_id,
            )
            if note_text:
                note = CRMNote(org_id=org_id, contact_id=contact.id, content=note_text, created_by_user_id=actor_id)
                db.add(note)
                db.flush()
                writer.emit(
                    event_type="crm_note.imported",
                    entity_type="crm_note",
                    entity_id=note.id,
                    payload={"contact_id": str(contact.id)},
                    diff=None,
                    actor_id=actor_id,
                )
            created += 1
        db.commit()
    return {
        "ready": len(ready),
        "created": created,
        "rejected": len(problems),
        "problems": problems,
        "headers": headers,
        "preview": [{"row": line, "name": fields["name"], "has_note": bool(note)} for line, fields, note in ready],
    }
