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
    subprocess.run([node, "--test", *_JS_TESTS], cwd=str(_REPO_ROOT), check=True)
