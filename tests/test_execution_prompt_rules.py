from app.core.domain.execution_prompt_rules import validate_execution_prompts


def test_required_prompt_and_select_choice_are_enforced():
    prompts = [
        {"label": "QC result", "type": "select", "required": True, "options": ["Pass", "Hold"]},
        {"label": "Operator note", "type": "text", "required": True},
        {"label": "Photo", "type": "evidence", "required": True},
    ]

    assert validate_execution_prompts(prompts, {"QC result": "Pass", "Operator note": "Looks good"}) == []
    assert validate_execution_prompts(prompts, {"QC result": "", "Operator note": "Looks good"}) == [
        'Please fill in required field: "QC result"'
    ]
    assert validate_execution_prompts(prompts, {"QC result": "Rework", "Operator note": "Looks good"}) == [
        'Field "QC result" must be one of: Pass, Hold'
    ]


def test_legacy_select_without_choices_stays_operable():
    prompts = [{"label": "Legacy grade", "type": "select", "required": True}]

    assert validate_execution_prompts(prompts, {"Legacy grade": "A"}) == []
