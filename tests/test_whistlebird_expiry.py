"""No expired ingredient is used, and expired stock is written off -- proven from the repository alone."""

from __future__ import annotations

import copy
import json
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.core.db import db_session
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_disposals as disposals  # noqa: E402
import whistlebird_legacy as legacy  # noqa: E402
import whistlebird_migration as wm  # noqa: E402
import whistlebird_replay as replay  # noqa: E402
import whistlebird_replay_simulation as simulation  # noqa: E402
from whistlebird_replay_timeline import DEFAULT_RAW_MATERIAL_MANIFEST, build_timeline  # noqa: E402

THROUGH = date(2026, 9, 19)
NZ = ZoneInfo("Pacific/Auckland")
PACKS = simulation.load_restock_packs(DEFAULT_RAW_MATERIAL_MANIFEST)


# --- the allocator ----------------------------------------------------------------------


def _lot(marker, quantity, expiry=None, name="Coriander seeds", unit="g", code=None):
    return {
        "id": marker,
        "name": name,
        "unit": unit,
        "quantity": Decimal(str(quantity)),
        "expiry_date": expiry,
        "ingredient_code": code,
    }


def test_an_expired_lot_is_skipped_and_the_next_lot_is_used():
    lots = [_lot("old", 100, date(2024, 1, 1)), _lot("new", 100, date(2026, 1, 1))]

    allocated, short = replay.allocate_fifo_lots(lots, "Coriander seeds", Decimal("30"), "g", date(2024, 6, 1))

    assert [a["inventory_item_id"] for a in allocated] == ["new"]
    assert short == 0


def test_a_lot_may_be_used_on_its_expiry_date_but_not_the_day_after():
    lots = [_lot("lot", 100, date(2024, 6, 1))]

    on_day, _ = replay.allocate_fifo_lots(lots, "Coriander seeds", Decimal("10"), "g", date(2024, 6, 1))
    next_day, short = replay.allocate_fifo_lots(lots, "Coriander seeds", Decimal("10"), "g", date(2024, 6, 2))

    assert [a["inventory_item_id"] for a in on_day] == ["lot"]
    assert next_day == [] and short == 10


def test_without_a_date_expiry_is_not_considered():
    allocated, _ = replay.allocate_fifo_lots(
        [_lot("old", 100, date(2020, 1, 1))], "Coriander seeds", Decimal("10"), "g"
    )

    assert [a["inventory_item_id"] for a in allocated] == ["old"]


def test_a_lot_with_no_expiry_is_always_usable():
    allocated, _ = replay.allocate_fifo_lots(
        [_lot("undated", 100, None)], "Coriander seeds", Decimal("10"), "g", date(2030, 1, 1)
    )

    assert [a["inventory_item_id"] for a in allocated] == ["undated"]


def test_a_lot_pinned_to_a_batch_is_never_drawn_by_the_fifo_fallback():
    lots = [_lot("pinned", 100, code="COR012"), _lot("free", 100, code="COR003")]

    allocated, _ = replay.allocate_fifo_lots(lots, "Coriander seeds", Decimal("10"), "g", None, frozenset({"COR012"}))

    assert [a["inventory_item_id"] for a in allocated] == ["free"]


def test_fifo_order_is_kept_across_lots_and_a_shortfall_is_reported():
    lots = [_lot("first", 30), _lot("second", 30)]

    allocated, short = replay.allocate_fifo_lots(lots, "Coriander seeds", Decimal("70"), "g")

    assert [(a["inventory_item_id"], a["quantity"]) for a in allocated] == [("first", "30"), ("second", "30")]
    assert short == 10


def test_spelling_variants_and_other_units_are_matched_as_the_replay_always_did():
    lots = [
        _lot("grams", 50, name="Juniper Berries (Macedonia)"),
        _lot("litres", 50, name="Juniper Berries (Macedonian)", unit="L"),
    ]

    allocated, _ = replay.allocate_fifo_lots(lots, "Juniper Berries (Macedonian)", Decimal("20"), "g")

    assert [a["inventory_item_id"] for a in allocated] == ["grams"]


# --- the whole replay's allocation, from the committed manifests --------------------------


@pytest.fixture(scope="module")
def sim():
    events = build_timeline(
        legacy.DEFAULT_LEGACY_SNAPSHOT, wm.DEFAULT_PRODUCTION_MANIFEST, DEFAULT_RAW_MATERIAL_MANIFEST
    )
    return simulation.simulate(events)


