# Sign-in for assistants (public MCP 8.2b): trying it with curl

The app is an OAuth 2.1 authorization server for AI assistants. There is no MCP server yet (that is
8.2c), but the whole sign-in and the read-only tokens can be exercised by hand. Spec:
`.agents/specs/public-mcp.md`.

Local values come from the `[mcp]` section of `app/config/local.ini`
(`issuer = http://localhost:8005`, `resource = http://localhost:8030/mcp`). Use the HTTPS dev URL
(`https://dev.biz-e.app`) if that is how you reach the app; the app redirects plain HTTP.

## 1. Turn assistants on for an organisation

Off by default. Until the Settings page exists (8.2e):

```bash
uv run workflow mcp enable --org-id <org uuid> --roles admin,member   # roles that may connect
uv run workflow mcp disable --org-id <org uuid>                        # off again, roles kept
```

## 2. Register a client (RFC 7591)

```bash
curl -s -X POST "$ISSUER/oauth/register" -H 'Content-Type: application/json' \
  -d '{"client_name":"My test client","redirect_uris":["http://localhost:8123/callback"]}'
# {"client_id":"…", …}
```

People in allowed roles can approve any registered client when their organisation has AI assistant
access enabled. The consent page shows the callback host in ASCII and labels clients outside the reviewed
list **Unverified app**. An HTTPS `client_id` identifies a client ID metadata document, which Biz-E
fetches and caches for 24 hours.

## 3. Sign in and approve

Make a PKCE pair, then open the authorize URL in a browser:

```bash
VERIFIER=$(openssl rand -base64 48 | tr -d '=+/\n' | cut -c1-64)
CHALLENGE=$(printf %s "$VERIFIER" | openssl dgst -sha256 -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')
echo "$ISSUER/oauth/authorize?response_type=code&client_id=$CLIENT_ID&redirect_uri=http%3A%2F%2Flocalhost%3A8123%2Fcallback&state=xyz&code_challenge=$CHALLENGE&code_challenge_method=S256&scope=bize.read&resource=$RESOURCE"
```

Signed out, you land on the normal sign-in page (password + 2FA) and come back to the consent page.
Approve, and the browser is sent to `http://localhost:8123/callback?code=bzc_…&state=xyz` (nothing
needs to be listening; copy the `code` from the address bar). The code lives 60 seconds and works once.

## 4. Exchange the code

```bash
curl -s -X POST "$ISSUER/oauth/token" \
  -d grant_type=authorization_code -d "code=$CODE" -d "code_verifier=$VERIFIER" \
  -d "client_id=$CLIENT_ID" -d "redirect_uri=http://localhost:8123/callback" -d "resource=$RESOURCE"
# {"access_token":"bza_…","token_type":"Bearer","expires_in":3600,"refresh_token":"bzr_…","scope":"bize.read"}
```

## 5. Use the token

```bash
curl -s "$ISSUER/api/core/inventory" -H "Authorization: Bearer $ACCESS"      # 200: what that person can read
curl -s -X POST "$ISSUER/api/core/inventory" -H "Authorization: Bearer $ACCESS" -d '{}'   # 403 insufficient_scope
curl -s "$ISSUER/api/core/mcp/me" -H "Authorization: Bearer $ACCESS"          # who the token is, what it may read
```

Refresh with `grant_type=refresh_token` (the old refresh token stops working; presenting it again ends
the whole connection). Revoke with `POST /oauth/revoke` (`token=…`), or from
`POST /api/core/mcp/grants/<id>/revoke` as the person (or an admin).

## What a token can and cannot do

* Only `GET`/`HEAD`, and only on routes whose policy rule names `production.view`, `inventory.view`,
  `sales.view`, `compliance.view` or `costs.view`, and only if the person's own role holds it.
* Never people, settings, exports or any write, whatever the role.
* Checked on every request: the org's switch, the person's role, that they are active, that their access
  has not ended and that they have not changed their password since approving. Flip any of them and the
  next call is refused (`403 mcp_not_allowed` or `401 invalid_token`); a grant is only ended by a password
  change, a revoke, or reuse of a used code or refresh token.
* 120 requests a minute per connection.
