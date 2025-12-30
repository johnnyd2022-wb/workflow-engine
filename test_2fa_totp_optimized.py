"""Optimized tests for TOTP 2FA endpoints - uses time manipulation to avoid waiting"""

from uuid import uuid4
import time

import pyotp
import pytest
import requests
import urllib3

# Disable SSL verification for local development with self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://localhost:8005"


class Test2FATOTP:
    """Test suite for TOTP 2FA functionality - optimized version"""

    @pytest.fixture(autouse=True)
    def setup_session(self):
        """Create a fresh session for each test"""
        self.session = requests.Session()
        self.session.verify = False
        yield
        # Cleanup: logout if logged in
        try:
            self.session.post(f"{BASE_URL}/auth/logout")
        except Exception:
            pass

    def _generate_two_different_tokens(self, secret: str):
        """Helper to generate two different TOTP tokens without waiting
        
        Uses pyotp's at() method to generate tokens for different time windows.
        This avoids waiting 30 seconds for the next TOTP window.
        """
        totp = pyotp.TOTP(secret)
        current_time = int(time.time())
        
        # Generate token for current time window
        token1 = totp.at(current_time)
        
        # Generate token for next time window (30 seconds later)
        token2 = totp.at(current_time + 30)
        
        # If they're somehow the same (shouldn't happen), use the window after that
        if token1 == token2:
            token2 = totp.at(current_time + 60)
        
        return token1, token2

    def test_enroll_2fa_requires_authentication(self):
        """Test that /2fa/enroll requires authentication"""
        response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        assert response.status_code == 401

    def test_enable_2fa_requires_authentication(self):
        """Test that /2fa/enable requires authentication"""
        response = self.session.post(f"{BASE_URL}/auth/2fa/enable", json={"token1": "123456", "token2": "654321"})
        assert response.status_code == 401

    def test_disable_2fa_requires_authentication(self):
        """Test that /2fa/disable requires authentication"""
        response = self.session.post(f"{BASE_URL}/auth/2fa/disable")
        assert response.status_code == 401

    def test_enroll_2fa_generates_secret_and_uri(self):
        """Test that enrolling in 2FA generates a secret and provisioning URI"""
        # First, sign up and login
        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": f"test_{uuid4().hex[:8]}@test.com",
                "password": "TestPass123!",
                "password_confirm": "TestPass123!",
            },
        )
        assert signup_response.status_code == 201

        # Enroll in 2FA
        enroll_response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        assert enroll_response.status_code == 200

        data = enroll_response.json()
        assert "secret" in data
        assert "provisioning_uri" in data
        assert len(data["secret"]) > 0
        assert len(data["provisioning_uri"]) > 0
        assert "otpauth://" in data["provisioning_uri"]

    def test_enable_2fa_with_valid_tokens(self):
        """Test enabling 2FA with two valid TOTP tokens"""
        # Sign up and login
        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": f"test_{uuid4().hex[:8]}@test.com",
                "password": "TestPass123!",
                "password_confirm": "TestPass123!",
            },
        )
        assert signup_response.status_code == 201

        # Enroll in 2FA
        enroll_response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        assert enroll_response.status_code == 200
        secret = enroll_response.json()["secret"]

        # Generate two different TOTP tokens using optimized method
        token1, token2 = self._generate_two_different_tokens(secret)

        # Enable 2FA with both tokens
        enable_response = self.session.post(
            f"{BASE_URL}/auth/2fa/enable", json={"token1": token1, "token2": token2}
        )
        assert enable_response.status_code == 200
        data = enable_response.json()
        assert data["enabled"] is True
        assert "backup_codes" in data
        assert len(data["backup_codes"]) == 10

        # Verify 2FA is enabled in /auth/me
        me_response = self.session.get(f"{BASE_URL}/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["user"]["two_factor_enabled"] is True

    def test_enable_2fa_with_invalid_token(self):
        """Test enabling 2FA with an invalid token fails"""
        # Sign up and login
        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": f"test_{uuid4().hex[:8]}@test.com",
                "password": "TestPass123!",
                "password_confirm": "TestPass123!",
            },
        )
        assert signup_response.status_code == 201

        # Enroll in 2FA
        enroll_response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        assert enroll_response.status_code == 200
        secret = enroll_response.json()["secret"]

        # Generate one valid token
        token1, token2 = self._generate_two_different_tokens(secret)

        # Try to enable with invalid first token
        enable_response = self.session.post(
            f"{BASE_URL}/auth/2fa/enable", json={"token1": "000000", "token2": token2}
        )
        assert enable_response.status_code == 400
        assert "Invalid first token" in enable_response.json()["error"]

        # Try with invalid second token
        enable_response = self.session.post(
            f"{BASE_URL}/auth/2fa/enable", json={"token1": token1, "token2": "000000"}
        )
        assert enable_response.status_code == 400
        assert "Invalid second token" in enable_response.json()["error"]

    def test_disable_2fa(self):
        """Test disabling 2FA"""
        # Sign up and login
        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": f"test_{uuid4().hex[:8]}@test.com",
                "password": "TestPass123!",
                "password_confirm": "TestPass123!",
            },
        )
        assert signup_response.status_code == 201

        # Enroll and enable 2FA
        enroll_response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        secret = enroll_response.json()["secret"]
        token1, token2 = self._generate_two_different_tokens(secret)

        enable_response = self.session.post(
            f"{BASE_URL}/auth/2fa/enable", json={"token1": token1, "token2": token2}
        )
        assert enable_response.status_code == 200

        # Verify it's enabled
        me_response = self.session.get(f"{BASE_URL}/auth/me")
        assert me_response.json()["user"]["two_factor_enabled"] is True

        # Disable 2FA
        disable_response = self.session.post(f"{BASE_URL}/auth/2fa/disable")
        assert disable_response.status_code == 200
        assert disable_response.json()["disabled"] is True

        # Verify it's disabled
        me_response = self.session.get(f"{BASE_URL}/auth/me")
        assert me_response.json()["user"]["two_factor_enabled"] is False

    def test_login_without_2fa_enabled(self):
        """Test that login works normally when 2FA is not enabled"""
        # Sign up
        email = f"test_{uuid4().hex[:8]}@test.com"
        password = "TestPass123!"

        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": email,
                "password": password,
                "password_confirm": password,
            },
        )
        assert signup_response.status_code == 201

        # Logout
        self.session.post(f"{BASE_URL}/auth/logout")

        # Login (should work without 2FA)
        login_response = self.session.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
        assert login_response.status_code == 200
        assert "requires_2fa" not in login_response.json()

    def test_login_with_2fa_enabled_requires_token(self):
        """Test that login requires 2FA token when 2FA is enabled"""
        # Sign up
        email = f"test_{uuid4().hex[:8]}@test.com"
        password = "TestPass123!"

        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": email,
                "password": password,
                "password_confirm": password,
            },
        )
        assert signup_response.status_code == 201

        # Enroll and enable 2FA
        enroll_response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        secret = enroll_response.json()["secret"]
        token1, token2 = self._generate_two_different_tokens(secret)

        enable_response = self.session.post(
            f"{BASE_URL}/auth/2fa/enable", json={"token1": token1, "token2": token2}
        )
        assert enable_response.status_code == 200

        # Logout
        self.session.post(f"{BASE_URL}/auth/logout")

        # Login (should require 2FA)
        login_response = self.session.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
        assert login_response.status_code == 200
        assert login_response.json()["requires_2fa"] is True

    def test_verify_2fa_with_valid_token_completes_login(self):
        """Test that verifying 2FA with valid token completes login"""
        # Sign up
        email = f"test_{uuid4().hex[:8]}@test.com"
        password = "TestPass123!"

        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": email,
                "password": password,
                "password_confirm": password,
            },
        )
        assert signup_response.status_code == 201

        # Enroll and enable 2FA
        enroll_response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        secret = enroll_response.json()["secret"]
        totp = pyotp.TOTP(secret)
        token1, token2 = self._generate_two_different_tokens(secret)

        enable_response = self.session.post(
            f"{BASE_URL}/auth/2fa/enable", json={"token1": token1, "token2": token2}
        )
        assert enable_response.status_code == 200

        # Logout
        self.session.post(f"{BASE_URL}/auth/logout")

        # Login (should require 2FA)
        login_response = self.session.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
        assert login_response.status_code == 200
        assert login_response.json()["requires_2fa"] is True

        # Verify 2FA with valid token
        verify_response = self.session.post(f"{BASE_URL}/auth/verify-2fa", json={"token": totp.now()})
        assert verify_response.status_code == 200
        assert "user" in verify_response.json()
        assert verify_response.json()["message"] == "Login successful"

        # Verify we're logged in
        me_response = self.session.get(f"{BASE_URL}/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["user"] is not None

    def test_verify_2fa_with_invalid_token_fails(self):
        """Test that verifying 2FA with invalid token fails"""
        # Sign up
        email = f"test_{uuid4().hex[:8]}@test.com"
        password = "TestPass123!"

        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": email,
                "password": password,
                "password_confirm": password,
            },
        )
        assert signup_response.status_code == 201

        # Enroll and enable 2FA
        enroll_response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        secret = enroll_response.json()["secret"]
        token1, token2 = self._generate_two_different_tokens(secret)

        enable_response = self.session.post(
            f"{BASE_URL}/auth/2fa/enable", json={"token1": token1, "token2": token2}
        )
        assert enable_response.status_code == 200

        # Logout
        self.session.post(f"{BASE_URL}/auth/logout")

        # Login (should require 2FA)
        login_response = self.session.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
        assert login_response.status_code == 200
        assert login_response.json()["requires_2fa"] is True

        # Try to verify with invalid token
        verify_response = self.session.post(f"{BASE_URL}/auth/verify-2fa", json={"token": "000000"})
        assert verify_response.status_code == 401
        assert "Invalid 2FA token" in verify_response.json()["error"]

    def test_verify_2fa_without_pending_session_fails(self):
        """Test that verifying 2FA without pending session fails"""
        response = self.session.post(f"{BASE_URL}/auth/verify-2fa", json={"token": "123456"})
        assert response.status_code == 401
        assert "No pending 2FA session" in response.json()["error"]

    def test_verify_2fa_missing_token_fails(self):
        """Test that verify-2fa requires token"""
        # Sign up and login to create pending session
        email = f"test_{uuid4().hex[:8]}@test.com"
        password = "TestPass123!"

        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": email,
                "password": password,
                "password_confirm": password,
            },
        )
        assert signup_response.status_code == 201

        # Enroll and enable 2FA
        enroll_response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        secret = enroll_response.json()["secret"]
        token1, token2 = self._generate_two_different_tokens(secret)

        enable_response = self.session.post(
            f"{BASE_URL}/auth/2fa/enable", json={"token1": token1, "token2": token2}
        )
        assert enable_response.status_code == 200

        # Logout
        self.session.post(f"{BASE_URL}/auth/logout")

        # Login to create pending session
        login_response = self.session.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
        assert login_response.status_code == 200

        # Try to verify without token (send JSON body but missing token field)
        verify_response = self.session.post(
            f"{BASE_URL}/auth/verify-2fa", 
            json={"remember_device": False}  # Send JSON but without token
        )
        assert verify_response.status_code == 400
        assert "token is required" in verify_response.json()["error"]

    def test_enable_2fa_missing_token_fails(self):
        """Test that enable-2fa requires both tokens"""
        # Sign up and login
        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": f"test_{uuid4().hex[:8]}@test.com",
                "password": "TestPass123!",
                "password_confirm": "TestPass123!",
            },
        )
        assert signup_response.status_code == 201

        # Enroll in 2FA
        enroll_response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        assert enroll_response.status_code == 200

        # Try to enable without tokens (send JSON body but missing token fields)
        enable_response = self.session.post(f"{BASE_URL}/auth/2fa/enable", json={"some_field": "value"})
        assert enable_response.status_code == 400
        assert "First token is required" in enable_response.json()["error"]

        # Try with only first token
        enable_response = self.session.post(f"{BASE_URL}/auth/2fa/enable", json={"token1": "123456"})
        assert enable_response.status_code == 400
        assert "Second token is required" in enable_response.json()["error"]

    def test_auth_me_returns_2fa_status(self):
        """Test that /auth/me returns two_factor_enabled status"""
        # Sign up
        signup_response = self.session.post(
            f"{BASE_URL}/auth/signup",
            json={
                "org_name": f"TestOrg_{uuid4().hex[:8]}",
                "email": f"test_{uuid4().hex[:8]}@test.com",
                "password": "TestPass123!",
                "password_confirm": "TestPass123!",
            },
        )
        assert signup_response.status_code == 201

        # Check initial status (should be False)
        me_response = self.session.get(f"{BASE_URL}/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["user"]["two_factor_enabled"] is False

        # Enroll and enable 2FA
        enroll_response = self.session.post(f"{BASE_URL}/auth/2fa/enroll")
        secret = enroll_response.json()["secret"]
        token1, token2 = self._generate_two_different_tokens(secret)

        enable_response = self.session.post(
            f"{BASE_URL}/auth/2fa/enable", json={"token1": token1, "token2": token2}
        )
        assert enable_response.status_code == 200

        # Check status (should be True)
        me_response = self.session.get(f"{BASE_URL}/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["user"]["two_factor_enabled"] is True

        # Disable 2FA
        disable_response = self.session.post(f"{BASE_URL}/auth/2fa/disable")
        assert disable_response.status_code == 200

        # Check status (should be False again)
        me_response = self.session.get(f"{BASE_URL}/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["user"]["two_factor_enabled"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

