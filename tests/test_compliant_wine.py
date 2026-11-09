"""Wine compliance in NZ Alcohol (docs/wine-compliance-plan.md, W1a).

Drives the real execution API: switching wine on adds the intake / cellar / bottle fields to
the winemaker's existing steps, Core refuses an intake without its trace fields, and the
Wine overview reads composition and the 85% label claims back through the lots each step
actually consumed -- no blend sheet typed anywhere.
"""

from __future__ import annotations

from datetime import date

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
            "Bottle": {ABV_PROMPT_LABEL: "12.5", rules.BOTTLE_SIZE: "750", "_qty": "850"},
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
