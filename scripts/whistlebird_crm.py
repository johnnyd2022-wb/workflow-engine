"""Replayable CRM sales-traceability configuration for Whistlebird Ltd.

The scoped reset deletes `product_mappings` and `crm_sales_traceability_config`, and neither
can be recovered from the legacy database. This module keeps them in version control
(`docs/whistlebird-crm-config-source.json`) and replays them through the real CRM API after
the Core history -- the same routes and validation the Configuration page hits -- so a
delete-and-rebuild does not silently lose the mappings that let Xero sales draw down FIFO
stock.

The Xero OAuth connection itself cannot be replayed; reconnect it in the app afterwards.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CRM_MANIFEST = Path(__file__).parents[1] / "docs" / "whistlebird-crm-config-source.json"

MATCH_TYPES = ("exact", "contains", "alias")
_MANIFEST_KEYS = {"_comment", "traceability_config", "product_mappings"}
_CONFIG_KEYS = {
    "matching_strategy",
    "manual_review_days",
    "strict_mapping",
    "task_done_archive_days",
    "revenue_baseline_target_mtd",
}
_MAPPING_KEYS = {"biz_e_product_name", "xero_description_pattern", "match_type", "notes"}
_MAX_TEXT = 500


class CrmManifestError(ValueError):
    """The CRM manifest is malformed. Raised before any request is issued."""


class CrmReplayError(RuntimeError):
    """A real API call was rejected or the target is not in the state the manifest needs."""


@dataclass(frozen=True)
class CrmMapping:
    biz_e_product_name: str
    xero_description_pattern: str
    match_type: str
    notes: str | None

    @property
    def key(self) -> tuple[str, str]:
        """Identity the server uses to reject duplicates: name and phrase, ignoring case."""
        return (self.biz_e_product_name.casefold(), self.xero_description_pattern.casefold())

    def payload(self) -> dict[str, Any]:
        return {
            "biz_e_product_name": self.biz_e_product_name,
            "xero_description_pattern": self.xero_description_pattern,
            "match_type": self.match_type,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CrmManifest:
    traceability_config: dict[str, Any]
    mappings: tuple[CrmMapping, ...]


def _unknown_keys(mapping: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise CrmManifestError(f"{where}: unknown key(s) {unknown}")


def _text(entry: dict[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CrmManifestError(f"{where}: {key} must be a non-empty string")
    value = value.strip()
    if len(value) > _MAX_TEXT:
        raise CrmManifestError(f"{where}: {key} must be {_MAX_TEXT} characters or fewer")
    return value


def parse_crm_manifest(data: dict[str, Any]) -> CrmManifest:
    if not isinstance(data, dict):
        raise CrmManifestError("manifest must be a JSON object")
    _unknown_keys(data, _MANIFEST_KEYS, "manifest")

    config = data.get("traceability_config")
    if not isinstance(config, dict):
        raise CrmManifestError("manifest: traceability_config must be an object")
    _unknown_keys(config, _CONFIG_KEYS, "traceability_config")
    if not isinstance(config.get("strict_mapping"), bool):
        raise CrmManifestError("traceability_config: strict_mapping must be true or false")

    raw_mappings = data.get("product_mappings")
    if not isinstance(raw_mappings, list) or not raw_mappings:
        raise CrmManifestError("manifest: product_mappings must be a non-empty list")

    mappings: list[CrmMapping] = []
    for index, entry in enumerate(raw_mappings):
        where = f"product_mappings[{index}]"
        if not isinstance(entry, dict):
            raise CrmManifestError(f"{where}: must be an object")
        _unknown_keys(entry, _MAPPING_KEYS, where)
        match_type = str(entry.get("match_type") or "exact").strip().lower()
        if match_type not in MATCH_TYPES:
            raise CrmManifestError(f"{where}: match_type must be one of {MATCH_TYPES}")
        notes = entry.get("notes")
        mappings.append(
            CrmMapping(
                biz_e_product_name=_text(entry, "biz_e_product_name", where),
                xero_description_pattern=_text(entry, "xero_description_pattern", where),
                match_type=match_type,
                notes=str(notes).strip() if notes else None,
            )
        )

    keys = [mapping.key for mapping in mappings]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise CrmManifestError(f"product_mappings: duplicate mapping(s) {duplicates} (compared ignoring case)")

    # A partial-match rule is silently inert while exact-only matching is on, which is the
    # state a reset leaves the tenant in -- so a manifest that asks for one without turning
    # exact-only matching off would rebuild a tenant whose sales all stay unmapped.
    if config["strict_mapping"] and any(mapping.match_type != "exact" for mapping in mappings):
        raise CrmManifestError(
            "traceability_config.strict_mapping is true but a mapping uses contains/alias matching, "
            "which never matches while exact-only matching is on"
        )
    return CrmManifest(traceability_config=dict(config), mappings=tuple(mappings))


def load_crm_manifest(path: Path = DEFAULT_CRM_MANIFEST) -> CrmManifest:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CrmManifestError(f"cannot read CRM manifest {path}: {exc}") from exc
    return parse_crm_manifest(data)


def missing_mappings(manifest: CrmManifest, existing: list[dict[str, Any]]) -> list[CrmMapping]:
    """Manifest mappings the target does not have yet (name and phrase, ignoring case)."""
    present = {
        (
            str(row.get("biz_e_product_name") or "").strip().casefold(),
            str(row.get("xero_description_pattern") or "").strip().casefold(),
        )
        for row in existing
    }
    return [mapping for mapping in manifest.mappings if mapping.key not in present]


def replay_crm_config(client: Any, manifest: CrmManifest) -> dict[str, int]:
    """Issue the manifest through the real CRM API. Resumable: mappings already present are skipped.

    Runs after every Core event, so each mapping's final product already exists. The
    configuration goes first, as it does when saving from the Configuration page.
    """
    # Refuse a mapping to a product the tenant does not have: the API would accept it and it
    # would simply never match, which is the failure this replay exists to prevent.
    products = {
        str(option.get("name") or "").strip().casefold()
        for option in client.get("/api/crm/final-products").get("final_products", [])
    }
    unknown = sorted(
        {m.biz_e_product_name for m in manifest.mappings if m.biz_e_product_name.casefold() not in products}
    )
    if unknown:
        raise CrmReplayError(f"CRM manifest maps to final product(s) that do not exist in the target: {unknown}")

    client.put("/api/crm/traceability-config", dict(manifest.traceability_config))

    existing = client.get("/api/crm/product-mappings").get("product_mappings", [])
    to_create = missing_mappings(manifest, existing)
    if to_create:
        client.post("/api/crm/product-mappings/bulk", {"mappings": [mapping.payload() for mapping in to_create]})
    return {
        "config": 1,
        "mappings_created": len(to_create),
        "mappings_skipped": len(manifest.mappings) - len(to_create),
    }


def verify_crm(target_url: str, org_name: str, manifest: CrmManifest) -> dict[str, Any]:
    """Read-only check that the target holds every manifest mapping and the manifest's config.

    Reported as missing/mismatch counts that should be zero, rather than as an exact row
    count, so a mapping the founder adds later in the CRM does not fail a later verify.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(target_url)
    try:
        with engine.connect() as conn:
            org_id = conn.execute(text("SELECT id FROM organisations WHERE name = :name"), {"name": org_name}).scalar()
            if org_id is None:
                raise CrmReplayError(f"organisation {org_name!r} does not exist")
            rows = conn.execute(
                text(
                    "SELECT biz_e_product_name, xero_description_pattern FROM product_mappings "
                    "WHERE org_id = :org_id AND is_active"
                ),
                {"org_id": org_id},
            ).all()
            config = conn.execute(
                text(
                    "SELECT strict_mapping, matching_strategy FROM crm_sales_traceability_config WHERE org_id = :org_id"
                ),
                {"org_id": org_id},
            ).first()
    finally:
        engine.dispose()

    existing = [{"biz_e_product_name": name, "xero_description_pattern": phrase} for name, phrase in rows]
    wanted = manifest.traceability_config
    config_matches = (
        config is not None
        and bool(config[0]) == wanted["strict_mapping"]
        and config[1] == wanted.get("matching_strategy", "fifo")
    )
    return {
        "crm_product_mappings_missing": {"expected": 0, "actual": len(missing_mappings(manifest, existing))},
        "crm_traceability_config_mismatch": {"expected": 0, "actual": 0 if config_matches else 1},
    }
