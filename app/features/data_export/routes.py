"""GL-P10: Settings → Account → "Download all your records"."""

from __future__ import annotations

import re
from datetime import timedelta

from flask import Blueprint, Response, g, jsonify, stream_with_context
from sqlalchemy import func

from app.api.routes.auth_routes import limiter
from app.core.db import db_session
from app.core.db.models.audit_log import AuditLog
from app.core.db.models.organisation import Organisation
from app.core.security.permissions import requires_auth, requires_org_scope, requires_permission
from app.core.utils.log_action import log_action
from app.core.utils.time import utc_now
from app.features.data_export.service import ExportStats, stream_export

bp = Blueprint("data_export", __name__)

# (window, most downloads in it) per person. Counted from the audit log, so every worker
# and every restart sees the same count; the in-process limiter below is only a fast first stop.
DOWNLOAD_LIMITS = ((timedelta(hours=1), 3), (timedelta(days=1), 10))


def _over_limit(org_id, user_id) -> bool:
    now = utc_now()
    for window, most in DOWNLOAD_LIMITS:
        started = (
            db_session()
            .query(func.count(AuditLog.id))
            .filter(
                AuditLog.org_id == org_id,
                AuditLog.user_id == user_id,
                AuditLog.action == "data_export_started",
                AuditLog.timestamp >= now - window,
            )
            .scalar()
        )
        if started >= most:
            return True
    return False


def _user_key() -> str:
    user = getattr(g, "current_user", None)
    return f"data-export:{user.id}" if user is not None else "data-export:anon"


@bp.get("/api/core/export/records.zip")
@requires_auth
@requires_org_scope
@requires_permission("settings.manage")
# A full export reads every table; a handful a day is plenty for any real use.
@limiter.limit("3 per hour; 10 per day", key_func=_user_key)
def download_records():
    org_id = g.current_org_id
    user_id = g.current_user.id
    if _over_limit(org_id, user_id):
        return jsonify(
            {"error": "You've downloaded your records several times recently. Try again later.", "code": "rate_limited"}
        ), 429
    org = db_session().get(Organisation, org_id)
    org_name = org.name if org is not None else "your business"
    log_action("data_export_started", "organisation", org_id, {}, org_id, user_id)
    stats = ExportStats()

    def generate():
        yield from stream_export(db_session(), org_id, org_name, stats)
        log_action(
            "data_export_completed",
            "organisation",
            org_id,
            {"rows": sum(stats.rows.values()), "files": stats.files, "truncated": stats.truncated},
            org_id,
            user_id,
        )

    slug = re.sub(r"[^a-z0-9]+", "-", org_name.lower()).strip("-")[:40] or "business"
    filename = f"biz-e-records-{slug}-{utc_now().date().isoformat()}.zip"
    return Response(
        stream_with_context(generate()),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
