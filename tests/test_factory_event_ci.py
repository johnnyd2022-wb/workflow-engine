"""ci/factory_event.sh: every CI job reports its end state to Event Factory, safely."""

import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ci" / "factory_event.sh"
CALL = "sh ci/factory_event.sh || true"


def run(env, received=None):
    server = None
    if received is not None:

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                received.append((dict(self.headers), json.loads(self.rfile.read(length))))
                self.send_response(202)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.handle_request, daemon=True).start()
        env = {**env, "FACTORY_EVENTS_URL": f"http://127.0.0.1:{server.server_port}/v1/webhooks/gitlab"}
    try:
        return subprocess.run(["sh", str(SCRIPT)], env={"PATH": "/usr/bin:/bin", **env}, timeout=30)
    finally:
        if server:
            server.server_close()


JOB = {"CI_PROJECT_ID": "123", "CI_JOB_ID": "5", "CI_PIPELINE_ID": "88", "CI_JOB_STATUS": "failed"}


def test_posts_ids_and_status_with_the_factory_token_only():
    received = []
    env = {**JOB, "FACTORY_CI_TOKEN": "ci-signal-secret", "CI_JOB_TOKEN": "gitlab-job-credential"}
    assert run(env, received).returncode == 0
    [(headers, body)] = received
    assert headers["X-Factory-CI-Token"] == "ci-signal-secret"
    assert body == {"project_id": 123, "job_id": 5, "pipeline_id": 88, "status": "failed"}
    # The GitLab job credential never leaves CI.
    assert "gitlab-job-credential" not in json.dumps([dict(headers), body])


def test_does_nothing_without_a_token_and_never_fails_the_job():
    received = []
    assert run(JOB, received).returncode == 0
    assert received == []
    unreachable = {**JOB, "FACTORY_CI_TOKEN": "x", "FACTORY_EVENTS_URL": "http://127.0.0.1:9/nothing"}
    assert subprocess.run(["sh", str(SCRIPT)], env={"PATH": "/usr/bin:/bin", **unreachable}, timeout=30).returncode == 0


def test_every_job_reports_its_end_state():
    for config in (ROOT / ".gitlab-ci.yml", ROOT / "terraform" / "ci.yml"):
        text = config.read_text()
        # A job-level after_script replaces the default one, so each must carry the call itself.
        for block in re.split(r"\n(?=\S)", text):
            if re.search(r"^\s+after_script:", block, re.M):
                assert CALL in block, f"{config.name}: {block.splitlines()[0]} drops the Factory event"
    default = re.search(r"^default:\n((?:  .*\n)+)", (ROOT / ".gitlab-ci.yml").read_text(), re.M)
    assert default and CALL in default.group(1)
