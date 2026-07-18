"""Performance budgets for core pages and API routes. Owned by the perf-guardrails skill.

Budgets live in .agents/perf/budgets.json; results land in
.agents/reports/perf/last-run.json for scripts/perf_triage.py to fold into the priority
checklist. Two tiers per spec D2 (.agents/specs/playwright-e2e.md):

- **ceiling** breaches FAIL (blocking): they are generous enough that only a real
  regression trips them — an N+1 explosion, a hung query, a render stall.
- **budget** breaches WARN and are reported (advisory): wall-clock on a dev laptop is
  too noisy to block on, and a flaky gate gets disabled within a month.

What is measured, and why these measures:

- **backend_ms** — server-side, from Flask's request_started to request_finished inside
  the app process (the E2E server boots in-process, tests/e2e/conftest.py:app_url), so
  TLS handshakes and client scheduling never pollute the number. Median of 5 after a
  warmup request.
- **queries** — DB statements per request via a SQLAlchemy before_cursor_execute
  listener. Fully deterministic: the runtime twin of .semgrep/rules/performance.yml's
  static N+1 rules. Max over samples, because a query count that varies across identical
  requests is itself a smell.
- **lcp_ms** — Chromium largest-contentful-paint, warm cache, median of 3 navigations.
  A local regression tripwire only; real-user LCP truth is the Faro RUM web-vitals
  stream (docs/observability-local-dev.md).
"""

from __future__ import annotations

import json
import statistics
import threading
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUDGETS_FILE = REPO_ROOT / ".agents" / "perf" / "budgets.json"
REPORT_FILE = REPO_ROOT / ".agents" / "reports" / "perf" / "last-run.json"

pytestmark = [pytest.mark.e2e, pytest.mark.perf]

BUDGETS = json.loads(BUDGETS_FILE.read_text(encoding="utf-8"))

WARMUP = 1
API_SAMPLES = 5
PAGE_SAMPLES = 3

# Resolves after the last LCP entry the observer has seen; the timeout is settle time for
# late entries (SPA pages fetch data after `load` and may repaint their largest element).
_LCP_JS = """
() => new Promise(resolve => {
  let lcp = 0;
  new PerformanceObserver(list => {
    for (const entry of list.getEntries()) lcp = Math.max(lcp, entry.startTime);
  }).observe({type: 'largest-contentful-paint', buffered: true});
  setTimeout(() => resolve(Math.round(lcp)), 800);
})
"""


def _limits(route: str, kind: str, metric: str) -> dict:
    merged = dict(BUDGETS["defaults"][kind].get(metric, {}))
    merged.update(BUDGETS.get("overrides", {}).get(route, {}).get(metric, {}))
    return merged


# --------------------------------------------------------------------------------------
# Instrumentation: per-request server duration + DB statement count
# --------------------------------------------------------------------------------------


