"""The red-main gate must inspect main even for stacked merge requests."""

import io
import json

import pytest

from scripts import check_main_pipeline


def test_stacked_mr_checks_default_branch(monkeypatch):
    requested = {}

    class Response(io.BytesIO):
        status = 200

    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, _method, path, **_kwargs):
            requested["path"] = path

        def getresponse(self):
            payload = {
                "id": "a" * 40,
                "last_pipeline": {"sha": "a" * 40, "ref": "main", "status": "success"},
            }
            return Response(json.dumps(payload).encode())

        def close(self):
            pass

    monkeypatch.setenv("CI_API_V4_URL", "https://gitlab.example/api/v4")
    monkeypatch.setenv("CI_SERVER_HOST", "gitlab.example")
    monkeypatch.setenv("CI_PROJECT_ID", "123")
    monkeypatch.setenv("CI_DEFAULT_BRANCH", "main")
    monkeypatch.setenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "feature/parent")
    monkeypatch.setenv("CI_JOB_TOKEN", "test-token")
    monkeypatch.setattr(check_main_pipeline, "HTTPSConnection", Connection)

    assert check_main_pipeline.main() == 0
    assert requested["path"] == "/api/v4/projects/123/repository/commits/main"


def _gate(monkeypatch, status, labels=None):
    class Response(io.BytesIO):
        status = 200

    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            payload = {"id": "a" * 40, "last_pipeline": {"sha": "a" * 40, "ref": "main", "status": status}}
            return Response(json.dumps(payload).encode())

        def close(self):
            pass

    monkeypatch.setenv("CI_API_V4_URL", "https://gitlab.example/api/v4")
    monkeypatch.setenv("CI_SERVER_HOST", "gitlab.example")
    monkeypatch.setenv("CI_PROJECT_ID", "123")
    monkeypatch.setenv("CI_DEFAULT_BRANCH", "main")
    monkeypatch.setenv("CI_JOB_TOKEN", "test-token")
    if labels is None:
        monkeypatch.delenv("CI_MERGE_REQUEST_LABELS", raising=False)
    else:
        monkeypatch.setenv("CI_MERGE_REQUEST_LABELS", labels)
    monkeypatch.setattr(check_main_pipeline, "HTTPSConnection", Connection)
    return check_main_pipeline.main()


@pytest.mark.parametrize("labels", [None, "", "ui,docs", "fixes-main-later", "not-fixes-main"])
def test_red_main_blocks_an_unlabelled_merge_request(monkeypatch, labels):
    assert _gate(monkeypatch, "failed", labels) == 1


@pytest.mark.parametrize("labels", ["fixes-main", "ui, fixes-main", "fixes-main,security"])
def test_red_main_lets_through_the_merge_request_labelled_to_repair_it(monkeypatch, labels, capsys):
    """Without this a red main blocks its own fix: nothing can merge, including the repair."""
    assert _gate(monkeypatch, "failed", labels) == 0
    assert "allowed through to repair it" in capsys.readouterr().out


def test_green_main_passes_with_or_without_the_label(monkeypatch):
    assert _gate(monkeypatch, "success") == 0
    assert _gate(monkeypatch, "success", "fixes-main") == 0
