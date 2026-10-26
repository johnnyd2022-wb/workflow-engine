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

## From the go-live assessment (!570)

The findings from `docs/nz-alcohol-go-live-assessment-2026-10-25.md`, as one list to work through. Each item is marked:

- **Fix**: a defect or clear requirement with one right answer. Fixed in code, no input needed.
- **Decide**: a design or product choice. Three researched options with screenshots, built with the page-design process, for the founder to pick.
- **Founder**: needs the founder, not code (pricing, legal terms, pilots).
- **Discuss**: I disagree or think it should be reshaped. The reason is given in "To go over together".

Status: ☐ open · ◐ in progress · ☑ done (with the MR).

### Launch gates (P0)

| | ID | Item | Type | Notes |
|---|---|---|---|---|
| ☑ | GL-A01 | One server-side password policy (min and max) across signup, invite and change; long input gives a 400, not a 500 | Fix | !571 |
| ☑ | GL-A02 | A password change signs out every other session | Fix | !571 |
| ☑ | GL-A03 | `password_reset: true` on login must not clear an account lock | Fix | !571 |
| ◐ | GL-A04 | Forgotten-password recovery | Decide + Founder | Interim help line on the sign-in form in !572. Self-service needs an email sender, which the app doesn't have. Until then, a visible "Locked out? Contact us" route (Fix) |
| ☐ | GL-A05 | One observed independent pilot per sector | Founder | Not code |

### Product and operations (P1)

| | ID | Item | Type | Notes |
|---|---|---|---|---|
| ☐ | GL-P01 | Returns, credit notes and physical stock | Decide | Importing credit notes is a fix; how a return shows on stock and duty is a design choice |
| ☐ | GL-P02 | Quality hold and release on a lot | Decide | |
| ☐ | GL-P03 | Recall case: scope, contacts, acknowledgements, recovered quantities, closure | Decide | Pairs with GL-P02 |
| ☑ | GL-P04 | Customs deadlines count NZ public holidays | Fix | !572. Licensing already has an NZ working-day calendar; excise doesn't use it |
| ☐ | GL-P05 | Say which excise figure is the estimate and which is the filing draft | Decide | |
| ☑ | GL-P06 | Warn when the built-in duty rates are past their review date | Fix | !572 |
| ☐ | GL-P07 | Advertise only the multi-site and planning flows that are on | Discuss | |
| ◐ | GL-P08 | Contract producer: one end-to-end test of the case described | Fix | Reclassified Decide + Founder, see below |
| ◐ | GL-P09 | Guided first-day setup | Decide | !574: three styles to pick from (setup guide, task list, one step at a time). The highest-impact design item |
| ☐ | GL-P10 | One readable export of all the business's records | Decide | |
| ☐ | GL-P11 | Reminders outside the app | Decide + Founder | Needs an email sender, as GL-A04 does |
| ☐ | GL-P12 | Cost, purchasing, fulfilment depth | Discuss | |

### UX and accessibility

| | ID | Item | Type | Notes |
|---|---|---|---|---|
| ☑ | GL-U01 | Dialogs: focus moves in, stays in, Escape closes, focus returns to the button | Fix | !573. One shared helper for every custom dialog |
| ☑ | GL-U02a | Tabs marked `role="tab"` get arrow keys and their panels | Fix | !573. Section tabs stay links with role=tab; arrows move focus only |
| ☐ | GL-U02b | One name for each place (Customs vs Excise, the two Tasks) | Decide | |
| ☑ | GL-U02c | Dangerous actions say their effect on stock, sales and filed periods | Fix | !572: deleting a workflow or step silently deleted its batches; now refused, and the delete confirmations state the effect. An audit of confirmation texts |
| ◐ | GL-U03 | Interrupted saves: no false "Saved", the form kept, retry without duplicates, sign in again without losing it | Fix | !573: production steps (offline and signed-out) and a sign-in-again path for every save. Receiving, counts and evidence still to test. Production steps, receiving, counts and evidence first |
| ☐ | GL-U04 | Whole-job audit: empty, error, no permission, expired session, phone, dark, 200% zoom | Fix | Screenshot sweep with fixes. Found so far: dark-mode headings on Record step are near-invisible; a boosted arrival at pages without section tabs sits 32px lower than a full load |
| ☑ | GL-U05 | NZ alcohol examples instead of "e.g., Steel Rods" | Fix | !572 |

### Conversion (P1)

| | ID | Item | Type | Notes |
|---|---|---|---|---|
| ☐ | GL-C01 | Pricing, inclusions, cancellation | Founder | |
| ☐ | GL-C02 | Privacy and service terms linked at signup and in the app | Founder + Fix | The founder supplies the terms; the links and pages are code |
| ☐ | GL-C03 | Import templates with an error report and a preview | Decide | |
| ☐ | GL-C04 | Help and contact on every page, with a reference ID | Decide | |
| ☐ | GL-C05 | Sector-specific example journeys | Founder | Needs a real customer's permission |
| ☐ | GL-C06 | Show the exception loop in the demo | Founder | Follows from GL-P01 to GL-P03 |

### Security (P1)

| | ID | Item | Type | Notes |
|---|---|---|---|---|
| ☐ | GL-S01 | Decide and test which sales actions may change stock | Fix + Founder | The invoice and sync halves of CRM F1 still need the founder's call |
| ◐ | GL-S02 | Every background and raw-SQL path names its org | Fix | !572: event-summary raw SQL names its org; the nightly warm job is tested against a hostile neighbour. Other raw SQL is locks, schema or already org-filtered |
| ◐ | GL-S03 | Untrusted-input rendering, attachments, link protocols | Fix | Audited: no user-stored URLs or x-html; innerHTML escaped and guarded by semgrep; uploads checked by magic bytes, allowlist and global nosniff. Left: the CSP migration (needs a plan, see below) |
| ◐ | GL-S04 | Session replay and error reports never capture tokens, contacts or recipes | Fix | !572: replays mask all page text (not just inputs); invite paths and token parameters scrubbed from events. Left: error-report payloads. Tests on the masking |
| ◐ | GL-S05 | Abuse and revocation across invite, portal, auditor expiry and deactivation | Fix | !571: deactivation, role change and password change reach open sessions (expiry, invites and the portal were already tested). Follows GL-A02 |

### To go over together

- **GL-P07: advertising multi-site and planning.** This is a rule about what to claim, not a code change; the Sites page already says which flows are on. I'd keep it in the sales playbook rather than here.
- **GL-P12: commercial depth.** I agree with the report and would build these only when a named buyer is missing one; listing them here invites building ahead of demand.
- **The "ten times better" targets.** They're worth measuring in the pilots, but they're founder goals, not engineering tasks.
- **GL-A05 and GL-C05: pilots and customer references.** They can't be built, only arranged.
- **GL-P08: contract producers.** The parts that exist are already tested (portal isolation, per-order duty responsibility, per-line materials source, customer material receipts). Two pieces don't exist yet, so a test can't cover them: a dispatch record tied to stock (dispatch is only "shared" by hand), and how a customer-liable order affects the producer's own excise entry, which still counts the removal. Which party's entry a contract removal belongs on is a duty-law decision, so this needs the founder before code.
- **GL-S03: tightening the CSP.** The CSP still allows inline and evaluated script because Alpine and inline handlers need it. Removing that needs Alpine's CSP build and moving inline handlers out, page by page, with browser coverage. That's a planned migration, not a one-MR fix.
- **No archive for workflows.** After !572 a workflow with batches can't be deleted, and there's no "archive" to hide old ones. Worth a design item if old workflows clutter the list.
