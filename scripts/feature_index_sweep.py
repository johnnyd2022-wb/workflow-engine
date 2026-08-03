#!/usr/bin/env python3
"""Reconcile .agents/feature-index.md's `reviewed:` lines against what's actually true.

The index's `reviewed:` line is hand-updated by review-feature's Step 5, on completion,
in whichever worktree that review ran in. Two ways that goes stale:

  - A review finished and its report merged to main, but whoever wrote the line used a
    slug that doesn't match the report dir (identity/auth+org is the deliberate
    exception; dilution-calculator/dilution_calculator is an accidental hyphen/underscore
    split) -> the index undercounts real work.
  - A review is mid-flight in its own worktree (entrypoint's Run-now/Add-to-queue split
    cuts one per dispatch) and hasn't produced .agents/reports/<slug>/review.md yet ->
    the index still reads "never", so a second sweep offers the same slice again and
    collides with the run already in progress.

This script is read-mostly and narrowly write: it will turn "never" into a dated
"reviewed" line when a review.md proves it, and "never" into an "in progress" annotation
when a live worktree proves that, but it will NEVER remove or blank an existing dated
line — a stray same-named worktree appearing after a real review completed is a note in
the summary, not grounds to un-review a slice.

Usage:
    python3 scripts/feature_index_sweep.py                # sweep, write, human summary
    python3 scripts/feature_index_sweep.py --json          # machine-readable, still writes
    python3 scripts/feature_index_sweep.py --dry-run       # compute only, no file write
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = REPO_ROOT / ".agents" / "feature-index.md"
REPORTS_DIR = REPO_ROOT / ".agents" / "reports"

SLICE_HEADER_RE = re.compile(r"^## (?P<name>[^\n]+)$", re.MULTILINE)
REVIEWED_LINE_RE = re.compile(r"^(?P<indent>[ \t]*)reviewed:(?P<sp>[ \t]*)(?P<value>.*)$", re.MULTILINE)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass
class SliceStatus:
    slug: str
    index_line: str
    block_start: int
    block_end: int
    review_report_date: str | None = None
    review_report_path: str | None = None
    worktree_branch: str | None = None
    worktree_path: str | None = None
    worktree_since: str | None = None
    partial_artifacts: list[str] = field(default_factory=list)
    computed_status: str = "never"  # reviewed | in_review | partial | never
    action: str = "none"


def slug_variants(slug: str) -> list[str]:
    variants = [slug]
    if "-" in slug:
        variants.append(slug.replace("-", "_"))
    if "_" in slug:
        variants.append(slug.replace("_", "-"))
    return list(dict.fromkeys(variants))


def find_review_report(slug: str) -> tuple[str | None, str | None]:
    for variant in slug_variants(slug):
        report = REPORTS_DIR / variant / "review.md"
        if report.is_file():
            text = report.read_text(errors="replace")
            m = re.search(r"^date:\s*(.+)$", text, re.MULTILINE)
            dates = DATE_RE.findall(m.group(1)) if m else DATE_RE.findall(text[:200])
            date = dates[-1] if dates else None
            return date, str(report.relative_to(REPO_ROOT))
    return None, None


def find_partial_artifacts(slug: str) -> list[str]:
    """A review-feature run in progress always writes baseline.md first (Step 2), before
    review.md (Step 4). Report dirs can also hold new-feature's build-time artifacts
    (spec-critic, build-review, test-author, ...) for a slice that has never been through
    review-feature at all -- those aren't a stalled review, so baseline.md is the marker
    that distinguishes "review-feature started here" from "some other skill wrote here"."""
    for variant in slug_variants(slug):
        d = REPORTS_DIR / variant
        if d.is_dir():
            files = sorted(p.name for p in d.iterdir() if p.is_file())
            if "baseline.md" in files and "review.md" not in files:
                return files
    return []


def list_worktrees() -> list[dict[str, str]]:
    """git worktree list works from any checkout -- linked worktrees are visible
    repo-wide, so this doesn't need Herdr or the caller to be in a specific worktree."""
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    ).stdout
    worktrees = []
    current: dict[str, str] = {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[len("worktree "):]}
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):].removeprefix("refs/heads/")
    if current:
        worktrees.append(current)
    return worktrees


def worktree_since(path: str) -> str | None:
    try:
        ctime = Path(path).stat().st_ctime
        return datetime.fromtimestamp(ctime, tz=timezone.utc).strftime("%Y-%m-%d")
    except OSError:
        return None


def parse_slices(text: str) -> dict[str, SliceStatus]:
    headers = list(SLICE_HEADER_RE.finditer(text))
    slices: dict[str, SliceStatus] = {}
    for i, h in enumerate(headers):
        name = h.group("name").strip()
        block_start = h.end()
        block_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[block_start:block_end]
        if not re.search(r"^[ \t]*subscription:", block, re.MULTILINE):
            continue  # not a slice section (e.g. "Two axes", "Platform (not a slice)")
        rm = REVIEWED_LINE_RE.search(block)
        if not rm:
            continue
        slices[name] = SliceStatus(
            slug=name,
            index_line=rm.group("value").strip(),
            block_start=block_start + rm.start("value"),
            block_end=block_start + rm.end("value"),
        )
    return slices


