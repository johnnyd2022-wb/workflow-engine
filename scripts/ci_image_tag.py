"""The tag of the CI image that matches this checkout (see ci/Dockerfile.ci).

The tag is a hash of everything the image is built from, so a tag never changes meaning:
the runner caches images and would not notice a reused tag.

    python3 scripts/ci_image_tag.py            # print the tag
    python3 scripts/ci_image_tag.py --check    # fail if CI_IMAGE_TAG in .gitlab-ci.yml is stale
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUTS = ("ci/Dockerfile.ci", "pyproject.toml", "uv.lock")
_PINNED = re.compile(r'^\s*CI_IMAGE_TAG:\s*"([0-9a-f]+)"', re.MULTILINE)


def image_tag(root: Path = REPO_ROOT) -> str:
    # The same as `cat ci/Dockerfile.ci pyproject.toml uv.lock | sha256sum | cut -c1-16`,
    # which is how the build job computes it on a runner with no Python.
    digest = hashlib.sha256()
    for name in INPUTS:
        digest.update((root / name).read_bytes())
    return digest.hexdigest()[:16]


def pinned_tag(root: Path = REPO_ROOT) -> str | None:
    match = _PINNED.search((root / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Exit 1 when the pinned CI_IMAGE_TAG is not this tag.")
    args = parser.parse_args()
    current = image_tag()
    if not args.check:
        print(current)
        return 0
    pinned = pinned_tag()
    if pinned == current:
        print(f"CI image tag {current} is current.")
        return 0
    print(
        f"CI image is stale: .gitlab-ci.yml pins {pinned or 'nothing'}, this checkout needs {current}.\n"
        f"Jobs still pass (uv sync installs the difference) but run slower. Once main has built "
        f"the new image, set CI_IMAGE_TAG to {current}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
