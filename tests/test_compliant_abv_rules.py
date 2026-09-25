"""ABV on alcohol products: NZ-alcohol rules that make a workflow's final step require ABV.

The operator maps final-step output names with case-insensitive exact/contains rules (the
CRM's product-mapping shape). A matched final step gets a required "ABV (%)" field through
the Compliant -> Core workflow-rule seam, and Core refuses to complete it without a valid
value -- the UI prompt is not the security boundary.
"""

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.features.compliant.modules.nz_alcohol.workflow_rules import (
    ABV_PROMPT_LABEL,
    matching_abv_rule,
    validate_abv_rules,
)
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

CONTAINS_FINAL = {"pattern": "final product", "match_type": "contains"}


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        ("final product", "must be a list"),
        ([{"pattern": "gin"}], "match_type must be exact or contains"),
        ([{"pattern": "gin", "match_type": "regex"}], "match_type must be exact or contains"),
        ([{"pattern": "   ", "match_type": "contains"}], "pattern must be 1-255 characters"),
        ([{"pattern": "x" * 256, "match_type": "contains"}], "pattern must be 1-255 characters"),
        ([{"pattern": "gin", "match_type": "exact", "abv": 40}], "must be an object with pattern and match_type"),
        (
            [
                {"pattern": "Final Product", "match_type": "contains"},
                {"pattern": "final product ", "match_type": "contains"},
            ],
            "duplicate rule",
        ),
    ],
)
def test_abv_rules_are_validated(rules, message):
    error = validate_abv_rules(rules)
    assert error is not None and message in error


def test_abv_rule_matching_is_case_insensitive_and_exact_beats_contains():
    exact = {"pattern": "Solstice - Final Product", "match_type": "exact"}
    rules = [CONTAINS_FINAL, exact]

    assert matching_abv_rule("SOLSTICE - final product", rules) is exact
    assert matching_abv_rule("Wildflower - final product", rules) is CONTAINS_FINAL
    assert matching_abv_rule("Library stock", rules) is None
    assert matching_abv_rule("", rules) is None
    assert validate_abv_rules(rules) is None


def _two_workflows(db, org_id):
    """A two-step brewing workflow ending in a final product, and a one-step trial.

    The intermediate step's output deliberately *also* contains "final product", so a
    test only passes if ABV is scoped to the workflow's last step, not to any step whose
    output happens to match the phrase.
    """
    repo = ProcessRepository(db)
    beer = repo.create_process(org_id=org_id, name="Pale ale", description="", is_draft=False)
    mash = repo.add_step(
        process_id=beer.id,
        org_id=org_id,
        step_number=1,
        position=1000,
        name="Mash",
        inputs=[],
        outputs=[{"name": "Wort for final product", "quantity": "10", "unit": "L"}],
        execution_prompts=[],
    )
    package = repo.add_step(
        process_id=beer.id,
        org_id=org_id,
        step_number=2,
        position=2000,
        name="Package",
        inputs=[],
        outputs=[{"name": "Pale Ale - Final Product", "quantity": "24", "unit": "units"}],
        execution_prompts=[{"label": "Batch number", "type": "number", "required": False}],
    )
    trial = repo.create_process(org_id=org_id, name="Recipe trials", description="", is_draft=False)
    library = repo.add_step(
        process_id=trial.id,
        org_id=org_id,
        step_number=1,
        position=1000,
        name="Library stock",
        inputs=[],
        outputs=[{"name": "Library stock", "quantity": "100", "unit": "mL"}],
        execution_prompts=[],
    )
    db.commit()
    return beer, mash, package, library


