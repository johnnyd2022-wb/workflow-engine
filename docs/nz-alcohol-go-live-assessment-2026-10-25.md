# NZ alcohol go-live assessment — 25 October 2026

**Go-live readiness: 68/100.** The app has a credible product at its centre: trace production and stock to a customer, reuse those records for compliance, and prepare a defensible excise draft. I would recruit supervised pilots now, and close the authentication gates before handling their live business data. I would not open an unattended public launch across distilleries, breweries and wineries with the current authentication defects and the remaining uncertainty about each sector's complete daily workflow.

The approved page designs improve the product substantially. They do not establish that a new producer can adopt it unaided, that every exceptional stock event is handled, or that it outperforms established industry software. The opportunity is convincing; an order-of-magnitude advantage is not yet demonstrated.

## Scope and evidence

This assessment covers application code, workflows, security, data correctness, UX/UI, sector fit and the application-facing parts of conversion and support. ECS, RDS, hosting, deployment architecture, network configuration, backups and other infrastructure are excluded from the score. Moving the hosting platform will not fix the application findings below.

Assessment baseline: **`cb3362be73bcee965338b97c66ab57e27522a49d`**, after !557, !558, !559, !560, !561, !563, !564, !565, !566, !567 and !568 merged; !562 was already merged. The style choices are Style 1 throughout except People/roles (Style 2) and Sales Tasks (permanent Board/List/Week views).

Evidence comes from the final code, focused PostgreSQL-backed tests, browser checks, deliberately adverse probes and current primary sources for competitors and regulatory expectations. The combined main branch passed its full unit-test job (3,388 passed; 899 skipped) and automated security checks; focused adverse tests still exposed the launch findings below. The adverse probes below failed the secure/accessible expectations; those failures are findings, not a green test claim. Vendor documentation establishes advertised capability, not a hands-on comparison of usability or reliability. No independent producer sessions were conducted during this assessment.

Older reports were treated as leads. In particular, the previous inventory source-reference tenant leak, non-finite quantity handling and foreign product-mapping references have fixes in current code. I have not counted those historical findings as open vulnerabilities. See `InventoryRepository._assert_source_refs_belong_to_org`, `inventory_quantity.py` and `CRMService._require_known_source_outputs`.

### How the score is composed

| Area | Available | Awarded | Reason |
| --- | ---: | ---: | --- |
| Stock, production and traceability correctness | 20 | 18 | Strong lineage, quantity guards, stocktake and recall foundations; operational exception coverage needs customer proof. |
| NZ compliance completeness and trust | 20 | 14 | Substantial excise, licensing and national-programme work; deadline precision, cross-sector completeness and real verification remain uneven. |
| Application security and recovery | 20 | 13 | Tenant controls, permission policy, CSRF and admin 2FA are strengths; three confirmed auth defects and incomplete recovery reduce confidence. |
| UX, consistency and accessibility | 15 | 12 | Approved designs are coherent and responsive; modal keyboard behavior and some task journeys still need work. |
| Onboarding, conversion and support | 15 | 5 | The core value is explainable, but real independent onboarding, pricing/terms, recovery and an obvious support path are unfinished. |
| Sector fit and competitive advantage | 10 | 6 | Useful foundations for all three sectors; depth and measurable superiority have not been established in all three. |
| **Total** | **100** | **68** | **Judgment against the stated launch scope, not a test-pass percentage.** |

The security launch gates do not disappear into the average. Fixing them is required even if every other category improves. I would expect the low 80s to become defensible after the gates and successful independent pilots, but that requires evidence and a fresh score.

## What is already worth selling

