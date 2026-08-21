#!/usr/bin/env python3
"""Safe preflight tooling for the one-off Whistlebird v1 → Biz-E migration.

This initial command is deliberately read-only.  It produces aggregate-only reports:
no contacts, email addresses, free-text notes, product names, or credentials are emitted.
Future reset/import commands must keep the same explicit tenant guardrails.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.orm import sessionmaker

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
LEGACY_TABLES = (
    "audit",
    "buyers",
    "crm_customers",
    "crm_follow_ups",
    "crm_logs",
    "crm_tasks",
    "customs_lodgements",
    "emails",
    "inventory",
    "monthly_totals",
    "product_actions_bottling",
    "product_actions_create_premix",
    "product_actions_distillation_experiments",
    "product_actions_ethanol",
    "product_actions_ex_stock_storage",
    "product_actions_flavor_experiments",
    "product_actions_flavor_vat",
    "product_actions_flavors",
    "product_actions_samples_consumed",
    "product_actions_samples_created",
    "products",
    "purchases_empty_bottles",
    "purchases_gns",
    "purchases_ingredients",
    "sales_product",
    "sales_product_samples",
    "suppliers",
)
RESET_TABLES = (
    "api_idempotency_keys",
    "audit_logs",
    "crm_notes",
    "crm_tasks",
    "xero_invoice_line_items",
    "xero_invoices",
    "xero_contacts",
    "xero_oauth_tokens",
    "xero_sync_jobs",
    "xero_tenants",
    "product_mappings",
    "crm_sales_traceability_config",
    "compliance_reports",
    "compliance_records",
    "compliance_alcohol_product_profiles",
    "compliance_profiles",
    "execution_evidence",
    "inventory_movements",
    "inventory_wastage",
    "inventory_items",
    "process_step_documents",
    "execution_steps",
    "executions",
    "process_versions",
    "steps",
    "processes",
    "entity_event_summaries",
    "entity_events",
)
RESET_ORG_NAME = "whistlebird_test"
DERIVED_TIMEZONE = ZoneInfo("Pacific/Auckland")
DERIVED_TIME = time(hour=12)
HISTORICAL_PROCESS_TEMPLATES = (
    ("Legacy ingredient receipt", "Receive a historical botanical/ingredient lot", "Ingredient lot", "g"),
    ("Legacy neutral spirit receipt", "Receive a historical neutral-grain-spirit lot", "GNS lot", "L"),
    ("Legacy packaging receipt", "Receive historical empty-bottle packaging", "Empty bottles", "units"),
    ("Legacy flavour preparation", "Prepare a historical flavour intermediate", "Flavour batch", "mL"),
    ("Legacy flavour vat", "Combine historical flavour into a vat", "Vat batch", "L"),
    ("Legacy distillation", "Run a historical distillation experiment", "Distillate", "L"),
    ("Legacy bottling", "Bottle a historical finished-product batch", "Bottle batch", "units"),
    ("Legacy samples", "Record historical sample creation or consumption", "Sample record", "units"),
    ("Legacy ex-stock storage", "Record historical off-site finished stock", "Stored bottle batch", "units"),
)


@dataclass(frozen=True)
class ProposedCoreRecord:
    """Validated migration record; never rendered with source business data."""

    legacy_table: str
    legacy_id: int
    legacy_date: date
    target_kind: str
    quantity: Decimal | None
    unit: str | None
    derived_at: datetime


@dataclass(frozen=True)
class ReceiptSourceRecord:
    """A source purchase row that can become one historically dated Core receipt."""

    legacy_table: str
    legacy_id: int
    legacy_date: date
    name: str
    quantity: Decimal
    unit: str
    supplier: str | None
    supplier_batch_number: str | None
    expiry_date: date | None
    process_name: str
    extra_data: dict[str, Any]


@dataclass(frozen=True)
class HistoricalOperationRecord:
    """One v1 production operation represented by a completed Core execution/output."""

    legacy_table: str
    legacy_id: int
    legacy_date: date
    process_name: str
    item_name: str
    quantity: Decimal
    unit: str
    inventory_type: str
    batch_label: str | None
    input_references: tuple[tuple[str, str], ...]
    extra_data: dict[str, Any]


@dataclass(frozen=True)
class HistoricalSampleRecord:
    legacy_table: str
    legacy_id: int
    legacy_date: date
    flavor_code: str | None
    details: dict[str, Any]


def _identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def _json_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _derived_timestamp(source_date: date) -> datetime:
    """Convert a date-only source value using the agreed, explicitly-derived convention."""
    return datetime.combine(source_date, DERIVED_TIME, tzinfo=DERIVED_TIMEZONE).astimezone(UTC)


def _decimal(value: Any, field: str, legacy_table: str, legacy_id: int) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{legacy_table}#{legacy_id} has invalid {field}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{legacy_table}#{legacy_id} has invalid {field}")
    return parsed.quantize(Decimal("0.0001"))


def _required_date(value: Any, legacy_table: str, legacy_id: int) -> date:
    if not isinstance(value, date):
        raise ValueError(f"{legacy_table}#{legacy_id} has no valid source date")
    return value


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _legacy_provenance(legacy_table: str, legacy_id: int, legacy_date: date) -> dict[str, Any]:
    return {
        "source_system": "whistlebird_v1",
        "legacy_source": {"table": legacy_table, "id": legacy_id},
        "legacy_date": legacy_date.isoformat(),
        "timestamp_policy": "derived_noon_pacific_auckland",
    }


def _decimal_label(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _legacy_list(value: Any) -> tuple[str, ...]:
    """Parse v1's brace-wrapped text lists without inferring their contents."""
    raw = _optional_text(value)
    if raw is None:
        return ()
    return tuple(
        entry
        for entry in (part.strip().strip('"') for part in raw.strip("{}").split(","))
        if entry
    )


def _receipt_source_records(connection: Connection) -> Iterator[ReceiptSourceRecord]:
    for row in connection.execute(
        text("SELECT id, date, supplier, gns_purchased_l, abv FROM purchases_gns ORDER BY id")
    ).mappings():
        legacy_id = row["id"]
        legacy_date = _required_date(row["date"], "purchases_gns", legacy_id)
        yield ReceiptSourceRecord(
            legacy_table="purchases_gns",
            legacy_id=legacy_id,
            legacy_date=legacy_date,
            name="Neutral grain spirit",
            quantity=_decimal(row["gns_purchased_l"], "gns_purchased_l", "purchases_gns", legacy_id),
            unit="L",
            supplier=_optional_text(row["supplier"]),
            supplier_batch_number=f"legacy-purchases_gns-{legacy_id}",
            expiry_date=None,
            process_name="Legacy neutral spirit receipt",
            extra_data={"legacy_gns_abv_percent": str(row["abv"] or "")},
        )

    for row in connection.execute(
        text("SELECT id, date, supplier, bottle_size_ml, empty_bottles_stored FROM purchases_empty_bottles ORDER BY id")
    ).mappings():
        legacy_id = row["id"]
        legacy_date = _required_date(row["date"], "purchases_empty_bottles", legacy_id)
        bottle_size = _decimal(row["bottle_size_ml"], "bottle_size_ml", "purchases_empty_bottles", legacy_id)
        yield ReceiptSourceRecord(
            legacy_table="purchases_empty_bottles",
            legacy_id=legacy_id,
            legacy_date=legacy_date,
            name=f"Empty bottles ({_decimal_label(bottle_size)} mL)",
            quantity=_decimal(
                row["empty_bottles_stored"], "empty_bottles_stored", "purchases_empty_bottles", legacy_id
            ),
            unit="units",
            supplier=_optional_text(row["supplier"]),
            supplier_batch_number=f"legacy-purchases_empty_bottles-{legacy_id}",
            expiry_date=None,
            process_name="Legacy packaging receipt",
            extra_data={"legacy_bottle_size_ml": str(bottle_size)},
        )

    for row in connection.execute(
        text(
            """
            SELECT id, date, supplier, ingredients, ingredients_amount, ingredients_code, ingredients_expiry
            FROM purchases_ingredients
            ORDER BY id
            """
        )
    ).mappings():
        legacy_id = row["id"]
        legacy_date = _required_date(row["date"], "purchases_ingredients", legacy_id)
        ingredient_name = _optional_text(row["ingredients"])
        if ingredient_name is None:
            raise ValueError(f"purchases_ingredients#{legacy_id} has no ingredient name")
        expiry_date = row["ingredients_expiry"]
        if expiry_date is not None and not isinstance(expiry_date, date):
            raise ValueError(f"purchases_ingredients#{legacy_id} has invalid ingredients_expiry")
        yield ReceiptSourceRecord(
            legacy_table="purchases_ingredients",
            legacy_id=legacy_id,
            legacy_date=legacy_date,
            name=ingredient_name,
            quantity=_decimal(row["ingredients_amount"], "ingredients_amount", "purchases_ingredients", legacy_id),
            unit="g",
            supplier=_optional_text(row["supplier"]),
            supplier_batch_number=_optional_text(row["ingredients_code"])
            or f"legacy-purchases_ingredients-{legacy_id}",
            expiry_date=expiry_date,
            process_name="Legacy ingredient receipt",
            extra_data={},
        )


