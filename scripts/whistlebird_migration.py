#!/usr/bin/env python3
"""Guarded, reproducible tooling that loads Whistlebird's production history into Biz-E.

The default/profile and dry-run actions are read-only and produce aggregate-only reports:
no contacts, email addresses, free-text notes, product names, or credentials are emitted.
Every write action is restricted to the exact disposable ``whistlebird_test`` tenant. The
rebuild action preflights, replays, and verifies the complete reviewed load in one command.

The load models production the way it actually happens: one workflow per product
(Wildflower gin, Solstice gin, Rosella gin) plus recipe-trial workflows, and one
execution per VAT batch that walks the real steps -- maceration, distilling, aging in
the VAT, bottling, labelling & packaging -- with every step stamped with its own real
date drawn from the source records. Raw-material purchases become dated inventory,
Customs lodgements become NZ-alcohol compliance records, and a small machine-only
``import_ref`` marker on each written row keeps a scoped reset-and-replay exact.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
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
DEFAULT_TEST_ADMIN_EMAIL = "whistlebird_test_admin@whistlebird.test"
WHISTLEBIRD_TEST_ADMIN_KEEPASS_ENTRY = "workflow-engine/whistlebird_test"
DEFAULT_PRODUCTION_MANIFEST = Path(__file__).parents[1] / "docs" / "whistlebird-production-sheet-source.json"
WHISTLEBIRD_NZ_ALCOHOL_SETTINGS = {
    "alcohol_product_types": ["spirits"],
    "require_core_source_refs": True,
    "trade_waste_required": False,
}
DERIVED_TIMEZONE = ZoneInfo("Pacific/Auckland")
DERIVED_TIME = time(hour=12)


# Step-1 (maceration) input lists: what each product's charge is built from, so the
# process definition itself documents the recipe and drives inventory-selection prompts
# at execution time -- the mechanism that lets a bottled product trace back to its source
# botanical purchases. Quantities are the founder-confirmed per-shot recipe (2026-09-14/
# -16), doubled per batch (two concentrate shots per VAT) -- see docs/whistlebird-raw-
# material-source.json's recipe_wildflower_per_shot_g/recipe_solstice_per_shot_g and
# docs/whistlebird-import-decisions.md "Stage 4". NGS/water are the flask-charge amounts
# from scripts/whistlebird_replay_timeline.py's _flask_ngs_and_water_l() (identical for
# both product lines; the larger VAT-fill dilution happens at a later step, not here) --
# duplicated here rather than imported to avoid a circular import between the two
# scripts; keep in sync if the founder revises the recipe.
# requires_inventory_selection=False marks fresh/foraged ingredients the distillery has
# never purchased as tracked inventory (per the founder, 2026-09-14) -- listed for a
# complete recipe, but with nothing to select at execution time.
def _tracked_input(name: str, quantity: str | None, unit: str) -> dict[str, Any]:
    return {"name": name, "quantity": quantity, "unit": unit, "requires_inventory_selection": True}


def _untracked_input(name: str, quantity: str | None, unit: str) -> dict[str, Any]:
    return {"name": name, "quantity": quantity, "unit": unit, "requires_inventory_selection": False}


_FLASK_NGS_INPUT = _tracked_input("Neutral grain spirit", "0.746", "L")
_FLASK_WATER_INPUT = _untracked_input("Water", "2.854", "L")
_WILDFLOWER_MACERATION_INPUTS = (
    _tracked_input("Juniper Berries (Macedonian)", "59.4", "g"),
    _tracked_input("Juniper Berries (Himalayan)", "48.6", "g"),
    _tracked_input("Orris root", "30.6", "g"),
    _tracked_input("Coriander seeds", "43.2", "g"),
    _tracked_input("Whole nutmeg (organic)", "11", "g"),
    _tracked_input("Orange peel - dried", "14.4", "g"),
    _tracked_input("Hibiscus flowers", "18", "g"),
    _tracked_input("Liquorice root", "5.4", "g"),
    _tracked_input("Cardamom pods", "43.2", "g"),
    _tracked_input("Persian black lime", "21.6", "g"),
    _tracked_input("Sumac berries - ground", "7.2", "g"),
    _tracked_input("Lemon myrtle", "14", "g"),
    _tracked_input("Dried mango slices", "18", "g"),
    _tracked_input("Dried apple ring", "36", "g"),
    _tracked_input("Elderflower", "18", "g"),
    _tracked_input("Green tea", "4", "bags"),
    _FLASK_NGS_INPUT,
    _FLASK_WATER_INPUT,
    _untracked_input("Lemon juice", "34", "mL"),
    _untracked_input("Grapefruit (pink) juice", "54", "mL"),
    _untracked_input("Lemon peel", "3.0", "g"),
)
_SOLSTICE_MACERATION_INPUTS = (
    _tracked_input("Juniper Berries (Macedonian)", "226.8", "g"),
    _tracked_input("Juniper Berries (Himalayan)", "97.2", "g"),
    _tracked_input("Whole nutmeg (organic)", "21.6", "g"),
    _tracked_input("Cinnamon", "5.76", "g"),
    _tracked_input("Liquorice root", "21.6", "g"),
    _tracked_input("Szechuan pepper", "3.6", "g"),
    _FLASK_NGS_INPUT,
    _FLASK_WATER_INPUT,
    _untracked_input("Kawakawa leaf", "8", "g"),
    _untracked_input("Orange peel", "5.0", "g"),
    _untracked_input("Orange juice", "108", "mL"),
)
# The rhubarb-maceration step consumes a whole aged Solstice VAT batch (an
# inventory-selectable work-in-progress item, no fixed quantity -- see
# docs/whistlebird-production-import-field-mapping.md's rosella_base_vat) plus rhubarb,
# which -- like the other product lines' foraged ingredients -- the distillery has never
# purchased as tracked inventory.
_ROSELLA_MACERATION_INPUTS = (
    _tracked_input("VAT batch", None, "L"),
    _untracked_input("Rhubarb", None, "kg"),
)


# Step outputs feeding the NEXT step as an input (2026-09-18 founder request): the
# process template itself should show the DAG a bottle actually travels through, not
# just Maceration's raw-material inputs. A "previous_output" input can't carry a real
# source_output_id in this static tuple -- that UUID only exists once the step that owns
# it has actually been created -- so this is a resolution marker setup_product_workflows()
# expands into the real {name, source_output_id, ...} shape once it knows the preceding
# step's freshly-created (or already-existing) output. Quantity is a fixed default only
# where the founder's recipe fixes it (maceration/distilling); Aging's and Bottling's own
# outputs genuinely vary per VAT/batch, so those consuming inputs default to None, same
# as _ROSELLA_MACERATION_INPUTS's "VAT batch" above.
def _previous_step_output_input(quantity: str | None, unit: str) -> dict[str, Any]:
    return {
        "quantity": quantity,
        "unit": unit,
        "requires_inventory_selection": True,
        "_wire_previous_output": True,
    }


# Maceration produces two 1.8L, 20% ABV flasks (3.6L total); distilling collects 1.08L
# of concentrate per flask (2.16L total) -- both fixed by the founder's recipe (see
# whistlebird_replay_timeline._flask_ngs_and_water_l), identical for Wildflower/Solstice.
_MACERATION_OUTPUT_NAME = "Maceration charge (2 x 1.8L, 20% ABV)"
_MACERATION_OUTPUT_UNIT = "L"
_MACERATION_OUTPUT_QUANTITY = "3.6"
_DISTILLATE_OUTPUT_NAME = "Gin concentrate"
_DISTILLATE_OUTPUT_UNIT = "L"
_DISTILLATE_OUTPUT_QUANTITY = "2.16"

# Aging's VAT-fill dilution -- founder recipe (2026-09-16), duplicated from
# whistlebird_replay_timeline._vat_fill_ngs_and_water_l for the same reason the flask
# NGS/water constants above are duplicated (avoiding a circular import).
_WILDFLOWER_FILL_NGS_INPUT = _tracked_input("Neutral grain spirit", "25.326", "L")
_WILDFLOWER_FILL_WATER_INPUT = _untracked_input("Water", "30.787", "L")
_SOLSTICE_FILL_NGS_INPUT = _tracked_input("Neutral grain spirit", "17.776", "L")
_SOLSTICE_FILL_WATER_INPUT = _untracked_input("Water", "25.064", "L")

# Custom execution prompts (2026-09-18 founder request).
_VAT_NUMBER_PROMPT = {"label": "VAT number", "type": "number", "unit": None, "required": True}
_FLASK_CODE_PROMPT = {"label": "Flask code", "type": "text", "unit": None, "required": True}

# One workflow per product. Each production batch (one VAT) is a single execution that
# walks these steps in order, every step stamped with its own real date. Steps are
# (name, description, output_name, output_unit, inputs, execution_prompts); an empty
# output_name means the step records what happened but creates no inventory item of its
# own. Each step (2026-09-18 onward) declares its own output and, from Distilling
# onward, an input wired to the immediately preceding step's output -- see
# _previous_step_output_input -- so the process template shows the real DAG a bottle
# travels through, not just Maceration's raw-material charge.
_WILDFLOWER_STEPS = (
    (
        "Maceration",
        "Prep and steep the botanical charge",
        _MACERATION_OUTPUT_NAME,
        _MACERATION_OUTPUT_UNIT,
        _WILDFLOWER_MACERATION_INPUTS,
        (),
    ),
    (
        "Distilling",
        "Distil the macerated charge to flavour spirit",
        _DISTILLATE_OUTPUT_NAME,
        _DISTILLATE_OUTPUT_UNIT,
        (_previous_step_output_input(_MACERATION_OUTPUT_QUANTITY, _MACERATION_OUTPUT_UNIT),),
        (_FLASK_CODE_PROMPT,),
    ),
    (
        "Aging",
        "Fill the VAT and let the batch rest to strength",
        "Aged Gin",
        "L",
        (
            _previous_step_output_input(_DISTILLATE_OUTPUT_QUANTITY, _DISTILLATE_OUTPUT_UNIT),
            _WILDFLOWER_FILL_NGS_INPUT,
            _WILDFLOWER_FILL_WATER_INPUT,
        ),
        (_VAT_NUMBER_PROMPT,),
    ),
    (
        "Bottling",
        "Bottle the rested VAT batch",
        "Bottled product",
        "units",
        (_previous_step_output_input(None, "L"),),
        (),
    ),
    (
        "Labelling & packaging",
        "Heat-shrink, label and case the bottles",
        "Wildflower - final product",
        "units",
        (_previous_step_output_input(None, "units"),),
        (),
    ),
)
_SOLSTICE_STEPS = (
    (
        "Maceration",
        "Prep and steep the botanical charge",
        _MACERATION_OUTPUT_NAME,
        _MACERATION_OUTPUT_UNIT,
        _SOLSTICE_MACERATION_INPUTS,
        (),
    ),
    (
        "Distilling",
        "Distil the macerated charge to flavour spirit",
        _DISTILLATE_OUTPUT_NAME,
        _DISTILLATE_OUTPUT_UNIT,
        (_previous_step_output_input(_MACERATION_OUTPUT_QUANTITY, _MACERATION_OUTPUT_UNIT),),
        (_FLASK_CODE_PROMPT,),
    ),
    (
        "Aging",
        "Fill the VAT and let the batch rest to strength",
        "Aged Gin",
        "L",
        (
            _previous_step_output_input(_DISTILLATE_OUTPUT_QUANTITY, _DISTILLATE_OUTPUT_UNIT),
            _SOLSTICE_FILL_NGS_INPUT,
            _SOLSTICE_FILL_WATER_INPUT,
        ),
        (_VAT_NUMBER_PROMPT,),
    ),
    (
        "Bottling",
        "Bottle the rested VAT batch",
        "Bottled product",
        "units",
        (_previous_step_output_input(None, "L"),),
        (),
    ),
    (
        "Labelling & packaging",
        "Heat-shrink, label and case the bottles",
        "Solstice - final product",
        "units",
        (_previous_step_output_input(None, "units"),),
        (),
    ),
)
_RHUBARB_GIN_STEPS = (
    (
        "Rhubarb maceration",
        "Steep an aged base VAT batch on rhubarb",
        "VAT batch",
        "L",
        _ROSELLA_MACERATION_INPUTS,
        (),
    ),
    ("Aging", "Let the rhubarb batch rest before bottling", "", "", (), ()),
    ("Bottling", "Bottle the rested batch", "Bottled product", "units", (), ()),
    ("Labelling & packaging", "Heat-shrink, label and case the bottles", "", "", (), ()),
)
_TRIAL_STEPS = (
    ("Distilling", "Distil a trial recipe", "", "", (), ()),
    ("Library stock", "Store the trial spirit as library stock", "Library stock", "mL", (), ()),
)
WILDFLOWER_WORKFLOW = "Wildflower gin"
SOLSTICE_WORKFLOW = "Solstice gin"
ROSELLA_WORKFLOW = "Rosella gin"
GG_TRIAL_WORKFLOW = "GG gin trials"
WB_TRIAL_WORKFLOW = "WB recipe trials"
SGS_TRIAL_WORKFLOW = "SGS spirit trials"
PRODUCT_WORKFLOWS: dict[str, tuple[str, tuple[tuple[str, str, str, str, tuple, tuple], ...]]] = {
    WILDFLOWER_WORKFLOW: ("botanical_gin", _WILDFLOWER_STEPS),
    SOLSTICE_WORKFLOW: ("botanical_gin", _SOLSTICE_STEPS),
    ROSELLA_WORKFLOW: ("rhubarb_gin", _RHUBARB_GIN_STEPS),
    GG_TRIAL_WORKFLOW: ("trial", _TRIAL_STEPS),
    WB_TRIAL_WORKFLOW: ("trial", _TRIAL_STEPS),
    SGS_TRIAL_WORKFLOW: ("trial", _TRIAL_STEPS),
}
PRODUCT_LINE_WORKFLOW = {
    "wildflower": WILDFLOWER_WORKFLOW,
    "solstice": SOLSTICE_WORKFLOW,
    "rosella": ROSELLA_WORKFLOW,
}
# Ordered step keys per workflow shape, used to line manifest/legacy dates up with steps.
BOTANICAL_GIN_STEP_KEYS = ("maceration", "distilling", "aging", "bottling", "labelling")
RHUBARB_GIN_STEP_KEYS = ("rhubarb_maceration", "aging", "bottling", "labelling")
TRIAL_STEP_KEYS = ("distilling", "library_stock")

IMPORT_MARKER_KEY = "import_ref"
BATCH_MARKER_KEY = "batch_ref"
PRODUCTION_SOURCE_TABLE = "production_sheet"
STEP_DATE_CONFIDENCE = ("clean", "resolved_by_context", "derived")


@dataclass(frozen=True)
class ProposedCoreRecord:
    """Validated candidate row for a dry run; never rendered with source business data."""

    source_table: str
    source_id: int
    source_date: date
    target_kind: str
    quantity: Decimal | None
    unit: str | None
    derived_at: datetime


@dataclass(frozen=True)
class RawMaterialRecord:
    """A source purchase row that becomes one dated raw-material inventory item."""

    source_table: str
    source_id: int
    source_date: date
    name: str
    quantity: Decimal
    unit: str
    supplier: str | None
    supplier_batch_number: str | None
    expiry_date: date | None
    extra_data: dict[str, Any]


@dataclass(frozen=True)
class BatchStep:
    """One step of a production batch with its resolved real date and how sure we are."""

    key: str
    step_date: date | None
    confidence: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProductionBatch:
    """One VAT batch -- a single multi-step execution of its product workflow."""

    global_vat: int
    product_line: str
    batch_label: str
    steps: dict[str, BatchStep]
    vat_volume_l: Decimal | None
    vat_abv: Decimal | None
    bottlings: tuple[dict[str, Any], ...]
    ingredient_codes: tuple[str, ...]
    base_vat: int | None
    extra_data: dict[str, Any]

    @property
    def workflow_name(self) -> str:
        return PRODUCT_LINE_WORKFLOW[self.product_line]

    @property
    def marker(self) -> str:
        return f"{self.product_line}-vat{self.global_vat}"


@dataclass(frozen=True)
class TrialRecord:
    """One recipe/distillation trial -- a distilling step feeding library stock."""

    workflow_name: str
    source_table: str
    source_id: int
    source_date: date
    label: str
    distillate_ml: Decimal | None
    library_ml: Decimal | None
    consumed: tuple[dict[str, Any], ...]
    extra_data: dict[str, Any]

    @property
    def marker(self) -> str:
        return f"trial-{self.source_table}-{self.source_id}"


def _identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def _enter_target_tenant_scope(stack: ExitStack, session: Any, requested_org_name: str) -> Any:
    """Activate the exact target tenant for standalone ORM work.

    The load has no Flask request, so it must establish the same ContextVar-backed scope
    that request middleware normally provides. The organisation lookup intentionally runs
    under the explicit ``unscoped`` escape hatch: it is the one pre-scope lookup needed to
    discover the scope, and the requested name has already been approved by the caller's
    safety policy. Every subsequent ORM statement runs under that exact org id.
    """
    from app.core.db.models.organisation import Organisation
    from app.core.security.tenant_scope import tenant_scope, unscoped

    with unscoped():
        org = session.query(Organisation).filter(Organisation.name == requested_org_name).one_or_none()
    if org is None:
        raise ValueError(f"Target organisation {requested_org_name!r} does not exist")
    stack.enter_context(tenant_scope(org.id))
    return org


def _json_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _derived_timestamp(source_date: date) -> datetime:
    """Convert a date-only source value using the agreed, explicitly-derived convention."""
    return datetime.combine(source_date, DERIVED_TIME, tzinfo=DERIVED_TIMEZONE).astimezone(UTC)


def _decimal(value: Any, field_name: str, source_table: str, source_id: int) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{source_table}#{source_id} has invalid {field_name}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{source_table}#{source_id} has invalid {field_name}")
    return parsed.quantize(Decimal("0.0001"))


def _optional_decimal(value: Any, field_name: str, source_table: str, source_id: int) -> Decimal | None:
    if value is None or str(value).strip() in ("", "None"):
        return None
    return _decimal(value, field_name, source_table, source_id)


def _required_date(value: Any, source_table: str, source_id: int) -> date:
    if not isinstance(value, date):
        raise ValueError(f"{source_table}#{source_id} has no valid source date")
    return value


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _decimal_label(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _legacy_list(value: Any) -> tuple[str, ...]:
    """Parse the source system's brace-wrapped text lists without inferring their contents."""
    raw = _optional_text(value)
    if raw is None:
        return ()
    return tuple(entry for entry in (part.strip().strip('"') for part in raw.strip("{}").split(",")) if entry)


