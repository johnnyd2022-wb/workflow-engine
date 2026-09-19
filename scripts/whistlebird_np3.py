"""Replayable NP3 food-control evidence for whistlebird_test.

The NP3 evidence a business enters in the Compliant workspace (attestations, control
logs, review intervals, the NP3 profile settings, the staff the training/illness logs
refer to) lives only in the database. This module makes it reproducible from version
control, the same two-pass way the Core history is:

1. **Replay** (`replay_np3`, called by `scripts/whistlebird_replay.py` after every Core
   event) issues each record through the real API -- the same routes and validation the
   browser hits. Nothing here can backdate a record; the routes stamp "now".
2. **Timestamp pass** (`correct_np3_timestamps`, called by
   `scripts/whistlebird_replay_correct_timestamps.py`) sets the dates the manifest
   declares (`signed_on`, `due_date`, a log's `event_date`) directly on the rows. Internal
   tooling for a demo/test tenant only -- the live app exposes no such capability.

Source of truth: `docs/whistlebird-np3-evidence-source.json`. Get evidence into it with

    uv run python scripts/whistlebird_np3.py snapshot --target-url ...

which reads the org's NP3 rows out of the database. Snapshot **before** any reset: the
scoped reset deletes `compliance_records`, and `scripts/whistlebird_rebuild_api.py`
refuses to reset while the database holds NP3 evidence the manifest does not.

Scope: text and selection evidence only. A record that links Core entities
(`source_refs`) or an uploaded evidence file cannot be replayed (their IDs are
regenerated on every reset), so the snapshot refuses them rather than silently dropping
them. UUIDs are not preserved anywhere: a log's employee is keyed by email and re-linked
to the newly created user.

Idempotency: the NP3 routes build `details` server-side and reject unknown fields, so a
row cannot carry an `import_ref` marker like a customs lodgement does. Identity is
instead a content fingerprint (control + the text the user entered), computed the same
way from a manifest entry and from a database row. Two identical entries in one manifest
are rejected for that reason.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent))
import whistlebird_migration as wm  # noqa: E402

DEFAULT_NP3_MANIFEST = Path(__file__).parents[1] / "docs" / "whistlebird-np3-evidence-source.json"
NP3_FRAMEWORK = "np3-food-control"
REVIEW_INTERVALS = (1, 3, 6, 12)
STAFF_ROLES = ("member", "admin")
_MANIFEST_KEYS = {"profile", "staff", "annual_training", "attestations", "logs"}
_PROFILE_KEYS = {"council_name", "trade_waste_consent_reference", "settings"}
_ANNUAL_TRAINING_KEYS = {"dates", "topics"}
_ANNUAL_TRAINING_TOPIC_KEYS = {"title", "np3_controls"}
_ATTESTATION_KEYS = {
    "control_id",
    "signed_on",
    "due_date",
    "review_interval_months",
    "how_we_meet",
    "evidence_reference",
    "evidence_fields",
}
_LOCAL_TZ = ZoneInfo("Pacific/Auckland")


class Np3ManifestError(ValueError):
    """The NP3 manifest is malformed, or asks for something the routes would reject."""


class Np3SnapshotError(RuntimeError):
    """The database holds NP3 evidence that cannot be represented in the manifest."""


def _add_months(value: date, months: int) -> date:
    """Calendar-cadence month arithmetic; identical to the attestation route's helper
    (`app/features/compliant/routes/api_routes.py`, asserted equal in the tests)."""
    month_index = value.month - 1 + months
    year, month = value.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


# --------------------------------------------------------------------------------------
# Manifest model
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Np3Attestation:
    control_id: str
    signed_on: date
    due_date: date
    review_interval_months: int
    how_we_meet: str
    evidence_reference: str
    evidence_fields: dict[str, str]

    @property
    def fingerprint(self) -> str:
        return attestation_fingerprint(
            self.control_id,
            self.how_we_meet,
            self.review_interval_months,
            self.evidence_reference,
            self.evidence_fields,
        )


@dataclass(frozen=True)
class Np3Log:
    control_id: str
    # Field values keyed as in the log template, except a "user" field (`employee_user_id`)
    # which is keyed `employee_email` and holds the person's email.
    fields: dict[str, str]

    @property
    def event_date(self) -> date:
        return date.fromisoformat(self.fields["event_date"])

    @property
    def fingerprint(self) -> str:
        return log_fingerprint(self.control_id, self.fields)


@dataclass(frozen=True)
class Np3Staff:
    email: str
    role: str = "member"
    name: str = ""


@dataclass(frozen=True)
class Np3Manifest:
    profile: dict[str, Any] | None = None
    staff: tuple[Np3Staff, ...] = ()
    attestations: tuple[Np3Attestation, ...] = ()
    logs: tuple[Np3Log, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def record_count(self) -> int:
        return len(self.attestations) + len(self.logs)


def _clean(mapping: dict[str, Any] | None) -> dict[str, str]:
    """Drop blank values and trim, as the log route does before storing."""
    return {key: value.strip() for key, value in (mapping or {}).items() if isinstance(value, str) and value.strip()}


def _digest(parts: list[Any]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def attestation_fingerprint(
    control_id: str,
    how_we_meet: str,
    review_interval_months: int,
    evidence_reference: str | None,
    evidence_fields: dict[str, Any] | None,
) -> str:
    return _digest(
        [
            "attestation",
            control_id,
            how_we_meet.strip(),
            int(review_interval_months),
            (evidence_reference or "").strip(),
            _clean(evidence_fields),
        ]
    )


def log_fingerprint(control_id: str, fields: dict[str, Any]) -> str:
    return _digest(["log", control_id, _clean(fields)])


def _user_field_keys(control_id: str) -> dict[str, str]:
    """{template field key: manifest key} for the log template's "user"-type fields."""
    from app.features.compliant.modules.nz_alcohol.np3_audit import np3_log_template

    template = np3_log_template(control_id) or {}
    return {
        item["key"]: item["key"].removesuffix("_user_id") + "_email"
        for item in template.get("fields", ())
        if item.get("type") == "user"
    }


