"""AC29: ``bize_mcp`` imports nothing from ``app`` (an import-graph test).

The MCP server is a protocol adapter that holds no database credentials and no app secrets. If it
could import ``app`` it could also open the database, so the boundary is enforced twice: by reading
every source file, and by importing the package in a clean interpreter and looking at what loaded.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "bize_mcp"


def _is_app(name: str) -> bool:
    return name == "app" or name.startswith("app.")


def _offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [f"{path.name}:{node.lineno} import {a.name}" for a in node.names if _is_app(a.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and _is_app(node.module or ""):
                found.append(f"{path.name}:{node.lineno} from {node.module} import ...")
            if node.level == 0 and node.module is None:
                found.append(f"{path.name}:{node.lineno} bare relative-looking import")
        elif isinstance(node, ast.Call):
            # importlib.import_module("app....") / __import__("app....") with a literal name
            func = node.func
            callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if callee in {"import_module", "__import__"} and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str) and _is_app(first.value):
                    found.append(f"{path.name}:{node.lineno} dynamic import of {first.value}")
    return found


def test_ac29_package_exists_and_is_outside_app():
    assert PACKAGE.is_dir(), "bize_mcp/ must be a top-level package"
    assert (PACKAGE / "__init__.py").is_file()
    assert (PACKAGE / "server.py").is_file()
    assert ROOT / "app" not in PACKAGE.parents


def test_ac29_no_bize_mcp_source_file_imports_app():
    files = sorted(PACKAGE.rglob("*.py"))
    assert len(files) >= 8, "the package should have its modules (config, client, shaping, tools, ...)"
    offences = [offence for path in files for offence in _offences(path)]
    assert offences == []


def test_ac29_importing_bize_mcp_loads_no_app_module():
    pytest.importorskip("mcp", reason="the optional `mcp` dependency group is not installed: uv sync --extra mcp")
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import bize_mcp, bize_mcp.server, bize_mcp.tools\n"
        "loaded = sorted(m for m in sys.modules if m == 'app' or m.startswith('app.'))\n"
        "print('LOADED', loaded)\n"
        "sys.exit(1 if loaded else 0)\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
