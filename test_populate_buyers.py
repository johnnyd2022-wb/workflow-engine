import os
import sys
from flask import Flask, session
from app import populate_buyers, xero, get_tenant_id

# Create a test Flask application
app = Flask(__name__)
app.secret_key = os.urandom(24)

def test_populate_buyers():
    with app.test_request_context():
        # Simulate a Xero session token
        # Replace these values with your actual test token
        session['xero_token'] = {
            'access_token': 'YOUR_TEST_ACCESS_TOKEN',
            'token_type': 'Bearer',
            'expires_in': 1800,
            'refresh_token': 'YOUR_TEST_REFRESH_TOKEN'
        }
        
        # Call the populate_buyers function
        result = populate_buyers()
        print(f"Result: {result}")

if __name__ == "__main__":
    test_populate_buyers() 