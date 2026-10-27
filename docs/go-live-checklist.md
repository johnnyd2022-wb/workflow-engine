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
| ◐ | GL-A04 | Forgotten-password recovery | Founder (blocked) | Interim help line on the sign-in form in !572. **Go-live blocker, on hold (founder, 2026-10-26):** self-service reset waits for email sending, via SES once the AWS production infrastructure is built (or a Google Workspace domain for biz-e as the fallback). Future assessments not about go-live should leave it out |
| ◐ | GL-A06 | Founder reviews pricing, terms and privacy before launch | Founder (review) | **Go-live blocker.** The placeholder pricing, terms and privacy pages (!579, GL-C01/GL-C02) need the founder's review, and the terms a lawyer's. Founder (2026-10-26): assessments assume the wording is good until then |
| ☐ | GL-A05 | One observed independent pilot per sector | Founder (after go-live) | Can only happen after launch. Whistlebird (an NZ distillery the founder owns and runs) is the pilot business for distilleries. Out of scope for go-live assessments |

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
| ◐ | GL-P08 | Contract producer: every departure is a CCA transfer or an excise removal | Fix | Founder (2026-10-26): goods leaving a CCA are either transferred to another CCA (date and time of movement, the receiving CCA code, ideally proof of receipt) or entered for excise. Contract manufacturing follows the same rule as sales to duty free. Part 1 (sales to another CCA, the movement register, Customs → Transfers) in !580; part 2 (dispatching contract orders) follows |
| ☑ | GL-P09 | Guided first-day setup | Decide | !574: Style 1, the setup guide, chosen 2026-10-26 |
| ☐ | GL-P10 | One readable export of all the business's records | Decide | |
| ☐ | GL-P11 | Reminders outside the app | Founder (blocked) | Same hold as GL-A04: needs SES (or Google Workspace) after the production infrastructure. Go-live blocker; leave it out of assessments not about go-live |
| ☐ | GL-P12 | Cost, purchasing, fulfilment depth | Discuss | |

### UX and accessibility

| | ID | Item | Type | Notes |
|---|---|---|---|---|
| ☑ | GL-U01 | Dialogs: focus moves in, stays in, Escape closes, focus returns to the button | Fix | !573. One shared helper for every custom dialog |
| ☑ | GL-U02a | Tabs marked `role="tab"` get arrow keys and their panels | Fix | !573. Section tabs stay links with role=tab; arrows move focus only |
| ☐ | GL-U02b | One name for each place (Customs vs Excise, the two Tasks) | Decide | |
| ☑ | GL-U02c | Dangerous actions say their effect on stock, sales and filed periods | Fix | !572: deleting a workflow or step silently deleted its batches; now refused, and the delete confirmations state the effect. An audit of confirmation texts |
| ◐ | GL-U03 | Interrupted saves: no false "Saved", the form kept, retry without duplicates, sign in again without losing it | Fix | !573: production steps (offline and signed-out) and a sign-in-again path for every save. Receiving, counts and evidence still to test. Production steps, receiving, counts and evidence first |
| ◐ | GL-U04 | Whole-job audit: empty, error, no permission, expired session, phone, dark, 200% zoom | Fix | Screenshot sweep with fixes. A boosted arrival at pages without section tabs sat 32px lower than a full load (fixed in !575). !585: a contrast measurement of every registry page in both themes (under 3:1 flagged), down from 13 dark and 1 light pattern to none, starting with the near-invisible Record step headings; pinned by a browser test. Left: empty, error, no-permission and expired-session states, phone and 200% zoom |
| ☑ | GL-U05 | NZ alcohol examples instead of "e.g., Steel Rods" | Fix | !572 |
| ◐ | GL-U06 | Record production step opens a picker: every batch in flight and a start-new-batch list, two taps to any step | Fix (founder: go-live blocker) | !576 |

### Conversion (P1)

