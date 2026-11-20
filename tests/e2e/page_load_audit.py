"""Collect paired navigation metrics from Chromium without changing test fixtures."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from tests.e2e.test_perf_budgets import REGISTRY, instrument_performance

METRICS = """async () => {
    const navigation = performance.getEntriesByType('navigation')[0];
    const resources = performance.getEntriesByType('resource');
    const lcp = await new Promise(resolve => {
        const observer = new PerformanceObserver(entries => {
            observer.disconnect();
            resolve(Math.round(entries.getEntries().at(-1).startTime));
        });
        observer.observe({ type: 'largest-contentful-paint', buffered: true });
        setTimeout(() => { observer.disconnect(); resolve(null); }, 150);
    });
    const sameOrigin = resources.filter(entry => new URL(entry.name).origin === location.origin);
    const largest = [...sameOrigin].sort((a, b) => b.transferSize - a.transferSize).slice(0, 5);
    return {
        ttfb_ms: Math.round(navigation.responseStart),
        lcp_ms: lcp,
        load_ms: Math.round(navigation.loadEventEnd),
        requests: sameOrigin.length + 1,
        transferred_bytes: navigation.transferSize + sameOrigin.reduce((sum, entry) => sum + entry.transferSize, 0),
        cached_resources: sameOrigin.filter(entry => !entry.transferSize && entry.decodedBodySize).length,
        largest: largest.map(entry => [new URL(entry.name).pathname, entry.transferSize]),
    };
}"""


def measure_page(browser, app_url, route, storage_state=None, *, label=None):
    report = os.environ.get("PAGE_LOAD_REPORT")
    if not report:
        return
    label = label or route
    selected = os.environ.get("PAGE_LOAD_ROUTES", "").split()
    if selected and label not in selected:
        return
    for sample in range(int(os.environ.get("PAGE_LOAD_SAMPLES", "3"))):
        with browser.new_context(
            base_url=app_url,
            ignore_https_errors=True,
            storage_state=storage_state,
            viewport={"width": 1440, "height": 900},
        ) as context:
            page = context.new_page()
            for cache in ("cold", "warm"):
                if cache == "warm":
                    page.goto("about:blank")
                path = urlsplit(route).path
                start = REGISTRY.count("GET", path)
                response = page.goto(route)
                final_path = urlsplit(page.url).path
                assert response and response.ok, f"{label}: {response.status if response else 'no response'}"
                assert final_path.rstrip("/") == urlsplit(route).path.rstrip("/"), (
                    f"{label} redirected away from the expected page"
                )
                page.wait_for_load_state("networkidle")
                metrics = page.evaluate(METRICS)
                query_samples = REGISTRY.since("GET", path, start)
                document_queries = query_samples[0]["queries"] if query_samples else None
                row = {
                    "route": label,
                    "sample": sample,
                    "cache": cache,
                    "document_queries": document_queries,
                    **metrics,
                }
                with Path(report).open("a", encoding="utf-8") as stream:
                    print(json.dumps(row), file=stream)


def audit_current_page(page, label, *, url=None):
    """Measure a page reached using the state built by an existing browser journey."""
    if not os.environ.get("PAGE_LOAD_REPORT"):
        return
    target = url or page.url
    location = urlsplit(page.url)
    origin = f"{location.scheme}://{location.netloc}"
    with contextmanager(instrument_performance)():
        measure_page(page.context.browser, origin, target, page.context.storage_state(), label=label)
