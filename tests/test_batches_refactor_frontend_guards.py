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


def test_doc_overlay_sandbox_and_teardown():
    s = _read("execution-doc-overlay.js")
    assert "removeDocFullscreenOverlay" in s
    assert "allow-same-origin" in s and "sandbox" in s
    assert "referrerPolicy" in s
    assert "popstate" in s
    assert "Escape" in s or "'Escape'" in s


def test_render_docs_iframe_hardening_and_summary_dom():
    s = _read("execution-render-docs.js")
    assert "iframe.setAttribute" in s
    assert "allow-same-origin" in s
    assert "referrerPolicy" in s
    assert "createTextNode('View inline')" in s


def test_open_step_generation_guard():
    s = _read("execution-open-step.js")
    assert "openExecutionModalGeneration" in s
    assert "openGen !== openExecutionModalGeneration" in s


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