def _require_date(value: Any, where: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise Np3ManifestError(f"{where}: {value!r} is not a YYYY-MM-DD date") from None


def _unknown_keys(mapping: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise Np3ManifestError(f"{where}: unknown key(s) {', '.join(unknown)}")


def parse_np3_manifest(data: dict[str, Any]) -> Np3Manifest:
    """Validate against what the real routes accept, so a bad manifest fails before any
    destructive step rather than as a rejected request halfway through a replay."""
    from app.features.compliant.modules.nz_alcohol.catalogue import framework_by_slug
    from app.features.compliant.modules.nz_alcohol.np3_audit import evidence_playbook, np3_log_template

    if not isinstance(data, dict):
        raise Np3ManifestError("manifest must be a JSON object")
    _unknown_keys(data, _MANIFEST_KEYS, "manifest")
    controls = dict((framework_by_slug(NP3_FRAMEWORK) or {}).get("controls", ()))

    profile = data.get("profile")
    if profile is not None:
        if not isinstance(profile, dict) or not isinstance(profile.get("settings"), dict):
            raise Np3ManifestError("profile must be an object with a settings object (or null)")
        _unknown_keys(profile, _PROFILE_KEYS, "profile")

    staff: list[Np3Staff] = []
    for index, item in enumerate(data.get("staff") or []):
        where = f"staff[{index}]"
        if not isinstance(item, dict) or not str(item.get("email") or "").strip():
            raise Np3ManifestError(f"{where}: email is required")
        _unknown_keys(item, {"email", "role", "name"}, where)
        role = item.get("role", "member")
        if role not in STAFF_ROLES:
            raise Np3ManifestError(f"{where}: role must be one of {', '.join(STAFF_ROLES)}")
        name = str(item.get("name") or "").strip()
        if len(name) > 120:
            raise Np3ManifestError(f"{where}: name must be at most 120 characters")
        staff.append(Np3Staff(email=item["email"].strip().lower(), role=role, name=name))
    emails = [member.email for member in staff]
    if len(set(emails)) != len(emails):
        raise Np3ManifestError("staff: duplicate email")

    attestations: list[Np3Attestation] = []
    for index, item in enumerate(data.get("attestations") or []):
        where = f"attestations[{index}]"
        if not isinstance(item, dict):
            raise Np3ManifestError(f"{where}: must be an object")
        if "source_refs" in item:
            raise Np3ManifestError(f"{where}: source_refs cannot be replayed (Core IDs change on every reset)")
        _unknown_keys(item, _ATTESTATION_KEYS, where)
        control_id = str(item.get("control_id") or "")
        if control_id not in controls:
            raise Np3ManifestError(f"{where}: unknown NP3 control {control_id!r}")
        how_we_meet = str(item.get("how_we_meet") or "").strip()
        if not how_we_meet or len(how_we_meet) > 4000:
            raise Np3ManifestError(f"{where}: how_we_meet is required and at most 4000 characters")
        interval = item.get("review_interval_months", 6)
        if interval not in REVIEW_INTERVALS:
            raise Np3ManifestError(f"{where}: review_interval_months must be one of {REVIEW_INTERVALS}")
        signed_on = _require_date(item.get("signed_on"), f"{where}.signed_on")
        due_date = (
            _require_date(item["due_date"], f"{where}.due_date")
            if item.get("due_date")
            else _add_months(signed_on, interval)
        )
        evidence_reference = str(item.get("evidence_reference") or "").strip()
        if len(evidence_reference) > 1024:
            raise Np3ManifestError(f"{where}: evidence_reference must be at most 1024 characters")
        evidence_fields = item.get("evidence_fields") or {}
        allowed_fields = {entry["key"] for entry in evidence_playbook(control_id)["fields"]}
        if (
            not isinstance(evidence_fields, dict)
            or not set(evidence_fields) <= allowed_fields
            or not all(isinstance(v, str) and len(v) <= 1024 for v in evidence_fields.values())
        ):
            raise Np3ManifestError(f"{where}: evidence_fields do not match {control_id!r}")
        attestations.append(
            Np3Attestation(
                control_id=control_id,
                signed_on=signed_on,
                due_date=due_date,
                review_interval_months=interval,
                how_we_meet=how_we_meet,
                evidence_reference=evidence_reference,
                evidence_fields=_clean(evidence_fields),
            )
        )

    logs: list[Np3Log] = []
    annual_training = data.get("annual_training")
    if annual_training is not None:
        if not isinstance(annual_training, dict):
            raise Np3ManifestError("annual_training must be an object")
        _unknown_keys(annual_training, _ANNUAL_TRAINING_KEYS, "annual_training")
        dates = annual_training.get("dates")
        if not isinstance(dates, list) or not dates:
            raise Np3ManifestError("annual_training.dates must be a non-empty list")
        training_dates = [_require_date(value, f"annual_training.dates[{index}]") for index, value in enumerate(dates)]
        if len(set(training_dates)) != len(training_dates):
            raise Np3ManifestError("annual_training.dates must not contain duplicates")
        topics = annual_training.get("topics")
        if not isinstance(topics, list) or not topics:
            raise Np3ManifestError("annual_training.topics must be a non-empty list")
        training_topics: list[tuple[str, tuple[str, ...]]] = []
        for index, item in enumerate(topics):
            where = f"annual_training.topics[{index}]"
            if not isinstance(item, dict):
                raise Np3ManifestError(f"{where}: must be an object")
            _unknown_keys(item, _ANNUAL_TRAINING_TOPIC_KEYS, where)
            title = str(item.get("title") or "").strip()
            control_ids = item.get("np3_controls")
            if not title or len(title) > 1024:
                raise Np3ManifestError(f"{where}: title is required and at most 1024 characters")
            if (
                not isinstance(control_ids, list)
                or not control_ids
                or not all(isinstance(control_id, str) and control_id in controls for control_id in control_ids)
                or len(set(control_ids)) != len(control_ids)
            ):
                raise Np3ManifestError(f"{where}: np3_controls must be unique known NP3 controls")
            training_topics.append((title, tuple(control_ids)))
        for training_date in training_dates:
            for member in staff:
                for title, control_ids in training_topics:
                    mapped_controls = ", ".join(control_ids)
                    person = member.name or member.email
                    logs.append(
                        Np3Log(
                            control_id="staff-competency",
                            fields={
                                "event_date": training_date.isoformat(),
                                "employee_email": member.email,
                                "training_topic": f"{title} (NP3 checks: {mapped_controls})",
                                "competency_result": "observed-competent",
                                "review_notes": (
                                    "REVIEW PLACEHOLDER — training register records "
                                    f"{person} as completed; confirm attendance and practical competency evidence."
                                ),
                            },
                        )
                    )

    for index, item in enumerate(data.get("logs") or []):
        where = f"logs[{index}]"
        if not isinstance(item, dict):
            raise Np3ManifestError(f"{where}: must be an object")
        _unknown_keys(item, {"control_id", "fields"}, where)
        control_id = str(item.get("control_id") or "")
        template = np3_log_template(control_id)
        if control_id not in controls or template is None:
            raise Np3ManifestError(f"{where}: {control_id!r} has no built-in NP3 log")
        fields = item.get("fields")
        if not isinstance(fields, dict):
            raise Np3ManifestError(f"{where}: fields must be an object")
        manifest_keys = _user_field_keys(control_id)
        allowed = {f["key"] for f in template["fields"]} - set(manifest_keys) | set(manifest_keys.values())
        if not set(fields) <= allowed:
            raise Np3ManifestError(f"{where}: fields {sorted(set(fields) - allowed)} do not match {control_id!r}")
        cleaned = _clean(fields)
        for definition in template["fields"]:
            key = manifest_keys.get(definition["key"], definition["key"])
            if definition.get("required") and not cleaned.get(key):
                raise Np3ManifestError(f"{where}: {definition['label']} ({key}) is required")
            if definition.get("type") == "date" and cleaned.get(key):
                _require_date(cleaned[key], f"{where}.{key}")
            if definition.get("type") == "select" and cleaned.get(key):
                if cleaned[key] not in {option[0] for option in definition.get("options", ())}:
                    raise Np3ManifestError(f"{where}: {key} has an invalid option {cleaned[key]!r}")
        for email in (cleaned[key].lower() for key in manifest_keys.values() if key in cleaned):
            if email not in emails:
                raise Np3ManifestError(f"{where}: {email!r} is not listed under staff")
        for key in manifest_keys.values():
            if key in cleaned:
                cleaned[key] = cleaned[key].lower()
        if cleaned.get("result") == "action-required" and not (
            cleaned.get("corrective_action") or cleaned.get("cause_and_action")
        ):
            raise Np3ManifestError(f"{where}: a follow-up-required entry needs its corrective action")
        logs.append(Np3Log(control_id=control_id, fields=cleaned))

    fingerprints = [record.fingerprint for record in (*attestations, *logs)]
    if len(set(fingerprints)) != len(fingerprints):
        raise Np3ManifestError("two NP3 entries have identical content; identity is content-based, so they must differ")
    return Np3Manifest(
        profile=profile,
        staff=tuple(staff),
        attestations=tuple(attestations),
        logs=tuple(logs),
        raw=data,
    )


def load_np3_manifest(path: Path = DEFAULT_NP3_MANIFEST) -> Np3Manifest:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Np3ManifestError(f"NP3 manifest not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise Np3ManifestError(f"NP3 manifest is not valid JSON: {exc}") from None
    return parse_np3_manifest(data)


# --------------------------------------------------------------------------------------
# Database reads (read-only, same pattern as MarkerStore)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DbRecord:
    id: str
    kind: str  # "attestation" | "log" | "unrecognised"
    control_id: str
    fingerprint: str | None
    created_on: date
    due_date: date | None
    period_start: date | None
    review_interval_months: int | None
    how_we_meet: str
    evidence_reference: str
    evidence_fields: dict[str, str]
    log_fields: dict[str, str]
    has_source_refs: bool


class Np3Store:
    def __init__(self, target_url: str, org_id: Any):
        self._engine = create_engine(target_url)
        self.org_id = str(org_id)

    def dispose(self) -> None:
        self._engine.dispose()

    def user_id_for_email(self, email: str) -> str | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT id FROM users WHERE org_id = :org AND lower(email) = :email LIMIT 1"),
                {"org": self.org_id, "email": email.lower()},
            ).first()
            return str(row[0]) if row else None

    def users(self) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, lower(email), role, is_active FROM users WHERE org_id = :org ORDER BY lower(email)"),
                {"org": self.org_id},
            ).all()
        return [{"id": str(r[0]), "email": r[1], "role": str(r[2]).lower(), "is_active": r[3]} for r in rows]

    def profile(self) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT council_name, trade_waste_consent_reference, settings "
                    "FROM compliance_profiles WHERE org_id = :org LIMIT 1"
                ),
                {"org": self.org_id},
            ).first()
        if row is None:
            return None
        return {"council_name": row[0], "trade_waste_consent_reference": row[1], "settings": row[2] or {}}

    def records(self) -> list[DbRecord]:
        email_by_id = {user["id"]: user["email"] for user in self.users()}
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, control_id, record_type, details, evidence_reference, due_date, period_start, "
                    "created_at, source_refs FROM compliance_records "
                    "WHERE org_id = :org AND framework_slug = :framework ORDER BY created_at, id"
                ),
                {"org": self.org_id, "framework": NP3_FRAMEWORK},
            ).all()
        records: list[DbRecord] = []
        for row in rows:
            record_id, control_id, record_type, details, reference, due, period_start, created_at, refs = row
            details = details or {}
            base = dict(
                id=str(record_id),
                control_id=control_id,
                created_on=created_at.astimezone(_LOCAL_TZ).date(),
                due_date=due,
                period_start=period_start,
                evidence_reference=(reference or "").strip(),
                has_source_refs=bool(refs),
            )
            if record_type == "attestation" and "how_we_meet" in details:
                interval = details.get("review_interval_months", 6)
                fields = _clean(details.get("evidence_fields"))
                records.append(
                    DbRecord(
                        kind="attestation",
                        fingerprint=attestation_fingerprint(
                            control_id, details["how_we_meet"], interval, reference, fields
                        ),
                        review_interval_months=interval,
                        how_we_meet=details["how_we_meet"].strip(),
                        evidence_fields=fields,
                        log_fields={},
                        **base,
                    )
                )
            elif "log_fields" in details:
                keys = _user_field_keys(control_id)
                fields = {}
                for key, value in _clean(details["log_fields"]).items():
                    if key in keys:
                        fields[keys[key]] = email_by_id.get(value, value).lower()
                    else:
                        fields[key] = value
                records.append(
                    DbRecord(
                        kind="log",
                        fingerprint=log_fingerprint(control_id, fields),
                        review_interval_months=None,
                        how_we_meet="",
                        evidence_fields={},
                        log_fields=fields,
                        **base,
                    )
                )
            else:
                records.append(
                    DbRecord(
                        kind="unrecognised",
                        fingerprint=None,
                        review_interval_months=None,
                        how_we_meet="",
                        evidence_fields={},
                        log_fields={},
                        **base,
                    )
                )
        return records

    def fingerprints(self) -> set[str]:
        return {record.fingerprint for record in self.records() if record.fingerprint}


