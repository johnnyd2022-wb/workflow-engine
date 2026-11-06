#!/usr/bin/env python3
"""uv_audit's gate: block a merge request only on advisories it introduces.

A newly published advisory used to turn every open merge request red on uv_audit at once,
including ones that never touched a dependency, until a bump merged and each was re-run (31
of 33 uv_audit failures from 2026-10-20 to 11-02 were MRs, see
.agents/reports/ci/pipeline-health-2026-11.md). Now:

* main (no merge-request base): any advisory fails, exactly as before. main is the release
  gate, and Event Factory routes a red main uv_audit to dependency-update.
* merge request: the target branch's lockfile at the merge base is audited too. An advisory
  that is also present there was not introduced by this MR, so it is a warning (exit 3,
  which the job allows as a failure) that names the advisories; one the MR adds fails (exit
  1). If the base can't be audited, the gate fails closed on everything.

    python3 scripts/uv_audit_gate.py --out .agents/reports/security/uv-audit.json [--base SHA]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

WARN = 3
AUDIT = ["uv", "audit", "--frozen", "--output-format", "json", "--preview-features", "audit-command,json-output"]
INPUTS = ("pyproject.toml", "uv.lock")


def audit(project: Path) -> tuple[int, dict]:
    out = subprocess.run(AUDIT, cwd=project, capture_output=True, text=True)
    try:
        report = json.loads(out.stdout)
    except ValueError:
        report = {}
    if out.stderr:
        sys.stderr.write(out.stderr)
    return out.returncode, report


def findings(report: dict) -> set[tuple[str, str]]:
    keys = set()
    for v in report.get("vulnerabilities", []):
        keys.add((v.get("dependency", {}).get("name", "?"), v.get("id", "?")))
    for s in report.get("adverse_statuses", []):
        keys.add((s.get("dependency", {}).get("name", "?"), f"status:{s.get('status', '?')}"))
    return keys


def distrust(code: int, report: dict) -> str | None:
    """Why an audit run can't be believed, or None. uv audit exits 0 (clean) or 1 (findings)."""
    if "summary" not in report:
        return f"produced no report (exit {code})"
    if code not in (0, 1):
        return f"exited {code}"
    if code == 1 and not findings(report):
        return "exited 1 but reported no findings"
    return None


def deps_changed(base: str) -> bool:
    """Whether the MR touches the dependency inputs at all (fails closed to True)."""
    out = subprocess.run(["git", "diff", "--quiet", base, "HEAD", "--", *INPUTS], capture_output=True)
    return out.returncode != 0


def base_findings(base: str) -> set[tuple[str, str]] | None:
    with tempfile.TemporaryDirectory() as tmp:
        for name in INPUTS:
            show = subprocess.run(["git", "show", f"{base}:{name}"], capture_output=True, text=True)
            if show.returncode != 0:
                print(f"uv_audit_gate: cannot read {name} at {base[:8]}: {show.stderr.strip()}", file=sys.stderr)
                return None
            (Path(tmp) / name).write_text(show.stdout)
        code, report = audit(Path(tmp))
        why = distrust(code, report)
        if why:
            print(f"uv_audit_gate: auditing the lockfile at {base[:8]} {why}", file=sys.stderr)
            return None
        return findings(report)


def decide(head: set, base: set | None) -> tuple[int, set, set]:
    """(exit code, introduced, pre-existing)."""
    if not head:
        return 0, set(), set()
    if base is None:
        return 1, head, set()
    introduced, existing = head - base, head & base
    return (1 if introduced else WARN), introduced, existing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--base", default="", help="merge-request diff base SHA; empty on main")
    ap.add_argument(
        "--target",
        default="",
        help="the target branch's current tip; checked too when the MR changes pyproject.toml/uv.lock",
    )
    a = ap.parse_args(argv)

    code, report = audit(Path.cwd())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2))
    why = distrust(code, report)
    if why:
        # Fail closed whatever the findings say: the scan itself didn't run cleanly.
        print(f"uv audit {why}; failing closed.", file=sys.stderr)
        return 1
    head = findings(report)
    if head:
        print(json.dumps(report, indent=2))
    base = None
    if not a.base:
        result, introduced, existing = (1 if head else 0), head, set()
    else:
        base = base_findings(a.base) if head else set()
        if head and base is not None and deps_changed(a.base):
            # The MR re-locks dependencies. An advisory counts as pre-existing only if the target
            # still has it now; otherwise an MR branched before the target's fix could bring it
            # back. No target tip to check against: fail closed.
            tip = base_findings(a.target) if a.target else None
            base = None if tip is None else base & tip
        result, introduced, existing = decide(head, base)

    for pkg, vid in sorted(introduced):
        print(f"NEW      {pkg}: {vid}")
    for pkg, vid in sorted(existing):
        print(f"EXISTING {pkg}: {vid}  (already on the target branch; dependency-update owns it)")
    if result == 0:
        print(f"uv audit: no known vulnerabilities in {report['summary'].get('audited_packages', '?')} packages")
    elif result == WARN:
        print("uv audit: every advisory above is already on the target branch, so this MR is not blocked (warning).")
    elif a.base and base is None:
        print("uv audit: could not audit the target branch, so every advisory blocks (fail closed).")
    return result


if __name__ == "__main__":
    sys.exit(main())
