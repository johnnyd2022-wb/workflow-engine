#!/bin/bash
# Setup and start Flask application server for CI tests
# This script generates SSL certificates and starts the server in the background

set -e

echo "🚀 Setting up Flask application server..."

APP_PORT="$(python3 -c "import configparser; config = configparser.ConfigParser(); config.read('app/config/test.ini'); print(config.getint('app', 'port'))")"
case "$APP_PORT" in
  ''|*[!0-9]*)
    echo "❌ Could not read a numeric test app port from app/config/test.ini"
    exit 1
    ;;
esac

# Generate self-signed certificate for HTTPS (tests require HTTPS)
echo "Generating self-signed SSL certificate..."
mkdir -p app/tls
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout app/tls/app_cert.key \
  -out app/tls/app_cert.pem \
  -days 365 \
  -subj "/C=US/ST=State/L=City/O=Org/CN=localhost" \
  2>/dev/null || true

# Start server in background
echo "Starting Flask application server..."
# Debug: Show current directory and directory structure
PROJECT_ROOT="$(pwd)"
echo "Current directory: $PROJECT_ROOT"
echo "Checking directory structure:"
echo "  - app/features exists: $([ -d "$PROJECT_ROOT/app/features" ] && echo "YES" || echo "NO")"
echo "  - app/features/workflow_engine exists: $([ -d "$PROJECT_ROOT/app/features/workflow_engine" ] && echo "YES" || echo "NO")"
# The features directory is at app/features/, so we need to add app/ to PYTHONPATH
# This allows 'from features.workflow_engine...' to work
APP_DIR="$PROJECT_ROOT/app"
echo "Setting PYTHONPATH to include: $APP_DIR"
# Use uv run to ensure we use the virtual environment with all dependencies
PYTHONPATH="$APP_DIR:${PYTHONPATH:-}" ENVIRONMENT=test uv run python -c "import sys; print('Python sys.path:', sys.path); import os; print('PYTHONPATH env:', os.environ.get('PYTHONPATH', 'NOT SET')); import sys; print('Can import features?', 'features' in [p.split('/')[-1] if '/' in p else p for p in sys.path])" >> /tmp/flask.log 2>&1
PYTHONPATH="$APP_DIR:${PYTHONPATH:-}" ENVIRONMENT=test uv run python -m app.main >> /tmp/flask.log 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > /tmp/flask.pid
printf 'https://localhost:%s\n' "$APP_PORT" > /tmp/flask.base-url
echo "Flask server started with PID: $SERVER_PID"

# Wait for server to be ready (check health endpoint)
echo "Waiting for Flask server to start..."
for i in {1..60}; do
  if curl -k -f -s "https://localhost:$APP_PORT/healthcheck" > /dev/null 2>&1; then
    echo "✅ Flask server is ready!"
    exit 0
  fi
  if [ $i -eq 60 ]; then
    echo "❌ Flask server failed to start after 60 seconds!"
    echo "Server logs:"
    cat /tmp/flask.log
    exit 1
  fi
  sleep 1
done