1. **Connected source-to-sale records.** Supplier lots, production inputs/outputs, batch stock and invoice allocation are connected. The recall browser scenario follows a supplier lot to multiple customer invoices, flags missing contact information and exports the customer list. This is considerably more valuable than another digital checklist. See `tests/e2e/source_to_sale/test_mock_recall.py` and `app/core/backend/dagtraversal.py`.
2. **Stock correctness has structural protection.** Stored quantities use Decimal/Numeric, counted goods have whole-unit rules, mutations need a write reason, and tenant-scoped source references have explicit checks. Opening-stock/go-live and stocktake workflows reduce the pressure to invent historical production. See `tests/test_whole_units.py`, `tests/test_inventory_quantity_guard.py`, `tests/test_go_live.py` and `tests/test_stocktake.py`.
3. **NZ excise is real functionality.** The code distinguishes rate bases per litre of beverage and per litre of alcohol, effective dates, alcohol levy and GST, sales estimates versus removal-based filing, non-sale movements and locked lodgement snapshots. The 2026 built-in rates match the bands published by [NZ Customs](https://www.customs.govt.nz/about-us/news/important-notices/new-excise-duty-rates-for-alcohol-from-1-july-2026). See `excise_tariff.py`, `excise.py`, `sales_excise.py` and `movement_excise.py` under `app/features/compliant/modules/nz_alcohol/`.
4. **Compliance is connected to work.** Evidence, checks, production capture, verification outcomes, training, corrective-action material and licensing records are more useful together than as disconnected PDFs. Licensing has an inspector pack; the national-programme module contains substantive playbooks and evidence templates.
5. **Access control is more mature than a simple admin/member switch.** There is a default-deny endpoint policy, built-in/custom roles, audited user management, admin 2FA and tenant read/write backstops. These are meaningful strengths, not substitutes for fixing the auth findings.
6. **The UI now has a recognisable house style.** The selected settings cards, licensing registers, customer tabs and People/roles views reduce visual uncertainty. Sales Tasks offers real working views instead of asking customers to choose a design concept.

Keep these outcomes central to demos. A general workflow engine, every calculator, or a long module catalogue is a weaker opening story than “receive a lot, make a batch, sell it, trace it, prepare the records”.

## Launch gates: fix or prove these before an unattended public launch

Priority here means release order, not a CVSS score. P0 means I would block unattended public launch; P1 means required for a credible premium offering or for the affected customer segment; P2 can follow initial sales.

### GL-A01 — P0: enforce password requirements on the server

**Confirmed behavior:** an authenticated user can replace a strong password with `x`; `/auth/change-password` returns 200. The invite path calls `validate_new_password`, but signup through `OrgManager.create_org_with_admin_user` and password change do not share that validation. The password-policy helper explicitly provides advisory warnings. A second boundary probe confirmed that a 73-byte replacement password returns an internal 500 rather than a validation 4xx response; the locked bcrypt version is 5.0.0.

**Why it matters:** browser guidance can be bypassed, and account strength should not depend on how an account was created or changed. Admin 2FA reduces some risk; it does not make weak passwords acceptable for other roles or recovery.

**Required:** one server-side minimum/maximum policy across signup, invite acceptance, change and future reset. Preserve support for long passphrases; do not silently truncate inputs at bcrypt's limit. Make the UI describe the policy the server actually enforces.

**Acceptance:** the same short password is rejected in every entry path; valid passphrases work; oversized input returns a useful 4xx response; the existing successful-auth flows remain green. Evidence: [change-password route](../app/api/routes/auth_routes.py), [organisation signup service](../app/core/security/org_manager.py) and [shared invite password validation](../app/core/security/people.py); functions `change_password`, `create_org_with_admin_user` and `validate_new_password`.

### GL-A02 — P0: revoke existing sessions after a password change or recovery

**Confirmed behavior:** browsers A and B both sign in. A changes the password successfully. B can still fetch the authenticated `/auth/session-timeout` resource with a 200 response. Deleting trusted-device rows affects remembered sign-in; it does not revoke an already authenticated signed-cookie session. The comment in `change_password` overstates what that cleanup does.

**Required:** a server-checked authentication/session version or equivalent revocation mechanism. Reissue A's current session deliberately; reject B's old session. Apply the same mechanism to password reset and “sign out other devices”. Keep deactivation and role changes immediately effective.

**Acceptance:** B's old session is refused on the next authenticated request, A remains signed in if that is the chosen UX, remembered devices cannot reauthenticate silently, and all recovery paths have regression coverage. Evidence: [change-password route](../app/api/routes/auth_routes.py) and [session-to-user middleware](../app/api/middleware/tenant_context.py), with no checked auth-version field in current session handling.

### GL-A03 — P0: remove the caller-controlled account-lockout bypass

**Confirmed behavior:** with `account_locked_until` in the future, a normal correct-password login returns 401. The same request with `"password_reset": true` returns 200 and clears the lockout. There is no verified reset token in that request; the client supplies the flag used to skip the lock check.

This is **not** a password or 2FA bypass. The demonstrated defect is that a caller can select a path that bypasses the account-lockout control, weakening the intended account-based protection against continued guessing. The normal login limiter key is `IP:email` (`get_rate_limit_key`), so changing IP creates another bucket; the independent account-lockout layer therefore matters.

**Required:** remove the flag from normal login. Only a completed, independently verified recovery procedure may clear a lockout. Continue to apply appropriate IP/account throttles to login and recovery.

**Acceptance:** booleans, truthy strings and other caller-supplied reset flags never change the locked-login result. A real verified recovery flow can reset the lock and records an audit event. Evidence: [login route](../app/api/routes/auth_routes.py), specifically `is_password_reset`, the lockout branch and the unlock branch.

### GL-A04 — P0 for self-service launch: provide a complete recovery and trust journey

I found password change for a signed-in user, TOTP backup codes, Google sign-in and admin-issued invite links. I did not find a complete forgotten-password flow for an existing password-only user. Invites are links the admin sends; the product plan explicitly says there is no application email sender yet.

This is survivable for a supported pilot with a named recovery contact. It is a conversion and retention problem for a public “Sign up” product. Do not replace verification with an admin simply accepting an email claim.

**Required:** verified, expiring, single-use recovery; generic responses that do not enumerate accounts; clear backup-code and lost-authenticator handling; a visible support route. Google sign-in is already implemented and should not be listed as a missing feature. Offer an explicit support-assisted route until the complete self-service path exists.

**Acceptance:** a new operator can recover on a second device without an engineer, the old sessions are revoked, and an attacker cannot bind a recovery request to another tenant/account. A documented assisted launch may defer automation, not verification.

### GL-A05 — P0 for broad three-sector claims: validate an independent producer in each sector

`docs/second-producer-pilot.md` is a preparation document; roadmap 6.2 remains open. Automated scenarios and the founder's own production history are good engineering evidence, but neither establishes that an unfamiliar brewery or winery can adopt the app.

Run the same observed session with one independent distillery, brewery and winery operator: start with their real workflow, opening stock and Xero conventions; reach a traced sale; handle a realistic exception; produce the relevant compliance evidence. Record every facilitator intervention and every task the operator cannot complete. Have their actual compliance adviser/verifier review the output for the intended scope.

**Acceptance:** each sector has a recorded, repeatable successful first-day journey and an agreed supported scope. If only one sector passes, launch that scope and describe the others as pilots. A live pilot with clear human support is a reasonable next step; a claim to replace every specialist industry system is not supported yet.

## Product and operational gaps, in practical priority order

| ID / priority | Current evidence and consequence | What I would require |
| --- | --- | --- |
| GL-P01 / P1 | **Returns, credits and physical stock need one explicit supported story.** `XeroAPIClient.fetch_all_invoices` requests ACCREC invoices; I did not find a corresponding credit-note ingestion/reconciliation path. A credit note is not proof that stock came back, and a stock return is not proof of a Customs refund. | Demonstrate partial/full credits, voids, damaged returns, goods returned into bond and a subsequent re-sale. Keep financial correction, physical receipt and possible duty credit distinct, linked and auditable. Provide a documented manual path where automation is absent. |
| GL-P02 / P1, potentially a customer-specific gate | **No authoritative quality hold/release workflow was established.** The inventory model has no dedicated hold state, and the planning adapter explicitly says there is no reservation/hold ledger. Some planning code notices `extra_data` hold/quarantine markers; that is not evidence of a cross-product enforcement guarantee. | A hold on a lot must prevent use, FIFO/manual allocation and dispatch where relevant, show affected stock and descendants, require an authorised release and retain the reason/history. Until implemented, agree an explicit supported hold procedure with every pilot; never imply a trace report itself stops a sale. |
| GL-P03 / P1 | **Recall tracing is ahead of recall case management.** The existing scripted drill proves locating/exporting customers. It does not prove a customer has acknowledged a recall, affected stock is held, retrieval quantities reconcile, or corrective actions are closed. | Reuse the operational-case machinery for a compact recall record: scope, decision/risk assessment, contacts and draft notices, acknowledgements, quantities recovered/disposed, owner and closure evidence. Do not send messages automatically in a drill. [MPI's mock-recall guidance](https://www.mpi.govt.nz/food-business/food-recalls/doing-food-recall) requires testing the procedure and its effectiveness, not only finding records. |
| GL-P04 / P1 | **Deadline language is more confident than one implementation.** `excise.working_day` counts Mon–Fri and explicitly excludes public-holiday modelling. Licensing has a separate NZ working-day calendar. Customs entry and payment deadlines are different. | Use an appropriate, sourced Customs calendar and show entry, payment and renewal dates separately. If an approximation remains, label the actual date beside it as an estimate and link the authoritative deadline. Test holidays, year-end and NZ local dates. [Customs' entry/payment guidance](https://www.customs.govt.nz/business/excise/lodge-your-excise-entry/) is the baseline, including nil returns. |
| GL-P05 / P1 | **The two excise views can be misunderstood.** `sales_excise.py` is explicitly an estimate from sales; the Customs filing draft is based on removals. The distinction is correct, but a producer can still see two plausible totals for one month. | Show “sales estimate” versus “removal-based draft” consistently, provide an explanation/reconciliation link for the difference, and explain non-sale removals, credits and locked periods at the relevant action. An accountant must be able to tie a draft back to the stock events without guessing which screen is authoritative. |
| GL-P06 / P1 | **Annual rates have a maintenance dependency.** The built-in guide currently has 2024–2026 effective rates and source/check dates. It must not silently become “current” forever after the next adjustment. | An application-visible rate review date, a new-year fixture against the published rates, safe treatment of missing/overridden classifications and a clear stale-guide warning. Retain historical rates and source references on filed snapshots. Do not reprice historical removals at today's rate. |
| GL-P07 / P1 | **Multi-site and planning are partly delivered, deliberately gated.** The roadmap still describes material commitments, adapters, promise dates and further site operations as unfinished. The Sites page correctly distinguishes prepared sites from recording enabled elsewhere. | Test the exact configuration being sold. Advertise single-site or the specific enabled multi-site flows; do not sell a full ATP/MRP planner from the presence of a schedule or a site list. A promised date must say whether material readiness and capacity were actually checked. |
| GL-P08 / P1 for contract producers | **The contract portal is not a blanket proof of complete contract manufacturing.** Order/batch foundations and portal work exist, while materials ownership, duty declarations and planning integration have remaining roadmap items. | A customer supplies one material, the producer supplies another, one party is liable for duty, an order is partly made and dispatched, and the customer sees only their records. Test the whole case and refusal paths before selling it as supported. |
| GL-P09 / P1 | **Getting started is still a collection of capable screens.** Opening stock, workflow templates, Xero connection and mapping exist, but their existence does not give a newcomer a dependable sequence. | A short, resumable setup path: sector/site/obligations → starter workflow → opening-stock count → Xero connection/mappings → first batch/sale → trace/evidence check. Show completion and the next concrete action; avoid asking a new operator to understand the module architecture. |
| GL-P10 / P1 | **Durable data exit is a commercial feature.** There are several useful CSV/PDF exports, but I did not establish a single customer-facing complete export of the business's records, links and evidence with a readable manifest. | Demonstrate an export that another person can read without a live subscription: stock, batches, movements, sales allocations, compliance records, evidence and audit history. Explain retention and deletion rules, including financial/regulatory records. This is app data portability, not an infrastructure backup recommendation. |
| GL-P11 / P1 | **Reminders depend on attention.** In-app findings are useful, but a licence renewal still matters when the owner has not opened the app. The documented invite mechanism also requires a human to send a link. | Make notification expectations explicit. For supported pilots, assign a named person and review cadence; for public launch, add verified recipient preferences and useful reminder/digest delivery, retry/failure visibility and deep links. Do not promise that a date cannot lapse unnoticed without a functioning attention path. |
| GL-P12 / P2, or P1 where the sale needs it | **Cost/margin, purchasing, ordering and fulfilment are thinner than specialist suites.** Existing production and Xero invoicing should not be described as a complete financial or distribution system. | Prioritise the first buyer's missing job: landed batch/unit cost and gross margin; expected raw-material receipts/POs; pick/pack/dispatch; or a POS/e-commerce connector. Keep accounting in Xero until there is a tested reason to duplicate it. |

Returns, holds, recalls and excise reconciliation are connected: a producer must handle a bad batch, a returned case or a corrected sale without breaking stock, traceability or the duty record. That is more urgent than adding another dashboard widget.

## UX/UI and consistency

The new designs are a good direction. Keep the approved layouts and finish behavior within them; there is no case here for reopening the style selection exercise. The seeded phone review showed readable licensing status cards and useful fixed receiving/navigation actions. It also showed the legacy manual-receipt example “e.g., Steel Rods” in the NZ alcohol journey. Replace generic examples/defaults with sector-appropriate guidance where the sector is known; small language mismatches make an otherwise focused product feel unfinished.

### GL-U01 — P1: make dialogs work with a keyboard

**Confirmed browser finding:** on the approved Sales settings page, clicking **Add a mapping** shows the modal but leaves `document.activeElement` outside `[data-ss-mapping-dialog]`. Its `role="dialog"` and `aria-modal="true"` do not move focus or enforce modality by themselves. The focused adverse browser probe fails on this exact condition.

Move initial focus into the dialog, keep Tab/Shift+Tab inside, give Escape one consistent effect, make the background inert and restore focus to the trigger on close. Cover validation failure, saving and a successful close. Apply one tested implementation to the custom Sales dialogs/drawers; native dialogs on other pages should meet the same behavior. Do not merely add more ARIA attributes. The scope of the confirmed defect is the mapping dialog; inspect other dialogs rather than assuming every one has the same bug.

### GL-U02 — P1: finish navigation and interaction consistency

- Keep a stable name for the same thing across navigation, headings and action labels. “Customs”, “Excise estimate”, “Licensing”, “Tasks” and “Batch matching” need a predictable relationship; the reader should know their current workspace and the next place to go.
- Page tabs with tab semantics need the corresponding keyboard behavior and panel association. Audit this with a keyboard and screen reader; a row of clickable buttons alone does not establish accessibility.
- Confirm direct URLs, reload, browser Back, opening in a new tab and boosted navigation for every primary flow. Sales Tasks now retains the selected view in its URL as well as browser storage.
- Put the next primary action in view at phone width for recording a step, receiving stock, entering a count and attaching evidence. A page fitting without horizontal overflow is necessary but not proof that work is easy on the floor.
- Make dangerous actions state their effect on stock, sales and filed periods before confirmation. Preserve entered data and put a refused save beside its cause.

### GL-U03 — P1: make interruption safe

A phone losing connectivity, a 401 during a form, a stale edit or a duplicate tap must not produce a false “Saved”, silently lose a production record, or duplicate a removal. Idempotency and optimistic-write protection exist in parts of the backend; verify the user-facing recovery path at each critical write.

The code search did not establish a general offline queue or draft store. Do not market offline recording yet. The minimum is clear unsaved/saved status, retained form data, retry without duplication, a safe reauthentication path and an honest message when connectivity is required. A native mobile app is not required for the first launch.

### GL-U04 — P1/P2: audit the whole job, not just redesigned pages

Run the same visual and interaction checklist on production execution, workflow editing, inventory receiving/adjustment, stocktake, supplier details, trace/recall, compliance evidence, settings and account recovery. Include empty, loading, large-data, validation-error, permission-denied, expired-session, phone and dark-theme states. Test 200% zoom and long real names/addresses. Use consistent dates, precision, currency and units; keep L, mL, LAL, bottles, cases and kegs unmistakable.

The current browser tests establish specific actions and fit at representative widths. They are not a complete accessibility audit or a performance benchmark on a low-end phone. Add measurements with a realistic year of a producer's records before promising effortless scale.

## Fit for each NZ alcohol segment

All three segments carry equal weight in this recommendation. A configurable workflow and a sector template are valuable starting points; they are not proof that the specialised jobs below are complete.

| Segment | Credible value today | What could stop the sale | Evidence required before a broad launch claim |
| --- | --- | --- | --- |
| **Distillery** | Ingredient/batch trace, flexible production steps, ABV capture and tools, opening stock, removals-based excise, licensing and evidence. This is closest to the founding use case. | A producer with mature stock may need barrel/cask custody, re-gauging, evaporation/loss and blending-cost reporting. Contract/customer-owned stock and duty responsibility add complexity. Generic prompts can capture facts without providing a coherent operating ledger. | A distiller other than the founder runs a complete production-to-sale cycle, an event/sample removal, a return, a stock variance and a correction after filing. If aged spirits are in the supported market, demonstrate the cask/maturation lifecycle explicitly. |
| **Brewery** | Brewing templates include original/final gravity; fermentation and packaging can be modelled; yeast/keg tools, traceability and compliance evidence exist. | A brewery may buy for tank utilisation, fermentation readings, packaging yields, keg custody/deposits, reorders and distribution. A task board and keg-fill calculator do not establish these workflows. Breww also offers NZ excise, so that alone is not a switching reason. | Observe a brew, split packaging into kegs/cans, an ullage/return, stock allocation, one taproom/wholesale sales path and the excise reconciliation. Establish which keg/deposit, fulfilment and vessel jobs remain in other systems. |
| **Winery** | Grape-intake/cellar/bottling templates, lot lineage and a Wine Standards Management Plan framework exist. `catalogue.py` contains registration, risk-control, trace/recall and wine-return evidence controls. | Four WSMP controls are not demonstrated end-to-end winery management. Buyers may require harvest/vineyard/contract-grower handling, lab results, blend composition, additions, tank/barrel movements, cost and export evidence. A generic “NP3 pack” cannot describe every winery's obligations. | A winemaker maps their actual WSMP and, where relevant, export requirements to the app and produces the required records from a real blend/bottling/sale. Review the [MPI integrated WSMP model](https://www.mpi.govt.nz/dmsdocument/52927/direct) with that winery rather than implying that a general template settles its scope. |

For any segment, test allergen/label evidence and the programme actually selected. MPI's current [national-programme guidance](https://www.mpi.govt.nz/food-business/running-a-food-business/national-programmes) includes updated water, allergen-labelling and mock-recall requirements. The app has substantive controls in these areas; the remaining task is proving the producer's real process satisfies them and making omissions visible.

## Competitive assessment

Checked against official vendor material on 25 October 2026. These are capability and positioning comparisons, not claims that I have run timed hands-on trials of the competing products.

| Alternative | What its own documentation establishes | Implication for Biz-E |
| --- | --- | --- |
| **Vinsight** | Its [distillery product](https://www.vinsight.net/distillery-app) advertises production traceability, bonded/multiple locations, cost tracking, purchasing, price books, 3PL-related workflows and Xero. It publishes NZD monthly tiers of $59/$99/$177/$399 excluding applicable tax, with differing user allowances and plan inclusions. | This is a direct NZ-relevant alternative, not an unsophisticated spreadsheet. A producer may already have broader commercial and inventory workflows here. Win on a demonstrably easier connected compliance/trace journey, while clearly explaining any work they must retain elsewhere. Do not compare price without matching inclusions, users and onboarding. |
| **Breww** | Its official [NZ excise announcement](https://community.breww.com/t/new-zealand-alcohol-excise-duty-calculations-are-here/7307), originally posted 18 August 2026, describes NZ duty and HPA levy calculations with breakdowns for entry preparation. Its [Xero integration](https://breww.com/features/integrations/xero/) describes invoice/credit-note syncing, stock/WIP/COGS journals and payment/balance data. | “We support New Zealand excise and Xero” is not a unique proposition. Brewery buyers will compare commercial depth, daily usability and migration effort. Biz-E's strongest potential distinction is joining production facts, compliance evidence and recall actions with less setup and less duplicate work. That distinction must be measured. |
| **vintrace** | Its [plans](https://www.vintrace.com/pricing-and-plans/) describe harvest, vineyard blocks, wine production, tank maps, labs, trial blends and, in higher plans, finished goods and costing. Its [accounting documentation](https://support.vintrace.com/hc/en-us/articles/32303315132180-Accounting-Integration-with-vintrace) explicitly covers NZ excise and sales/purchase/client billing with Xero. | A winery switching from a specialist cellar system could lose considerable domain depth. Start by proving a winery's complete supported scope. An attractive generic workflow editor is not sufficient grounds to claim a better winery operating system. |
| **Safe Food Pro** | Its [product material](https://www.safefoodpro.com/) describes mobile food-safety recording, training/certifications, temperature monitoring and audit-ready reports. | This is chiefly a benchmark for easy compliance recording rather than a complete substitute for production and stock. Biz-E can connect evidence to batch facts, but must be at least as clear about what a staff member needs to record next and how a verifier finds it. |
| **Xero + spreadsheets + shared folders** | A likely buying alternative to validate in pilot interviews, rather than a researched vendor feature claim. It gives the owner familiar tools and requires no migration decision. | The competitor is often “continue doing what works this month”. The demo must remove a measurable job: reconstructing a recall, assembling verification evidence or reconciling an excise entry. Merely moving the same transcription into more screens will not convert. |

I cannot substantiate that Biz-E is currently ten times better than these alternatives. The plausible route is ten times less effort on a small set of important outcomes, supported by a connected record model. Matching every feature in a mature brewery/winery suite first would delay the product without proving that advantage.

## What would stop conversion, even if the software works

| ID / priority | Buyer question | Needed application/product response |
| --- | --- | --- |
| GL-C01 / P1 | **What does it cost, what is included, and what happens if I cancel?** | Complete the founder's existing pricing/inclusion decision sheet (roadmap 6.3). Show currency/GST, included sectors/modules/users/sites, onboarding/support, trial limits, cancellation and export. Manual billing can support an initial launch; an automated billing platform is not the first blocker. |
| GL-C02 / P1 before public signup | **Can I trust you with recipes, staff/customer data and regulatory records?** | Publish and link real privacy, service and support terms at signup and in the app. I did not find privacy/terms links in `landing.html`. Explain data use, access, retention, export/deletion and telemetry in ordinary language. The [NZ government's privacy-statement guidance](https://www.digital.govt.nz/standards-and-guidance/design-and-ux/usability/privacy-statements-for-websites?rf=1) is a useful baseline for transparency; have the business's actual terms reviewed. |
| GL-C03 / P1 | **How do I move my existing records without rebuilding years of production?** | Sell a controlled cutover through opening stock, mapping preview and reconciliation. Give import templates with an actionable error report, a trial import/preview, and a known way to correct a mistake. Existing opening-stock functionality is an asset; turn it into the onboarding path. |
| GL-C04 / P1 | **Who helps when a count or filing does not look right?** | Put a visible help/contact action on the relevant page, include a safe reference ID, and document ownership/response expectations. Recovery should not require discovering which agent or repository file owns a feature. |
| GL-C05 / P1 | **Does this genuinely work for a business like mine?** | Show a permissioned, sector-specific example: a distillery sample removal, a brewery split packaging/return, or a winery blend/WSMP evidence journey. Follow with a real customer reference once the independent pilot succeeds. Do not invent testimonials or regulatory endorsement. |
| GL-C06 / P1 | **Will I need to run another stock spreadsheet anyway?** | Demonstrate the exception loop: receipt → production → sale → return/variance/hold → corrected trace and duty. If a supported manual step is needed, show it during the sale. Hidden gaps discovered after onboarding damage trust more than a clearly bounded offer. |

The current landing page tells the source-to-sale story much better than a generic manufacturing pitch. Its primary sign-up action nevertheless runs ahead of the demonstrated onboarding/recovery/commercial journey. A prominent supported-pilot or book-a-walkthrough path is a reasonable launch choice while those gaps are closed.

## Further application security work

The three confirmed auth defects above come first. Then:

- **GL-S01 / P1 — finish permission boundaries around stock-changing sales operations.** !557 restricts explicit batch picking/reconciliation with `inventory.adjust`. Check invoice authorisation, Xero sync and custom-role combinations separately: decide which sales-driven stock changes are delegated by a sales permission, document that decision and test it. Do not assume a disabled matching button settles the whole downstream inventory effect. This is the remaining distinction in the CRM F1 audit, not a claim that every sales-triggered stock update is illicit.
- **GL-S02 / P1 — prove the tenant boundary in background and portal paths.** The global ORM filter deliberately permits no-context work and does not cover raw SQL or identity-map returns. HTTP middleware and explicit query checks are important backstops. Keep them; inventory every unscoped worker/task/raw-query path, require an explicit org and test hostile neighbour data. The documented mechanism gap is not by itself a demonstrated current HTTP leak.
- **GL-S03 / P1 — shrink XSS containment weaknesses deliberately.** CSP still allows inline/evaluated script because of existing Alpine/HTMX usage. Moving to a compatible CSP-safe expression strategy requires a migration; removing header allowances in isolation would break the app. Prioritise untrusted-input rendering, attachment handling and explicit protocol validation now, then tighten CSP with browser coverage. No new exploitable XSS was established in this assessment.
- **GL-S04 / P1 — test privacy behavior with real-shaped data.** RUM/session replay has masking controls; verify that credentials, invite/recovery tokens, customer contact details, recipes and evidence do not appear in captures or error reports. Make these controls part of application tests and the privacy explanation, not an assumption from enabling “masking”.
- **GL-S05 / P1 — test abuse and revocation as a complete journey.** Password reset, invite reissue/acceptance, account email changes, portal login, auditor expiry, deactivation and concurrent sessions should share clear rules. Avoid account enumeration and excessive work on anonymous endpoints; rate limits must stay effective across the supported application configuration.

The recovery/revocation and password recommendations align with the [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) and [Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html). This is targeted engineering assessment, not a completed penetration test of every endpoint.

## What I would build and prove next

This is a release sequence, not a requirement to implement every desirable feature before the first sale.

| Order | Deliverable | Exit criterion |
| --- | --- | --- |
| 1 | **Close GL-A01–A03 and the modal focus defect.** Small, separately reviewed changes with adverse regression tests. | The reproductions below fail on this baseline and pass with the fixes; normal sign-in, 2FA, Google linking, password change, invites and dialog save/cancel flows still work. |
| 2 | **Make the launch offer trustworthy.** Supported scope, recovery/help, pricing/inclusions, privacy/service terms and a guided first-day route. | A buyer can understand the offer, start, get help and leave with their records; no hidden manual recovery or unsupported module is discovered after purchase. |
| 3 | **Complete the exception drill.** Return/credit, hold/recall, stock variance, non-sale removal and post-lodgement correction. | Quantities, affected customers and duty reconcile; responsibility and each manual step are clear. Close or explicitly bound the affected segment's GL-P01–P08 gaps. |
| 4 | **Run three observed pilots.** One independent operator in each sector, with their real terminology and workflow. | Complete first traced sale and appropriate evidence/draft, log facilitator assistance, review exceptions and obtain permission for any reference. Do not tick roadmap 6.2 from a synthetic test. |
| 5 | **Polish from measured friction.** Keyboard/phone use, slow or interrupted saves, imports, labels and the first-screen next action. | Repeat the same tasks; fewer interventions and no lost/duplicated writes. Fix the failures that cost an operator time before adding optional breadth. |
| 6 | **Expand the specific jobs buyers will pay for.** Cost/margin, procurement, keg/cask operations, winery depth, fuller planning or commerce integrations. | A validated customer need, complete supported workflow and a clear commercial reason. These are not all prerequisites for a bounded initial offer. |

A minimum supported launch is achievable without a full ERP, a native mobile app, every POS connector, a rewrite of the frontend framework, every remaining architecture carve, automated billing or a sophisticated optimiser. Those are not substitutes for dependable stock, access control, recovery and a convincing first customer journey.

### Turn “ten times better” into a testable claim

Use the same starting data and operator to establish a baseline in their current tools. The numbers below are proposed targets, not measurements already achieved or claims about all competitors.

| Outcome | Initial release bar | Evidence of an order-of-magnitude advantage |
| --- | --- | --- |
| Find a dangerous batch's customers | Correct export in under five minutes, including missing contacts and remaining stock. | At most one tenth of that operator's prior elapsed/manual effort, with a complete decision/contact/recovery record rather than a faster but incomplete list. |
| Prepare verification evidence | Relevant records and attachments are readable, linked and understandable to the verifier. | At most one tenth of the measured preparation effort, with no spreadsheet/folder reconstruction of the same facts. |
| Prepare an excise period | Correct sourced rates, removal totals, exceptions and an auditable draft; filing remains a deliberate human action. | At most one tenth of recurring reconciliation effort over several periods, with no unexplained difference to the filed entry. |
| Adopt the product | First traced sale in one supported sitting; no fabricated historical batches. | A measured reduction in onboarding and migration effort, with the operator independently repeating the workflow later. |
| Operate on the floor | Successful key tasks at 390px/200% zoom, keyboard where applicable, and interrupted-save recovery without loss or duplication. | A large measured reduction in recording effort/errors; do not force a “10×” headline where a more honest measure is appropriate. |

Measure accuracy, support time and repeatability alongside speed. A five-minute scripted recall test is a useful regression guard; it is not proof of tenfold competitive advantage or of the complete real recall procedure.

## Validation record and limits

- **Assessed commit:** `cb3362be73bcee965338b97c66ab57e27522a49d`. All eleven requested MRs were verified merged, each with a successful final head pipeline.
- **Combined main CI:** the full unit-test job passed **3,388 tests, with 899 skipped** in 348.47 seconds. Skipped tests are not passing coverage. Migration reversibility, Ruff, feature-route checks, secret/dependency scanning and application security jobs passed. The full pipeline finished successfully, including all three deployed smoke checks on that exact combined commit. [Pipeline](https://gitlab.com/whistlebird/workflow-engine/-/pipelines/2986174355).
- **Focused business/security regression:** 311 PostgreSQL-backed tests passed on `88d8ad7a` during integration. The later application changes are UI/page registration; this is supporting evidence rather than a second independent full-suite count.
- **Deliberate final-baseline probes:** four security assertions failed as expected: weak replacement password accepted (200), another browser's session remained usable (200), caller-supplied reset flag cleared account lockout (200), and a 73-byte replacement password produced 500. These establish GL-A01–A03. One browser assertion failed because the mapping dialog did not receive keyboard focus (GL-U01).
- **Static review:** the selected UI changes passed targeted Python/JavaScript checks and Semgrep. A further Semgrep auto-rules scan of the four authentication/security files reviewed for this report completed with zero findings (290 rules). The reproduced defects show why a clean static scan is not a security verdict.
- **Browser regression and visual review:** The source-to-sale suite plus boosted-navigation and authenticated-page-render checks passed **91/91** on the final assessed commit (485.17 seconds). Run with `env -u ENVIRONMENT uv run pytest tests/e2e/source_to_sale/ tests/e2e/test_boosted_navigation.py tests/e2e/test_pages_render.py -q -p no:cacheprovider`; the local browser harness requires `ENVIRONMENT` unset. The initial `ENVIRONMENT=test` attempt skipped all 91 and was not counted. A seeded sweep captured 26 surfaces at 390px and 1440px (52 page/viewport combinations): all returned successful HTTP responses and none had document-level horizontal overflow. Eight additional dark-theme screenshots were captured. Representative screenshots were inspected manually, including Home, receipt, planner, sales, licensing, People, stocktake, NP3 and dark inventory; this is a first-viewport spot check, not every interaction or a complete contrast audit. The synthetic org was purged after use.

The following remain unproved and should not be advertised as completed evidence:

- an independently observed end-to-end adoption session for each of the three sectors;
- a live accountant/verifier's sign-off on each intended compliance scope and a real customer period's complete reconciliation;
- complete credit-note/physical-return/hold/recall closure across sales, stock and duty;
- a comprehensive accessibility audit, low-end-phone performance with a realistic year's data, and all connectivity/session-expiry scenarios;
- an independent penetration test, a full data-export/retention review and every background/portal permission combination;
- timed hands-on competitor benchmarks or an established willingness-to-pay result.

The selected design MRs can be successfully merged and their tests can pass while these product release gates remain open. This report intentionally records that difference.

### Reproduce the confirmed security findings

From the assessed checkout, place the following in a temporary `tests/_go_live_security_probes.py` and run:

```bash
ENVIRONMENT=test uv run pytest tests/_go_live_security_probes.py -q -p no:cacheprovider
```

The real PostgreSQL test configuration and the repository's existing account fixture are required. The fixture creates its own test account. These assertions describe the desired security behavior; all three fail on the assessed baseline with actual HTTP 200 responses. A separate 73-byte replacement-password probe returned 500 rather than the expected validation 400 (GL-A01). Remove the temporary file after use; do not hide these failures by relaxing the assertions.

```python
from tests.test_auth_password_session import account, PASSWORD  # noqa: F401


def test_password_change_revokes_another_browser(account):
    other = account["make_client"](PASSWORD)
    assert other.get("/auth/session-timeout").status_code == 200
    new = "Replacement-Password!2026"
    changed = account["client"].post("/auth/change-password", json={
        "current_password": PASSWORD,
        "new_password": new,
        "new_password_confirm": new,
    })
    assert changed.status_code == 200
    assert other.get("/auth/session-timeout").status_code in (401, 403)


def test_one_character_password_is_refused(account):
    changed = account["client"].post("/auth/change-password", json={
        "current_password": PASSWORD,
        "new_password": "x",
        "new_password_confirm": "x",
    })
    assert changed.status_code == 400


def test_a_client_flag_cannot_clear_an_account_lock(account, db):
    from datetime import UTC, datetime, timedelta
    from app.core.db.models.user import User

    db.query(User).filter(User.email == account["email"]).update({
        User.account_locked_until: datetime.now(UTC) + timedelta(minutes=15),
    })
    db.commit()
    payload = {"email": account["email"], "password": PASSWORD}
    ordinary = account["make_client"]().post("/auth/login", json=payload)
    assert ordinary.status_code == 401
    flagged = account["make_client"]().post("/auth/login", json={
        **payload, "password_reset": True,
    })
    assert flagged.status_code == 401
```

For the mapping-dialog focus probe, reuse `sales_page`, `xero` and their re-exported fixtures from `tests/e2e/test_sales_settings_page.py`: open `/crm/configuration`, wait for `.sales-settings[aria-busy='false']`, click **Add a mapping**, confirm the dialog is visible, then assert:

```python
assert sales_page.evaluate(
    "document.querySelector('[data-ss-mapping-dialog]')"
    ".contains(document.activeElement)"
)
```

The actual result is `False`. Confirm focus containment/restoration and keyboard operation when fixing it, rather than just making this initial-focus assertion pass.
