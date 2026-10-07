"""Production observability switches must not read "on" for a pipeline that cannot work.

Findings-Index: 2b86fa07 -- ``docs/production-bringup-checklist.md`` §3. ``prod.ini`` set
``otel_enabled`` / ``rum_enabled`` to true while pointing every collector at ``localhost``. Inside the
production container ``localhost`` is the container itself (and ``:8000`` is the app), so nothing
could ever be collected.

It was inert, not live: tracing, metrics, the OTLP log handler and the ``/telemetry`` proxy all
also require the separate ``grafana_data_enabled`` / ``posthog_data_enabled`` consent flags, which
``prod.ini`` leaves off. These tests pin the honest shape instead: a master switch may only be on
alongside a collector that is not loopback, so turning a pipeline on later forces a real endpoint
to be chosen in the same change.
"""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.utils.config_loader import Config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "app" / "config"
SHIPPED_PRODUCTION_CONFIGS = ("prod.ini", "prod.ini.template")


def _is_loopback(url: str) -> bool:
    """True for a collector URL that cannot be reached from outside its own container."""
    host = (urlsplit(url.strip()).hostname or "").lower()
    return not host or host in {"localhost", "::1", "0.0.0.0"} or host.startswith("127.")


def _config_for(name: str) -> Config:
    """A Config over one shipped file, so absent keys resolve through the real code defaults
    (``otel_enabled`` defaults on and every collector defaults to ``localhost``)."""
    cfg = Config.__new__(Config)
    cfg.environment = "production"
    cfg.config = ConfigParser()
    assert cfg.config.read(CONFIG_DIR / name), f"{name} not found"
    return cfg


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:4317",
        "http://127.0.0.1:8000",
        "http://127.0.0.2",
        "http://[::1]:12347",
        "http://0.0.0.0:1",
        "",
    ],
)
def test_loopback_detector_flags_unreachable_collectors(url):
    assert _is_loopback(url)


@pytest.mark.parametrize("url", ["https://otel.example.com", "http://collector.internal:4317", "http://10.0.0.5:4317"])
def test_loopback_detector_accepts_real_collectors(url):
    assert not _is_loopback(url)


@pytest.mark.parametrize("name", SHIPPED_PRODUCTION_CONFIGS)
def test_otel_is_only_on_with_a_reachable_collector(name):
    cfg = _config_for(name)

    if cfg.otel_enabled:
        assert not _is_loopback(cfg.otel_exporter_endpoint), (
            f"{name}: otel_enabled = true but otel_exporter_endpoint is {cfg.otel_exporter_endpoint!r}, "
            "which is the container itself in production. Point it at a real collector or set otel_enabled = false."
        )


@pytest.mark.parametrize("name", SHIPPED_PRODUCTION_CONFIGS)
def test_rum_is_only_on_with_reachable_upstreams(name):
    cfg = _config_for(name)

    if cfg.rum_enabled:
        upstreams = {
            "rum_faro_upstream": cfg.rum_faro_upstream,
            "rum_posthog_capture_upstream": cfg.rum_posthog_capture_upstream,
            "rum_posthog_replay_upstream": cfg.rum_posthog_replay_upstream,
            "rum_posthog_feature_flags_upstream": cfg.rum_posthog_feature_flags_upstream,
            "rum_posthog_upstream": cfg.rum_posthog_upstream,
        }
        unreachable = {key: url for key, url in upstreams.items() if _is_loopback(url)}
        assert not unreachable, (
            f"{name}: rum_enabled = true but these upstreams are loopback (the container itself, or the app on "
            f":8000) in production: {unreachable}. Point them at real collectors or set rum_enabled = false."
        )
