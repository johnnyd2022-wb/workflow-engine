"""Keep Core route composition out of the feature implementation packages."""

import ast
from pathlib import Path

import pytest

FEATURES_DIR = Path(__file__).resolve().parents[1] / "app" / "features"
CORE_COMPOSITION = "app.core.backend.backend"


@pytest.mark.parametrize("feature", ["execution", "inventory", "process_design", "traceability"])
def test_core_slices_import_public_dependencies(feature):
    violations = []
    for path in (FEATURES_DIR / feature).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                if any(alias.name == CORE_COMPOSITION for alias in node.names):
                    violations.append(f"{path.name}:{node.lineno} imports Core composition")
            if not isinstance(node, ast.ImportFrom) or node.level or node.module is None:
                continue
            if node.module == CORE_COMPOSITION or (
                node.module == "app.core.backend" and any(alias.name == "backend" for alias in node.names)
            ):
                violations.append(f"{path.name}:{node.lineno} imports Core composition")
            parts = node.module.split(".")
            if len(parts) > 2 and parts[:2] == ["app", "features"] and parts[2] != feature:
                for alias in node.names:
                    if alias.name.startswith("_") or alias.name == "*":
                        violations.append(f"{path.name}:{node.lineno} imports {node.module}.{alias.name}")
    assert not violations, "\n".join(violations)
