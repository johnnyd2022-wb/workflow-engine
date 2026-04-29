#!/usr/bin/env python3
"""Count lines of code by file type; print totals and top-5 files per type.

Run from repo root: python scripts/loc_stats.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Directories to skip entirely
SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".eggs",
    ".tmp-venv",
}

# Treat as non-text for line counts
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".pyc",
    ".pyo",
    ".class",
    ".sqlite",
    ".db",
    ".bin",
    ".mp4",
    ".webm",
    ".mp3",
    ".wav",
}


def file_type_label(path: Path) -> str:
    suf = path.suffix.lower()
    if not suf and path.name.startswith("."):
        return path.name
    if not suf:
        return "(no ext)"
    return suf


def should_skip_dir(name: str) -> bool:
    if name in SKIP_DIR_NAMES:
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def line_count(path: Path) -> int | None:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > 50 * 1024 * 1024:
        return None
    if data[:8192].find(b"\0") != -1:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    return len(text.splitlines())


def collect_stats(root: Path) -> tuple[dict[str, int], dict[str, int], dict[str, list[tuple[Path, int]]]]:
    lines_by_type: dict[str, int] = defaultdict(int)
    files_by_type: dict[str, int] = defaultdict(int)
    files_lines: dict[str, list[tuple[Path, int]]] = defaultdict(list)

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        parts = rel.parts
        if "site-packages" in parts:
            continue
        if any(should_skip_dir(part) for part in parts[:-1]):
            continue
        n = line_count(p)
        if n is None:
            continue
        label = file_type_label(p)
        lines_by_type[label] += n
        files_by_type[label] += 1
        files_lines[label].append((rel, n))

    return dict(lines_by_type), dict(files_by_type), dict(files_lines)


def print_markdown(
    lines_by_type: dict[str, int],
    files_by_type: dict[str, int],
    files_lines: dict[str, list[tuple[Path, int]]],
) -> None:
    # Totals: sort by lines descending
    types_sorted = sorted(lines_by_type.items(), key=lambda x: (-x[1], x[0]))
    total_lines = sum(lines_by_type.values())
    total_files = sum(files_by_type.values())

    print("## Totals by file type\n")
    print("| File type | Files | Lines |")
    print("|-----------|------:|------:|")
    for t, lines in types_sorted:
        print(f"| {t} | {files_by_type[t]} | {lines} |")
    print(f"| **all** | **{total_files}** | **{total_lines}** |")

    print("\n## Top 5 largest files per file type\n")
    for t, _lines in types_sorted:
        entries = sorted(files_lines.get(t, []), key=lambda x: (-x[1], str(x[0])))[:5]
        if not entries:
            continue
        print(f"### {t}\n")
        print("| Lines | Path |")
        print("|------:|------|")
        for rel, n in entries:
            print(f"| {n} | `{rel}` |")
        print()


def main() -> int:
    root = ROOT
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
        if not root.is_dir():
            print(f"Not a directory: {root}", file=sys.stderr)
            return 1

    lines_by_type, files_by_type, files_lines = collect_stats(root)
    print_markdown(lines_by_type, files_by_type, files_lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
