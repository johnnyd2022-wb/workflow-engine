# Tastings build-review follow-up

Date: 2026-10-27. Scope: the three findings in `build-review.md`, after root's patches. Read-only grader; no source edits.

- **Prior-removal ambiguity: closed.** `_source_basis` now loads at most two candidate out-transfers and explicitly rejects anything other than one attributable covering removal with `TastingError` status400. It does not choose an arbitrary historical row or manufacture a second removal. Both four-bottle and one-bottle coalesced histories are covered by regression tests, including unchanged source quantity and zero pool lots after rejection. Aggregate attribution remains deliberately unsupported and is clearly rejected.
- **Stock search replacing people: closed.** JS `choices()` updates only stock, while `people()` has separate query, pagination, request token and option state. The API accepts independent `people_q`/`people_offset` and reports separate continuation flags. People search includes name/email; stock search no longer removes the Rep/Customer choices. Final browser coverage remains the root's E2E stage.
- **Planning-note loss: closed.** `Tasting.outcome_notes` is a separate additive model/migration field; finalisation writes it and retains `notes`. Both fields are serialized and separately rendered. Blank/nonblank outcome tests also replay the identical finalisation and prove stock is consumed only once.

Independent validation: `PYTHONPATH=. ENVIRONMENT=test uv run python /tmp/tastings_pytest.py tests/test_tastings.py -q -p no:cacheprovider` completed **29 passed**, one existing Flask-Limiter warning, 5.21s. This wrapper uses only `workflow-engine-test_tastings_build`. No migration or shared database change was performed by the reviewer.

VERDICT: clean
