#!/usr/bin/env python3
"""Publish MR plans and apply only an approved, matching plan after merge."""

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
REVIEW_JOB = "terraform_cloudflare_review"


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
        req = Request(f"{self.base}/projects/{self.project}/{path}", headers=headers, data=data, method=method)
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


def plan_comment(plan_text, counts, commit, job_url, review_url):
    text = redact(plan_text).strip()
    fence = "`" * max(3, max((len(match) + 1 for match in re.findall(r"`+", text)), default=3))
    return (
        f"### Terraform plan — review required\n\n"
        f"**{counts['create']} to add, {counts['update']} to change, {counts['delete']} to destroy.**\n\n"
        f"Commit: `{commit}` · [Plan job]({job_url})\n\n"
        f"Read the plan below, then run [**Review Terraform plan**]({review_url}) using its ▶ button. "
        "The pipeline stays blocked until that review step passes. "
        "Approve the MR and merge once the pipeline is green; apply runs after merge.\n\n"
        f"{fence}text\n{text}\n{fence}\n"
    )


def publish_plan(api, counts):
    iid = os.environ["CI_MERGE_REQUEST_IID"]
    mr = api.fetch(f"merge_requests/{iid}")
    if mr["state"] != "opened" or mr["diff_refs"]["head_sha"] != os.environ["CI_COMMIT_SHA"]:
        raise GateError("MR has changed or closed; refusing to publish a stale plan")
    review_jobs = [
        job for job in api.all(f"pipelines/{os.environ['CI_PIPELINE_ID']}/jobs") if job["name"] == REVIEW_JOB
    ]
    if len(review_jobs) != 1:
        raise GateError("Cannot publish the plan without its blocking review job")
    body = plan_comment(
        (ARTIFACTS / "plan.txt").read_text(),
        counts,
        os.environ["CI_COMMIT_SHA"],
        os.environ["CI_JOB_URL"],
        review_jobs[0]["web_url"],
    )
    if len(body.encode()) > 900_000:
        raise GateError("Plan is too large for an MR comment; reduce the change scope")
    note = api.fetch(f"merge_requests/{iid}/notes", method="POST", payload={"body": body})
    print(f"Published full Terraform plan in MR !{iid}; explicit review is required")
    return {"note_id": note["id"], "note_digest": hashlib.sha256(body.encode()).hexdigest()}


def verify_acknowledgement(plan_job, review_job, approver_id):
    if (
        review_job["status"] != "success"
        or review_job["commit"]["id"] != plan_job["commit"]["id"]
        or review_job["pipeline"]["id"] != plan_job["pipeline"]["id"]
        or str((review_job.get("user") or {}).get("id")) != str(approver_id)
        or datetime.fromisoformat(review_job["finished_at"].replace("Z", "+00:00"))
        < datetime.fromisoformat(plan_job["finished_at"].replace("Z", "+00:00"))
    ):
        raise GateError("The configured approver must complete the review job for this final plan")


def acknowledge_plan(api):
    iid = os.environ["CI_MERGE_REQUEST_IID"]
    mr = api.fetch(f"merge_requests/{iid}")
    if mr["state"] != "opened" or mr["diff_refs"]["head_sha"] != os.environ["CI_COMMIT_SHA"]:
        raise GateError("This MR plan has been superseded or the MR is closed")
    job = api.fetch(f"jobs/{os.environ['CI_JOB_ID']}")
    if str((job.get("user") or {}).get("id")) != os.environ["TERRAFORM_APPROVER_ID"]:
        raise GateError("Only the configured approver may acknowledge the Terraform plan")
    review = json.loads((ARTIFACTS / "review.json").read_text())
    plans = [item for item in api.all(f"pipelines/{os.environ['CI_PIPELINE_ID']}/jobs") if item["name"] == PLAN_JOB]
    if len(plans) != 1:
        raise GateError("Review requires one final Terraform plan job")
    plan = plans[0]
    if (
        plan["status"] != "success"
        or plan["commit"]["id"] != os.environ["CI_COMMIT_SHA"]
        or review.get("version") != 1
        or review.get("job_id") != str(plan["id"])
        or review.get("commit_sha") != os.environ["CI_COMMIT_SHA"]
        or review.get("mr_iid") != iid
        or review.get("config_digest") != config_digest()
    ):
        raise GateError("Review artifact does not match this successful final plan")
    note = api.fetch(f"merge_requests/{iid}/notes/{review['note_id']}")
    if hashlib.sha256(note["body"].encode()).hexdigest() != review["note_digest"]:
        raise GateError("The published plan comment has changed; replan before review")
    print(f"Terraform plan for MR !{iid} explicitly reviewed by {job['user']['username']}")