def test_no_expired_ingredient_is_used_anywhere_in_the_replay(sim):
    assert sim.uses_after_expiry == []


def test_every_step_is_backed_by_stock_the_api_would_accept(sim):
    assert sim.errors == []


def test_no_recipe_demand_is_left_unbacked_only_because_its_lots_had_expired(sim):
    """What remains unbacked are recipes that predate every receipt, which is unchanged history."""
    assert sim.gaps == []


def test_the_modelled_restock_purchases_are_well_formed_and_uniquely_coded():
    payload = json.loads(DEFAULT_RAW_MATERIAL_MANIFEST.read_text(encoding="utf-8"))
    restocks = [r for r in payload["inferred_records"] if "first_needed_by" in r]

    assert restocks, "the restock purchases are in the manifest"
    codes = [r["code"] for r in payload["clean_records"] + payload["inferred_records"]]
    assert len(codes) == len(set(codes)), "ingredient codes identify a lot, so must be unique"
    for record in restocks:
        assert record["confidence"] == "resolved_by_context"
        assert record["first_needed_by"]["global_vat"] and record["first_needed_by"]["product"]
        assert "consumed_by" not in record, "a restock is not pinned to the batch that first needed it"
        assert record["supplier_batch_number"], "the source map traces a lot by its batch number"
        assert record["source"].startswith("derived:"), "curation is labelled in the manifest, never in loaded rows"


def test_every_expired_lot_left_with_stock_is_in_the_disposals_manifest(sim):
    listed = {d.lot: d for d in disposals.load_disposals_manifest()}
    expired_with_stock = {
        lot.marker: lot
        for lot in sim.lots.values()
        if lot.expiry_date is not None and lot.expiry_date <= THROUGH and lot.quantity > 0
    }

    assert set(listed) == set(expired_with_stock)
    for marker, lot in expired_with_stock.items():
        assert listed[marker].quantity == lot.quantity, f"{marker}: the replay leaves {lot.quantity}"
        assert listed[marker].unit == lot.unit


def test_no_disposal_precedes_the_lots_expiry_or_its_last_use(sim):
    for disposal in disposals.load_disposals_manifest():
        lot = sim.lots[disposal.lot]
        assert disposal.on >= lot.expiry_date
        assert lot.last_used is None or disposal.on >= lot.last_used


def test_the_committed_manifests_are_exactly_what_the_planner_would_produce_now(sim):
    """A stale manifest (allocation changed, plan not re-run) shows up here rather than in a rebuild."""
    assert simulation.plan_restock(sim, PACKS) == []
    committed = json.loads(simulation.DEFAULT_DISPOSALS_MANIFEST.read_text(encoding="utf-8"))["disposals"]
    assert simulation.plan_disposals(sim, THROUGH) == committed


def test_every_maceration_event_reserves_every_pinned_lot_not_just_its_own():
    events = build_timeline(
        legacy.DEFAULT_LEGACY_SNAPSHOT, wm.DEFAULT_PRODUCTION_MANIFEST, DEFAULT_RAW_MATERIAL_MANIFEST
    )
    macerations = [
        e
        for e in events
        if e.event_type == "complete_step" and e.payload.get("step_key") in simulation.MACERATION_STEPS
    ]
    reserved = {e.payload["reserved_ingredient_codes"] for e in macerations}

    assert len(reserved) == 1, "one global set, identical on every maceration"
    (codes,) = reserved
    assert codes == {"CP019", "HF021", "DAS019"}, "only the VAT59 supplier lots, which are real receipts, stay pinned"
    own = next(e for e in macerations if e.payload["batch"].global_vat == 59).payload["known_input_quantities"]
    assert set(own) == codes


# --- real pack sizes, not per-batch sizes ------------------------------------------------------

# Founder-confirmed 2026-09-19 (botanicals the old manifest sized to one batch's use). Green tea: boxes of 20 bags.
FOUNDER_PACKS = {
    "Sumac berries - ground": (500, "g"),
    "Persian black lime": (500, "g"),
    "Dried mango slices": (1000, "g"),
    "Szechuan pepper": (500, "g"),
    "Orange peel - dried": (200, "g"),
    "Green tea": (20, "bags"),
}


def test_the_pack_sizes_are_the_ones_the_founder_confirmed():
    for name, (quantity, unit) in FOUNDER_PACKS.items():
        pack = PACKS[replay._canonical_material_name(name)]
        assert (pack.quantity, pack.unit) == (Decimal(quantity), unit), name


