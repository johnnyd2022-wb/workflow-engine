# Tastings test reconciliation

The original builder supplied the feature tests; root added regressions for empty booking/dispatch, coalesced prior-removal rejection, and separate blank/nonblank outcome notes. Browser tests exercise stock-first searching and the full dispatch/partial-bottle/reuse flow at desktop and phone sizes, linked calendar navigation, boosted revisit and Back, errors/filter clearing, and nine temporary concept width checks. Subscription-aware performance tests in the same fixture-owning module consume the Tastings feature measure list, using the existing server-side query/duration instrumentation and default written budgets. It deliberately asserts200 rather than skipping an unmeasurable subscribed route.

Shared surfaces affected: excise drafts/lodgement and source-CCA observations, generic CRM task update/delete and Core lane writes, page navigation, access policy and selected-site staff endpoint coverage. Related suites are included in the final root regression run. Existing tests were not removed or weakened. The browser journey now scopes a pool row by the exact dispatch lot ID because running the flow at both widths creates two distinct lots of the same product; both must independently retain550mL.

`.agents/test-map.md` gains the Tastings flow. `scripts/test_map_check.py --json` was run before edits; it already reported five dangling old flow rows plus unlisted existing suites. This change does not claim to resolve unrelated map debt. The final evaluator is independent of both backend and root test authors.

VERDICT: clean
