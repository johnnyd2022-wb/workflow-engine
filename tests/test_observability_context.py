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
