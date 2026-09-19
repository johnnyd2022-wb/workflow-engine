"""The one-command rebuild must never run a destructive step it was not cleared to run."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_migration as wm  # noqa: E402
import whistlebird_np3 as np3  # noqa: E402
import whistlebird_rebuild_api as rebuild_api  # noqa: E402


@pytest.fixture
def steps(monkeypatch, tmp_path):
    """Replace every step with a recorder so no database or server is touched."""
    called: list[str] = []

    def record(name, result=None):
        def _step(*_args, **_kwargs):
            called.append(name)
            return result if result is not None else {}

        return _step

    manifest = tmp_path / "np3.json"
    manifest.write_text(json.dumps({"profile": None, "staff": [], "attestations": [], "logs": []}))
    monkeypatch.setenv("WHISTLEBIRD_TEST_ADMIN_PASSWORD", "not-a-real-password")
    monkeypatch.setattr(rebuild_api, "server_reachable", lambda *_a, **_k: None)
    monkeypatch.setattr(np3, "np3_unsnapshotted", lambda *_a, **_k: [])
    monkeypatch.setattr(wm, "ensure_target_org_admin", record("tenant"))
    monkeypatch.setattr(wm, "sync_whistlebird_test_admin_password", record("password"))
    monkeypatch.setattr(wm, "reset_target_org", record("reset"))
    monkeypatch.setattr(wm, "setup_product_workflows", record("workflows"))
    monkeypatch.setattr(wm, "ensure_compliant_nz_alcohol_setup", record("compliant"))
    monkeypatch.setattr(rebuild_api.replay, "run_replay", record("replay"))
    monkeypatch.setattr(rebuild_api.correct, "correct_timestamps", record("timestamps"))
    monkeypatch.setattr(wm, "build_import_verification", record("verify"))
    monkeypatch.setattr(wm, "_require_matching_import", record("require"))
    return {"called": called, "manifest": manifest}


def _args(steps, *extra):
    return rebuild_api._arguments(
        [
            "--legacy-url=postgresql://legacy",
            "--target-url=postgresql://target",
            f"--np3-manifest={steps['manifest']}",
            *extra,
        ]
    )


def test_without_the_confirm_flag_nothing_runs(steps):
    report = rebuild_api.rebuild(_args(steps))

    assert report["dry_run"] is True
    assert steps["called"] == []


def test_confirmed_rebuild_runs_the_documented_path_in_order(steps):
    rebuild_api.rebuild(_args(steps, "--confirm-reset-whistlebird-test"))

    assert steps["called"] == [
        "tenant",
        "password",
        "reset",
        "workflows",
        "compliant",
        "replay",
        "timestamps",
        "verify",
        "require",
    ]


def test_unsnapshotted_np3_evidence_blocks_the_reset(steps, monkeypatch):
    monkeypatch.setattr(np3, "np3_unsnapshotted", lambda *_a, **_k: ["staff-competency: attestation not in manifest"])

    with pytest.raises(rebuild_api.RebuildRefusedError, match="would delete NP3 evidence"):
        rebuild_api.rebuild(_args(steps, "--confirm-reset-whistlebird-test"))

    assert steps["called"] == []


def test_discarding_unsnapshotted_evidence_must_be_explicit(steps, monkeypatch):
    monkeypatch.setattr(np3, "np3_unsnapshotted", lambda *_a, **_k: ["staff-competency: attestation not in manifest"])

    rebuild_api.rebuild(_args(steps, "--confirm-reset-whistlebird-test", "--discard-unsnapshotted-np3"))

    assert "reset" in steps["called"]


def test_invalid_manifest_blocks_the_reset(steps):
    steps["manifest"].write_text(json.dumps({"attestations": [{"control_id": "nope"}]}))

    with pytest.raises(rebuild_api.RebuildRefusedError, match="NP3 manifest invalid"):
        rebuild_api.rebuild(_args(steps, "--confirm-reset-whistlebird-test"))

    assert steps["called"] == []


def test_unreachable_app_blocks_the_reset(steps, monkeypatch):
    monkeypatch.setattr(rebuild_api, "server_reachable", lambda *_a, **_k: "app not reachable")

    with pytest.raises(rebuild_api.RebuildRefusedError, match="app not reachable"):
        rebuild_api.rebuild(_args(steps, "--confirm-reset-whistlebird-test"))

    assert steps["called"] == []


def test_only_the_test_tenant_is_accepted(steps):
    with pytest.raises(SystemExit):
        _args(steps, "--org-name=Some Other Org")
