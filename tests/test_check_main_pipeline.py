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


def _walk(monkeypatch, chain, labels=None):
    """chain: list of pipeline statuses from main's head backwards (None = no pipeline)."""
    shas = [str(i) * 40 for i in range(len(chain))]
    requested = []

    class Response(io.BytesIO):
        status = 200

    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, _method, path, **_kwargs):
            requested.append(path.rsplit("/", 1)[1])

        def getresponse(self):
            ref = requested[-1]
            i = 0 if ref == "main" else shas.index(ref)
            payload = {"id": shas[i], "parent_ids": shas[i + 1 : i + 2]}
            if chain[i] is not None:
                payload["last_pipeline"] = {"sha": shas[i], "ref": "main", "status": chain[i]}
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
    return check_main_pipeline.main(), requested


@pytest.mark.parametrize("head", ["running", "pending", "created", None])
def test_main_mid_pipeline_is_judged_by_the_newest_finished_pipeline(monkeypatch, head, capsys):
    """The commonest red MR gate: main still building after the previous merge."""
    code, requested = _walk(monkeypatch, [head, "success"])
    assert code == 0
    assert requested == ["main", "1" * 40]
    assert "still building" in capsys.readouterr().out


@pytest.mark.parametrize("head", ["running", None])
def test_main_mid_pipeline_after_a_red_pipeline_still_blocks(monkeypatch, head):
    assert _walk(monkeypatch, [head, "failed", "success"])[0] == 1
    assert _walk(monkeypatch, [head, "running", "canceled", "success"])[0] == 1
    assert _walk(monkeypatch, [head, "failed"], "fixes-main")[0] == 0


def test_red_head_blocks_without_walking(monkeypatch):
    code, requested = _walk(monkeypatch, ["failed", "success"])
    assert code == 1
    assert requested == ["main"]


def test_walk_is_bounded_and_fails_closed(monkeypatch):
    chain = ["running"] * (check_main_pipeline.MAX_WALK + 3) + ["success"]
    code, requested = _walk(monkeypatch, chain)
    assert code == 1
    assert len(requested) == check_main_pipeline.MAX_WALK + 1
