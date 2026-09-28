# Google sign-in

Google signs in to existing accounts. It never creates a user or organisation. The
identity table binds `google` plus immutable `sub` to a tenant/user composite foreign
key. A later Google email change does not change the local account.

An initial automatic link requires an active account with an exact normalized email
match and Google authority: `gmail.com`, or an ID token `hd` matching the email domain.
Third party Google addresses must first sign in with their local password and use
Settings → Sign-in methods → Link Google. Linking confirms that password and binds the
callback to the same session account, tenant and password version. A different Google
subject cannot replace a link; a subject cannot belong to two local accounts.

An invite can be accepted with Google only with the unexpired one-time invite token,
the invited authoritative verified address, and the same local account if the subject
is already bound. The account already exists. Google-only invite accounts can add a
password within ten minutes of a fresh Google sign-in; unlink requires a known valid
password. Other email domains accept the password invite first, then link explicitly.

## Environment setup

Sign-in remains disabled until credentials are provisioned. Set `[google_sign_in]
enabled = true` in the environment config. Never put credentials in tracked ini files.
Use a separate Google Cloud OAuth **web application** client for each environment,
with scopes `openid email` and its exact redirect URI:

| Environment | Default redirect URI |
| --- | --- |
| local | `https://dev.biz-e.app/auth/google/callback` |
| test | `https://test.biz-e.app/auth/google/callback` |
| production (`prod`) | `https://biz-e.app/auth/google/callback` |

Override the URI with `GOOGLE_REDIRECT_URI` for another HTTPS deployment hostname;
it must end in `/auth/google/callback`, with no query, fragment or embedded credentials.
Register that same URI in Google Cloud. Provision local KeePassXC entries
`workflow-engine/google/client_id` and `workflow-engine/google/client_secret`, each
with the credential in its Password field. Entry paths are configurable under
`[google_sign_in]`. CI/deployment uses protected masked `GOOGLE_CLIENT_ID` and
`GOOGLE_CLIENT_SECRET` variables. Enabled configurations fail startup if incomplete.
No Google secrets are required for the automated test suite.

Authorization uses a server redirect, S256 PKCE, random state and nonce, and a
ten-minute flow. Authlib validates the code exchange and ID token signature using
Google discovery/JWKS, and checks issuer, audience, expiry and nonce. Additional
strict claims checks reject false/missing `email_verified`, wrong `azp` and nonce
shortcuts. Neither access nor refresh tokens are retained. All mutating Google routes
remain under Flask-WTF CSRF protection; callback is GET and verifies state. Secure,
HttpOnly, SameSite=Lax cookies permit Google's top-level callback; no external script
or connect source needs adding to CSP. Google responses use `no-store` and
`no-referrer` headers.

Enrolled users still complete existing TOTP or backup-code verification. Administrators
without TOTP still enter the existing mandatory enrolment flow. Lockouts, account
activation, organisation suspension and Auditor expiry are checked before sign-in,
and again after the pending Google/TOTP step. Audit actions include `login_google`,
`google_identity_linked`, `google_identity_unlinked`, and `accept_invite_google`.

The org-domain second-factor trust policy is a separate pending founder decision;
this implementation does not bypass TOTP based on Google claims.

## Verification and rollout

Tests mock only the provider-verification boundary for route scenarios. They also
exercise Authlib's signature/claims checks with locally signed tokens and mocked
Google JWKS and code exchange. Provision real credentials and verify the configured
redirect and Johnny's existing account before enabling production sign-in.

Primary references checked 28 September 2026:

- [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect)
- [Google account authority](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token)
- [Authlib Flask client](https://docs.authlib.org/en/latest/client/flask.html)
