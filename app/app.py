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
from initialize import db_conn

from app.api.app_factory import create_app
from app.core.security.permissions import requires_auth
from app.utils.config_loader import config

# Create app using factory (blueprints are registered in create_app)
app = create_app()


# Log feature status from configuration
def log_feature_status():
    """Log configuration sections and values with ZERO maintenance required"""
    print("🔧 FEATURE STATUS FROM CONFIGURATION:")
    print()

    # Access the underlying ConfigParser object from config
    configparser_obj = config.config

    # Process each section dynamically - NO HARDCODED LOGIC
    for section_name in sorted(configparser_obj.sections()):
        print(f"⚙️ {section_name.upper()}:")

        for key, value in configparser_obj[section_name].items():
            # Convert snake_case to readable format
            readable_key = key.replace("_", " ").title()

            # Handle boolean values (true/false) - ONLY check the value itself
            if value.lower() in ["true", "false"]:
                is_enabled = value.lower() == "true"
                status = "✅" if is_enabled else "❌"
                print(f"   {status} {readable_key}")
            else:
                # Hide sensitive information
                if any(sensitive_word in key.lower() for sensitive_word in ["password", "secret", "token", "key"]):
                    print(f"   🔒 {readable_key}: ***HIDDEN***")
                else:
                    print(f"   📄 {readable_key}: {value}")
        print()

    # Dynamically detect and log blueprint registrations by checking Flask app
    print("🔗 REGISTERED BLUEPRINTS:")
    blueprint_count = 0
    for blueprint_name, blueprint in app.blueprints.items():
        # Skip the default Flask blueprints and only show custom blueprints
        if blueprint_name not in ["static", "url_defaults"]:
            friendly_name = blueprint_name.replace("_", " ").upper()
            print(f"   ✅ {friendly_name}")
            blueprint_count += 1

    if blueprint_count == 0:
        print("   ⚠️ No custom blueprints registered")

    print("=" * 50)


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
    """Alias for the workflow-engine dashboard (SPA shell + shared sidebar)."""
    return redirect("/workflow-engine/dashboard")


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
        print(f"❌ Initialize script failed with return code {result.returncode}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        raise Exception(f"Database initialization failed: {result.stderr}")
    else:
        print("✅ Database initialization completed successfully")
        print(f"Output: {result.stdout}")


@app.route("/initialize", methods=["POST"])
def initialize():
    print("Accessed /initialize route")
    try:
        initialize_database()
        return redirect(url_for("index"))
    except Exception as e:
        print(f"❌ Initialize failed: {e}")
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
        print(f"✅ SSL enabled with certificates: {cert_file}")
    else:
        print(f"⚠️  SSL certificates not found at {cert_file} or {key_file}, running without SSL")

    app.run(host=config.host, port=config.port, debug=config.debug, ssl_context=ssl_context)