def test_every_modelled_purchase_is_a_whole_pack_never_a_batch_sized_lot():
    payload = json.loads(DEFAULT_RAW_MATERIAL_MANIFEST.read_text(encoding="utf-8"))
    restocks = [r for r in payload["inferred_records"] if "first_needed_by" in r]

    for record in restocks:
        pack = PACKS[replay._canonical_material_name(record["ingredient"])]
        assert (Decimal(str(record["quantity"])), record["unit"]) == (pack.quantity, pack.unit), record["code"]
    per_batch = [
        r
        for r in payload["inferred_records"]
        if "consumed_by" in r
        and "purchase_quantity" not in r
        and replay._canonical_material_name(r["ingredient"]) in PACKS
    ]
    assert per_batch == [], "no lot of a packed botanical is sized to a single batch's use"


def test_a_pack_purchase_is_drawn_down_by_many_batches(sim):
    """One purchase, many batches: the trace fans out from the lot, which is what a real purchase looks like.

    The one exception is a pack opened for the newest batch: nothing has come after it yet to draw it down.
    """
    restocks = {
        f"raw-manifest-{r['code']}"
        for r in json.loads(DEFAULT_RAW_MATERIAL_MANIFEST.read_text(encoding="utf-8"))["inferred_records"]
        if "first_needed_by" in r
    }
    batches_by_lot: dict[str, set[str]] = {}
    days_by_lot: dict[str, set[date]] = {}
    for use in sim.uses:
        batches_by_lot.setdefault(use.lot, set()).add(use.batch)
        days_by_lot.setdefault(use.lot, set()).add(use.on)
    newest_day = max(use.on for use in sim.uses)

    assert restocks <= set(sim.lots)
    for marker in restocks:
        if len(batches_by_lot.get(marker, ())) < 2:
            assert days_by_lot.get(marker) == {newest_day}, f"{marker} feeds a single batch that is not the newest"


def test_no_two_lots_of_one_material_share_a_supplier_batch_number():
    """inventory_items is unique on (org, name, supplier_batch_number); a clash would only fail mid-rebuild."""
    events = build_timeline(
        legacy.DEFAULT_LEGACY_SNAPSHOT, wm.DEFAULT_PRODUCTION_MANIFEST, DEFAULT_RAW_MATERIAL_MANIFEST
    )
    keys = [
        (
            replay._canonical_material_display_name(
                e.payload["record"].get("name") or e.payload["record"]["ingredient"]
            ),
            e.payload["record"]["supplier_batch_number"],
        )
        for e in events
        if e.event_type == "create_inventory_item" and e.payload["record"].get("supplier_batch_number")
    ]

    assert len(keys) == len(set(keys))


def test_dried_orange_peel_is_stock_and_only_fresh_orange_peel_is_untracked():
    tracked = {e["name"] for e in wm._WILDFLOWER_MACERATION_INPUTS if e["requires_inventory_selection"]}
    untracked = {e["name"] for e in wm._SOLSTICE_MACERATION_INPUTS if not e["requires_inventory_selection"]}

    assert "Orange peel - dried" in tracked
    assert "Orange peel" in untracked


def _sumac_restocks() -> list[dict]:
    payload = json.loads(DEFAULT_RAW_MATERIAL_MANIFEST.read_text(encoding="utf-8"))
    return [
        r for r in payload["inferred_records"] if "first_needed_by" in r and r["ingredient"] == "Sumac berries - ground"
    ]


def test_sumac_packs_expire_after_the_shelf_life_of_the_real_bag_and_are_bought_again():
    restocks = _sumac_restocks()

    assert len(restocks) >= 2, "one 500 g bag cannot last the two years of history"
    for record in restocks:
        bought = date.fromisoformat(record["date"])
        assert date.fromisoformat(record["expiry_date"]) == bought + timedelta(days=285), record["code"]


def test_sumac_packs_carry_supplier_batch_ids_that_look_like_real_lot_numbers():
    restocks = sorted(_sumac_restocks(), key=lambda r: r["date"])
    ids = [r["supplier_batch_number"] for r in restocks]

    assert all(re.fullmatch(r"\d{6}", batch) for batch in ids), ids
    assert all(batch != r["code"] for batch, r in zip(ids, restocks)), "not just the internal code"
    assert ids == sorted(ids), "lot numbers count up with time, as a supplier's do"
    assert len(set(ids)) == len(ids)