def _import_marker(marker: str, source_table: str, source_id: Any, *, step: str | None = None) -> dict[str, Any]:
    """The machine-only marker written into every produced row for idempotent replay.

    Deliberately carries no "legacy"/"historical" wording: the loaded data is treated as
    live production history. ``import_ref`` is unique per row; ``batch_ref`` groups a
    batch's steps so a scoped reset-and-replay can find and skip what already exists.
    """
    payload: dict[str, Any] = {
        IMPORT_MARKER_KEY: f"{marker}:{step}" if step else marker,
        BATCH_MARKER_KEY: marker,
        "source_ref": {"table": source_table, "id": source_id},
        "timestamp_policy": "derived_noon_pacific_auckland",
    }
    if step:
        payload["step"] = step
    return payload


def _monotonic_step_dates(raw_dates: list[date | None]) -> tuple[list[date], list[bool]]:
    """Fill gaps and clamp a step-date sequence so it never goes backwards.

    ``complete_step`` refuses to close a step while an earlier one is open, so the step
    timestamps must be non-decreasing. A ``None`` (no source event) inherits the nearest
    recorded step's date -- the previous step's, or, for leading gaps, the first recorded
    step ahead of it; a date earlier than the previous step is pulled forward. Every
    inherited or pulled-forward value is flagged so the execution data records that the
    date was derived, not recorded.
    """
    if not raw_dates or all(d is None for d in raw_dates):
        raise ValueError("a batch must have at least one real source date")
    first_real = next(d for d in raw_dates if d is not None)
    resolved: list[date] = []
    adjusted: list[bool] = []
    for raw in raw_dates:
        if raw is None:
            resolved.append(resolved[-1] if resolved else first_real)
            adjusted.append(True)
            continue
        if resolved and raw < resolved[-1]:
            resolved.append(resolved[-1])
            adjusted.append(True)
            continue
        resolved.append(raw)
        adjusted.append(False)
    return resolved, adjusted


# --------------------------------------------------------------------------------------
# Source readers (prior inventory database)
# --------------------------------------------------------------------------------------


