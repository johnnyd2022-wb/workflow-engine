✅ TOTP 2FA Implementation Guide (Directory-Aware & uv-Ready)

Below is the full set of instructions you can paste into Cursor and apply one by one.

1. Install dependencies with uv

Use the modern Python package:

Option A – pyotp (recommended, stable)
uv add pyotp
uv add qrcode[pil]

Option B – onetimepass (older, less maintained)

Not recommended — stick with pyotp.

2. Add 2FA fields to User model

Edit:
app/core/db/models/user.py

Add fields:
from sqlalchemy import Boolean, String

totp_secret = Column(String, nullable=True)
two_factor_enabled = Column(Boolean, default=False)

3. Generate Alembic migration

From project root:

uv run alembic revision -m "add 2fa fields to user" --autogenerate
uv run alembic upgrade head

4. Update UserRepository

File:
app/core/db/repositories/user_repo.py

Add helpers:

def set_totp_secret(self, user_id, secret: str):
    user = self.get_user_by_id(user_id)
    user.totp_secret = secret
    self.db.commit()
    return user

def enable_two_factor(self, user_id):
    user = self.get_user_by_id(user_id)
    user.two_factor_enabled = True
    self.db.commit()
    return user

def disable_two_factor(self, user_id):
    user = self.get_user_by_id(user_id)
    user.totp_secret = None
    user.two_factor_enabled = False
    self.db.commit()
    return user

5. Add AuthService support

File:
app/core/security/auth_service.py

Add:

import pyotp

def verify_totp(self, user, token: str) -> bool:
    if not user.totp_secret:
        return False
    totp = pyotp.TOTP(user.totp_secret)
    return totp.verify(token, valid_window=1)

6. Update login flow to require TOTP (if enabled)

File:
app/api/routes/auth_routes.py

After password is verified, add:
if user.two_factor_enabled:
    # Do NOT log in yet — return partial auth state
    session["pending_2fa_user_id"] = str(user.id)
    return jsonify({"requires_2fa": True}), 200

Add new route:
@auth_bp.route("/verify-2fa", methods=["POST"])
def verify_two_factor():
    data = request.json
    token = data.get("token")

    pending = session.get("pending_2fa_user_id")
    if not pending:
        return jsonify({"error": "No pending 2FA session"}), 401

    user = user_repo.get_user_by_id(UUID(pending))
    if not user:
        return jsonify({"error": "User not found"}), 404

    if not auth_service.verify_totp(user, token):
        return jsonify({"error": "Invalid 2FA token"}), 401

    # Complete login
    session["user_id"] = pending
    session.pop("pending_2fa_user_id", None)

    return jsonify({"success": True}), 200

7. Add enrollment endpoints

Still inside auth_routes.py:

Create a secret + QR code
import pyotp
import base64

@auth_bp.route("/2fa/enroll", methods=["POST"])
@requires_auth
def enroll_2fa():
    user = g.current_user

    new_secret = pyotp.random_base32()
    user_repo.set_totp_secret(user.id, new_secret)

    totp = pyotp.TOTP(new_secret)
    provisioning_uri = totp.provisioning_uri(
        name=user.email,
        issuer_name="WorkflowEngine"
    )

    return jsonify({
        "secret": new_secret,
        "provisioning_uri": provisioning_uri
    })

8. Enable/disable 2FA

Add:

@auth_bp.route("/2fa/enable", methods=["POST"])
@requires_auth
def enable_2fa():
    token = request.json.get("token")
    user = g.current_user

    if not auth_service.verify_totp(user, token):
        return jsonify({"error": "Invalid token"}), 400

    user_repo.enable_two_factor(user.id)
    return jsonify({"enabled": True})

@auth_bp.route("/2fa/disable", methods=["POST"])
@requires_auth
def disable_2fa():
    user_repo.disable_two_factor(g.current_user.id)
    return jsonify({"disabled": True})

9. Update /auth/me to return 2FA status

File:
app/api/routes/auth_routes.py

Inside return payload add:

"user": {
    ...
    "two_factor_enabled": g.current_user.two_factor_enabled,
}

10. Frontend Integration Instructions (UI is already built)

Since your UI exists already, update its logic:

Profile Settings Page

Add a “Security / Two-Factor Authentication” section.

Show:

Current status (two_factor_enabled)

Button: Enable 2FA

Button: Disable 2FA

When enabling:

Call /2fa/enroll

Display QR (from provisioning_uri)

User scans

User enters code

Call /2fa/enable

Login Page

After password step, if API returns:

{ "requires_2fa": true }


Then:

Show the TOTP input field

POST token to /verify-2fa

On success -> redirect to app

Reset 2FA

Expose /2fa/disable from admin UI or org-owner UI.

11. Tenant Context Compatibility

Your hardened tenant middleware is already safe.

2FA affects nothing in:

tenant loading

session user_id

/auth/me

org binding

The only session addition is:

session["pending_2fa_user_id"]


Which is deleted after verification.

This is compatible with your multi-tenant rules.

12. Optional: Log all 2FA events

Use existing audit logger:

app/core/utils/log_action.py

Add calls such as:

log_action("2fa_enrolled", user_id=g.user_id)
log_action("2fa_enabled", user_id=g.user_id)
log_action("2fa_disabled", user_id=g.user_id)
log_action("2fa_failure", user_id=user.id)

Add tests for each endpoint so we can test these never break before deploying our app and impact customers