# --------------------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------------------


def replay_np3(client: Any, store: Np3Store, manifest: Np3Manifest) -> dict[str, int]:
    """Issue the manifest through the real API. Runs after every Core event so an
    `np3_execution_evidence_mode: required` profile cannot block the Core replay."""
    counts = {"staff": 0, "profile": 0, "attestations": 0, "logs": 0, "skipped": 0}

    for member in manifest.staff:
        if store.user_id_for_email(member.email):
            counts["skipped"] += 1
            continue
        # Nobody signs in as a seeded staff member; the password is thrown away.
        client.post("/org/users", {"email": member.email, "password": secrets.token_urlsafe(32), "role": member.role})
        counts["staff"] += 1

    if manifest.profile is not None:
        payload = {"settings": manifest.profile["settings"]}
        for key in ("council_name", "trade_waste_consent_reference"):
            if key in manifest.profile:
                payload[key] = manifest.profile[key]
        client.put("/api/compliant/profile", payload)
        counts["profile"] += 1

    existing = store.fingerprints()
    for attestation in manifest.attestations:
        if attestation.fingerprint in existing:
            counts["skipped"] += 1
            continue
        body: dict[str, Any] = {
            "control_id": attestation.control_id,
            "how_we_meet": attestation.how_we_meet,
            "confirmed": True,
            "review_interval_months": attestation.review_interval_months,
        }
        if attestation.evidence_reference:
            body["evidence_reference"] = attestation.evidence_reference
        if attestation.evidence_fields:
            body["evidence_fields"] = attestation.evidence_fields
        client.post("/api/compliant/np3-audit/attestations", body)
        counts["attestations"] += 1

    for log in manifest.logs:
        if log.fingerprint in existing:
            counts["skipped"] += 1
            continue
        fields = dict(log.fields)
        for key, manifest_key in _user_field_keys(log.control_id).items():
            if manifest_key in fields:
                user_id = store.user_id_for_email(fields.pop(manifest_key))
                if user_id is None:
                    raise Np3ManifestError(f"log for {log.control_id}: staff member was not created")
                fields[key] = user_id
        client.post(f"/api/compliant/np3-audit/checks/{log.control_id}/logs", {"fields": fields})
        counts["logs"] += 1
    return counts