def _disambiguate_reused_supplier_batches(records: list[ReceiptSourceRecord]) -> list[ReceiptSourceRecord]:
    """Respect Biz-E's name/batch uniqueness while retaining every legacy receipt row."""
    batch_keys = Counter((record.name, record.supplier_batch_number) for record in records)
    disambiguated: list[ReceiptSourceRecord] = []
    for record in records:
        key = (record.name, record.supplier_batch_number)
        if record.supplier_batch_number is None or batch_keys[key] == 1:
            disambiguated.append(record)
            continue
        original_batch = record.supplier_batch_number
        suffix = f" [legacy-{record.legacy_table}-{record.legacy_id}]"
        disambiguated.append(
            replace(
                record,
                supplier_batch_number=f"{original_batch[: 255 - len(suffix)]}{suffix}",
                extra_data={
                    **record.extra_data,
                    "legacy_supplier_batch_number": original_batch,
                    "supplier_batch_number_disambiguated": True,
                },
            )
        )
    return disambiguated


def _operation_source_records(connection: Connection) -> Iterator[HistoricalOperationRecord]:
    for row in connection.execute(
        text(
            """
            SELECT id, date, flavor_stored_ml, clearing_amount, clearing_abv, flavor_code, flavor_batch,
                   ingredient_codes
            FROM product_actions_flavors
            ORDER BY id
            """
        )
    ).mappings():
        legacy_id = row["id"]
        legacy_date = _required_date(row["date"], "product_actions_flavors", legacy_id)
        yield HistoricalOperationRecord(
            legacy_table="product_actions_flavors",
            legacy_id=legacy_id,
            legacy_date=legacy_date,
            process_name="Legacy flavour preparation",
            item_name="Historical flavour intermediate",
            quantity=_decimal(row["flavor_stored_ml"], "flavor_stored_ml", "product_actions_flavors", legacy_id),
            unit="mL",
            inventory_type="work_in_progress",
            batch_label=_optional_text(row["flavor_batch"]) or _optional_text(row["flavor_code"]),
            input_references=tuple(("ingredient_code", code) for code in _legacy_list(row["ingredient_codes"])),
            extra_data={
                "legacy_flavor_code": _optional_text(row["flavor_code"]),
                "legacy_flavor_batch": _optional_text(row["flavor_batch"]),
                "legacy_clearing_amount": str(row["clearing_amount"] or ""),
                "legacy_clearing_abv_percent": str(row["clearing_abv"] or ""),
            },
        )
    for row in connection.execute(
        text(
            """
            SELECT id, date, flavor_stored_ml, clearing_amount, clearing_abv, flavor_code
            FROM product_actions_flavor_experiments
            ORDER BY id
            """
        )
    ).mappings():
        legacy_id = row["id"]
        legacy_date = _required_date(row["date"], "product_actions_flavor_experiments", legacy_id)
        flavor_code = _optional_text(row["flavor_code"])
        yield HistoricalOperationRecord(
            legacy_table="product_actions_flavor_experiments",
            legacy_id=legacy_id,
            legacy_date=legacy_date,
            process_name="Legacy flavour preparation",
            item_name="Historical flavour experiment",
            quantity=_decimal(
                row["flavor_stored_ml"], "flavor_stored_ml", "product_actions_flavor_experiments", legacy_id
            ),
            unit="mL",
            inventory_type="work_in_progress",
            batch_label=flavor_code,
            input_references=(),
            extra_data={
                "legacy_flavor_code": flavor_code,
                "legacy_clearing_amount": str(row["clearing_amount"] or ""),
                "legacy_clearing_abv_percent": str(row["clearing_abv"] or ""),
            },
        )

    for row in connection.execute(
        text(
            """
            SELECT id, date, alcohol_used_l, alcohol_used_abv, alcohol_yield_l, alcohol_yield_abv,
                   experiment_id, flavor_codes, lal
            FROM product_actions_distillation_experiments
            ORDER BY id
            """
        )
    ).mappings():
        legacy_id = row["id"]
        legacy_date = _required_date(row["date"], "product_actions_distillation_experiments", legacy_id)
        yield_abv = _decimal(
            row["alcohol_yield_abv"], "alcohol_yield_abv", "product_actions_distillation_experiments", legacy_id
        )
        yield HistoricalOperationRecord(
            legacy_table="product_actions_distillation_experiments",
            legacy_id=legacy_id,
            legacy_date=legacy_date,
            process_name="Legacy distillation",
            item_name=f"Historical distillate ({_decimal_label(yield_abv)}% ABV)",
            quantity=_decimal(
                row["alcohol_yield_l"], "alcohol_yield_l", "product_actions_distillation_experiments", legacy_id
            ),
            unit="L",
            inventory_type="work_in_progress",
            batch_label=_optional_text(row["experiment_id"]),
            input_references=tuple(("flavor_code", code) for code in (row["flavor_codes"] or [])),
            extra_data={
                "legacy_experiment_id": _optional_text(row["experiment_id"]),
                "legacy_alcohol_used_l": str(row["alcohol_used_l"] or ""),
                "legacy_alcohol_used_abv_percent": str(row["alcohol_used_abv"] or ""),
                "legacy_yield_abv_percent": str(yield_abv),
                "legacy_litres_of_alcohol": str(row["lal"] or ""),
            },
        )

    for row in connection.execute(
        text(
            """
            SELECT id, date, notes, alcohol_volume, alcohol_abv, lal, container_id
            FROM product_actions_create_premix
            ORDER BY id
            """
        )
    ).mappings():
        legacy_id = row["id"]
        legacy_date = _required_date(row["date"], "product_actions_create_premix", legacy_id)
        yield HistoricalOperationRecord(
            legacy_table="product_actions_create_premix",
            legacy_id=legacy_id,
            legacy_date=legacy_date,
            process_name="Legacy flavour preparation",
            item_name="Historical premix",
            quantity=_decimal(row["alcohol_volume"], "alcohol_volume", "product_actions_create_premix", legacy_id),
            unit="L",
            inventory_type="work_in_progress",
            batch_label=_optional_text(row["container_id"]),
            input_references=(),
            extra_data={
                "legacy_container_id": _optional_text(row["container_id"]),
                "legacy_alcohol_abv_percent": str(row["alcohol_abv"] or ""),
                "legacy_litres_of_alcohol": str(row["lal"] or ""),
                "legacy_notes_present": bool(_optional_text(row["notes"])),
            },
        )

    for row in connection.execute(
        text(
            """
            SELECT id, date, product_name, storage_id, bottle_size_ml, abv, bottles_stored, lal
            FROM product_actions_ex_stock_storage
            ORDER BY id
            """
        )
    ).mappings():
        legacy_id = row["id"]
        legacy_date = _required_date(row["date"], "product_actions_ex_stock_storage", legacy_id)
        bottle_size = _decimal(row["bottle_size_ml"], "bottle_size_ml", "product_actions_ex_stock_storage", legacy_id)
        abv = _decimal(row["abv"], "abv", "product_actions_ex_stock_storage", legacy_id)
        yield HistoricalOperationRecord(
            legacy_table="product_actions_ex_stock_storage",
            legacy_id=legacy_id,
            legacy_date=legacy_date,
            process_name="Legacy ex-stock storage",
            item_name=_optional_text(row["product_name"])
            or f"Whistlebird ex-stock product ({_decimal_label(bottle_size)} mL, {_decimal_label(abv)}% ABV)",
            quantity=_decimal(
                row["bottles_stored"], "bottles_stored", "product_actions_ex_stock_storage", legacy_id
            ),
            unit="units",
            inventory_type="final_product",
            batch_label=_optional_text(row["storage_id"]),
            input_references=(),
            extra_data={
                "legacy_storage_id": _optional_text(row["storage_id"]),
                "legacy_bottle_size_ml": str(bottle_size),
                "legacy_abv_percent": str(abv),
                "legacy_litres_of_alcohol": str(row["lal"] or ""),
            },
        )

    for row in connection.execute(
        text("SELECT id, date, abv, vat_batch, volume_amount, flavor_batch FROM product_actions_flavor_vat ORDER BY id")
    ).mappings():
        legacy_id = row["id"]
        legacy_date = _required_date(row["date"], "product_actions_flavor_vat", legacy_id)
        yield HistoricalOperationRecord(
            legacy_table="product_actions_flavor_vat",
            legacy_id=legacy_id,
            legacy_date=legacy_date,
            process_name="Legacy flavour vat",
            item_name="Historical flavour vat",
            quantity=_decimal(row["volume_amount"], "volume_amount", "product_actions_flavor_vat", legacy_id),
            unit="L",
            inventory_type="work_in_progress",
            batch_label=_optional_text(row["vat_batch"]),
            input_references=tuple(("flavor_batch", batch) for batch in _legacy_list(row["flavor_batch"])),
            extra_data={
                "legacy_vat_batch": _optional_text(row["vat_batch"]),
                "legacy_vat_abv_percent": str(row["abv"] or ""),
                "legacy_flavor_batches": list(_legacy_list(row["flavor_batch"])),
            },
        )

    for row in connection.execute(
        text(
            """
            SELECT id, date, bottles_stored, abv, bottle_size_ml, vat_batch, bottle_batch
            FROM product_actions_bottling
            ORDER BY id
            """
        )
    ).mappings():
        legacy_id = row["id"]
        legacy_date = _required_date(row["date"], "product_actions_bottling", legacy_id)
        bottle_size = _decimal(row["bottle_size_ml"], "bottle_size_ml", "product_actions_bottling", legacy_id)
        abv = _decimal(row["abv"], "abv", "product_actions_bottling", legacy_id)
        yield HistoricalOperationRecord(
            legacy_table="product_actions_bottling",
            legacy_id=legacy_id,
            legacy_date=legacy_date,
            process_name="Legacy bottling",
            item_name=(
                f"Whistlebird bottled product ({_decimal_label(bottle_size)} mL, {_decimal_label(abv)}% ABV)"
            ),
            quantity=_decimal(row["bottles_stored"], "bottles_stored", "product_actions_bottling", legacy_id),
            unit="units",
            inventory_type="final_product",
            batch_label=_optional_text(row["bottle_batch"]),
            input_references=(
                (("vat_batch", _optional_text(row["vat_batch"])),) if _optional_text(row["vat_batch"]) else ()
            ),
            extra_data={
                "legacy_bottle_batch": _optional_text(row["bottle_batch"]),
                "legacy_vat_batch": _optional_text(row["vat_batch"]),
                "legacy_bottle_size_ml": str(bottle_size),
                "legacy_abv_percent": str(abv),
                "legacy_total_volume_ml": str((bottle_size * _decimal(row["bottles_stored"], "bottles_stored", "product_actions_bottling", legacy_id)).quantize(Decimal("0.0001"))),
            },
        )


