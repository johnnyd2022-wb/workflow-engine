"""Tests for the replayable CRM mappings/config (scripts/whistlebird_crm.py)."""

from __future__ import annotations

import copy
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.organisation import Organisation
from app.core.db.models.task_board_lane import TaskBoardLane  # noqa: F401 - registers CRM task FK target metadata
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.sales_traceability_config import SalesTraceabilityConfig
from app.features.crm.models.xero_contact import XeroContact  # noqa: F401 - registers invoice FK target metadata
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
from app.features.crm.services.crm_service import CRMService
from app.features.crm.services.sales_traceability_service import SalesTraceabilityService

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from whistlebird_crm import (  # noqa: E402
    DEFAULT_CRM_MANIFEST,
    CrmManifestError,
    CrmReplayError,
    load_crm_manifest,
    missing_mappings,
    parse_crm_manifest,
    replay_crm_config,
    verify_crm,
)


def _raw() -> dict:
    return json.loads(DEFAULT_CRM_MANIFEST.read_text(encoding="utf-8"))


class _FakeClient:
    """Records calls and answers the three GETs the replay makes."""

    def __init__(self, products, existing=()):
        self.products = list(products)
        self.existing = list(existing)
        self.calls: list[tuple[str, str, object]] = []

    def get(self, path):
        self.calls.append(("GET", path, None))
        if path == "/api/crm/final-products":
            return {"final_products": [{"name": name} for name in self.products]}
        if path == "/api/crm/product-mappings":
            return {"product_mappings": self.existing}
        raise AssertionError(path)

    def put(self, path, body):
        self.calls.append(("PUT", path, body))
        return {}

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        return {}


ALL_PRODUCTS = [
    "Wildflower - final product",
    "Solstice - final product",
    "Rosella - final product",
    "Green Gold - final product",
]


# --- manifest ---------------------------------------------------------------------


def test_committed_manifest_holds_the_five_reviewed_contains_mappings_and_partial_matching():
    manifest = load_crm_manifest()

    assert {(m.biz_e_product_name, m.xero_description_pattern, m.match_type) for m in manifest.mappings} == {
        ("Wildflower - final product", "Wildflower", "contains"),
        ("Solstice - final product", "Solstice", "contains"),
        ("Rosella - final product", "Rosella", "contains"),
        ("Rosella - final product", "Bin stock", "contains"),
        ("Green Gold - final product", "Green Gold", "contains"),
    }
    assert manifest.traceability_config["strict_mapping"] is False, "contains rules never match while strict"


def _mutated(mutate):
    data = copy.deepcopy(_raw())
    mutate(data)
    return data


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["traceability_config"].update(strict_mapping=True), "exact-only matching is on"),
        (lambda d: d["traceability_config"].pop("strict_mapping"), "strict_mapping must be true or false"),
        (lambda d: d["traceability_config"].update(strict_mapping="false"), "strict_mapping must be true or false"),
        (lambda d: d["product_mappings"].append(dict(d["product_mappings"][0])), "duplicate"),
        (
            lambda d: d["product_mappings"].append(
                {**d["product_mappings"][0], "xero_description_pattern": "WILDFLOWER"}
            ),
            "duplicate",
        ),
        (lambda d: d["product_mappings"][0].update(match_type="fuzzy"), "match_type"),
        (lambda d: d["product_mappings"][0].update(colour="green"), "unknown key"),
        (lambda d: d["product_mappings"][0].update(xero_description_pattern="  "), "non-empty"),
        (lambda d: d["product_mappings"][0].update(xero_description_pattern="x" * 501), "500 characters"),
        (lambda d: d.update(product_mappings=[]), "non-empty list"),
        (lambda d: d.update(surprise=1), "unknown key"),
    ],
)
def test_manifest_validation_rejects_a_malformed_manifest_before_any_request(mutate, message):
    with pytest.raises(CrmManifestError, match=message):
        parse_crm_manifest(_mutated(mutate))


def test_strict_mapping_with_only_exact_rules_is_valid():
    data = _mutated(lambda d: d["traceability_config"].update(strict_mapping=True))
    for mapping in data["product_mappings"]:
        mapping["match_type"] = "exact"

    assert parse_crm_manifest(data).traceability_config["strict_mapping"] is True


# --- replay -----------------------------------------------------------------------


