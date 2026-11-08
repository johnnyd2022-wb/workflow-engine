# Settings design review — 2026-10-12

Scope: current Settings template, new settings-design CSS/JS, shared fallback initializer,
new Settings browser tests, changed workspace-overviews Settings test, and screenshot
scenario assertions. HTML review, JS review, and test-evaluator applied independently.
Application and test files were not edited by this reviewer.

## Findings and corrections

1. **Boosted arrival does not run the dedicated initializer.** The main inline Settings
   script remains in the `scripts` block outside `#page-content`. The SPA shell selects
   only `#page-content` on navigation. The new fallback guard then skips initialization
   on the redesigned page. Move the dedicated initializer into content or invoke it via
   the page lifecycle; verify both first boosted arrival and leave/return.
2. **The new IIFE permits repeat execution without global teardown.** Once executed on
   boosted navigation, the inline script adds another fetch wrapper, visibility/error
   listeners, activity listeners and a 45-second interval per visit. Independent throttle
   state means multiple `/auth/me` pings after repeated visits. Register a page teardown
   or keep genuine global behavior under one shell lifetime guard.
3. **Board/desk summaries advertise unavailable disclosure.** Their native `summary`
   remains keyboard focusable, while pointer events are disabled and a toggle callback
   immediately reopens the category. Make the disclosure work or expose a noninteractive
   heading when disclosure is unavailable. Preserve native disclosure in Register.

Findings were sent promptly to the author. Re-review confirmed the corrections:

- Dedicated account/security code is now extracted to `settings-controller.js`, loaded
  within content after password-policy, and registered through `bize.onPage`. The shared
  legacy fallback skips this dedicated page; the selected content includes all scripts
  required for a fresh boosted arrival.
- Document/window listeners share an AbortController; all page timer IDs are tracked and
  cleared; the installed fetch wrapper is restored at teardown. Only page-owned requests
  receive the cancellation signal, and response/JSON completion checks cancellation before
  old state can touch the next page. Global requests retain their independent behavior.
- Page-owned toast/modal elements are tracked and removed when leaving. Abort catches
  avoid false error messages; callers of retryOperation explicitly stop on teardown before
  consuming an undefined canceled result. The nested 2FA JSON catch also stops on teardown.
- Styles 1/2 hide native summaries and expose noninteractive named headings. Register
  exposes the working native summaries, with the duplicate headings hidden.
- Existing mutations now explicitly send the CSRF meta token without changing payloads.
  The disable-2FA confirmation clones static template content rather than HTML strings;
  it has a named dialog role, modal semantics and a named close control. Activity cleanup
  explicitly clears its named interval as well as the tracked timer collection.

Static HTML/JS verdict after correction: **clean for the reviewed changes**. This is not
a full audit of legacy authentication code or a runtime claim for every security flow.

## Static test evaluation

- `test_settings_groups_account_security_and_organisation_in_cards`: prior card-stack
  geometry is deliberately replaced by explicit account/organisation group positioning.
  Exact destinations, ordered headings, responsive alignment and overflow checks survive.
  This is a specified layout change, not silent assertion weakening.
- `test_concepts_keep_all_settings_reachable`: verifies exact concept selection, required
  headings, editable loaded account, category visibility, destinations and overflow at
  four widths. No tautology; a missing category or layout overflow can falsify it.
- `test_profile_load_failure_disables_editing_until_retry`: real intercepted failure,
  disabled inputs/save, retry, real returned email and hidden load status. Claims are
  specific and can fail independently of its fixture.
- `test_notification_controls_are_explicitly_unavailable`: disabled/unchecked notification
  controls and independently enabled appearance control reflect the stated product change.
- `test_concept_switch_preserves_draft_and_boosted_return`: real draft survives layout
  changes; window sentinel, remembered concept and server-loaded email guard return.
  Dedicated lifecycle tests below now extend its return coverage.
- `test_repeated_boosted_visits_have_one_activity_ping`: advances a controlled clock,
  dispatches real input after three boosted arrivals, observes the real `/auth/me` request
  and asserts exactly one ping per visit. Removing listener teardown can falsify this.
  The initial numeric-ID CSS selector and incorrect fixture 2FA expectation were flagged
  and corrected: bracketed ID selection and expected Disabled. Runtime remains deferred.