def verify_review(mr, approvals, job, review, digest, approver_id):
    head = mr["diff_refs"]["head_sha"]
    if mr["state"] != "merged" or mr["target_branch"] != os.environ["CI_DEFAULT_BRANCH"]:
        raise GateError("Apply requires a merged MR targeting the default branch")
    if int(mr["source_project_id"]) != int(os.environ["CI_PROJECT_ID"]):
        raise GateError("Fork merge requests cannot authorize apply")
    if job["status"] != "success" or job["commit"]["id"] != head:
        raise GateError("The latest MR plan job must have succeeded for its final commit")
    if (
        review.get("version") != 1
        or review.get("commit_sha") != head
        or review.get("job_id") != str(job["id"])
        or review.get("mr_iid") != str(mr["iid"])
    ):
        raise GateError("Reviewed plan does not belong to this MR's final commit and job")
    if review.get("config_digest") != digest:
        raise GateError(
            "Merged Terraform configuration differs from the reviewed configuration; replan/review required"
        )
    completed = datetime.fromisoformat(job["finished_at"].replace("Z", "+00:00"))
    approved = any(
        str(item["user"]["id"]) == str(approver_id)
        and item.get("approved_at")
        and datetime.fromisoformat(item["approved_at"].replace("Z", "+00:00")) >= completed
        for item in approvals.get("approved_by", [])
    )
    if not approved or approvals.get("approvals_left", 0) != 0:
        raise GateError("The configured approver must approve after the successful final MR plan")


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
    approvals = api.fetch(f"merge_requests/{mr['iid']}/approvals")
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
    acknowledgements = [item for item in jobs if item["name"] == REVIEW_JOB]
    if len(acknowledgements) != 1:
        raise GateError("The final MR pipeline must contain the Terraform review job")
    verify_acknowledgement(job, acknowledgements[0], os.environ["TERRAFORM_APPROVER_ID"])
    review = json.loads(api.fetch(f"jobs/{job['id']}/artifacts/terraform/cloudflare/.ci/review.json", raw=True))
    verify_review(mr, approvals, job, review, config_digest(), os.environ["TERRAFORM_APPROVER_ID"])
    print(f"Verified approved MR !{mr['iid']} and plan job {job['id']}")
    return review


def check_current_main(api):
    head = api.fetch(f"repository/commits/{quote(os.environ['CI_DEFAULT_BRANCH'], safe='')}")
    if head["id"] != os.environ["CI_COMMIT_SHA"]:
        raise GateError("This pipeline has been superseded on main; refusing to apply old configuration")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "review", "apply"))
    args = parser.parse_args()
    if args.command == "review":
        if (
            os.environ.get("CI_PIPELINE_SOURCE") != "merge_request_event"
            or os.environ.get("CI_MERGE_REQUEST_SOURCE_PROJECT_ID") != os.environ.get("CI_PROJECT_ID")
            or os.environ.get("CI_MERGE_REQUEST_EVENT_TYPE") != "detached"
        ):
            raise GateError("Review runs only for same-project detached MR pipelines")
        acknowledge_plan(GitLab())
        return
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
                "version": 1,
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
