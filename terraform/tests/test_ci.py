"""Approval, provenance and drift gates must fail closed."""

import copy
import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.approvals = {
            "approvals_left": 0,
            "approved_by": [{"user": {"id": 7}, "approved_at": "2026-10-08T10:01:00Z"}],
        }
        self.review = {"version": 1, "commit_sha": "abc", "job_id": "5", "mr_iid": "4", "config_digest": "digest"}

    def verify(self):
        ci.verify_review(self.mr, self.approvals, self.job, self.review, "digest", "7")

    def test_approved_final_plan(self):
        self.verify()

    def test_missing_or_early_or_wrong_approval(self):
        for approval in (
            [],
            [{"user": {"id": 7}}],
            [{"user": {"id": 7}, "approved_at": "2026-10-08T09:59:00Z"}],
            [{"user": {"id": 8}, "approved_at": "2026-10-08T10:01:00Z"}],
        ):
            with self.subTest(approval=approval):
                self.approvals["approved_by"] = approval
                with self.assertRaises(ci.GateError):
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
            ("version", 2),
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


if __name__ == "__main__":
    unittest.main()