# --------------------------------------------------------------------------------------
# Timestamp pass and verification
# --------------------------------------------------------------------------------------


def _org_id(conn: Any, org_name: str) -> Any:
    row = conn.execute(text("SELECT id FROM organisations WHERE name = :name"), {"name": org_name}).first()
    if not row:
        raise ValueError(f"org {org_name!r} does not exist")
    return row[0]


def correct_np3_timestamps(target_url: str, org_name: str, manifest: Np3Manifest) -> int:
    """Set each replayed record's business dates from the manifest. Fails loudly if a
    manifest record was never replayed, rather than skipping past it."""
    engine = create_engine(target_url)
    updated = 0
    try:
        with engine.begin() as conn:
            org_id = _org_id(conn, org_name)
            store = Np3Store(target_url, org_id)
            try:
                by_fingerprint = {r.fingerprint: r for r in store.records() if r.fingerprint}
            finally:
                store.dispose()
            attestation_updates: list[dict[str, Any]] = []
            log_updates: list[dict[str, Any]] = []
            for record in (*manifest.attestations, *manifest.logs):
                row = by_fingerprint.get(record.fingerprint)
                if row is None:
                    raise RuntimeError(f"NP3 record for {record.control_id} was not replayed; cannot date it")
                if isinstance(record, Np3Attestation):
                    at = wm._derived_timestamp(record.signed_on)
                    attestation_updates.append({"at": at, "due": record.due_date, "id": row.id, "org": org_id})
                else:
                    at = wm._derived_timestamp(record.event_date)
                    log_updates.append({"at": at, "id": row.id, "org": org_id})
            # Batched after validation, so a record that was never replayed changes nothing.
            if attestation_updates:
                conn.execute(
                    text(
                        "UPDATE compliance_records SET created_at = :at, updated_at = :at, due_date = :due "
                        "WHERE id = :id AND org_id = :org"
                    ),
                    attestation_updates,
                )
            if log_updates:
                conn.execute(
                    text(
                        "UPDATE compliance_records SET created_at = :at, updated_at = :at "
                        "WHERE id = :id AND org_id = :org"
                    ),
                    log_updates,
                )
            updated = len(attestation_updates) + len(log_updates)
    finally:
        engine.dispose()
    return updated