def sweep() -> tuple[dict[str, SliceStatus], str]:
    text = INDEX.read_text()
    slices = parse_slices(text)
    worktrees = {w.get("branch"): w for w in list_worktrees() if w.get("branch")}

    for slug, s in slices.items():
        date, report_path = find_review_report(slug)
        s.review_report_date = date
        s.review_report_path = report_path

        wt = worktrees.get(f"review/{slug}")
        if wt:
            s.worktree_branch = wt["branch"]
            s.worktree_path = wt["path"]
            s.worktree_since = worktree_since(wt["path"])

        # Anchored: a genuine reviewed line starts with the date ("2026-07-26 (...)").
        # An in-progress annotation also *contains* a date ("started 2026-08-02") --
        # a bare search() would misread that as already reviewed.
        already_dated = bool(re.match(r"\d{4}-\d{2}-\d{2}", s.index_line.strip()))

        if date:
            s.computed_status = "reviewed"
            if not already_dated:
                s.action = f"index: never -> {date} (see {report_path})"
        elif wt:
            if already_dated:
                # A same-named worktree exists after a real review already landed --
                # note it, never blank the dated line to make room for it.
                s.computed_status = "reviewed"
                s.action = f"note: re-review worktree {wt['path']} is live, index date kept as-is"
            else:
                s.computed_status = "in_review"
                if s.index_line.strip().lower() == "never":
                    since = f", started {s.worktree_since}" if s.worktree_since else ""
                    s.action = f"index: never -> in progress ({wt['branch']} @ {wt['path']}{since})"
        else:
            partial = find_partial_artifacts(slug)
            s.partial_artifacts = partial
            if partial and s.index_line.strip().lower() == "never":
                s.computed_status = "partial"
                s.action = f"flag only: {len(partial)} report artifact(s), no review.md, no live worktree -- looks stalled"
            else:
                s.computed_status = "reviewed" if already_dated else "never"

    return slices, text


def apply_updates(slices: dict[str, SliceStatus], text: str) -> tuple[str, list[str]]:
    edits = []
    changed_lines = []
    for s in slices.values():
        if s.action.startswith("index:"):
            new_value = s.action.split("index: never -> ", 1)[1]
            edits.append((s.block_start, s.block_end, new_value))
            changed_lines.append(f"{s.slug}: {s.action}")
    if not edits:
        return text, changed_lines
    edits.sort(key=lambda e: e[0], reverse=True)
    for start, end, new_value in edits:
        text = text[:start] + new_value + text[end:]
    return text, changed_lines


def picklist_order(slices: dict[str, SliceStatus]) -> tuple[list[str], list[str]]:
    """never/partial first (file order, i.e. dict insertion order), then reviewed
    oldest-date-first, most-recent-last. in_review is excluded -- a sweep run for it
    is already underway, offering it again would collide."""
    never_or_partial = [s.slug for s in slices.values() if s.computed_status in ("never", "partial")]
    reviewed = [s for s in slices.values() if s.computed_status == "reviewed"]

    def sort_key(s: SliceStatus) -> str:
        dates = DATE_RE.findall(s.index_line)
        return dates[0] if dates else "9999-99-99"

    reviewed.sort(key=sort_key)
    excluded = [s.slug for s in slices.values() if s.computed_status == "in_review"]
    return never_or_partial + [s.slug for s in reviewed], excluded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="compute and report, don't write the index")
    args = parser.parse_args()

    slices, text = sweep()
    order, excluded = picklist_order(slices)

    changed_lines: list[str] = []
    if not args.dry_run:
        new_text, changed_lines = apply_updates(slices, text)
        if changed_lines:
            INDEX.write_text(new_text)

    if args.json:
        payload = {
            "slices": {
                s.slug: {
                    "index_line": s.index_line,
                    "computed_status": s.computed_status,
                    "review_report_date": s.review_report_date,
                    "review_report_path": s.review_report_path,
                    "worktree_branch": s.worktree_branch,
                    "worktree_path": s.worktree_path,
                    "worktree_since": s.worktree_since,
                    "partial_artifacts": s.partial_artifacts,
                    "action": s.action,
                }
                for s in slices.values()
            },
            "picklist_order": order,
            "excluded_in_review": excluded,
            "index_updated": bool(changed_lines) and not args.dry_run,
            "changes": changed_lines,
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"feature-index sweep: {len(slices)} slices, {len(excluded)} in review, "
          f"{sum(1 for s in slices.values() if s.computed_status == 'reviewed')} reviewed")
    if excluded:
        print("  in progress (excluded from picklist):")
        for slug in excluded:
            s = slices[slug]
            since = f", started {s.worktree_since}" if s.worktree_since else ""
            print(f"    - {slug}: {s.worktree_branch} @ {s.worktree_path}{since}")
    partials = [s for s in slices.values() if s.computed_status == "partial"]
    if partials:
        print("  partial (report artifacts but no review.md, no live worktree -- looks stalled):")
        for s in partials:
            print(f"    - {s.slug}: {', '.join(s.partial_artifacts)}")
    if changed_lines:
        print(f"  index updated ({'dry-run, not written' if args.dry_run else 'written'}):")
        for line in changed_lines:
            print(f"    - {line}")
    else:
        print("  index already matches ground truth, no changes")
    print(f"  picklist order: {', '.join(order)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
