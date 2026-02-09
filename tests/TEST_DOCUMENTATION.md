# 2FA and Login Flow Test Documentation

This document explains all the unit tests for the 2FA (Two-Factor Authentication) and login flow implementation, including backup codes.

## Test Files Overview

1. **`test_2fa_totp.py`** - Tests for 2FA enrollment, enablement, and disablement
2. **`test_login_2fa_flow.py`** - Comprehensive tests for login flow with 2FA and backup codes
3. **`test_multi_tenant_api.py`** - Tests for multi-tenant API endpoints (not 2FA-specific)

---

## Test File: `test_2fa_totp.py`

### Purpose
Tests the core 2FA functionality: enrollment, enablement, disablement, and basic authentication requirements.

### Test Cases

#### 1. `test_enroll_2fa_requires_authentication`
**What it tests:** Verifies that the `/auth/2fa/enroll` endpoint requires authentication.

**How it validates:**
- Makes an unauthenticated request to `/auth/2fa/enroll`
- Expects HTTP 401 (Unauthorized)

**Why it matters:** Ensures that only authenticated users can enroll in 2FA, preventing unauthorized access to 2FA secrets.

---

#### 2. `test_enable_2fa_requires_authentication`
**What it tests:** Verifies that the `/auth/2fa/enable` endpoint requires authentication.

**How it validates:**
- Makes an unauthenticated request to `/auth/2fa/enable`
- Expects HTTP 401 (Unauthorized)

**Why it matters:** Ensures that only authenticated users can enable 2FA on their account.

---

#### 3. `test_disable_2fa_requires_authentication`
**What it tests:** Verifies that the `/auth/2fa/disable` endpoint requires authentication.

**How it validates:**
- Makes an unauthenticated request to `/auth/2fa/disable`
- Expects HTTP 401 (Unauthorized)

**Why it matters:** Prevents unauthorized users from disabling 2FA on accounts.

---

#### 4. `test_enroll_2fa_generates_secret_and_uri`
**What it tests:** Verifies that enrolling in 2FA generates a valid TOTP secret and provisioning URI.

**How it validates:**
- Signs up a new user
- Calls `/auth/2fa/enroll`
- Verifies response contains:
  - `secret` field (non-empty)
  - `provisioning_uri` field (non-empty)
  - URI starts with `otpauth://`

**Why it matters:** Ensures users receive valid TOTP secrets that can be used with authenticator apps.

---

#### 5. `test_enable_2fa_with_valid_tokens`
**What it tests:** Verifies that enabling 2FA with two valid TOTP tokens succeeds and returns backup codes.

