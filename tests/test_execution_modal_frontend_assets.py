"""Lightweight guardrails for execution UI refactor (Parts 2–3).

Avoids browser automation; asserts shipped assets still contain expected anchors.
"""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_execution_modal_css_defines_inventory_picker_classes():
    css_path = _REPO_ROOT / "app" / "core" / "frontend" / "css" / "execution-modal.css"
    text = css_path.read_text(encoding="utf-8")
    assert ".exec-picker-card" in text
    assert ".exec-picker-chip--danger" in text


def test_execution_modal_js_does_not_inject_legacy_picker_style_tag():
    """Picker rules moved to execution-modal.css (no duplicate mega inline blob)."""
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal.js"
    text = js_path.read_text(encoding="utf-8")
    assert "execution-modal-picker-styles" not in text


def test_refresh_execution_inventory_handles_page_embed():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal-secondary.js"
    text = js_path.read_text(encoding="utf-8")
    assert "pageEmbed" in text
    assert "batch-start-spa" in text


def test_execution_shared_utils_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-shared-utils.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "convertUnit" in body and "prettyLabel" in body


def test_execution_ui_utils_defines_execution_ui():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-ui-utils.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "ExecutionUI" in body and "setRenderMode" in body


def test_execution_doc_overlay_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-doc-overlay.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "openDocFullScreenOverlay" in body


def test_execution_modal_does_not_define_doc_overlay_inline():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal.js"
    text = js_path.read_text(encoding="utf-8")
    assert "openDocFullScreenOverlay" not in text


def test_execution_session_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-session.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "ExecutionSessionAPI" in body and "resetForOpen" in body and "WeakMap" in body


def test_batch_start_loads_session_before_execution_modal():
    """batch-start includes shared stack; stack order: … doc-overlay → render-docs → … execution-modal."""
    # The stack include lives in the batch-start-scripts.html partial (moved there so scripts
    # sit inside #page-content for HTMX swap compatibility).
    scripts_path = _REPO_ROOT / "app" / "core" / "frontend" / "processes" / "batch-start-scripts.html"
    assert scripts_path.is_file()
    batch_text = scripts_path.read_text(encoding="utf-8")
    assert "execution_modal_stack_scripts.html" in batch_text
    stack_path = _REPO_ROOT / "app" / "core" / "frontend" / "shared" / "execution_modal_stack_scripts.html"
    text = stack_path.read_text(encoding="utf-8")
    i_utils = text.find("execution-shared-utils.js")
    i_session = text.find("execution-session.js")
    i_doc_overlay = text.find("execution-doc-overlay.js")
    i_docs = text.find("execution-render-docs.js")
    i_prompts = text.find("execution-render-prompts.js")
    i_inv_utils = text.find("inventory-type-utils.js")
    i_inv_display = text.find("inventory-display.js")
    i_inv_picker = text.find("inventory-picker-controller.js")
    i_inv_pick_view = text.find("execution-inventory-picker-view.js")
    i_inv_row = text.find("execution-inventory-row-renderer.js")
    i_inputs = text.find("execution-render-inputs.js")
    i_outputs = text.find("execution-render-outputs.js")
    i_submit = text.find("execution-submit.js")
    i_secondary = text.find("execution-modal-secondary.js")
    i_open = text.find("execution-open-step.js")
    i_modal = text.find("execution-modal.js")
    assert (
        0
        < i_utils
        < i_session
        < i_doc_overlay
        < i_docs
        < i_prompts
        < i_inv_utils
        < i_inv_display
        < i_inv_picker
        < i_inv_pick_view
        < i_inv_row
        < i_inputs
        < i_outputs
        < i_submit
        < i_secondary
        < i_open
        < i_modal
    )


def test_execution_modal_calls_render_docs_api():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal.js"
    text = js_path.read_text(encoding="utf-8")
    assert "ExecutionRenderDocs.renderStepDocumentation" in text


def test_execution_open_step_module_calls_render_docs():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-open-step.js"
    assert js_path.is_file()
    text = js_path.read_text(encoding="utf-8")
    assert "ExecutionOpenStep" in text
    assert "ExecutionRenderDocs.renderStepDocumentation" in text


def test_execution_modal_delegates_open_to_open_step():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal.js"
    text = js_path.read_text(encoding="utf-8")
    assert "ExecutionOpenStep.openExecutionModal" in text
    assert "loadOrgUsersMap" in text


def test_execution_render_prompts_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-render-prompts.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "ExecutionRenderPrompts" in body and "renderExecutionPrompts" in body


def test_execution_modal_calls_render_prompts_api():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal.js"
    text = js_path.read_text(encoding="utf-8")
    assert "ExecutionRenderPrompts.renderExecutionPrompts" in text


def test_execution_render_outputs_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-render-outputs.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "ExecutionRenderOutputs" in body and "renderVariableOutputs" in body


