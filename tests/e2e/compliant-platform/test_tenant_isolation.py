"""The mandatory cross-tenant probe for Compliant (e2e-playwright skill, step 1): an
authenticated user from org B must not be able to read or act on org A's profile,
records, alcohol-products, or reports. Every probe goes through `page.request` on an
already-logged-in page -- the real browser session's cookies, not a bypass.

Companion to `tests/test_compliant_routes.py::test_compliant_profile_records_and_audit_pack_are_org_scoped`,
which proves one org-A/org-B report 404. This file is the per-surface version at the E2E
layer, plus the report-format matrix (json/html/csv must all 404, not just the default)
and the source_refs cross-org linking guarantee the spec calls out as its own
tenant-isolation contract, separate from plain cross-org reads.
"""

from __future__ import annotations

import uuid

import pytest

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e

FRAMEWORK_SLUG = "customs-alcohol"
CONTROL_ID = "product-mapping"


@pytest.fixture()
def seeded_org_a(
    two_tenants, enable_profile, create_alcohol_product, create_record, create_report, create_core_execution
):
    """Org A fully seeded: enabled profile, an alcohol product, a manual record, a real
    Core execution, and a generated report -- everything test_cross_tenant_* below tries
    to reach from org B."""
    page_a = two_tenants["a"]
    run_id = uuid.uuid4().hex[:8]
    marker = f"OrgA Secret {run_id}"

    enable_profile(page_a, enabled=True, settings={"alcohol_product_types": ["spirits"]}, council_name=marker)
    product_id = create_alcohol_product(page_a, f"{marker} Gin", product_type="spirits", abv_percent="40")
    record = create_record(page_a, framework_slug=FRAMEWORK_SLUG, control_id=CONTROL_ID, title=marker)
    execution_id = create_core_execution(page_a)
    report = create_report(page_a, FRAMEWORK_SLUG)["report"]

    return {
        "marker": marker,
        "product_id": product_id,
        "record_id": record["id"],
        "execution_id": execution_id,
        "report_id": report["report_id"],
        "pages": two_tenants,
    }


def test_cross_tenant_profile_not_visible(seeded_org_a):
    """Org B's own overview must show its own (unconfigured) profile, never org A's
    council_name/settings, even though both orgs hit the same route."""
    page_b = seeded_org_a["pages"]["b"]
    response = page_b.request.get("/api/compliant/overview")
    assert response.status == 200, response.text()
    body = response.json()
    assert body["profile"] is None, f"org B saw a profile it never configured: {body['profile']}"
    assert seeded_org_a["marker"] not in response.text(), "org A's council_name leaked into org B's overview"


def test_cross_tenant_alcohol_products_not_listed(seeded_org_a):
    page_b = seeded_org_a["pages"]["b"]
    response = page_b.request.get("/api/compliant/alcohol-products")
    assert response.status == 200, response.text()
    products = response.json()["products"]
    assert seeded_org_a["product_id"] not in [p["id"] for p in products], (
        "org A's alcohol product leaked into org B's list"
    )
    assert seeded_org_a["marker"] not in response.text()


def test_cross_tenant_duplicate_name_check_is_per_org_not_global(seeded_org_a):
    """AC: the unique constraint is (org_id, inventory_name) -- org B must be able to
    create a product with the SAME inventory_name org A already used. A cross-tenant
    isolation bug here would show up as an unexpected 409 instead of the intended 201."""
    page_b = seeded_org_a["pages"]["b"]
    response = page_b.request.post(
        "/api/compliant/alcohol-products",
        headers=csrf_headers(page_b),
        data={
            "inventory_name": f"{seeded_org_a['marker']} Gin",
            "product_type": "spirits",
            "abv_percent": "40",
        },
    )
    assert response.status == 201, (
        f"org B was blocked by org A's inventory_name -- the unique constraint leaked "
        f"across tenants: {response.status} {response.text()}"
    )


def test_cross_tenant_records_not_listed(seeded_org_a):
    page_b = seeded_org_a["pages"]["b"]
    response = page_b.request.get("/api/compliant/records")
    assert response.status == 200, response.text()
    records = response.json()["records"]
    assert seeded_org_a["record_id"] not in [r["id"] for r in records], "org A's record leaked into org B's list"
    assert seeded_org_a["marker"] not in response.text()


def test_cross_tenant_source_ref_to_another_orgs_execution_is_rejected(seeded_org_a, enable_profile):
    """AC: every source_ref that parses as a UUID must resolve to a row in *this org's*
    Execution/ExecutionEvidence/ExecutionStep/InventoryMovement -- a same-format UUID
    belonging to another org is rejected, same as one that resolves to nothing. This is
    the tenant-isolation guarantee for cross-object linking, not just cross-org reads:
    org A's real Execution id genuinely exists in the Execution table
    `invalid_core_source_references` queries -- just scoped to org A, not org B -- so this
    proves the org_id filter on that query, not merely "unknown UUIDs are rejected"
    (which a nonexistent UUID would already show).
    """
    page_b = seeded_org_a["pages"]["b"]
    enable_profile(page_b, enabled=True, settings={"require_core_source_refs": False})
    response = page_b.request.post(
        "/api/compliant/records",
        headers=csrf_headers(page_b),
        data={
            "framework_slug": "customs-alcohol",
            "control_id": "movement-evidence",
            "record_type": "attestation",
            "title": "Attempted cross-org link",
            "evidence_reference": "dispatch-note-x",
            "source_refs": [seeded_org_a["execution_id"]],
        },
    )
    assert response.status == 400, f"expected org A's execution id to be rejected, got {response.status}"
    assert "this organisation" in response.json()["error"]


def test_cross_tenant_report_returns_404_not_200_for_every_format(seeded_org_a):
    """AC: GET /api/compliant/reports/<report_id> for another org's real report id 404s
    -- must not distinguish "doesn't exist" from "exists in another org", and must 404
    for every ?format=, not just the default json."""
    page_b = seeded_org_a["pages"]["b"]
    report_id = seeded_org_a["report_id"]

    for fmt in (None, "json", "html", "csv"):
        url = f"/api/compliant/reports/{report_id}" + (f"?format={fmt}" if fmt else "")
        response = page_b.request.get(url)
        assert response.status == 404, f"format={fmt!r}: org B read org A's report ({response.status})"
        assert seeded_org_a["marker"] not in response.text(), f"format={fmt!r}: org A's data leaked into a 404 body"


def test_cross_tenant_report_creation_is_scoped_to_the_requesting_org(seeded_org_a, enable_profile, create_report):
    """Org B generating its own report for the same framework slug must not see org A's
    records folded in -- proves report generation itself is org-scoped, not just report
    retrieval by id."""
    page_b = seeded_org_a["pages"]["b"]
    enable_profile(page_b, enabled=True, settings={"alcohol_product_types": ["spirits"]})
    body = create_report(page_b, FRAMEWORK_SLUG)
    assert body["report"]["report_id"] != seeded_org_a["report_id"]
    assert seeded_org_a["marker"] not in str(body["report"]["payload"]), (
        "org A's record data leaked into org B's freshly generated report"
    )

    # Sanity: the probe is not inert -- org A can see its own report content.
    page_a = seeded_org_a["pages"]["a"]
    own = page_a.request.get(f"/api/compliant/reports/{seeded_org_a['report_id']}")
    assert own.status == 200
    assert seeded_org_a["marker"] in own.text(), "probe is inert: org A can't see its own record in its own report"
