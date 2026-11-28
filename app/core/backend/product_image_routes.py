"""Authenticated final product photos for workflows and inventory lots."""

from io import BytesIO

from flask import abort, g, request, send_file, url_for

from app.core.db import db_session
from app.core.db.repositories.product_image_repo import ProductImageRepository
from app.core.security.permissions import requires_auth
from app.core.services.product_images import MAX_UPLOAD_BYTES, InvalidProductImageError, normalize_product_image
from app.observability import get_logger
from app.utils.request_validation import InvalidInputError, JsonInput, read_form

logger = get_logger(__name__)


class ProductImageForm(JsonInput):
    """Multipart accepts only the file and the standard CSRF field."""


def workflow_image_url(process_id, image_ids):
    if process_id in image_ids:
        return url_for("core.get_workflow_product_image", process_id=process_id)
    return None


def _send_image(content):
    if content is None:
        abort(404)
    response = send_file(BytesIO(content), mimetype="image/webp", download_name="product.webp", etag=False)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def register_routes(bp):
    @bp.get("/api/core/processes/<uuid:process_id>/product-image")
    @requires_auth
    def get_workflow_product_image(process_id):
        return _send_image(ProductImageRepository(db_session).workflow_image(g.current_org_id, process_id))

    @bp.put("/api/core/processes/<uuid:process_id>/product-image")
    @requires_auth
    def put_workflow_product_image(process_id):
        org_id = g.current_org_id
        repo = ProductImageRepository(db_session)
        try:
            read_form(ProductImageForm)
            files = request.files.getlist("file")
            if set(request.files) != {"file"} or len(files) != 1:
                raise InvalidInputError({"file": "Choose one final product image."})
            upload = files[0]
            content = normalize_product_image(upload.stream.read(MAX_UPLOAD_BYTES + 1), upload.mimetype)
        except InvalidProductImageError as exc:
            return InvalidInputError({"file": str(exc)}).response()
        except InvalidInputError as exc:
            return exc.response()

        if not repo.lock_workflow(org_id, process_id):
            abort(404)
        repo.save(org_id, process_id, content)
        db_session.commit()
        logger.info("product_image.saved", org_id=str(org_id), process_id=str(process_id))
        return {"product_image_url": url_for("core.get_workflow_product_image", process_id=process_id)}

    @bp.delete("/api/core/processes/<uuid:process_id>/product-image")
    @requires_auth
    def delete_workflow_product_image(process_id):
        org_id = g.current_org_id
        repo = ProductImageRepository(db_session)
        if not repo.lock_workflow(org_id, process_id):
            abort(404)
        repo.remove(org_id, process_id)
        db_session.commit()
        logger.info("product_image.removed", org_id=str(org_id), process_id=str(process_id))
        return "", 204

    @bp.get("/api/core/inventory/<uuid:item_id>/product-image")
    @requires_auth
    def get_inventory_product_image(item_id):
        return _send_image(ProductImageRepository(db_session).inventory_image(g.current_org_id, item_id))
