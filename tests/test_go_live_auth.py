"""The go-live assessment's three account gates (docs/go-live-checklist.md GL-A01 to GL-A03).

Each test is one of the report's reproductions, kept as a regression test: they all failed on
cb3362be (200s, and a 500 for the oversized password).
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.db.models.user import User
from tests.test_auth_password_session import PASSWORD, account  # noqa: F401 -- fixture re-export

NEW = "Replacement-Password!2026"


def _change(client, new, current=PASSWORD):
    return client.post(
        "/auth/change-password",
        json={"current_password": current, "new_password": new, "new_password_confirm": new},
    )


# --- GL-A02: a password change ends every other session ------------------------------------


def test_password_change_signs_out_another_browser(account):  # noqa: F811
    other = account["make_client"](PASSWORD)
    assert other.get("/auth/session-timeout").status_code == 200
    assert _change(account["client"], NEW).status_code == 200
    assert other.get("/auth/session-timeout").status_code == 401


def test_the_browser_that_changed_the_password_stays_signed_in(account):  # noqa: F811
    assert _change(account["client"], NEW).status_code == 200
    assert account["client"].get("/auth/session-timeout").status_code == 200


def test_signing_in_with_the_new_password_works_everywhere(account):  # noqa: F811
    assert _change(account["client"], NEW).status_code == 200
    fresh = account["make_client"](NEW)
    assert fresh.get("/auth/session-timeout").status_code == 200


def test_a_session_from_before_stamps_existed_ends(account):  # noqa: F811
    # Nothing on the server says which password an unstamped cookie signed in with, so it can't be
    # trusted to have outlived a password change. Codex's ordering on !571: unstamp, change the
    # password elsewhere, then use the old cookie: it was a 200.
    other = account["make_client"](PASSWORD)
    with other.session_transaction() as sess:
        sess.pop("auth_stamp", None)
    assert _change(account["client"], NEW).status_code == 200
    assert other.get("/auth/session-timeout").status_code == 401


def test_an_unstamped_cookie_ends_even_with_no_password_change(account):  # noqa: F811
    other = account["make_client"](PASSWORD)
    with other.session_transaction() as sess:
        sess.pop("auth_stamp", None)
    assert other.get("/auth/session-timeout").status_code == 401


# --- GL-A01: one password rule everywhere ------------------------------------------------------


def test_one_character_password_is_refused_on_change(account):  # noqa: F811
    resp = _change(account["client"], "x")
    assert resp.status_code == 400
    assert "at least 8" in resp.get_json()["error"]


def test_an_oversized_password_is_a_400_not_a_500(account):  # noqa: F811
    resp = _change(account["client"], "a" * 73)
    assert resp.status_code == 400
    assert "at most 72 characters" in resp.get_json()["error"]


def test_a_long_passphrase_within_the_limit_works(account):  # noqa: F811
    phrase = "correct horse battery staple and a gin and tonic"  # 48 bytes
    assert _change(account["client"], phrase).status_code == 200
    assert account["make_client"](phrase).get("/auth/session-timeout").status_code == 200


def test_signing_in_with_an_oversized_password_is_a_plain_refusal(account):  # noqa: F811
    resp = account["make_client"]().post("/auth/login", json={"email": account["email"], "password": "a" * 200})
    assert resp.status_code == 401


def test_signup_refuses_a_short_password(account):  # noqa: F811
    resp = account["make_client"]().post(
        "/auth/signup",
        json={
            "org_name": f"Shortpass {uuid4()}",
            "email": f"short-{uuid4()}@test.com",
            "password": "x",
            "password_confirm": "x",
        },
    )
    assert resp.status_code == 400
    assert "at least 8" in resp.get_json()["error"]


# --- GL-A03: nothing the caller sends clears an account lock -------------------------------


def _lock(db, email):  # noqa: F811
    db.query(User).filter(User.email == email).update(
        {User.account_locked_until: datetime.now(UTC) + timedelta(minutes=15)}
    )
    db.commit()


def test_a_client_flag_cannot_clear_an_account_lock(account, db):  # noqa: F811
    _lock(db, account["email"])
    payload = {"email": account["email"], "password": PASSWORD}
    assert account["make_client"]().post("/auth/login", json=payload).status_code == 401
    for flag in (True, "true", 1, "yes"):
        resp = account["make_client"]().post("/auth/login", json={**payload, "password_reset": flag})
        # Refused either way; the login rate limit may answer the later tries with a 429.
        assert resp.status_code in (401, 429), flag
    db.expire_all()
    assert db.query(User).filter(User.email == account["email"]).one().account_locked_until is not None


# --- GL-S05: revocation reaches sessions that are already open ----------------------------


def _user(db, email):
    db.expire_all()
    return db.query(User).filter(User.email == email).one()


def test_deactivating_someone_ends_their_open_session(account, db):  # noqa: F811
    assert account["client"].get("/auth/session-timeout").status_code == 200
    _user(db, account["email"]).is_active = False
    db.commit()
    assert account["client"].get("/auth/session-timeout").status_code == 401
    # And they can't sign straight back in.
    fresh = account["make_client"]()
    assert fresh.post("/auth/login", json={"email": account["email"], "password": PASSWORD}).status_code in (401, 403)


def test_a_role_change_applies_on_the_next_request(account, db):  # noqa: F811
    from app.core.db.models.user import UserRole

    client = account["client"]
    assert client.post("/api/core/executions", json={}).status_code != 403
    _user(db, account["email"]).role = UserRole.AUDITOR
    db.commit()
    assert client.post("/api/core/executions", json={}).status_code == 403
