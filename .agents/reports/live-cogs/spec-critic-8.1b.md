Build-readiness grade: not ready. I found seven high-impact and six medium-impact gaps. The SDK enum literals themselves are correct; the main SDK problem is underspecified field mapping.

## High impact

1. **Purchase lines lack stable Xero account identity**

   Spec: [1159–1164](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1159>), [1176–1179](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1176>), [1199–1201](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1199>).

   `purchase_lines` stores only `account_code`, yet account overrides are addressed by `xero_account_id`. `AccountCode` is nullable and mutable; the installed SDK provides the stable `LineItem.account_id` separately ([line_item.py:32](</home/johnny/wt-live-cogs-xero/.venv/lib/python3.14/site-packages/xero_python/accounting/models/line_item.py:32>)). A code rename can leave lines unclassifiable or cause an override to update the wrong historical lines.

   **Fix:** Add `xero_account_id` to `purchase_lines`, with a composite tenant FK to `xero_accounts`. Match by `AccountID`; allow code fallback only when exactly one account in the same Xero tenant matches. Keep code/name merely as snapshots. Add an AC covering a code rename and override after rename.

2. **LineItemID handling contradicts the fingerprint algorithm**

   Spec: [1190–1197](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1190>), AC67–68 at [1227–1230](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1227>).

   The first sentence says a matching `LineItemID` updates in place. The generic rule immediately afterwards says same key plus changed fingerprint supersedes it. AC68 demands the former. Two faithful implementations can therefore produce different identities—fatal once 8.1c allocations reference those rows.

   AC67 also says inserting `A,X,B` “supersedes pos:2 and pos:3”; there was no original `pos:3`.

   **Fix:** Define two explicit branches:

   - With `LineItemID`: key by ID and update the row in place regardless of fingerprint.
   - Without ID: compare the positional key and fingerprint; mismatch supersedes.

   Rewrite the insertion AC to say old `pos:2` is superseded, new `pos:2=X` and `pos:3=B` are inserted, and `pos:1` is retained.

3. **The positional fingerprint is not deterministic enough**

   Spec: [1191–1196](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1191>).

   `normalise(description)` is undefined, as are null encoding, decimal scale, Unicode handling and delimiter escaping. `a|b`-style concatenation is collision-prone when text contains `|`. The fingerprint also omits stored fields such as `unit_amount` and `tax_amount`, despite claiming that a match means “unchanged”.

   **Fix:** Specify canonical JSON or length-prefixed encoding, explicit nulls, Unicode normalization, whitespace rules, and canonical Decimal strings. List every source field that determines positional identity. Add ACs for null versus empty, pipe characters, decimal scale, Unicode and tax/unit changes.

4. **Applying the start-date filter to every incremental fetch loses backdated edits**

   Spec: [1170–1174](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1170>).

   A stored 10 November transaction edited in Xero to 31 October will no longer satisfy `Date >= start_date`, so its modification, deletion or recoding is never seen. That breaks the later-change rules required by 8.1c.

   **Fix:** Use the Xero date predicate only for the bootstrap. Subsequent calls should fetch solely by modified-since, then locally accept either:

   - a previously known external ID, regardless of its new date; or
   - a new document whose current date is on/after `start_date`.

   Add an AC for a stored transaction moved before `start_date`.

5. **FX handling cannot distinguish base currency from a missing foreign rate**

   Spec: [1181–1188](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1181>), AC66 at [1225–1226](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1225>).

   AC66 explicitly treats an AUD document with a null rate as already base currency. That can silently store AUD as NZD. The codebase does not currently store the organisation’s base currency, although the installed SDK exposes `Organisation.base_currency` ([organisation.py:451](</home/johnny/wt-live-cogs-xero/.venv/lib/python3.14/site-packages/xero_python/accounting/models/organisation.py:451>)).

   A11 also leaves the conversion direction as a live-production verification task, which is not build-ready.

   **Fix:** Fetch/cache Xero’s base currency. Base-currency documents need no rate; foreign documents require a positive rate, including a legitimate rate of exactly 1. Null or non-positive foreign rates become `needs_rate`. Resolve the divide-versus-multiply rule with an authoritative captured Xero fixture before merging, or quarantine every foreign document as `needs_rate`. Correct AC66 accordingly.

6. **Transaction boundaries and cursor advancement remain underdefined**

   Spec: [1165–1168](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1165>), [1203–1211](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1203>), AC71–72.

   Important outcomes are unspecified:

   - Whether `start_date` survives missing scopes or a failed first sync. If it rolls back, a retry tomorrow silently advances the start and misses a day.
   - Whether account-cache writes roll back when the later bank call fails.
   - Whether the sales cursor advances when sales succeeded but purchases failed.
   - Whether job finalization, purchase counters and cursor commit atomically.

   The baseline finalizer also defines “partial” by nonzero synced counts ([xero_sync_service.py:43](</home/johnny/wt-live-cogs-xero/app/features/crm/services/xero_sync_service.py:43>)); successful zero-row sales followed by a purchase exception can therefore become `failed`, contrary to AC71.

   **Fix:** State the unit of work explicitly:

   - Persist `start_date` once, before scope/API checks, so it is the activation anchor.
   - Put account changes, documents, lines and `purchases_cursor` in one phase savepoint.
   - Never commit inside purchase helpers.
   - Finalize the job once in the outer transaction.
   - Track phase success independently of row counts.
   - Define sales-cursor advancement independently from purchase success.

   Add ACs for zero-row sales plus purchase failure, first-sync failure across NZ midnight, and failure after accounts were updated.