def _sample_source_records(connection: Connection) -> Iterator[HistoricalSampleRecord]:
    for table in ("product_actions_samples_created", "product_actions_samples_consumed"):
        for row in connection.execute(
            text(
                f"""
                SELECT id, date, flavor_code, number_of_bottles, abv, bottle_size_ml, lal
                FROM {_identifier(table)}
                ORDER BY id
                """
            )
        ).mappings():
            legacy_id = row["id"]
            legacy_date = _required_date(row["date"], table, legacy_id)
            yield HistoricalSampleRecord(
                legacy_table=table,
                legacy_id=legacy_id,
                legacy_date=legacy_date,
                flavor_code=_optional_text(row["flavor_code"]),
                details={
                    "sample_action": "created" if table.endswith("created") else "consumed",
                    "legacy_number_of_bottles": str(row["number_of_bottles"] or ""),
                    "legacy_abv_percent": str(row["abv"] or ""),
                    "legacy_bottle_size_ml": str(row["bottle_size_ml"] or ""),
                    "legacy_litres_of_alcohol": str(row["lal"] or ""),
                },
            )


def _date_columns(connection: Connection) -> Iterator[tuple[str, str]]:
    rows = connection.execute(
        text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND data_type = 'date'
            ORDER BY table_name, column_name
            """
        )
    )
    yield from rows.tuples()


def _legacy_profile(connection: Connection) -> dict[str, Any]:
    table_counts = {
        table: connection.execute(text(f"SELECT count(*) FROM {_identifier(table)}")).scalar_one()
        for table in LEGACY_TABLES
    }

    date_ranges: dict[str, dict[str, Any]] = {}
    for table, column in _date_columns(connection):
        if table not in LEGACY_TABLES:
            continue
        result = connection.execute(
            text(
                f"SELECT count({_identifier(column)}), min({_identifier(column)}), max({_identifier(column)}) "
                f"FROM {_identifier(table)}"
            )
        ).one()
        date_ranges[f"{table}.{column}"] = {
            "non_null_count": result[0],
            "min": _json_value(result[1]),
            "max": _json_value(result[2]),
        }

    link_metrics = connection.execute(
        text(
            """
            SELECT 'bottling_vat_batches' AS metric,
                   count(DISTINCT nullif(trim(vat_batch), '')) AS value
            FROM product_actions_bottling
            UNION ALL
            SELECT 'bottling_bottle_batches', count(DISTINCT nullif(trim(bottle_batch), ''))
            FROM product_actions_bottling
            UNION ALL
            SELECT 'sales_bottle_batches', count(DISTINCT nullif(trim(bottle_batch), ''))
            FROM sales_product
            UNION ALL
            SELECT 'bottling_to_sales_batch_matches', count(*)
            FROM product_actions_bottling b
            JOIN sales_product s
              ON nullif(trim(b.bottle_batch), '') = nullif(trim(s.bottle_batch), '')
            UNION ALL
            SELECT 'bottling_to_flavour_vat_matches', count(*)
            FROM product_actions_bottling b
            JOIN product_actions_flavor_vat f
              ON nullif(trim(b.vat_batch), '') = nullif(trim(f.vat_batch), '')
            UNION ALL
            SELECT 'sales_json_product_payloads', count(*) FILTER (WHERE products IS NOT NULL)
            FROM sales_product
            UNION ALL
            SELECT 'sales_json_product_entries', count(*)
            FROM sales_product
            CROSS JOIN LATERAL jsonb_each(coalesce(products -> 'products', '{}'::jsonb))
            """
        )
    ).tuples()

    source_timezone = connection.execute(text("SHOW TimeZone")).scalar_one()
    source_timestamp_column_count = connection.execute(
        text(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type IN ('timestamp with time zone', 'timestamp without time zone')
            """
        )
    ).scalar_one()
    return {
        "source_timezone": source_timezone,
        "source_timestamp_column_count": source_timestamp_column_count,
        "table_counts": table_counts,
        "date_ranges": date_ranges,
        "link_metrics": dict(link_metrics.all()),
    }