def test_replay_saves_the_config_first_then_creates_every_mapping_in_one_bulk_request():
    client = _FakeClient(ALL_PRODUCTS)

    counts = replay_crm_config(client, load_crm_manifest())

    verbs = [(verb, path) for verb, path, _ in client.calls]
    assert verbs.index(("PUT", "/api/crm/traceability-config")) < verbs.index(
        ("POST", "/api/crm/product-mappings/bulk")
    ), "partial matching must be enabled before contains mappings are saved, as the Configuration page does"
    (bulk,) = [body for verb, path, body in client.calls if verb == "POST"]
    assert len(bulk["mappings"]) == 5
    assert {m["xero_description_pattern"] for m in bulk["mappings"]} == {
        "Wildflower",
        "Solstice",
        "Rosella",
        "Bin stock",
        "Green Gold",
    }
    assert counts == {"config": 1, "mappings_created": 5, "mappings_skipped": 0}


def test_replay_is_resumable_and_only_creates_the_missing_mappings():
    existing = [
        {"biz_e_product_name": "Wildflower - final product", "xero_description_pattern": "wildflower"},
        {"biz_e_product_name": "ROSELLA - FINAL PRODUCT", "xero_description_pattern": "Rosella"},
    ]
    client = _FakeClient(ALL_PRODUCTS, existing)

    counts = replay_crm_config(client, load_crm_manifest())

    (bulk,) = [body for verb, _path, body in client.calls if verb == "POST"]
    assert {m["xero_description_pattern"] for m in bulk["mappings"]} == {"Solstice", "Bin stock", "Green Gold"}
    assert counts == {"config": 1, "mappings_created": 3, "mappings_skipped": 2}


def test_replay_makes_no_bulk_request_when_every_mapping_already_exists():
    manifest = load_crm_manifest()
    existing = [
        {"biz_e_product_name": m.biz_e_product_name, "xero_description_pattern": m.xero_description_pattern}
        for m in manifest.mappings
    ]
    client = _FakeClient(ALL_PRODUCTS, existing)

    counts = replay_crm_config(client, manifest)

    assert not [call for call in client.calls if call[0] == "POST"]
    assert counts["mappings_created"] == 0


def test_replay_refuses_a_mapping_to_a_product_the_tenant_does_not_have_and_writes_nothing():
    client = _FakeClient([name for name in ALL_PRODUCTS if not name.startswith("Green Gold")])

    with pytest.raises(CrmReplayError, match="Green Gold - final product"):
        replay_crm_config(client, load_crm_manifest())

    assert not [call for call in client.calls if call[0] in ("PUT", "POST")], "a typo must not half-apply"


def test_missing_mappings_compares_name_and_phrase_ignoring_case():
    manifest = load_crm_manifest()
    existing = [{"biz_e_product_name": "rosella - final product", "xero_description_pattern": "BIN STOCK"}]

    missing = {(m.biz_e_product_name, m.xero_description_pattern) for m in missing_mappings(manifest, existing)}

    assert ("Rosella - final product", "Bin stock") not in missing
    assert ("Rosella - final product", "Rosella") in missing


# --- contract with the real CRM service ---------------------------------------------


