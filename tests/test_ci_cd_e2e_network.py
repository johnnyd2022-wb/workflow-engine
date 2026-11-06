"""cd_e2e's browser must not share the Docker host's network namespace.

With --network host, Chromium saw every bridge another job created or removed on the shared
Docker engine and aborted in-flight loads with net::ERR_NETWORK_CHANGED, for Google Fonts and
localhost alike (main 2026-10-27, 10-28, 11-06; PH-NETCHANGE). On the app's own bridge network
it sees only its own interface.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _job(name: str) -> str:
    text = (ROOT / ".gitlab-ci.yml").read_text()
    return re.split(r"(?m)^[A-Za-z_][\w-]*:\n", text.split(f"\n{name}:\n", 1)[1], maxsplit=1)[0]


def test_cd_e2e_runs_its_browser_on_the_apps_network_not_the_hosts():
    job = _job("cd_e2e")
    run = job.split('docker run --detach --name "$CD_E2E_CONTAINER"', 1)[1].split("sleep infinity", 1)[0]
    assert "--network host" not in run
    assert "--network workflow-observability" in run
    assert "host.docker.internal:127.0.0.1" not in job
    assert 'E2E_BASE_URL="https://workflow-engine-test:8001"' in job


def test_the_app_container_it_reaches_is_on_that_network_under_that_name():
    script = (ROOT / "scripts" / "deploy_test_simple.sh").read_text()
    assert "--name workflow-engine-test\n" in script
    assert "--network workflow-observability\n" in script
