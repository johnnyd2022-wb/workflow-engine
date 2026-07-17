import os
import sys

# Add parent directory to path so 'app' can be imported as a package
# This is needed when running app/app.py directly
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import datetime

# Import xero client stuff here
import subprocess

from flask import redirect, url_for

from app.api.app_factory import create_app
from app.core.security.permissions import requires_auth
from app.initialize import db_conn
from app.observability import get_logger
from app.utils.config_loader import config

# Create app using factory (blueprints are registered in create_app)
app = create_app()
LOGGER = get_logger(__name__)


# Log feature status from configuration
def log_feature_status():
    """Log configuration sections and values with ZERO maintenance required"""
    # Access the underlying ConfigParser object from config
    configparser_obj = config.config

    section_snapshot: dict[str, dict] = {}
    # Process each section dynamically - NO HARDCODED LOGIC
    for section_name in sorted(configparser_obj.sections()):
        section_snapshot[section_name] = {}

        for key, value in configparser_obj[section_name].items():
            # Convert snake_case to readable format
            # Handle boolean values (true/false) - ONLY check the value itself
            if value.lower() in ["true", "false"]:
                section_snapshot[section_name][key] = value.lower() == "true"
            else:
                # Hide sensitive information
                if any(sensitive_word in key.lower() for sensitive_word in ["password", "secret", "token", "key"]):
                    section_snapshot[section_name][key] = "***HIDDEN***"
                else:
                    section_snapshot[section_name][key] = value

    # Dynamically detect and log blueprint registrations by checking Flask app
    blueprints = []
    for blueprint_name, blueprint in app.blueprints.items():
        _ = blueprint
        # Skip the default Flask blueprints and only show custom blueprints
        if blueprint_name not in ["static", "url_defaults"]:
            blueprints.append(blueprint_name)

    LOGGER.info("feature_status", sections=section_snapshot, blueprints=blueprints)


# Call the logging function
log_feature_status()


@app.route("/")
def index():
    """Landing page with sign-up and login"""
    import os

    from flask import render_template_string

    # Get the path to the landing.html file in ui/templates
    app_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(app_dir, "ui", "templates", "landing.html")

    with open(template_path, encoding="utf-8") as f:
        template_content = f.read()

    return render_template_string(template_content)


@app.route("/landing-diagram")
def landing_diagram():
    """Serve the biz-e operational diagram (embedded on landing page via iframe)"""
    import os

    from flask import send_from_directory

    app_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(app_dir, "ui", "templates")
    return send_from_directory(templates_dir, "biz-e-diagram-landing.html")


@app.route("/dashboard")
@requires_auth
def dashboard():
    """Alias for the core dashboard."""
    return redirect("/core/dashboard")


@app.route("/healthcheck")
def healthcheck():
    """Health check endpoint that verifies database connectivity"""
    try:
        # Test database connection
        connection, cursor = db_conn()

        # Run a simple PostgreSQL version query
        cursor.execute("SELECT version();")
        version = cursor.fetchone()

        # Close the connection
        cursor.close()
        connection.close()

        return {
            "status": "healthy",
            "database": "connected",
            "postgresql_version": version[0] if version else "unknown",
            "timestamp": datetime.datetime.now().isoformat(),
            "environment": config.environment,
        }, 200

    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.datetime.now().isoformat(),
            "environment": config.environment,
        }, 503


## Initialize Database Calls ##


# Function to call the main() function from initialize.py
def initialize_database():
    python_executable = sys.executable
    initialize_script = "app/initialize.py"
    result = subprocess.run([python_executable, initialize_script], capture_output=True, text=True)

    if result.returncode != 0:
        LOGGER.error(
            "initialize_script_failed",
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        raise Exception(f"Database initialization failed: {result.stderr}")
    else:
        LOGGER.info("initialize_script_completed", output=result.stdout)


@app.route("/initialize", methods=["POST"])
def initialize():
    LOGGER.info("initialize_route_accessed")
    try:
        initialize_database()
        return redirect(url_for("index"))
    except Exception as e:
        LOGGER.exception("initialize_route_failed", error=str(e))
        return f"Database initialization failed: {str(e)}", 500


if __name__ == "__main__":
    # Run the app on all available network interfaces (0.0.0.0)
    # Use configuration for host, port, and debug settings

    # Resolve SSL certificate paths relative to app.py location
    app_dir = os.path.dirname(os.path.abspath(__file__))
    cert_file = os.path.join(app_dir, "tls", "app_cert.pem")
    key_file = os.path.join(app_dir, "tls", "app_cert.key")

    # Only use SSL if certificate files exist
    ssl_context = None
    if os.path.exists(cert_file) and os.path.exists(key_file):
        ssl_context = (cert_file, key_file)
        LOGGER.info("ssl_enabled", cert_file=cert_file, key_file=key_file)
    else:
        LOGGER.warning("ssl_certificates_missing", cert_file=cert_file, key_file=key_file)

    app.run(host=config.host, port=config.port, debug=config.debug, ssl_context=ssl_context)
