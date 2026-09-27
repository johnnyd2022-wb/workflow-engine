"""Fail an MR gate while the default branch has no successful pipeline."""

import json
import os
import ssl
import sys
from http.client import HTTPSConnection
from urllib.parse import quote, urlsplit


def main() -> int:
    try:
        api_url = os.environ["CI_API_V4_URL"]
        server_host = os.environ["CI_SERVER_HOST"]
        project_id = os.environ["CI_PROJECT_ID"]
        # Stacked MRs target feature branches, but the gate must always inspect main.
        target = os.environ["CI_DEFAULT_BRANCH"]
        job_token = os.environ["CI_JOB_TOKEN"]
    except KeyError as exc:
        print(f"Missing CI variable: {exc.args[0]}", file=sys.stderr)
        return 2

    parsed = urlsplit(api_url)
    if parsed.scheme != "https" or parsed.hostname != server_host or parsed.username:
        print("CI API must use HTTPS on the configured GitLab host.", file=sys.stderr)
        return 2
    path = (
        f"{parsed.path.rstrip('/')}/projects/{quote(project_id, safe='')}/repository/commits/{quote(target, safe='')}"
    )
    connection = HTTPSConnection(server_host, parsed.port, timeout=20, context=ssl.create_default_context())
    try:
        connection.request("GET", path, headers={"JOB-TOKEN": job_token})
        response = connection.getresponse()
        if response.status != 200:
            print(f"Could not inspect {target} pipeline: HTTP {response.status}", file=sys.stderr)
            return 1
        commit = json.load(response)
    except (OSError, TimeoutError, ValueError) as exc:
        print(f"Could not inspect {target} pipeline: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()

    pipeline = commit.get("last_pipeline") or {}
    sha = commit.get("id")
    status = pipeline.get("status")
    print(f"{target} {sha[:8] if isinstance(sha, str) else '?'}: pipeline {status or 'missing'}")
    if pipeline.get("sha") != sha or pipeline.get("ref") != target or status != "success":
        print(f"Merge blocked until the latest {target} pipeline succeeds.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
