"""The page registry stays true to the routes and the access policy."""

from collections import Counter

import pytest

from app.ui.page_registry import PAGES, SECTIONS, page_for, requirement


@pytest.fixture(scope="module")
def app():
    from app.app import app

    return app


def test_paths_are_unique_and_sections_known():
    assert [path for path, n in Counter(page.path for page in PAGES).items() if n > 1] == []
    assert {page.section for page in PAGES} <= set(SECTIONS)


def test_every_section_has_a_root_page():
    assert {page.section for page in PAGES} == set(SECTIONS)


def test_every_path_is_a_real_get_route_with_an_access_rule(app):
    from app.core.security.access_policy import DENY

    for page in PAGES:
        assert requirement(page, app) != DENY, page.path


def test_parents_exist_and_are_not_cyclic():
    for page in PAGES:
        seen = {page.path}
        parent = page.parent
        while parent:
            assert parent not in seen, f"{page.path}: parent cycle"
            seen.add(parent)
            found = page_for(parent)
            assert found is not None, f"{page.path}: unknown parent {parent}"
            parent = found.parent


def test_feature_flags_are_known():
    assert {page.feature for page in PAGES} <= {None, "crm", "compliant"}