def test_abv_rules_touch_only_their_own_setting_and_list_every_final_step(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    try:
        settings = {"alcohol_product_types": ["beer"], "np3_review_interval_months": 12}
        assert client.put("/api/compliant/profile", json={"enabled": True, "settings": settings}).status_code == 200
        _two_workflows(db, org.id)

        listed = client.get("/api/compliant/nz-alcohol/abv-rules").get_json()
        outputs = {candidate["output_name"] for candidate in listed["candidates"]}
        # Only each workflow's final step: the wort (step 1 of 2) is an intermediate.
        assert outputs == {"Pale Ale - Final Product", "Library stock"}
        assert listed["rules"] == []

        saved = client.put("/api/compliant/nz-alcohol/abv-rules", json={"rules": [CONTAINS_FINAL]})
        assert saved.status_code == 200
        by_output = {c["output_name"]: c["matched_rule"] for c in saved.get_json()["candidates"]}
        assert by_output["Pale Ale - Final Product"] == CONTAINS_FINAL
        assert by_output["Library stock"] is None

        profile_settings = client.get("/api/compliant/overview").get_json()["profile"]["settings"]
        assert profile_settings["abv_product_rules"] == [CONTAINS_FINAL]
        assert profile_settings["alcohol_product_types"] == ["beer"]  # untouched
        assert profile_settings["np3_review_interval_months"] == 12  # untouched

        bad = client.put(
            "/api/compliant/nz-alcohol/abv-rules", json={"rules": [{"pattern": "x", "match_type": "regex"}]}
        )
        assert bad.status_code == 400
        bad_profile = client.put(
            "/api/compliant/profile",
            json={"enabled": True, "settings": {"abv_product_rules": [{"pattern": "", "match_type": "exact"}]}},
        )
        assert bad_profile.status_code == 400
    finally:
        clear_org_synthetic_data(db, org.id)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_matched_final_step_requires_a_valid_abv_and_other_steps_do_not(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    try:
        client.put(
            "/api/compliant/profile",
            json={
                "enabled": True,
                "settings": {"alcohol_product_types": ["beer"], "abv_product_rules": [CONTAINS_FINAL]},
            },
        )
        beer, mash, package, library = _two_workflows(db, org.id)

        def abv_prompts(step_id=None):
            url = "/api/compliant/capture-context" + (f"?step_id={step_id}" if step_id else "")
            body = client.get(url).get_json()
            return [e["prompt"] for e in body["extensions"] if e["prompt"].get("label") == ABV_PROMPT_LABEL]

        assert abv_prompts() == []  # no step context -> only every-step rules
        assert abv_prompts(mash.id) == []  # not the final step
        assert abv_prompts(library.id) == []  # final step, but not an alcohol product
        (prompt,) = abv_prompts(package.id)
        assert prompt["type"] == "number" and prompt["required"] is True
        assert prompt["min"] == 0 and prompt["max"] == 100
        assert client.get("/api/compliant/capture-context?step_id=not-a-uuid").status_code == 400

        execution = ExecutionRepository(db).create_execution(org_id=org.id, process_id=beer.id)
        db.commit()
        first, last = sorted(execution.execution_steps, key=lambda s: s.step.position)
        complete = f"/api/core/executions/{execution.id}/steps/{{}}/complete"
        body = {"actual_inputs": [], "actual_outputs": []}

        # The intermediate step completes without any ABV.
        assert client.post(complete.format(first.id), json={**body, "execution_data": {}}).status_code == 200

        for bad_value in (None, "  ", "strong", "150", "-1"):
            data = {} if bad_value is None else {ABV_PROMPT_LABEL: bad_value}
            response = client.post(complete.format(last.id), json={**body, "execution_data": data})
            assert response.status_code == 409, bad_value
            assert response.get_json()["code"] == "compliance_requirement_not_met"
        db.refresh(last)
        assert last.status.value != "completed"

        ok = client.post(complete.format(last.id), json={**body, "execution_data": {ABV_PROMPT_LABEL: "5.2"}})
        assert ok.status_code == 200
        db.refresh(last)
        assert last.status.value == "completed"
        assert last.execution_data[ABV_PROMPT_LABEL] == "5.2"
    finally:
        clear_org_synthetic_data(db, org.id)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_abv_rule_still_applies_when_np3_evidence_capture_is_off(db, flask_app):  # noqa: F811
    """Turning the evidence shelf off must not stop an alcohol product's ABV being recorded."""
    org, client = _admin_client(db, flask_app)
    try:
        client.put(
            "/api/compliant/profile",
            json={
                "enabled": True,
                "settings": {"np3_execution_evidence_mode": "off", "abv_product_rules": [CONTAINS_FINAL]},
            },
        )
        _beer, _mash, package, _library = _two_workflows(db, org.id)
        extensions = client.get(f"/api/compliant/capture-context?step_id={package.id}").get_json()["extensions"]
        assert [e["prompt"]["label"] for e in extensions] == [ABV_PROMPT_LABEL]
    finally:
        clear_org_synthetic_data(db, org.id)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()
