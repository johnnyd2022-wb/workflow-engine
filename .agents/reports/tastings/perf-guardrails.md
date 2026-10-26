# Tastings performance guardrails

New feature-scoped measure list in `.agents/perf/budgets.json` binds subscribed `/crm/tastings`, list, choices, pool and event detail to existing query/backend/LCP budgets. Five real browser performance cases live with their one session-scoped subscribed fixture in `tests/e2e/test_tastings_page.py`; each requires200 rather than silently skipping an unavailable feature. No ceiling was raised.

UTC final9 run: list7 queries/7.5ms, choices8/9.6ms, pool6/6.4ms, detail10/10.4ms; page9 queries/8.7ms and132ms LCP. All ceilings pass. Page exceeds the shared advisory5-query budget; it stays visible as an advisory and below the20-query ceiling. These are warmed local fixture medians, not production latency guarantees. A separate populated seven-event seed measured stable bounded queries across five reads. Maximum200-event/50-choice load scaling was not benchmarked.

Planning validation's per-line source lookups were replaced with batched same-org queries after the existing Semgrep N+1 rule flagged them. Events are bounded to200 over93days, stock/people/pool to50 per page, allocations to20. List rep names and detail source facts are batched; linked CRM tasting relationships use select-in loading.

The independent evaluator injected above-ceiling API query and page LCP values; both failed. Scoped final JSON is stored alongside this report; global unrelated performance report is preserved.

VERDICT: clean
