"""Keep the Core route monolith from growing while routes move into slices."""

import argparse
import subprocess
import sys


BACKEND_PATH = "app/core/backend/backend.py"


def line_count(ref: str) -> int:
    result = subprocess.run(
        ["git", "show", f"{ref}:{BACKEND_PATH}"],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        # The completed carve removes backend.py; that is the desired end state.
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
            capture_output=True,
            check=False,
        )
        if exists.returncode:
            raise ValueError(f"Cannot read Git commit {ref}")
        return 0
    return len(result.stdout.splitlines())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Merge request diff base or previous main commit")
    parser.add_argument("--head", required=True, help="Commit being checked")
    args = parser.parse_args()

    try:
        before = line_count(args.base)
        after = line_count(args.head)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"{BACKEND_PATH}: {before} lines at base, {after} at head")
    if after > before:
        print("Move new routes into their owning slice; backend.py must not grow.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
