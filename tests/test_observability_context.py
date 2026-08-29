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


def _build_nested_compliant_app():
    """Mirrors the real nesting in app/features/compliant/compliant_bp.py:
    create_compliant_blueprint() registers compliant_api/compliant_pages/
    compliant_tools as sub-blueprints of a parent "compliant" blueprint, so
    request.blueprint for a real request is the dotted "compliant.compliant_api"
    / "...compliant_pages" / "...compliant_tools" (or bare "compliant" for the
    parent's own /compliant/static route). The relocated dilution calculator now
    lives under compliant_tools, so it must attribute to feature "compliant".
    """
    from flask import Flask

    app = Flask(__name__)

    api_bp = Blueprint("compliant_api", __name__)
    page_bp = Blueprint("compliant_pages", __name__)
    tools_bp = Blueprint("compliant_tools", __name__)

    @api_bp.route("/api/compliant/overview", methods=["GET"])
    def overview():
        return jsonify({"feature": feature_for_request()})

    @page_bp.route("/compliant", methods=["GET"])
    def dashboard():
        return jsonify({"feature": feature_for_request()})

    @tools_bp.route("/compliant/tools", methods=["GET"])
    def tools_page():
        return jsonify({"feature": feature_for_request()})

    @tools_bp.route("/api/compliant/tools/<key>/solve", methods=["POST"])
    def tools_solve(key):
        return jsonify({"feature": feature_for_request()})

    parent_bp = Blueprint("compliant", __name__)
    parent_bp.register_blueprint(api_bp)
    parent_bp.register_blueprint(page_bp)
    parent_bp.register_blueprint(tools_bp)
    app.register_blueprint(parent_bp)

    return app


def test_feature_mapping_for_nested_compliant_blueprints():
    """Regression test: without the dotted-path entries in BLUEPRINT_FEATURE the
    nested compliant routes resolve request.blueprint to
    "compliant.compliant_api" / "...compliant_tools", which would fall through to
    "platform" instead of "compliant" — breaking feature-scoped triage for the
    whole Compliant product area, including the relocated dilution calculator.
    """
    app = _build_nested_compliant_app()

    with app.test_client() as client:
        assert client.get("/api/compliant/overview").get_json()["feature"] == "compliant"
        assert client.get("/compliant").get_json()["feature"] == "compliant"
        assert client.get("/compliant/tools").get_json()["feature"] == "compliant"
        assert client.post("/api/compliant/tools/dilution/solve").get_json()["feature"] == "compliant"


def test_dilution_calculator_feature_mappings_are_gone():
    """The standalone dilution_calculator blueprint was removed — its dotted-path
    BLUEPRINT_FEATURE entries must not linger (a map key for a nonexistent blueprint is
    dead config that hides a real mapping bug)."""
    from app.observability.context import BLUEPRINT_FEATURE

    assert not any("dilution_calculator" in k for k in BLUEPRINT_FEATURE)
    assert BLUEPRINT_FEATURE.get("compliant") == "compliant"
    assert BLUEPRINT_FEATURE.get("compliant.compliant_pages") == "compliant"


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
