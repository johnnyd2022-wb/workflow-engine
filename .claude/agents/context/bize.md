# Biz-E — Business Facts

SaaS platform / operating system for manufacturers, especially **regulated** manufacturers.
Built because no existing tool let users define custom business processes — with inputs,
constraints, outputs, inventory movement, traceability, and compliance logic — configurable
by business users through the UI.

## Positioning

> A **source-to-sale workflow engine** for manufacturers: custom processes, inventory by
> stage, traceability, compliance checks, CRM basics, metrics, and accounting integrations.

Pain-led one-liners to draw from (see `brand-bize.md` for voice):

- "Replace spreadsheet chaos with custom operational workflows and audit-ready records."
- "Build the process your business actually uses, then track every input, output, and
  compliance step from source to sale."
- "The flexible operating system for small manufacturers."

Differentiator vs. ERPs: user-configurable processes without developers/consultants/
implementation projects. The important part is the **process graph** — steps, constraints,
inventory-stage logic, traceability, compliance outputs — not just metadata fields.

## Core concepts

Custom processes · process steps · inputs · constraints · outputs · inventory movement
between stages · traceability · compliance checks · audit readiness · source-to-sale ·
CRM basics · metrics · accounting integrations · API-first.

## Target market

- **Initial:** distilleries, wineries, breweries; then food (NP1–3), supplements,
  cosmetics, medical/regulated manufacturing.
- **Geography:** New Zealand first → Australia → broader English-speaking markets. Global
  inbound possible for the "Core" tier.
- **Market sizing (assumptions):** NZ SAM ~650 businesses for the initial regulated/
  alcohol-adjacent market; realistic adoption ~10–20%.

## Pricing (see `offers-pricing.md`)

- **Core:** ~NZD **$150 + GST/month**.
- **Compliant:** ~NZD **$199–200 + GST/month**; ~30% adoption assumption.
- MRR targets: 200 Core ≈ **$30k MRR**; later target **$50k MRR**.
- Time-investment thresholds discussed: $500 / $1,000 / $3,000 / $5,000 per week
  (increasing justification for time, contracting, or staffing).

## Value proposition

Pain: spreadsheet-based ops, painful audit prep (~20 hrs for some), manual traceability,
fragile compliance reporting, process living in people's heads, rigid/expensive/
consultant-heavy ERPs. Value: structured custom workflows, inventory-by-stage, enforced
constraints, one-click traceability, audit-ready reports, scale without losing control.

## Architecture / implementation

- Stack: **Flask, SQLAlchemy, Alembic, PostgreSQL**, static HTML/CSS/JS, **pytest**
  integration tests, **Docker** dev env.
- Execution engine: create/get execution; complete step; statuses **READY / PENDING /
  COMPLETED**; tests for 2/3/5/10-step workflows.
- Multi-tenant: middleware sets `g.user_id`, `g.email`, `g.role`, `g.org_id`, `g.name`,
  `g.status`; `/auth/me` returns `{user:null}` when logged out.
- 2FA/TOTP: enrol QR, enable (two tokens), verify, disable, cancel; lockout after 5
  failures for 1 minute.
- Static files: `safe_join`; rejects `..`, `/`, `\`; 400/404 handling.
- Docker dev: DB `8401 → 5432`; app `8001`.

## Accounting integrations

- **Xero** (in progress): OAuth2 routes `/xerologin`, `/xeroauth`, `/invoices`. Tenant
  picker needed for multi-org authorisations (single org can auto-connect). Tokens
  **encrypted in DB**, not in session cookies; session holds only non-sensitive tenant
  names/IDs. `xero_connection_id` column on `xero_tenants`, sourced from Xero `/connections`.
  Env vars override config: `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_REDIRECT_URI`.
- Future: QuickBooks Online (QBO), MYOB. Treat integrations as strategic features needing
  technical planning, release management, docs, marketing, sales messaging, onboarding.

## Go-to-market

- Channels: LinkedIn, Reddit, Discord, distiller communities, direct outreach, regulator
  conversations, founder network, global inbound for Core.
- Community reference: a distillers Discord (~340 members).
- Competitors / adjacent: **Distillx5, CraftedERP, Orchestrated**.
- Edge: user-configurable processes, compliance focus, small-business fit, low
  implementation overhead, flexible workflow engine (not rigid ERP), NZ/AU compliance
  awareness, and **real distillery experience via Whistlebird**.

See also: `brand-bize.md`, `audiences.md`, `offers-pricing.md`, `projects/bize/`.
