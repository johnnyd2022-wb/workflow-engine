"""feature_subscriptions: the per-org entitlement primitive + its admin CLI.

Covers spec .agents/specs/compliant_tools.md AC1, AC2, AC8, AC18.
"""

from __future__ import annotations

import logging

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.core.db.models.feature_subscription import FeatureSubscription
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from tests.factories import OrganisationFactory


@pytest.fixture
def orgs(db):
    a = OrganisationFactory()
    b = OrganisationFactory()
    db.commit()
    yield a, b
    db.query(FeatureSubscription).filter(FeatureSubscription.org_id.in_([a.id, b.id])).delete(synchronize_session=False)
    db.commit()


# ── AC1: schema ─────────────────────────────────────────────────────────────────


def test_ac1_table_columns_and_constraints(db):
    cols = {c.name: c for c in FeatureSubscription.__table__.columns}
    assert set(cols) == {
        "id",
        "org_id",
        "feature_key",
        "active",
        "granted_at",
        "granted_by_user_id",
        "notes",
    }
    assert cols["org_id"].nullable is False
    assert cols["feature_key"].nullable is False
    assert cols["active"].nullable is False
    assert cols["feature_key"].type.length == 80
    assert cols["notes"].type.length == 500
    uniques = {
        tuple(sorted(c.columns.keys()))
        for c in FeatureSubscription.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("feature_key", "org_id") in uniques
    org_fk = next(fk for fk in cols["org_id"].foreign_keys)
    assert org_fk.ondelete == "CASCADE"
    user_fk = next(fk for fk in cols["granted_by_user_id"].foreign_keys)
    assert user_fk.ondelete == "SET NULL"


# ── AC2: org_has_feature / repo semantics + isolation ───────────────────────────


def test_ac2_is_active_true_only_for_active_row(db, orgs):
    a, _b = orgs
    repo = FeatureSubscriptionRepository(db)
    assert repo.is_active(a.id, "compliant") is False  # no row
    repo.grant(a.id, "compliant")
    assert repo.is_active(a.id, "compliant") is True
    repo.revoke(a.id, "compliant")
    assert repo.is_active(a.id, "compliant") is False  # row present but inactive


def test_ac2_org_has_feature_wrapper_and_isolation(db, orgs):
    from app.core.security.entitlements import org_has_feature

    a, b = orgs
    FeatureSubscriptionRepository(db).grant(b.id, "compliant")
    # A has no row; B's row must not leak to A.
    assert org_has_feature(db, a.id, "compliant") is False
    assert org_has_feature(db, b.id, "compliant") is True
    assert org_has_feature(db, None, "compliant") is False
    assert org_has_feature(db, "not-a-uuid", "compliant") is False


def test_ac2_grant_is_idempotent(db, orgs):
    a, _b = orgs
    repo = FeatureSubscriptionRepository(db)
    repo.grant(a.id, "compliant", notes="first")
    repo.revoke(a.id, "compliant")
    repo.grant(a.id, "compliant", notes="second")
    rows = repo.list_for_org(a.id)
    assert len(rows) == 1
    assert rows[0].active is True
    assert rows[0].notes == "second"


# ── AC8: admin CLI ─────────────────────────────────────────────────────────────


def test_ac8_grant_revoke_list_cli(db, orgs):
    a, _b = orgs
    runner = CliRunner()

    r = runner.invoke(cli, ["grant-feature", "--org-id", str(a.id), "--feature", "compliant", "--note", "paid"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli, ["grant-feature", "--org-id", str(a.id), "--feature", "compliant"])
    assert r.exit_code == 0
    db.expire_all()
    rows = FeatureSubscriptionRepository(db).list_for_org(a.id)
    assert len(rows) == 1 and rows[0].active is True

    r = runner.invoke(cli, ["list-features", "--org-id", str(a.id)])
    assert r.exit_code == 0 and "compliant" in r.output and "active" in r.output

    r = runner.invoke(cli, ["revoke-feature", "--org-id", str(a.id), "--feature", "compliant"])
    assert r.exit_code == 0
    db.expire_all()
    assert FeatureSubscriptionRepository(db).is_active(a.id, "compliant") is False

    r = runner.invoke(cli, ["revoke-feature", "--org-id", str(a.id), "--feature", "never-granted"])
    assert r.exit_code == 0 and "no" in r.output.lower()


def test_ac8_cli_rejects_bad_and_unknown_org():
    runner = CliRunner()
    r = runner.invoke(cli, ["grant-feature", "--org-id", "nope", "--feature", "compliant"])
    assert r.exit_code != 0
    r = runner.invoke(
        cli, ["grant-feature", "--org-id", "00000000-0000-0000-0000-000000000000", "--feature", "compliant"]
    )
    assert r.exit_code != 0 and "not found" in r.output.lower()


# ── AC18: destructive downgrade warns with a row count ─────────────────────────


def test_ac18_migration_downgrade_logs_row_count_before_dropping(monkeypatch, caplog):
    """The row-count WARNING must fire *before* the destructive drop, and must carry the
    real count — so an operator sees what they are about to lose. Records call order and
    asserts the exact sequence, not just that a warning happened somewhere.
    """
    import app.core.db.migrations.versions.feature_subscriptions_001 as mig

    calls: list[str] = []

    class _Bind:
        def execute(self, stmt, *_a, **_k):
            text = str(getattr(stmt, "text", stmt))
            calls.append(f"execute:{'regclass' if 'to_regclass' in text else 'count' if 'count(' in text else 'other'}")

            class _R:
                @staticmethod
                def scalar():
                    return "public.feature_subscriptions" if "to_regclass" in text else 3

            return _R()

    monkeypatch.setattr(mig.op, "get_bind", lambda: _Bind())
    monkeypatch.setattr(mig.op, "drop_index", lambda *a, **k: calls.append("drop_index"))
    monkeypatch.setattr(mig.op, "drop_table", lambda *a, **k: calls.append("drop_table"))

    real_warning = logging.getLogger("alembic.runtime.migration").warning

    def _tracking_warning(msg, *a, **k):
        calls.append("warning")
        return real_warning(msg, *a, **k)

    monkeypatch.setattr(logging.getLogger("alembic.runtime.migration"), "warning", _tracking_warning)

    with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
        mig.downgrade()

    # The count query and the warning both happen before either drop.
    assert calls == ["execute:regclass", "execute:count", "warning", "drop_index", "drop_table"], calls
    warn = next(r for r in caplog.records if "feature_subscriptions" in r.getMessage())
    assert "3" in warn.getMessage() and "irrecoverable" in warn.getMessage()


def test_ac18_migration_downgrade_noops_when_table_absent(monkeypatch, caplog):
    import app.core.db.migrations.versions.feature_subscriptions_001 as mig

    dropped: list[str] = []

    class _Bind:
        def execute(self, *_a, **_k):
            class _R:
                @staticmethod
                def scalar():
                    return None  # to_regclass -> table absent

            return _R()

    monkeypatch.setattr(mig.op, "get_bind", lambda: _Bind())
    monkeypatch.setattr(mig.op, "drop_index", lambda *a, **k: dropped.append("index"))
    monkeypatch.setattr(mig.op, "drop_table", lambda *a, **k: dropped.append("table"))

    with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
        mig.downgrade()

    assert dropped == []
    assert any("already absent" in r.getMessage() for r in caplog.records)
