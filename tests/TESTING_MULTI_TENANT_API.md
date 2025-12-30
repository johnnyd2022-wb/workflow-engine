# Testing Multi-Tenant API Endpoints

This guide shows you how to test the new multi-tenant authentication and organisation management endpoints.

## Prerequisites

1. **Start the application:**
   ```bash
   uv run workflow serve
   # Or
   python app/main.py
   ```

2. **Create your first organisation** (if you haven't already):
   ```bash
   uv run workflow create-org --name "Test Company" --email "admin@test.com" --password "SecurePass123!"
   ```

## Testing with cURL

### 1. Sign Up (Create Organisation + Admin User)

```bash
curl -X POST http://localhost:8005/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "org_name": "Acme Corp",
    "email": "admin@acme.com",
    "password": "SecurePassword123!"
  }'
```

**Expected Response (201):**
```json
{
  "message": "Organisation and admin user created successfully",
  "organisation": {
    "id": "uuid-here",
    "name": "Acme Corp",
    "status": "active"
  },
  "user": {
    "id": "uuid-here",
    "email": "admin@acme.com",
    "role": "admin"
  }
}
```

**Note:** This also sets a session cookie, so you're automatically logged in.

---

### 2. Login

```bash
curl -X POST http://localhost:8005/auth/login \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{
    "email": "admin@acme.com",
    "password": "SecurePassword123!"
  }'
```

**Expected Response (200):**
```json
{
  "message": "Login successful",
  "user": {
    "id": "uuid-here",
    "email": "admin@acme.com",
    "role": "admin",
    "org_id": "uuid-here"
  }
}
```

**Note:** Use `-c cookies.txt` to save session cookies, then use `-b cookies.txt` in subsequent requests.

---

### 3. Get Current User Info

```bash
curl -X GET http://localhost:8005/auth/me \
  -b cookies.txt \
  -H "Content-Type: application/json"
```

**Expected Response (200):**
```json
{
  "user": {
    "id": "uuid-here",
    "email": "admin@acme.com",
    "role": "admin",
    "org_id": "uuid-here",
    "is_active": true
  },
  "organisation": {
    "id": "uuid-here",
    "name": "Acme Corp",
    "status": "active"
  }
}
```

---

### 4. Get Current Organisation

```bash
curl -X GET http://localhost:8005/org \
  -b cookies.txt \
  -H "Content-Type: application/json"
```

**Expected Response (200):**
```json
{
  "organisation": {
    "id": "uuid-here",
    "name": "Acme Corp",
    "status": "active",
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00"
  }
}
```

---

### 5. Update Organisation (Admin Only)

```bash
curl -X PATCH http://localhost:8005/org \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corporation Updated"
  }'
```

**Expected Response (200):**
```json
{
  "message": "Organisation updated successfully",
  "organisation": {
    "id": "uuid-here",
    "name": "Acme Corporation Updated",
    "status": "active"
  }
}
```

---

### 6. List Users in Organisation

```bash
curl -X GET http://localhost:8005/org/users \
  -b cookies.txt \
  -H "Content-Type: application/json"
```

**Expected Response (200):**
```json
{
  "users": [
    {
      "id": "uuid-here",
      "email": "admin@acme.com",
      "role": "admin",
      "is_active": true,
      "created_at": "2024-01-01T00:00:00"
    }
  ]
}
```

---

### 7. Create New User (Admin Only)

```bash
curl -X POST http://localhost:8005/org/users \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{
    "email": "member@acme.com",
    "password": "MemberPass123!",
    "role": "member"
  }'
```

**Expected Response (201):**
```json
{
  "message": "User created successfully",
  "user": {
    "id": "uuid-here",
    "email": "member@acme.com",
    "role": "member",
    "is_active": true
  }
}
```

---

### 8. Delete User (Admin Only, Soft Delete)

```bash
curl -X DELETE http://localhost:8005/org/users/{user_id} \
  -b cookies.txt \
  -H "Content-Type: application/json"
```

**Expected Response (200):**
```json
{
  "message": "User deleted successfully"
}
```

---

### 9. Logout

```bash
curl -X POST http://localhost:8005/auth/logout \
  -b cookies.txt \
  -H "Content-Type: application/json"
```

**Expected Response (200):**
```json
{
  "message": "Logout successful"
}
```

---

## Testing with Python (requests library)

Create a file `test_api.py`:

```python
import requests

BASE_URL = "http://localhost:8005"
session = requests.Session()

# 1. Sign Up
response = session.post(
    f"{BASE_URL}/auth/signup",
    json={
        "org_name": "Test Company",
        "email": "admin@test.com",
        "password": "SecurePass123!"
    }
)
print("Signup:", response.json())
print(f"Status: {response.status_code}\n")

# 2. Get Current User
response = session.get(f"{BASE_URL}/auth/me")
print("Current User:", response.json())
print(f"Status: {response.status_code}\n")

# 3. Get Organisation
response = session.get(f"{BASE_URL}/org")
print("Organisation:", response.json())
print(f"Status: {response.status_code}\n")

# 4. Create User
response = session.post(
    f"{BASE_URL}/org/users",
    json={
        "email": "member@test.com",
        "password": "MemberPass123!",
        "role": "member"
    }
)
print("Create User:", response.json())
print(f"Status: {response.status_code}\n")

# 5. List Users
response = session.get(f"{BASE_URL}/org/users")
print("List Users:", response.json())
print(f"Status: {response.status_code}\n")

# 6. Logout
response = session.post(f"{BASE_URL}/auth/logout")
print("Logout:", response.json())
print(f"Status: {response.status_code}\n")
```

Run it:
```bash
python test_api.py
```

---

## Testing Multi-Tenant Isolation

To verify that tenants are properly isolated, test with two different organisations:

### Setup Two Organisations

```bash
# Create Org 1
curl -X POST http://localhost:8005/auth/signup \
  -H "Content-Type: application/json" \
  -c org1_cookies.txt \
  -d '{"org_name": "Company A", "email": "admin@companya.com", "password": "Pass123!"}'

# Create Org 2
curl -X POST http://localhost:8005/auth/signup \
  -H "Content-Type: application/json" \
  -c org2_cookies.txt \
  -d '{"org_name": "Company B", "email": "admin@companyb.com", "password": "Pass123!"}'
```

### Test Isolation

```bash
# As Org 1 admin, list users (should only see Org 1 users)
curl -X GET http://localhost:8005/org/users -b org1_cookies.txt

# As Org 2 admin, list users (should only see Org 2 users)
curl -X GET http://localhost:8005/org/users -b org2_cookies.txt
```

Each organisation should only see their own users, proving tenancy is enforced.

---

## Error Testing

### Test Invalid Login
```bash
curl -X POST http://localhost:8005/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "wrong@email.com", "password": "wrongpass"}'
```
**Expected:** 401 Unauthorized

### Test Unauthorized Access (No Session)
```bash
curl -X GET http://localhost:8005/org/users
```
**Expected:** 401 Unauthorized (or 403 if tenant context fails)

### Test Member Trying Admin Action
```bash
# Login as member
curl -X POST http://localhost:8005/auth/login \
  -H "Content-Type: application/json" \
  -c member_cookies.txt \
  -d '{"email": "member@acme.com", "password": "MemberPass123!"}'

# Try to create user (should fail - members can't create users)
curl -X POST http://localhost:8005/org/users \
  -b member_cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"email": "new@acme.com", "password": "Pass123!", "role": "member"}'
```
**Expected:** 403 Forbidden

---

## Using Postman or Insomnia

1. **Create a new collection** for "Multi-Tenant API"

2. **Set base URL:** `http://localhost:8005`

3. **For authenticated requests:**
   - Use the "Cookies" tab to manage session cookies
   - Or use the "Headers" tab and add: `Cookie: session=your-session-cookie`

4. **Create requests for each endpoint:**
   - POST `/auth/signup`
   - POST `/auth/login`
   - GET `/auth/me`
   - GET `/org`
   - PATCH `/org`
   - GET `/org/users`
   - POST `/org/users`
   - DELETE `/org/users/{user_id}`
   - POST `/auth/logout`

---

## Quick Test Script

Save this as `quick_test.sh`:

```bash
#!/bin/bash

BASE_URL="http://localhost:8005"

echo "=== Testing Multi-Tenant API ==="
echo ""

echo "1. Sign Up..."
SIGNUP_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/signup" \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{"org_name": "Test Org", "email": "admin@test.com", "password": "Test123!"}')
echo "$SIGNUP_RESPONSE" | python -m json.tool
echo ""

echo "2. Get Current User..."
curl -s -X GET "$BASE_URL/auth/me" -b cookies.txt | python -m json.tool
echo ""

echo "3. Get Organisation..."
curl -s -X GET "$BASE_URL/org" -b cookies.txt | python -m json.tool
echo ""

echo "4. List Users..."
curl -s -X GET "$BASE_URL/org/users" -b cookies.txt | python -m json.tool
echo ""

echo "5. Create User..."
curl -s -X POST "$BASE_URL/org/users" \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"email": "user@test.com", "password": "User123!", "role": "member"}' | python -m json.tool
echo ""

echo "=== Test Complete ==="
```

Make it executable and run:
```bash
chmod +x quick_test.sh
./quick_test.sh
```

---

## Troubleshooting

### "Authentication required" errors
- Make sure you're sending session cookies with `-b cookies.txt` (cURL) or using a session (Python requests)
- Check that you logged in successfully first

### "Invalid organisation" errors
- This means the org_id in your session doesn't exist in the database
- Try logging in again to refresh your session

### Port not available
- Check the app is running: `uv run workflow serve`
- Check the port in your config: `app/config/local.ini` (default: 8005)

### Database connection errors
- Make sure PostgreSQL is running
- Check database credentials in `app/config/local.ini`

