"""Every CI script line must be a string, or GitLab rejects the whole pipeline before any job.

An unquoted list item containing ": " (an echo message, say) parses as a YAML mapping, and
GitLab refuses the config with zero jobs created, so the failure shows up as a pipeline with
nothing in it. Use a folded block (`- >`) or quotes for such lines.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_KEY = re.compile(r"^(\s*)(?:script|before_script|after_script):\s*$")
ITEM = re.compile(r"^\s*- (.*)$")


def plain_items_that_become_mappings(text: str) -> list[str]:
    bad, block_indent = [], None
    for line in text.splitlines():
        key = SCRIPT_KEY.match(line)
        if key:
            block_indent = len(key.group(1))
            continue
        if block_indent is None or not line.strip():
            continue
        if len(line) - len(line.lstrip()) <= block_indent and not line.lstrip().startswith("- "):
            block_indent = None
            continue
        item = ITEM.match(line)
        if item:
            value = item.group(1)
            if value[:1] not in {'"', "'", ">", "|", "*", "&"} and (": " in value or value.endswith(":")):
                bad.append(line.strip())
    return bad


@pytest.mark.parametrize("config", [".gitlab-ci.yml", "terraform/ci.yml"])
def test_no_script_line_parses_as_a_mapping(config):
    assert plain_items_that_become_mappings((ROOT / config).read_text()) == []


def test_the_check_catches_an_unquoted_colon():
    text = 'job:\n  script:\n    - run || echo "note: x"\n    - >\n      echo "ok: y"\n  rules:\n    - if: $A\n'
    assert plain_items_that_become_mappings(text) == ['- run || echo "note: x"']