7. **The 8.1b account override operation conflicts with 8.1c rule precedence**

   Spec: [1199–1201](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1199>) versus the referenced precedence rules at [551–564](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:551>).

   “Re-classifies every live line” is safe only before rules exist. In 8.1c, blindly updating every line will overwrite payee/description rules and manual treatment overrides that are supposed to outrank account defaults.

   **Fix:** Introduce a single `classify_line`/`reclassify_account_lines` seam in 8.1b. It currently returns the account effective treatment; 8.1c extends it with rule/manual precedence. Account PUT and account-sync changes must invoke that seam rather than bulk-writing the account treatment.

## Medium impact

8. **The source identity is not tied to the connected Xero tenant**

   Spec: [1151–1158](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1151>).

   Accounts and documents are unique only per Biz-E org. The current OAuth model can retain multiple `XeroTenant` rows, while purchase cursor/settings are per Biz-E org. Selecting a different Xero organisation can mix account codes and reuse the old cursor.

   **Fix:** Store `xero_tenant_id` on Xero accounts and purchase documents, include it in source uniqueness, and store which tenant owns `purchases_cursor`. On tenant change, reset that cursor without discarding old purchase facts. Add a tenant-switch AC.

9. **`unit_amount` and refund sign semantics are incomplete**

   Spec: [1159–1162](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1159>), [1181–1188](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1181>).

   `amount_ex_tax` and tax are converted, but `unit_amount` is not defined as source currency versus base currency, inclusive versus exclusive, or signed versus unsigned. “Refund stores amounts negated” also fails to define behavior if Xero supplies a negative source line. This will give 8.1c different pre-fill and refund behavior between implementations.

   **Fix:** Either rename/store `source_unit_amount` with explicit source semantics, or define a base-currency ex-tax unit amount. State sign invariants for every monetary field and behavior for mixed/negative source lines. Define totals as null for `needs_rate`.

10. **SDK adapters are not pinned**

   Spec: [1151–1153](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1151>), [1176](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1176>).

   In xero_python 4.0.0, account class is `Account._class`, not `account_class`; account type, currency and line-amount type are Enum values requiring `.value`. `str(AccountType.DIRECTCOSTS)` produces `AccountType.DIRECTCOSTS`, not `DIRECTCOSTS`.

   **Fix:** Add the exact adapter mapping to the contract and require tests using real SDK objects. The literal enum values listed by the spec—`DIRECTCOSTS`, `EXPENSE`, `Exclusive`, `Inclusive`, `NoTax`—are otherwise correct.

11. **Stored-scope gating mishandles unknown scope state**

   Spec: [1205–1207](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1205>).

   `XeroOAuthToken.scopes` is nullable. Existing CRM behavior deliberately treats an empty scope record as unknown and attempts the call ([contact_service.py:252](</home/johnny/wt-live-cogs-xero/app/features/crm/services/contact_service.py:252>)). Token refresh can also overwrite scopes with a missing response value.

   **Fix:** Only preflight-reject when a nonblank stored scope list definitively lacks a required scope. For null/blank, attempt the API and translate insufficient-scope. Preserve the previous scope string when refresh omits it. Add both cases to AC71.

12. **Counters are unobservable and `purchases_synced` is ambiguous**

   Spec: “skipped and counted” at [1176–1179](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1176>), AC72 at [1238–1239](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1238>).

   No job/result field is specified for skipped lines. “Documents upserted” could mean remote documents processed, inserted, changed, or merely returned again by the overlap window.

   **Fix:** Define every count precisely. For example, `purchases_synced` equals successfully processed remote transactions having at least one stored line, including unchanged retries; expose skipped-line/document counts in job details or remove “counted”. Add repeat-sync and no-expense-lines assertions.

13. **Layer-1 keyword matching is nondeterministic**

   Spec: [537–543](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:537>), AC64.

   Case handling, word boundaries, plurals and precedence are unspecified. Naive substring matching makes `rent` match “current”; stemming choices make “salary” behavior differ. “One test each” does not cover each listed keyword.

   **Fix:** Define exact casefold/token or prefix semantics, explicitly order duty before overhead, and table-test every keyword plus near-miss names.

14. **Isolation and downgrade ACs do not protect the new user-owned data**

   Spec: AC70/73 at [1232–1241](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:1232>) and the referenced migration rule at [189–193](</home/johnny/wt-live-cogs-xero/.agents/specs/live-cogs.md:189>).

   AC73 checks document/account reads but not cross-org line attachment or account reclassification. Also, `treatment_override` is user-authored data with no other copy, yet the general downgrade rule mentions refusing only while typed prices exist.

   **Fix:** Add cross-org line-FK and account-PUT reclassification tests. Require `costing_purchases_001` downgrade to refuse while any account override exists.

Review was read-only. I graded the contract at commit `1770558d` against the 8.1a baseline and installed xero_python 4.0.0; concurrent uncommitted implementation work was not graded as the deliverable.

VERDICT: gaps-found
