"""GL-P10: Settings → Account → "Download all your records"."""

from __future__ import annotations

import re

from flask import Blueprint, Response, g, stream_with_context

from app.api.routes.auth_routes import limiter
from app.core.db import db_session
from app.core.db.models.organisation import Organisation
from app.core.security.permissions import requires_auth, requires_org_scope, requires_permission
from app.core.utils.log_action import log_action
from app.core.utils.time import utc_now
from app.features.data_export.service import ExportStats, stream_export

bp = Blueprint("data_export", __name__)


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