def _target_profile(connection: Connection, requested_org_name: str) -> dict[str, Any]:
    exact_match_count = connection.execute(
        text("SELECT count(*) FROM organisations WHERE name = :name"), {"name": requested_org_name}
    ).scalar_one()
    similar_org_count = connection.execute(
        text("SELECT count(*) FROM organisations WHERE lower(name) LIKE :pattern"),
        {"pattern": "%whistlebird%"},
    ).scalar_one()
    return {
        "requested_org_name": requested_org_name,
        "requested_org_exists": bool(exact_match_count),
        "similarly_named_org_count": similar_org_count,
    }


def build_core_dry_run(legacy_url: str) -> dict[str, Any]:
    """Validate the first import tranche without writing source or target data."""
    proposed: list[ProposedCoreRecord] = []
    customs_lodgements = 0

    with create_engine(legacy_url).connect() as connection:
        gns_rows = connection.execute(
            text("SELECT id, date, gns_purchased_l FROM purchases_gns ORDER BY id")
        ).mappings()
        for row in gns_rows:
            legacy_id = row["id"]
            legacy_date = _required_date(row["date"], "purchases_gns", legacy_id)
            proposed.append(
                ProposedCoreRecord(
                    legacy_table="purchases_gns",
                    legacy_id=legacy_id,
                    legacy_date=legacy_date,
                    target_kind="raw_material_addition",
                    quantity=_decimal(row["gns_purchased_l"], "gns_purchased_l", "purchases_gns", legacy_id),
                    unit="L",
                    derived_at=_derived_timestamp(legacy_date),
                )
            )

        bottle_rows = connection.execute(
            text("SELECT id, date, empty_bottles_stored FROM purchases_empty_bottles ORDER BY id")
        ).mappings()
        for row in bottle_rows:
            legacy_id = row["id"]
            legacy_date = _required_date(row["date"], "purchases_empty_bottles", legacy_id)
            proposed.append(
                ProposedCoreRecord(
                    legacy_table="purchases_empty_bottles",
                    legacy_id=legacy_id,
                    legacy_date=legacy_date,
                    target_kind="raw_material_addition",
                    quantity=_decimal(
                        row["empty_bottles_stored"], "empty_bottles_stored", "purchases_empty_bottles", legacy_id
                    ),
                    unit="units",
                    derived_at=_derived_timestamp(legacy_date),
                )
            )

        ingredient_rows = connection.execute(
            text("SELECT id, date, ingredients_amount FROM purchases_ingredients ORDER BY id")
        ).mappings()
        for row in ingredient_rows:
            legacy_id = row["id"]
            legacy_date = _required_date(row["date"], "purchases_ingredients", legacy_id)
            proposed.append(
                ProposedCoreRecord(
                    legacy_table="purchases_ingredients",
                    legacy_id=legacy_id,
                    legacy_date=legacy_date,
                    target_kind="raw_material_addition",
                    quantity=_decimal(
                        row["ingredients_amount"], "ingredients_amount", "purchases_ingredients", legacy_id
                    ),
                    unit="g",
                    derived_at=_derived_timestamp(legacy_date),
                )
            )

        lodgement_rows = connection.execute(
            text("SELECT id, date, lodged_volume, lodged_abv, lal FROM customs_lodgements ORDER BY id")
        ).mappings()
        for row in lodgement_rows:
            legacy_id = row["id"]
            legacy_date = _required_date(row["date"], "customs_lodgements", legacy_id)
            _decimal(row["lodged_volume"], "lodged_volume", "customs_lodgements", legacy_id)
            _decimal(row["lodged_abv"], "lodged_abv", "customs_lodgements", legacy_id)
            _decimal(row["lal"], "lal", "customs_lodgements", legacy_id)
            customs_lodgements += 1

    by_kind: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for record in proposed:
        by_kind[record.target_kind] = by_kind.get(record.target_kind, 0) + 1
        by_source[record.legacy_table] = by_source.get(record.legacy_table, 0) + 1
    return {
        "dry_run": True,
        "timestamp_policy": "derived_noon_pacific_auckland",
        "proposed_records": by_kind,
        "proposed_records_by_source": by_source,
        "validated_compliance_records": {"customs_lodgements": customs_lodgements},
        "notes": [
            "No target rows were written.",
            "Ingredient quantities are grams, confirmed from the deployed Whistlebird v1 form.",
            "Batch-linked production and sales rows are intentionally excluded from this tranche.",
        ],
    }


def build_traceability_dry_run(legacy_url: str) -> dict[str, Any]:
    """Measure legacy production/sales linkage without inferring missing batch edges."""
    with create_engine(legacy_url).connect() as connection:
        metrics = connection.execute(
            text(
                """
                SELECT 'flavour_actions' AS metric, count(*) AS value
                FROM product_actions_flavors
                UNION ALL
                SELECT 'flavour_vat_actions', count(*)
                FROM product_actions_flavor_vat
                UNION ALL
                SELECT 'premix_actions', count(*)
                FROM product_actions_create_premix
                UNION ALL
                SELECT 'distillation_actions', count(*)
                FROM product_actions_distillation_experiments
                UNION ALL
                SELECT 'bottling_actions', count(*)
                FROM product_actions_bottling
                UNION ALL
                SELECT 'bottling_rows_with_flavour_vat_match', count(*)
                FROM product_actions_bottling b
                WHERE EXISTS (
                    SELECT 1
                    FROM product_actions_flavor_vat f
                    WHERE nullif(trim(b.vat_batch), '') = nullif(trim(f.vat_batch), '')
                )
                UNION ALL
                SELECT 'flavour_vat_rows_with_flavour_match', count(*)
                FROM product_actions_flavor_vat v
                WHERE EXISTS (
                    SELECT 1
                    FROM product_actions_flavors f
                    CROSS JOIN LATERAL unnest(string_to_array(trim(both '{}' FROM v.flavor_batch), ',')) ref(flavor_batch)
                    WHERE f.flavor_batch = trim(both '"' FROM ref.flavor_batch)
                )
                UNION ALL
                SELECT 'bottling_rows_with_manual_sales_batch_match', count(*)
                FROM product_actions_bottling b
                WHERE EXISTS (
                    SELECT 1
                    FROM sales_product s
                    CROSS JOIN LATERAL unnest(string_to_array(trim(both '{}' FROM s.bottle_batch), ',')) ref(bottle_batch)
                    WHERE b.bottle_batch = trim(both '"' FROM ref.bottle_batch)
                )
                UNION ALL
                SELECT 'sales_rows', count(*)
                FROM sales_product
                UNION ALL
                SELECT 'manual_sales_rows_with_bottling_match', count(DISTINCT s.id)
                FROM sales_product s
                WHERE EXISTS (
                    SELECT 1
                    FROM product_actions_bottling b
                    CROSS JOIN LATERAL unnest(string_to_array(trim(both '{}' FROM s.bottle_batch), ',')) ref(bottle_batch)
                    WHERE b.bottle_batch = trim(both '"' FROM ref.bottle_batch)
                )
                UNION ALL
                SELECT 'sales_product_entries', count(*)
                FROM sales_product
                CROSS JOIN LATERAL jsonb_each(coalesce(products -> 'products', '{}'::jsonb))
                UNION ALL
                SELECT 'sales_product_entries_with_batch', count(*)
                FROM sales_product
                CROSS JOIN LATERAL jsonb_each(coalesce(products -> 'products', '{}'::jsonb)) item
                WHERE nullif(trim(item.value ->> 'bottle_batch'), '') IS NOT NULL
                """
            )
        ).all()
    values = dict(metrics)
    return {
        "dry_run": True,
        "metrics": values,
        "ready_edges": {
            "flavour_to_flavour_vat": values["flavour_vat_rows_with_flavour_match"],
            "bottling_to_flavour_vat": values["bottling_rows_with_flavour_vat_match"],
            "bottling_to_manual_sales": values["manual_sales_rows_with_bottling_match"],
        },
        "held_edges": {
            "invoice_derived_sales_needing_reconciliation": values["sales_rows"]
            - values["manual_sales_rows_with_bottling_match"],
        },
        "notes": [
            "Only database-evidenced batch matches are eligible for automatic traceability edges.",
            "No production, inventory, process, execution or sales rows were written.",
            "Sales product payloads remain available for Xero reconciliation after connection.",
        ],
    }


