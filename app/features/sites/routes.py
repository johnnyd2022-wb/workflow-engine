"""Site configuration API and page; existing operational routes retain their URLs."""

from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.site_guard import SiteScopeError
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action
from app.features.sites import service

sites_bp = Blueprint(
    "sites",
    __name__,
    template_folder="frontend/templates",
    static_folder="frontend/static",
    static_url_path="/static/sites",
)


def _org():
    return UUID(g.org_id)


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise SiteScopeError("Send a JSON object")
    return data


@sites_bp.errorhandler(SiteScopeError)
def site_error(error):
    db_session.rollback()
    return jsonify({"error": str(error), "code": "invalid_site_scope"}), 400


@sites_bp.errorhandler(IntegrityError)
def site_conflict(_error):
    db_session.rollback()
    return jsonify({"error": "This site configuration conflicts with an existing record"}), 409


@sites_bp.route("/core/sites")
@requires_auth
def sites_page():
    return render_template("sites/sites.html", active_page="settings")


@sites_bp.route("/api/core/sites", methods=["GET"])
@requires_auth
def list_sites():
    return jsonify(service.overview(db_session, _org()))


@sites_bp.route("/api/core/sites/<site_id>/position", methods=["GET"])
@requires_auth
def site_position(site_id):
    if not g.current_org.multiple_sites_enabled:
        raise SiteScopeError("Multiple sites are switched off")
    site = service.get_site(db_session, _org(), service.parse_id(site_id))
    if site is None:
        return jsonify({"error": "Site not found"}), 404
    from sqlalchemy import func

    from app.core.db.models.inventory_item import InventoryItem

    rows = (
        db_session.query(
            InventoryItem.inventory_type, InventoryItem.unit, func.sum(InventoryItem.quantity), func.count()
        )
        .filter(
            InventoryItem.org_id == _org(),
            InventoryItem.site_id == site.id,
        )
        .group_by(InventoryItem.inventory_type, InventoryItem.unit)
        .order_by(InventoryItem.inventory_type, InventoryItem.unit)
        .all()
    )
    return jsonify(
        {
            "site": service.serialise(site),
            "stock": [
                {"inventory_type": kind, "unit": unit, "quantity": str(quantity), "lots": count}
                for kind, unit, quantity, count in rows
            ],
        }
    )


@sites_bp.route("/api/core/sites/settings", methods=["PUT"])
@requires_auth
def configure_sites():
    data = _body()
    if set(data) != {"enabled"}:
        raise SiteScopeError("Send only the enabled setting")
    org = service.configure(db_session, _org(), data["enabled"])
    db_session.commit()
    log_action("update", "organisation", org.id, {"multiple_sites_enabled": org.multiple_sites_enabled})
    return jsonify(service.overview(db_session, _org()))


@sites_bp.route("/api/core/sites", methods=["POST"])
@requires_auth
def create_site():
    site = service.save_site(db_session, _org(), _body())
    db_session.commit()
    log_action("create", "site", site.id, service.serialise(site))
    return jsonify(service.serialise(site)), 201


@sites_bp.route("/api/core/sites/<site_id>", methods=["PATCH"])
@requires_auth
def update_site(site_id):
    site = service.get_site(db_session, _org(), service.parse_id(site_id))
    if site is None:
        return jsonify({"error": "Site not found"}), 404
    service.save_site(db_session, _org(), _body(), site)
    db_session.commit()
    log_action("update", "site", site.id, service.serialise(site))
    return jsonify(service.serialise(site))


def install_site_request_validation(app):
    """Reject unsupported site hints before an older route could silently ignore them.

    Default-site requests need no route changes: the flush guard tags their new rows.
    Additional-site operations wait for the site-specific inventory/production slices.
    """
    tagged_endpoints = frozenset(
        {
            "core.create_inventory_item",
            "core.create_execution",
            "stock_locations.create_location",
            "core.consume_final_product_fifo",
        }
    )

    @app.before_request
    def validate_requested_site():
        if request.endpoint not in tagged_endpoints or not getattr(g, "current_user", None):
            return None
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return None
        try:
            if "site_id" not in data:
                if (
                    request.endpoint == "core.create_inventory_item"
                    and g.current_org.multiple_sites_enabled
                    and data.get("barcode")
                ):
                    from app.core.db.models.inventory_item import InventoryItem
                    from app.core.db.site_operations import resolve_site

                    existing = (
                        db_session.query(InventoryItem)
                        .filter(InventoryItem.org_id == _org(), InventoryItem.barcode == str(data["barcode"]).strip())
                        .one_or_none()
                    )
                    if existing is not None and existing.site_id != resolve_site(db_session, _org()):
                        raise SiteScopeError("Barcode stock belongs to another site; choose its site explicitly")
                return None
            if not g.current_org.multiple_sites_enabled:
                raise SiteScopeError("Multiple sites are switched off")
            site = service.get_site(db_session, _org(), service.parse_id(data["site_id"]))
            if site is None or not site.is_active:
                raise SiteScopeError("Site must be active and belong to this organisation")
            if not site.is_default and not g.current_org.multiple_site_operations_enabled:
                raise SiteScopeError("Operations at additional sites are not available yet")
            g.validated_site_id = site.id
            if request.endpoint == "core.create_inventory_item" and data.get("barcode"):
                from app.core.db.models.inventory_item import InventoryItem

                existing = (
                    db_session.query(InventoryItem)
                    .filter(InventoryItem.org_id == _org(), InventoryItem.barcode == str(data["barcode"]).strip())
                    .one_or_none()
                )
                if existing is not None and existing.site_id != site.id:
                    raise SiteScopeError("Barcode stock belongs to another site")
        except SiteScopeError as error:
            return jsonify({"error": str(error), "code": "invalid_site_scope"}), 400
        return None