def _expected_profile(manifest: Np3Manifest) -> dict[str, Any]:
    """What the org's profile should hold: the manifest's, else just the setup baseline."""
    if manifest.profile is not None:
        return {
            "council_name": manifest.profile.get("council_name"),
            "trade_waste_consent_reference": manifest.profile.get("trade_waste_consent_reference"),
            "settings": manifest.profile["settings"],
        }
    return {
        "council_name": None,
        "trade_waste_consent_reference": None,
        "settings": wm.WHISTLEBIRD_NZ_ALCOHOL_SETTINGS,
    }


def verify_np3(target_url: str, org_name: str, manifest: Np3Manifest) -> dict[str, Any]:
    """`{expected, actual}` pairs in the shape `_require_matching_import` already checks.

    Two-way on purpose: a count mismatch catches evidence in the database the manifest
    lacks (unsnapshotted), the content pair catches manifest evidence that is missing or
    differs, and the date pair catches a record the timestamp pass did not date.
    """
    engine = create_engine(target_url)
    try:
        with engine.connect() as conn:
            org_id = _org_id(conn, org_name)
    finally:
        engine.dispose()
    store = Np3Store(target_url, org_id)
    try:
        records = store.records()
        users = {user["email"]: user for user in store.users()}
        profile = store.profile()
    finally:
        store.dispose()

    by_fingerprint = {r.fingerprint: r for r in records if r.fingerprint}
    present = 0
    date_mismatches = 0
    for record in (*manifest.attestations, *manifest.logs):
        row = by_fingerprint.get(record.fingerprint)
        if row is None:
            continue
        present += 1
        if isinstance(record, Np3Attestation):
            wrong = row.created_on != record.signed_on or row.due_date != record.due_date
        else:
            wrong = row.created_on != record.event_date
        date_mismatches += int(wrong)
    expected_profile = _expected_profile(manifest)
    profile_matches = profile is not None and all(profile[key] == expected_profile[key] for key in expected_profile)
    staff_present = sum(1 for member in manifest.staff if member.email in users and users[member.email]["is_active"])
    return {
        "np3_record_count": {"expected": manifest.record_count, "actual": len(records)},
        "np3_record_content": {"expected": manifest.record_count, "actual": present},
        "np3_staff": {"expected": len(manifest.staff), "actual": staff_present},
        "np3_profile": {"expected": 1, "actual": int(profile_matches)},
        "np3_date_mismatches": date_mismatches,
    }


