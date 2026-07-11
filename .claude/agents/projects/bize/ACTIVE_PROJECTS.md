# Biz-E — Active Projects

Source of truth for Biz-E *change* work (features, releases, GTM projects). Live features &
customer operational workflows live in the Biz-E product itself. Maintained via **Project
Manager**; **Biz-E Product Manager** owns roadmap/PRDs, **CTO** the designs, **Release
Manager** the shipping.

> **⏸ On hold — Q3 2026.** Biz-E is paused while the Whistlebird liquor licence takes the
> evenings. First goal on resume: **1–2 pilot customers**. Statuses below are frozen —
> confirm on resume.

| Project | Status | Owner | Target | Next milestone | Next action |
|---|---|---|---|---|---|
| **Xero integration** (OAuth, invoices, multi-org tenant selection) | paused (was in progress) | Johnny | TBD | Tenant selection + encrypted token storage | On resume: confirm remaining scope; plan release |
| Compliance reporting feature | idea/roadmap | Johnny | TBD | — | Define MVP scope |
| Onboarding flow | idea/roadmap | Johnny | TBD | — | Define first-run experience |
| Landing page / positioning | idea/roadmap | Johnny | TBD | — | Draft hero + pain-led copy (Marketing) |
| Customer pilot | idea | Johnny | TBD | — | Identify 1–2 distilleries for a pilot |

## Xero — known technical notes (from `context/bize.md`)
- Routes `/xerologin`, `/xeroauth`, `/invoices`; single org auto-connects, multi-org needs
  tenant picker. Tokens **encrypted in DB**, not session cookies; session holds only
  non-sensitive tenant names/IDs. `xero_connection_id` on `xero_tenants` from `/connections`.
  Env overrides config: `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_REDIRECT_URI`.

## How to add a project
Use `skills/project-manager/templates/project-brief.md`. For Biz-E builds, link the GitLab
issues/MRs (use `glab`).
