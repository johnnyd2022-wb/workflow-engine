"""The CI image tag must identify the image's inputs exactly: the runner caches images, so a
tag that did not change when the lockfile did would silently keep serving the old one."""

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import ci_image_tag  # noqa: E402

ROOT = ci_image_tag.REPO_ROOT


def _checkout(tmp_path, **overrides):
    files = {"ci/Dockerfile.ci": "FROM python\n", "pyproject.toml": "[project]\n", "uv.lock": "version = 1\n"}
    files.update(overrides)
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def test_tag_matches_the_shell_pipeline_the_build_job_uses():
    """ci_image_build runs on a runner with no Python and computes the tag with sha256sum."""
    shell = subprocess.run(
        "cat ci/Dockerfile.ci pyproject.toml uv.lock | sha256sum | cut -c1-16",
        shell=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert ci_image_tag.image_tag() == shell
    assert (
        "cat ci/Dockerfile.ci pyproject.toml uv.lock | sha256sum | cut -c1-16" in (ROOT / ".gitlab-ci.yml").read_text()
    )


@pytest.mark.parametrize("changed", ["ci/Dockerfile.ci", "pyproject.toml", "uv.lock"])
def test_tag_changes_when_any_input_changes(tmp_path, changed):
    before = ci_image_tag.image_tag(_checkout(tmp_path))
    after = ci_image_tag.image_tag(_checkout(tmp_path, **{changed: "changed\n"}))
    assert before != after
    assert len(after) == 16 and int(after, 16) >= 0


def test_tag_ignores_everything_else(tmp_path):
    root = _checkout(tmp_path)
    before = ci_image_tag.image_tag(root)
    (root / ".gitlab-ci.yml").write_text('variables:\n  CI_IMAGE_TAG: "abc123"\n')
    (root / "app").mkdir()
    (root / "app" / "app.py").write_text("print(1)\n")
    assert ci_image_tag.image_tag(root) == before
    expected = hashlib.sha256(b"FROM python\n[project]\nversion = 1\n").hexdigest()[:16]
    assert before == expected


def test_pinned_tag_is_read_from_the_ci_config(tmp_path):
    root = _checkout(tmp_path)
    (root / ".gitlab-ci.yml").write_text('variables:\n  UV_VERSION: "1"\n  CI_IMAGE_TAG: "0123456789abcdef"\n')
    assert ci_image_tag.pinned_tag(root) == "0123456789abcdef"
    (root / ".gitlab-ci.yml").write_text("variables: {}\n")
    assert ci_image_tag.pinned_tag(root) is None


def test_python_jobs_fall_back_cleanly_on_a_bare_image():
    """Every skipped install step must be guarded, so a job still works without the image."""
    config = (ROOT / ".gitlab-ci.yml").read_text()
    ci_part = config.split("# CD: build stage")[0]
    for line in ci_part.splitlines():
        stripped = line.strip().lstrip("- ")
        if stripped.startswith("#"):
            continue
        for command in ("apt-get update", "apt-get install", "deb.nodesource.com"):
            if command in stripped:
                assert 'test -n "${CI_PREBUILT:-}" || ' in stripped, line
    assert 'pip install "uv==${UV_VERSION}"' in ci_part
    assert "--with-deps chromium" not in ci_part
