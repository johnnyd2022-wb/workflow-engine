"""The red-main gate must inspect main even for stacked merge requests."""

import io
import json

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
