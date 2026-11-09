"""Wine compliance in NZ Alcohol (docs/wine-compliance-plan.md, W1a).

Drives the real execution API: switching wine on adds the intake / cellar / bottle fields to
the winemaker's existing steps, Core refuses an intake without its trace fields, and the
Wine overview reads composition and the 85% label claims back through the lots each step
actually consumed -- no blend sheet typed anywhere.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.features.compliant.modules.nz_alcohol.wine import label, roles, rules
from app.features.compliant.modules.nz_alcohol.wine.service import validate_plan
from app.features.compliant.modules.nz_alcohol.workflow_rules import ABV_PROMPT_LABEL
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

BODY = {"actual_inputs": [], "actual_outputs": []}


def _step(repo, org_id, process, n, name, output, unit):
    return repo.add_step(
        process_id=process.id,
        org_id=org_id,
        step_number=n,
        position=1000 * n,
        name=name,
        inputs=[],
        outputs=[{"name": output, "quantity": "1", "unit": unit}],
        execution_prompts=[],
    )


def _workflows(db, org_id):
    repo = ProcessRepository(db)
    intake_p = repo.create_process(org_id=org_id, name="Grape intake", description="", is_draft=False)
    intake = _step(repo, org_id, intake_p, 1, "Grape intake", "Grape lot", "kg")
    wine_p = repo.create_process(org_id=org_id, name="Sauvignon blanc", description="", is_draft=False)
    crush = _step(repo, org_id, wine_p, 1, "Crush and press", "Juice", "L")
    ferment = _step(repo, org_id, wine_p, 2, "Ferment", "Young wine", "L")
    cellar = _step(repo, org_id, wine_p, 3, "Cellar", "Finished wine", "L")
    bottle = _step(repo, org_id, wine_p, 4, "Bottle", "Bottled wine", "units")
    gin_p = repo.create_process(org_id=org_id, name="London dry gin", description="", is_draft=False)
    gin_bottle = _step(repo, org_id, gin_p, 1, "Bottling", "Gin 70cl", "units")
    db.commit()
    return (
        intake_p,
        wine_p,
        {"intake": intake, "crush": crush, "ferment": ferment, "cellar": cellar, "bottle": bottle},
        gin_bottle,
    )


@pytest.fixture
def wine_org(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    client.put(
        "/api/compliant/profile",
        json={
            "enabled": True,
            "settings": {
                "alcohol_product_types": ["wine", "spirits"],
                # A broad ABV mapping also matches the wine's final step: ABV must still be asked once.
                "abv_product_rules": [{"pattern": "wine", "match_type": "contains"}],
            },
        },
    )
    try:
        yield org, client
    finally:
        from app.core.db.models.lot_hold import LotHold
        from app.features.compliant.models import ComplianceRecord

        db.rollback()
        db.query(LotHold).filter(LotHold.org_id == org.id).delete(synchronize_session=False)
        db.query(ComplianceRecord).filter(ComplianceRecord.org_id == org.id).delete(synchronize_session=False)
        db.commit()
        clear_org_synthetic_data(db, org.id)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def _labels(client, step_id):
    body = client.get(f"/api/compliant/capture-context?step_id={step_id}").get_json()
    return [e["prompt"]["label"] for e in body["extensions"]]


def test_roles_are_inferred_only_inside_winemaking_processes(db, wine_org):
    org, _client = wine_org
    _i, _w, steps, gin_bottle = _workflows(db, org.id)
    found = roles.roles_for_org(db, org.id, {})
    assert {role: found.get(step.id) for role, step in steps.items()} == {r: r for r in steps}
    assert gin_bottle.id not in found  # a gin "Bottling" step is not a wine bottling step
    override = {roles.OVERRIDE_SETTING: {str(steps["cellar"].id): "none", str(gin_bottle.id): "bottle"}}
    found = roles.roles_for_org(db, org.id, override)
    assert steps["cellar"].id not in found and found[gin_bottle.id] == "bottle"


def test_wine_steps_ask_for_their_records_and_nothing_else_does(db, wine_org):
    org, client = wine_org
    _i, _w, steps, gin_bottle = _workflows(db, org.id)
    intake = _labels(client, steps["intake"].id)
    for label_ in (rules.GROWER, rules.VARIETY, rules.VINTAGE, rules.REGION, rules.SPRAY_DIARY):
        assert label_ in intake
    assert rules.SO2_ADDED in _labels(client, steps["cellar"].id)
    assert rules.VARIETY not in _labels(client, steps["crush"].id)
    bottle = _labels(client, steps["bottle"].id)
    assert bottle.count(ABV_PROMPT_LABEL) == 1 and rules.BOTTLE_SIZE in bottle
    assert not set(_labels(client, gin_bottle.id)) & {rules.BOTTLE_SIZE, rules.VARIETY, rules.SO2_ADDED}

    vintage = next(
        e["prompt"]
        for e in client.get(f"/api/compliant/capture-context?step_id={steps['intake'].id}").get_json()["extensions"]
        if e["prompt"]["label"] == rules.VINTAGE
    )
    assert vintage["default"] == rules.current_vintage()


def test_wine_rules_switch_off_with_the_product_type(db, wine_org):
    org, client = wine_org
    _i, _w, steps, _g = _workflows(db, org.id)
    client.put("/api/compliant/profile", json={"enabled": True, "settings": {"alcohol_product_types": ["spirits"]}})
    assert rules.VARIETY not in _labels(client, steps["intake"].id)
    assert client.get("/api/compliant/wine").get_json() == {"enabled": False}


def _run(db, client, org_id, process_id, data_by_step, inputs_by_step=None):
    execution = ExecutionRepository(db).create_execution(org_id=org_id, process_id=process_id)
    db.commit()
    lots = {}
    for es in sorted(execution.execution_steps, key=lambda s: s.step.position):
        name = es.step.name
        out = es.step.outputs[0]
        quantity = data_by_step.get(name, {}).pop("_qty", "100")
        outputs = [{"name": out["name"], "quantity": quantity, "unit": out["unit"]}]
        body = {
            "actual_inputs": (inputs_by_step or {}).get(name, []),
            "actual_outputs": outputs,
            "execution_data": data_by_step.get(name, {}),
        }
        response = client.post(f"/api/core/executions/{execution.id}/steps/{es.id}/complete", json=body)
        assert response.status_code == 200, (name, response.get_json())
        lot = db.query(InventoryItem).filter(InventoryItem.source_execution_step_id == es.id).one()
        lots[name] = lot
        nxt = [{"inventory_item_id": str(lot.id), "name": lot.name, "quantity": quantity, "unit": out["unit"]}]
        # each later step consumes all of the previous step's output
        idx = [s.step.name for s in sorted(execution.execution_steps, key=lambda s: s.step.position)].index(name)
        later = sorted(execution.execution_steps, key=lambda s: s.step.position)[idx + 1 : idx + 2]
        if later:
            inputs_by_step = inputs_by_step or {}
            inputs_by_step.setdefault(later[0].step.name, nxt)
    return lots


def test_intake_without_its_trace_fields_is_refused(db, wine_org):
    org, client = wine_org
    intake_p, _w, _s, _g = _workflows(db, org.id)
    execution = ExecutionRepository(db).create_execution(org_id=org.id, process_id=intake_p.id)
    db.commit()
    (es,) = execution.execution_steps
    url = f"/api/core/executions/{execution.id}/steps/{es.id}/complete"
    missing = client.post(url, json={**BODY, "execution_data": {rules.GROWER: "Block 4", rules.VINTAGE: "2026"}})
    assert missing.status_code == 409
    assert missing.get_json()["code"] == "compliance_requirement_not_met"
    assert "Variety" in missing.get_json()["error"]
    bad_year = client.post(
        url,
        json={**BODY, "execution_data": {rules.GROWER: "Block 4", rules.VARIETY: "Pinot noir", rules.VINTAGE: "1850"}},
    )
    assert bad_year.status_code == 409


def test_blend_composition_and_label_preflight_come_from_the_trace(db, wine_org):
    org, client = wine_org
    intake_p, wine_p, _s, _g = _workflows(db, org.id)
    sb = _run(
        db, client, org.id, intake_p.id,
        {"Grape intake": {rules.GROWER: "Block 4", rules.VARIETY: "Sauvignon blanc", rules.VINTAGE: "2026",
                          rules.REGION: "Marlborough", "_qty": "900"}},
    )["Grape intake"]  # fmt: skip
    pg = _run(
        db, client, org.id, intake_p.id,
        {"Grape intake": {rules.GROWER: "Smith Vineyard", rules.VARIETY: "Pinot gris", rules.VINTAGE: "2026",
                          rules.REGION: "Nelson", "_qty": "100"}},
    )["Grape intake"]  # fmt: skip
    crush_inputs = [
        {"inventory_item_id": str(sb.id), "name": sb.name, "quantity": "900", "unit": "kg"},
        {"inventory_item_id": str(pg.id), "name": pg.name, "quantity": "100", "unit": "kg"},
    ]
    _run(
        db, client, org.id, wine_p.id,
        {
            "Crush and press": {"_qty": "700"},
            "Ferment": {"_qty": "650"},
            "Cellar": {rules.SO2_ADDED: "35", rules.FINING: "Egg (albumin)", "_qty": "640"},
            "Bottle": {ABV_PROMPT_LABEL: "12.5", rules.BOTTLE_SIZE: "750", rules.RELEASE: rules.RELEASE_YES,
                       "_qty": "850"},
        },
        {"Crush and press": crush_inputs},
    )  # fmt: skip

    body = client.get("/api/compliant/wine").get_json()
    assert body["enabled"] is True
    assert body["vintage"]["intake_lots"] == 2 and body["vintage"]["intake_kg"] == 1000.0
    assert body["plan"]["litres_made"] == 650.0  # the ferment output is "wine made"
    (pre,) = body["preflight"]
    comp = pre["lot"]["composition"]
    assert comp["variety"][0] == {"value": "Sauvignon blanc", "share": 0.9}
    assert comp["claims"]["variety"]["status"] == "pass"
    assert comp["claims"]["vintage"] == {"status": "pass", "value": "2026", "share": 1.0}
    assert comp["growers"] == ["Block 4", "Smith Vineyard"]
    assert comp["allergens"] == ["egg"] and comp["so2_mg_per_l"] == 35.0
    items = {i["key"]: i for i in pre["items"]}
    assert items["standard-drinks"]["detail"].startswith("Approx. 7.4 standard drinks")
    assert items["sulphites"]["status"] == "declare"
    assert items["allergens"]["status"] == "review"
    assert items["claim-variety"]["status"] == "ok"
    assert items["pregnancy"]["status"] == "declare"


def test_an_85_15_blend_passes_but_80_20_cannot_name_one_variety():
    from decimal import Decimal

    from app.features.compliant.modules.nz_alcohol.wine.composition import Composition, claims

    passing = Composition(variety={"Pinot noir": Decimal("0.85"), "Syrah": Decimal("0.15")})
    failing = Composition(variety={"Pinot noir": Decimal("0.80"), "Syrah": Decimal("0.20")})
    assert claims(passing)["variety"]["status"] == "pass"
    assert claims(failing)["variety"]["status"] == "fail"
    estimated = Composition(variety={"Pinot noir": Decimal("0.9")}, estimated=True)
    assert claims(estimated)["variety"]["status"] == "review"


def test_standard_drinks_matches_the_research_worked_example():
    from decimal import Decimal

    assert label.standard_drinks(Decimal(750), Decimal("12.5")) == Decimal("7.4")


def test_plan_validation_and_exemption_meter(db, wine_org):
    org, client = wine_org
    with pytest.raises(ValueError, match="registered plan or the small winemaker exemption"):
        validate_plan({"mode": "maybe"})
    with pytest.raises(ValueError, match="exemption started"):
        validate_plan({"mode": "exempt"})
    assert client.put("/api/compliant/wine/plan", json={"mode": "exempt", "exemption_start": "bad"}).status_code == 400
    start = date(date.today().year - 1, 3, 1).isoformat()
    ok = client.put("/api/compliant/wine/plan", json={"mode": "exempt", "exemption_start": start})
    assert ok.status_code == 200
    plan = client.get("/api/compliant/wine").get_json()["plan"]
    assert plan["mode"] == "exempt" and plan["exemption_limit_l"] == 20000.0
    assert plan["exemption_expires"].startswith(str(date.today().year + 1))


# ---------------------------------------------------------------------------------------
# Every-requirement register (plan §6)
# ---------------------------------------------------------------------------------------


def _bottled_org(db, client, org_id, release=rules.RELEASE_YES):
    intake_p, wine_p, _s, _g = _workflows(db, org_id)
    lot = _run(
        db, client, org_id, intake_p.id,
        {"Grape intake": {rules.GROWER: "Block 1", rules.VARIETY: "Pinot noir", rules.VINTAGE: str(rules.current_vintage()),
                          rules.REGION: "Central Otago", rules.SPRAY_DIARY: "Yes", "_qty": "1000"}},
    )["Grape intake"]  # fmt: skip
    lots = _run(
        db, client, org_id, wine_p.id,
        {"Crush and press": {"_qty": "700"}, "Ferment": {"_qty": "650"}, "Cellar": {rules.SO2_ADDED: "30", "_qty": "640"},
         "Bottle": {ABV_PROMPT_LABEL: "13.5", rules.BOTTLE_SIZE: "750", rules.RELEASE: release, "_qty": "850"}},
        {"Crush and press": [{"inventory_item_id": str(lot.id), "name": lot.name, "quantity": "1000", "unit": "kg"}]},
    )  # fmt: skip
    return lots["Bottle"]


def test_bottling_refuses_without_a_release_decision(db, wine_org):
    org, client = wine_org
    _i, wine_p, _s, _g = _workflows(db, org.id)
    execution = ExecutionRepository(db).create_execution(org_id=org.id, process_id=wine_p.id)
    db.commit()
    rows = sorted(execution.execution_steps, key=lambda s: s.step.position)
    for es in rows[:3]:
        assert client.post(f"/api/core/executions/{execution.id}/steps/{es.id}/complete", json=BODY).status_code == 200
    bottle = rows[3]
    url = f"/api/core/executions/{execution.id}/steps/{bottle.id}/complete"
    refused = client.post(url, json={**BODY, "execution_data": {ABV_PROMPT_LABEL: "13", rules.BOTTLE_SIZE: "750"}})
    assert refused.status_code == 409 and "released for sale" in refused.get_json()["error"]


def test_checklist_reads_production_and_records(db, wine_org):
    org, client = wine_org
    client.put("/api/compliant/wine/plan", json={"mode": "registered", "plan_reference": "WSMP 9", "verifier": "AsureQuality"})
    _bottled_org(db, client, org.id)
    body = client.get("/api/compliant/wine").get_json()
    (wsmp,) = [g for g in body["checklist"] if g["framework"] == "wine-standards"]
    items = {i["control"]: i for i in wsmp["items"]}
    assert "small-winemaker-exemption" not in items  # registered, not exempt
    assert items["wsmp-registration"]["status"] == "ok" and items["wsmp-registration"]["source"] == "production"
    assert items["grape-intake"]["status"] == "ok" and "1 of 1" in items["grape-intake"]["detail"]
    assert items["lab-release"]["status"] == "ok"
    assert items["recall"]["status"] == "missing"
    assert items["water"]["status"] == "missing"
    assert {g["framework"] for g in body["checklist"]} == {"wine-standards"}  # no export/SWNZ/organic switched on

    saved = client.post(
        "/api/compliant/wine/records",
        json={"framework": "wine-standards", "control": "water", "title": "Bore water test: clear",
              "next_due": (date.today().replace(year=date.today().year + 1)).isoformat(), "evidence_reference": "Lab 4471"},
    )  # fmt: skip
    assert saved.status_code == 201, saved.get_json()
    items = {i["control"]: i for i in client.get("/api/compliant/wine").get_json()["checklist"][0]["items"]}
    assert items["water"]["status"] == "ok"
    bad = client.post("/api/compliant/wine/records", json={"framework": "wine-export", "control": "batch-eligibility", "title": "x"})
    assert bad.status_code == 400 and "doesn't apply" in bad.get_json()["error"]


def test_a_problem_report_starts_the_24_hour_clock_and_holds_the_wine(db, wine_org):
    from app.core.db.models.lot_hold import LotHold

    org, client = wine_org
    lot = _bottled_org(db, client, org.id)
    reported = client.post(
        "/api/compliant/wine/problems",
        json={"kind": "critical", "description": "Glass fragment found in a bottle", "lot_id": str(lot.id)},
    )
    assert reported.status_code == 201, reported.get_json()
    body = reported.get_json()
    assert body["held"] is True and body["record"]["status"] == "open"
    assert body["record"]["due_date"] == (date.today() + timedelta(days=1)).isoformat() or body["record"]["due_date"] == date.today().isoformat()
    hold = db.query(LotHold).filter(LotHold.org_id == org.id, LotHold.inventory_item_id == lot.id, LotHold.released_at.is_(None)).one()
    assert "Glass fragment" in hold.reason
    items = {i["control"]: i for i in client.get("/api/compliant/wine").get_json()["checklist"][0]["items"]}
    assert items["nonconformance"]["status"] in ("due", "overdue")


def test_label_approval_lapses_when_the_wine_changes(db, wine_org):
    org, client = wine_org
    lot = _bottled_org(db, client, org.id)

    def approval():
        (pf,) = client.get("/api/compliant/wine").get_json()["preflight"]
        return next(i for i in pf["items"] if i["key"] == "label-approval")

    assert approval()["detail"] == "Not approved yet."
    ok = client.post(f"/api/compliant/wine/lots/{lot.id}/label-approval", json={"label_version": "v3"})
    assert ok.status_code == 201, ok.get_json()
    assert approval()["status"] == "ok"
    # Something behind the label changes: the recorded ABV is corrected.
    from app.core.db.models.execution_step import ExecutionStep

    step = db.query(ExecutionStep).filter(ExecutionStep.id == lot.source_execution_step_id).one()
    step.execution_data = {**step.execution_data, ABV_PROMPT_LABEL: "14"}
    db.commit()
    assert approval()["status"] == "review" and "lapsed" in approval()["detail"]


def test_export_register_enforces_eligibility_volume_expiry_and_samples(db, wine_org):
    org, client = wine_org
    lot = _bottled_org(db, client, org.id)
    refused = client.post("/api/compliant/wine/export/eligibility", json={"lot_id": str(lot.id)})
    assert "Turn on exporting" in refused.get_json()["error"]
    client.put("/api/compliant/wine/plan", json={"mode": "registered", "plan_reference": "WSMP 9", "wine_exporter": True})
    granted = (date.today() - timedelta(days=10)).isoformat()
    ok = client.post(
        "/api/compliant/wine/export/eligibility",
        json={"lot_id": str(lot.id), "form": "packaged", "granted_on": granted, "ees_reference": "EES-1",
              "eligible_litres": "500", "markets": "GB, AU"},
    )  # fmt: skip
    assert ok.status_code == 201, ok.get_json()
    elig = ok.get_json()["record"]["id"]

    def ship(**kw):
        body = {"kind": "commercial", "litres": "300", "shipped_on": date.today().isoformat(), "market": "GB",
                "consignee": "London Wines", "customs_entry": "TSW-1", "eligibility_id": elig, **kw}  # fmt: skip
        return client.post("/api/compliant/wine/export/consignments", json=body)

    assert ship().status_code == 201
    over = ship()  # 300 more would pass 500 eligible
    assert over.status_code == 400 and "200 L" in over.get_json()["error"]
    assert "doesn't cover US" in ship(market="US", litres="10").get_json()["error"]
    assert "Customs export entry" in ship(customs_entry="", litres="10").get_json()["error"]
    late = (date.today() + timedelta(days=800)).isoformat()
    assert "expired" in ship(shipped_on=late, litres="10").get_json()["error"]
    big_sample = ship(kind="trade_sample", litres="111", eligibility_id=None, not_for_sale_marked=True)
    assert "110 L" in big_sample.get_json()["error"]
    unmarked = ship(kind="trade_sample", litres="20", eligibility_id=None)
    assert "not for sale" in unmarked.get_json()["error"]
    assert ship(kind="trade_sample", litres="20", eligibility_id=None, not_for_sale_marked=True).status_code == 201
    assert "27 L" in ship(kind="small_trade", litres="28").get_json()["error"]
    reg = client.get("/api/compliant/wine").get_json()["export"]
    (row,) = reg["eligibilities"]
    assert row["exported_litres"] == 300.0 and row["remaining_litres"] == 200.0  # samples don't use eligibility
    assert reg["levy"]["litres_exported"] == 300.0 and reg["levy"]["levy_due"] == 0.0


def test_exempt_makers_cannot_export(db, wine_org):
    org, client = wine_org
    lot = _bottled_org(db, client, org.id)
    start = date(date.today().year - 1, 3, 1).isoformat()
    refused = client.put("/api/compliant/wine/plan", json={"mode": "exempt", "exemption_start": start, "wine_exporter": True})
    assert refused.status_code == 400 and "can't be exported" in refused.get_json()["error"]
    client.put("/api/compliant/wine/plan", json={"mode": "exempt", "exemption_start": start})
    no = client.post(
        "/api/compliant/wine/export/eligibility",
        json={"lot_id": str(lot.id), "form": "bulk", "granted_on": start, "ees_reference": "E", "eligible_litres": "5"},
    )
    assert no.status_code == 400 and "can't be exported" in no.get_json()["error"]


def test_unreleased_wine_cannot_get_export_eligibility(db, wine_org):
    org, client = wine_org
    lot = _bottled_org(db, client, org.id, release=rules.RELEASE_NOT_YET)
    client.put("/api/compliant/wine/plan", json={"mode": "registered", "wine_exporter": True})
    no = client.post(
        "/api/compliant/wine/export/eligibility",
        json={"lot_id": str(lot.id), "form": "packaged", "granted_on": date.today().isoformat(), "ees_reference": "E",
              "eligible_litres": "5"},
    )  # fmt: skip
    assert no.status_code == 400 and "Release this lot" in no.get_json()["error"]


def test_trace_and_mass_balance_for_a_wine_officer(db, wine_org):
    org, client = wine_org
    lot = _bottled_org(db, client, org.id)
    body = client.get(f"/api/compliant/wine/lots/{lot.id}/trace").get_json()
    stages = [s["stage"] for s in body["steps"]]
    assert stages[0] == "Bottle" and stages[-1] == "Grape intake"
    ferment = next(s for s in body["steps"] if s["stage"] == "Ferment")
    assert ferment["used"] == 700.0 and ferment["made"] == 650.0 and ferment["loss_pct"] == 7.1
    intake = body["steps"][-1]
    assert intake["source"]["grower"] == "Block 1" and intake["source"]["spray_diary"] == "Yes"
    csv_text = client.get(f"/api/compliant/wine/lots/{lot.id}/trace?format=csv").get_data(as_text=True)
    assert csv_text.splitlines()[0].startswith("Lot,Stage") and "Block 1" in csv_text
    assert client.get("/api/compliant/wine/lots/not-a-uuid/trace").status_code == 404


def test_optional_frameworks_follow_their_switches(db, wine_org):
    _org, client = wine_org
    client.put("/api/compliant/wine/plan", json={"mode": "registered", "wine_exporter": True, "wine_swnz": True, "wine_organic": True})
    names = {g["framework"] for g in client.get("/api/compliant/wine").get_json()["checklist"]}
    assert names == {"wine-standards", "wine-export", "swnz", "organic-wine"}
