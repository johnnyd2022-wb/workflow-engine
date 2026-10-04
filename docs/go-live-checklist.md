# Go-live checklist

Track production readiness here. Add new items with stable `GL-` IDs and tick
them only after verification in production. Record the date and evidence when
completing an item.

## Checklist

- [ ] **GL-001 — Set up production Google OAuth.**

  Create a dedicated biz-e production Google Cloud project and Web application
  OAuth client. Configure the audience as **External**, publishing status as
  **In production**, and authorized domain as `biz-e.app`. Complete the branding
  and consent-screen information, including the real homepage, privacy policy,
  and terms links. Request only the sign-in scopes `openid email`.

  Register the exact redirect URI `https://biz-e.app/auth/google/callback`.
  Supply the production client ID and secret as protected, masked
  `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` deployment variables. Keep the
  credential values out of Git and images; use production credentials separately
  from dev/test credentials.

  Verify a production Google sign-in reaches the existing user's correct
  organisation, records a `login_google` audit, preserves the required 2FA flow,
  and refuses an unknown email without creating a user or organisation.

  Setup reference: [Google sign-in](google-sign-in.md).

  Completed: —. Evidence: —.
