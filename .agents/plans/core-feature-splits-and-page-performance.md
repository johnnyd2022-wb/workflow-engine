# Core feature ownership and page performance

This extends the [feature-slicing plan](feature-slicing-plan.md). Keep Core's public URL, endpoint, tenant access, request and response contracts while moving implementation into the feature that owns it. The [feature index](../feature-index.md) is the route ownership ledger.

## Architecture merge requests

| Order | Slice | Scope and acceptance |
| --- | --- | --- |
| 1 | Inventory | Move stock routes, CSV import, suppliers, locations, stocktakes, holds and their dedicated UI. Keep stock writes, checks and valuation behavior intact. |
| 2 | Process design | Move workflow definition and editor routes and UI. Preserve the process DAG, templates, draft navigation and saved workflow semantics. |
| 3 | Execution | Move execution and step recording routes and UI. Preserve idempotency, stock writes, execution history and shared model contracts. |
| 4 | Traceability | Move source maps, traversal and trace UI. Pin forward and backward lineage results and org scoping. |
| 5 | Core composition | Review remaining shell and feature-level dependencies after the moves. Replace private cross-feature imports with explicit public entry points where the caller has a legitimate dependency. |

Use one MR per slice and keep code movement separate from subsequent behavior or performance changes. A slice owns its HTTP entry points and dedicated templates and assets. Use a standalone Blueprint when its endpoint namespace already belongs to the feature. Attach routes that have an established `core.*` namespace through Core composition. Keep cross-feature entity models, schema and transactions stable during the refactor. Use the allowlisted asset registry for existing public asset URLs and test that only intended assets are exposed.

Each MR updates the route ledger, compares the composed URL map with its base and verifies generated OpenAPI. Run domain, API, tenant isolation, JS and browser journeys for the changed slice. Run the full suite across the complete split, with failures investigated on the base if attribution is unclear. Extend checked ownership or import rules where a concrete regression can be detected with low false-positive risk.

## Page performance

1. Reconcile the live Flask page surface and the mobile page audit inventory. Identify canonical pages, legitimate redirects, parameter fixtures, feature entitlements and transient login or workflow states. Inventory public and signed-in pages, including the portal, plus interaction-dependent UI where opening data is part of page readiness.
2. Record browser-cold and browser-warm runs as pairs. Use fresh browser contexts with session cookies restored for the cold run. Navigate again with caching enabled in the same context for the warm run. Keep app processes, seed data, viewport and browser versions fixed. Label measurements in an already-running app as browser-cold. Report server cold-start separately if measured.
3. Save sample counts, TTFB, LCP, transfer sizes, request and query counts, and ready-state timings where the page exposes a readiness assertion. Track navigation errors and unavailable variants separately. Use a seeded small fixture for coverage, then exercise expensive surfaces with representative data volumes. Keep timing comparisons on the same runner.
4. Publish results by page, with the largest measured opportunity first on each page. Prioritize shared fixes by total impact across pages, and use focused before-and-after runs to verify savings and functional equivalence.
5. Add regression checks alongside each fix. Favor request counts, query ceilings, asset inclusion and bytes as stable CI checks. Reuse current Semgrep rules for known static patterns and the existing budget runner for repeatable runtime checks. Keep noisy browser timings advisory unless an existing generous ceiling already applies.

The [20 November page load assessment](../../docs/page-load-assessment-2026-11-20.md) records the measurements, shipped changes under review and remaining tuning priorities.