def test_a_green_tea_box_is_twenty_bags_and_a_vat_uses_four():
    pack = PACKS["green tea"]
    per_vat = next(e for e in wm._WILDFLOWER_MACERATION_INPUTS if e["name"] == "Green tea")

    assert (pack.quantity, pack.unit) == (Decimal(20), "bags")
    assert Decimal(per_vat["quantity"]) == 4 and per_vat["unit"] == "bags", "2 bags per flask, 2 flasks per VAT"


# --- the planner ---------------------------------------------------------------------------


def _short(on, name="Sumac berries - ground", quantity="7.2", unit="g", vat=29, batch="wildflower-vat29"):
    return simulation.Shortfall(on, batch, name, Decimal(quantity), unit, vat, "wildflower")


def _sim_with(*shortfalls, lots=()):
    sim = simulation.Simulation()
    sim.shortfalls.extend(shortfalls)
    for lot in lots:
        sim.lots[lot.marker] = lot
    return sim


def _old_lot(name="Sumac berries - ground", purchased=date(2024, 1, 1), code="SBG001"):
    return simulation.SimLot("raw-old", name, "g", Decimal("0"), purchased, None, code, "Moore Wilson", 0)


def test_the_planner_buys_one_whole_pack_for_the_earliest_shortfall_only():
    sim = _sim_with(_short(date(2025, 7, 17)), _short(date(2025, 9, 1), vat=36, batch="wildflower-vat36"))

    (record,) = simulation.plan_restock(sim, PACKS)

    assert (record["ingredient"], record["quantity"], record["unit"]) == ("Sumac berries - ground", 500, "g")
    assert record["date"] == "2025-07-14", "three days before the step that needed it"
    assert record["first_needed_by"] == {"global_vat": 29, "product": "wildflower"}
    assert "consumed_by" not in record
    assert record["code"] == "SBG001"


def test_codes_continue_after_the_highest_code_already_in_use():
    sim = _sim_with(_short(date(2025, 7, 17)), lots=[_old_lot(code="SBG007")])

    (record,) = simulation.plan_restock(sim, PACKS)

    assert record["code"] == "SBG008"


def test_a_recipe_that_predates_every_receipt_is_left_unbacked_not_restocked():
    sim = _sim_with(_short(date(2024, 1, 22)))

    assert simulation.plan_restock(sim, PACKS) == []


def test_a_recipe_after_an_earlier_receipt_ran_out_is_restocked_even_before_the_legacy_cutoff():
    sim = _sim_with(_short(date(2024, 6, 1)), lots=[_old_lot()])

    (record,) = simulation.plan_restock(sim, PACKS)

    assert record["date"] == "2024-05-29"


def test_an_ingredient_without_a_pack_size_is_never_restocked():
    assert simulation.plan_restock(_sim_with(_short(date(2025, 9, 1), name="Liquorice root")), PACKS) == []


@pytest.mark.parametrize(
    ("shortfall", "message"),
    [
        (_short(date(2025, 9, 1), quantity="501"), "more than one 500 g pack"),
        (_short(date(2025, 9, 1), unit="kg"), "sized in g"),
    ],
)
def test_the_planner_refuses_a_demand_a_single_pack_cannot_meet(shortfall, message):
    with pytest.raises(ValueError, match=message):
        simulation.plan_restock(_sim_with(shortfall), PACKS)


def test_the_planner_owns_restocks_and_per_batch_stand_ins_but_never_a_real_receipt():
    per_batch = {"ingredient": "Sumac berries - ground", "consumed_by": {"global_vat": 29}}
    real_receipt = {**per_batch, "ingredient": "Cardamom pods", "purchase_quantity": 500}

    assert simulation.is_modelled_record({"ingredient": "Sumac berries - ground", "first_needed_by": {}}, PACKS)
    assert simulation.is_modelled_record(per_batch, PACKS)
    assert not simulation.is_modelled_record(real_receipt, PACKS)
    assert not simulation.is_modelled_record({"ingredient": "Coriander seeds"}, PACKS)


def test_a_restock_orders_its_purchase_before_the_batch_without_pinning_it(tmp_path):
    from whistlebird_replay_timeline import _load_raw_material_manifest

    path = tmp_path / "raw.json"
    path.write_text(
        json.dumps(
            {
                "clean_records": [],
                "inferred_records": [
                    {"code": "SBG002", "quantity": 500, "unit": "g", "first_needed_by": {"global_vat": 29}},
                    {"code": "CP019", "quantity": 43.2, "unit": "g", "consumed_by": {"global_vat": 59}},
                ],
            }
        ),
        encoding="utf-8",
    )

    _records, codes_by_vat, known = _load_raw_material_manifest(path)

    assert codes_by_vat == {29: ["SBG002"], 59: ["CP019"]}
    assert known == {59: {"CP019": ("43.2", "g")}}, "only the exact-quantity receipt is pinned"


