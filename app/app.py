import sys
import json
from datetime import date
import datetime
import threading
import schedule
import time
from flask import Flask, render_template, redirect, url_for, request, send_file
import subprocess
from initialize import db_conn
from database_insert import insert_data
from flask import Flask, render_template, jsonify, redirect, request, session, url_for, Response, stream_with_context
import os
# Import xero client stuff here
from xero_python.api_client import ApiClient
from xero_python.accounting import AccountingApi
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.api_client.configuration import Configuration
from authlib.integrations.flask_client import OAuth
import requests
from xml.etree import ElementTree as ET
import io
import zipfile
import math
from config_loader import config

# Import CRM blueprint
from features.crm.backend.backend import crm_bp

# Import Supply Chain blueprint
from features.supply_chain.backend.backend import supply_chain_bp

app = Flask(__name__)

# Register blueprints conditionally based on config
if config.crm_enabled:
    app.register_blueprint(crm_bp)

if config.supply_chain_enabled:
    app.register_blueprint(supply_chain_bp)

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
            readable_key = key.replace('_', ' ').title()
            
            # Handle boolean values (true/false) - ONLY check the value itself
            if value.lower() in ['true', 'false']:
                is_enabled = value.lower() == 'true'
                status = '✅' if is_enabled else '❌'
                print(f"   {status} {readable_key}")
            else:
                # Hide sensitive information
                if any(sensitive_word in key.lower() for sensitive_word in ['password', 'secret', 'token', 'key']):
                    print(f"   🔒 {readable_key}: ***HIDDEN***")
                else:
                    print(f"   📄 {readable_key}: {value}")
        print()
    
    # Dynamically detect and log blueprint registrations by checking Flask app
    print("🔗 REGISTERED BLUEPRINTS:")
    blueprint_count = 0
    for blueprint_name, blueprint in app.blueprints.items():
        # Skip the default Flask blueprints and only show custom blueprints
        if blueprint_name not in ['static', 'url_defaults']:
            friendly_name = blueprint_name.replace('_', ' ').upper()
            print(f"   ✅ {friendly_name}")
            blueprint_count += 1
    
    if blueprint_count == 0:
        print("   ⚠️ No custom blueprints registered")
    
    print("="*50)

# Call the logging function
log_feature_status()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/healthcheck')
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
            'status': 'healthy',
            'database': 'connected',
            'postgresql_version': version[0] if version else 'unknown',
            'timestamp': datetime.datetime.now().isoformat(),
            'environment': config.environment
        }, 200
        
    except Exception as e:
        return {
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e),
            'timestamp': datetime.datetime.now().isoformat(),
            'environment': config.environment
        }, 503

## Initialize Database Calls ##

# Function to call the main() function from initialize.py
def initialize_database():
    python_executable = sys.executable
    initialize_script = "initialize.py"
    result = subprocess.run([python_executable, initialize_script], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ Initialize script failed with return code {result.returncode}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        raise Exception(f"Database initialization failed: {result.stderr}")
    else:
        print("✅ Database initialization completed successfully")
        print(f"Output: {result.stdout}")

@app.route('/initialize', methods=['POST'])
def initialize():
    print("Accessed /initialize route")
    try:
        initialize_database()
        return redirect(url_for('index'))
    except Exception as e:
        print(f"❌ Initialize failed: {e}")
        return f"Database initialization failed: {str(e)}", 500

if __name__ == '__main__':
    # Run the app on all available network interfaces (0.0.0.0)
    # Use configuration for host, port, and debug settings
    app.run(
        host=config.host,
        port=config.port,
        debug=config.debug,
        ssl_context=('tls/wb_cert.pem', 'tls/wb_cert.key')
    )