class _Registry:
    """Samples keyed by (method, path), recorded inside the app process."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.samples: dict[tuple[str, str], list[dict]] = {}

    def record(self, method: str, path: str, ms: float, queries: int) -> None:
        with self.lock:
            self.samples.setdefault((method, path), []).append({"ms": ms, "queries": queries})

    def count(self, method: str, path: str) -> int:
        with self.lock:
            return len(self.samples.get((method, path), []))

    def since(self, method: str, path: str, start: int) -> list[dict]:
        with self.lock:
            return list(self.samples.get((method, path), [])[start:])


REGISTRY = _Registry()
RESULTS: list[dict] = []


@pytest.fixture(scope="session")
def perf_instrumentation(app_url):
    """Attach Flask signals and a SQLAlchemy cursor listener; write the report on teardown.

    Safe to attach after boot: signals and engine events bind to global objects, not to
    Flask's setup phase, so this never hits the setup-after-first-request guard. Counters
    live on `g`, so concurrent requests on the threaded dev server cannot cross-count.
    """
    from flask import g, has_request_context, request, request_finished, request_started
    from sqlalchemy import event

    from app.core.db import engine

    def _started(sender, **extra):
        g._perf_t0 = time.perf_counter()
        g._perf_queries = 0

    def _cursor(conn, cursor, statement, parameters, context, executemany):
        if has_request_context() and hasattr(g, "_perf_queries"):
            g._perf_queries += 1

    def _finished(sender, response, **extra):
        t0 = getattr(g, "_perf_t0", None)
        if t0 is None:
            return
        ms = (time.perf_counter() - t0) * 1000.0
        REGISTRY.record(request.method, request.path, ms, getattr(g, "_perf_queries", 0))

    request_started.connect(_started)
    request_finished.connect(_finished)
    event.listen(engine, "before_cursor_execute", _cursor)
    try:
        yield REGISTRY
    finally:
        request_started.disconnect(_started)
        request_finished.disconnect(_finished)
        event.remove(engine, "before_cursor_execute", _cursor)
        if RESULTS:
            REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
            REPORT_FILE.write_text(
                json.dumps(
                    {
                        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "budgets_file": str(BUDGETS_FILE.relative_to(REPO_ROOT)),
                        "results": sorted(RESULTS, key=lambda r: r["route"]),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )


# --------------------------------------------------------------------------------------
# Evaluation: ceiling blocks, budget warns (spec D2's two tiers)
# --------------------------------------------------------------------------------------


def _evaluate(route: str, kind: str, metrics: dict) -> None:
    over_budget, over_ceiling = [], []
    for metric, value in metrics.items():
        if value is None:
            continue
        lim = _limits(route, kind, metric)
        if lim.get("ceiling") is not None and value > lim["ceiling"]:
            over_ceiling.append(f"{metric}={value:.0f} > ceiling {lim['ceiling']}")
        elif lim.get("budget") is not None and value > lim["budget"]:
            over_budget.append(f"{metric}={value:.0f} > budget {lim['budget']}")
    RESULTS.append(
        {
            "route": route,
            "kind": kind,
            "metrics": {k: (round(v, 1) if v is not None else None) for k, v in metrics.items()},
            "over_budget": over_budget,
            "over_ceiling": over_ceiling,
        }
    )
    if over_ceiling:
        pytest.fail(f"{route}: {'; '.join(over_ceiling)} — a ceiling breach is a real regression (blocking tier)")
    if over_budget:
        warnings.warn(f"{route} over budget (advisory, non-blocking): {'; '.join(over_budget)}", stacklevel=1)


# --------------------------------------------------------------------------------------
# Measurements
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", BUDGETS["measure"]["api"])
def test_api_perf_budget(perf_instrumentation, logged_in_page, route):
    page = logged_in_page
    start = REGISTRY.count("GET", route)
    for _ in range(WARMUP + API_SAMPLES):
        resp = page.request.get(route)
        if resp.status >= 400:
            pytest.skip(
                f"{route} returned {resp.status} — not measurable as the logged-in user; "
                "route correctness belongs to the main E2E suite, not the perf tier"
            )
    samples = REGISTRY.since("GET", route, start)[WARMUP:]
    assert samples, f"no server-side samples recorded for {route} — instrumentation is broken"
    _evaluate(
        route,
        "api",
        {
            "backend_ms": statistics.median(s["ms"] for s in samples),
            "queries": max(s["queries"] for s in samples),
        },
    )


@pytest.mark.parametrize("route", BUDGETS["measure"]["pages"])
def test_page_perf_budget(perf_instrumentation, logged_in_page, route):
    page = logged_in_page
    resp = page.goto(route)  # warmup: fills the browser cache and any server-side caches
    if resp is not None and resp.status >= 400:
        pytest.skip(
            f"{route} returned {resp.status} — not measurable as the logged-in user; "
            "route correctness belongs to the main E2E suite, not the perf tier"
        )
    start = REGISTRY.count("GET", route)
    lcps: list[int] = []
    for _ in range(PAGE_SAMPLES):
        page.goto(route, wait_until="load")
        lcp = page.evaluate(_LCP_JS)
        if lcp:
            lcps.append(lcp)
    samples = REGISTRY.since("GET", route, start)
    assert samples, f"no server-side samples recorded for {route} — instrumentation is broken"
    _evaluate(
        route,
        "page",
        {
            "backend_ms": statistics.median(s["ms"] for s in samples),
            "queries": max(s["queries"] for s in samples),
            "lcp_ms": statistics.median(lcps) if lcps else None,
        },
    )
