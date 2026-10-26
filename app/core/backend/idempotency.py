"""Retry-safe write routes (GL-U03).

A save can reach the server and still look failed: the connection drops on the way back, so the
page shows an error and the person presses Save again. With an ``Idempotency-Key`` header the
second request replays the first one's response instead of creating a second record.

How it holds:

1. the key is claimed first, as a pending row (``http_status`` 0); the unique (org, key)
   constraint means a parallel retry finds it rather than running the write again;
2. the view runs; a 2xx response is stored on the row, anything else releases the key so a
   corrected retry can run;
3. a retry with a stored response gets it back (``Idempotent-Replay: true``); one that finds the
   key still pending gets a 409 to try again; the same key with a different body is a 409.

Requests without the header behave exactly as before.
"""

from __future__ import annotations

import hashlib
from functools import wraps

from flask import Response, g, jsonify, make_response, request
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.models.api_idempotency_key import ApiIdempotencyKey

PENDING = 0


def _row(org_id, key):
    return (
        db_session.query(ApiIdempotencyKey)
        .filter(ApiIdempotencyKey.org_id == org_id, ApiIdempotencyKey.key == key)
        .one_or_none()
    )


def _answer(row, payload_hash):
    if row.payload_hash != payload_hash:
        return jsonify({"error": "This Idempotency-Key was already used for a different request"}), 409
    if row.http_status == PENDING:
        return jsonify({"error": "That save is still in progress; try again in a moment"}), 409
    response = Response(row.response_json, status=row.http_status, mimetype="application/json")
    response.headers["Idempotent-Replay"] = "true"
    return response


def idempotent_write(scope: str):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            client_key = request.headers.get("Idempotency-Key")
            if not client_key:
                return view(*args, **kwargs)
            if not 1 <= len(client_key) <= 128:
                return jsonify({"error": "Idempotency-Key must be 1-128 characters"}), 400
            org_id = g.current_org_id
            who = getattr(getattr(g, "current_user", None), "id", "")
            key = scope + ":" + hashlib.sha256(f"{who}:{client_key}".encode()).hexdigest()
            payload_hash = hashlib.sha256(request.get_data()).hexdigest()

            existing = _row(org_id, key)
            if existing is not None:
                return _answer(existing, payload_hash)
            db_session.add(
                ApiIdempotencyKey(
                    org_id=org_id, key=key, payload_hash=payload_hash, response_json="{}", http_status=PENDING
                )
            )
            try:
                db_session.commit()
            except IntegrityError:  # a parallel retry claimed it first
                db_session.rollback()
                return _answer(_row(org_id, key), payload_hash)

            try:
                response = make_response(view(*args, **kwargs))
            except Exception:
                db_session.rollback()
                db_session.query(ApiIdempotencyKey).filter(
                    ApiIdempotencyKey.org_id == org_id, ApiIdempotencyKey.key == key
                ).delete(synchronize_session=False)
                db_session.commit()
                raise
            row = _row(org_id, key)
            if row is not None:
                if 200 <= response.status_code < 300:
                    row.response_json = response.get_data(as_text=True)
                    row.http_status = response.status_code
                else:
                    db_session.delete(row)
                db_session.commit()
            return response

        return wrapped

    return decorate
