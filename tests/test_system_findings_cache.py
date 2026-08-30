"""Read-through cache for /api/core/system-findings.

The endpoint's contract (findings + system_status shape, org scoping, 401) is covered by
test_corechecks_routes.py. This file covers the caching layer added on top:

- first request computes and stores; subsequent requests are served from the row
- an inventory/execution/process mutation marks the row stale -> next request recomputes
- an unrelated event (user.login) does NOT invalidate
- an expired row (past TTL) recomputes
- the cache is per-org
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.backend import system_findings_cache as sfc
from app.core.db.models.organisation import Organisation
from app.core.db.models.system_findings_cache import SystemFindingsCache
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

PASSWORD = DEFAULT_TEST_PASSWORD
ENDPOINT = "/api/core/system-findings"
DASHBOARD_ENDPOINT = "/api/core/dashboard/summary?window_days=30"


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        yield app


def _make_org_and_client(db, flask_app):
    org = OrganisationFactory()
    db.commit()
    email = f"user_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id, email=email, password_hash=AuthService.hash_password(PASSWORD), is_active=True
    )
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return org, client


def _cache_row(db, org_id):
    return db.query(SystemFindingsCache).filter_by(org_id=org_id).first()


@pytest.fixture
def authed(db, flask_app):
    org, client = _make_org_and_client(db, flask_app)
    yield org, client
    db.rollback()
    db.query(SystemFindingsCache).filter_by(org_id=org.id).delete(synchronize_session=False)
    db.query(Organisation).filter_by(id=org.id).delete(synchronize_session=False)
    db.commit()


def test_first_call_computes_and_stores_then_serves_from_cache(db, authed, monkeypatch):
    org, client = authed
    calls = {"n": 0}
    real_compute = sfc._compute_expensive

    def counting_compute(org_id, session):
        calls["n"] += 1
        return real_compute(org_id, session)

    monkeypatch.setattr(sfc, "_compute_expensive", counting_compute)

    first = client.get(ENDPOINT)
    assert first.status_code == 200
    assert set(first.get_json()) == {"findings", "system_status"}
    assert calls["n"] == 1
    assert _cache_row(db, org.id) is not None

    # three more calls -> no further computes, byte-identical payload
    for _ in range(3):
        r = client.get(ENDPOINT)
        assert r.status_code == 200
        assert r.get_data() == first.get_data()
    assert calls["n"] == 1


def test_invalidating_event_marks_stale_and_forces_recompute(db, authed, monkeypatch):
    org, client = authed
    calls = {"n": 0}
    real = sfc._compute_expensive
    monkeypatch.setattr(sfc, "_compute_expensive", lambda o, s: (calls.__setitem__("n", calls["n"] + 1) or real(o, s)))

    client.get(ENDPOINT)
    assert calls["n"] == 1
    client.get(ENDPOINT)
    assert calls["n"] == 1  # cached

    # an inventory mutation goes through EventWriter -> mark_stale
    from app.core.backend.event_writer import EventWriter

    EventWriter(db, org.id).emit("inventory_item.updated", "inventory_item", uuid4(), {"x": 1})
    db.commit()
    assert _cache_row(db, org.id).stale is True

    client.get(ENDPOINT)
    assert calls["n"] == 2  # recomputed
    db.expire_all()
    assert _cache_row(db, org.id).stale is False  # recompute cleared it


def test_unrelated_event_does_not_invalidate(db, authed, monkeypatch):
    org, client = authed
    calls = {"n": 0}
    real = sfc._compute_expensive
    monkeypatch.setattr(sfc, "_compute_expensive", lambda o, s: (calls.__setitem__("n", calls["n"] + 1) or real(o, s)))

    client.get(ENDPOINT)
    from app.core.backend.event_writer import EventWriter

    EventWriter(db, org.id).emit("user.login", "user", uuid4(), {"ip": "127.0.0.1"})
    db.commit()
    db.expire_all()
    assert _cache_row(db, org.id).stale is False

    client.get(ENDPOINT)
    assert calls["n"] == 1  # still cached


def test_expired_row_recomputes(db, authed, monkeypatch):
    org, client = authed
    calls = {"n": 0}
    real = sfc._compute_expensive
    monkeypatch.setattr(sfc, "_compute_expensive", lambda o, s: (calls.__setitem__("n", calls["n"] + 1) or real(o, s)))

    client.get(ENDPOINT)
    assert calls["n"] == 1

    # backdate the row well past the max age (and any midnight boundary)
    old = datetime.now(UTC) - sfc.TTL - timedelta(minutes=1)
    db.execute(
        text("UPDATE system_findings_cache SET computed_at = :t WHERE org_id = :o"),
        {"t": old, "o": str(org.id)},
    )
    db.commit()

    client.get(ENDPOINT)
    assert calls["n"] == 2


def test_freshness_rolls_over_at_nz_midnight(db, authed, monkeypatch):
    """A row computed before the last Pacific/Auckland midnight is stale; one computed
    after it is fresh -- so the DAG traversal runs about once per NZ day."""
    org, client = authed
    calls = {"n": 0}
    real = sfc._compute_expensive
    monkeypatch.setattr(sfc, "_compute_expensive", lambda o, s: (calls.__setitem__("n", calls["n"] + 1) or real(o, s)))

    client.get(ENDPOINT)
    assert calls["n"] == 1

    now = datetime.now(UTC)
    last_midnight = sfc._last_local_midnight(now)

    # computed one minute BEFORE the last NZ midnight -> stale -> recompute
    db.execute(
        text("UPDATE system_findings_cache SET computed_at = :t WHERE org_id = :o"),
        {"t": last_midnight - timedelta(minutes=1), "o": str(org.id)},
    )
    db.commit()
    client.get(ENDPOINT)
    assert calls["n"] == 2

    # computed one minute AFTER the last NZ midnight -> still fresh -> no recompute
    db.execute(
        text("UPDATE system_findings_cache SET computed_at = :t, stale = false WHERE org_id = :o"),
        {"t": last_midnight + timedelta(minutes=1), "o": str(org.id)},
    )
    db.commit()
    client.get(ENDPOINT)
    assert calls["n"] == 2


def test_only_the_dag_check_is_cached_cheap_checks_run_every_request(db, authed, monkeypatch):
    """The expensive (expired_materials) slice is cached; every other check runs live on
    each request so the banner reflects time-sensitive checks (output_expiry etc.) in
    real time."""
    org, client = authed
    exp = {"n": 0}
    live = {"n": 0}
    real_exp = sfc._compute_expensive
    real_live = sfc._run_live
    monkeypatch.setattr(sfc, "_compute_expensive", lambda o, s: (exp.__setitem__("n", exp["n"] + 1) or real_exp(o, s)))
    monkeypatch.setattr(sfc, "_run_live", lambda o, s: (live.__setitem__("n", live["n"] + 1) or real_live(o, s)))

    for _ in range(3):
        assert client.get(ENDPOINT).status_code == 200

    assert exp["n"] == 1, "expensive slice recomputed more than once despite a fresh cache"
    assert live["n"] == 3, "cheap checks did not run on every request"
    assert "expired_materials" in {r["check_id"] for r in _cache_row(db, org.id).payload["results"]}


def test_cache_is_per_org(db, flask_app):
    org_a, client_a = _make_org_and_client(db, flask_app)
    org_b, client_b = _make_org_and_client(db, flask_app)
    try:
        client_a.get(ENDPOINT)
        client_b.get(ENDPOINT)
        assert _cache_row(db, org_a.id) is not None
        assert _cache_row(db, org_b.id) is not None
        assert _cache_row(db, org_a.id).id != _cache_row(db, org_b.id).id

        # invalidating org A must not touch org B's row
        from app.core.backend.event_writer import EventWriter

        EventWriter(db, org_a.id).emit("execution.step_completed", "execution", uuid4(), {})
        db.commit()
        db.expire_all()
        assert _cache_row(db, org_a.id).stale is True
        assert _cache_row(db, org_b.id).stale is False
    finally:
        db.rollback()
        for oid in (org_a.id, org_b.id):
            db.query(SystemFindingsCache).filter_by(org_id=oid).delete(synchronize_session=False)
            db.query(Organisation).filter_by(id=oid).delete(synchronize_session=False)
        db.commit()


def test_banner_payload_is_slimmed(db, authed):
    """The /api/core/system-findings response feeds only the banner / badge /
    Notifications page. `_banner_finding_data` drops the expired_materials DAG edge list
    and the wide item objects (~400 KB on a real org) -- keep only the fields those three
    consumers read."""

    real = sfc._compute_expensive

    # a check result carrying the full shape the DAG check produces.
    # _compute_expensive returns (results, ok) -- ok=True means "safe to cache".
    def fake_expensive(org_id, session):
        return [
            {
                "check_id": "expired_materials",
                "flagged": True,
                "message": "1 expired raw material with stock",
                "data": {
                    "expired_raw_materials": [
                        {"id": "r1", "name": "juniper", "expiry_date": "2025-01-01", "supplier": "ACME", "quantity": "3.0"}
                    ],
                    "impacted_items": [
                        {"id": "w1", "name": "batch", "expired_raw_material_id": "r1", "extra_data": {"big": "x" * 500}}
                    ],
                    "connections": [{"from_id": "r1", "to_id": "w1", "execution_id": "e1"}] * 50,
                },
            }
        ], True

    org, client = authed
    import pytest as _pytest  # noqa

    sfc._compute_expensive = fake_expensive
    try:
        body = client.get(ENDPOINT).get_json()
    finally:
        sfc._compute_expensive = real

    finding = next(f for f in body["findings"] if f["check_id"] == "expired_materials")
    data = finding["data"]
    assert "connections" not in data, "the DAG edge list must be dropped"
    assert set(data["expired_raw_materials"][0]) <= set(sfc._EXPIRED_RAW_KEEP)
    assert "supplier" not in data["expired_raw_materials"][0] and "quantity" not in data["expired_raw_materials"][0]
    assert set(data["impacted_items"][0]) <= set(sfc._IMPACTED_KEEP)
    assert data["impacted_items"][0]["expired_raw_material_id"] == "r1"  # kept -- Notifications groups on it
    assert "extra_data" not in data["impacted_items"][0]


def test_get_check_results_is_the_full_merged_set(db, authed):
    """get_check_results() returns the same check ids CoreChecksRunner.run_all_checks()
    does -- the expensive slice from cache, the cheap ones live."""
    from app.core.backend.corechecks import CoreChecksRunner

    org, _client = authed
    merged = sfc.get_check_results(org.id, db)
    live_ref = CoreChecksRunner(org_id=org.id, session=db).run_all_checks()

    assert {r.check_id for r in merged} == {r.check_id for r in live_ref}
    assert "expired_materials" in {r.check_id for r in merged}


def test_dashboard_summary_shares_the_cached_dag_slice(db, authed, monkeypatch):
    """The landing-page /api/core/dashboard/summary no longer runs the expired_materials
    DAG traversal on every load -- it reads the same per-org cached slice /core does, so a
    burst of dashboard loads computes it once, and a mutation still forces a recompute."""
    org, client = authed
    calls = {"n": 0}
    real = sfc._compute_expensive
    monkeypatch.setattr(sfc, "_compute_expensive", lambda o, s: (calls.__setitem__("n", calls["n"] + 1) or real(o, s)))

    first = client.get(DASHBOARD_ENDPOINT)
    assert first.status_code == 200
    # the dashboard shape, not the banner shape
    assert {"compliance", "action_board", "audit_log", "operations"} <= set(first.get_json())
    assert calls["n"] == 1

    for _ in range(3):
        assert client.get(DASHBOARD_ENDPOINT).status_code == 200
    assert calls["n"] == 1, "dashboard summary recomputed the DAG slice despite a fresh cache"

    from app.core.backend.event_writer import EventWriter

    EventWriter(db, org.id).emit("inventory_item.updated", "inventory_item", uuid4(), {"x": 1})
    db.commit()

    assert client.get(DASHBOARD_ENDPOINT).status_code == 200
    assert calls["n"] == 2, "an inventory mutation did not invalidate the slice for the dashboard"


def test_prewarm_populates_a_fresh_row_without_a_request(db, authed):
    """The scheduled warm job recomputes the cached slice ahead of the first user."""
    org, _client = authed
    assert _cache_row(db, org.id) is None

    sfc.prewarm(org.id, db)

    db.expire_all()
    row = _cache_row(db, org.id)
    assert row is not None and row.stale is False
    assert sfc._fresh(row, datetime.now(UTC))
    assert "expired_materials" in {r["check_id"] for r in row.payload["results"]}


# ---------------------------------------------------------------------------------------
# Failure semantics: a check that raises must stay VISIBLE (flagged "Check failed"
# result), exactly as CoreChecksRunner.run_all_checks() has always done. The cache
# rewrite's _run_live() previously logged-and-dropped it, and a cached-check exception
# escaped as a 500 instead of a failure result -- either way letting the /core banner and
# system_status report a healthier state than the checks actually support.
# Finding: .agents/reports/perf/2026-08-29-mr-187-200-review.md (P1, MR !201).
# ---------------------------------------------------------------------------------------


def _raise_for(check_id_to_fail, message="check exploded"):
    from app.core.backend.corechecks import CoreChecksRunner

    real = CoreChecksRunner.run_check

    def patched(self, check_id):
        if check_id == check_id_to_fail:
            raise RuntimeError(message)
        return real(self, check_id)

    return patched


def test_live_check_failure_is_a_flagged_result_not_dropped(db, authed, monkeypatch):
    org, _client = authed
    from app.core.backend.corechecks import CoreChecksRunner

    monkeypatch.setattr(CoreChecksRunner, "run_check", _raise_for("untracked_items", "db exploded"))

    results = sfc._run_live(org.id, db)
    failed = [r for r in results if r.check_id == "untracked_items"]
    assert len(failed) == 1, "the failed live check was dropped instead of flagged"
    assert failed[0].flagged is True
    assert failed[0].message.startswith("Check failed:") and "db exploded" in failed[0].message
    assert failed[0].data is None


def test_cached_check_failure_is_returned_visible_and_not_frozen_into_cache(db, authed, monkeypatch):
    org, _client = authed
    from app.core.backend.corechecks import CoreChecksRunner

    monkeypatch.setattr(CoreChecksRunner, "run_check", _raise_for("expired_materials", "dag exploded"))

    # No 500: the compute failure comes back as a flagged result...
    results = sfc._cached_expensive(org.id, db)
    em = [r for r in results if r["check_id"] == "expired_materials"]
    assert len(em) == 1 and em[0]["flagged"] is True
    assert em[0]["message"].startswith("Check failed:") and "dag exploded" in em[0]["message"]

    # ...and it is NOT persisted -- otherwise a transient failure sticks as "fresh" until
    # the next NZ midnight and every later request serves the stale failure.
    db.expire_all()
    assert _cache_row(db, org.id) is None, "a failed cached check must not be written to the cache row"

    # The banner/findings list still shows it (get_or_compute path).
    payload = sfc.get_or_compute(org.id, db)
    assert any(
        f["check_id"] == "expired_materials" and f["text"].startswith("Check failed")
        for f in payload["findings"]
    ), "the failed cached check disappeared from the banner findings"


def test_prewarm_does_not_cache_a_failed_slice(db, authed, monkeypatch):
    org, _client = authed
    from app.core.backend.corechecks import CoreChecksRunner

    monkeypatch.setattr(CoreChecksRunner, "run_check", _raise_for("expired_materials"))
    sfc.prewarm(org.id, db)
    db.expire_all()
    assert _cache_row(db, org.id) is None


def test_system_status_is_not_healthy_while_a_check_is_failing():
    """Pure-function proof that the failure result changes system_status severity: a
    flagged 'Check failed' result (data=None) yields a CHECK_FAILED signal and drops the
    state off 'healthy'. Without this, _signals_from_results ignored data-less results and
    a failing check left the banner green."""
    from app.core.backend.corechecks import CheckResult
    from app.core.backend.system_status import _signals_from_results, derive_health_state

    healthy = CheckResult(check_id="untracked_items", flagged=False, message=None, data={"untracked_items": []})
    failed = CheckResult(check_id="output_expiry", flagged=True, message="Check failed: boom", data=None)

    assert derive_health_state(_signals_from_results([healthy])) == "healthy"

    signals = _signals_from_results([healthy, failed])
    assert any(s["type"] == "CHECK_FAILED" and s["has_issue"] for s in signals)
    assert derive_health_state(signals) == "degraded"


# ---------------------------------------------------------------------------------------
# Narrow accessor for the expiry-only endpoint (MR !201 P2).
# GET /api/core/inventory/expired-materials rendered ONLY the expired_materials slice but
# called get_check_results(), which also runs every cheap live check
# (untracked_items / output_expiry / output_ready_date / enabled compliance) on each
# request just to throw them away. get_expired_materials_result() returns only the cached
# DAG slice.
# ---------------------------------------------------------------------------------------


def test_get_expired_materials_result_does_not_run_live_checks(db, authed, monkeypatch):
    org, _client = authed
    live_calls = {"n": 0}
    real_live = sfc._run_live
    monkeypatch.setattr(
        sfc, "_run_live", lambda o, s: (live_calls.__setitem__("n", live_calls["n"] + 1) or real_live(o, s))
    )

    r = sfc.get_expired_materials_result(org.id, db)
    assert live_calls["n"] == 0, "the narrow accessor must not run the live checks"

    # It returns the same expired_materials result the full merge would.
    full = next((x for x in sfc.get_check_results(org.id, db) if x.check_id == "expired_materials"), None)
    assert live_calls["n"] == 1, "get_check_results DOES run the live checks (contrast)"
    assert (r is None) == (full is None)
    if r is not None:
        assert r.check_id == "expired_materials"


def test_expired_materials_endpoint_skips_the_live_checks(db, authed, monkeypatch):
    org, client = authed

    def _boom(_o, _s):
        raise AssertionError("live checks ran for the expiry-only endpoint")

    monkeypatch.setattr(sfc, "_run_live", _boom)

    resp = client.get("/api/core/inventory/expired-materials")
    assert resp.status_code == 200
    assert set(resp.get_json()) >= {"expired_raw_materials", "impacted_items"}