def _raw_material_records(connection: Connection) -> Iterator[RawMaterialRecord]:
    for row in connection.execute(
        text("SELECT id, date, supplier, gns_purchased_l, abv FROM purchases_gns ORDER BY id")
    ).mappings():
        source_id = row["id"]
        source_date = _required_date(row["date"], "purchases_gns", source_id)
        yield RawMaterialRecord(
            source_table="purchases_gns",
            source_id=source_id,
            source_date=source_date,
            name="Neutral grain spirit",
            quantity=_decimal(row["gns_purchased_l"], "gns_purchased_l", "purchases_gns", source_id),
            unit="L",
            supplier=_optional_text(row["supplier"]),
            supplier_batch_number=f"GNS-{source_date.isoformat()}-{source_id}",
            expiry_date=None,
            extra_data={"gns_abv_percent": str(row["abv"] or "")},
        )

    for row in connection.execute(
        text("SELECT id, date, supplier, bottle_size_ml, empty_bottles_stored FROM purchases_empty_bottles ORDER BY id")
    ).mappings():
        source_id = row["id"]
        source_date = _required_date(row["date"], "purchases_empty_bottles", source_id)
        bottle_size = _decimal(row["bottle_size_ml"], "bottle_size_ml", "purchases_empty_bottles", source_id)
        yield RawMaterialRecord(
            source_table="purchases_empty_bottles",
            source_id=source_id,
            source_date=source_date,
            name=f"Empty bottles ({_decimal_label(bottle_size)} mL)",
            quantity=_decimal(
                row["empty_bottles_stored"], "empty_bottles_stored", "purchases_empty_bottles", source_id
            ),
            unit="units",
            supplier=_optional_text(row["supplier"]),
            supplier_batch_number=f"BOTTLES-{source_date.isoformat()}-{source_id}",
            expiry_date=None,
            extra_data={"bottle_size_ml": str(bottle_size)},
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
        source_id = row["id"]
        source_date = _required_date(row["date"], "purchases_ingredients", source_id)
        ingredient_name = _optional_text(row["ingredients"])
        if ingredient_name is None:
            raise ValueError(f"purchases_ingredients#{source_id} has no ingredient name")
        expiry_date = row["ingredients_expiry"]
        if expiry_date is not None and not isinstance(expiry_date, date):
            raise ValueError(f"purchases_ingredients#{source_id} has invalid ingredients_expiry")
        yield RawMaterialRecord(
            source_table="purchases_ingredients",
            source_id=source_id,
            source_date=source_date,
            name=ingredient_name,
            quantity=_decimal(row["ingredients_amount"], "ingredients_amount", "purchases_ingredients", source_id),
            unit="g",
            supplier=_optional_text(row["supplier"]),
            supplier_batch_number=_optional_text(row["ingredients_code"])
            or f"ING-{source_date.isoformat()}-{source_id}",
            expiry_date=expiry_date,
            extra_data={"ingredient_code": _optional_text(row["ingredients_code"]) or ""},
        )

    for row in connection.execute(
        text(
            "SELECT id, date, notes, alcohol_volume, alcohol_abv, lal, container_id "
            "FROM product_actions_create_premix ORDER BY id"
        )
    ).mappings():
        source_id = row["id"]
        source_date = _required_date(row["date"], "product_actions_create_premix", source_id)
        yield RawMaterialRecord(
            source_table="product_actions_create_premix",
            source_id=source_id,
            source_date=source_date,
            name="Premix dilution solution",
            quantity=_decimal(row["alcohol_volume"], "alcohol_volume", "product_actions_create_premix", source_id),
            unit="L",
            supplier=None,
            supplier_batch_number=f"PREMIX-{_optional_text(row['container_id']) or source_id}",
            expiry_date=None,
            extra_data={
                "container_id": _optional_text(row["container_id"]) or "",
                "abv_percent": str(row["alcohol_abv"] or ""),
                "litres_of_alcohol": str(row["lal"] or ""),
            },
        )


def _disambiguate_reused_supplier_batches(records: list[RawMaterialRecord]) -> list[RawMaterialRecord]:
    """Respect Biz-E's name/batch uniqueness while retaining every purchase row."""
    batch_keys = Counter((record.name, record.supplier_batch_number) for record in records)
    disambiguated: list[RawMaterialRecord] = []
    for record in records:
        key = (record.name, record.supplier_batch_number)
        if record.supplier_batch_number is None or batch_keys[key] == 1:
            disambiguated.append(record)
            continue
        original_batch = record.supplier_batch_number
        suffix = f" (lot {record.source_id})"
        disambiguated.append(
            replace(
                record,
                supplier_batch_number=f"{original_batch[: 255 - len(suffix)]}{suffix}",
                extra_data={
                    **record.extra_data,
                    "recorded_supplier_batch_number": original_batch,
                    "supplier_batch_number_disambiguated": True,
                },
            )
        )
    return disambiguated


def _customs_lodgement_rows(connection: Connection) -> list[dict[str, Any]]:
    return list(
        connection.execute(
            text(
                """
                SELECT id, date, date_period, lodged_volume, lodged_abv, lal, bottles
                FROM customs_lodgements
                ORDER BY id
                """
            )
        ).mappings()
    )


def _legacy_batches(connection: Connection) -> dict[int, ProductionBatch]:
    """Assemble one ProductionBatch per VAT from the prior database's flavour/vat/bottling rows."""
    flavour_dates: dict[str, list[date]] = defaultdict(list)
    flavour_codes_seen: dict[str, str] = {}
    flavour_ingredients: dict[str, list[str]] = defaultdict(list)
    for row in connection.execute(
        text("SELECT id, date, flavor_code, flavor_batch, ingredient_codes FROM product_actions_flavors ORDER BY id")
    ).mappings():
        fb = _optional_text(row["flavor_batch"])
        if not fb:
            continue
        flavour_dates[fb].append(_required_date(row["date"], "product_actions_flavors", row["id"]))
        code = _optional_text(row["flavor_code"])
        if code:
            flavour_codes_seen[fb] = code
        flavour_ingredients[fb].extend(_legacy_list(row["ingredient_codes"]))

    bottlings: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute(
        text(
            """
            SELECT id, date, bottles_stored, abv, bottle_size_ml, vat_batch, bottle_batch
            FROM product_actions_bottling
            ORDER BY date, id
            """
        )
    ).mappings():
        vb = _optional_text(row["vat_batch"])
        if not vb:
            continue
        bottlings[vb].append(
            {
                "date": _required_date(row["date"], "product_actions_bottling", row["id"]).isoformat(),
                "bottles": str(
                    _decimal(row["bottles_stored"], "bottles_stored", "product_actions_bottling", row["id"])
                ),
                "bottle_size_ml": str(
                    _decimal(row["bottle_size_ml"], "bottle_size_ml", "product_actions_bottling", row["id"])
                ),
                "abv_percent": str(_decimal(row["abv"], "abv", "product_actions_bottling", row["id"])),
                "bottle_batch": _optional_text(row["bottle_batch"]),
                "source_ref": {"table": "product_actions_bottling", "id": row["id"]},
            }
        )

    batches: dict[int, ProductionBatch] = {}
    for row in connection.execute(
        text("SELECT id, date, abv, vat_batch, volume_amount, flavor_batch FROM product_actions_flavor_vat ORDER BY id")
    ).mappings():
        vat_id = row["id"]
        vat_batch = _optional_text(row["vat_batch"]) or f"VAT{vat_id}"
        fill_date = _required_date(row["date"], "product_actions_flavor_vat", vat_id)
        flavour_batches = _legacy_list(row["flavor_batch"])
        mac_dates = [d for fb in flavour_batches for d in flavour_dates.get(fb, [])]
        maceration = min(mac_dates) if mac_dates else fill_date
        distilling = max(mac_dates) if mac_dates else fill_date
        codes = sorted({c for fb in flavour_batches for c in flavour_ingredients.get(fb, [])})
        product_line = "rosella" if vat_batch.upper().startswith("WBRS") else "wildflower"
        bots = bottlings.get(vat_batch, [])
        first_bottle = date.fromisoformat(bots[0]["date"]) if bots else None
        last_bottle = date.fromisoformat(bots[-1]["date"]) if bots else None
        if product_line == "rosella":
            step_dates = {
                "rhubarb_maceration": BatchStep("rhubarb_maceration", maceration, "resolved_by_context"),
                "aging": BatchStep("aging", fill_date, "clean"),
                "bottling": BatchStep("bottling", first_bottle, "clean" if first_bottle else "derived"),
                "labelling": BatchStep("labelling", last_bottle, "derived"),
            }
        else:
            step_dates = {
                "maceration": BatchStep("maceration", maceration, "clean" if mac_dates else "derived"),
                "distilling": BatchStep("distilling", distilling, "clean" if mac_dates else "derived"),
                "aging": BatchStep("aging", fill_date, "clean"),
                "bottling": BatchStep("bottling", first_bottle, "clean" if first_bottle else "derived"),
                "labelling": BatchStep("labelling", last_bottle, "derived"),
            }
        batches[vat_id] = ProductionBatch(
            global_vat=vat_id,
            product_line=product_line,
            batch_label=vat_batch,
            steps=step_dates,
            vat_volume_l=_optional_decimal(row["volume_amount"], "volume_amount", "product_actions_flavor_vat", vat_id),
            vat_abv=_optional_decimal(row["abv"], "abv", "product_actions_flavor_vat", vat_id),
            bottlings=tuple(bots),
            ingredient_codes=tuple(codes),
            base_vat=None,
            extra_data={
                "flavour_batches": list(flavour_batches),
                "recipe_code": flavour_codes_seen.get(flavour_batches[0]) if flavour_batches else None,
            },
        )
    return batches


def _trial_records(connection: Connection) -> Iterator[TrialRecord]:
    consumed_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute(
        text(
            "SELECT id, date, flavor_code, number_of_bottles, abv, bottle_size_ml "
            "FROM product_actions_samples_consumed ORDER BY id"
        )
    ).mappings():
        code = _optional_text(row["flavor_code"]) or ""
        consumed_by_code[code].append(
            {
                "date": _required_date(row["date"], "product_actions_samples_consumed", row["id"]).isoformat(),
                "bottles": str(row["number_of_bottles"] or ""),
                "abv_percent": str(row["abv"] or ""),
                "bottle_size_ml": str(row["bottle_size_ml"] or ""),
                "source_ref": {"table": "product_actions_samples_consumed", "id": row["id"]},
            }
        )

    for row in connection.execute(
        text(
            "SELECT id, date, flavor_code, flavor_stored_ml, clearing_amount, clearing_abv "
            "FROM product_actions_flavor_experiments ORDER BY id"
        )
    ).mappings():
        source_id = row["id"]
        code = _optional_text(row["flavor_code"]) or f"experiment-{source_id}"
        workflow = GG_TRIAL_WORKFLOW if code.upper().startswith("GG") else WB_TRIAL_WORKFLOW
        yield TrialRecord(
            workflow_name=workflow,
            source_table="product_actions_flavor_experiments",
            source_id=source_id,
            source_date=_required_date(row["date"], "product_actions_flavor_experiments", source_id),
            label=code,
            distillate_ml=_optional_decimal(
                row["clearing_amount"], "clearing_amount", "product_actions_flavor_experiments", source_id
            ),
            library_ml=_optional_decimal(
                row["flavor_stored_ml"], "flavor_stored_ml", "product_actions_flavor_experiments", source_id
            ),
            consumed=tuple(consumed_by_code.get(code, [])),
            extra_data={"recipe_code": code, "clearing_abv_percent": str(row["clearing_abv"] or "")},
        )

    for row in connection.execute(
        text(
            "SELECT id, date, experiment_id, alcohol_yield_l, alcohol_yield_abv, alcohol_used_l, lal, notes "
            "FROM product_actions_distillation_experiments ORDER BY id"
        )
    ).mappings():
        source_id = row["id"]
        label = _optional_text(row["experiment_id"]) or f"X{source_id}"
        yield_l = _optional_decimal(
            row["alcohol_yield_l"], "alcohol_yield_l", "product_actions_distillation_experiments", source_id
        )
        library_ml = (yield_l * Decimal(1000)) if yield_l is not None else None
        yield TrialRecord(
            workflow_name=SGS_TRIAL_WORKFLOW,
            source_table="product_actions_distillation_experiments",
            source_id=source_id,
            source_date=_required_date(row["date"], "product_actions_distillation_experiments", source_id),
            label=label,
            distillate_ml=library_ml,
            library_ml=library_ml,
            consumed=(),
            extra_data={
                "experiment_id": label,
                "yield_abv_percent": str(row["alcohol_yield_abv"] or ""),
                "alcohol_used_l": str(row["alcohol_used_l"] or ""),
                "litres_of_alcohol": str(row["lal"] or ""),
            },
        )

    for row in connection.execute(
        text(
            "SELECT id, date, flavor_code, number_of_bottles, abv, bottle_size_ml "
            "FROM product_actions_samples_created ORDER BY id"
        )
    ).mappings():
        source_id = row["id"]
        code = _optional_text(row["flavor_code"]) or f"sample-{source_id}"
        bottles = _optional_decimal(
            row["number_of_bottles"], "number_of_bottles", "product_actions_samples_created", source_id
        )
        size = _optional_decimal(row["bottle_size_ml"], "bottle_size_ml", "product_actions_samples_created", source_id)
        library_ml = (bottles * size) if (bottles is not None and size is not None) else None
        yield TrialRecord(
            workflow_name=WB_TRIAL_WORKFLOW,
            source_table="product_actions_samples_created",
            source_id=source_id,
            source_date=_required_date(row["date"], "product_actions_samples_created", source_id),
            label=code,
            distillate_ml=library_ml,
            library_ml=library_ml,
            consumed=tuple(consumed_by_code.get(code, [])),
            extra_data={"recipe_code": code, "abv_percent": str(row["abv"] or ""), "sample_batch": True},
        )


# --------------------------------------------------------------------------------------
# Curated manifest (post-cutoff batches recorded only in the production sheet)
# --------------------------------------------------------------------------------------


def _load_manifest(manifest_path: Path) -> tuple[list[ProductionBatch], list[dict[str, Any]]]:
    """Load and validate the curated per-batch production manifest.

    This never reads the live Google Sheet: the manifest at ``manifest_path`` is a frozen,
    human-reviewed JSON file that a founder edits directly to correct a date, quantity, or
    link before rerunning. A step whose ``confidence`` is not in STEP_DATE_CONFIDENCE, or a
    batch flagged ``exclude``, is skipped by the apply action and reported by the dry run.
    """
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    batches: list[ProductionBatch] = []
    excluded: list[dict[str, Any]] = list(payload.get("excluded", []))
    for entry in payload.get("records", []):
        label = str(entry.get("batch_label") or entry.get("global_vat"))
        if entry.get("exclude"):
            excluded.append({"batch_label": label, "reason": entry.get("notes", "excluded in manifest")})
            continue
        global_vat = int(entry["global_vat"])
        product_line = entry["product"]
        if product_line not in PRODUCT_LINE_WORKFLOW:
            raise ValueError(f"manifest batch {label} has unknown product {product_line!r}")
        step_keys = RHUBARB_GIN_STEP_KEYS if product_line == "rosella" else BOTANICAL_GIN_STEP_KEYS
        raw_steps = entry.get("steps", {})
        steps: dict[str, BatchStep] = {}
        unresolved: list[str] = []
        for key in step_keys:
            spec = raw_steps.get(key) or {}
            confidence = spec.get("confidence", "derived")
            iso = spec.get("date")
            step_date = date.fromisoformat(iso) if iso else None
            if confidence not in STEP_DATE_CONFIDENCE:
                unresolved.append(key)
            steps[key] = BatchStep(key, step_date, confidence, dict(spec.get("data") or {}))
        if unresolved:
            excluded.append({"batch_label": label, "reason": f"unresolved step dates: {', '.join(unresolved)}"})
            continue
        bottlings = tuple(
            {
                "date": b["date"],
                "bottles": str(_decimal(b["bottles"], "bottles", PRODUCTION_SOURCE_TABLE, global_vat)),
                "estimated": bool(b.get("estimated")),
                "source_ref": {"table": PRODUCTION_SOURCE_TABLE, "id": b.get("sheet_row", global_vat)},
            }
            for b in entry.get("bottlings", [])
        )
        batches.append(
            ProductionBatch(
                global_vat=global_vat,
                product_line=product_line,
                batch_label=label,
                steps=steps,
                vat_volume_l=_optional_decimal(
                    entry.get("vat_volume_l"), "vat_volume_l", PRODUCTION_SOURCE_TABLE, global_vat
                ),
                vat_abv=_optional_decimal(entry.get("vat_abv"), "vat_abv", PRODUCTION_SOURCE_TABLE, global_vat),
                bottlings=bottlings,
                ingredient_codes=(),
                base_vat=entry.get("rosella_base_vat"),
                extra_data={
                    "sheet_rows": entry.get("sheet_rows"),
                    "notes": entry.get("notes"),
                    "from_manifest": True,
                },
            )
        )
    return batches, excluded


def _merge_batches(legacy: dict[int, ProductionBatch], manifest: list[ProductionBatch]) -> list[ProductionBatch]:
    """Overlay manifest batches onto the prior-database batches, keyed by global VAT number.

    A manifest batch for a VAT the prior database already has (e.g. VAT23/24/26, distilled
    in the old system but bottled after the cutoff) fills in only the steps the old data is
    missing -- it never rewrites a step the prior database recorded. A manifest batch for a
    VAT the old system never had (Solstice, VAT27+) is created whole.
    """
    merged: dict[int, ProductionBatch] = dict(legacy)
    for batch in manifest:
        base = merged.get(batch.global_vat)
        if base is None:
            merged[batch.global_vat] = batch
            continue
        steps = dict(base.steps)
        for key, step in batch.steps.items():
            existing = steps.get(key)
            if existing is None or existing.step_date is None:
                steps[key] = step
        merged[batch.global_vat] = replace(
            base,
            steps=steps,
            bottlings=base.bottlings or batch.bottlings,
            vat_volume_l=base.vat_volume_l or batch.vat_volume_l,
            vat_abv=base.vat_abv or batch.vat_abv,
            base_vat=base.base_vat or batch.base_vat,
            extra_data={**base.extra_data, "manifest_continuation": True},
        )
    return [merged[key] for key in sorted(merged)]


# --------------------------------------------------------------------------------------
# Profile / dry-run (read-only)
# --------------------------------------------------------------------------------------


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
    source_timezone = connection.execute(text("SHOW TimeZone")).scalar_one()
    return {"source_timezone": source_timezone, "table_counts": table_counts, "date_ranges": date_ranges}


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


def build_profile(legacy_url: str, target_url: str, requested_org_name: str) -> dict[str, Any]:
    with create_engine(legacy_url).connect() as legacy_connection:
        legacy = _legacy_profile(legacy_connection)
    with create_engine(target_url).connect() as target_connection:
        target = _target_profile(target_connection, requested_org_name)
    return {"legacy": legacy, "target": target}


def build_core_dry_run(legacy_url: str) -> dict[str, Any]:
    """Validate the deterministic raw-material and Customs tranche without writing."""
    proposed: list[ProposedCoreRecord] = []
    customs_lodgements = 0
    with create_engine(legacy_url).connect() as connection:
        for record in _disambiguate_reused_supplier_batches(list(_raw_material_records(connection))):
            proposed.append(
                ProposedCoreRecord(
                    source_table=record.source_table,
                    source_id=record.source_id,
                    source_date=record.source_date,
                    target_kind="raw_material_inventory",
                    quantity=record.quantity,
                    unit=record.unit,
                    derived_at=_derived_timestamp(record.source_date),
                )
            )
        for row in _customs_lodgement_rows(connection):
            _decimal(row["lal"], "lal", "customs_lodgements", row["id"])
            customs_lodgements += 1
    by_source: dict[str, int] = {}
    for record in proposed:
        by_source[record.source_table] = by_source.get(record.source_table, 0) + 1
    return {
        "dry_run": True,
        "timestamp_policy": "derived_noon_pacific_auckland",
        "proposed_raw_material_items": len(proposed),
        "proposed_raw_material_items_by_source": by_source,
        "validated_compliance_records": {"customs_lodgements": customs_lodgements},
        "notes": [
            "No target rows were written.",
            "Ingredient quantities are grams, confirmed from the deployed Whistlebird form.",
            "Raw materials load as dated inventory only -- no workflow or execution.",
        ],
    }


def build_production_dry_run(legacy_url: str, manifest_path: Path | None) -> dict[str, Any]:
    """Report the batch executions the load would build, by product and step, without writing."""
    with create_engine(legacy_url).connect() as connection:
        legacy = _legacy_batches(connection)
        trials = list(_trial_records(connection))
    manifest_batches: list[ProductionBatch] = []
    excluded: list[dict[str, Any]] = []
    if manifest_path and manifest_path.exists():
        manifest_batches, excluded = _load_manifest(manifest_path)
    batches = _merge_batches(legacy, manifest_batches)
    by_workflow = Counter(batch.workflow_name for batch in batches)
    derived_steps = Counter(
        step.key
        for batch in batches
        for step in batch.steps.values()
        if step.confidence == "derived" or step.step_date is None
    )
    return {
        "dry_run": True,
        "proposed_batch_executions": dict(sorted(by_workflow.items())),
        "proposed_trial_executions": dict(sorted(Counter(t.workflow_name for t in trials).items())),
        "steps_with_derived_dates": dict(sorted(derived_steps.items())),
        "excluded_batches": len(excluded),
        "notes": [
            "No target rows were written.",
            "One execution per VAT batch; every step carries its own resolved date.",
            "Steps with a derived date inherit the neighbouring recorded step's date and say so.",
        ],
    }


def build_manifest_dry_run(manifest_path: Path) -> dict[str, Any]:
    batches, excluded = _load_manifest(manifest_path)
    return {
        "dry_run": True,
        "manifest_batches": len(batches),
        "manifest_batches_by_product": dict(sorted(Counter(b.product_line for b in batches).items())),
        "excluded_batches": len(excluded),
        "excluded_reasons": [row.get("reason") for row in excluded],
        "notes": [
            "Aggregate-only report: no batch labels, ingredient names, or quantities are emitted.",
            "Excluded entries need founder confirmation before they can load; see the decisions log.",
        ],
    }


def build_traceability_dry_run(legacy_url: str) -> dict[str, Any]:
    """Measure database-evidenced production/sales linkage without inferring missing edges."""
    with create_engine(legacy_url).connect() as connection:
        metrics = connection.execute(
            text(
                """
                SELECT 'flavour_actions' AS metric, count(*) AS value FROM product_actions_flavors
                UNION ALL SELECT 'flavour_vat_actions', count(*) FROM product_actions_flavor_vat
                UNION ALL SELECT 'bottling_actions', count(*) FROM product_actions_bottling
                UNION ALL SELECT 'bottling_rows_with_flavour_vat_match', count(*)
                FROM product_actions_bottling b
                WHERE EXISTS (
                    SELECT 1 FROM product_actions_flavor_vat f
                    WHERE nullif(trim(b.vat_batch), '') = nullif(trim(f.vat_batch), '')
                )
                UNION ALL SELECT 'sales_rows', count(*) FROM sales_product
                """
            )
        ).all()
    return {"dry_run": True, "metrics": dict(metrics), "notes": ["No rows were written."]}


# --------------------------------------------------------------------------------------
# Writers (scoped to whistlebird_test)
# --------------------------------------------------------------------------------------


def _resolve_step_inputs(inputs: tuple[dict[str, Any], ...], previous_output: dict[str, str] | None) -> list[dict]:
    """Expand any `_previous_step_output_input` marker into the real
    {name, source_output_id, ...} shape the guided-input UI itself would produce for a
    "previous_output"-type input, using the immediately preceding step's own output
    (freshly created or already existing -- the caller resolves that either way)."""
    resolved = []
    for item in inputs:
        if not item.get("_wire_previous_output"):
            resolved.append(dict(item))
            continue
        if previous_output is None:
            raise ValueError("step declares a previous-step-output input but the previous step has no output")
        resolved.append(
            {
                "name": previous_output["name"],
                "source_output_id": previous_output["id"],
                "quantity": item["quantity"],
                "unit": item.get("unit") or previous_output["unit"],
                "requires_inventory_selection": True,
                "is_variable": False,
            }
        )
    return resolved


def setup_product_workflows(target_url: str, requested_org_name: str) -> dict[str, list[str]]:
    """Create one workflow per product plus the recipe-trial workflows, each with its steps.

    Idempotent on three axes: missing steps are added (``repaired``/``created``); an
    already-created step whose stored ``inputs``/``outputs``/``execution_prompts`` is
    empty but the definition above now specifies one gets repaired in place
    (``inputs_repaired``) -- this is how a definition change (e.g. adding the maceration
    recipe, or wiring a step's output into the next step's input) reaches steps a prior
    run of this function already created with those fields empty.
    """
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Workflow setup is only permitted for {RESET_ORG_NAME!r}")

    from app.core.db.models.process import Process, ProcessCategory
    from app.core.db.models.step import Step
    from app.core.db.repositories.process_repo import ProcessRepository

    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    scope = ExitStack()
    created: list[str] = []
    existing: list[str] = []
    repaired: list[str] = []
    inputs_repaired: list[str] = []
    try:
        org = _enter_target_tenant_scope(scope, session, requested_org_name)
        repository = ProcessRepository(session)
        for name, (_shape, steps) in PRODUCT_WORKFLOWS.items():
            process = session.query(Process).filter(Process.org_id == org.id, Process.name == name).one_or_none()
            step_count = 0
            existing_steps: list[Step] = []
            if process is not None:
                existing_steps = (
                    session.query(Step).filter(Step.process_id == process.id).order_by(Step.step_number).all()
                )
                step_count = len(existing_steps)
                if step_count == len(steps):
                    existing.append(name)
                else:
                    repaired.append(name)
            else:
                process = repository.create_process(
                    org_id=org.id,
                    name=name,
                    description=f"{name}: maceration through packaging, one execution per batch.",
                    category=ProcessCategory.MANUFACTURING,
                    is_draft=False,
                )
                created.append(name)
            previous_output: dict[str, str] | None = None
            for index, (step_name, description, output_name, unit, inputs, execution_prompts) in enumerate(
                steps, start=1
            ):
                resolved_inputs = _resolve_step_inputs(inputs, previous_output)
                if step_count and index <= step_count:
                    existing_step = existing_steps[index - 1]
                    updates: dict[str, list] = {}
                    if resolved_inputs and not existing_step.inputs:
                        updates["inputs"] = resolved_inputs
                    if output_name and not existing_step.outputs:
                        updates["outputs"] = [{"id": str(uuid4()), "name": output_name, "unit": unit}]
                    if execution_prompts and not existing_step.execution_prompts:
                        updates["execution_prompts"] = list(execution_prompts)
                    if updates:
                        repository.update_step(
                            step_id=existing_step.id,
                            process_id=process.id,
                            org_id=org.id,
                            **updates,
                        )
                        if name not in inputs_repaired:
                            inputs_repaired.append(name)
                    existing_outputs = updates.get("outputs", existing_step.outputs) or []
                    previous_output = (
                        {
                            "id": existing_outputs[0]["id"],
                            "name": existing_outputs[0]["name"],
                            "unit": existing_outputs[0]["unit"],
                        }
                        if existing_outputs
                        else None
                    )
                    continue
                outputs = [{"id": str(uuid4()), "name": output_name, "unit": unit}] if output_name else []
                repository.add_step(
                    process_id=process.id,
                    org_id=org.id,
                    step_number=index,
                    position=index * 1000,
                    name=step_name,
                    description=description,
                    inputs=resolved_inputs,
                    outputs=outputs,
                    execution_prompts=list(execution_prompts),
                )
                previous_output = (
                    {"id": outputs[0]["id"], "name": outputs[0]["name"], "unit": outputs[0]["unit"]}
                    if outputs
                    else None
                )
        return {
            "created": created,
            "existing": existing,
            "repaired": repaired,
            "inputs_repaired": inputs_repaired,
        }
    finally:
        scope.close()
        session.close()
        engine.dispose()


def apply_raw_material_inventory(legacy_url: str, target_url: str, requested_org_name: str) -> dict[str, int]:
    """Load purchase rows as dated raw-material inventory items and additions -- no workflow."""
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Raw-material load is only permitted for {RESET_ORG_NAME!r}")

    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
    from app.core.db.models.inventory_wastage import InventoryWastage  # noqa: F401 - resolves ORM relationship
    from app.core.db.repositories.inventory_repo import InventoryRepository

    with create_engine(legacy_url).connect() as legacy_connection:
        records = _disambiguate_reused_supplier_batches(list(_raw_material_records(legacy_connection)))

    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    scope = ExitStack()
    imported = 0
    skipped = 0
    try:
        org = _enter_target_tenant_scope(scope, session, requested_org_name)
        session.execute(text("SELECT set_config('app.inventory_qty_guard', '1', true)"))
        inventory_repository = InventoryRepository(session)
        for record in records:
            marker = f"raw-{record.source_table}-{record.source_id}"
            existing = (
                session.query(InventoryItem.id)
                .filter(
                    InventoryItem.org_id == org.id,
                    InventoryItem.extra_data[IMPORT_MARKER_KEY].astext == marker,
                )
                .first()
            )
            if existing:
                skipped += 1
                continue
            provenance = _import_marker(marker, record.source_table, record.source_id)
            item = inventory_repository.create_inventory_item(
                org_id=org.id,
                name=record.name,
                quantity=record.quantity,
                unit=record.unit,
                inventory_type="raw_material",
                supplier=record.supplier,
                purchase_date=record.source_date,
                supplier_batch_number=record.supplier_batch_number,
                expiry_date=record.expiry_date,
                extra_data={**provenance, **record.extra_data},
                commit=False,
            )
            business_at = _derived_timestamp(record.source_date)
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
                    movement_metadata=provenance,
                )
            )
            imported += 1
        session.commit()
        return {"imported_items": imported, "skipped_items": skipped}
    except Exception:
        session.rollback()
        raise
    finally:
        scope.close()
        session.close()
        engine.dispose()