- `test_departure_cancels_pending_profile_load`: injects a pending profile GET, records
  the supplied AbortSignal and verifies it is aborted by boosted departure. This directly
  detects missing cancellation; it does not prove late JSON completion cannot mutate a
  replacement page. That continuation protection was assessed statically.
- Screenshot scenarios assert a real save followed by reload, unsaved draft preservation,
  explicit load failure/retry, loading-disabled-save, and boosted return with sentinel.

No unjustified skip/xfail, assertion tautology, widened value tolerance, or silent dropped
behavior claim found. Local pytest and mutation probes were **not run**, as the user
explicitly requested CI to run tests and requested no CI monitoring. Test-evaluator
runtime verdict: **inconclusive (runtime/mutation verification intentionally deferred)**.
Static validity: claims are meaningful and falsifiable. No runtime pass is claimed.

## Security and scope

New account inputs retain existing IDs and gain associated labels. Preview storage contains
only a UI preference. New navigation code uses no user-derived HTML. Permission conditionals
for organisation destinations survive; no route/API/authentication policy changes occur.
Raw account fetches and legacy security markup predate the redesign; this review flags the
new lifecycle interaction without asserting a full authentication-security audit.

## Screenshot inspection

This reviewer read images individually with view_image. The inspection ledger below
enumerates every filename by pass, style and suffix (filename is `styleN-SUFFIX.png`):

| Pass | Styles | Suffixes viewed | Count |
| --- | --- | --- | --- |
| 02 | 3 | edited, error, loading, organisation, preferences, return, security | 7 |
| 03 | 1, 2, 3 | edited, error, loading, organisation, preferences, return, security | 21 |
| 04 | 1, 2, 3 | dark, desktop, edited, error, laptop, loading, organisation, phone, preferences, return, security, wall | 36 |
| 05 | 1, 2, 3 | dark, desktop, edited, error, laptop, loading, organisation, phone, preferences, return, security, wall | 36 |
| 05 | 1 | session | 1 |
| 06 | 1, 2, 3 | dark, desktop, edited, error, laptop, loading, organisation, phone, preferences, return, security, wall | 36 |
| 06 | 1 | session, 2fa | 2 |
| 07 | 1, 2 | dark, desktop, edited, error, laptop, loading, organisation, phone, preferences, return, security, wall, session, 2fa, appearance | 30 |
| 07 | 3 | 2fa (masked replacement) | 1 |

No actionable clipping, overlap or spacing defect was found in these 170 screenshot
filenames. The final three enrollment captures were subsequently replaced with viewport
captures masking the QR/manual secret; this reviewer read all three replacements too.
Register's pass-03 field pairing improves on pass 02: company full width, first/last names
paired, email/phone paired. Error/retry and disabled loading-save states are explicit;
organisation destinations and preference availability remain understandable. Board's long
page is the documented visibility tradeoff rather than a broken layout. All four widths
in passes 04/05 preserve reachable content; the fixed mobile navigation appearing inside
a tall full-page capture is a screenshot artifact, not evidence that scrolling is blocked.
The session-save screenshots display a success message and the updated two-hour value.
The enrollment dialog fits the phone width, with readable QR/manual-code instructions and
reachable cancel/start controls. Actual appearance-toggle screenshots show the dark theme
and checked control together. Passes 05/06 stopped on external capture-harness selector/
hidden-input errors; their PNGs are inspected but those runs are not reported as passing.
Screenshot inspection does not establish the final controller's runtime lifecycle safety.
The author independently inspected all 15 Style 3 pass-07 images, completing final-pass
coverage for all 45 PNGs. This review records that author inspection separately from the
170 filenames personally viewed above. Static findings are corrected, required local
pytest remains intentionally deferred, and the designs await the user's concept choice.

Overall static review: **clean after corrections**. Test-evaluator runtime verdict remains
**inconclusive**, intentionally deferred to CI under the user's instruction. No local
pytest, mutation run, CI monitoring or application/test edit was performed by this reviewer.
