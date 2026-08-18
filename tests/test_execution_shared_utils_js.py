"""Run Node unit tests under tests/js/*.test.js (execution shared utils, session, …)."""

import glob
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_JS_TESTS = sorted(glob.glob(str(_REPO_ROOT / "tests" / "js" / "*.test.js")))


def test_execution_js_node_unit_files_exist():
    assert _JS_TESTS, "expected tests/js/*.test.js"


def test_execution_js_node_unit():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH — install Node 18+ to run JS unit tests")

    # `node --test` was added in Node 18 (experimental) / stabilized in Node 20 (CI installs
    # 20.x, .gitlab-ci.yml:127) — older system `node` binaries (e.g. distro-packaged v12)
    # reject the flag outright with a non-JSON "bad option: --test" and exit 9, which
    # CalledProcessError would otherwise surface as a hard failure indistinguishable from a
    # real assertion failure. Skip honestly instead, same as the "not on PATH" case above.
    version_out = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    major = int(version_out.lstrip("v").split(".")[0])
    if major < 18:
        pytest.skip(f"node {version_out} predates `--test` (needs 18+) — install Node 18+ to run JS unit tests")

    subprocess.run([node, "--test", *_JS_TESTS], cwd=str(_REPO_ROOT), check=True)
