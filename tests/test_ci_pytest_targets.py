"""relevant_tests hands pytest one target per line, and a target can contain spaces.

Test impact analysis selects individual node IDs, and a parametrised ID can hold spaces, e.g.
``...ignores_letter_case[wildflower-Whistlebird Gin 44% - WILDFLOWER - 700ml trade]``. Splitting
the target file on spaces shredded such an ID into ``Gin``, ``44%``, ``-`` ...; pytest answered
"file or directory not found: Gin", collected 0 items and failed the job, for any MR whose diff
made that test relevant (seen on MR !542, which only touched the code the test covers).

These run the job's own shell lines (with /tmp redirected), so a rewrite of them is held to the
same contract.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = "/tmp/relevant-pytest-targets"
ARGS = "/tmp/pytest-args"
SPACED_ID = (
    "tests/test_sales_traceability.py::test_reconcile_contains_mapping_ignores_letter_case"
    "[wildflower-Whistlebird Gin 44% - WILDFLOWER - 700ml trade]"
)


def conversion_lines() -> list[str]:
    """The relevant_tests shell lines that rewrite the target files, in the order they run."""
    text = (ROOT / ".gitlab-ci.yml").read_text()
    job = text[text.index("\nrelevant_tests:") : text.index("\nmr_e2e:")]
    return [
        line.strip()
        for line in job.splitlines()
        if not line.strip().startswith("#") and re.search(r"\b(tr|sed)\b", line) and (TARGETS in line or ARGS in line)
    ]


def run(lines: list[str], targets: str, tmp_path: Path) -> list[str]:
    (tmp_path / "relevant-pytest-targets").write_text(targets)
    for line in lines:
        subprocess.run(["bash", "-c", line.replace("/tmp/", f"{tmp_path}/")], check=True, cwd=tmp_path)
    return (tmp_path / "pytest-args").read_text().splitlines()


def test_a_selected_test_id_containing_spaces_reaches_pytest_whole(tmp_path):
    # What tia.py writes: one node ID per line. Only the last line runs after it replaces the file.
    targets = f"{SPACED_ID}\ntests/test_crm.py\n"

    assert run(conversion_lines()[-1:], targets, tmp_path) == [SPACED_ID, "tests/test_crm.py"]


def test_path_rules_output_still_becomes_one_target_per_line(tmp_path):
    """[CONTROL] What select_relevant_tests.py prints: paths on one line, separated by spaces."""
    targets = "tests/test_crm.py tests/test_xero_sync_service.py\n"

    assert run(conversion_lines(), targets, tmp_path) == ["tests/test_crm.py", "tests/test_xero_sync_service.py"]
