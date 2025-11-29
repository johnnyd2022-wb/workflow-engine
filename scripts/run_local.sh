#!/bin/bash

# Local environment runner
export ENVIRONMENT=local
echo "🚀 Starting Workflow Engine app in LOCAL environment..."
echo "Environment: $ENVIRONMENT"
echo "Config file: config/$ENVIRONMENT.ini"

# Run the app directly with Python
python3 app.py