# --- the manifest --------------------------------------------------------------------------


def _raw() -> dict:
    return json.loads(disposals.DEFAULT_DISPOSALS_MANIFEST.read_text(encoding="utf-8"))


def _mutated(mutate) -> dict:
    data = copy.deepcopy(_raw())
    mutate(data)
    return data


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(surprise=1), "unknown key"),
        (lambda d: d.update(disposals="x"), "must be a list"),
        (lambda d: d["disposals"][0].update(colour="green"), "unknown key"),
        (lambda d: d["disposals"][0].pop("reason"), "missing"),
        (lambda d: d["disposals"][0].update(reason="   "), "reason is required"),
        (lambda d: d["disposals"][0].update(reason="x" * 501), "500 characters"),
        (lambda d: d["disposals"][0].update(quantity=0), "positive"),
        (lambda d: d["disposals"][0].update(quantity="lots"), "must be a number"),
        (lambda d: d["disposals"][0].update(date="19/09/2026"), "ISO date"),
        (lambda d: d["disposals"][0].update(lot="not-a-marker"), "import marker"),
        (lambda d: d["disposals"].append(dict(d["disposals"][0])), "duplicate lot"),
    ],
)
def test_a_malformed_disposals_manifest_is_rejected_before_any_request(mutate, message):
    with pytest.raises(disposals.DisposalManifestError, match=message):
        disposals.parse_disposals_manifest(_mutated(mutate))


# --- replaying a disposal ------------------------------------------------------------------


class _Store:
    def __init__(self, lots, disposed=()):
        self.lots = lots
        self.disposed = set(disposed)

    def raw_material_for_marker(self, marker):
        return self.lots.get(marker)

    def wastage_recorded_for_item(self, item_id):
        return item_id in self.disposed


class _Client:
    def __init__(self, response=None):
        self.calls = []
        self.response = response if response is not None else {"success": True}

    def post(self, path, body):
        self.calls.append((path, body))
        return self.response


def _disposal(**overrides):
    base = {
        "lot": "raw-legacy-purchases_ingredients-9",
        "ingredient": "butterfly pea flowers",
        "quantity": Decimal("500"),
        "unit": "g",
        "on": date(2024, 6, 1),
        "reason": "Expired 2024-06-01",
    }
    return disposals.Disposal(**{**base, **overrides})


def _lot_row(quantity="500.0000", unit="g"):
    return {"id": "item-1", "name": "butterfly pea flowers", "unit": unit, "quantity": Decimal(quantity)}


def test_a_disposal_goes_through_the_real_wastage_api_with_a_reason_and_an_idempotency_key():
    client = _Client()

    counts = disposals.replay_disposals(client, _Store({_disposal().lot: _lot_row()}), (_disposal(),))

    assert counts == {"disposed": 1, "skipped": 0}
    ((path, body),) = client.calls
    assert path == "/api/core/inventory/wastage"
    assert body["entries"] == [
        {
            "inventory_item_id": "item-1",
            "quantity_wasted": "500",
            "quantity_unit": "g",
            "reason": "Expired 2024-06-01",
        }
    ]
    assert body["idempotency_key"] == "whistlebird-disposal:raw-legacy-purchases_ingredients-9"


def test_replay_is_resumable_a_lot_already_written_off_is_skipped():
    client = _Client()

    counts = disposals.replay_disposals(client, _Store({_disposal().lot: _lot_row("0")}, {"item-1"}), (_disposal(),))

    assert counts == {"disposed": 0, "skipped": 1}
    assert client.calls == []


def test_replay_refuses_to_dispose_a_different_quantity_than_was_curated():
    client = _Client()

    with pytest.raises(disposals.DisposalReplayError, match="holds 480 g but the manifest expects 500"):
        disposals.replay_disposals(client, _Store({_disposal().lot: _lot_row("480")}), (_disposal(),))

    assert client.calls == [], "nothing is written off on a mismatch"


