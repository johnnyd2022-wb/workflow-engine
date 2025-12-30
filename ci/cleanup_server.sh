#!/bin/bash
# Cleanup Flask application server after CI tests
# This script stops the server that was started in setup_server.sh

set -e

echo "🧹 Cleaning up Flask server..."

if [ -f /tmp/flask.pid ]; then
  SERVER_PID=$(cat /tmp/flask.pid)
  echo "Stopping Flask server (PID: $SERVER_PID)..."
  
  # Try graceful shutdown first
  kill $SERVER_PID 2>/dev/null || true
  sleep 2
  
  # Force kill if still running
  if kill -0 $SERVER_PID 2>/dev/null; then
    echo "Force killing Flask server..."
    kill -9 $SERVER_PID 2>/dev/null || true
  fi
  
  rm -f /tmp/flask.pid
  echo "✅ Flask server stopped"
else
  echo "No Flask server PID file found, server may not have been running"
fi