def apply_customs_lodgements(legacy_url: str, target_url: str, requested_org_name: str) -> dict[str, int]:
    """Load Customs lodgement rows as NZ-alcohol compliance records with their real periods."""
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Customs load is only permitted for {RESET_ORG_NAME!r}")

    from app.features.compliant.models.compliance_record import ComplianceRecord

    with create_engine(legacy_url).connect() as legacy_connection:
        lodgements = _customs_lodgement_rows(legacy_connection)

    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    scope = ExitStack()
    imported = 0
    skipped = 0
    try:
        org = _enter_target_tenant_scope(scope, session, requested_org_name)
        for row in lodgements:
            source_id = row["id"]
            source_date = _required_date(row["date"], "customs_lodgements", source_id)
            marker = f"customs-{source_id}"
            existing = (
                session.query(ComplianceRecord.id)
                .filter(
                    ComplianceRecord.org_id == org.id,
                    ComplianceRecord.details[IMPORT_MARKER_KEY].astext == marker,
                )
                .first()
            )
            if existing:
                skipped += 1
                continue
            period = _optional_text(row["date_period"]) or source_date.isoformat()
            provenance = _import_marker(marker, "customs_lodgements", source_id)
            session.add(
                ComplianceRecord(
                    org_id=org.id,
                    framework_slug="customs-alcohol",
                    control_id="period-lodgement",
                    record_type="lodgement",
                    status="complete",
                    title=f"Customs lodgement — {period}",
                    period_start=source_date,
                    period_end=source_date,
                    measured_value=_decimal(row["lal"], "lal", "customs_lodgements", source_id),
                    evidence_reference=f"Customs alcohol reconciliation lodgement for period {period}.",
                    source_refs=[],
                    details={
                        **provenance,
                        "period_label": period,
                        "lodged_volume_l": str(
                            _decimal(row["lodged_volume"], "lodged_volume", "customs_lodgements", source_id)
                        ),
                        "lodged_abv_percent": str(
                            _decimal(row["lodged_abv"], "lodged_abv", "customs_lodgements", source_id)
                        ),
                        "litres_of_alcohol": str(_decimal(row["lal"], "lal", "customs_lodgements", source_id)),
                        "bottle_count": str(_decimal(row["bottles"], "bottles", "customs_lodgements", source_id)),
                    },
                    created_at=_derived_timestamp(source_date),
                    updated_at=_derived_timestamp(source_date),
                )
            )
            imported += 1
        session.commit()
        return {"imported_lodgements": imported, "skipped_lodgements": skipped}
    except Exception:
        session.rollback()
        raise
    finally:
        scope.close()
        session.close()
        engine.dispose()


