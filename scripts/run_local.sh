#!/bin/bash

# Local environment runner
export WB_ENVIRONMENT=local
echo "🚀 Starting WhistleBird app in LOCAL environment..."
echo "Environment: $WB_ENVIRONMENT"
echo "Config file: config/$WB_ENVIRONMENT.ini"

# Run the app directly with Python
python3 app.py