@pytest.fixture
def db():
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture
def crm_org(db):
    org = OrganisationRepository(db).create_org(f"CRM Manifest Test Org {uuid4()}")
    db.commit()
    yield org

    db.rollback()
    db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == org.id).delete(synchronize_session=False)
    db.query(InventoryMovement).filter(InventoryMovement.org_id == org.id).delete(synchronize_session=False)
    db.query(EntityEvent).filter(EntityEvent.org_id == org.id).delete(synchronize_session=False)
    db.query(InventoryItem).filter(InventoryItem.org_id == org.id).delete(synchronize_session=False)
    db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.org_id == org.id).delete(synchronize_session=False)
    db.query(XeroInvoice).filter(XeroInvoice.org_id == org.id).delete(synchronize_session=False)
    db.query(ProductMapping).filter(ProductMapping.org_id == org.id).delete(synchronize_session=False)
    db.query(SalesTraceabilityConfig).filter(SalesTraceabilityConfig.org_id == org.id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def test_committed_manifest_is_accepted_by_the_crm_service_and_maps_the_reviewed_sales_lines(db, crm_org):
    """The exact payloads the replay sends must pass server validation, and the result must behave.

    Bin stock (a generic description carrying a Rosella item code) draws down Rosella; shipping
    and the SAMPLE minis stay unmapped; a paid line and its free "(11 + 1)" promo line take 12.
    """
    manifest = load_crm_manifest()
    service = CRMService(db)
    service.update_traceability_config(crm_org.id, dict(manifest.traceability_config))
    service.create_mappings(crm_org.id, [m.payload() for m in manifest.mappings], None)
    db.commit()

    repo = InventoryRepository(db)
    for name in ALL_PRODUCTS:
        repo.create_inventory_item(
            crm_org.id,
            name=name,
            quantity="30",
            unit="units",
            inventory_type="final_product",
            extra_data={"batch_number": 1},
        )
    invoice = XeroInvoice(
        org_id=crm_org.id,
        xero_invoice_id="xero-manifest-mix",
        xero_tenant_id="test-tenant",
        invoice_type="ACCREC",
        status="PAID",
        date=date(2025, 9, 19),
    )
    db.add(invoice)
    db.flush()
    lines = [
        ("Whistlebird Gin - Bin stock", "3"),
        ("Whistlebird Rosella 700ml - x1", "11"),
        ("Whistlebird Rosella 700ml - x1 (11 + 1 deal)", "1"),
        ("Shipping", "1"),
        ("SAMPLE", "4"),
    ]
    for position, (description, quantity) in enumerate(lines, start=1):
        db.add(
            XeroInvoiceLineItem(
                org_id=crm_org.id,
                invoice_id=invoice.id,
                xero_line_item_id=f"xero-manifest-mix-line-{position}",
                description=description,
                quantity=Decimal(quantity),
            )
        )
    db.commit()

    summary = SalesTraceabilityService(db).reconcile_org(crm_org.id)

    assert summary["allocated"] == 3
    assert summary["unmapped"] == 2, "Shipping and SAMPLE are deliberately outside product FIFO"
    remaining = {
        item.name: item.quantity for item in db.query(InventoryItem).filter(InventoryItem.org_id == crm_org.id).all()
    }
    assert remaining["Rosella - final product"] == Decimal("30") - Decimal("3") - Decimal("11") - Decimal("1")
    assert remaining["Wildflower - final product"] == Decimal("30")


def test_verify_reports_zero_after_a_full_load_then_flags_a_missing_mapping_and_a_config_drift(db, crm_org):
    manifest = load_crm_manifest()
    service = CRMService(db)
    service.update_traceability_config(crm_org.id, dict(manifest.traceability_config))
    service.create_mappings(crm_org.id, [m.payload() for m in manifest.mappings], None)
    db.commit()
    url = db.get_bind().url.render_as_string(hide_password=False)

    clean = verify_crm(url, crm_org.name, manifest)
    assert clean == {
        "crm_product_mappings_missing": {"expected": 0, "actual": 0},
        "crm_traceability_config_mismatch": {"expected": 0, "actual": 0},
    }

    db.query(ProductMapping).filter(
        ProductMapping.org_id == crm_org.id, ProductMapping.xero_description_pattern == "Bin stock"
    ).delete(synchronize_session=False)
    db.query(SalesTraceabilityConfig).filter(SalesTraceabilityConfig.org_id == crm_org.id).update(
        {"strict_mapping": True}, synchronize_session=False
    )
    db.commit()

    drifted = verify_crm(url, crm_org.name, manifest)
    assert drifted["crm_product_mappings_missing"]["actual"] == 1
    assert drifted["crm_traceability_config_mismatch"]["actual"] == 1


def test_verify_ignores_a_mapping_added_later_in_the_crm(db, crm_org):
    """The founder may add mappings after a rebuild; that must not fail a later --verify-import."""
    manifest = load_crm_manifest()
    service = CRMService(db)
    service.update_traceability_config(crm_org.id, dict(manifest.traceability_config))
    service.create_mappings(
        crm_org.id,
        [m.payload() for m in manifest.mappings]
        + [
            {
                "biz_e_product_name": "Extra - final product",
                "xero_description_pattern": "Extra",
                "match_type": "contains",
            }
        ],
        None,
    )
    db.commit()

    result = verify_crm(db.get_bind().url.render_as_string(hide_password=False), crm_org.name, manifest)

    assert result["crm_product_mappings_missing"]["actual"] == 0