def np3_unsnapshotted(
    target_url: str, org_name: str, manifest: Np3Manifest, admin_email: str = wm.DEFAULT_TEST_ADMIN_EMAIL
) -> list[str]:
    """Human-readable reasons a reset would lose NP3 evidence the manifest does not hold.
    Empty when the org is absent (nothing to lose) or the manifest already covers it."""
    engine = create_engine(target_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT id FROM organisations WHERE name = :name"), {"name": org_name}).first()
    finally:
        engine.dispose()
    if row is None:
        return []
    store = Np3Store(target_url, row[0])
    try:
        records = store.records()
        profile = store.profile()
        users = {user["email"] for user in store.users()}
    finally:
        store.dispose()
    reasons: list[str] = []
    manifest_fingerprints = {r.fingerprint for r in (*manifest.attestations, *manifest.logs)}
    for record in records:
        if record.fingerprint is None:
            reasons.append(f"{record.control_id}: a record the manifest cannot represent ({record.id})")
        elif record.fingerprint not in manifest_fingerprints:
            reasons.append(f"{record.control_id}: {record.kind} in the database is not in the manifest")
    expected = _expected_profile(manifest)
    if profile is not None and any(profile[key] != expected[key] for key in expected):
        reasons.append("NP3 profile settings in the database differ from the manifest")
    extra_users = users - {m.email for m in manifest.staff} - {admin_email}
    if extra_users:
        reasons.append(f"users in the database not in the manifest: {', '.join(sorted(extra_users))}")
    return reasons


# --------------------------------------------------------------------------------------
# Snapshot: database -> manifest
# --------------------------------------------------------------------------------------


def snapshot_np3(target_url: str, org_name: str, existing: Np3Manifest | None = None) -> dict[str, Any]:
    """Read the org's NP3 evidence into manifest form.

    Dates you already set in the manifest win: a record whose content is unchanged keeps
    its `signed_on`/`due_date`. New attestations take the date they were signed in the
    database (today) -- edit `signed_on` in the JSON to the date you want.
    """
    if org_name != wm.RESET_ORG_NAME:
        raise ValueError(f"Snapshot is only permitted for {wm.RESET_ORG_NAME!r}")
    return _snapshot_org(target_url, org_name, existing, wm.DEFAULT_TEST_ADMIN_EMAIL)


def _snapshot_org(target_url: str, org_name: str, existing: Np3Manifest | None, admin_email: str) -> dict[str, Any]:
    """`snapshot_np3` minus the tenant-name guard, so tests can run it on a throwaway org."""
    engine = create_engine(target_url)
    try:
        with engine.connect() as conn:
            org_id = _org_id(conn, org_name)
    finally:
        engine.dispose()
    store = Np3Store(target_url, org_id)
    try:
        records = store.records()
        users = store.users()
        profile = store.profile()
    finally:
        store.dispose()

    problems = [
        f"{r.control_id}: {r.kind} record {r.id} "
        + ("links Core records (source_refs)" if r.has_source_refs else "is not an NP3 attestation or log")
        for r in records
        if r.kind == "unrecognised" or r.has_source_refs
    ]
    if problems:
        raise Np3SnapshotError("cannot snapshot:\n  " + "\n  ".join(problems))

    prior = {r.fingerprint: r for r in ((*existing.attestations, *existing.logs) if existing else ())}
    attestations = []
    for record in records:
        if record.kind != "attestation":
            continue
        kept = prior.get(record.fingerprint)
        entry: dict[str, Any] = {
            "control_id": record.control_id,
            "signed_on": (kept.signed_on if kept else record.created_on).isoformat(),
            "due_date": (kept.due_date if kept else record.due_date).isoformat(),
            "review_interval_months": record.review_interval_months,
            "how_we_meet": record.how_we_meet,
        }
        if record.evidence_reference:
            entry["evidence_reference"] = record.evidence_reference
        if record.evidence_fields:
            entry["evidence_fields"] = dict(sorted(record.evidence_fields.items()))
        attestations.append(entry)
    logs = [
        {"control_id": r.control_id, "fields": dict(sorted(r.log_fields.items()))} for r in records if r.kind == "log"
    ]
    attestations.sort(key=lambda e: (e["control_id"], e["signed_on"], e["how_we_meet"]))
    logs.sort(key=lambda e: (e["control_id"], e["fields"].get("event_date", ""), json.dumps(e["fields"])))

    seeded = [{"email": user["email"], "role": user["role"]} for user in users if user["email"] != admin_email]
    inactive = [user["email"] for user in users if not user["is_active"] and user["email"] != admin_email]
    if inactive:
        raise Np3SnapshotError(f"inactive users cannot be replayed: {', '.join(inactive)}")

    manifest: dict[str, Any] = {
        "profile": None,
        "staff": seeded,
        "attestations": attestations,
        "logs": logs,
    }
    if profile is not None and profile != _expected_profile(Np3Manifest()):
        manifest["profile"] = {
            "council_name": profile["council_name"],
            "trade_waste_consent_reference": profile["trade_waste_consent_reference"],
            "settings": profile["settings"],
        }
    parse_np3_manifest(manifest)  # the snapshot must itself be a valid, replayable manifest
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="Validate the manifest without touching any database.")
    validate.add_argument("--manifest", type=Path, default=DEFAULT_NP3_MANIFEST)
    snap = sub.add_parser("snapshot", help="Write the org's NP3 evidence from the database into the manifest.")
    snap.add_argument("--manifest", type=Path, default=DEFAULT_NP3_MANIFEST)
    snap.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    snap.add_argument("--org-name", default=wm.RESET_ORG_NAME)
    snap.add_argument("--dry-run", action="store_true", help="Print what would change; write nothing.")
    check = sub.add_parser("verify", help="Compare the database against the manifest, read-only.")
    check.add_argument("--manifest", type=Path, default=DEFAULT_NP3_MANIFEST)
    check.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    check.add_argument("--org-name", default=wm.RESET_ORG_NAME)
    args = parser.parse_args()
    if args.command != "validate" and not args.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    return args