def _load_process_steps(session: Any, org_id: Any) -> dict[str, list[Any]]:
    from app.core.db.models.process import Process
    from app.core.db.models.step import Step

    result: dict[str, list[Any]] = {}
    processes = {
        p.name: p
        for p in session.query(Process).filter(Process.org_id == org_id, Process.name.in_(PRODUCT_WORKFLOWS)).all()
    }
    missing = sorted(set(PRODUCT_WORKFLOWS) - set(processes))
    if missing:
        raise RuntimeError(f"Missing product workflows: {', '.join(missing)}")
    for name, process in processes.items():
        steps = session.query(Step).filter(Step.process_id == process.id).order_by(Step.position).all()
        result[name] = [process, steps]
    return result


def apply_production_batches(
    legacy_url: str, target_url: str, requested_org_name: str, manifest_path: Path | None
) -> dict[str, int]:
    """Build one multi-step execution per VAT batch, every step stamped with its real date."""
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Batch load is only permitted for {RESET_ORG_NAME!r}")

    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
    from app.core.db.models.inventory_wastage import InventoryWastage  # noqa: F401 - resolves ORM relationship
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from app.core.db.repositories.inventory_repo import InventoryRepository

    with create_engine(legacy_url).connect() as legacy_connection:
        legacy = _legacy_batches(legacy_connection)
    manifest_batches: list[ProductionBatch] = []
    if manifest_path and manifest_path.exists():
        manifest_batches, _ = _load_manifest(manifest_path)
    batches = _merge_batches(legacy, manifest_batches)

    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    scope = ExitStack()
    imported = 0
    skipped = 0
    steps_completed = 0
    try:
        org = _enter_target_tenant_scope(scope, session, requested_org_name)
        session.execute(text("SELECT set_config('app.inventory_qty_guard', '1', true)"))
        workflows = _load_process_steps(session, org.id)
        execution_repository = ExecutionRepository(session)
        inventory_repository = InventoryRepository(session)

        ingredient_by_code: dict[str, list[Any]] = defaultdict(list)
        for item in session.query(InventoryItem).filter(InventoryItem.org_id == org.id).all():
            extra = item.extra_data or {}
            code = extra.get("ingredient_code") or extra.get("recorded_supplier_batch_number")
            if code:
                ingredient_by_code[str(code)].append(item)
        vat_item_by_global: dict[int, Any] = {}

        for batch in batches:
            already = (
                session.query(ExecutionStep.id)
                .filter(
                    ExecutionStep.org_id == org.id,
                    ExecutionStep.execution_data[BATCH_MARKER_KEY].astext == batch.marker,
                )
                .first()
            )
            if already:
                skipped += 1
                continue

            process, steps = workflows[batch.workflow_name]
            step_keys = RHUBARB_GIN_STEP_KEYS if batch.product_line == "rosella" else BOTANICAL_GIN_STEP_KEYS
            raw_dates = [batch.steps[key].step_date if key in batch.steps else None for key in step_keys]
            resolved, adjusted = _monotonic_step_dates(raw_dates)

            execution = execution_repository.create_execution(org.id, process.id, commit=False)
            exec_steps = (
                session.query(ExecutionStep)
                .filter(ExecutionStep.execution_id == execution.id, ExecutionStep.org_id == org.id)
                .order_by(ExecutionStep.step_number)
                .all()
            )
            vat_item = None
            product_item = None
            for index, (step_key, exec_step) in enumerate(zip(step_keys, exec_steps, strict=True)):
                step = steps[index]
                step_date = resolved[index]
                business_at = _derived_timestamp(step_date)
                recorded = batch.steps.get(step_key)
                confidence = "derived" if adjusted[index] or recorded is None else recorded.confidence
                marker = _import_marker(batch.marker, PRODUCTION_SOURCE_TABLE, batch.global_vat, step=step_key)
                step_data: dict[str, Any] = {
                    **marker,
                    "date_confidence": confidence,
                    "step_date": step_date.isoformat(),
                    "batch_label": batch.batch_label,
                    "global_vat": batch.global_vat,
                }
                actual_inputs: list[dict[str, Any]] = []
                actual_outputs: list[dict[str, Any]] = []

                if step_key in ("maceration", "rhubarb_maceration"):
                    for code in batch.ingredient_codes:
                        for candidate in ingredient_by_code.get(code, []):
                            actual_inputs.append(
                                {
                                    "inventory_item_id": str(candidate.id),
                                    "name": candidate.name,
                                    "quantity": None,
                                    "unit": candidate.unit,
                                    "link": {"kind": "ingredient_code", "reference": code},
                                }
                            )
                    if step_key == "rhubarb_maceration" and batch.base_vat is not None:
                        base_item = vat_item_by_global.get(batch.base_vat)
                        if base_item is None:
                            raise RuntimeError(
                                f"Rosella VAT{batch.global_vat} needs base VAT{batch.base_vat} loaded first"
                            )
                        actual_inputs.append(
                            {
                                "inventory_item_id": str(base_item.id),
                                "name": base_item.name,
                                "quantity": None,
                                "unit": base_item.unit,
                                "link": {"kind": "base_vat", "reference": batch.base_vat},
                            }
                        )

                produces_vat = step_key in ("aging", "rhubarb_maceration") and bool(step.outputs)
                produces_bottles = step_key == "bottling"

                if produces_vat and vat_item is None:
                    quantity = batch.vat_volume_l or Decimal("0")
                    vat_item = inventory_repository.create_inventory_item(
                        org_id=org.id,
                        name=f"{batch.product_line.title()} {batch.batch_label} VAT batch",
                        quantity=quantity,
                        unit="L",
                        inventory_type="work_in_progress",
                        supplier_batch_number=batch.batch_label,
                        source_execution_id=execution.id,
                        source_execution_step_id=exec_step.id,
                        source_output_id=step.outputs[0]["id"],
                        source_step_name=step.name,
                        extra_data={
                            **marker,
                            "batch_label": batch.batch_label,
                            "global_vat": batch.global_vat,
                            "abv_percent": str(batch.vat_abv) if batch.vat_abv is not None else "",
                        },
                        commit=False,
                    )
                    vat_item.created_at = business_at
                    vat_item.updated_at = business_at
                    vat_item_by_global[batch.global_vat] = vat_item
                    actual_outputs = [
                        {
                            "inventory_item_id": str(vat_item.id),
                            "name": vat_item.name,
                            "quantity": str(quantity),
                            "unit": "L",
                        }
                    ]
                    session.add(
                        InventoryMovement(
                            org_id=org.id,
                            inventory_item_id=vat_item.id,
                            movement_type=InventoryMovementType.PRODUCTION.value,
                            quantity=quantity,
                            unit="L",
                            created_at=business_at,
                            movement_metadata=marker,
                        )
                    )

                if produces_bottles and batch.bottlings:
                    if vat_item is not None:
                        actual_inputs.append(
                            {
                                "inventory_item_id": str(vat_item.id),
                                "name": vat_item.name,
                                "quantity": None,
                                "unit": vat_item.unit,
                                "link": {"kind": "vat_batch", "reference": batch.batch_label},
                            }
                        )
                    total_bottles = sum((Decimal(str(b["bottles"])) for b in batch.bottlings), Decimal("0"))
                    size_ml = batch.bottlings[0].get("bottle_size_ml") if batch.bottlings else None
                    abv = batch.vat_abv
                    if abv is None and batch.bottlings and batch.bottlings[0].get("abv_percent"):
                        abv = Decimal(str(batch.bottlings[0]["abv_percent"]))
                    product_item = inventory_repository.create_inventory_item(
                        org_id=org.id,
                        name=f"{batch.product_line.title()} {batch.batch_label} bottled product",
                        quantity=total_bottles,
                        unit="units",
                        inventory_type="final_product",
                        supplier_batch_number=batch.batch_label,
                        source_execution_id=execution.id,
                        source_execution_step_id=exec_step.id,
                        source_output_id=step.outputs[0]["id"],
                        source_step_name=step.name,
                        extra_data={
                            **marker,
                            "batch_label": batch.batch_label,
                            "global_vat": batch.global_vat,
                            "bottle_size_ml": str(size_ml or ""),
                            "abv_percent": str(abv) if abv is not None else "",
                            "bottlings": list(batch.bottlings),
                        },
                        commit=False,
                    )
                    product_item.created_at = business_at
                    product_item.updated_at = business_at
                    actual_outputs = [
                        {
                            "inventory_item_id": str(product_item.id),
                            "name": product_item.name,
                            "quantity": str(total_bottles),
                            "unit": "units",
                        }
                    ]
                    movements = batch.bottlings or ({"date": step_date.isoformat(), "bottles": str(total_bottles)},)
                    for entry in movements:
                        moved_at = _derived_timestamp(date.fromisoformat(entry["date"]))
                        session.add(
                            InventoryMovement(
                                org_id=org.id,
                                inventory_item_id=product_item.id,
                                movement_type=InventoryMovementType.PRODUCTION.value,
                                quantity=Decimal(str(entry["bottles"])),
                                unit="units",
                                created_at=moved_at,
                                movement_metadata={
                                    **marker,
                                    "bottling_date": entry["date"],
                                    "estimated": bool(entry.get("estimated")),
                                },
                            )
                        )
                    step_data["bottlings"] = list(batch.bottlings)

                if step_key == "labelling" and product_item is not None:
                    actual_inputs.append(
                        {
                            "inventory_item_id": str(product_item.id),
                            "name": product_item.name,
                            "quantity": None,
                            "unit": "units",
                            "link": {"kind": "bottled_product", "reference": batch.batch_label},
                        }
                    )

                execution_repository.complete_step(
                    exec_step.id,
                    org.id,
                    actual_inputs=actual_inputs,
                    actual_outputs=actual_outputs,
                    execution_data=step_data,
                    completed_at_override=business_at,
                    commit=False,
                )
                exec_step.started_at = business_at
                exec_step.created_at = business_at
                exec_step.updated_at = business_at
                steps_completed += 1

            first_at = _derived_timestamp(resolved[0])
            last_at = _derived_timestamp(resolved[-1])
            execution.started_at = first_at
            execution.created_at = first_at
            execution.completed_at = last_at
            execution.updated_at = last_at
            imported += 1

        session.commit()
        return {"imported_batches": imported, "skipped_batches": skipped, "steps_completed": steps_completed}
    except Exception:
        session.rollback()
        raise
    finally:
        scope.close()
        session.close()
        engine.dispose()


