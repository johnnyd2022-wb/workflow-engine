# TEST EVALUATION FOLLOW-UP — 2026-10-27

Scope: only the new `test_fractional_litre_line_keeps_unit_and_identity_after_second_stock_search` in `tests/e2e/test_tastings_page.py`, its added20L producer-stock fixture, and the corresponding selected-source metadata changes in `tastings.js`. The prior test evaluation remains applicable to the rest of the batch.

Static review: **valid**. The test selects a real same-org bulk item, enters the independently chosen0.5L quantity, performs a second stock search that excludes that item, and checks the retained canonical unit, product and batch against concrete fixture values. Native `checkValidity()` must remain true. A second bottled line is then selected and an actual create request must return201, with the bulk item's exact ID and0.5 canonical quantity in the returned allocations and its product in the displayed detail. No mock, skip, catch-all response assertion, assertion deletion or expected value recomputed through the implementation was introduced. Converting this particular exactly representable0.5 value to float does not widen the comparison.

The new fixture supplies positive, producer-owned finished opening stock in litres. It does not claim to dispatch that stock or establish its excise profile; this test is specifically about retaining editor metadata and successfully saving the plan after choices are replaced.

Source review: the selection handler clears previous source IDs and display metadata, then captures the newly selected item's name, batch and unit. A later render can restore its checked option and fractional unit step from that retained line when current search choices omit it. The request builder sends only source identity and quantity, keeping display metadata out of the authoritative API payload. These paths correspond directly to the assertions. This test does not claim to prove every possible subsequent source-switch transition.

Falsifiability evidence inspected: root's real pre-fix browser run `/home/johnny/.cache/tastings/fractional-before.log` fails this same test at native `checkValidity()` after the second search, with `assert False`; this is the actual reported regression rather than an unrelated setup failure. Root's full post-fix `/home/johnny/.cache/tastings/browser-final7.log` reports **20 passed**, three warnings,34.34s. Both logs were independently read; these browser executions were run by root, not repeated or represented as this evaluator's own execution. The concrete pre-fix red and corrected green supply the additional falsifiability evidence; no further backend mutation probe was needed for these presentation/editor changes.

No application, test or script was edited by this evaluator. Only this report was added. No unresolved test-validity finding.

VERDICT: valid

## Deterministic pytest collection follow-up

Independently inspected the final `tests/test_tastings.py` diff: only the two import-time `uuid4()` values in `test_validation_and_reference_isolation` were replaced by fixed, syntactically valid version4 UUID strings ending in0001 and0002. The same missing rep/contact reference rejection paths, test body, fixture and `pytest.raises(service.TastingError)` assertion remain unchanged. Randomness was not part of the behavior under test; deterministic values preserve the intended invalid-reference inputs while giving separate xdist collectors identical parameter IDs. Existing hostile-org reference coverage is unaffected. No assertion was weakened, no test skipped, and no source was edited by this evaluator. Root's fresh collection comparison and backend rerun are separate execution evidence; this note is a static independent review of the exact two-line change.

VERDICT: valid
