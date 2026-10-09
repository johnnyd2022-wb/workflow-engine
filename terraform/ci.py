#!/usr/bin/env python3
"""Publish MR plans and apply only a reviewed, matching plan after merge."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = Path(__file__).resolve().parent.parent
STACK = REPO / "terraform/cloudflare"
ARTIFACTS = STACK / ".ci"
PLAN_JOB = "terraform_cloudflare_plan"
PLAN_MARKER = "<!-- workflow-engine:terraform-plan:cloudflare -->"


class GateError(RuntimeError):
    pass


class ArtifactRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise GateError("Artifact redirects must use HTTPS")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected:
            # Signed artifact storage URLs do not need the GitLab credential.
            for name in ("Private-token", "Job-token", "Authorization"):
                redirected.remove_header(name)
        return redirected


class GitLab:
    def __init__(self):
        self.base = os.environ["CI_API_V4_URL"].rstrip("/")
        parsed = urlsplit(self.base)
        if parsed.scheme != "https" or parsed.hostname != os.environ["CI_SERVER_HOST"] or parsed.username:
            raise GateError("GitLab API must use HTTPS on CI_SERVER_HOST")
        self.project = quote(os.environ["CI_PROJECT_ID"], safe="")
        self.token = os.environ["TERRAFORM_GITLAB_READ_TOKEN"]
        self.opener = build_opener(ArtifactRedirect())

    def fetch(self, path, *, raw=False, method="GET", payload=None):
        headers = {"PRIVATE-TOKEN": self.token}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        req = Request(
            f"{self.base}/projects/{self.project}" + (f"/{path}" if path else ""),
            headers=headers,
            data=data,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=30) as response:
                data = response.read()
        except HTTPError as error:
            raise GateError(f"GitLab lookup failed: HTTP {error.code}") from None
        return data if raw else json.loads(data)

    def all(self, path):
        items = []
        for page in range(1, 101):
            separator = "&" if "?" in path else "?"
            batch = self.fetch(f"{path}{separator}{urlencode({'per_page': 100, 'page': page})}")
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise GateError("GitLab result pagination exceeded 10,000 entries")


def config_digest():
    files = [REPO / ".gitlab-ci.yml", REPO / "terraform/ci.yml", Path(__file__).resolve()]
    for folder in (STACK, REPO / "terraform/modules"):
        files.extend(
            path
            for path in folder.rglob("*")
            if path.is_file()
            and not any(part in {".terraform", ".ci", "__pycache__"} for part in path.parts)
            and path.suffix in {".tf", ".hcl", ".json"}
        )
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        digest.update(str(path.relative_to(REPO)).encode() + b"\0" + path.read_bytes() + b"\0")
    # These are IDs, not secrets, and ensure plan/apply target the same tenant.
    for key in ("TF_VAR_account_id", "TF_VAR_zone_id"):
        digest.update(key.encode() + b"\0" + os.environ[key].encode() + b"\0")
    return digest.hexdigest()


def summarize(plan):
    counts = {"create": 0, "update": 0, "delete": 0}
    changes = []
    for resource in plan.get("resource_changes", []):
        actions = resource["change"]["actions"]
        for action in actions:
            if action in counts:
                counts[action] += 1
        if actions != ["no-op"]:
            changes.append({key: resource[key] for key in ("address", "provider_name", "change")})
    outputs = {key: change for key, change in plan.get("output_changes", {}).items() if change["actions"] != ["no-op"]}
    canonical = json.dumps(
        {"resources": sorted(changes, key=lambda item: item["address"]), "outputs": outputs},
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    return counts, fingerprint


def redact(text):
    for key in ("PGPASSWORD", "CLOUDFLARE_API_TOKEN", "TERRAFORM_GITLAB_READ_TOKEN"):
        secret = os.getenv(key)
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def terraform(*args, accepted=(0,), log=None):
    process = subprocess.Popen(
        ["terraform", *args], cwd=STACK, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    with log.open("w") if log else open(os.devnull, "w") as output:
        for line in process.stdout:
            safe = redact(line)
            print(safe, end="", flush=True)
            output.write(safe)
    code = process.wait()
    if code not in accepted:
        raise GateError(f"terraform {args[0]} failed with exit code {code}")
    return code


def make_plan():
    ARTIFACTS.mkdir(exist_ok=True)
    terraform("fmt", "-check", "-recursive", str(REPO / "terraform"))
    terraform("init", "-input=false", "-no-color", "-lockfile=readonly")
    terraform("validate", "-no-color")
    planfile = ARTIFACTS / "plan.tfplan"
    try:
        terraform(
            "plan",
            "-input=false",
            "-no-color",
            "-lock-timeout=120s",
            "-detailed-exitcode",
            f"-out={planfile}",
            accepted=(0, 2),
            log=ARTIFACTS / "plan.txt",
        )
        result = subprocess.run(
            ["terraform", "show", "-json", str(planfile)], cwd=STACK, capture_output=True, text=True
        )
        if result.returncode:
            raise GateError("Could not read saved Terraform plan")
        counts, fingerprint = summarize(json.loads(result.stdout))
        return planfile, counts, fingerprint
    except BaseException:
        planfile.unlink(missing_ok=True)
        raise


def plan_comment(plan_text, counts, commit, job_url):
    text = redact(plan_text).strip()
    fence = "`" * max(3, max((len(match) + 1 for match in re.findall(r"`+", text)), default=3))
    return (
        f"{PLAN_MARKER}\n### Terraform plan — review required\n\n"
        f"**{counts['create']} to add, {counts['update']} to change, {counts['delete']} to destroy.**\n\n"
        f"Commit: `{commit}` · [Plan job]({job_url})\n\n"
        "Read the plan below, then **resolve this thread** to acknowledge your review. "
        "The MR stays blocked until this thread is resolved. "
        "Thread resolution is the plan approval. Merge once the pipeline is green; apply runs after merge.\n\n"
        f"{fence}text\n{text}\n{fence}\n"
    )


def publish_plan(api, counts):
    iid = os.environ["CI_MERGE_REQUEST_IID"]
    mr = api.fetch(f"merge_requests/{iid}")
    if (
        mr["state"] != "opened"
        or mr["diff_refs"]["head_sha"] != os.environ["CI_COMMIT_SHA"]
        or str((mr.get("head_pipeline") or {}).get("id")) != os.environ["CI_PIPELINE_ID"]
    ):
        raise GateError("MR or pipeline has changed; refusing to publish a stale plan")
    if not api.fetch("").get("only_allow_merge_if_all_discussions_are_resolved"):
        raise GateError("Enable the project's All threads must be resolved merge check before planning")
    body = plan_comment(
        (ARTIFACTS / "plan.txt").read_text(), counts, os.environ["CI_COMMIT_SHA"], os.environ["CI_JOB_URL"]
    )
    if len(body.encode()) > 900_000:
        raise GateError("Plan is too large for an MR thread; reduce the change scope")
    # Overview discussions are resolvable MR threads, unlike individual notes.
    discussion = api.fetch(f"merge_requests/{iid}/discussions", method="POST", payload={"body": body})
    note = discussion["notes"][0]
    if not note.get("resolvable") or note.get("resolved") or discussion.get("individual_note"):
        raise GateError("GitLab did not create an unresolved, resolvable plan thread")
    url = f"{mr['web_url']}#note_{note['id']}"
    # Retire only older plan threads published by this bot identity. The newest
    # thread remains unresolved, and only its ID is recorded in the review artifact.
    for older in api.all(f"merge_requests/{iid}/discussions"):
        notes = older.get("notes") or []
        root = notes[0] if notes else {}
        if (
            older["id"] != discussion["id"]
            and len(notes) == 1  # Keep conversations with replies for human resolution.
            and root.get("body", "").startswith(PLAN_MARKER + "\n")
            and (root.get("author") or {}).get("id") == note["author"]["id"]
            and root.get("resolvable")
            and not root.get("resolved")
            and root.get("created_at", "") <= note["created_at"]
        ):
            api.fetch(
                f"merge_requests/{iid}/discussions/{older['id']}/notes",
                method="POST",
                payload={"body": f"Superseded by the [new Terraform plan]({url}); review the new thread."},
            )
            api.fetch(f"merge_requests/{iid}/discussions/{older['id']}", method="PUT", payload={"resolved": True})
    print(f"Published unresolved Terraform plan thread in MR !{iid}: {url}")
    return {
        "discussion_id": discussion["id"],
        "note_id": note["id"],
        "note_digest": hashlib.sha256(note["body"].encode()).hexdigest(),
    }


def verify_plan_thread(discussion, review, approver_id, merged_at):
    if discussion.get("id") != review.get("discussion_id") or discussion.get("individual_note"):
        raise GateError("Plan review does not belong to the recorded discussion")
    notes = discussion.get("notes") or []
    note = next((item for item in notes if item.get("id") == review.get("note_id")), None)
    if not note or not note.get("resolvable"):
        raise GateError("The original plan review thread is missing")
    if hashlib.sha256(note["body"].encode()).hexdigest() != review.get("note_digest"):
        raise GateError("The published plan has changed; replan and review required")
    if not note.get("resolved") or any(item.get("resolvable") and not item.get("resolved") for item in notes):
        raise GateError("The final Terraform plan thread must be resolved before apply")
    if str((note.get("resolved_by") or {}).get("id")) != str(approver_id):
        raise GateError("The configured approver must resolve the final Terraform plan thread")
    if (
        not note.get("resolved_at")
        or not note.get("created_at")
        or datetime.fromisoformat(note["resolved_at"].replace("Z", "+00:00"))
        < datetime.fromisoformat(note["created_at"].replace("Z", "+00:00"))
    ):
        raise GateError("Plan thread resolution must follow publication of the final plan")
    if not merged_at or datetime.fromisoformat(note["resolved_at"].replace("Z", "+00:00")) > datetime.fromisoformat(
        merged_at.replace("Z", "+00:00")
    ):
        raise GateError("The final plan must be reviewed before the MR is merged")


def verify_review(mr, job, review, digest):
    head = mr["diff_refs"]["head_sha"]
    if mr["state"] != "merged" or mr["target_branch"] != os.environ["CI_DEFAULT_BRANCH"]:
        raise GateError("Apply requires a merged MR targeting the default branch")
    if int(mr["source_project_id"]) != int(os.environ["CI_PROJECT_ID"]):
        raise GateError("Fork merge requests cannot authorize apply")
    if job["status"] != "success" or job["commit"]["id"] != head:
        raise GateError("The latest MR plan job must have succeeded for its final commit")
    if (
        review.get("version") != 2
        or review.get("commit_sha") != head
        or review.get("job_id") != str(job["id"])
        or review.get("mr_iid") != str(mr["iid"])
    ):
        raise GateError("Reviewed plan does not belong to this MR's final commit and job")
    if review.get("config_digest") != digest:
        raise GateError(
            "Merged Terraform configuration differs from the reviewed configuration; replan/review required"
        )


def reviewed_manifest(api):
    sha = os.environ["CI_COMMIT_SHA"]
    requests = api.fetch(f"repository/commits/{quote(sha, safe='')}/merge_requests")
    candidates = [
        mr
        for mr in requests
        if mr.get("state") == "merged"
        and sha in (mr.get("merge_commit_sha"), mr.get("squash_commit_sha"))
        and mr["target_branch"] == os.environ["CI_DEFAULT_BRANCH"]
    ]
    if len(candidates) != 1:
        raise GateError("Apply requires exactly one merged MR associated with this commit")
    mr = api.fetch(f"merge_requests/{candidates[0]['iid']}")
    pipeline = mr.get("head_pipeline") or {}
    if (
        pipeline.get("source") != "merge_request_event"
        or pipeline.get("sha") != mr["diff_refs"]["head_sha"]
        or pipeline.get("status") != "success"
    ):
        raise GateError("The final MR pipeline must be successful and match the reviewed commit")
    jobs = api.all(f"pipelines/{pipeline['id']}/jobs")
    matches = [job for job in jobs if job["name"] == PLAN_JOB]
    if len(matches) != 1:
        raise GateError("The final MR pipeline must contain one Terraform plan job")
    job = matches[0]
    review = json.loads(api.fetch(f"jobs/{job['id']}/artifacts/terraform/cloudflare/.ci/review.json", raw=True))
    verify_review(mr, job, review, config_digest())
    discussion = api.fetch(f"merge_requests/{mr['iid']}/discussions/{review['discussion_id']}")
    verify_plan_thread(discussion, review, os.environ["TERRAFORM_APPROVER_ID"], mr.get("merged_at"))
    print(f"Verified reviewed MR !{mr['iid']} and plan job {job['id']}")
    return review


def check_current_main(api):
    head = api.fetch(f"repository/commits/{quote(os.environ['CI_DEFAULT_BRANCH'], safe='')}")
    if head["id"] != os.environ["CI_COMMIT_SHA"]:
        raise GateError("This pipeline has been superseded on main; refusing to apply old configuration")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "apply"))
    args = parser.parse_args()
    for key in ("PG_CONN_STR", "PGPASSWORD", "CLOUDFLARE_API_TOKEN", "TF_VAR_account_id", "TF_VAR_zone_id"):
        if not os.getenv(key):
            raise GateError(f"Runner credential missing: {key}; refresh it from KeePassXC")
    os.environ["TF_DATA_DIR"] = str(STACK / ".terraform")
    os.environ["TF_IN_AUTOMATION"] = "1"
    # CI uses the existing schema/indices; it never bootstraps or owns the backend.
    for key in ("PG_SKIP_SCHEMA_CREATION", "PG_SKIP_TABLE_CREATION", "PG_SKIP_INDEX_CREATION"):
        os.environ[key] = "true"
    if args.command == "plan":
        if os.environ.get("CI_PIPELINE_SOURCE") != "merge_request_event" or os.environ.get(
            "CI_MERGE_REQUEST_SOURCE_PROJECT_ID"
        ) != os.environ.get("CI_PROJECT_ID"):
            raise GateError("Plan runs only for same-project merge requests")
        if os.environ.get("CI_MERGE_REQUEST_EVENT_TYPE") != "detached":
            raise GateError("This workflow requires detached MR pipelines, not merged-result/merge-train pipelines")
        planfile, counts, fingerprint = make_plan()
        try:
            (ARTIFACTS / "summary.json").write_text(json.dumps(counts) + "\n")
            review = {
                "version": 2,
                "commit_sha": os.environ["CI_COMMIT_SHA"],
                "job_id": os.environ["CI_JOB_ID"],
                "mr_iid": os.environ["CI_MERGE_REQUEST_IID"],
                "config_digest": config_digest(),
                "changes_fingerprint": fingerprint,
                "counts": counts,
            }
            review.update(publish_plan(GitLab(), counts))
            (ARTIFACTS / "review.json").write_text(json.dumps(review, sort_keys=True) + "\n")
        finally:
            # Raw plan JSON and binary plans can contain secrets. Publish neither.
            planfile.unlink(missing_ok=True)
    else:
        if (
            os.environ.get("CI_PIPELINE_SOURCE") != "push"
            or os.environ.get("CI_COMMIT_BRANCH") != os.environ.get("CI_DEFAULT_BRANCH")
            or os.environ.get("CI_COMMIT_REF_PROTECTED") != "true"
        ):
            raise GateError("Apply runs only on a push pipeline for the protected default branch")
        api = GitLab()
        check_current_main(api)
        review = reviewed_manifest(api)
        planfile, counts, fingerprint = make_plan()
        try:
            if fingerprint != review["changes_fingerprint"] or counts != review["counts"]:
                raise GateError("The current plan differs from the reviewed MR plan; replan/review required")
            check_current_main(api)
            terraform("apply", "-input=false", "-no-color", "-lock-timeout=120s", str(planfile))
        finally:
            planfile.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (GateError, KeyError, OSError, ValueError) as error:
        print(f"Terraform CI: {redact(str(error))}", file=sys.stderr)
        sys.exit(1)
