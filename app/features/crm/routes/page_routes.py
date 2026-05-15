"""CRM page routes — serve HTML SPA pages."""

import logging

from flask import Blueprint, render_template

from app.core.security.permissions import requires_auth

logger = logging.getLogger(__name__)

page_bp = Blueprint("crm_pages", __name__, template_folder="../frontend/templates")


@page_bp.route("/crm", methods=["GET"])
@requires_auth
def crm_index():
    return render_template("crm/overview.html", active_page="crm")


@page_bp.route("/crm/customers", methods=["GET"])
@requires_auth
def crm_customers():
    return render_template("crm/customers.html", active_page="crm")


@page_bp.route("/crm/customers/<contact_id>", methods=["GET"])
@requires_auth
def crm_customer_detail(contact_id: str):
    return render_template("crm/customer_detail.html", active_page="crm", contact_id=contact_id)


@page_bp.route("/crm/tasks", methods=["GET"])
@requires_auth
def crm_tasks():
    return render_template("crm/tasks.html", active_page="crm")


@page_bp.route("/crm/analytics", methods=["GET"])
@requires_auth
def crm_analytics():
    return render_template("crm/analytics.html", active_page="crm")


@page_bp.route("/crm/configuration", methods=["GET"])
@requires_auth
def crm_configuration():
    return render_template("crm/configuration.html", active_page="crm")