**How it validates:**
- Signs up a user
- Enrolls in 2FA
- Generates two different TOTP tokens (waits between generations to ensure they're different)
- Calls `/auth/2fa/enable` with `token1` and `token2`
- Verifies:
  - HTTP 200 response
  - `enabled: true` in response
  - `backup_codes` array with 10 codes
  - 2FA is enabled in `/auth/me` response

**Why it matters:** 
- Validates the two-token requirement (ensures user can generate codes correctly)
- Confirms backup codes are generated and returned
- Ensures 2FA state is properly persisted

---

#### 6. `test_enable_2fa_with_invalid_token`
**What it tests:** Verifies that enabling 2FA with invalid tokens fails appropriately.

**How it validates:**
- Signs up a user and enrolls in 2FA
- Generates one valid token
- Tests two scenarios:
  1. Invalid `token1` with valid `token2` → expects "Invalid first token"
  2. Valid `token1` with invalid `token2` → expects "Invalid second token"
- Both should return HTTP 400

**Why it matters:** Ensures invalid tokens are rejected and appropriate error messages are returned.

---

#### 7. `test_disable_2fa`
**What it tests:** Verifies that disabling 2FA works correctly.

**How it validates:**
- Signs up a user
- Enrolls and enables 2FA
- Verifies 2FA is enabled via `/auth/me`
- Calls `/auth/2fa/disable`
- Verifies:
  - HTTP 200 response
  - `disabled: true` in response
  - 2FA is disabled in `/auth/me` response

**Why it matters:** Ensures users can disable 2FA when needed, and the state is properly updated.

---

#### 8. `test_login_without_2fa_enabled`
**What it tests:** Verifies that login works normally when 2FA is not enabled.

**How it validates:**
- Signs up a user (2FA not enabled)
- Logs out
- Logs in with email/password
- Verifies:
  - HTTP 200 response
  - `requires_2fa` not in response
  - Login successful message
  - User is authenticated (can access `/auth/me`)

**Why it matters:** Ensures the normal login flow works for users without 2FA.

---

#### 9. `test_login_with_2fa_enabled_requires_token`
**What it tests:** Verifies that login requires 2FA verification when 2FA is enabled.

**How it validates:**
- Signs up a user
- Enrolls and enables 2FA
- Logs out
- Attempts login with email/password
- Verifies:
  - HTTP 200 response
  - `requires_2fa: true` in response
  - User is NOT authenticated yet (cannot access protected endpoints)

**Why it matters:** Ensures 2FA is properly enforced during login.

---

#### 10. `test_verify_2fa_with_valid_token_completes_login`
**What it tests:** Verifies that verifying 2FA with a valid TOTP token completes the login process.

**How it validates:**
- Signs up a user
- Enrolls and enables 2FA
- Logs out
- Logs in (gets `requires_2fa: true`)
- Verifies 2FA with valid TOTP token
- Verifies:
  - HTTP 200 response
  - "Login successful" message
  - User is authenticated (can access `/auth/me`)

**Why it matters:** Ensures the complete 2FA login flow works end-to-end.

---

#### 11. `test_verify_2fa_with_invalid_token_fails`
**What it tests:** Verifies that verifying 2FA with an invalid token fails.

**How it validates:**
- Signs up a user
- Enrolls and enables 2FA
- Logs out
- Logs in (gets `requires_2fa: true`)
- Attempts to verify with invalid token "000000"
- Verifies:
  - HTTP 401 response
  - Error message about invalid token
  - User is NOT authenticated

**Why it matters:** Ensures invalid tokens are rejected and users cannot bypass 2FA.

---

#### 12. `test_verify_2fa_without_pending_session_fails`
**What it tests:** Verifies that verifying 2FA without a pending session fails.

**How it validates:**
- Makes a direct request to `/auth/verify-2fa` without logging in first
- Expects HTTP 401 with "No pending 2FA session" error

**Why it matters:** Prevents direct access to the verify endpoint without going through the login flow.

---

#### 13. `test_verify_2fa_missing_token_fails`
**What it tests:** Verifies that the verify-2fa endpoint requires a token.

**How it validates:**
- Signs up a user
- Enrolls and enables 2FA
- Logs out
- Logs in (creates pending session)
- Attempts to verify without providing a token
- Expects HTTP 400 with "token is required" error

**Why it matters:** Ensures proper input validation on the verify endpoint.

---

#### 14. `test_auth_me_returns_2fa_status`
**What it tests:** Verifies that `/auth/me` correctly returns the 2FA status.

**How it validates:**
- Signs up a user
- Checks initial 2FA status (should be `false`)
- Enables 2FA
- Checks status again (should be `true`)
- Disables 2FA
- Checks status again (should be `false`)

**Why it matters:** Ensures the frontend can accurately display 2FA status to users.

---

#### 15. `test_enable_2fa_missing_token_fails`
**What it tests:** Verifies that enabling 2FA requires both tokens.

**How it validates:**
- Signs up a user
- Enrolls in 2FA
- Attempts to enable without tokens → expects "First token is required"
- Attempts to enable with only `token1` → expects "Second token is required"

**Why it matters:** Ensures proper input validation and enforces the two-token requirement.

---

## Test File: `test_login_2fa_flow.py`

### Purpose
Comprehensive tests for the complete login flow with 2FA, including backup codes, format validation, and edge cases.

### Test Cases

#### 1. `test_login_without_2fa_succeeds`
**What it tests:** Verifies normal login flow when 2FA is not enabled.

**How it validates:**
- Signs up a user (no 2FA)
- Logs out
- Logs in with email/password
- Verifies successful login and authentication

**Why it matters:** Ensures backward compatibility for users without 2FA.

---

#### 2. `test_login_with_2fa_requires_verification`
**What it tests:** Verifies that login requires 2FA verification when 2FA is enabled.

**How it validates:**
- Signs up a user
- Enables 2FA
- Logs out
- Attempts login
- Verifies `requires_2fa: true` and user is not authenticated yet

**Why it matters:** Ensures 2FA is properly enforced.

---

#### 3. `test_verify_2fa_with_totp_completes_login`
**What it tests:** Verifies that login completes successfully with a valid TOTP token.

**How it validates:**
- Signs up a user
- Enables 2FA
- Logs out
- Logs in (gets `requires_2fa: true`)
- Verifies with valid TOTP token
- Verifies successful login and authentication

**Why it matters:** Validates the primary 2FA authentication method.

---

#### 4. `test_verify_2fa_with_backup_code_completes_login`
**What it tests:** Verifies that login completes successfully with a valid backup code.

**How it validates:**
- Signs up a user
- Enables 2FA (receives backup codes)
- Logs out
- Logs in (gets `requires_2fa: true`)
- Verifies with a backup code
- Verifies successful login and authentication

**Why it matters:** Ensures backup codes work as a recovery mechanism when TOTP device is unavailable.

---

#### 5. `test_verify_2fa_with_invalid_totp_fails`
**What it tests:** Verifies that invalid TOTP tokens are rejected.

**How it validates:**
- Signs up a user
- Enables 2FA
- Logs out
- Logs in
- Attempts to verify with invalid token "000000"
- Verifies failure and user remains unauthenticated

**Why it matters:** Prevents brute force attacks and ensures security.

---

#### 6. `test_verify_2fa_with_invalid_backup_code_fails`
**What it tests:** Verifies that invalid backup codes are rejected.

**How it validates:**
- Signs up a user
- Enables 2FA
- Logs out
- Logs in
- Attempts to verify with invalid backup code "INVALID1"
- Verifies failure and user remains unauthenticated

**Why it matters:** Ensures backup codes cannot be guessed or brute-forced.

---

#### 7. `test_verify_2fa_without_pending_session_fails`
**What it tests:** Verifies that verify-2fa requires a pending session from login.

**How it validates:**
- Makes direct request to `/auth/verify-2fa` without logging in
- Expects HTTP 401 with "No pending 2FA session" error

**Why it matters:** Prevents direct access to verify endpoint without proper authentication flow.

---

#### 8. `test_verify_2fa_missing_token_fails`
**What it tests:** Verifies that verify-2fa requires a token parameter.

**How it validates:**
- Signs up a user
- Enables 2FA
- Logs out
- Logs in (creates pending session)
- Attempts to verify without token
- Expects HTTP 400 with "token is required" error

**Why it matters:** Ensures proper input validation.

---

#### 9. `test_backup_code_is_one_time_use`
**What it tests:** Verifies that backup codes can only be used once.

**How it validates:**
- Signs up a user
- Enables 2FA (receives backup codes)
- Logs out
- Logs in and uses a backup code → succeeds
- Logs out
- Logs in again and attempts to use the same backup code → fails

**Why it matters:** 
- Critical security feature: backup codes are one-time use only
- Prevents code reuse attacks
- Ensures codes are properly marked as consumed

---

#### 10. `test_backup_code_format_validation`
**What it tests:** Verifies that backup code format is validated server-side.

**How it validates:**
- Signs up a user
- Enables 2FA
- Logs out
- Logs in
- Attempts to verify with:
  - Too short code (6 chars) → expects format error
  - Too long code (9 chars) → expects format error
  - Non-alphanumeric code → expects format error

**Why it matters:**
- Server-side validation prevents invalid input from reaching the database
- Ensures consistent format (8 alphanumeric characters)
- Provides clear error messages to users

---

#### 11. `test_totp_code_format_validation`
**What it tests:** Verifies that TOTP code format is validated server-side.

**How it validates:**
- Signs up a user
- Enables 2FA
- Logs out
- Logs in
- Attempts to verify with:
  - Non-numeric code → expects format error
  - Wrong length (5 digits) → expects format error

**Why it matters:**
- Ensures TOTP codes are exactly 6 digits
- Prevents invalid input from being processed
- Provides clear error messages

---

#### 12. `test_verify_2fa_expired_session_fails`
**What it tests:** Verifies that expired pending 2FA sessions are rejected.

**How it validates:**
- Signs up a user
- Enables 2FA
- Logs out
- Logs in (creates pending session)
- Note: Actual expiration testing requires waiting 5+ minutes, which is impractical in unit tests
- This test validates the endpoint exists and handles missing/expired sessions

**Why it matters:** 
- Prevents stale sessions from being used
- Enforces time-limited 2FA verification windows
- Note: Full expiration testing should be done in integration tests

---

#### 13. `test_disable_2fa_allows_normal_login`
**What it tests:** Verifies that disabling 2FA allows normal login without 2FA verification.

**How it validates:**
- Signs up a user
- Enables 2FA
- Disables 2FA
- Logs out
- Logs in with email/password only
- Verifies successful login without 2FA requirement

**Why it matters:** Ensures users can revert to password-only authentication if needed.

---

#### 14. `test_enable_2fa_returns_backup_codes`
**What it tests:** Verifies that enabling 2FA returns 10 backup codes with correct format.

**How it validates:**
- Signs up a user
- Enrolls in 2FA
- Enables 2FA with two valid tokens
- Verifies response contains:
  - `enabled: true`
  - `backup_codes` array with exactly 10 codes
  - Each code is exactly 8 characters
  - Each code is alphanumeric

**Why it matters:**
- Ensures backup codes are generated correctly
- Validates code format (8 alphanumeric characters)
- Confirms codes are returned to the user (one-time display)

---

#### 15. `test_enable_2fa_requires_two_different_tokens`
**What it tests:** Verifies that enabling 2FA requires two different tokens.

**How it validates:**
- Signs up a user
- Enrolls in 2FA
- Generates one TOTP token
- Attempts to enable with the same token for both `token1` and `token2`
- Expects HTTP 400 with "Second token must be different from the first" error

**Why it matters:**
- Ensures users can generate multiple codes (validates authenticator app is working)
- Prevents clock synchronization issues
- Confirms user understands how to use TOTP

---

## Test Cleanup

Both test files include cleanup mechanisms:

1. **Automatic cleanup in fixtures:** Each test uses a `setup_session` fixture that cleans up test data after each test
2. **Cleanup script:** `cleanup_test_data.py` can be run manually to remove test data
3. **Isolated test data:** Each test uses unique email addresses and org names to avoid conflicts

---

## Running the Tests

### Run all 2FA tests:
```bash
pytest test_2fa_totp.py test_login_2fa_flow.py -v
```

### Run specific test file:
```bash
pytest test_2fa_totp.py -v
pytest test_login_2fa_flow.py -v
```

### Run specific test:
```bash
pytest test_login_2fa_flow.py::TestLogin2FAFlow::test_backup_code_is_one_time_use -v
```

### Run with coverage:
```bash
pytest test_2fa_totp.py test_login_2fa_flow.py --cov=app --cov-report=html
```

---

## Test Coverage Summary

### Authentication & Authorization
- ✅ Unauthenticated access is blocked
- ✅ Authenticated users can enroll/enable/disable 2FA
- ✅ Login flow respects 2FA status

### 2FA Enrollment & Enablement
- ✅ Secret and provisioning URI generation
- ✅ Two-token requirement for enablement
- ✅ Backup code generation (10 codes, 8 characters each)
- ✅ Invalid token rejection

### Login Flow
- ✅ Normal login (no 2FA)
- ✅ 2FA-required login flow
- ✅ TOTP token verification
- ✅ Backup code verification
- ✅ Invalid code rejection

### Backup Codes
- ✅ One-time use enforcement
- ✅ Format validation (8 alphanumeric)
- ✅ Consumption tracking

### Security
- ✅ Format validation (TOTP: 6 digits, Backup: 8 alphanumeric)
- ✅ Pending session requirement
- ✅ Expired session handling
- ✅ Invalid input rejection

---

## Notes

1. **Time-dependent tests:** Some tests involve waiting for TOTP token generation. The tests use `time.sleep()` to ensure different tokens, but in rare cases tokens may still be the same (within the same 30-second window). The tests handle this by waiting for the next window if needed.

2. **Cleanup:** Test cleanup is automatic but may leave some data if tests fail. Use `cleanup_test_data.py` to manually clean up if needed.

3. **Server requirement:** Tests require the application server to be running on `https://localhost:8005`. Start the server before running tests.

4. **SSL certificates:** Tests disable SSL verification for local development. Do not use this in production.

5. **Rate limiting:** Some endpoints are rate-limited. If tests fail with rate limit errors, wait a few minutes and retry.

---

## Future Test Enhancements

Potential additions:
- Integration tests for session expiration (requires waiting 5+ minutes)
- Tests for trusted device functionality
- Tests for concurrent enrollment attempts
- Tests for network failure scenarios
- Performance tests for backup code generation/verification
- Tests for edge cases (empty codes, special characters, etc.)

---

## Execution Tests (test_executions.py)

**Purpose:** Gate for deployments. Ensures the execution lifecycle (create execution, get execution with steps, complete step with `actual_inputs`/`actual_outputs`) does not regress. Locks in the contract used by the flows2 execution modal (quantity/unit/inventory_item_id shape).

**Scope:** `ExecutionRepository`, execution/execution_step models. Uses real DB and fixtures (same pattern as `test_corechecks`, `test_dag_traversal`).

### Test Classes

| Class | What it tests |
|-------|----------------|
| **TestCreateExecution** | Create execution creates steps; first step READY, rest PENDING; invalid process_id raises. |
| **TestGetExecution** | Get execution returns steps with `actual_inputs`/`actual_outputs`; wrong org or nonexistent id returns None. |
| **TestCompleteStepContract** | Complete step persists `actual_inputs`, `actual_outputs`, `execution_data`; get returns them; accepts empty lists. |
| **TestCompleteStepOrder** | Cannot complete step 2 before step 1; completing step 1 marks step 2 READY; completing all marks execution COMPLETED. |
| **TestCompleteStepNegative** | Complete with wrong org returns None; nonexistent step id returns None; completing already-completed step raises. |
| **TestExecutionFlowE2E** | Full flow: create → complete step 1 (modal-shaped payload) → get → complete step 2 → get; asserts persisted quantities and execution status. |

### Running execution tests

```bash
pytest tests/test_executions.py -v
```

To run as part of the full test suite (e.g. in CI):

```bash
uv run pytest tests/ -v
```

