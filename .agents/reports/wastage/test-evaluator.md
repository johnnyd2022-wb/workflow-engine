# TEST-EVALUATOR: wastage
date: 2026-08-11
engine: codex exec, model gpt-5.6-sol, effort high, --sandbox read-only
grader_engine: codex (independent, per preflight)

## Note on report authorship
The grader's own sandbox rejected its attempt to write this file
(`patch rejected: writing is blocked by read-only sandbox`) — the exact scenario
`.agents/verification-chain.md` §5 documents: a `--sandbox read-only` Codex stage cannot
write its own report file, and correctly declined to route around the boundary rather than
finding another writable channel. This file is the orchestrator's transcription of the
grader's verbatim findings from its own final messages, per that section's instructions.
Codex confirmed at the end of its run that it made no code edits (`git status --porcelain`
showed no changes attributable to it beyond the orchestrator's own prior work already in
the tree) — it is read-only by construction (sandboxed) and by conduct (it explicitly
tried, was blocked, and stopped rather than working around it).

Scope was the 11 tests this session added: 4 in `tests/test_wastage.py`, 7 in the new
`tests/e2e/test_inventory_dispose_pages.py`. The grader's sandbox had no PostgreSQL or
browser access (network-restricted), so it could not execute the live mutation
spot-checks the prompt requested for most tests — it graded 9 of the 11 by static
inspection ("non-tautological claims that match their names") and found two concrete,
actionable defects by reading the assertions against the route logic directly.

## Findings (verbatim from Codex, lightly reformatted)

**F1 — the cross-tenant test's quantity-leak assertion checked the wrong value.**
> The highest-value test has a concrete static defect: it seeds on-hand `42` and previews
> wasting `1`, but the page discloses the computed remainder (`41`), not the original
> on-hand quantity. Therefore the `"42" not in disclosed` assertion would remain green
> even if quantity leaked through the current preview path. The unique marker-name
> assertion still catches a full org-filter removal, but the test's explicit
> quantity-non-disclosure claim is not honestly proven.

Test: `test_org_b_cannot_preview_dispose_org_a_item` (`tests/e2e/test_inventory_dispose_pages.py`).
Root cause: `inventory_dispose_confirm` renders `remaining_dec = current_qty_dec -
quantity_wasted_dec` (backend.py:770-777), never the raw on-hand quantity — so a test
seeding 42 and checking for absence of "42" was checking for a string the page never
prints regardless of whether the leak exists.

**F2 — the happy-path remainder assertion could coincidentally pass on broken code.**
> A second weak assertion is in the happy-path remainder test: `to_contain_text("7")`
> searches the entire content region, which also includes an 8-character random
> hexadecimal suffix in the item name. If the remainder computation were removed or
> inverted, the assertion could still pass whenever that random suffix contains `7`
> (about 40% probability).

Test: `test_dispose_confirm_computes_remaining_quantity`.

## Remediation (this review, after the grader's sandbox blocked its own write)

**F1** — `assert "42" not in disclosed` replaced with `assert "41" not in disclosed` (the
value actually rendered on a leak), plus a new sanity assertion that the legitimate
owner's own preview of the identical request *does* show "41" — proving the check target
is real, not just absent-by-construction. Mutation-verified live: wrapped the item lookup
in `unscoped()` with the explicit org filter also removed (a true leak — the earlier,
narrower mutation of just the explicit `.filter()` alone was silently caught by this
branch's global `TenantScoped` filter, so it doesn't exercise a real leak by itself).
Reran the test: **failed**, as expected. Restored the code (`git diff --stat` confirmed
only the two access_denied blocks from the observability stage remain). Reran the full
file: **7/7 green**.

**F2** — `to_contain_text("7")` replaced with a sentence-anchored regex,
`re.compile(r"remaining quantity will be\s*\n?\s*7\b")`, which cannot match inside the
item name's hex suffix.

## Verdict on the other 9 tests
Codex's static pass found no tautologies, weakened asserts, or name/behavior mismatches
in: `test_dispose_page_preselects_only_the_requested_item_ids`,
`test_dispose_confirm_rejects_non_finite_quantity`,
`test_dispose_confirm_rejects_negative_quantity`,
`test_dispose_confirm_missing_item_id_shows_error`,
`test_dispose_confirm_nonexistent_item_shows_error`,
`test_wastage_rejects_wasting_from_zero_quantity_item`,
`test_wastage_rejects_non_string_quantity_unit`,
`test_list_wastage_rejects_malformed_inventory_item_id`,
`test_list_wastage_filters_by_inventory_item_id`.

(The two observability regression tests added in the same session,
`test_wastage_cross_org_rejection_emits_access_denied` and
`test_dispose_confirm_cross_org_item_emits_access_denied`, were added after this grading
run and were independently mutation-tested live by the orchestrator — see
`.agents/reports/wastage/observability.md` — rather than re-sent to the grader, since
they follow the exact `caplog`/`access_denied` pattern already established and verified
elsewhere in this codebase.)

## Post-fix confirmation
```
pytest tests/e2e/test_inventory_dispose_pages.py tests/test_wastage.py -q
38 passed
```
Flake check on the e2e file: 5/5 runs green across this session (3 pre-fix, 2 post-fix).

VERDICT: valid
