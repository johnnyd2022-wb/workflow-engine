# Sales HTML / JavaScript review — 2026-10-11

Scope: uncommitted `feat/sales-design`, Sales overview template, component and page stylesheet, with the Sales design plan. Read html-review, js-review and autonomy instructions. This is a code review; the author owns the screenshot loops and full verification chain.

## Findings resolved during review

1. Nested task action keyboard activation: the new task-card Enter/Space handlers intercepted events from **Open in Tasks**, cancelling native activation and collapsing its parent. The author added `@keydown.stop` to the inner action and a browser navigation regression test. Independent mutation removing this stop makes that test fail.
2. Canvas assertion initially compared only CSS width, which did not reliably guard the canvas backing width. The author now asserts `canvas.width / devicePixelRatio` against actual parent width. Independently forcing width 600 fails all three sampled 1920-wide concepts.
3. Chart observer cleanup: late request completion could re-observe a detached canvas after `destroy()`. The author moved the connected-root check before observer registration at `overview.js:742`. Static verification confirms detached roots return before observation.

## Preserved behavior and boundaries

The template still extends the shared SPA shell and uses the shared section head. Header actions are supplied through its existing block. Page styles are scoped; shared tabs and sidebar are untouched. Task rendering uses `x-text`, API calls continue through CRMAPI, and no new backend, tenant filter or money calculation is introduced. Local/session storage contains UI preferences only. Charts use root-scoped lookups and disconnected-root guards; observers disconnect on component destruction. Existing widget configuration, stored order, Top N, invoice actions and date filtering remain available.

Saved-order tests exercise actual DOM order and boosted return, rather than only a local-storage write. API rendering tests deliberately replace read responses; they prove presentation/error handling, not backend authorization or revenue correctness.

Nonblocking limits: full modal accessibility and the local-time end-of-month implementation predate this diff. The final dark primary foreground uses `--ui-surface-subtle` against the shared accent, and its light foreground uses `--text-inverse`; no new palette literal remains. The fixed 100 ms canvas wait could later become an auto-retrying assertion if runtime flake evidence warrants it.

Verdict: **clean after the fixes above**, subject to the author's full checks and screenshot sign-off. No unresolved code-review blocker identified.
