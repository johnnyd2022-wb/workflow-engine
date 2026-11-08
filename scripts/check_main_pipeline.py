"""Fail an MR gate while the default branch has no successful pipeline.

A red main would otherwise block the very merge request that repairs it. A merge request
labelled ``fixes-main`` passes this gate while main is red; every other job still has to
pass. The label is read when the pipeline is created, so add it before running the pipeline.

main mid-pipeline is not main red. When the newest main commit's pipeline is still running
(or not created yet, right after a merge), the gate walks back along main's first parents to
the newest commit whose main pipeline has finished, and that one decides. Before this, every
merge request whose pipeline started while main was building failed here and needed a whole
new pipeline (docs: .agents/reports/ci/pipeline-health-2026-11.md).
"""

import json
import os
import ssl
import sys
from http.client import HTTPSConnection
from urllib.parse import quote, urlsplit

FIX_LABEL = "fixes-main"
# Statuses that mean "not decided yet". Anything else is a finished verdict.
IN_PROGRESS = {"created", "waiting_for_resource", "preparing", "pending", "running", "scheduled"}
# How many first-parent commits to walk back past in-progress or pipeline-less commits.
MAX_WALK = 10


class GateError(Exception):
    pass


def _repairs_main() -> bool:
    labels = os.environ.get("CI_MERGE_REQUEST_LABELS", "")
    return FIX_LABEL in {label.strip() for label in labels.split(",")}


def _commit(server_host, port, base_path, project_id, ref, job_token) -> dict:
    path = f"{base_path}/projects/{quote(project_id, safe='')}/repository/commits/{quote(ref, safe='')}"
    connection = HTTPSConnection(server_host, port, timeout=20, context=ssl.create_default_context())
    try:
        connection.request("GET", path, headers={"JOB-TOKEN": job_token})
        response = connection.getresponse()
        if response.status != 200:
            raise GateError(f"HTTP {response.status}")
        return json.load(response)
    except (OSError, TimeoutError, ValueError) as exc:
        raise GateError(str(exc)) from exc
    finally:
        connection.close()


def _blocked(target: str) -> int:
    if _repairs_main():
        print(f"{target} is not green, but this merge request is labelled {FIX_LABEL!r}: allowed through to repair it.")
        return 0
    print(
        f"Merge blocked until the latest {target} pipeline succeeds. "
        f"Label the merge request that repairs {target} {FIX_LABEL!r}.",
        file=sys.stderr,
    )
    return 1


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
    base_path = parsed.path.rstrip("/")

    ref = target
    for step in range(MAX_WALK + 1):
        try:
            commit = _commit(server_host, parsed.port, base_path, project_id, ref, job_token)
        except GateError as exc:
            print(f"Could not inspect {target} pipeline: {exc}", file=sys.stderr)
            return 1
        sha = commit.get("id")
        pipeline = commit.get("last_pipeline") or {}
        ours = pipeline.get("sha") == sha and pipeline.get("ref") == target
        status = pipeline.get("status") if ours else None
        label = "head" if step == 0 else f"head~{step}"
        print(f"{target} {label} {sha[:8] if isinstance(sha, str) else '?'}: pipeline {status or 'missing'}")
        if status == "success":
            if step:
                print(f"{target} head is still building; its newest finished pipeline is green, so this gate passes.")
            return 0
        if status is not None and status not in IN_PROGRESS:
            return _blocked(target)
        parents = commit.get("parent_ids") or []
        if not parents:
            break
        ref = parents[0]
    print(f"No finished {target} pipeline in the last {MAX_WALK + 1} commits.", file=sys.stderr)
    return _blocked(target)


if __name__ == "__main__":
    raise SystemExit(main())
