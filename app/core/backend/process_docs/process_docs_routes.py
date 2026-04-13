"""API routes for process step documentation (SOP): upload, inline, list, delete, download."""

import logging
from io import BytesIO
from uuid import UUID

from flask import g, jsonify, request, send_file

from app.core.backend.process_docs.process_docs_service import (
    create_or_update_inline,
    delete_document,
    get_file_for_download,
    list_docs_for_step,
    upload_sop_file,
)
from app.core.backend.process_docs.process_docs_validation import (
    get_allowed_mime_types,
    get_max_file_size_bytes,
    validate_file_streaming,
    validate_inline_request,
    validate_upload_request,
)
from app.core.db.models.user import UserRole
from app.core.security.permissions import requires_auth, requires_role
from app.core.utils.log_action import log_action

logger = logging.getLogger(__name__)


def _org_uuid():
    org_id = getattr(g, "org_id", None) or getattr(g, "current_org_id", None)
    if not org_id:
        return None
    try:
        return UUID(org_id) if isinstance(org_id, str) else org_id
    except (ValueError, TypeError):
        return None


def _user_id_uuid():
    uid = getattr(g, "user_id", None) or (getattr(g, "current_user", None) and getattr(g.current_user, "id", None))
    if not uid:
        return None
    try:
        return UUID(uid) if isinstance(uid, str) else uid
    except (ValueError, TypeError):
        return None


def register_routes(bp):
    @bp.route("/api/core/process-docs/config", methods=["GET"])
    @requires_auth
    def process_docs_config():
        """Return process doc upload limits for frontend."""
        return jsonify(
            {
                "max_file_size_bytes": get_max_file_size_bytes(),
                "allowed_mime_types": get_allowed_mime_types(),
            }
        )

    @bp.route("/api/core/process-docs/upload", methods=["POST"])
    @requires_auth
    def process_docs_upload():
        """Upload an SOP file for a process step (same auth as POST /processes/.../steps)."""
        org_id = _org_uuid()
        if not org_id:
            return jsonify({"error": "Organisation context required"}), 400
        process_id = request.form.get("process_id", "").strip()
        step_id = request.form.get("step_id", "").strip()
        title = request.form.get("title", "").strip()
        ok, err = validate_upload_request(org_id, process_id, step_id)
        if not ok:
            return jsonify({"error": err}), 400
        ok, err, temp_path, content_type, original_filename, file_size = validate_file_streaming()
        if not ok:
            return jsonify({"error": err}), 400
        try:
            p_uuid = UUID(process_id)
            s_uuid = UUID(step_id)
        except (ValueError, TypeError):
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            return jsonify({"error": "Invalid process_id or step_id"}), 400

        result, err_msg, status = upload_sop_file(
            org_id=org_id,
            process_id=p_uuid,
            step_id=s_uuid,
            temp_path=temp_path,
            title=title or None,
            content_type=content_type,
            file_size=file_size,
            original_filename=original_filename,
            created_by=_user_id_uuid(),
        )
        if err_msg:
            return jsonify({"error": err_msg}), status
        log_action(
            "upload",
            "process_step_document",
            result.get("id") and UUID(result["id"]),
            {
                "process_id": process_id,
                "step_id": step_id,
                "title": result.get("title"),
                "file_size": result.get("file_size"),
            },
            org_id,
            _user_id_uuid(),
        )
        return jsonify(result), 201

    @bp.route("/api/core/process-docs/inline", methods=["POST"])
    @requires_auth
    def process_docs_inline():
        """Create or update inline SOP (same auth as step create/update)."""
        org_id = _org_uuid()
        if not org_id:
            return jsonify({"error": "Organisation context required"}), 400
        data = request.get_json() or {}
        process_id_s = data.get("process_id", "").strip()
        step_id_s = data.get("step_id", "").strip()
        title = (data.get("title") or "").strip()
        content_markdown = data.get("content_markdown")
        document_id_s = (data.get("document_id") or "").strip() or None
        if content_markdown is not None and not isinstance(content_markdown, str):
            content_markdown = str(content_markdown)
        try:
            p_uuid = UUID(process_id_s) if process_id_s else None
            s_uuid = UUID(step_id_s) if step_id_s else None
            doc_uuid = UUID(document_id_s) if document_id_s else None
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid process_id, step_id, or document_id"}), 400
        if not p_uuid or not s_uuid:
            return jsonify({"error": "process_id and step_id are required"}), 400
        ok, err = validate_inline_request(org_id, p_uuid, s_uuid, title, content_markdown or "")
        if not ok:
            return jsonify({"error": err}), 400
        result, err_msg, status = create_or_update_inline(
            org_id=org_id,
            process_id=p_uuid,
            step_id=s_uuid,
            title=title,
            content_markdown=content_markdown or "",
            created_by=_user_id_uuid(),
            document_id=doc_uuid,
        )
        if err_msg:
            return jsonify({"error": err_msg}), status
        log_action(
            "create" if status == 201 else "update",
            "process_step_document",
            result.get("id") and UUID(result["id"]),
            {"process_id": process_id_s, "step_id": step_id_s, "title": result.get("title")},
            org_id,
            _user_id_uuid(),
        )
        return jsonify(result), status

    @bp.route("/api/core/process-docs/<step_id>", methods=["GET"])
    @requires_auth
    def process_docs_list(step_id: str):
        """List all SOP documents for a step (for execution modal). Read-only for any authenticated user."""
        org_id = _org_uuid()
        if not org_id:
            return jsonify({"error": "Organisation context required"}), 400
        try:
            step_uuid = UUID(step_id)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid step_id"}), 400
        items = list_docs_for_step(step_uuid, org_id)
        return jsonify({"documents": items})

    @bp.route("/api/core/process-docs/<doc_id>/download", methods=["GET"])
    @requires_auth
    def process_docs_download(doc_id: str):
        """Stream SOP file; verify org ownership. Read-only for any authenticated user."""
        org_id = _org_uuid()
        if not org_id:
            return jsonify({"error": "Organisation context required"}), 400
        try:
            doc_uuid = UUID(doc_id)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid document ID"}), 400
        file_bytes, mime_type, file_name, err = get_file_for_download(doc_uuid, org_id)
        if err:
            if "not found" in err.lower() or "access denied" in err.lower() or "inline" in err.lower():
                return jsonify({"error": err}), 404
            return jsonify({"error": err}), 400
        inline = request.args.get("inline") or request.args.get("view")
        as_attachment = not (inline and str(inline).strip().lower() in ("1", "true", "yes"))
        response = send_file(
            BytesIO(file_bytes),
            mimetype=mime_type or "application/octet-stream",
            as_attachment=as_attachment,
            download_name=file_name or "document",
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @bp.route("/api/core/process-docs/<doc_id>", methods=["DELETE"])
    @requires_auth
    @requires_role(UserRole.ADMIN)
    def process_docs_delete(doc_id: str):
        """Soft-delete an SOP document. Admin only."""
        org_id = _org_uuid()
        if not org_id:
            return jsonify({"error": "Organisation context required"}), 400
        try:
            doc_uuid = UUID(doc_id)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid document ID"}), 400
        success, err_msg, status = delete_document(doc_uuid, org_id)
        if not success:
            return jsonify({"error": err_msg}), status
        log_action("delete", "process_step_document", doc_uuid, {}, org_id, _user_id_uuid())
        return jsonify({"deleted": True}), 200
