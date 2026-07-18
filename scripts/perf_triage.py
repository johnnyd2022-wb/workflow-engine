#!/usr/bin/env python3
"""Deterministic performance triage: fuse the static perf-rule findings, the app's route
surface, the perf budgets, and the last measured run into one priority-ordered checklist.

Owned by the perf-guardrails skill. Answers, in one cheap pass, the question an agent
would otherwise re-derive by reading the whole app: which routes are most likely slow
(static semgrep evidence), which of those are actually measured against budgets, and
which measured ones are over. Skills run this BEFORE spending tokens on manual perf
archaeology, and rerun it after a page/flow changes so the checklist stays current.

Design rules (same as preflight.py / e2e_coverage.py / error_scan.py):
- stdlib only, except importing the app's url_map via scripts/e2e_coverage.py (the only
  accurate source of the route surface) and shelling out to semgrep if it is on PATH.
- machine-readable first (`--json`); humans get the summary; `--write-index` regenerates
  the checklist markdown so the index is a build product, not hand-maintained prose.
- it reports and ranks; fixing a finding is the calling skill's decision.
- an absent tool degrades honestly: no semgrep means `static: unavailable` in the
  output, never a silently empty finding list.

Inputs:
- .semgrep/rules/performance.yml     via `semgrep --json` (static N+1 / unbounded-query rules)
- app.url_map                        via scripts/e2e_coverage.py (routes + exclusions)
- .agents/perf/budgets.json          what is measured, and against what
- .agents/reports/perf/last-run.json what the last perf-test run actually observed

Usage:
    python scripts/perf_triage.py                 # human summary + checklist
    python scripts/perf_triage.py --json          # full machine-readable output
    python scripts/perf_triage.py --write-index   # also regenerate the checklist markdown
    python scripts/perf_triage.py --check         # exit 1 on ceiling breach or an
                                                  #   unmeasured area with WARNING findings
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGETS_FILE = REPO_ROOT / ".agents" / "perf" / "budgets.json"
LAST_RUN_FILE = REPO_ROOT / ".agents" / "reports" / "perf" / "last-run.json"
INDEX_FILE = REPO_ROOT / ".agents" / "reports" / "perf" / "priority-checklist.md"
PERF_RULES = REPO_ROOT / ".semgrep" / "rules" / "performance.yml"

SEVERITY_WEIGHT = {"ERROR": 5, "WARNING": 3, "INFO": 1}

# File location -> feature area -> route prefixes. Attribution is honest at AREA
# granularity: a finding in app/core/backend/backend.py cannot be pinned to one route
# without call-graph analysis, but it raises the priority of every route its area serves.
AREA_ROUTE_PREFIXES: dict[str, tuple[str, ...]] = {
    "crm": ("/crm", "/api/crm"),
    "workflow_engine": ("/workflow-engine",),
    "core": ("/core", "/api/core", "/auth", "/org", "/dashboard"),
    "shared-frontend": (),  # app/ui — served into every page; findings score globally
}


def area_of_file(path: str) -> str:
    if path.startswith("app/features/"):
        parts = path.split("/")
        return parts[2] if len(parts) > 2 else "core"
    if path.startswith("app/ui/"):
        return "shared-frontend"
    return "core"


def area_of_route(rule: str) -> str:
    for area, prefixes in AREA_ROUTE_PREFIXES.items():
        if any(rule == p or rule.startswith(p + "/") or rule.startswith(p) and p != "/" for p in prefixes):
            return area
    return "core"


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------


def static_findings() -> dict:
    """Run the repo's performance semgrep rules over app/. Degrades honestly."""
    if not PERF_RULES.exists():
        return {"status": "unavailable", "reason": f"{PERF_RULES} missing", "findings": []}
    if shutil.which("semgrep") is None:
        return {"status": "unavailable", "reason": "semgrep not on PATH", "findings": []}
    proc = subprocess.run(
        [
            "semgrep",
            "--config",
            str(PERF_RULES),
            "--json",
            "--quiet",
            # vendored third-party bundles are not ours to fix; findings there are noise
            "--exclude",
            "*.full.js",
            "--exclude",
            "*.iife.js",
            "app/",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "unavailable", "reason": f"semgrep failed rc={proc.returncode}", "findings": []}
    # rc=2 with parseable output means some RULES failed to parse: report degraded, keep
    # the findings that did run rather than pretending the scan was clean or empty.
    rule_errors = [e.get("rule_id", "?") for e in raw.get("errors", []) if e.get("type") == "Rule parse error"]
    status = "ok" if not rule_errors else f"degraded ({len(rule_errors)} broken rules: {', '.join(rule_errors)})"
    findings = [
        {
            "file": str(Path(r["path"]).as_posix()),
            "line": r["start"]["line"],
            "rule": r["check_id"].rsplit(".", 1)[-1],
            "severity": r["extra"]["severity"],
            "area": area_of_file(str(Path(r["path"]).as_posix())),
        }
        for r in raw.get("results", [])
    ]
    return {"status": status, "findings": findings}


def route_surface() -> list[dict]:
    """Non-excluded (rule, methods) pairs, reusing e2e_coverage's app import + exclusions."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    sys.path.insert(0, str(REPO_ROOT))
    import e2e_coverage  # noqa: PLC0415

    return [r for r in e2e_coverage.app_routes() if not e2e_coverage._excluded(r["rule"])]


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# Triage
# --------------------------------------------------------------------------------------


def build_triage() -> dict:
    static = static_findings()
    budgets = load_json(BUDGETS_FILE) or {}
    last_run = load_json(LAST_RUN_FILE)
    routes = route_surface()

    measured = set(budgets.get("measure", {}).get("pages", [])) | set(budgets.get("measure", {}).get("api", []))

    area_score: dict[str, int] = {}
    area_files: dict[str, dict[str, int]] = {}
    for f in static["findings"]:
        w = SEVERITY_WEIGHT.get(f["severity"], 1)
        area_score[f["area"]] = area_score.get(f["area"], 0) + w
        area_files.setdefault(f["area"], {})
        area_files[f["area"]][f["file"]] = area_files[f["area"]].get(f["file"], 0) + w
    global_score = area_score.pop("shared-frontend", 0)

    results_by_route = {r["route"]: r for r in (last_run or {}).get("results", [])}

    items: list[dict] = []

    # 1. Measured breaches — real observed evidence outranks static suspicion.
    for route, res in results_by_route.items():
        if res.get("over_ceiling"):
            items.append(
                {
                    "priority": 100,
                    "kind": "ceiling-breach",
                    "route": route,
                    "evidence": "; ".join(res["over_ceiling"]),
                    "action": "regression — bisect the change and fix before anything else ships",
                }
            )
        elif res.get("over_budget"):
            items.append(
                {
                    "priority": 50 + area_score.get(area_of_route(route), 0),
                    "kind": "budget-breach",
                    "route": route,
                    "evidence": "; ".join(res["over_budget"]),
                    "action": "investigate; likely candidates are this area's static findings below",
                }
            )

    # 2. Static findings, heaviest files first — the "likely worst performance" queue.
    for area, files in sorted(area_files.items(), key=lambda kv: -sum(kv[1].values())):
        for file, score in sorted(files.items(), key=lambda kv: -kv[1]):
            lines = sorted(
                f"{f['rule']}:{f['line']}({f['severity'][0]})" for f in static["findings"] if f["file"] == file
            )
            items.append(
                {
                    "priority": 10 + score,
                    "kind": "static-finding",
                    "route": f"[{area}] {file}",
                    "evidence": ", ".join(lines),
                    "action": "fix the pattern or justify with a scoped `# nosemgrep` + reason",
                }
            )

    # 3. Areas with WARNING+ static findings but no measured route: blind spots.
    unmeasured_hot = []
    for area, score in area_score.items():
        area_routes = [r["rule"] for r in routes if area_of_route(r["rule"]) == area]
        if score >= SEVERITY_WEIGHT["WARNING"] and not any(r in measured for r in area_routes):
            unmeasured_hot.append(area)
            items.append(
                {
                    "priority": 10 + score,
                    "kind": "unmeasured-area",
                    "route": f"[{area}]",
                    "evidence": f"static score {score}, no route in .agents/perf/budgets.json measure lists",
                    "action": "add this area's key page + API routes to the measure lists",
                }
            )

    items.sort(key=lambda i: -i["priority"])

    ceiling_breaches = [i for i in items if i["kind"] == "ceiling-breach"]
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "static": {"status": static["status"], **({"reason": static["reason"]} if "reason" in static else {})},
        "summary": {
            "routes_considered": len(routes),
            "routes_measured": len(measured),
            "static_findings": len(static["findings"]),
            "global_shared_frontend_score": global_score,
            "last_run": (last_run or {}).get("generated"),
            "ceiling_breaches": len(ceiling_breaches),
            "budget_breaches": len([i for i in items if i["kind"] == "budget-breach"]),
            "unmeasured_hot_areas": unmeasured_hot,
        },
        "checklist": items,
    }


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------


def render_human(data: dict) -> str:
    s = data["summary"]
    out = ["perf triage"]
    out.append(
        f"  routes: {s['routes_considered']} considered, {s['routes_measured']} measured; "
        f"static: {data['static']['status']} ({s['static_findings']} findings); "
        f"last run: {s['last_run'] or 'none'}"
    )
    out.append(
        f"  breaches: {s['ceiling_breaches']} ceiling (blocking), {s['budget_breaches']} budget (advisory); "
        f"unmeasured hot areas: {', '.join(s['unmeasured_hot_areas']) or 'none'}"
    )
    if data["checklist"]:
        out.append("\n  checklist (highest priority first):")
        for i, item in enumerate(data["checklist"], 1):
            out.append(f"    {i:2}. [{item['priority']:3}] {item['kind']:15} {item['route']}")
            out.append(f"         {item['evidence']}")
            out.append(f"         → {item['action']}")
    else:
        out.append("  ✓ nothing to triage")
    return "\n".join(out)


def render_index(data: dict) -> str:
    s = data["summary"]
    lines = [
        "# Performance priority checklist — GENERATED",
        "",
        f"Generated {data['generated']} by `scripts/perf_triage.py --write-index`. Do not",
        "hand-edit; rerun the script after a page/flow changes or after a perf-test run.",
        "Budgets: `.agents/perf/budgets.json`; measurements: `tests/e2e/test_perf_budgets.py`;",
        "raw last run: `.agents/reports/perf/last-run.json`. Owned by the **perf-guardrails** skill.",
        "",
        f"- static rules: **{data['static']['status']}** ({s['static_findings']} findings, "
        f"shared-frontend score {s['global_shared_frontend_score']})",
        f"- routes measured: **{s['routes_measured']}** of {s['routes_considered']} considered",
        f"- last measured run: {s['last_run'] or 'none'}",
        f"- breaches: **{s['ceiling_breaches']} ceiling (blocking)**, {s['budget_breaches']} budget (advisory)",
        "",
        "| # | priority | kind | where | evidence | action |",
        "|---|---|---|---|---|---|",
    ]
    for i, item in enumerate(data["checklist"], 1):
        lines.append(
            f"| {i} | {item['priority']} | {item['kind']} | `{item['route']}` | {item['evidence']} | {item['action']} |"
        )
    if not data["checklist"]:
        lines.append("| – | – | – | – | nothing to triage | – |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic performance triage checklist.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--write-index", action="store_true", help=f"regenerate {INDEX_FILE.name}")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 on any ceiling breach or unmeasured area with WARNING-level findings",
    )
    args = parser.parse_args()

    try:
        data = build_triage()
    except Exception as exc:  # pragma: no cover - defensive
        msg = {"error": f"could not build triage: {exc}"}
        print(json.dumps(msg) if args.json else f"perf_triage: {msg['error']}", file=sys.stderr)
        return 2

    if args.write_index:
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        INDEX_FILE.write_text(render_index(data), encoding="utf-8")

    print(json.dumps(data, indent=2) if args.json else render_human(data))

    if args.check and (data["summary"]["ceiling_breaches"] or data["summary"]["unmeasured_hot_areas"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
