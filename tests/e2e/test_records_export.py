"""GL-P10 in a browser: an admin downloads every record from Settings; staff never see the button.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui), so no live
server is needed.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

HOST = "https://crm.test"


@pytest.fixture()
def role():
    return UserRole.ADMIN


@pytest.fixture()
def user(_member, db, role):  # noqa: F811
    _member.role = role
    db.commit()
    return _member


def test_an_admin_downloads_all_records(sales_page, org):  # noqa: F811
    sales_page.goto(HOST + "/core/settings")
    sales_page.get_by_role("link", name="Your records").click()
    button = sales_page.get_by_role("link", name="Download records (.zip)")
    expect(button).to_be_visible()
    with sales_page.expect_download() as info:
        button.click()
    # The test router forwards only a few headers and Chromium cancels a routed download before
    # it lands, so the attachment filename is checked in tests/test_data_export.py and the bytes
    # are fetched here through the same route the link uses.
    assert info.value.url.endswith("/api/core/export/records.zip")
    body = sales_page.evaluate(
        """async (href) => {
            const r = await fetch(href, {credentials: 'same-origin'});
            return {status: r.status, bytes: Array.from(new Uint8Array(await r.arrayBuffer()))};
        }""",
        button.get_attribute("href"),
    )
    assert body["status"] == 200
    zf = zipfile.ZipFile(io.BytesIO(bytes(body["bytes"])))
    assert f"All records for {org.name}" in zf.read("README.txt").decode()
    assert "tables/inventory_items.csv" in zf.namelist()


@pytest.mark.parametrize("role", [UserRole.MEMBER])
def test_staff_do_not_see_the_download(sales_page, role):  # noqa: F811
    sales_page.goto(HOST + "/core/settings")
    expect(sales_page.get_by_role("link", name="Profile")).to_be_visible()
    expect(sales_page.get_by_role("link", name="Your records")).to_have_count(0)
    expect(sales_page.locator("#records-export-download")).to_have_count(0)
