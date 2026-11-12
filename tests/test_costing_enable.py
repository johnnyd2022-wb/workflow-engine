"""Switching live cost on for an organisation (`workflow costing enable`).

First used for Whistlebird: the feature, new purchases counted from today, stock history rebuilt
for lots made before the cost engine, and optionally earlier purchases loaded from Xero.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.core.security.entitlements import org_has_feature
from app.features.costing.enable import enable_costing
from app.features.costing.models import CostFlow, CostingSettings
from app.features.costing.service import CostingError
from tests.costing_helpers import lot, new_org, purge
from tests.test_costing_purchases import FakeXero, connect, line, txn

TODAY = date(2026, 11, 12)


@pytest.fixture
def org(db):
    from app.core.db.models.organisation import Organisation

    o = new_org(db, grant=False)
    oid = o.id
    yield o
    db.rollback()
    purge(db, db.get(Organisation, oid))  # the CLI closes the session, detaching `o`


def _settings(db, org_id):
    db.expire_all()
    return db.query(CostingSettings).filter(CostingSettings.org_id == org_id).one()


def _strip_flows(db, org_id):
    """A lot made before the cost engine: no flow rows yet."""
    db.query(CostFlow).filter(CostFlow.org_id == org_id).delete()
    db.commit()


def test_enable_without_xero_grants_anchors_and_rebuilds_history(db, org):
    juniper = lot(db, org.id, "Juniper", 5, "kg")
    _strip_flows(db, org.id)
    result = enable_costing(db, org.id, today=TODAY)
    assert org_has_feature(db, org.id, "costing")
    assert _settings(db, org.id).start_date == TODAY
    assert result["flows_added"] >= 1
    assert db.query(CostFlow).filter(CostFlow.inventory_item_id == juniper.id).count() == 1
    assert result["history"] == {"status": "not_requested"}
    assert (result["products"], result["purchases_to_record"]) == (0, 0)


def test_enable_is_idempotent_and_never_moves_the_start_date(db, org):
    enable_costing(db, org.id, today=TODAY)
    again = enable_costing(db, org.id, today=TODAY + timedelta(days=30))
    assert _settings(db, org.id).start_date == TODAY
    assert again["start_date"] == TODAY.isoformat() and again["flows_added"] == 0


def test_enable_with_history_loads_earlier_purchases_from_xero(db, org, monkeypatch):
    connect(db, org.id)
    fake = FakeXero().install(monkeypatch)
    fake.transactions = [
        txn(
            [line("310", "45", line_item_id=str(uuid4()))],
            on=TODAY - timedelta(days=40),
            amounts="NoTax",
            payee="Old Co",
        )
    ]
    result = enable_costing(db, org.id, history_from=TODAY - timedelta(days=90), today=TODAY)
    assert result["history"]["status"] == "loaded" and result["history"]["documents"] == 1
    call = fake.bank_calls()[-1]
    assert (call["from_date"], call["to_date"]) == (TODAY - timedelta(days=90), TODAY)
    assert (result["purchases_to_record"], result["earlier_purchases_to_record"]) == (0, 1)


def test_history_needing_reconnect_is_reported_and_the_rest_stands(db, org, monkeypatch):
    connect(db, org.id, scopes="openid accounting.contacts accounting.invoices offline_access")
    FakeXero().install(monkeypatch)
    result = enable_costing(db, org.id, history_from=TODAY - timedelta(days=30), today=TODAY)
    assert result["history"]["status"] == "needs_reconnect"
    assert org_has_feature(db, org.id, "costing") and _settings(db, org.id).start_date == TODAY


def test_history_without_any_xero_connection_is_reported(db, org):
    result = enable_costing(db, org.id, history_from=TODAY - timedelta(days=30), today=TODAY)
    assert result["history"]["status"] == "needs_reconnect"


@pytest.mark.parametrize("days_back", [-1, 3 * 366])
def test_history_dates_are_checked_before_anything_changes(db, org, days_back):
    with pytest.raises(CostingError):
        enable_costing(db, org.id, history_from=TODAY - timedelta(days=days_back), today=TODAY)
    db.expire_all()
    assert not org_has_feature(db, org.id, "costing")


def test_summary_names_products_still_waiting(db, org):
    from tests.costing_helpers import complete, user_client, workflow  # noqa: F401

    spirit = lot(db, org.id, "Spirit", 10, "L")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    from app.core.db.repositories.execution_repo import ExecutionRepository  # noqa: F401

    result = enable_costing(db, org.id, today=TODAY)
    assert result["products"] >= 1
    assert result["products_ready"] < result["products"]
    assert any(p["name"] == "Gin" for p in result["not_ready"])
    assert spirit.id  # declared product, no batch yet: waits on its inputs


def test_cli_enable(db, org):
    runner = CliRunner()
    r = runner.invoke(cli, ["costing", "enable", "--org-id", str(org.id)])
    assert r.exit_code == 0, r.output
    assert "Live cost is on" in r.output and "Products with a full cost" in r.output
    assert org_has_feature(db, org.id, "costing")
    assert runner.invoke(cli, ["costing", "enable", "--org-id", "nope"]).exit_code != 0
    assert (
        runner.invoke(cli, ["costing", "enable", "--org-id", str(org.id), "--history-from", "2026-13-01"]).exit_code
        != 0
    )
    missing = runner.invoke(cli, ["costing", "enable", "--org-id", str(uuid4())])
    assert missing.exit_code == 1


def test_cli_enable_exits_2_when_history_needs_reconnect(db, org):
    r = CliRunner().invoke(
        cli,
        [
            "costing",
            "enable",
            "--org-id",
            str(org.id),
            "--history-from",
            (date.today() - timedelta(days=30)).isoformat(),
        ],
    )
    assert r.exit_code == 2, r.output
    assert "Earlier purchases not loaded" in r.output
