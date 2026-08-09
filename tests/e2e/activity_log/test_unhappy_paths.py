"""Unhappy paths for the activity-log routes: bad input must 400, never 500 (AC1, AC2,
AC9, and the two int()-parse gaps fixed in this review, F2 in security-audit.md)."""

import pytest

from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e


def test_ac1_invalid_entity_type_returns_400(browser, app_url, fresh_user):
    user = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        login_through_ui(page, user["email"], user["password"])
        resp = page.request.get("/api/core/entities/not_a_real_type/00000000-0000-0000-0000-000000000000/story")
        assert resp.status == 400
        assert resp.json()["error"] == "Invalid entity_type"
    finally:
        context.close()


def test_ac2_invalid_entity_id_returns_400_not_500(browser, app_url, fresh_user):
    user = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        login_through_ui(page, user["email"], user["password"])
        resp = page.request.get("/api/core/entities/inventory_item/not-a-uuid/story")
        assert resp.status == 400
        assert resp.json()["error"] == "Invalid entity_id"
    finally:
        context.close()


def test_regression_non_numeric_limit_on_story_returns_400_not_500(browser, app_url, fresh_user):
    """[REGRESSION] F2: bare int() on limit/offset raised an unhandled ValueError -> 500
    before this review's fix."""
    user = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        login_through_ui(page, user["email"], user["password"])
        resp = page.request.get(
            "/api/core/entities/inventory_item/00000000-0000-0000-0000-000000000000/story?limit=abc"
        )
        assert resp.status == 400, resp.text()
    finally:
        context.close()


def test_regression_non_numeric_offset_on_activity_feed_returns_400_not_500(browser, app_url, fresh_user):
    user = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        login_through_ui(page, user["email"], user["password"])
        resp = page.request.get("/api/core/entities/activity?offset=abc")
        assert resp.status == 400, resp.text()
    finally:
        context.close()


def test_unauthenticated_story_request_returns_401(browser, app_url):
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        resp = page.request.get("/api/core/entities/inventory_item/00000000-0000-0000-0000-000000000000/story")
        assert resp.status == 401
    finally:
        context.close()