def test_execution_modal_calls_render_outputs_api():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal.js"
    text = js_path.read_text(encoding="utf-8")
    assert "ExecutionRenderOutputs.renderVariableOutputs" in text


def test_execution_submit_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-submit.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "ExecutionSubmit" in body and "submitExecution" in body


def test_execution_modal_delegates_submit_to_execution_submit():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal.js"
    text = js_path.read_text(encoding="utf-8")
    assert "window.ExecutionSubmit.submitExecution" in text
    assert "SessionAPI: SessionAPI" in text
    assert "convertUnit: convertUnit" in text
    assert "getCurrentUser: window.getCurrentUser" in text


def test_execution_modal_secondary_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal-secondary.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "ExecutionModalSecondary" in body and "install" in body
    assert "refreshExecutionModalInventory" in body


def test_execution_modal_installs_secondary_flows():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal.js"
    text = js_path.read_text(encoding="utf-8")
    assert "ExecutionModalSecondary.install" in text


def test_execution_render_docs_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-render-docs.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "ExecutionRenderDocs" in body and "renderStepDocumentation" in body


def test_inventory_type_utils_defines_matches_search():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "inventory-type-utils.js"
    body = js_path.read_text(encoding="utf-8")
    assert "matchesSearch" in body and "buildInventorySearchHayLower" in body


def test_inventory_picker_controller_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "inventory-picker-controller.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "InventoryPickerController" in body and "create" in body


def test_execution_inventory_picker_view_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-inventory-picker-view.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "ExecutionInventoryPickerView" in body and "buildPayload" in body and "buildDetailsFragment" in body
    assert "chipsFragment" in body and "metaGridEl" in body and "appendMetaGridCell" in body


def test_execution_inventory_row_renderer_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-inventory-row-renderer.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "ExecutionInventoryRowRenderer" in body and "createInputRow" in body


def test_execution_render_inputs_module_exists():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-render-inputs.js"
    assert js_path.is_file()
    body = js_path.read_text(encoding="utf-8")
    assert "ExecutionRenderInputs" in body and "renderVariableInventoryInputs" in body
    assert "renderConfirmExecutionInputs" in body
    assert "clearInventoryPickerCardCaches" in body and "PICKER_CARD_CACHE_MAX_ROWS" in body


def test_inventory_refresh_clears_picker_card_cache_hook():
    secondary = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal-secondary.js"
    text = secondary.read_text(encoding="utf-8")
    assert "clearInventoryPickerCardCaches" in text


def test_open_step_clears_picker_card_cache_before_inputs_reset():
    open_step = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-open-step.js"
    text = open_step.read_text(encoding="utf-8")
    assert "clearInventoryPickerCardCaches" in text


def test_execution_render_inputs_picker_cache_row_cap_branch():
    """Cache reuse gated by filtered list length vs PICKER_CARD_CACHE_MAX_ROWS (behavioral anchor, not exact formatting)."""
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-render-inputs.js"
    body = js_path.read_text(encoding="utf-8")
    assert "usePickerCardCache" in body
    assert "PICKER_CARD_CACHE_MAX_ROWS" in body
    assert re.search(
        r"(?:var|const)\s+usePickerCardCache\s*=\s*list\.length\s*<=\s*PICKER_CARD_CACHE_MAX_ROWS",
        body,
    ), "expected row-cap: usePickerCardCache from list.length vs PICKER_CARD_CACHE_MAX_ROWS"
    assert re.search(r"if\s*\(\s*usePickerCardCache\s*\)", body)


def test_inventory_refresh_clears_picker_cache_before_row_updates():
    """
    Phase invariant inside refreshExecutionModalInventory only: invalidate picker Maps before
    querying rows (see flows-and-batches-review.md). Scoped slice avoids brittle global line order.
    """
    secondary = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal-secondary.js"
    text = secondary.read_text(encoding="utf-8")
    marker = "window.refreshExecutionModalInventory = async function"
    start = text.find(marker)
    assert start != -1
    window = text[start : start + 12000]
    clear_call = "ExecutionRenderInputs.clearInventoryPickerCardCaches(modal)"
    selects_loop = "var selects = modal.querySelectorAll('.execute-inventory-select')"
    i_clear = window.find(clear_call)
    i_selects = window.find(selects_loop)
    assert i_clear != -1 and i_selects != -1
    assert i_clear < i_selects


def test_execution_modal_calls_render_inputs_api():
    js_path = _REPO_ROOT / "app" / "core" / "frontend" / "js" / "execution-modal.js"
    text = js_path.read_text(encoding="utf-8")
    assert "ExecutionRenderInputs.renderVariableInventoryInputs" in text
    assert "ExecutionRenderInputs.renderConfirmExecutionInputs" in text
