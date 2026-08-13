"""Feature-tag context tests for observability request mapping."""

from flask import Blueprint, jsonify

from app.observability.context import feature_for_request


def _build_feature_app():
    from flask import Flask

    app = Flask(__name__)

    auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
    org_bp = Blueprint("org", __name__, url_prefix="/org")
    core_bp = Blueprint("core", __name__, url_prefix="/api/core")
    crm_bp = Blueprint("crm", __name__, url_prefix="/crm")

    @auth_bp.route("/feature", methods=["GET"])
    def auth_feature():
        return jsonify({"feature": feature_for_request()})

    @org_bp.route("/feature", methods=["GET"])
    def org_feature():
        return jsonify({"feature": feature_for_request()})

    @core_bp.route("/feature", methods=["GET"])
    def core_feature():
        return jsonify({"feature": feature_for_request()})

    @crm_bp.route("/feature", methods=["GET"])
    def crm_feature():
        return jsonify({"feature": feature_for_request()})

    @app.route("/feature", methods=["GET"])
    def platform_feature():
        return jsonify({"feature": feature_for_request()})

    app.register_blueprint(auth_bp)
    app.register_blueprint(org_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(crm_bp)

    return app


def test_feature_mapping_for_blueprints_and_platform_routes():
    app = _build_feature_app()

    with app.test_client() as client:
        assert client.get("/auth/feature").get_json()["feature"] == "auth"
        assert client.get("/org/feature").get_json()["feature"] == "org"
        assert client.get("/api/core/feature").get_json()["feature"] == "core"
        assert client.get("/crm/feature").get_json()["feature"] == "crm"
        assert client.get("/feature").get_json()["feature"] == "platform"


def _build_nested_dilution_calculator_app():
    """Mirrors the real nesting in
    app/features/dilution_calculator/dilution_calculator_bp.py:
    create_dilution_calculator_blueprint() registers api_bp/page_bp as
    sub-blueprints of a parent "dilution_calculator" blueprint. Flask's
    request.blueprint returns the full dotted parent.child path for a route
    reached through a nested blueprint, not just the child's own name — this
    reproduces that shape instead of the flat single-blueprint shape the other
    test in this file uses (which would pass even if the dotted-path mapping
    were missing).
    """
    from flask import Flask

    app = Flask(__name__)

    api_bp = Blueprint("dilution_calculator_api", __name__)
    page_bp = Blueprint("dilution_calculator_pages", __name__)

    @api_bp.route("/api/dilution-calculator/solve", methods=["POST"])
    def solve():
        return jsonify({"feature": feature_for_request()})

    @page_bp.route("/dilution-calculator", methods=["GET"])
    def index():
        return jsonify({"feature": feature_for_request()})

    parent_bp = Blueprint("dilution_calculator", __name__)
    parent_bp.register_blueprint(api_bp)
    parent_bp.register_blueprint(page_bp)
    app.register_blueprint(parent_bp)

    return app


def test_feature_mapping_for_nested_dilution_calculator_blueprints():
    """Regression test: without the dotted-path entries in BLUEPRINT_FEATURE,
    both routes below resolve request.blueprint to
    "dilution_calculator.dilution_calculator_api" /
    "...dilution_calculator_pages", which isn't in the map, so they'd silently
    fall through to "platform" instead of "dilution_calculator" — breaking
    feature-scoped triage/dashboards for this feature.
    """
    app = _build_nested_dilution_calculator_app()

    with app.test_client() as client:
        assert client.post("/api/dilution-calculator/solve").get_json()["feature"] == "dilution_calculator"
        assert client.get("/dilution-calculator").get_json()["feature"] == "dilution_calculator"


def _build_nested_crm_app():
    """Mirrors the real nesting in app/features/crm/crm_bp.py:
    create_crm_blueprint() registers oauth_bp/api_bp/page_bp as sub-blueprints
    of a parent "crm" blueprint. Like dilution_calculator above, this means
    request.blueprint for a real CRM request is the dotted "crm.crm_api" /
    "crm.crm_oauth" / "crm.crm_pages", not the flat child name — unlike
    test_feature_mapping_for_blueprints_and_platform_routes above, whose `crm`
    fixture is a single unnested blueprint and would stay green even if the
    dotted-path mapping were missing.
    """
    from flask import Flask

    app = Flask(__name__)

    api_bp = Blueprint("crm_api", __name__)
    oauth_bp = Blueprint("crm_oauth", __name__)
    page_bp = Blueprint("crm_pages", __name__)

    @api_bp.route("/api/crm/xero/status", methods=["GET"])
    def status():
        return jsonify({"feature": feature_for_request()})

    @oauth_bp.route("/crm/xero/auth", methods=["GET"])
    def auth():
        return jsonify({"feature": feature_for_request()})

    @page_bp.route("/crm/customers", methods=["GET"])
    def customers():
        return jsonify({"feature": feature_for_request()})

    parent_bp = Blueprint("crm", __name__)
    parent_bp.register_blueprint(oauth_bp)
    parent_bp.register_blueprint(api_bp)
    parent_bp.register_blueprint(page_bp)
    app.register_blueprint(parent_bp)

    return app


def test_feature_mapping_for_nested_crm_blueprints():
    """Regression test: real CRM requests resolve request.blueprint to
    "crm.crm_api" / "crm.crm_oauth" / "crm.crm_pages", which without the
    dotted-path entries in BLUEPRINT_FEATURE fall through to "platform"
    instead of "crm" — mislabeling every CRM observability event."""
    app = _build_nested_crm_app()

    with app.test_client() as client:
        assert client.get("/api/crm/xero/status").get_json()["feature"] == "crm"
        assert client.get("/crm/xero/auth").get_json()["feature"] == "crm"
        assert client.get("/crm/customers").get_json()["feature"] == "crm"
