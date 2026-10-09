"""Approval, provenance and drift gates must fail closed."""

import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("terraform_ci", Path(__file__).parents[1] / "ci.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"CI_DEFAULT_BRANCH": "main", "CI_PROJECT_ID": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.mr = {
            "iid": 4,
            "state": "merged",
            "target_branch": "main",
            "source_project_id": 1,
            "diff_refs": {"head_sha": "abc"},
        }
        self.job = {"id": 5, "status": "success", "commit": {"id": "abc"}, "finished_at": "2026-10-08T10:00:00Z"}
        self.review = {"version": 2, "commit_sha": "abc", "job_id": "5", "mr_iid": "4", "config_digest": "digest"}

    def verify(self):
        ci.verify_review(self.mr, self.job, self.review, "digest")

    def test_matching_final_plan(self):
        self.verify()

    def test_unmerged_fork_failed_or_stale_job(self):
        changes = [
            (self.mr, "state", "opened"),
            (self.mr, "source_project_id", 2),
            (self.job, "status", "failed"),
            (self.job, "commit", {"id": "old"}),
        ]
        for target, key, value in changes:
            original = target[key]
            target[key] = value
            with self.subTest(key=key), self.assertRaises(ci.GateError):
                self.verify()
            target[key] = original

    def test_wrong_artifact_or_config(self):
        for key, value in [
            ("version", 1),
            ("commit_sha", "old"),
            ("job_id", "6"),
            ("mr_iid", "3"),
            ("config_digest", "different"),
        ]:
            original = self.review[key]
            self.review[key] = value
            with self.subTest(key=key), self.assertRaises(ci.GateError):
                self.verify()
            self.review[key] = original


class PlanTests(unittest.TestCase):
    def test_replacement_counts_and_changed_values(self):
        resource = {
            "address": "test.one",
            "provider_name": "test",
            "change": {"actions": ["delete", "create"], "before": {"name": "old"}, "after": {"name": "new"}},
        }
        plan = {"resource_changes": [resource]}
        counts, fingerprint = ci.summarize(plan)
        self.assertEqual(counts, {"create": 1, "update": 0, "delete": 1})
        changed = copy.deepcopy(plan)
        changed["resource_changes"][0]["change"]["after"]["name"] = "unreviewed"
        self.assertNotEqual(fingerprint, ci.summarize(changed)[1])

    def test_output_changes_affect_review(self):
        self.assertNotEqual(
            ci.summarize({})[1],
            ci.summarize({"output_changes": {"id": {"actions": ["update"], "before": "a", "after": "b"}}})[1],
        )

    def test_noop_refresh_does_not_change_fingerprint(self):
        plan = {
            "resource_changes": [
                {
                    "address": "test.one",
                    "provider_name": "test",
                    "change": {"actions": ["no-op"], "before": {"computed": "changed"}},
                }
            ]
        }
        self.assertEqual(ci.summarize({}), ci.summarize(plan))

    def test_secret_redaction(self):
        with patch.dict(os.environ, {"PGPASSWORD": "db-secret", "CLOUDFLARE_API_TOKEN": "cf-secret"}):
            self.assertEqual(ci.redact("db-secret cf-secret"), "[REDACTED] [REDACTED]")


