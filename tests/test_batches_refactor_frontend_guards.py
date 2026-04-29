"""
Lightweight source guards for batches-refactor hardening (see cursor_instructions/batches-refactor-checklist.md).

These tests lock in key patterns; they are not browser E2E tests.
"""

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_JS = _REPO / "app" / "core" / "frontend" / "js"


def _read(name: str) -> str:
    p = _JS / name
    assert p.is_file(), f"missing {p}"
    return p.read_text(encoding="utf-8")


def test_execution_security_utils_embed_policy():
    s = _read("execution-security-utils.js")
    assert "ExecutionSecurityUtils" in s
    assert "isSameOriginEmbedUrl" in s
    assert "javascript:" in s and "data:" in s
    assert "loc.protocol" in s and ("loc.origin" in s or "http:" in s)
    assert "client-side" in s.lower() or "server" in s.lower()


def test_doc_overlay_sandbox_and_teardown():
    s = _read("execution-doc-overlay.js")
    assert "removeDocFullscreenOverlay" in s
    assert "allow-same-origin" in s and "sandbox" in s
    assert "referrerPolicy" in s
    assert "popstate" in s
    assert "Escape" in s or "'Escape'" in s
    assert "ExecutionSecurityUtils" in s
    assert "isSameOriginEmbedUrl" in s
    assert "__executionSecurityUtilsMissingLogged" in s


def test_render_docs_iframe_hardening_and_summary_dom():
    s = _read("execution-render-docs.js")
    assert "iframe.setAttribute" in s
    assert "allow-same-origin" in s
    assert "referrerPolicy" in s
    assert "createTextNode('View inline')" in s
    assert "ExecutionSecurityUtils" in s
    assert "isSameOriginEmbedUrl" in s
    assert "__executionSecurityUtilsMissingLogged" in s


def test_execution_step_spa_picker_event_delegation():
    s = _read("execution-step-spa.js")
    assert "_execSpaPickerDelegate" in s
    assert ".closest('.exec-picker-card')" in s


def test_open_step_generation_guard():
    s = _read("execution-open-step.js")
    assert "openExecutionModalGeneration" in s
    assert "staleOpen(openGen)" in s


def test_modal_secondary_bind_refresh_and_submit_guards():
    s = _read("execution-modal-secondary.js")
    assert "refreshInventoryGeneration" in s
    assert "gen !== refreshInventoryGeneration" in s
    assert "_executionUntrackedFormBound" in s
    assert "_untrackedSubmitInFlight" in s


def test_shared_utils_org_users_warn():
    s = _read("execution-shared-utils.js")
    assert "loadOrgUsersMap: failed to fetch" in s
    assert "console.warn" in s


def test_core_api_abort_error_passthrough():
    s = _read("core-api.js")
    assert "AbortError" in s
    assert "error.name === 'AbortError'" in s or "name === 'AbortError'" in s
    assert "network request failed" in s.lower() or "networkerror" in s.lower()


def test_open_step_abort_and_stale_helper():
    s = _read("execution-open-step.js")
    assert "openExecutionModalAbortController" in s
    assert "staleOpen" in s
    assert "getInventory(null, null, { signal" in s or "signal: signal" in s


def test_submit_execution_in_flight_guard():
    s = _read("execution-submit.js")
    assert "_submitExecutionInFlight" in s


def test_modal_secondary_refresh_abort():
    s = _read("execution-modal-secondary.js")
    assert "refreshInventoryAbort" in s
    assert "getInventory(null, null, { signal" in s or "refreshSignal" in s


def test_render_prompts_abort_and_evidence_dedupe():
    s = _read("execution-render-prompts.js")
    assert "throwIfAborted" in s
    assert "seenIds" in s and "Set" in s


def test_execution_modal_requires_security_utils():
    s = _read("execution-modal.js")
    assert "ExecutionSecurityUtils" in s
    assert "execution-security-utils.js must be loaded" in s


def test_jinja_execution_stack_include_order():
    root = _REPO / "app" / "core" / "frontend" / "shared" / "execution_modal_stack_scripts.html"
    t = root.read_text(encoding="utf-8")
    assert "execution-open-step.js" in t
    assert "execution-modal.js" in t
    i_open = t.find("execution-open-step")
    i_modal = t.find("execution-modal.js")
    assert i_open != -1 and i_modal != -1 and i_open < i_modal