def main() -> int:
    args = _arguments()
    try:
        if args.command == "validate":
            manifest = load_np3_manifest(args.manifest)
            print(
                f"ok: {len(manifest.attestations)} attestations, {len(manifest.logs)} logs, {len(manifest.staff)} staff"
            )
            return 0
        current = load_np3_manifest(args.manifest) if args.manifest.exists() else None
        if args.command == "verify":
            report = verify_np3(args.target_url, args.org_name, current or Np3Manifest())
            print(json.dumps(report, indent=2))
            pairs = [value for value in report.values() if isinstance(value, dict)]
            mismatched = any(pair["expected"] != pair["actual"] for pair in pairs)
            return 1 if mismatched or report["np3_date_mismatches"] else 0
        snapshot = snapshot_np3(args.target_url, args.org_name, current)
    except (Np3ManifestError, Np3SnapshotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    saved = parse_np3_manifest(snapshot)
    before = {r.fingerprint for r in (*current.attestations, *current.logs)} if current else set()
    after = {r.fingerprint for r in (*saved.attestations, *saved.logs)}
    print(
        f"snapshot: {len(snapshot['attestations'])} attestations, {len(snapshot['logs'])} logs, "
        f"{len(snapshot['staff'])} staff; {len(after - before)} new, {len(before - after)} removed"
    )
    if args.dry_run:
        return 0
    write_manifest(args.manifest, snapshot)
    print(f"wrote {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
