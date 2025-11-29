"""API-related CLI commands"""
import click
import sys
import os
from pathlib import Path

# Add the parent directory to the path so we can import app modules
# This must be done before importing app modules
current_dir = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.dirname(current_dir)
parent_dir = os.path.dirname(app_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

# Import the Flask app and config (after path setup)
from app.app import app  # noqa: E402
from app.utils.config_loader import config  # noqa: E402


def get_ssl_context():
    """Get SSL context paths relative to app directory"""
    app_dir_path = Path(__file__).parent.parent
    cert_file = app_dir_path / 'tls' / 'wb_cert.pem'
    key_file = app_dir_path / 'tls' / 'wb_cert.key'
    return (str(cert_file), str(key_file))


@click.command()
def start():
    """Start the Flask application"""
    # Run the app using the same configuration as app.py
    app.run(
        host=config.host,
        port=config.port,
        debug=config.debug,
        ssl_context=get_ssl_context()
    )


@click.command()
@click.option('--host', default=None, help='Host to bind to (overrides config)')
@click.option('--port', default=None, type=int, help='Port to bind to (overrides config)')
@click.option('--debug/--no-debug', default=None, help='Enable/disable debug mode (overrides config)')
def serve(host, port, debug):
    """Start the Flask application with optional overrides"""
    # Use provided options or fall back to config
    host = host or config.host
    port = port or config.port
    debug = debug if debug is not None else config.debug
    
    app.run(
        host=host,
        port=port,
        debug=debug,
        ssl_context=get_ssl_context()
    )

