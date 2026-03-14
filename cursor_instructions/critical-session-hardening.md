You are a security-focused Python/Flask engineer. I want you to update my Flask app to address **all critical and high-priority security issues** related to authentication, session management, 2FA, and trusted devices. Make all changes directly in the files, in-place, and explain each change with a short comment. Prioritize in this order: session cookie hardening, full session wipe, normalized error messages, rate limiting enhancements, audit logging, and trusted device verification. 

Here is my current Flask app:

Files:
1. app/api/app_factory.py
2. app/api/middleware/session_security.py
3. app/api/middleware/tenant_context.py
4. app/api/routes/auth_routes.py
5. app/api/routes/org_routes.py
6. app/utils/config_loader.py
7. templates/session_expired.html

Perform the following **specific tasks**:

---

**1. app_factory.py: session cookie hardening**
- Ensure `SESSION_COOKIE_SECURE=True` in production, regardless of `request.is_secure`.
- Confirm `SESSION_COOKIE_HTTPONLY=True` and `SESSION_COOKIE_SAMESITE="Strict"`.
- Add `SESSION_COOKIE_PATH="/"` explicitly.
- Ensure `PERMANENT_SESSION_LIFETIME` is aligned with default user session timeout.

---

**2. app/api/middleware/session_security.py**
- Ensure `session.clear()` is called on logout, 2FA cancel, password change, and session expiry.
- Confirm `session.modified = True` is set after any session change.
- Add short comments explaining why each step is done.

---

**3. app/api/routes/auth_routes.py**
- Normalize error messages for login/signup to prevent user enumeration.
  Example: Replace any message like "Email already exists" or "Invalid credentials" with a generic "Cannot complete request. Check credentials or contact support."
- Update rate limiter to combine **IP + account/email** for login and 2FA endpoints.
- Ensure password hash uses **Argon2 or bcrypt**, and add code to rehash old passwords if work factor changes.
- Ensure 2FA routes log all actions (`enable`, `disable`, `verify`, `enroll`) but **do not log tokens**.

---

**4. Trusted devices (auth_routes.py + session_security.py)**
- Ensure trusted device cookie is `Secure=True, HttpOnly, SameSite=Lax, Path=/`.
- Add encryption of the token payload before storing in the cookie.
- Verify fingerprinting is robust: combine User-Agent + IP + hashed device ID.
- Ensure expiration is enforced (e.g., 30 days).

---

**5. app/api/middleware/tenant_context.py**
- Confirm no sensitive session data leaks across tenants.

---

**6. templates/session_expired.html**
- Ensure it does **not expose any sensitive session data**.

---

**7. Logging**
- Ensure all security-sensitive events are logged:
  - Login, logout, 2FA enable/disable, password change, signup
  - Mask sensitive data (never log passwords, tokens, or 2FA codes)
  - Add short comments explaining why each log is needed

---

**Deliverable:**
- For each file, provide **full updated code** with inline comments explaining changes.
- Ensure the app is **ready for production security** for authentication and session management.
- Do not change any unrelated business logic or features.
- Ensure nothing is ambiguous; use exact variable names, functions, and file paths as per the current app.
