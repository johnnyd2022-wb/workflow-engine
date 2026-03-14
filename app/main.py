"""Main entry point for the application"""

import os
import sys

from app.api.app_factory import create_app
from app.utils.config_loader import config

# Add parent directory to path so 'app' can be imported as a package
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Create app
app = create_app()

if __name__ == "__main__":
    # Resolve SSL certificate paths
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
