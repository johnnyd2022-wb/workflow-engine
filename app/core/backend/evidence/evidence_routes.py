"""API routes for evidence upload and download."""

import logging
from io import BytesIO
from uuid import UUID

from flask import g, jsonify, request, send_file

from app.core.backend.evidence.evidence_service import (
    get_evidence_for_download,
    list_evidence_for_execution,
    upload_evidence_from_temp,
)
from app.core.backend.evidence.evidence_validation import (
    get_allowed_mime_types,
    get_max_file_size_bytes,
    validate_file_streaming,
    validate_upload_request,
)
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action

logger = logging.getLogger(__name__)


def register_routes(bp):
    @bp.route("/api/core/evidence/config", methods=["GET"])
    @requires_auth
    def evidence_config():
        """Return evidence upload limits (single source of truth for frontend)."""
        return jsonify({
            "max_file_size_bytes": get_max_file_size_bytes(),
            "allowed_mime_types": get_allowed_mime_types(),
        })

    @bp.route("/api/core/evidence/upload", methods=["POST"])
    @requires_auth
    def evidence_upload():
        """Upload an evidence file for an execution (optional step_id).
        Frontend may send multiple files in sequence; each is an independent record (no batch semantics)."""
        org_id = getattr(g, "org_id", None)
        if not org_id:
            return jsonify({"error": "Organisation context required"}), 400
        try:
            org_uuid = UUID(org_id) if isinstance(org_id, str) else org_id
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid organisation context"}), 400

        execution_id = request.form.get("execution_id", "").strip()
        step_id = request.form.get("step_id", "").strip() or None
        logger.info("Evidence upload request: org_id=%s execution_id=%s step_id=%s", org_uuid, execution_id, step_id)
        ok, err = validate_upload_request(org_uuid, execution_id, step_id)
        if not ok:
            logger.warning("Evidence upload validate_upload_request failed: %s", err)
            return jsonify({"error": err}), 400

        ok, err, temp_path, content_type, original_filename, file_size = validate_file_streaming()
        if not ok:
            logger.warning("Evidence upload validate_file_streaming failed: %s", err)
            return jsonify({"error": err}), 400

        try:
            execution_uuid = UUID(execution_id)
            step_uuid = UUID(step_id) if step_id else None
        except (ValueError, TypeError):
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            return jsonify({"error": "Invalid execution_id or step_id"}), 400

        user_email = (
            getattr(g, "user_email", None) or getattr(g, "user", {}).get("email") if hasattr(g, "user") else None
        )
        if isinstance(user_email, dict):
            user_email = user_email.get("email")
        uploaded_by = str(user_email) if user_email else None

        result, err_msg, status = upload_evidence_from_temp(
            org_id=org_uuid,
            execution_id=execution_uuid,
            temp_path=temp_path,
            file_name=original_filename,
            content_type=content_type,
            file_size=file_size,
            step_id=step_uuid,
            uploaded_by=uploaded_by,
        )
        if err_msg:
            logger.warning("Evidence upload_evidence returned error: %s status=%s", err_msg, status)
            return jsonify({"error": err_msg}), status

        logger.info("Evidence upload success: evidence_id=%s execution_id=%s", result.get("id"), execution_id)
        log_action(
            "upload",
            "evidence",
            result.get("id") and UUID(result["id"]),
            {"execution_id": execution_id, "file_name": original_filename, "file_size": result.get("file_size")},
            org_uuid,
            getattr(g, "user_id", None),
        )
        return jsonify(result), 201

    @bp.route("/api/core/evidence/<evidence_id>/download", methods=["GET"])
    @requires_auth
    def evidence_download(evidence_id: str):
        """Stream evidence file; verify org ownership."""
        org_id = getattr(g, "org_id", None)
        if not org_id:
            return jsonify({"error": "Organisation context required"}), 400
        try:
            org_uuid = UUID(org_id) if isinstance(org_id, str) else org_id
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid organisation context"}), 400
        try:
            eid = UUID(evidence_id)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid evidence ID"}), 400

        file_bytes, mime_type, file_name, err = get_evidence_for_download(eid, org_uuid)
        if err:
            if "not found" in err.lower() or "access denied" in err.lower():
                return jsonify({"error": err}), 404
            return jsonify({"error": err}), 400

        # inline=1 or view=1: open in browser (Content-Disposition: inline); otherwise force download
        inline = request.args.get("inline") or request.args.get("view")
        as_attachment = not (inline and str(inline).strip().lower() in ("1", "true", "yes"))

        return send_file(
            BytesIO(file_bytes),
            mimetype=mime_type or "application/octet-stream",
            as_attachment=as_attachment,
            download_name=file_name or "evidence",
        )

    @bp.route("/api/core/evidence/list", methods=["GET"])
    @requires_auth
    def evidence_list():
        """List evidence for an execution (query param: execution_id)."""
        org_id = getattr(g, "org_id", None)
        if not org_id:
            return jsonify({"error": "Organisation context required"}), 400
        try:
            org_uuid = UUID(org_id) if isinstance(org_id, str) else org_id
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid organisation context"}), 400
        execution_id = request.args.get("execution_id", "").strip()
        if not execution_id:
            return jsonify({"error": "execution_id is required"}), 400
        try:
            execution_uuid = UUID(execution_id)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid execution_id"}), 400
        items = list_evidence_for_execution(execution_uuid, org_uuid)
        return jsonify({"evidence": items})