def test_replay_refuses_a_missing_lot_and_a_unit_mismatch_and_an_api_refusal():
    with pytest.raises(disposals.DisposalReplayError, match="no such lot"):
        disposals.replay_disposals(_Client(), _Store({}), (_disposal(),))
    with pytest.raises(disposals.DisposalReplayError, match="unit is 'L'"):
        disposals.replay_disposals(_Client(), _Store({_disposal().lot: _lot_row(unit="L")}), (_disposal(),))
    with pytest.raises(disposals.DisposalReplayError, match="refused"):
        disposals.replay_disposals(_Client({"success": False}), _Store({_disposal().lot: _lot_row()}), (_disposal(),))


# --- timestamps and verification against a real database -----------------------------------


@pytest.fixture
def db():
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture
def org(db):
    org = OrganisationRepository(db).create_org(f"Disposal Test Org {uuid4()}")
    db.commit()
    yield org

    db.rollback()
    db.query(InventoryMovement).filter(InventoryMovement.org_id == org.id).delete(synchronize_session=False)
    db.query(InventoryWastage).filter(InventoryWastage.org_id == org.id).delete(synchronize_session=False)
    db.query(EntityEvent).filter(EntityEvent.org_id == org.id).delete(synchronize_session=False)
    db.query(InventoryItem).filter(InventoryItem.org_id == org.id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def _url(db) -> str:
    return db.get_bind().url.render_as_string(hide_password=False)


def _lot_in_db(db, org, marker, quantity):
    item = InventoryRepository(db).create_inventory_item(
        org.id,
        name="butterfly pea flowers",
        quantity=quantity,
        unit="g",
        inventory_type="raw_material",
        extra_data={"import_ref": marker},
    )
    db.commit()
    return item


def _write_off(db, org, item, recorded_at=None):
    wastage = InventoryWastage(
        org_id=org.id, inventory_item_id=item.id, quantity_wasted="500", unit="g", reason="Expired 2024-06-01"
    )
    if recorded_at is not None:
        wastage.recorded_at = recorded_at
    db.add(wastage)
    db.flush()
    db.add(
        InventoryMovement(
            org_id=org.id,
            inventory_item_id=item.id,
            source_wastage_id=wastage.id,
            movement_type="WASTAGE",
            quantity=Decimal("-500"),
            unit="g",
        )
    )
    db.commit()
    return wastage


def _noon_nz(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time().replace(hour=12), tzinfo=NZ)


def test_timestamps_move_the_write_off_and_its_ledger_line_to_the_curated_date(db, org):
    item = _lot_in_db(db, org, "raw-test-lot-1", "0")
    _write_off(db, org, item)
    disposal = _disposal(lot="raw-test-lot-1")

    corrected = disposals.correct_disposal_timestamps(_url(db), org.name, (disposal,), _noon_nz)

    assert corrected == 1
    db.expire_all()
    wastage = db.query(InventoryWastage).filter(InventoryWastage.org_id == org.id).one()
    movement = db.query(InventoryMovement).filter(InventoryMovement.org_id == org.id).one()
    assert wastage.recorded_at.astimezone(NZ).date() == date(2024, 6, 1)
    assert movement.created_at == wastage.recorded_at


def test_verify_is_clean_after_a_correct_write_off_and_flags_a_missing_one_and_a_wrong_date(db, org):
    done = _lot_in_db(db, org, "raw-test-done", "0")
    _write_off(db, org, done, recorded_at=_noon_nz(date(2024, 6, 1)))
    untouched = _lot_in_db(db, org, "raw-test-untouched", "500")
    wrong_date = _lot_in_db(db, org, "raw-test-wrong-date", "0")
    _write_off(db, org, wrong_date, recorded_at=_noon_nz(date(2025, 1, 1)))
    url = _url(db)

    clean = disposals.verify_disposals(url, org.name, (_disposal(lot="raw-test-done"),))
    flagged = disposals.verify_disposals(
        url,
        org.name,
        (_disposal(lot="raw-test-untouched"), _disposal(lot="raw-test-wrong-date"), _disposal(lot="raw-test-done")),
    )

    assert clean["disposals_missing"]["actual"] == 0 and clean["disposal_date_mismatches"]["actual"] == 0
    assert flagged["disposals_missing"]["actual"] == 1, "the untouched lot still holds stock"
    assert flagged["disposal_date_mismatches"]["actual"] == 1, "the other was written off on the wrong date"
    assert untouched is not None


def test_verify_counts_no_expired_use_when_nothing_has_been_consumed(db, org):
    result = disposals.verify_disposals(_url(db), org.name, ())

    assert result["expired_lot_uses"] == {"expected": 0, "actual": 0}
