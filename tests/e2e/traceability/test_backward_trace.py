"""AC7: backward trace from a WIP/final item includes the traced item itself.

The historical bug (spec: cursor_instructions/sourcemap-v2.md sec 7a) was that
`trace_backward` only returns SOURCE items, so the traced item's own row was missing from
`all_items`/the table. AC8 is the paired guarantee: `intermediates`/`raw_materials`
nonetheless exclude the traced item -- it appears once, in `all_items`/`traced_item`, not
duplicated into the source lists.
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_ac7_backward_trace_api_includes_traced_item_in_all_items(traced_chain):
    page, dag, _user = traced_chain

    resp = page.request.get(f"/api/core/inventory/trace-backward/{dag['w1_id']}")
    assert resp.status == 200, resp.text()
    body = resp.json()

    assert body["traced_item"]["id"] == str(dag["w1_id"])
    all_ids = {item["id"] for item in body["all_items"]}
    assert str(dag["w1_id"]) in all_ids, "AC7: traced item itself must be present in all_items"
    assert str(dag["r1_id"]) in all_ids, "the source raw material must also be present"

    # AC8: source lists exclude the traced item; connections only reference ids in the response.
    assert str(dag["w1_id"]) not in {item["id"] for item in body["intermediates"]}
    assert str(dag["w1_id"]) not in {item["id"] for item in body["raw_materials"]}
    for conn in body["connections"]:
        assert conn["from_id"] in all_ids
        assert conn["to_id"] in all_ids


def test_ac7_backward_trace_connections_are_non_empty(traced_chain):
    """The AC8 loop above (every connection references a response id) would pass
    vacuously on an empty connections list -- assert R1->W1 is actually present, not
    just that whatever connections exist are well-formed."""
    page, dag, _user = traced_chain

    resp = page.request.get(f"/api/core/inventory/trace-backward/{dag['w1_id']}")
    assert resp.status == 200, resp.text()
    body = resp.json()

    assert body["connections"], "backward trace from W1 must report at least one connection"
    assert any(
        c["from_id"] == str(dag["r1_id"]) and c["to_id"] == str(dag["w1_id"]) for c in body["connections"]
    ), f"expected an R1->W1 connection, got: {body['connections']}"


def test_ac7_backward_trace_from_wip_card_shows_traced_item_in_table(traced_chain):
    page, _dag, _user = traced_chain
    page.goto("/core/sourcemap")
    page.wait_for_load_state("networkidle")

    card = page.locator(".sm-browse-card", has_text="W1").first
    expect(card).to_be_visible()
    card.click()

    expect(page.locator(".sm-impact-header__item-name")).to_have_text("W1")

    page.get_by_role("tab", name="Table").click()
    table_body = page.locator("#sm-table-body")
    # AC7: the table (built from all_items) includes both the traced item (W1) and its
    # source (R1) -- not just the source, which was the historical bug.
    expect(table_body).to_contain_text("W1")
    expect(table_body).to_contain_text("R1")
    # Step hand-offs have their own rows; the two inventory materials appear once each.
    expect(page.locator("#sm-table-body tr.sm-trace-row--material")).to_have_count(2)


def test_backward_trace_from_final_item_includes_traced_item_itself(traced_chain):
    """AC7 again, but rooted at F1 (the other backward-trace entry point: any inventory
    item, not just WIP) -- W1 and R1 are both upstream sources of F1."""
    page, dag, _user = traced_chain

    resp = page.request.get(f"/api/core/inventory/trace-backward/{dag['f1_id']}")
    assert resp.status == 200, resp.text()
    body = resp.json()

    all_ids = {item["id"] for item in body["all_items"]}
    assert str(dag["f1_id"]) in all_ids
    assert str(dag["w1_id"]) in all_ids
    assert str(dag["r1_id"]) in all_ids
    assert body["traced_item"]["id"] == str(dag["f1_id"])