def apply_trial_batches(legacy_url: str, target_url: str, requested_org_name: str) -> dict[str, int]:
    """Load recipe/distillation trials as a distilling step feeding library stock."""
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Trial load is only permitted for {RESET_ORG_NAME!r}")

    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
    from app.core.db.models.inventory_wastage import InventoryWastage  # noqa: F401 - resolves ORM relationship
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from app.core.db.repositories.inventory_repo import InventoryRepository

    with create_engine(legacy_url).connect() as legacy_connection:
        trials = list(_trial_records(legacy_connection))

    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    scope = ExitStack()
    imported = 0
    skipped = 0
    consumed_movements = 0
    try:
        org = _enter_target_tenant_scope(scope, session, requested_org_name)
        session.execute(text("SELECT set_config('app.inventory_qty_guard', '1', true)"))
        workflows = _load_process_steps(session, org.id)
        execution_repository = ExecutionRepository(session)
        inventory_repository = InventoryRepository(session)

        for trial in trials:
            already = (
                session.query(ExecutionStep.id)
                .filter(
                    ExecutionStep.org_id == org.id,
                    ExecutionStep.execution_data[BATCH_MARKER_KEY].astext == trial.marker,
                )
                .first()
            )
            if already:
                skipped += 1
                continue
            process, steps = workflows[trial.workflow_name]
            business_at = _derived_timestamp(trial.source_date)
            execution = execution_repository.create_execution(org.id, process.id, commit=False)
            exec_steps = (
                session.query(ExecutionStep)
                .filter(ExecutionStep.execution_id == execution.id, ExecutionStep.org_id == org.id)
                .order_by(ExecutionStep.step_number)
                .all()
            )
            for index, (step_key, exec_step) in enumerate(zip(TRIAL_STEP_KEYS, exec_steps, strict=True)):
                step = steps[index]
                marker = _import_marker(trial.marker, trial.source_table, trial.source_id, step=step_key)
                outputs: list[dict[str, Any]] = []
                if step_key == "library_stock" and step.outputs:
                    quantity = trial.library_ml or Decimal("0")
                    item = inventory_repository.create_inventory_item(
                        org_id=org.id,
                        name=f"Trial library stock {trial.label}",
                        quantity=quantity,
                        unit="mL",
                        inventory_type="work_in_progress",
                        supplier_batch_number=trial.label[:255],
                        source_execution_id=execution.id,
                        source_execution_step_id=exec_step.id,
                        source_output_id=step.outputs[0]["id"],
                        source_step_name=step.name,
                        extra_data={**marker, **trial.extra_data},
                        commit=False,
                    )
                    item.created_at = business_at
                    item.updated_at = business_at
                    outputs = [
                        {
                            "inventory_item_id": str(item.id),
                            "name": item.name,
                            "quantity": str(quantity),
                            "unit": "mL",
                        }
                    ]
                    session.add(
                        InventoryMovement(
                            org_id=org.id,
                            inventory_item_id=item.id,
                            movement_type=InventoryMovementType.PRODUCTION.value,
                            quantity=quantity,
                            unit="mL",
                            created_at=business_at,
                            movement_metadata=marker,
                        )
                    )
                    for entry in trial.consumed:
                        moved_at = _derived_timestamp(date.fromisoformat(entry["date"]))
                        session.add(
                            InventoryMovement(
                                org_id=org.id,
                                inventory_item_id=item.id,
                                movement_type=InventoryMovementType.ADJUSTMENT.value,
                                quantity=Decimal("0"),
                                unit="mL",
                                created_at=moved_at,
                                movement_metadata={
                                    **marker,
                                    "consumed_as": "library_stock_sample",
                                    "quantity_not_recorded": True,
                                    "recorded": entry,
                                },
                            )
                        )
                        consumed_movements += 1
                execution_repository.complete_step(
                    exec_step.id,
                    org.id,
                    actual_inputs=[],
                    actual_outputs=outputs,
                    execution_data={
                        **marker,
                        "step_date": trial.source_date.isoformat(),
                        "trial_label": trial.label,
                        **trial.extra_data,
                    },
                    completed_at_override=business_at,
                    commit=False,
                )
                exec_step.started_at = business_at
                exec_step.created_at = business_at
                exec_step.updated_at = business_at
            execution.started_at = business_at
            execution.created_at = business_at
            execution.completed_at = business_at
            execution.updated_at = business_at
            imported += 1

        session.commit()
        return {
            "imported_trials": imported,
            "skipped_trials": skipped,
            "consumption_movements": consumed_movements,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        scope.close()
        session.close()
        engine.dispose()


def reset_target_org(target_url: str, requested_org_name: str) -> dict[str, Any]:
    """Delete loaded tenant data while preserving the target organisation and its users.

    This is intentionally constrained to the single agreed test tenant. Do not generalise
    the confirmation flag or call this function for an arbitrary organisation.
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


def ensure_target_org_admin(
    target_url: str, requested_org_name: str, admin_email: str, admin_password: str
) -> dict[str, bool]:
    """Create the one permitted test tenant and its deterministic admin if absent.

    This deliberately does not reset an existing password or alter an existing user. The
    supplied password is used only for a newly-created account and is never included in
    the report.
    """
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Tenant setup is only permitted for {RESET_ORG_NAME!r}")

    normalized_email = admin_email.lower().strip()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("A valid test-admin email address is required")
    if not admin_password:
        raise ValueError("A non-empty test-admin password is required")

    from app.core.db.models.organisation import Organisation, OrganisationStatus
    from app.core.db.models.user import User, UserRole
    from app.core.security.auth_service import AuthService
    from app.core.security.tenant_scope import tenant_scope, unscoped

    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    scope = ExitStack()
    org_created = False
    admin_created = False
    try:
        with unscoped():
            org = session.query(Organisation).filter(Organisation.name == requested_org_name).one_or_none()
        if org is None:
            with unscoped():
                existing_email_owner = session.query(User).filter(User.email == normalized_email).one_or_none()
            if existing_email_owner is not None:
                raise ValueError("The requested test-admin email is already assigned to another user")
            org = Organisation(name=requested_org_name, status=OrganisationStatus.ACTIVE)
            session.add(org)
            session.flush()
            org_created = True

        scope.enter_context(tenant_scope(org.id))
        admin = session.query(User).filter(User.org_id == org.id, User.email == normalized_email).one_or_none()
        if admin is None:
            with unscoped():
                existing_email_owner = session.query(User).filter(User.email == normalized_email).one_or_none()
            if existing_email_owner is not None:
                raise ValueError("The requested test-admin email is already assigned to another user")
            session.add(
                User(
                    org_id=org.id,
                    email=normalized_email,
                    password_hash=AuthService.hash_password(admin_password),
                    role=UserRole.ADMIN,
                    is_active=True,
                )
            )
            admin_created = True
        elif not admin.is_active or admin.role != UserRole.ADMIN:
            raise ValueError("The deterministic test-admin account is not an active administrator")

        session.commit()
        return {"org_created": org_created, "admin_created": admin_created}
    except Exception:
        session.rollback()
        raise
    finally:
        scope.close()
        session.close()
        engine.dispose()


def _keepass_password(entry_name: str) -> str:
    """Read a KeePassXC entry's Password field, using this repo's existing helper
    (scripts/local_secrets.py) and its KEEPASS_KDBX_PATH/KEEPASS_PASSWORD env vars.
    Raises rather than returning a falsy value -- a missing/wrong entry here should
    stop the caller, not silently fall through to some other credential.
    """
    from local_secrets import get_keepass_entry

    entry = get_keepass_entry(entry_name)
    password = entry.get("Password")
    if not password:
        raise ValueError(
            f"KeePassXC entry {entry_name!r} not found or has no Password field "
            "(check KEEPASS_KDBX_PATH/KEEPASS_PASSWORD)"
        )
    return password


def sync_whistlebird_test_admin_password(
    target_url: str, requested_org_name: str, admin_email: str = DEFAULT_TEST_ADMIN_EMAIL
) -> dict[str, bool]:
    """Reset the deterministic test admin's password to match the KeePassXC entry
    `workflow-engine/whistlebird_test` -- the single source of truth for this one
    disposable account's credential from now on.

    Unlike `ensure_target_org_admin` (which deliberately never touches an existing
    password -- appropriate for a general-purpose "create if absent" helper), this
    function is meant to run every time a bootstrap/replay script touches this
    account, so its password never again silently drifts out of sync with what the
    founder has actually set in KeePass.
    """
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Password sync is only permitted for {RESET_ORG_NAME!r}")

    password = _keepass_password(WHISTLEBIRD_TEST_ADMIN_KEEPASS_ENTRY)

    from app.core.db.models.user import User
    from app.core.security.auth_service import AuthService
    from app.core.security.tenant_scope import unscoped

    normalized_email = admin_email.lower().strip()
    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        with unscoped():
            user = session.query(User).filter(User.email == normalized_email).one_or_none()
        if user is None:
            raise ValueError(f"test admin {admin_email!r} does not exist yet -- run --ensure-test-tenant first")
        user.password_hash = AuthService.hash_password(password)
        session.commit()
        return {"synced": True}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def ensure_compliant_nz_alcohol_setup(target_url: str, requested_org_name: str) -> dict[str, bool | str]:
    """Set up the documented Compliant NZ-alcohol tier for the Whistlebird test tenant."""
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Compliant NZ-alcohol setup is only permitted for {RESET_ORG_NAME!r}")

    # Importing InventoryMovement through the compliance/repository path configures its
    # relationship to InventoryWastage. The app factory imports both at startup, but
    # this standalone maintenance script must do the same before its first ORM query.
    from app.core.db.models.inventory_wastage import InventoryWastage  # noqa: F401
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.compliant.service import ComplianceService

    engine = create_engine(target_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    scope = ExitStack()
    try:
        org = _enter_target_tenant_scope(scope, session, requested_org_name)
        profile = ComplianceService(session).upsert_profile(
            org.id,
            {
                "enabled": True,
                "industry_module": "nz_alcohol",
                "council_name": None,
                "trade_waste_consent_reference": None,
                "settings": WHISTLEBIRD_NZ_ALCOHOL_SETTINGS,
            },
        )
        row = FeatureSubscriptionRepository(session).grant(
            org.id,
            "compliant",
            notes="Whistlebird test bootstrap: NZ alcohol Compliant tier",
        )
        return {
            "feature_key": row.feature_key,
            "active": row.active,
            "profile_enabled": profile.enabled,
            "industry_module": profile.industry_module,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        scope.close()
        session.close()
        engine.dispose()


def _require_matching_import(report: dict[str, Any], report_name: str) -> None:
    """Refuse a bootstrap that completed writes but did not reproduce expected counts.

    Handles both report shapes: a group that is itself an ``{expected, actual}`` pair, and
    a group of named ``{expected, actual}`` pairs. ``date_mismatches`` and ``wording_leaks``
    groups are simple ``{label: count}`` maps where any non-zero count is a failure.
    """
    mismatches: list[str] = []

    def _pair_mismatch(label: str, pair: dict[str, Any]) -> None:
        if pair.get("expected") != pair.get("actual"):
            mismatches.append(f"{label}: expected {pair.get('expected')}, got {pair.get('actual')}")

    for group_name, group in report.items():
        if not isinstance(group, dict):
            continue
        if group_name in ("date_mismatches", "wording_leaks"):
            mismatches.extend(f"{group_name}.{label}: {count}" for label, count in group.items() if count)
        elif {"expected", "actual"} <= set(group):
            _pair_mismatch(group_name, group)
        else:
            for label, pair in group.items():
                if isinstance(pair, dict):
                    _pair_mismatch(label, pair)
    if mismatches:
        raise RuntimeError(f"{report_name} verification failed: {'; '.join(mismatches)}")


# --------------------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------------------


def build_import_verification(
    legacy_url: str,
    target_url: str,
    requested_org_name: str,
    manifest_path: Path | None,
    include_replay_ngs_purchases: bool = True,
) -> dict[str, Any]:
    """Compare loaded counts against the sources and assert no legacy wording leaked.

    `include_replay_ngs_purchases` defaults to True because `--verify-import` (its main
    real-world caller) checks a target populated by the preferred API-replay path
    (`scripts/whistlebird_replay.py`), which buys dedicated per-batch NGS on top of the
    sources below. `bootstrap_whistlebird_test` -- the older ORM-direct path, which never
    creates those purchases -- passes False so its own internal verification isn't broken
    by counting stock it doesn't produce.
    """
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Verification is only permitted for {RESET_ORG_NAME!r}")

    with create_engine(legacy_url).connect() as source:
        raw_material_sources = {
            table: source.execute(text(f"SELECT count(*) FROM {_identifier(table)}")).scalar_one()
            for table in (
                "purchases_gns",
                "purchases_empty_bottles",
                "purchases_ingredients",
                "product_actions_create_premix",
            )
        }
        expected_lodgements = source.execute(text("SELECT count(*) FROM customs_lodgements")).scalar_one()
        zero_quantity_legacy_ingredients = source.execute(
            text("SELECT count(*) FROM purchases_ingredients WHERE ingredients_amount <= 0")
        ).scalar_one()
        legacy = _legacy_batches(source)
    raw_material_manifest_path = Path(__file__).parents[1] / "docs" / "whistlebird-raw-material-source.json"
    if raw_material_manifest_path.exists():
        raw_material_manifest = json.loads(raw_material_manifest_path.read_text(encoding="utf-8"))
        raw_material_sources["docs/whistlebird-raw-material-source.json"] = len(
            raw_material_manifest.get("clean_records", [])
        ) + len(raw_material_manifest.get("inferred_records", []))
    raw_material_sources["purchases_ingredients"] -= zero_quantity_legacy_ingredients
    manifest_batches: list[ProductionBatch] = []
    if manifest_path and manifest_path.exists():
        manifest_batches, _ = _load_manifest(manifest_path)
    batches = _merge_batches(legacy, manifest_batches)
    expected_by_workflow = Counter(batch.workflow_name for batch in batches)

    if include_replay_ngs_purchases:
        # The API-replay path (scripts/whistlebird_replay.py) buys Neutral grain spirit
        # dedicated to a single batch wherever the real purchases_gns purchases can't
        # reach (see whistlebird_replay_timeline.NGS_LEGACY_POOL_CUTOFF) -- not sourced
        # from any legacy table or manifest file, so it has to be counted here rather
        # than read off a source count above.
        from whistlebird_replay_timeline import count_dedicated_ngs_purchases

        raw_material_sources["ngs_dedicated_purchases"] = count_dedicated_ngs_purchases(batches)

    with create_engine(target_url).connect() as target:
        org_id = target.execute(
            text("SELECT id FROM organisations WHERE name = :name"), {"name": requested_org_name}
        ).scalar_one_or_none()
        if org_id is None:
            raise ValueError(f"Target organisation {requested_org_name!r} does not exist")
        params = {"org_id": org_id, "names": list(PRODUCT_WORKFLOWS), "key": IMPORT_MARKER_KEY}
        actual_raw = target.execute(
            text(
                """
                SELECT count(*) FROM inventory_items
                WHERE org_id = :org_id AND inventory_type = 'raw_material'
                  AND extra_data ->> :key LIKE 'raw-%'
                """
            ),
            params,
        ).scalar_one()
        actual_by_workflow = dict(
            target.execute(
                text(
                    """
                    SELECT p.name, count(*)
                    FROM executions e JOIN processes p ON p.id = e.process_id
                    WHERE e.org_id = :org_id AND p.name = ANY(:names)
                    GROUP BY p.name
                    """
                ),
                params,
            ).all()
        )
        incomplete_steps = target.execute(
            text(
                """
                SELECT count(*) FROM execution_steps es
                JOIN executions e ON e.id = es.execution_id
                JOIN processes p ON p.id = e.process_id
                WHERE e.org_id = :org_id AND p.name = ANY(:names) AND es.status <> 'COMPLETED'
                """
            ),
            params,
        ).scalar_one()
        step_date_mismatches = target.execute(
            text(
                """
                SELECT count(*) FROM execution_steps es
                JOIN executions e ON e.id = es.execution_id
                WHERE e.org_id = :org_id
                  AND es.execution_data ? 'step_date'
                  AND (es.completed_at AT TIME ZONE 'Pacific/Auckland')::date
                      <> (es.execution_data ->> 'step_date')::date
                """
            ),
            params,
        ).scalar_one()
        actual_lodgements = target.execute(
            text(
                """
                SELECT count(*) FROM compliance_records
                WHERE org_id = :org_id AND framework_slug = 'customs-alcohol'
                  AND control_id = 'period-lodgement' AND details ->> :key LIKE 'customs-%'
                """
            ),
            params,
        ).scalar_one()
        stamped_today = target.execute(
            text(
                """
                SELECT count(*) FROM execution_steps es JOIN executions e ON e.id = es.execution_id
                WHERE e.org_id = :org_id
                  AND (es.completed_at AT TIME ZONE 'Pacific/Auckland')::date
                      = (now() AT TIME ZONE 'Pacific/Auckland')::date
                """
            ),
            params,
        ).scalar_one()
        wording_leaks = {}
        leak_sql = {
            "process_names": "SELECT count(*) FROM processes WHERE org_id = :org_id "
            "AND lower(name) ~ 'legacy|sheet:|historical'",
            "step_names": "SELECT count(*) FROM steps WHERE org_id = :org_id "
            "AND lower(name) ~ 'legacy|sheet:|historical'",
            "inventory_names": "SELECT count(*) FROM inventory_items WHERE org_id = :org_id "
            "AND lower(name) ~ 'legacy|sheet:|historical'",
            "inventory_extra": "SELECT count(*) FROM inventory_items WHERE org_id = :org_id "
            "AND lower(extra_data::text) ~ 'whistlebird_v1|legacy_source|historical_import'",
            "step_extra": "SELECT count(*) FROM execution_steps es JOIN executions e ON e.id = es.execution_id "
            "WHERE e.org_id = :org_id "
            "AND lower(es.execution_data::text) ~ 'whistlebird_v1|legacy_source|historical_import'",
        }
        for label, sql in leak_sql.items():
            wording_leaks[label] = target.execute(text(sql), params).scalar_one()

    return {
        "raw_material_items": {"expected": sum(raw_material_sources.values()), "actual": actual_raw},
        "batch_executions": {
            name: {"expected": expected_by_workflow.get(name, 0), "actual": actual_by_workflow.get(name, 0)}
            for name in (WILDFLOWER_WORKFLOW, SOLSTICE_WORKFLOW, ROSELLA_WORKFLOW)
        },
        "customs_lodgements": {"expected": expected_lodgements, "actual": actual_lodgements},
        "incomplete_batch_steps": {"expected": 0, "actual": incomplete_steps},
        "date_mismatches": {"step_dates": step_date_mismatches, "steps_stamped_on_run_date": stamped_today},
        "wording_leaks": wording_leaks,
    }


def build_manifest_verification(manifest_path: Path, target_url: str, requested_org_name: str) -> dict[str, Any]:
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Verification is only permitted for {RESET_ORG_NAME!r}")
    batches, excluded = _load_manifest(manifest_path)
    expected = Counter(b.product_line for b in batches)
    with create_engine(target_url).connect() as target:
        org_id = target.execute(
            text("SELECT id FROM organisations WHERE name = :name"), {"name": requested_org_name}
        ).scalar_one_or_none()
        if org_id is None:
            raise ValueError(f"Target organisation {requested_org_name!r} does not exist")
        loaded_labels = target.execute(
            text(
                """
                SELECT count(DISTINCT es.execution_data ->> 'batch_label')
                FROM execution_steps es JOIN executions e ON e.id = es.execution_id
                WHERE e.org_id = :org_id AND es.execution_data -> 'source_ref' ->> 'table' = :tbl
                """
            ),
            {"org_id": org_id, "tbl": PRODUCTION_SOURCE_TABLE},
        ).scalar_one()
    return {
        "manifest_batches_by_product": {k: expected.get(k, 0) for k in ("wildflower", "solstice", "rosella")},
        "loaded_batch_labels_with_manifest_steps": loaded_labels,
        "excluded_batches": len(excluded),
    }


# --------------------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------------------


def bootstrap_whistlebird_test(
    legacy_url: str,
    target_url: str,
    requested_org_name: str,
    admin_email: str,
    admin_password: str,
    manifest_path: Path,
) -> dict[str, Any]:
    """Rebuild the disposable Whistlebird tenant from reviewed, deterministic sources.

    Every read-only validation happens before the first target write. The only destructive
    operation is the existing exact-name reset, which preserves tenant users and rejects
    every other organisation name.
    """
    if requested_org_name != RESET_ORG_NAME:
        raise ValueError(f"Bootstrap is only permitted for {RESET_ORG_NAME!r}")

    preflight = {
        "core": build_core_dry_run(legacy_url),
        "production": build_production_dry_run(legacy_url, manifest_path),
        "manifest": build_manifest_dry_run(manifest_path),
    }
    setup = ensure_target_org_admin(target_url, requested_org_name, admin_email, admin_password)
    password_sync = sync_whistlebird_test_admin_password(target_url, requested_org_name, admin_email)
    reset = reset_target_org(target_url, requested_org_name)
    workflows = setup_product_workflows(target_url, requested_org_name)
    raw_materials = apply_raw_material_inventory(legacy_url, target_url, requested_org_name)
    batches = apply_production_batches(legacy_url, target_url, requested_org_name, manifest_path)
    trials = apply_trial_batches(legacy_url, target_url, requested_org_name)
    lodgements = apply_customs_lodgements(legacy_url, target_url, requested_org_name)
    # This ORM-direct path never buys the API-replay path's dedicated per-batch NGS
    # purchases (see build_import_verification's docstring), so its own verification
    # must not expect them.
    verification = build_import_verification(
        legacy_url, target_url, requested_org_name, manifest_path, include_replay_ngs_purchases=False
    )
    manifest_verification = build_manifest_verification(manifest_path, target_url, requested_org_name)
    _require_matching_import(verification, "Production history load")
    compliant_nz_alcohol_setup = ensure_compliant_nz_alcohol_setup(target_url, requested_org_name)
    return {
        "preflight": preflight,
        "tenant_setup": setup,
        "password_sync": password_sync,
        "reset": reset,
        "workflows": workflows,
        "raw_materials": raw_materials,
        "batches": batches,
        "trials": trials,
        "customs_lodgements": lodgements,
        "verification": {"load": verification, "manifest": manifest_verification},
        "compliant_nz_alcohol_setup": compliant_nz_alcohol_setup,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--legacy-url",
        default=os.environ.get("WB_LEGACY_DATABASE_URL"),
        help="Prior-database SQLAlchemy URL (or set WB_LEGACY_DATABASE_URL).",
    )
    parser.add_argument(
        "--target-url",
        default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"),
        help="Target SQLAlchemy URL (or set BIZE_MIGRATION_DATABASE_URL).",
    )
    parser.add_argument("--org-name", default="whistlebird_test", help="Requested target tenant name.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path; stdout is always written.")
    parser.add_argument(
        "--admin-email",
        default=DEFAULT_TEST_ADMIN_EMAIL,
        help="Test-admin email used only by --ensure-test-tenant / --rebuild-whistlebird-test.",
    )
    parser.add_argument(
        "--admin-password-env",
        default="WHISTLEBIRD_TEST_ADMIN_PASSWORD",
        help="Environment-variable name holding the test-admin password (never printed).",
    )
    parser.add_argument(
        "--sheet-manifest",
        type=Path,
        help="Path to the curated per-batch production manifest JSON (docs/whistlebird-production-sheet-source.json).",
    )
    parser.add_argument(
        "--ensure-test-tenant",
        action="store_true",
        help="Create only whistlebird_test and its deterministic test-admin account if absent.",
    )
    parser.add_argument(
        "--rebuild-whistlebird-test",
        action="store_true",
        help="Preflight, create whistlebird_test if needed, reset its data, replay the full load, "
        "and require matching verification.",
    )
    parser.add_argument(
        "--confirm-reset-whistlebird-test",
        action="store_true",
        help="Delete loaded data only for the whistlebird_test tenant; preserves its users.",
    )
    parser.add_argument(
        "--sync-test-admin-password",
        action="store_true",
        help="Reset the deterministic test admin's password to match the KeePassXC entry "
        f"{WHISTLEBIRD_TEST_ADMIN_KEEPASS_ENTRY!r} (also runs automatically as part of "
        "--rebuild-whistlebird-test).",
    )
    parser.add_argument(
        "--dry-run-core",
        action="store_true",
        help="Validate the deterministic raw-material and Customs tranche without writing.",
    )
    parser.add_argument(
        "--dry-run-traceability",
        action="store_true",
        help="Measure database-evidenced production and sales links without writing.",
    )
    parser.add_argument(
        "--dry-run-production",
        action="store_true",
        help="Report the per-batch executions the load would build, by product and step, without writing.",
    )
    parser.add_argument(
        "--dry-run-manifest",
        action="store_true",
        help="Validate the curated per-batch production manifest without writing.",
    )
    parser.add_argument(
        "--setup-workflows",
        action="store_true",
        help="Create the per-product and trial workflows only for whistlebird_test.",
    )
    parser.add_argument(
        "--apply-raw-materials",
        action="store_true",
        help="Load prior-database purchases as dated inventory only into whistlebird_test.",
    )
    parser.add_argument(
        "--apply-batches",
        action="store_true",
        help="Build one multi-step execution per VAT batch into whistlebird_test.",
    )
    parser.add_argument(
        "--apply-trials",
        action="store_true",
        help="Load recipe/distillation trials into whistlebird_test.",
    )
    parser.add_argument(
        "--apply-customs-lodgements",
        action="store_true",
        help="Load Customs lodgements as NZ-alcohol compliance records into whistlebird_test.",
    )
    parser.add_argument(
        "--verify-import",
        action="store_true",
        help="Compare loaded counts against the sources and check for legacy wording, without writing.",
    )
    parser.add_argument(
        "--verify-manifest",
        action="store_true",
        help="Compare the curated manifest against loaded rows without writing.",
    )
    arguments = parser.parse_args()

    if not arguments.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    actions = (
        arguments.ensure_test_tenant,
        arguments.rebuild_whistlebird_test,
        arguments.confirm_reset_whistlebird_test,
        arguments.sync_test_admin_password,
        arguments.dry_run_core,
        arguments.dry_run_traceability,
        arguments.dry_run_production,
        arguments.dry_run_manifest,
        arguments.setup_workflows,
        arguments.apply_raw_materials,
        arguments.apply_batches,
        arguments.apply_trials,
        arguments.apply_customs_lodgements,
        arguments.verify_import,
        arguments.verify_manifest,
    )
    if sum(bool(a) for a in actions) > 1:
        parser.error("Specify only one action per invocation")
    target_scoped = (
        arguments.ensure_test_tenant,
        arguments.rebuild_whistlebird_test,
        arguments.confirm_reset_whistlebird_test,
        arguments.sync_test_admin_password,
        arguments.setup_workflows,
        arguments.apply_raw_materials,
        arguments.apply_batches,
        arguments.apply_trials,
        arguments.apply_customs_lodgements,
        arguments.verify_import,
        arguments.verify_manifest,
    )
    if any(target_scoped) and arguments.org_name != RESET_ORG_NAME:
        parser.error(f"--org-name must be exactly {RESET_ORG_NAME!r} for this action")
    arguments.admin_password = os.environ.get(arguments.admin_password_env)
    if (arguments.ensure_test_tenant or arguments.rebuild_whistlebird_test) and not arguments.admin_password:
        # Falls back to the same KeePassXC entry the deterministic test admin's password
        # is kept in sync with (sync_whistlebird_test_admin_password) -- the env var
        # remains a valid override (e.g. CI), it's just no longer required for local use.
        try:
            arguments.admin_password = _keepass_password(WHISTLEBIRD_TEST_ADMIN_KEEPASS_ENTRY)
        except ValueError as e:
            parser.error(f"{arguments.admin_password_env} is not set and KeePassXC fallback failed: {e}")
    if not arguments.sheet_manifest and (
        arguments.rebuild_whistlebird_test or arguments.dry_run_manifest or arguments.verify_manifest
    ):
        arguments.sheet_manifest = DEFAULT_PRODUCTION_MANIFEST
    needs_legacy = (
        arguments.rebuild_whistlebird_test
        or arguments.dry_run_core
        or arguments.dry_run_traceability
        or arguments.dry_run_production
        or arguments.apply_raw_materials
        or arguments.apply_batches
        or arguments.apply_trials
        or arguments.apply_customs_lodgements
        or arguments.verify_import
        or not any(actions)
    )
    if needs_legacy and not arguments.legacy_url:
        parser.error("--legacy-url is required for this action (or set WB_LEGACY_DATABASE_URL)")
    return arguments


def main() -> int:
    arguments = _arguments()
    manifest = arguments.sheet_manifest or DEFAULT_PRODUCTION_MANIFEST
    if arguments.rebuild_whistlebird_test:
        report = bootstrap_whistlebird_test(
            arguments.legacy_url,
            arguments.target_url,
            arguments.org_name,
            arguments.admin_email,
            arguments.admin_password,
            arguments.sheet_manifest,
        )
    elif arguments.ensure_test_tenant:
        report = ensure_target_org_admin(
            arguments.target_url, arguments.org_name, arguments.admin_email, arguments.admin_password
        )
    elif arguments.confirm_reset_whistlebird_test:
        report = reset_target_org(arguments.target_url, arguments.org_name)
    elif arguments.sync_test_admin_password:
        report = sync_whistlebird_test_admin_password(arguments.target_url, arguments.org_name, arguments.admin_email)
    elif arguments.setup_workflows:
        report = setup_product_workflows(arguments.target_url, arguments.org_name)
    elif arguments.apply_raw_materials:
        report = apply_raw_material_inventory(arguments.legacy_url, arguments.target_url, arguments.org_name)
    elif arguments.apply_batches:
        report = apply_production_batches(arguments.legacy_url, arguments.target_url, arguments.org_name, manifest)
    elif arguments.apply_trials:
        report = apply_trial_batches(arguments.legacy_url, arguments.target_url, arguments.org_name)
    elif arguments.apply_customs_lodgements:
        report = apply_customs_lodgements(arguments.legacy_url, arguments.target_url, arguments.org_name)
    elif arguments.verify_import:
        report = build_import_verification(arguments.legacy_url, arguments.target_url, arguments.org_name, manifest)
    elif arguments.verify_manifest:
        report = build_manifest_verification(manifest, arguments.target_url, arguments.org_name)
    elif arguments.dry_run_manifest:
        report = build_manifest_dry_run(manifest)
    elif arguments.dry_run_core:
        report = build_core_dry_run(arguments.legacy_url)
    elif arguments.dry_run_traceability:
        report = build_traceability_dry_run(arguments.legacy_url)
    elif arguments.dry_run_production:
        report = build_production_dry_run(arguments.legacy_url, manifest)
    else:
        report = build_profile(arguments.legacy_url, arguments.target_url, arguments.org_name)
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
