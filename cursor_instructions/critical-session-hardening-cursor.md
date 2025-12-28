# Cursor: Apply critical and high-priority security improvements in the Flask application.
# Implement the following items only:

1. HTTPS Enforcement
   - File: app_factory.py
   - Add a before_request middleware to redirect all non-HTTPS traffic to HTTPS in production.
   - Add HSTS headers: Strict-Transport-Security: max-age=31536000; includeSubDomains

2. Security Headers
   - File: app_factory.py
   - Add after_request middleware to set:
     X-Content-Type-Options: nosniff
     X-Frame-Options: DENY
     X-XSS-Protection: 1; mode=block
     Content-Security-Policy: default-src 'self'

3. CSRF Protection
   - File: app_factory.py
   - Use Flask-WTF CSRFProtect
   - Initialize CSRF with the app

4. Account Lockout
   - File: app/api/routes/auth_routes.py
   - Lock user account for 1 minutes after 5 failed login attempts
   - Allow login via password reset during lockout - note passowrd reset flow has not yet been created so just add the code required to allow login on password reset 
   - Log IP address and User-Agent on all login attempts
   - Include inline comments explaining the logic

5. Password Policy Warning
   - File: app/api/routes/auth_routes.py
   - When setting/changing passwords, warn in the UI using styled tooltip or nice looking warning if:
     - Password < 8 characters
     - Missing uppercase, lowercase, number, or special character
   - Do not block users from proceeding

6. Audit Logging Enhancements
   - File: app/api/routes/auth_routes.py
   - Log IP addresses and User-Agent strings and user id for security events:
     - Login success/failure
     - Password change
     - 2FA enable/disable
     - Account lockouts

7. Database Connection Security
   - File: app/utils/config_loader.py
   - Ensure database connection strings include SSL/TLS parameters

# Notes:
- Add inline comments explaining each change to maintain clarity.
- Medium-priority items (rate limiting storage, input validation, XSS prevention, dependency scanning, etc.) are deferred for future passes.
- Avoid removing any existing functionality.
- Do not alter secret key management as AWS Secrets Manager will be used in production.
