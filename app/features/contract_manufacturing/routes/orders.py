"""Staff API. Every endpoint is also explicitly classified in access_policy.POLICY."""

from functools import wraps
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.security.permissions import has_permission, requires_auth
from app.features.contract_manufacturing.services.orders import (
    DUTY_RESPONSIBILITIES,
    MATERIALS_SOURCES,
    ORDER_STATUSES,
    ContractOrderService,
    OrderError,
    object_body,
    serialize_customer,
    serialize_line,
    serialize_order,
)

bp = Blueprint(
    "contracts",
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend/static",
    static_url_path="/contracts/static",
)


def service():
    return ContractOrderService(db_session(), UUID(g.org_id))


def production_access():
    return has_permission(g.current_user, "production.view")


def guard_recipe_write(data):
    lines = data.get("lines", []) if isinstance(data, dict) else []
    if isinstance(lines, list):
        candidates = [data, *lines]
    else:
        candidates = [data]
    if not production_access() and any(
        isinstance(line, dict)
        and any(key in line for key in ("spec_reference", "process_id", "process_version_id", "source_output_id"))
        for line in candidates
    ):
        raise OrderError("Production access is required to change specification or recipe references", 403)


def handled(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except OrderError as error:
            db_session.rollback()
            return jsonify({"error": str(error)}), error.status
        except IntegrityError:
            db_session.rollback()
            return jsonify(
                {"error": "This reference or association already exists, or its records are unavailable."}
            ), 409

    return wrapped


@bp.get("/api/core/contract-customers")
@requires_auth
@handled
def list_customers():
    return jsonify({"customers": [serialize_customer(row) for row in service().customers()]})


@bp.post("/api/core/contract-customers")
@requires_auth
@handled
def create_customer():
    row = service().save_customer(request.get_json(silent=True))
    db_session.commit()
    return jsonify({"customer": serialize_customer(row)}), 201


@bp.patch("/api/core/contract-customers/<uuid:customer_id>")
@requires_auth
@handled
def update_customer(customer_id):
    row = service().save_customer(request.get_json(silent=True), customer_id)
    db_session.commit()
    return jsonify({"customer": serialize_customer(row)})


@bp.get("/api/core/contract-orders")
@requires_auth
@handled
def list_orders():
    return jsonify(
        {
            "orders": [
                serialize_order(row, production_access())
                for row in service().orders(
                    customer_id=request.args.get("customer_id"), status=request.args.get("status")
                )
            ]
        }
    )


@bp.post("/api/core/contract-orders")
@requires_auth
@handled
def create_order():
    data = request.get_json(silent=True)
    guard_recipe_write(data)
    row = service().create_order(data)
    db_session.commit()
    return jsonify({"order": serialize_order(row, production_access())}), 201


@bp.get("/api/core/contract-orders/<uuid:order_id>")
@requires_auth
@handled
def get_order(order_id):
    return jsonify({"order": serialize_order(service().order(order_id), production_access())})


@bp.patch("/api/core/contract-orders/<uuid:order_id>")
@requires_auth
@handled
def update_order(order_id):
    row = service().update_order(order_id, request.get_json(silent=True))
    db_session.commit()
    return jsonify({"order": serialize_order(row, production_access())})


@bp.post("/api/core/contract-orders/<uuid:order_id>/lines")
@requires_auth
@handled
def create_line(order_id):
    data = request.get_json(silent=True)
    guard_recipe_write(data)
    row = service().add_line(order_id, data)
    db_session.commit()
    return jsonify({"line": serialize_line(row, production_access())}), 201


@bp.patch("/api/core/contract-orders/<uuid:order_id>/lines/<uuid:line_id>")
@requires_auth
@handled
def update_line(order_id, line_id):
    data = request.get_json(silent=True)
    guard_recipe_write(data)
    row = service().update_line(order_id, line_id, data)
    db_session.commit()
    return jsonify({"line": serialize_line(row, production_access())})


@bp.post("/api/core/contract-orders/<uuid:order_id>/lines/<uuid:line_id>/batches")
@requires_auth
@handled
def link_batch(order_id, line_id):
    data = request.get_json(silent=True)
    object_body(data, {"execution_id"})
    row = service().link_batch(order_id, line_id, data.get("execution_id"))
    db_session.commit()
    return jsonify({"execution_id": str(row.execution_id), "line_id": str(row.line_id)}), 201


@bp.delete("/api/core/contract-orders/<uuid:order_id>/lines/<uuid:line_id>/batches/<uuid:execution_id>")
@requires_auth
@handled
def unlink_batch(order_id, line_id, execution_id):
    service().unlink_batch(order_id, line_id, execution_id)
    db_session.commit()
    return "", 204


def page_context():
    svc = service()
    return dict(
        active_page="contracts",
        duty_choices=DUTY_RESPONSIBILITIES,
        materials_choices=MATERIALS_SOURCES,
        status_choices=ORDER_STATUSES,
        crm_contacts=svc.crm_choices() if has_permission(g.current_user, "sales.view") else [],
        recipe_outputs=svc.recipe_choices() if production_access() else [],
        available_batches=svc.batch_choices() if has_permission(g.current_user, "production.record") else [],
    )


@bp.get("/core/contracts")
@requires_auth
@handled
def home():
    orders = service().orders()
    customers = service().customers() if has_permission(g.current_user, "sales.view") else []
    return render_template(
        "contracts/home.html",
        orders=[serialize_order(row, production_access()) for row in orders],
        customers=[serialize_customer(row) for row in customers],
        **page_context(),
    )


@bp.get("/core/contracts/<uuid:order_id>")
@requires_auth
@handled
def order_page(order_id):
    return render_template(
        "contracts/order.html", order=serialize_order(service().order(order_id), production_access()), **page_context()
    )
