#!/usr/bin/env python3
"""Build and check the skill wiring graph.

The roster fingerprint in skill-index.md answers "does this skill exist". It cannot
answer the question that actually decides whether a skill ever runs: "does anything
route to it". A skill nothing calls is a skill that never fires, no matter how good its
instructions are — and that failure is invisible, because nothing errors.

This script walks .claude/skills/*/SKILL.md, builds the reference graph, and reports:

  orphan     no inbound references and not a declared root -> nothing can trigger it
  unindexed  registered but missing from skill-index.md    -> entrypoint can't route it
  unknown-root  declared a root but no longer exists       -> stale ROOTS entry

Deliberately NOT checked: handoff reciprocity ("A names B, so B must name A"). It was
tried and cut — it fired on 23 pairs, nearly all correct one-way caller→callee edges
(new-feature calls spec-first; spec-first has no business naming every caller). A check
that cries wolf 20+ times gets ignored, and then the real orphan is ignored with it.
Two-way handoffs stay a house-standard judgment for skill-smith to apply while reading,
not a gate.

Usage:
    python3 scripts/skill_graph.py             # human summary
    python3 scripts/skill_graph.py --json      # machine-readable
    python3 scripts/skill_graph.py --check     # exit 1 if any problem
    python3 scripts/skill_graph.py --skill fix-bug   # one skill's edges
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
INDEX = SKILLS_DIR / "entrypoint" / "skill-index.md"

# Skills that are legitimately uncalled: a human or a schedule invokes them. Everything
# else with no inbound edge is an orphan. This list is the one piece of curated judgment
# here — the graph itself is derived, but "is it *meant* to be a root" is a design fact.
ROOTS = {
    # engineering front doors — the user names these
    "entrypoint",
    "new-feature",
    "review-feature",
    "fix-bug",
    "deploy-runner",
    "dependency-update",
    # autonomous watchers — a schedule invokes these
    "prod-sentinel",
    "security-audit",
    "suite-warden",
    "perf-guardrails",
    "docs-truth",
    "skill-smith",
    "preflight",
    # user- or schedule-invoked test coverage authoring (test-evaluator is NOT a root:
    # it only ever runs when a caller hands it a batch, so its reachability is proven by
    # inbound edges, not by declaration)
    "test-author",
    # ad hoc, pointed at a file by a human
    "html-review",
    "js-review",
    "python-review",
    # founder-ops: business-operator is the front door, the rest are user-invoked
    # specialists whose triggers are conversational, not code-path
    "business-operator",
    "bize-product-manager",
    "calendar-planner",
    "community-triage",
    "competitor-watch",
    "compliance-project-assistant",
    "content-producer",
    "crm-updater",
    "cto-software-architect",
    "customer-success-onboarding",
    "discovery-synthesis",
    "distillery-strategy-advisor",
    "finance-advisor",
    "licence-study-coach",
    "marketing-director",
    "outbound-sales",
    "project-manager",
    "release-manager",
    "sales-manager",
    "sales-watches",
    "herdr-multi-agent-collab",
}


def skill_names() -> list[str]:
    if not SKILLS_DIR.is_dir():
        raise SystemExit(f"no skills dir at {SKILLS_DIR}")
    return sorted(p.name for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").exists())


def strip_frontmatter(text: str) -> str:
    """Drop YAML frontmatter.

    A skill's own description often names sibling skills as *contrast* ("not for X, use
    Y") — routing prose, not a wire. Counting those as edges would mark half the roster
    wired when nothing calls it.
    """
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :]
    return text


def build_graph(names: list[str]) -> dict[str, Any]:
    bodies = {n: strip_frontmatter((SKILLS_DIR / n / "SKILL.md").read_text(encoding="utf-8")) for n in names}
    outbound: dict[str, set[str]] = {n: set() for n in names}
    inbound: dict[str, set[str]] = {n: set() for n in names}

    for name, body in bodies.items():
        for other in names:
            if other == name:
                continue
            # word-boundary match so `preflight` doesn't match inside another word
            if re.search(rf"(?<![\w-]){re.escape(other)}(?![\w-])", body):
                outbound[name].add(other)
                inbound[other].add(name)
    return {"outbound": outbound, "inbound": inbound, "bodies": bodies}


def indexed_skills() -> set[str]:
    if not INDEX.exists():
        return set()
    text = INDEX.read_text(encoding="utf-8")
    # rows reference skills as `name` in backticks
    return set(re.findall(r"`([a-z0-9][a-z0-9-]+)`", text))


def fingerprint_entries() -> list[str] | None:
    """The roster fingerprint block under '## Roster fingerprint' in skill-index.md.

    Anchored to the heading, not to "the first fenced block" — the file has other code
    fences, and a naive fence match silently reads the wrong one, which is a fun way to
    report drift that isn't there.
    """
    if not INDEX.exists():
        return None
    text = INDEX.read_text(encoding="utf-8")
    if "## Roster fingerprint" not in text:
        return None
    section = text.split("## Roster fingerprint", 1)[1]
    block = re.search(r"```\n(.*?)```", section, re.S)
    return block.group(1).split() if block else None


def analyse() -> dict[str, Any]:
    names = skill_names()
    graph = build_graph(names)
    inbound, outbound = graph["inbound"], graph["outbound"]
    indexed = indexed_skills()

    orphans = [n for n in names if not inbound[n] and n not in ROOTS]
    unindexed = [n for n in names if n not in indexed]
    unknown_roots = sorted(ROOTS - set(names))

    fingerprint = fingerprint_entries()
    if fingerprint is None:
        fingerprint_drift = ["<no roster fingerprint block in skill-index.md>"]
    else:
        missing = [f"+{n}" for n in names if n not in fingerprint]  # on disk, not in index
        stale = [f"-{n}" for n in fingerprint if n not in names]  # in index, not on disk
        fingerprint_drift = missing + stale

    problems = {
        "orphans": orphans,
        "unindexed": unindexed,
        "unknown_roots": unknown_roots,
        "fingerprint_drift": fingerprint_drift,
    }
    return {
        "skill_count": len(names),
        "ok": not any(problems.values()),
        "problems": problems,
        "edges": {n: sorted(outbound[n]) for n in names},
        "inbound": {n: sorted(inbound[n]) for n in names},
        "roots": sorted(ROOTS & set(names)),
    }


def render(report: dict[str, Any]) -> str:
    p = report["problems"]
    out = [f"skill wiring: {report['skill_count']} skills, {len(report['roots'])} roots", ""]

    if p["orphans"]:
        out.append("  ORPHANS (nothing routes to them — they will never fire):")
        out += [f"    ✗ {n}" for n in p["orphans"]]
    if p["unindexed"]:
        out.append("  UNINDEXED (entrypoint cannot route them):")
        out += [f"    ✗ {n}" for n in p["unindexed"]]
    if p["unknown_roots"]:
        out.append("  STALE ROOTS (declared in ROOTS, no longer exist):")
        out += [f"    ✗ {n}" for n in p["unknown_roots"]]
    if p["fingerprint_drift"]:
        out.append("  FINGERPRINT DRIFT (+ on disk not in index, - in index not on disk):")
        out += [f"    ✗ {n}" for n in p["fingerprint_drift"]]

    if report["ok"]:
        out.append("  ✓ every skill is reachable from a root, indexed, and in the fingerprint")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build and check the skill wiring graph.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 if any problem")
    ap.add_argument("--skill", metavar="NAME", help="show one skill's edges")
    args = ap.parse_args()

    report = analyse()

    if args.skill:
        name = args.skill
        if name not in report["edges"]:
            print(f"unknown skill: {name}", file=sys.stderr)
            return 2
        print(f"{name}")
        print(f"  calls    : {', '.join(report['edges'][name]) or '(nothing)'}")
        print(f"  called by: {', '.join(report['inbound'][name]) or '(nothing)'}")
        print(f"  root     : {'yes' if name in report['roots'] else 'no'}")
        return 0

    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0 if report["ok"] or not args.check else 1


if __name__ == "__main__":
    sys.exit(main())