def build_production_dry_run(legacy_url: str) -> dict[str, Any]:
    """Validate the directly evidenced flavour/vat/bottling production tranche without writes."""
    with create_engine(legacy_url).connect() as connection:
        operations = list(_operation_source_records(connection))
    by_source = Counter(operation.legacy_table for operation in operations)
    references = Counter(kind for operation in operations for kind, _ in operation.input_references)
    return {
        "dry_run": True,
        "proposed_completed_executions": dict(sorted(by_source.items())),
        "proposed_input_references": dict(sorted(references.items())),
        "operations_without_direct_input_reference": sum(not operation.input_references for operation in operations),
        "notes": [
            "No target rows were written.",
            "Only exact legacy ingredient-code, flavour-code, flavour-batch and vat-batch references are eligible for Core inputs.",
            "Input quantities are not inferred where the v1 operation omitted them.",
        ],
    }


def apply_core_receipts_and_lodgements(legacy_url: str, target_url: str, requested_org_name: str) -> dict[str, int]:
    """Import the deterministic v1 purchase and Customs rows into existing Core/Compliant tables.

    The target guard deliberately permits only the disposable Whistlebird test tenant.  Reruns
    identify rows by their v1 table/id provenance stored in existing JSONB metadata; no migration
    ledger or schema extension is introduced.
    """
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Core import is only permitted for {RESET_ORG_NAME!r}")

    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
    from app.core.db.models.inventory_wastage import InventoryWastage  # noqa: F401 - resolves ORM relationship
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.process import Process
    from app.core.db.models.step import Step
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from app.core.db.repositories.inventory_repo import InventoryRepository
    from app.features.compliant.models.compliance_record import ComplianceRecord

    with create_engine(legacy_url).connect() as legacy_connection:
        receipts = _disambiguate_reused_supplier_batches(list(_receipt_source_records(legacy_connection)))
        lodgements = list(
            legacy_connection.execute(
                text(
                    """
                    SELECT id, date, date_period, lodged_volume, lodged_abv, lal, bottles
                    FROM customs_lodgements
                    ORDER BY id
                    """
                )
            ).mappings()
        )

    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    imported_receipts = 0
    skipped_receipts = 0
    imported_lodgements = 0
    skipped_lodgements = 0
    try:
        org = session.query(Organisation).filter(Organisation.name == requested_org_name).one_or_none()
        if org is None:
            raise ValueError(f"Target organisation {requested_org_name!r} does not exist")
        # This standalone, explicitly scoped script has its own SQLAlchemy engine rather than
        # the application engine that registers the per-statement guard synchroniser.  The Core
        # repository still supplies its normal Python-side write authorisation; this transaction-
        # local GUC supplies the matching PostgreSQL trigger authorisation for receipt creation.
        session.execute(text("SELECT set_config('app.inventory_qty_guard', '1', true)"))
        processes = {
            process.name: process
            for process in session.query(Process)
            .filter(Process.org_id == org.id, Process.name.in_([record.process_name for record in receipts]))
            .all()
        }
        missing_processes = sorted({record.process_name for record in receipts} - set(processes))
        if missing_processes:
            raise RuntimeError(f"Missing historical process templates: {', '.join(missing_processes)}")

        execution_repository = ExecutionRepository(session)
        inventory_repository = InventoryRepository(session)
        for record in receipts:
            source = {"table": record.legacy_table, "id": record.legacy_id}
            existing = (
                session.query(InventoryItem.id)
                .filter(InventoryItem.org_id == org.id, InventoryItem.extra_data.contains({"legacy_source": source}))
                .first()
            )
            if existing:
                skipped_receipts += 1
                continue

            process = processes[record.process_name]
            execution = execution_repository.create_execution(org.id, process.id, commit=False)
            execution_step = (
                session.query(ExecutionStep)
                .filter(ExecutionStep.execution_id == execution.id, ExecutionStep.org_id == org.id)
                .one()
            )
            step = session.query(Step).filter(Step.id == execution_step.step_id).one()
            output_id = step.outputs[0]["id"]
            provenance = _legacy_provenance(record.legacy_table, record.legacy_id, record.legacy_date)
            item = inventory_repository.create_inventory_item(
                org_id=org.id,
                name=record.name,
                quantity=record.quantity,
                unit=record.unit,
                inventory_type="raw_material",
                supplier=record.supplier,
                purchase_date=record.legacy_date,
                supplier_batch_number=record.supplier_batch_number,
                expiry_date=record.expiry_date,
                source_execution_id=execution.id,
                source_execution_step_id=execution_step.id,
                source_output_id=output_id,
                source_step_name=step.name,
                extra_data={**provenance, **record.extra_data, "historical_import": True},
                commit=False,
            )
            execution_repository.complete_step(
                execution_step.id,
                org.id,
                actual_outputs=[
                    {
                        "inventory_item_id": str(item.id),
                        "name": item.name,
                        "quantity": str(record.quantity),
                        "unit": record.unit,
                    }
                ],
                execution_data={**provenance, "historical_import": True},
                completed_at_override=_derived_timestamp(record.legacy_date),
                commit=False,
            )
            business_at = _derived_timestamp(record.legacy_date)
            execution.started_at = business_at
            execution.completed_at = business_at
            execution.created_at = business_at
            execution.updated_at = business_at
            execution_step.started_at = business_at
            execution_step.completed_at = business_at
            execution_step.created_at = business_at
            execution_step.updated_at = business_at
            item.created_at = business_at
            item.updated_at = business_at
            session.add(
                InventoryMovement(
                    org_id=org.id,
                    inventory_item_id=item.id,
                    movement_type=InventoryMovementType.ADD.value,
                    quantity=record.quantity,
                    unit=record.unit,
                    created_at=business_at,
                    movement_metadata={**provenance, "historical_import": True},
                )
            )
            imported_receipts += 1

        for row in lodgements:
            legacy_id = row["id"]
            legacy_date = _required_date(row["date"], "customs_lodgements", legacy_id)
            source = {"table": "customs_lodgements", "id": legacy_id}
            existing = (
                session.query(ComplianceRecord.id)
                .filter(ComplianceRecord.org_id == org.id, ComplianceRecord.details.contains({"legacy_source": source}))
                .first()
            )
            if existing:
                skipped_lodgements += 1
                continue
            provenance = _legacy_provenance("customs_lodgements", legacy_id, legacy_date)
            period = _optional_text(row["date_period"]) or legacy_date.isoformat()
            lodgement = ComplianceRecord(
                org_id=org.id,
                framework_slug="customs-alcohol",
                control_id="period-lodgement",
                record_type="lodgement",
                status="complete",
                title=f"Historical Customs lodgement: {period}",
                period_start=legacy_date,
                period_end=legacy_date,
                measured_value=_decimal(row["lal"], "lal", "customs_lodgements", legacy_id),
                evidence_reference=(
                    f"Imported from Whistlebird v1 customs_lodgements#{legacy_id}; "
                    "the filed source document is not present in the legacy database."
                ),
                source_refs=[],
                details={
                    **provenance,
                    "historical_import": True,
                    "legacy_period_label": period,
                    "lodged_volume_l": str(
                        _decimal(row["lodged_volume"], "lodged_volume", "customs_lodgements", legacy_id)
                    ),
                    "lodged_abv_percent": str(
                        _decimal(row["lodged_abv"], "lodged_abv", "customs_lodgements", legacy_id)
                    ),
                    "lodged_litres_of_alcohol": str(
                        _decimal(row["lal"], "lal", "customs_lodgements", legacy_id)
                    ),
                    "legacy_bottle_count": str(
                        _decimal(row["bottles"], "bottles", "customs_lodgements", legacy_id)
                    ),
                },
                created_at=_derived_timestamp(legacy_date),
                updated_at=_derived_timestamp(legacy_date),
            )
            session.add(lodgement)
            imported_lodgements += 1

        session.commit()
        return {
            "imported_receipts": imported_receipts,
            "skipped_receipts": skipped_receipts,
            "imported_lodgements": imported_lodgements,
            "skipped_lodgements": skipped_lodgements,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def apply_evidenced_production(legacy_url: str, target_url: str, requested_org_name: str) -> dict[str, int]:
    """Import only v1 flavour/vat/bottling rows whose lineage references are source-evidenced."""
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Production import is only permitted for {RESET_ORG_NAME!r}")

    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
    from app.core.db.models.inventory_wastage import InventoryWastage  # noqa: F401 - resolves ORM relationship
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.process import Process
    from app.core.db.models.step import Step
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from app.core.db.repositories.inventory_repo import InventoryRepository

    with create_engine(legacy_url).connect() as legacy_connection:
        operations = list(_operation_source_records(legacy_connection))

    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    imported = 0
    skipped = 0
    linked_inputs = 0
    try:
        org = session.query(Organisation).filter(Organisation.name == requested_org_name).one_or_none()
        if org is None:
            raise ValueError(f"Target organisation {requested_org_name!r} does not exist")
        session.execute(text("SELECT set_config('app.inventory_qty_guard', '1', true)"))
        processes = {
            process.name: process
            for process in session.query(Process)
            .filter(Process.org_id == org.id, Process.name.in_([operation.process_name for operation in operations]))
            .all()
        }
        missing_processes = sorted({operation.process_name for operation in operations} - set(processes))
        if missing_processes:
            raise RuntimeError(f"Missing historical process templates: {', '.join(missing_processes)}")

        items = session.query(InventoryItem).filter(InventoryItem.org_id == org.id).all()
        ingredient_by_code: dict[str, list[InventoryItem]] = defaultdict(list)
        flavour_by_batch: dict[str, list[InventoryItem]] = defaultdict(list)
        flavour_by_code: dict[str, list[InventoryItem]] = defaultdict(list)
        vat_by_batch: dict[str, list[InventoryItem]] = defaultdict(list)
        for item in items:
            extra_data = item.extra_data or {}
            legacy_source = extra_data.get("legacy_source") or {}
            if legacy_source.get("table") == "purchases_ingredients":
                code = extra_data.get("legacy_supplier_batch_number") or item.supplier_batch_number
                if code:
                    ingredient_by_code[str(code)].append(item)
            if legacy_source.get("table") == "product_actions_flavors" and extra_data.get("legacy_flavor_batch"):
                flavour_by_batch[str(extra_data["legacy_flavor_batch"])].append(item)
            if (
                legacy_source.get("table") == "product_actions_flavor_experiments"
                and extra_data.get("legacy_flavor_code")
            ):
                flavour_by_code[str(extra_data["legacy_flavor_code"])].append(item)
            if legacy_source.get("table") == "product_actions_flavor_vat" and extra_data.get("legacy_vat_batch"):
                vat_by_batch[str(extra_data["legacy_vat_batch"])].append(item)

        available_flavour_batches = {
            operation.batch_label
            for operation in operations
            if operation.legacy_table == "product_actions_flavors" and operation.batch_label
        }
        available_vat_batches = {
            operation.batch_label
            for operation in operations
            if operation.legacy_table == "product_actions_flavor_vat" and operation.batch_label
        }
        available_flavour_codes = {
            str(operation.extra_data["legacy_flavor_code"])
            for operation in operations
            if operation.legacy_table == "product_actions_flavor_experiments"
            and operation.extra_data.get("legacy_flavor_code")
        }
        unresolved_source_references = [
            (operation.legacy_table, operation.legacy_id, kind, reference)
            for operation in operations
            for kind, reference in operation.input_references
            if (kind == "ingredient_code" and reference not in ingredient_by_code)
            or (kind == "flavor_batch" and reference not in available_flavour_batches)
            or (kind == "flavor_code" and reference not in available_flavour_codes)
            or (kind == "vat_batch" and reference not in available_vat_batches)
        ]
        if unresolved_source_references:
            raise RuntimeError("Production import has unresolved source-evidenced references")

        execution_repository = ExecutionRepository(session)
        inventory_repository = InventoryRepository(session)
        for operation in operations:
            source = {"table": operation.legacy_table, "id": operation.legacy_id}
            existing = (
                session.query(InventoryItem)
                .filter(InventoryItem.org_id == org.id, InventoryItem.extra_data.contains({"legacy_source": source}))
                .one_or_none()
            )
            if existing is not None:
                skipped += 1
                item = existing
            else:
                resolved_inputs: list[dict[str, Any]] = []
                for kind, reference in operation.input_references:
                    if kind == "ingredient_code":
                        candidates = ingredient_by_code[reference]
                    elif kind == "flavor_batch":
                        candidates = flavour_by_batch[reference]
                    elif kind == "flavor_code":
                        candidates = flavour_by_code[reference]
                    elif kind == "vat_batch":
                        candidates = vat_by_batch[reference]
                    else:  # Defensive: source builders above are the only permitted reference vocabulary.
                        raise RuntimeError(f"Unsupported production reference kind: {kind}")
                    resolved_inputs.extend(
                        {
                            "inventory_item_id": str(candidate.id),
                            "name": candidate.name,
                            "quantity": None,
                            "unit": candidate.unit,
                            "legacy_link_kind": kind,
                            "legacy_reference": reference,
                            "legacy_quantity_recorded": False,
                        }
                        for candidate in candidates
                    )

                process = processes[operation.process_name]
                execution = execution_repository.create_execution(org.id, process.id, commit=False)
                execution_step = (
                    session.query(ExecutionStep)
                    .filter(ExecutionStep.execution_id == execution.id, ExecutionStep.org_id == org.id)
                    .one()
                )
                step = session.query(Step).filter(Step.id == execution_step.step_id).one()
                provenance = _legacy_provenance(operation.legacy_table, operation.legacy_id, operation.legacy_date)
                original_batch = operation.batch_label or f"legacy-{operation.legacy_table}-{operation.legacy_id}"
                suffix = f" [legacy-{operation.legacy_table}-{operation.legacy_id}]"
                item = inventory_repository.create_inventory_item(
                    org_id=org.id,
                    name=operation.item_name,
                    quantity=operation.quantity,
                    unit=operation.unit,
                    inventory_type=operation.inventory_type,
                    supplier_batch_number=f"{original_batch[: 255 - len(suffix)]}{suffix}",
                    source_execution_id=execution.id,
                    source_execution_step_id=execution_step.id,
                    source_output_id=step.outputs[0]["id"],
                    source_step_name=step.name,
                    extra_data={
                        **provenance,
                        **operation.extra_data,
                        "legacy_batch_label": operation.batch_label,
                        "historical_import": True,
                    },
                    commit=False,
                )
                execution_repository.complete_step(
                    execution_step.id,
                    org.id,
                    actual_inputs=resolved_inputs,
                    actual_outputs=[
                        {
                            "inventory_item_id": str(item.id),
                            "name": item.name,
                            "quantity": str(operation.quantity),
                            "unit": operation.unit,
                        }
                    ],
                    execution_data={
                        **provenance,
                        **operation.extra_data,
                        "historical_import": True,
                        "legacy_input_quantities_unavailable": True,
                    },
                    completed_at_override=_derived_timestamp(operation.legacy_date),
                    commit=False,
                )
                business_at = _derived_timestamp(operation.legacy_date)
                execution.started_at = business_at
                execution.completed_at = business_at
                execution.created_at = business_at
                execution.updated_at = business_at
                execution_step.started_at = business_at
                execution_step.completed_at = business_at
                execution_step.created_at = business_at
                execution_step.updated_at = business_at
                item.created_at = business_at
                item.updated_at = business_at
                session.add(
                    InventoryMovement(
                        org_id=org.id,
                        inventory_item_id=item.id,
                        movement_type=InventoryMovementType.PRODUCTION.value,
                        quantity=operation.quantity,
                        unit=operation.unit,
                        created_at=business_at,
                        movement_metadata={**provenance, "historical_import": True},
                    )
                )
                linked_inputs += len(resolved_inputs)
                imported += 1

            extra_data = item.extra_data or {}
            legacy_source = extra_data.get("legacy_source") or {}
            if legacy_source.get("table") == "product_actions_flavors" and extra_data.get("legacy_flavor_batch"):
                flavour_by_batch[str(extra_data["legacy_flavor_batch"])].append(item)
            if (
                legacy_source.get("table") == "product_actions_flavor_experiments"
                and extra_data.get("legacy_flavor_code")
            ):
                flavour_by_code[str(extra_data["legacy_flavor_code"])].append(item)
            if legacy_source.get("table") == "product_actions_flavor_vat" and extra_data.get("legacy_vat_batch"):
                vat_by_batch[str(extra_data["legacy_vat_batch"])].append(item)

        session.commit()
        return {"imported_executions": imported, "skipped_executions": skipped, "linked_inputs": linked_inputs}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def apply_sample_history(legacy_url: str, target_url: str, requested_org_name: str) -> dict[str, int]:
    """Import historical sample events without fabricating inventory output or consumption quantities."""
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Sample import is only permitted for {RESET_ORG_NAME!r}")

    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.process import Process
    from app.core.db.repositories.execution_repo import ExecutionRepository

    with create_engine(legacy_url).connect() as legacy_connection:
        samples = list(_sample_source_records(legacy_connection))
    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    imported = 0
    skipped = 0
    linked_inputs = 0
    source_only = 0
    try:
        org = session.query(Organisation).filter(Organisation.name == requested_org_name).one_or_none()
        if org is None:
            raise ValueError(f"Target organisation {requested_org_name!r} does not exist")
        process = (
            session.query(Process)
            .filter(Process.org_id == org.id, Process.name == "Legacy samples")
            .one_or_none()
        )
        if process is None:
            raise RuntimeError("Missing historical process template: Legacy samples")

        flavour_by_code: dict[str, list[InventoryItem]] = defaultdict(list)
        for item in session.query(InventoryItem).filter(InventoryItem.org_id == org.id).all():
            extra_data = item.extra_data or {}
            legacy_source = extra_data.get("legacy_source") or {}
            if (
                legacy_source.get("table") == "product_actions_flavor_experiments"
                and extra_data.get("legacy_flavor_code")
            ):
                flavour_by_code[str(extra_data["legacy_flavor_code"])].append(item)

        execution_repository = ExecutionRepository(session)
        for sample in samples:
            source = {"table": sample.legacy_table, "id": sample.legacy_id}
            exists = (
                session.query(ExecutionStep.id)
                .join(Execution, ExecutionStep.execution_id == Execution.id)
                .filter(
                    Execution.org_id == org.id,
                    ExecutionStep.execution_data.contains({"legacy_source": source}),
                )
                .first()
            )
            if exists:
                skipped += 1
                continue

            candidates = flavour_by_code.get(sample.flavor_code or "", [])
            actual_inputs = [
                {
                    "inventory_item_id": str(candidate.id),
                    "name": candidate.name,
                    "quantity": None,
                    "unit": candidate.unit,
                    "legacy_link_kind": "flavor_code",
                    "legacy_reference": sample.flavor_code,
                    "legacy_quantity_recorded": False,
                }
                for candidate in candidates
            ]
            provenance = _legacy_provenance(sample.legacy_table, sample.legacy_id, sample.legacy_date)
            execution = execution_repository.create_execution(org.id, process.id, commit=False)
            execution_step = (
                session.query(ExecutionStep)
                .filter(ExecutionStep.execution_id == execution.id, ExecutionStep.org_id == org.id)
                .one()
            )
            execution_repository.complete_step(
                execution_step.id,
                org.id,
                actual_inputs=actual_inputs,
                actual_outputs=[],
                execution_data={
                    **provenance,
                    **sample.details,
                    "historical_import": True,
                    "legacy_flavor_code": sample.flavor_code,
                    "legacy_flavor_code_resolved": bool(candidates),
                    "no_inventory_output_created": True,
                },
                completed_at_override=_derived_timestamp(sample.legacy_date),
                commit=False,
            )
            business_at = _derived_timestamp(sample.legacy_date)
            execution.started_at = business_at
            execution.completed_at = business_at
            execution.created_at = business_at
            execution.updated_at = business_at
            execution_step.started_at = business_at
            execution_step.completed_at = business_at
            execution_step.created_at = business_at
            execution_step.updated_at = business_at
            imported += 1
            linked_inputs += len(actual_inputs)
            source_only += not bool(actual_inputs)

        session.commit()
        return {
            "imported_sample_executions": imported,
            "skipped_sample_executions": skipped,
            "linked_inputs": linked_inputs,
            "source_only_executions": source_only,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def reset_target_org(target_url: str, requested_org_name: str) -> dict[str, Any]:
    """Delete imported tenant data while preserving the target organisation and its users.

    This is intentionally constrained to the single agreed test tenant.  Do not generalise the
    confirmation flag or call this function for an arbitrary organisation.
    """
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Reset is only permitted for {RESET_ORG_NAME!r}")

    with create_engine(target_url).begin() as connection:
        org_rows = connection.execute(
            text("SELECT id FROM organisations WHERE name = :name"), {"name": requested_org_name}
        ).all()
        if len(org_rows) != 1:
            raise ValueError(f"Expected exactly one target organisation named {requested_org_name!r}")
        org_id = org_rows[0].id
        deleted_rows = {
            table: connection.execute(
                text(f"DELETE FROM {_identifier(table)} WHERE org_id = :org_id"), {"org_id": org_id}
            ).rowcount
            for table in RESET_TABLES
        }
        remaining_rows = {
            table: connection.execute(
                text(f"SELECT count(*) FROM {_identifier(table)} WHERE org_id = :org_id"), {"org_id": org_id}
            ).scalar_one()
            for table in RESET_TABLES
        }
        if any(remaining_rows.values()):
            raise RuntimeError("Scoped reset verification failed; transaction will be rolled back")
    return {
        "org_name": requested_org_name,
        "deleted_rows": deleted_rows,
        "preserved": ["organisations", "users", "trusted_devices", "two_factor_backup_codes"],
    }


def setup_historical_process_templates(target_url: str, requested_org_name: str) -> dict[str, list[str]]:
    """Create only the approved historical templates in the existing Biz-E process model."""
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Historical templates are only permitted for {RESET_ORG_NAME!r}")

    from app.core.db.models.organisation import Organisation
    from app.core.db.models.process import Process, ProcessCategory
    from app.core.db.models.step import Step
    from app.core.db.repositories.process_repo import ProcessRepository

    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    created: list[str] = []
    existing: list[str] = []
    repaired: list[str] = []
    try:
        org = session.query(Organisation).filter(Organisation.name == requested_org_name).one_or_none()
        if org is None:
            raise ValueError(f"Target organisation {requested_org_name!r} does not exist")

        repository = ProcessRepository(session)
        for name, description, output_name, unit in HISTORICAL_PROCESS_TEMPLATES:
            process = session.query(Process).filter(Process.org_id == org.id, Process.name == name).one_or_none()
            if process is not None:
                step_count = session.query(Step).filter(Step.process_id == process.id).count()
                if step_count:
                    existing.append(name)
                    continue
                repaired.append(name)
            else:
                process = repository.create_process(
                    org_id=org.id,
                    name=name,
                    description=f"Historical import template. {description}",
                    category=ProcessCategory.MANUFACTURING,
                    is_draft=False,
                )
                created.append(name)
            repository.add_step(
                process_id=process.id,
                org_id=org.id,
                step_number=1,
                position=1000,
                name="Record historical operation",
                description="Completed historical operation imported from Whistlebird v1.",
                outputs=[{"id": str(uuid4()), "name": output_name, "unit": unit}],
                execution_prompts=[],
            )
        missing_steps = [
            name
            for (name,) in (
                session.query(Process.name)
                .outerjoin(Step, Step.process_id == Process.id)
                .filter(
                    Process.org_id == org.id,
                    Process.name.in_([template[0] for template in HISTORICAL_PROCESS_TEMPLATES]),
                )
                .group_by(Process.name)
                .having(text("count(steps.id) = 0"))
                .all()
            )
        ]
        if missing_steps:
            raise RuntimeError("Historical template setup left a process without a step")
        return {"created": created, "existing": existing, "repaired": repaired}
    finally:
        session.close()
        engine.dispose()


def build_profile(legacy_url: str, target_url: str, requested_org_name: str) -> dict[str, Any]:
    """Read both databases and return an aggregate-only migration preflight report."""
    with create_engine(legacy_url).connect() as legacy_connection:
        legacy = _legacy_profile(legacy_connection)
    with create_engine(target_url).connect() as target_connection:
        target = _target_profile(target_connection, requested_org_name)
    return {"legacy": legacy, "target": target}


def build_import_verification(legacy_url: str, target_url: str, requested_org_name: str) -> dict[str, Any]:
    """Compare imported source counts and business dates without exposing operational data."""
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Verification is only permitted for {RESET_ORG_NAME!r}")
    inventory_tables = (
        "purchases_gns",
        "purchases_empty_bottles",
        "purchases_ingredients",
        "product_actions_flavors",
        "product_actions_flavor_experiments",
        "product_actions_flavor_vat",
        "product_actions_distillation_experiments",
        "product_actions_create_premix",
        "product_actions_bottling",
        "product_actions_ex_stock_storage",
    )
    sample_tables = ("product_actions_samples_created", "product_actions_samples_consumed")
    with create_engine(legacy_url).connect() as source:
        expected_inventory = {
            table: source.execute(text(f"SELECT count(*) FROM {_identifier(table)}")).scalar_one()
            for table in inventory_tables
        }
        expected_samples = {
            table: source.execute(text(f"SELECT count(*) FROM {_identifier(table)}")).scalar_one()
            for table in sample_tables
        }
        expected_lodgements = source.execute(text("SELECT count(*) FROM customs_lodgements")).scalar_one()
    with create_engine(target_url).connect() as target:
        org_id = target.execute(
            text("SELECT id FROM organisations WHERE name = :name"), {"name": requested_org_name}
        ).scalar_one_or_none()
        if org_id is None:
            raise ValueError(f"Target organisation {requested_org_name!r} does not exist")
        actual_inventory = dict(
            target.execute(
                text(
                    """
                    SELECT extra_data -> 'legacy_source' ->> 'table' AS legacy_table, count(*)
                    FROM inventory_items
                    WHERE org_id = :org_id AND extra_data ->> 'source_system' = 'whistlebird_v1'
                    GROUP BY legacy_table
                    """
                ),
                {"org_id": org_id},
            ).all()
        )
        actual_samples = dict(
            target.execute(
                text(
                    """
                    SELECT execution_data -> 'legacy_source' ->> 'table' AS legacy_table, count(*)
                    FROM execution_steps es
                    JOIN executions e ON e.id = es.execution_id
                    WHERE e.org_id = :org_id AND execution_data ->> 'source_system' = 'whistlebird_v1'
                    GROUP BY legacy_table
                    """
                ),
                {"org_id": org_id},
            ).all()
        )
        inventory_date_mismatches = target.execute(
            text(
                """
                SELECT count(*)
                FROM inventory_items
                WHERE org_id = :org_id
                  AND extra_data ->> 'source_system' = 'whistlebird_v1'
                  AND (created_at AT TIME ZONE 'Pacific/Auckland')::date
                      <> (extra_data ->> 'legacy_date')::date
                """
            ),
            {"org_id": org_id},
        ).scalar_one()
        execution_date_mismatches = target.execute(
            text(
                """
                SELECT count(*)
                FROM execution_steps es
                JOIN executions e ON e.id = es.execution_id
                WHERE e.org_id = :org_id
                  AND execution_data ->> 'source_system' = 'whistlebird_v1'
                  AND (es.completed_at AT TIME ZONE 'Pacific/Auckland')::date
                      <> (execution_data ->> 'legacy_date')::date
                """
            ),
            {"org_id": org_id},
        ).scalar_one()
        actual_lodgements = target.execute(
            text(
                """
                SELECT count(*)
                FROM compliance_records
                WHERE org_id = :org_id
                  AND framework_slug = 'customs-alcohol'
                  AND control_id = 'period-lodgement'
                  AND details ->> 'source_system' = 'whistlebird_v1'
                """
            ),
            {"org_id": org_id},
        ).scalar_one()
    return {
        "inventory": {
            table: {"expected": expected, "actual": actual_inventory.get(table, 0)}
            for table, expected in expected_inventory.items()
        },
        "samples": {
            table: {"expected": expected, "actual": actual_samples.get(table, 0)}
            for table, expected in expected_samples.items()
        },
        "customs_lodgements": {"expected": expected_lodgements, "actual": actual_lodgements},
        "date_mismatches": {"inventory": inventory_date_mismatches, "execution_steps": execution_date_mismatches},
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--legacy-url",
        default=os.environ.get("WB_LEGACY_DATABASE_URL"),
        help="Legacy SQLAlchemy URL (or set WB_LEGACY_DATABASE_URL).",
    )
    parser.add_argument(
        "--target-url",
        default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"),
        help="Target SQLAlchemy URL (or set BIZE_MIGRATION_DATABASE_URL).",
    )
    parser.add_argument("--org-name", default="whistlebird_test", help="Requested migration tenant name.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path; stdout is always written.")
    parser.add_argument(
        "--confirm-reset-whistlebird-test",
        action="store_true",
        help="Delete imported data only for the whistlebird_test tenant; preserves its users.",
    )
    parser.add_argument(
        "--dry-run-core",
        action="store_true",
        help="Validate the deterministic GNS, packaging, ingredient and Customs source tranche without writing.",
    )
    parser.add_argument(
        "--dry-run-traceability",
        action="store_true",
        help="Measure database-evidenced production and sales links without writing.",
    )
    parser.add_argument(
        "--dry-run-production",
        action="store_true",
        help="Validate the evidence-backed flavour, vat and bottling production tranche without writing.",
    )
    parser.add_argument(
        "--setup-historical-templates",
        action="store_true",
        help="Create approved historical process templates only for whistlebird_test.",
    )
    parser.add_argument(
        "--apply-core-receipts-and-lodgements",
        action="store_true",
        help="Import deterministic v1 purchases and Customs rows only into whistlebird_test.",
    )
    parser.add_argument(
        "--apply-evidenced-production",
        action="store_true",
        help="Import only source-evidenced v1 flavour, vat and bottling executions into whistlebird_test.",
    )
    parser.add_argument(
        "--apply-sample-history",
        action="store_true",
        help="Import v1 sample records as historical executions only into whistlebird_test.",
    )
    parser.add_argument(
        "--verify-import",
        action="store_true",
        help="Compare source and target Whistlebird import counts and dates without writing.",
    )
    arguments = parser.parse_args()
    if not arguments.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    if (
        not (
            arguments.confirm_reset_whistlebird_test
            or arguments.setup_historical_templates
            or arguments.apply_core_receipts_and_lodgements
            or arguments.apply_evidenced_production
            or arguments.apply_sample_history
            or arguments.verify_import
        )
        and not arguments.legacy_url
    ):
        parser.error("--legacy-url is required unless performing the scoped reset")
    return arguments


def main() -> int:
    arguments = _arguments()
    if arguments.confirm_reset_whistlebird_test:
        report = reset_target_org(arguments.target_url, arguments.org_name)
    elif arguments.setup_historical_templates:
        report = setup_historical_process_templates(arguments.target_url, arguments.org_name)
    elif arguments.apply_core_receipts_and_lodgements:
        report = apply_core_receipts_and_lodgements(arguments.legacy_url, arguments.target_url, arguments.org_name)
    elif arguments.apply_evidenced_production:
        report = apply_evidenced_production(arguments.legacy_url, arguments.target_url, arguments.org_name)
    elif arguments.apply_sample_history:
        report = apply_sample_history(arguments.legacy_url, arguments.target_url, arguments.org_name)
    elif arguments.verify_import:
        report = build_import_verification(arguments.legacy_url, arguments.target_url, arguments.org_name)
    elif arguments.dry_run_core:
        report = build_core_dry_run(arguments.legacy_url)
    elif arguments.dry_run_traceability:
        report = build_traceability_dry_run(arguments.legacy_url)
    elif arguments.dry_run_production:
        report = build_production_dry_run(arguments.legacy_url)
    else:
        report = build_profile(arguments.legacy_url, arguments.target_url, arguments.org_name)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
