import json
import subprocess
import sys

import requests
import urllib3

"""Quick test script for multi-tenant API endpoints"""

# Disable SSL verification for local development with self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://localhost:8005"
session = requests.Session()
session.verify = False  # Disable SSL verification for local testing


def print_response(title, response):
    """Pretty print API response"""
    print(f"\n{'=' * 60}")
    print(f"{title}")
    print(f"{'=' * 60}")
    print(f"Status: {response.status_code}")
    try:
        print(f"Response:\n{json.dumps(response.json(), indent=2)}")
    except (ValueError, requests.exceptions.JSONDecodeError):
        print(f"Response: {response.text}")


def main():
    print("🚀 Testing Multi-Tenant API Endpoints")
    print(f"Base URL: {BASE_URL}\n")

    # Clean up any existing test data first (optional - comment out if you want to keep data)
    # Uncomment the next 3 lines to auto-cleanup before testing:
    print("🧹 Cleaning up previous test data...")
    subprocess.run([sys.executable, "cleanup_test_data.py"], check=False)

    # 1. Sign Up
    print_response(
        "1. SIGN UP - Create Organisation + Admin User",
        session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": "Test Company",
                "email": "admin@test.com",
                "password": "SecurePass123!",
            },
        ),
    )

    if session.cookies.get("session"):
        print("✅ Session cookie received")

    # 2. Get Current User
    print_response("2. GET CURRENT USER", session.get(f"{BASE_URL}/auth/me"))

    # 3. Get Organisation
    print_response("3. GET ORGANISATION", session.get(f"{BASE_URL}/org"))

    # 4. Update Organisation
    print_response(
        "4. UPDATE ORGANISATION (Admin Only)",
        session.patch(
            f"{BASE_URL}/org",
            json={"name": "Test Company Updated"},
        ),
    )

    # 5. List Users
    print_response("5. LIST USERS", session.get(f"{BASE_URL}/org/users"))

    # 6. Create New User
    print_response(
        "6. CREATE USER (Admin Only)",
        session.post(
            f"{BASE_URL}/org/users",
            json={
                "email": "member@test.com",
                "password": "MemberPass123!",
                "role": "member",
            },
        ),
    )

    # 7. List Users Again (should show new user)
    print_response("7. LIST USERS (After Creation)", session.get(f"{BASE_URL}/org/users"))

    # 8. Logout
    print_response("8. LOGOUT", session.post(f"{BASE_URL}/auth/logout"))

    print("\n" + "=" * 60)
    print("✅ Test Complete!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError:
        print("❌ Error: Could not connect to server.")
        print(f"   Make sure the app is running on {BASE_URL}")
        print("   Start it with: uv run workflow serve")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