class ThreadReviewTests(unittest.TestCase):
    def setUp(self):
        self.note = {
            "id": 8,
            "body": "full plan",
            "resolvable": True,
            "resolved": True,
            "resolved_by": {"id": 7},
            "created_at": "2026-10-09T10:00:00Z",
            "resolved_at": "2026-10-09T10:01:00Z",
        }
        self.discussion = {"id": "thread", "individual_note": False, "notes": [self.note]}
        self.review = {"discussion_id": "thread", "note_id": 8, "note_digest": hashlib.sha256(b"full plan").hexdigest()}

    def verify(self):
        ci.verify_plan_thread(self.discussion, self.review, "7", "2026-10-09T10:02:00Z")

    def test_matching_resolution(self):
        self.verify()

    def test_wrong_actor_unresolved_edited_or_bad_time(self):
        for key, value in [
            ("resolved_by", {"id": 9}),
            ("resolved_by", None),
            ("resolved", False),
            ("body", "different plan"),
            ("resolvable", False),
            ("resolved_at", None),
            ("resolved_at", "2026-10-09T09:59:00Z"),
            ("resolved_at", "2026-10-09T10:03:00Z"),
        ]:
            original = self.note[key]
            self.note[key] = value
            with self.subTest(key=key), self.assertRaises(ci.GateError):
                self.verify()
            self.note[key] = original

    def test_wrong_discussion_or_deleted_note(self):
        self.discussion["id"] = "old-thread"
        with self.assertRaises(ci.GateError):
            self.verify()
        self.discussion["id"] = "thread"
        self.discussion["notes"] = []
        with self.assertRaises(ci.GateError):
            self.verify()

    def test_unresolved_reply_reopens_review(self):
        self.discussion["notes"].append({"id": 9, "resolvable": True, "resolved": False})
        with self.assertRaises(ci.GateError):
            self.verify()

    def test_comment_full_plan_and_secret_redaction(self):
        with patch.dict(os.environ, {"PGPASSWORD": "db-secret"}):
            body = ci.plan_comment(
                "Plan: 1 to add. db-secret ```danger",
                {"create": 1, "update": 0, "delete": 0},
                "abc",
                "https://gitlab.com/plan",
            )
        self.assertNotIn("db-secret", body)
        self.assertIn("Plan: 1 to add.", body)
        self.assertIn("````text", body)
        self.assertIn("resolve this thread", body)
        self.assertNotIn("▶", body)


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "CI_MERGE_REQUEST_IID": "4",
                "CI_COMMIT_SHA": "abc",
                "CI_PIPELINE_ID": "1",
                "CI_JOB_URL": "https://gitlab.com/plan",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = patch.object(ci, "ARTIFACTS", Path(folder.name))
        self.folder.start()
        self.addCleanup(self.folder.stop)
        (Path(folder.name) / "plan.txt").write_text("Plan: 1 to add.")
        self.mr = {
            "state": "opened",
            "diff_refs": {"head_sha": "abc"},
            "head_pipeline": {"id": 1},
            "web_url": "https://gitlab.com/mr/4",
        }
        self.thread = {
            "id": "new",
            "individual_note": False,
            "notes": [
                {
                    "id": 8,
                    "body": "GitLab-normalized plan text",
                    "resolvable": True,
                    "resolved": False,
                    "author": {"id": 7},
                    "created_at": "2026-10-09T10:00:00Z",
                }
            ],
        }
        self.api = Mock()
        self.api.fetch.side_effect = [self.mr, {"only_allow_merge_if_all_discussions_are_resolved": True}, self.thread]
        self.api.all.return_value = []

    def test_publishes_resolvable_thread_and_records_identity(self):
        review = ci.publish_plan(self.api, {"create": 1, "update": 0, "delete": 0})
        self.assertEqual(review["discussion_id"], "new")
        self.assertEqual(review["note_id"], 8)
        self.assertEqual(review["note_digest"], hashlib.sha256(b"GitLab-normalized plan text").hexdigest())
        self.assertEqual(self.api.fetch.call_args.args, ("merge_requests/4/discussions",))
        self.assertEqual(self.api.fetch.call_args.kwargs["method"], "POST")

    def test_refuses_stale_pipeline(self):
        self.mr["head_pipeline"]["id"] = 2
        with self.assertRaises(ci.GateError):
            ci.publish_plan(self.api, {"create": 1, "update": 0, "delete": 0})
        self.assertEqual(self.api.fetch.call_count, 1)

    def test_refuses_disabled_merge_check(self):
        self.api.fetch.side_effect = [self.mr, {"only_allow_merge_if_all_discussions_are_resolved": False}]
        with self.assertRaises(ci.GateError):
            ci.publish_plan(self.api, {"create": 1, "update": 0, "delete": 0})
        self.assertEqual(self.api.fetch.call_count, 2)

    def test_supersedes_only_older_automated_threads(self):
        root = {
            "body": ci.PLAN_MARKER + "\nold plan",
            "author": {"id": 7},
            "resolvable": True,
            "resolved": False,
            "created_at": "2026-10-09T09:00:00Z",
        }
        self.api.all.return_value = [
            self.thread,
            {"id": "old", "notes": [root]},
            {"id": "human", "notes": [root | {"body": "Human discussion"}]},
            {"id": "conversation", "notes": [root, {"body": "Question about the old plan"}]},
            {"id": "other-author", "notes": [root | {"author": {"id": 9}}]},
        ]
        self.api.fetch.side_effect = [
            self.mr,
            {"only_allow_merge_if_all_discussions_are_resolved": True},
            self.thread,
            {},
            {},
        ]
        ci.publish_plan(self.api, {"create": 1, "update": 0, "delete": 0})
        self.assertEqual(self.api.fetch.call_count, 5)
        self.assertEqual(self.api.fetch.call_args.args, ("merge_requests/4/discussions/old",))
        self.assertEqual(self.api.fetch.call_args.kwargs["payload"], {"resolved": True})


class NativeApprovalFlowTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"CI_DEFAULT_BRANCH": "main", "CI_PROJECT_ID": "1", "CI_COMMIT_SHA": "merge", "TERRAFORM_APPROVER_ID": "7"},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.digest = patch.object(ci, "config_digest", return_value="digest")
        self.digest.start()
        self.addCleanup(self.digest.stop)
        self.review = {
            "version": 2,
            "commit_sha": "abc",
            "job_id": "5",
            "mr_iid": "4",
            "config_digest": "digest",
            "discussion_id": "thread",
            "note_id": 8,
            "note_digest": hashlib.sha256(b"full plan").hexdigest(),
        }
        self.note = {
            "id": 8,
            "body": "full plan",
            "resolvable": True,
            "resolved": True,
            "resolved_by": {"id": 7},
            "created_at": "2026-10-09T10:00:00Z",
            "resolved_at": "2026-10-09T10:01:00Z",
        }
        responses = {
            "repository/commits/merge/merge_requests": [
                {"iid": 4, "state": "merged", "merge_commit_sha": "merge", "target_branch": "main"}
            ],
            "merge_requests/4": {
                "iid": 4,
                "state": "merged",
                "source_project_id": 1,
                "target_branch": "main",
                "diff_refs": {"head_sha": "abc"},
                "merged_at": "2026-10-09T10:02:00Z",
                "head_pipeline": {"id": 6, "source": "merge_request_event", "sha": "abc", "status": "success"},
            },
            "jobs/5/artifacts/terraform/cloudflare/.ci/review.json": json.dumps(self.review).encode(),
            "merge_requests/4/discussions/thread": {"id": "thread", "individual_note": False, "notes": [self.note]},
        }
        self.api = Mock()
        self.api.fetch.side_effect = lambda path, **kwargs: responses[path]
        self.api.all.return_value = [{"name": ci.PLAN_JOB, "id": 5, "status": "success", "commit": {"id": "abc"}}]

    def test_resolved_thread_authorizes_without_mr_approve_click(self):
        self.assertEqual(ci.reviewed_manifest(self.api), self.review)
        self.assertFalse(any("/approvals" in call.args[0] for call in self.api.fetch.call_args_list))

    def test_missing_thread_resolution_still_blocks_apply(self):
        self.note["resolved"] = False
        with self.assertRaises(ci.GateError):
            ci.reviewed_manifest(self.api)


if __name__ == "__main__":
    unittest.main()