| | ID | Item | Type | Notes |
|---|---|---|---|---|
| ◐ | GL-C01 | Pricing, inclusions, cancellation | Fix | Founder (2026-10-26): placeholders for now. Compliance (NZ Alcohol) is NZD 250 + GST a month; inclusions and cancellation are placeholder text until confirmed |
| ◐ | GL-C02 | Privacy and service terms linked at signup and in the app | Fix | Founder (2026-10-26): placeholder terms, modelled on what NZ SaaS products publish (Privacy Act 2020, Consumer Guarantees Act and Fair Trading Act in-trade exclusions, data in AWS, exit and deletion). Marked as drafts for legal review |
| ☐ | GL-C03 | Import templates with an error report and a preview | Decide | |
| ☐ | GL-C04 | Help and contact on every page, with a reference ID | Decide | |
| ◐ | GL-C05 | Sector-specific example journeys | Fix | Founder (2026-10-26): Whistlebird is the worked example for distilleries. Other sectors after go-live |
| ◐ | GL-C06 | Show the exception loop in the demo | Fix (placeholder) | Not demoing until the checklist is done. Founder (2026-10-26): load one or two demo orgs with the replay script and walk scenarios: a new setup showing value fast, and an established org for specific questions. A placeholder script and seed now. !587: `scripts/demo_orgs.py` loads a new and an established demo org (synthetic, not Whistlebird's real customers) and `docs/demo-script.md` has both scenarios, as placeholders to rehearse |

### Security (P1)

| | ID | Item | Type | Notes |
|---|---|---|---|---|
| ☑ | GL-S01 | Decide and test which sales actions may change stock | Founder | Founder (2026-10-26): with FIFO matching a sale always takes its stock off, so authorising an invoice (sales.record) reduces stock; manual mode waits for someone with inventory.adjust to pick the batch; picking a batch or re-running matching needs inventory.adjust (!557). Written into the sales.record permission and pinned by tests in !581 |
| ◐ | GL-S02 | Every background and raw-SQL path names its org | Fix | !572: event-summary raw SQL names its org; the nightly warm job is tested against a hostile neighbour. Other raw SQL is locks, schema or already org-filtered |
| ◐ | GL-S03 | Untrusted-input rendering, attachments, link protocols | Fix | Audited: no user-stored URLs or x-html; innerHTML escaped and guarded by semgrep; uploads checked by magic bytes, allowlist and global nosniff. Founder (2026-10-26): do the CSP migration next. Step 1 (!578) and step 2, inline handlers gone and `script-src-attr 'none'` enforced (!588); step 3, Alpine's CSP build so no page needs `'unsafe-eval'` (!590); step 4 (enforce) in docs/csp-migration-plan.md |
| ☑ | GL-S04 | Session replay and error reports never capture tokens, contacts or recipes | Fix | !572: replays mask all page text (not just inputs); invite paths and token parameters scrubbed from events. !583: error reports. Failed statements no longer carry their values (`hide_parameters`), logged tracebacks drop local variables, and every log string loses emails, Postgres constraint values, parameter blocks and tokens; browser events lose email addresses. Each pinned by a test that fails on the old code |
| ◐ | GL-S05 | Abuse and revocation across invite, portal, auditor expiry and deactivation | Fix | !571: deactivation, role change and password change reach open sessions (expiry, invites and the portal were already tested). Follows GL-A02 |

### To go over together

- **GL-P07: advertising multi-site and planning.** This is a rule about what to claim, not a code change; the Sites page already says which flows are on. I'd keep it in the sales playbook rather than here.
- **GL-P12: commercial depth.** I agree with the report and would build these only when a named buyer is missing one; listing them here invites building ahead of demand.
- **The "ten times better" targets.** Founder (2026-10-26): present options once the other items are addressed.
- **GL-P08: contract producers.** Settled by the founder on 2026-10-26 (see the row): every departure from a CCA is a CCA transfer or an excise removal.
- **GL-S03: tightening the CSP.** Agreed 2026-10-26: a planned migration over several MRs, starting now.
- **No archive for workflows.** After !572 a workflow with batches can't be deleted, and there's no "archive" to hide old ones. Worth a design item if old workflows clutter the list.
