#!/usr/bin/env python3
"""Index every documented finding, follow-up and known bug in the repo, and keep it true.

Why this exists: this repo documents its own debt *well* and then loses it. A
`review-feature` pass writes "→ **skill-smith**" at the bottom of a report, a
`security-audit` closes with "worth a follow-up ticket for the regex's coverage gap",
a spec leaves an open question — and every one of those is a real, already-triaged
action item that nobody will ever read again, because it is buried at line 150 of a
report in a directory nobody greps. The debt is not undocumented. It is unindexed.

So: a *deterministic* sweep, not an agent. Finding the items is pattern work — ripgrep
plus a markdown parser does it for free, every day, at zero token cost. Deciding what to
*do* about them is judgement, and that is the paired `findings-sweep` skill's job. This
script never fixes anything and never calls a model; it produces the worklist the skill
reads. Keeping that boundary is the whole point: an index that costs nothing to refresh
gets refreshed daily, and a worklist that is always current is one an agent can trust.

Three sources, because that is where this repo actually writes its findings:

  1. **Markdown sections** under a findings/follow-up/outstanding/known-issue heading,
     across `.agents/`, `.claude/skills/`, `docs/` and `tests/`. This is the big one —
     the repo has 105 "follow-up" mentions in markdown and exactly one `TODO` in code.
  2. **Code markers** — TODO/FIXME/HACK/XXX/BUG comments in `app/`, `tests/`, `scripts/`.
     Rare here, but free to collect and the conventional place to look.
  3. **GitLab MR descriptions** — open MRs whose description carries a follow-up section
     or unchecked `- [ ]` task, via `glab`. Deferred work agreed at review time.

And it is self-healing in both directions, which is what makes it safe to run unattended:

  - Every sweep re-reads the sources. An item whose text is gone is closed automatically
    (`done` if this loop had an MR open for it, `gone` if it vanished some other way).
  - A `Findings-Index:` trailer in a merged MR description closes the items that MR
    fixed, so the loop learns its own work landed without anyone telling it.
  - An item that reappears after being closed is reopened and flagged `regressed`, the
    same regression signal `finding_history.py` provides for review findings.
  - Verdicts a human already recorded in `finding_history.py` (false-positive,
    accepted-risk) suppress the matching item, so the loop cannot re-raise something a
    human already rejected. Suppression is only ever *read* from that store, never
    written here — granting it is a human's call, per `.agents/autonomy.md`.

Usage:
    python3 scripts/findings_index.py sweep              # refresh the index, human summary
    python3 scripts/findings_index.py sweep --json       # same, machine-readable
    python3 scripts/findings_index.py sweep --dry-run    # compute only, write nothing
    python3 scripts/findings_index.py next               # top N outstanding, budget-sized
    python3 scripts/findings_index.py next --limit 2     # ignore budget, take exactly 2
    python3 scripts/findings_index.py budget             # how many items today's quota affords
    python3 scripts/findings_index.py record --id a1b2c3d4 --status in-progress
    python3 scripts/findings_index.py --check            # exit 1 if the store is malformed

Exit codes: 0 = ok, 1 = malformed store / bad input, 2 = usage.

Stdlib only, no app imports: this runs on a timer, before and independently of the app.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_JSON = REPO_ROOT / ".agents" / "findings-index.json"
INDEX_MD = REPO_ROOT / ".agents" / "findings-index.md"
CONFIG_PATH = REPO_ROOT / ".agents" / "findings-index-config.json"
RATE_CACHE = Path.home() / ".claude" / "rate-limits-cache.json"
FINDING_HISTORY = REPO_ROOT / "scripts" / "finding_history.py"

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# sweep scope
#
# Derived from where the skills actually write (grepped out of .claude/skills/**),
# not guessed. Three exclusions are deliberate and load-bearing:
#
#   .claude/worktrees/  — each worktree is a FULL copy of the repo. Sweeping it would
#                         index every finding two to six times over, and the duplicates
#                         would carry different paths so dedup by id wouldn't save us.
#   .claude/agents/     — the founder's business workspace (Whistlebird/Biz-E). CLAUDE.md
#                         is explicit that it is not this codebase's engineering surface;
#                         its "follow-ups" are marketing tasks, not code the skill can fix.
#   cursor_instructions/— historical planning docs, pre-dating the skill suite. Their
#                         follow-up sections describe work long since done or abandoned,
#                         so indexing them would fill the worklist with archaeology.
# ---------------------------------------------------------------------------

DOC_ROOTS = (".agents", "docs")
CODE_ROOTS = ("app", "tests", "scripts", "migrations")

EXCLUDE_GLOBS = (
    "!.git/**",
    "!node_modules/**",
    "!.claude/worktrees/**",
    "!.claude/agents/**",
    "!cursor_instructions/**",
    "!**/__pycache__/**",
    "!*.lock",
    "!uv.lock",
    # This index and its own reports describe findings; sweeping them would re-index
    # every item as a new finding on the next tick, forever.
    "!.agents/findings-index.md",
    "!.agents/reports/findings-sweep/**",
    # Policy and format-specification documents. These describe what a finding LOOKS
    # like ("- F1 [fix|false-positive|accepted-risk] <file:line> <description>") rather
    # than stating one. Sweeping them indexed the templates themselves as P0 security
    # findings -- the single largest source of noise in the first real run.
    "!.agents/autonomy.md",
    "!.agents/conventions.md",
    "!.agents/verification-chain.md",
    "!.agents/ci-gate-setup.md",
    "!.agents/history/README.md",
    "!**/TEST_DOCUMENTATION.md",
)

# ---------------------------------------------------------------------------
# extraction patterns
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
BULLET_RE = re.compile(r"^(?P<indent>[ \t]*)(?:[-*+]|\d+\.)\s+(?P<text>.*)$")
CHECKBOX_RE = re.compile(r"^\[(?P<mark>[ xX])\]\s*(?P<rest>.*)$")

# Headings that open a section of actionable items. Matched against the heading text,
# case-insensitively. Kept deliberately tight -- "## Notes" or "## Summary" are prose,
# and pulling bullets out of them would bury the real items in narration.
FINDING_HEADINGS = (
    (re.compile(r"\bfollow[- ]?ups?\b", re.I), "follow-up"),
    (re.compile(r"\bfindings?\b", re.I), "finding"),
    (re.compile(r"\boutstanding\b", re.I), "outstanding"),
    (re.compile(r"\bknown (?:issues?|bugs?|gaps?|limitations?)\b", re.I), "known-issue"),
    (re.compile(r"\bdeferred\b", re.I), "deferred"),
    (re.compile(r"\b(?:action items?|next steps?|todo)\b", re.I), "action"),
    (re.compile(r"\b(?:coverage )?gaps?\b", re.I), "gap"),
    (re.compile(r"\bopen questions?\b", re.I), "open-question"),
    (re.compile(r"\bnot done\b", re.I), "deferred"),
)

# Code comment markers. `NOTE` is deliberately absent: this repo uses it for explanatory
# commentary ("NOTE: this is intentional"), not for work owed, so indexing it would be
# pure noise.
CODE_MARKER_RE = re.compile(r"(?:^|[^\w])(?P<marker>TODO|FIXME|HACK|XXX|BUG)\b[:\s(]*(?P<text>.*)$")
CODE_MARKER_RG = r"\b(TODO|FIXME|HACK|XXX|BUG)\b"

# Text that means an item is already dealt with, so it should not enter the worklist.
RESOLVED_MARKERS = re.compile(
    r"(^\s*(?:✅|✔|~~))|(\b(?:done|resolved|fixed|shipped|landed|completed|no longer)\b\s*[.:—-]?\s*$)"
    r"|(\bresolved (?:in|by)\b)|(\bfixed (?:in|by)\b)|(\balready (?:done|fixed|handled)\b)",
    re.I,
)

# A file path, optionally with a line or line-range, as this repo writes them in prose:
# `backend.py:2679`, `app/utils/config_loader.py:153-155`, `inventory_quantity_guard.py:57-70`.
CODE_REF_RE = re.compile(
    r"`?(?P<path>(?:[\w.-]+/)*[\w.-]+\.(?:py|js|html|css|sql|ini|toml|ya?ml|md|sh))"
    r"(?::(?P<line>\d+)(?:-\d+)?)?`?"
)

# The handoff arrow this repo's reports use to name the skill that owns an item:
# "Belongs to auth/org, not inventory → **follow-up review-feature pass**."
# security-audit reports use an explicit `route: **fix-bug**` line for the same purpose.
HANDOFF_RE = re.compile(r"(?:(?:→|->)|\broute:)\s*\*\*(?P<skill>[a-z][\w -]*)\*\*", re.I)

# ---------------------------------------------------------------------------
# actionability gates
#
# The first real sweep returned 182 items, and the top of the P0 list was almost entirely
# noise: format templates out of SKILL.md, findings a human had already ruled
# false-positive, and reports whose own header said `verdict: clean`. The three gates
# below are what separate "text that resembles a finding" from "work that is actually
# owed", and they are all read from conventions this repo already writes down.
# ---------------------------------------------------------------------------

# A report header field: `verdict: clean | patched | findings-open`. `clean` and
# `patched` mean the report closed its own findings, so nothing in it is owed.
VERDICT_RE = re.compile(r"^\s*(?:##\s*)?verdict:\s*(?P<verdict>[a-z-]+)", re.I | re.M)
VERDICT_CLOSED = {"clean", "patched", "no-findings", "pass", "valid", "sound"}

# The per-finding disposition this repo tags: `F1 [fix]`, `F2 [false-positive]`,
# `F3 [accepted-risk]`. Only `fix` is owed. The other two are recorded human judgements
# and re-raising them is exactly what finding_history.py exists to prevent.
DISPOSITION_RE = re.compile(r"^\s*(?:\*\*)?[A-Z]{1,3}\d+(?:\*\*)?\s*\[(?P<disp>[^\]]+)\]", re.I)
DISPOSITION_CLOSED = re.compile(r"\b(?:false[- ]positive|accepted[- ]risk|wont?[- ]fix|no[- ]action)\b", re.I)

# Placeholder syntax from a format spec rather than a real finding: `<file:line>`,
# `<slug>`, `<one-line description>`, or an alternation of every allowed disposition.
TEMPLATE_RE = re.compile(r"<[a-z][\w :|-]*>|\[[a-z-]+\|[a-z-]+(?:\|[a-z-]+)*\]", re.I)

# `patch: not applied` keeps an item open; `patch: <commit sha / diff summary>` means it
# already shipped. Read only when a disposition line is present, so ordinary prose using
# the word "patch" cannot accidentally close an item.
PATCH_APPLIED_RE = re.compile(r"\bpatch:\s*(?!not applied|none|n/a|not yet|pending)\S", re.I)

# The trailer a merged MR carries to close the items it fixed. The skill writes it; this
# script reads it back on the next sweep. That round trip is how the loop learns its own
# work landed without anyone updating the index by hand.
TRAILER_RE = re.compile(r"^\s*Findings-Index:\s*(?P<ids>[0-9a-f, ]+)\s*$", re.I | re.M)

# ---------------------------------------------------------------------------
# priority
#
# The script assigns a *signal*, not a verdict. Keyword tiers are crude and the skill is
# expected to overrule them on read -- but a crude ordering that runs daily beats a
# perfect ordering that needs a model to produce. Security first, cosmetics last, which
# is the ordering the founder asked for.
# ---------------------------------------------------------------------------

PRIORITY_TIERS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "P0",
        "security",
        # Two exclusions here are load-bearing, both found by reading real misfires:
        #   `auth\w*` also matches "author"/"authored"/"authors", which appear in nearly
        #     every report footer -- so authentication is spelled out instead.
        #   bare `token` matches "token cost" (LLM spend), which is how a docs proposal
        #     about skill economics was ranked a P0 security finding.
        re.compile(
            r"\b(?:security|vulnerab\w*|injection|sql[- ]injection|xss|csrf|ssrf|"
            r"auth|authn|authz|authentication|authoris\w*|authoriz\w*|unauthoris\w*|unauthoriz\w*|"
            r"tenant|org[_ ]id|cross[- ]org|multi[- ]tenant|leak\w*|secret|"
            r"credential|(?:auth|access|refresh|bearer|csrf|session|api)[-_ ]?tokens?|"
            r"password|cve|exploit|privilege|escalat\w*|bypass)\b",
            re.I,
        ),
    ),
    (
        "P1",
        "data-integrity",
        re.compile(
            r"\b(?:data[- ]loss|corrupt\w*|destructive|irreversible|drop (?:column|table)|"
            r"migration|alembic|downgrade|idempoten\w*|race condition|deadlock|"
            r"double[- ](?:write|charge|count)|wrong (?:result|total|quantity)|"
            r"incorrect\w*|miscalculat\w*)\b",
            re.I,
        ),
    ),
    (
        "P2",
        "performance",
        re.compile(
            r"\b(?:performance|perf\b|n\+1|slow\w*|latency|lcp|web[- ]vitals?|timeout|"
            r"memory leak|query count|budget breach|throughput)\b",
            re.I,
        ),
    ),
    (
        "P3",
        "reliability",
        re.compile(
            r"\b(?:flak\w*|brittle|fails? (?:closed|open)|error handling|retry|crash\w*|"
            r"regression|coverage|untested|no test|missing test|observability|logging|"
            r"broken|stale|drift)\b",
            re.I,
        ),
    ),
    (
        "P4",
        "maintainability",
        re.compile(r"\b(?:refactor\w*|cleanup|clean up|tidy|dead code|duplicat\w*|rename|docs?|documentation)\b", re.I),
    ),
)
COSMETIC_RE = re.compile(r"\b(?:cosmetic|nice[- ]to[- ]have|polish|wording|typo|style|whitespace|formatting)\b", re.I)
DEFAULT_PRIORITY = ("P4", "maintainability")

# Source weighting: a finding written by the security-audit skill is a security finding
# even if its prose never says "security".
SOURCE_TIER_HINTS = (
    (re.compile(r"/security-audit|/security/"), ("P0", "security")),
    (re.compile(r"/migrations?/"), ("P1", "data-integrity")),
    (re.compile(r"/perf/|perf-guardrails"), ("P2", "performance")),
)

STATUSES = (
    "outstanding",  # in the index, nobody has started it
    "in-progress",  # a skill run has claimed it this session
    "mr-open",  # fixed, MR pushed, waiting on review/merge
    "done",  # merged, or its source text is gone after we had an MR open
    "gone",  # source text disappeared without this loop shipping anything
    "suppressed",  # finding_history.py records a human false-positive/accepted-risk
    "wont-fix",  # explicitly declined; only a human sets this
)
OPEN_STATUSES = ("outstanding", "in-progress", "mr-open")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# item model
# ---------------------------------------------------------------------------


@dataclass
class Item:
    """One documented finding, keyed by a signature that survives line moves."""

    id: str
    title: str
    detail: str
    kind: str
    source_path: str
    source_line: int
    source_ref: str = ""  # "!141" for MR-sourced items
    code_refs: list[str] = field(default_factory=list)
    owner_skill: str = ""
    priority: str = "P4"
    impact: str = "maintainability"

    def to_new_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "detail": self.detail,
            "kind": self.kind,
            "source": {
                "path": self.source_path,
                "line": self.source_line,
                "ref": self.source_ref,
            },
            "code_refs": self.code_refs,
            "owner_skill": self.owner_skill,
            "priority": self.priority,
            "impact": self.impact,
            "status": "outstanding",
            "status_reason": "newly indexed",
            "first_seen": today(),
            "last_seen": today(),
            "attempts": 0,
            "mr": "",
            "history": [{"at": utc_now(), "status": "outstanding", "why": "newly indexed"}],
        }


def normalise_for_signature(text: str) -> str:
    """Collapse a finding to the words that identify it.

    Strips markdown emphasis, backticks, links and line/column numbers, so the same
    finding keeps one id when a report is reflowed, a path gains a line number, or
    someone bolds a phrase. Truncated to the first 24 significant words: enough to be
    specific, short enough that appending a sentence to a bullet doesn't mint a new item.
    """
    t = text.lower()
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)  # [text](link) -> text
    t = re.sub(r"[`*_~]+", "", t)  # markdown emphasis
    t = re.sub(r":\d+(?:-\d+)?\b", "", t)  # file.py:123 -> file.py
    t = re.sub(r"[^a-z0-9./_-]+", " ", t)
    words = [w for w in t.split() if w]
    return " ".join(words[:24])


def make_id(source_path: str, signature_text: str) -> str:
    """Stable 8-hex id. Scoped by source file so the same sentence in two reports stays
    two items -- they are genuinely two claims, and closing one should not close the other.

    sha256 rather than sha1 purely to keep the semgrep gate clean. This is content
    addressing, not a signature -- nobody is attacking the findings index, and truncating
    to 8 hex characters makes the choice of digest irrelevant to collision odds anyway --
    but a blocking scanner finding costs more to explain on every future run than the
    one-word change costs to make.
    """
    basis = f"{source_path}\x00{normalise_for_signature(signature_text)}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:8]


# How much of a finding counts as its "lead". Findings in this repo are long -- a single
# bullet routinely runs 1200 characters across repro steps, impact analysis and a
# recommended fix. Classifying on the whole body made almost everything P0, because any
# finding that so much as *mentions* auth or org_id in its evidence matched the security
# tier. A finding states what it IS in its opening sentence; that is what gets classified.
LEAD_CHARS = 260


def classify_priority(text: str, source_path: str) -> tuple[str, str]:
    """Highest matching tier wins; source hints can only raise, never lower.

    The lead is authoritative. The remainder of the body is consulted only to break a
    tie into the *default* tier -- so a finding whose body discusses performance but
    whose lead says nothing classifiable still lands on P2 rather than P4, without
    letting a passing mention of "token" in paragraph four claim P0.
    """
    lead = text[:LEAD_CHARS]

    def first_match(haystack: str) -> tuple[str, str] | None:
        for tier, impact, pattern in PRIORITY_TIERS:
            if pattern.search(haystack):
                return (tier, impact)
        return None

    if COSMETIC_RE.search(lead):
        best: tuple[str, str] | None = ("P4", "cosmetic")
    else:
        best = first_match(lead)
        if best is None:
            body_match = first_match(text)
            # A body-only signal is weak evidence: accept it, but never for the top two
            # tiers, which should require the finding to lead with the claim.
            best = body_match if body_match and body_match[0] >= "P2" else None

    if best is None:
        best = DEFAULT_PRIORITY
    for pattern, hinted in SOURCE_TIER_HINTS:
        if pattern.search(source_path) and hinted[0] < best[0]:
            best = hinted
    return best


def extract_code_refs(text: str) -> list[str]:
    """Pull `path.py:123` references out of prose -- the 'where in the code it lives'
    half of the index. Deduped, order preserved, capped so one reference-heavy bullet
    cannot dominate the rendered table."""
    refs: list[str] = []
    for m in CODE_REF_RE.finditer(text):
        path = m.group("path")
        # A bare "README.md" or "config.toml" with no directory is usually prose, not a
        # locator. Keep it only when it carries a line number, which implies a real site.
        if "/" not in path and not m.group("line"):
            continue
        ref = f"{path}:{m.group('line')}" if m.group("line") else path
        if ref not in refs:
            refs.append(ref)
    return refs[:6]


def summarise(text: str, limit: int = 120) -> str:
    """First sentence-ish, flattened to one line, for the index table."""
    flat = re.sub(r"\s+", " ", text).strip()
    flat = re.sub(r"^\*\*(.+?)\*\*[.:]?\s*", r"\1. ", flat)  # promote a bold lead-in
    cut = flat.split(". ")[0].strip().rstrip(".")
    if len(cut) < 20 and len(flat) > len(cut):
        cut = flat
    return (cut[: limit - 1] + "…") if len(cut) > limit else cut


# ---------------------------------------------------------------------------
# source 1 + 2: the working tree, found with ripgrep
# ---------------------------------------------------------------------------


def _rg(args: list[str], timeout: int = 60) -> list[str] | None:
    """Run ripgrep and return stdout lines, or **None if the scan could not be run**.

    That None is not pedantry. Callers use "did this source get scanned?" to decide
    whether an item's absence means it was resolved or merely unseen -- and conflating
    "ripgrep is missing" with "found nothing" would close every tracked item in the index
    at once, silently. Exit code 1 genuinely means no matches and returns an empty list.
    """
    if not shutil.which("rg"):
        return None
    try:
        proc = subprocess.run(
            ["rg", *args], capture_output=True, text=True, timeout=timeout, cwd=REPO_ROOT, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode not in (0, 1):
        return None
    return [line for line in proc.stdout.splitlines() if line]


def _exclude_args() -> list[str]:
    out: list[str] = []
    for glob in EXCLUDE_GLOBS:
        out += ["-g", glob]
    return out


def find_candidate_docs() -> list[Path] | None:
    """Files worth parsing in full, or None if the scan could not run (see `_rg`).

    ripgrep narrows thousands of files to dozens in milliseconds; the Python parser then
    only has to read the ones that can match.

    `--hidden` is required: everything that matters here lives under `.agents/` and
    `.claude/`, which ripgrep skips by default.
    """
    roots = [r for r in DOC_ROOTS if (REPO_ROOT / r).exists()]
    if not roots:
        return []
    pattern = "|".join(p.pattern for _, p in [(k, pat) for pat, k in FINDING_HEADINGS])
    args = [
        "--hidden",
        "--files-with-matches",
        "--ignore-case",
        "-g",
        "*.md",
        *_exclude_args(),
        "-e",
        r"^#{1,6}\s+.*(" + pattern + ")",
        *roots,
    ]
    lines = _rg(args)
    return None if lines is None else [REPO_ROOT / line for line in lines]


def parse_doc(path: Path) -> list[Item]:
    """Extract heading-scoped bullets from one markdown file.

    Only bullets *inside* a findings/follow-up/outstanding section are taken. That
    scoping is what keeps the index signal-dense: `.agents/autonomy.md` says
    "follow-up" in policy prose and contributes nothing, while
    `.agents/reports/inventory/review.md` contributes its five real handoffs.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    rel = path.relative_to(REPO_ROOT).as_posix()

    # A report that closed itself owes nothing. Checked against the FIRST verdict in the
    # file (the header), not the last -- `.agents/reports/**` reports restate the verdict
    # in a trailing footer, and a later `findings-open` in prose must not reopen a report
    # whose header says clean.
    verdict = VERDICT_RE.search(text)
    if verdict and verdict.group("verdict").lower() in VERDICT_CLOSED:
        return []

    lines = text.splitlines()
    items: list[Item] = []
    section: tuple[int, str] | None = None  # (heading level, kind)
    i = 0

    while i < len(lines):
        line = lines[i]

        heading = HEADING_RE.match(line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2)
            kind = next((k for pattern, k in FINDING_HEADINGS if pattern.search(title)), None)
            if kind:
                section = (level, kind)
            elif section and level <= section[0]:
                section = None  # a sibling/parent heading closes the section
            i += 1
            continue

        bullet = BULLET_RE.match(line) if section else None
        if bullet:
            indent = len(bullet.group("indent").expandtabs(4))
            block = [bullet.group("text").strip()]
            j = i + 1
            # Gather continuation lines: this repo wraps bullets across 3-5 lines, and a
            # finding truncated at the first newline loses the part naming the file.
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip() or HEADING_RE.match(nxt):
                    break
                nxt_bullet = BULLET_RE.match(nxt)
                if nxt_bullet and len(nxt_bullet.group("indent").expandtabs(4)) <= indent:
                    break
                block.append(nxt.strip())
                j += 1

            body = " ".join(block).strip()
            item = _item_from_bullet(body, rel, i + 1, section[1])
            if item:
                items.append(item)
            i = j
            continue

        i += 1

    return items


def _item_from_bullet(body: str, rel: str, line_no: int, kind: str) -> Item | None:
    """Turn one gathered bullet into an Item, or None if it is not actionable."""
    if not body or len(body) < 15:
        return None

    checkbox = CHECKBOX_RE.match(body)
    if checkbox:
        if checkbox.group("mark").lower() == "x":
            return None  # already ticked
        body = checkbox.group("rest").strip()

    if RESOLVED_MARKERS.search(body):
        return None

    # Format-spec placeholder, not a finding.
    if TEMPLATE_RE.search(body):
        return None

    # A tagged finding carries its own disposition; honour it.
    disposition = DISPOSITION_RE.match(body)
    if disposition:
        if DISPOSITION_CLOSED.search(disposition.group("disp")):
            return None
        if PATCH_APPLIED_RE.search(body):
            return None  # `patch: <commit>` — already shipped

    priority, impact = classify_priority(body, rel)
    handoff = HANDOFF_RE.search(body)
    return Item(
        id=make_id(rel, body),
        title=summarise(body),
        detail=re.sub(r"\s+", " ", body).strip()[:1200],
        kind=kind,
        source_path=rel,
        source_line=line_no,
        code_refs=extract_code_refs(body),
        owner_skill=handoff.group("skill").strip().lower() if handoff else "",
        priority=priority,
        impact=impact,
    )


def scan_code_markers() -> list[Item] | None:
    """TODO/FIXME/HACK/XXX/BUG comments in the code roots, or None if the scan failed.

    Sparse in this repo (one TODO at time of writing) but free to collect, and the first
    place a new contributor would leave a note.
    """
    roots = [r for r in CODE_ROOTS if (REPO_ROOT / r).exists()]
    if not roots:
        return []
    args = [
        "--hidden",
        "--line-number",
        "--no-heading",
        "--with-filename",
        *_exclude_args(),
        "-e",
        CODE_MARKER_RG,
        *roots,
    ]

    lines = _rg(args)
    if lines is None:
        return None

    items: list[Item] = []
    for raw in lines:
        parts = raw.split(":", 2)
        if len(parts) < 3:
            continue
        rel, line_s, content = parts[0], parts[1], parts[2]
        try:
            line_no = int(line_s)
        except ValueError:
            continue
        m = CODE_MARKER_RE.search(content)
        if not m:
            continue
        marker, text = m.group("marker"), m.group("text").strip()
        # A bare marker with no following text says nothing actionable, and a marker
        # inside this file's own patterns is self-reference.
        if not text or len(text) < 10 or rel == "scripts/findings_index.py":
            continue
        if RESOLVED_MARKERS.search(text):
            continue
        priority, impact = classify_priority(f"{marker} {text}", rel)
        body = f"{marker}: {text}"
        items.append(
            Item(
                id=make_id(rel, body),
                title=summarise(body),
                detail=body[:1200],
                kind="code-marker",
                source_path=rel,
                source_line=line_no,
                code_refs=[f"{rel}:{line_no}"],
                priority=priority,
                impact=impact,
            )
        )
    return items


# ---------------------------------------------------------------------------
# source 3: GitLab merge requests
# ---------------------------------------------------------------------------


def _glab_json(args: list[str], timeout: int = 45) -> Any | None:
    """Run a glab subcommand and parse its JSON, or None on any failure.

    A sweep must never crash because glab is missing, unauthed, or GitLab is briefly
    down -- the tree sources still produce a useful index without it. Note glab writes a
    'cannot start document portal' warning to *stderr* under systemd; capturing stdout
    separately is what keeps that out of the JSON parse.
    """
    if not shutil.which("glab"):
        return None
    try:
        proc = subprocess.run(
            ["glab", *args], capture_output=True, text=True, timeout=timeout, cwd=REPO_ROOT, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def scan_open_mrs() -> list[Item] | None:
    """Follow-ups and unchecked tasks in open MR descriptions, or None if glab could not
    be reached.

    The None matters: glab being missing, unauthed, or GitLab being briefly down is an
    expected degraded state, and treating it as "there are no MR findings" would close
    every MR-sourced item in the index as resolved.
    """
    data = _glab_json(["mr", "list", "--output", "json", "--per-page", "50"])
    if not isinstance(data, list):
        return None

    items: list[Item] = []
    for mr in data:
        iid, desc = mr.get("iid"), mr.get("description") or ""
        if not iid or not desc:
            continue
        ref = f"!{iid}"
        pseudo_path = f"gitlab:{ref}"
        title = (mr.get("title") or "").strip()

        for item in _parse_mr_description(desc, pseudo_path):
            item.source_ref = ref
            item.detail = f"[{ref} {title}] {item.detail}"[:1200]
            items.append(item)
    return items


def _parse_mr_description(desc: str, pseudo_path: str) -> list[Item]:
    """MR descriptions use the same heading+bullet shape as the reports, plus bare
    `- [ ]` task lists outside any heading -- GitLab renders those as a task list and
    the repo uses them for agreed-but-deferred work."""
    lines = desc.splitlines()
    items: list[Item] = []
    section: tuple[int, str] | None = None

    for idx, line in enumerate(lines):
        heading = HEADING_RE.match(line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2)
            kind = next((k for pattern, k in FINDING_HEADINGS if pattern.search(title)), None)
            if kind:
                section = (level, kind)
            elif section and level <= section[0]:
                section = None
            continue

        bullet = BULLET_RE.match(line)
        if not bullet:
            continue
        body = bullet.group("text").strip()
        checkbox = CHECKBOX_RE.match(body)
        # Take a bullet if it's in a findings section, OR if it's an unchecked task box
        # anywhere in the description.
        if not section and not (checkbox and checkbox.group("mark").lower() != "x"):
            continue
        item = _item_from_bullet(body, pseudo_path, idx + 1, section[1] if section else "mr-task")
        if item:
            items.append(item)
    return items


def merged_mr_closures(since_days: int) -> tuple[dict[str, str], list[str]]:
    """Map item-id -> "!N" for items closed by MRs merged in the window.

    This is the loop's feedback path. The `findings-sweep` skill puts a
    `Findings-Index: <id>, <id>` trailer in every MR it opens; when that MR merges, this
    reads the trailer back and closes the items. No trailer, no closure -- the script
    never guesses that an MR fixed a finding from title similarity, because a wrong
    auto-close silently drops real work off the list.

    Returns (closures, merged_refs_seen).
    """
    data = _glab_json(["mr", "list", "--merged", "--output", "json", "--per-page", "50"])
    if not isinstance(data, list):
        return {}, []

    cutoff = time.time() - since_days * 86400
    closures: dict[str, str] = {}
    seen: list[str] = []

    for mr in data:
        merged_at = mr.get("merged_at")
        if not merged_at:
            continue
        try:
            ts = datetime.strptime(merged_at[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC).timestamp()
        except ValueError:
            continue
        if ts < cutoff:
            continue
        ref = f"!{mr.get('iid')}"
        seen.append(ref)
        for match in TRAILER_RE.finditer(mr.get("description") or ""):
            for raw_id in match.group("ids").split(","):
                item_id = raw_id.strip().lower()
                if item_id:
                    closures[item_id] = ref
    return closures, seen


# ---------------------------------------------------------------------------
# human-recorded suppression, read from finding_history.py
# ---------------------------------------------------------------------------


def suppressed_ids(items: Iterable[Item]) -> dict[str, str]:
    """Ask finding_history.py whether a human already ruled on each item.

    Only ever *reads* that store. `.agents/autonomy.md` is explicit that an agent may
    recommend accepted-risk but only a human grants it, so this script can consume a
    recorded suppression and must never create one.

    Two details of `finding_history.py`'s contract are load-bearing, and getting either
    wrong fails SILENTLY -- the lookup just never matches, and a finding a human already
    rejected gets re-raised every single day:

      - `--json` is required. Without it `decide` prints human text ("new  (sig abc123)")
        which is not parseable, so every lookup is discarded by the JSONDecodeError path.
      - The verdict key is **`action`**, not `decision`, and the suppressing value is
        `"suppress"` (set when the last recorded human verdict was false-positive or
        accepted-risk -- see `finding_history.py:187`).
    """
    if not FINDING_HISTORY.exists():
        return {}
    out: dict[str, str] = {}
    for item in items:
        area = item.source_path.rsplit("/", 1)[0] if "/" in item.source_path else item.source_path
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(FINDING_HISTORY),
                    "decide",
                    "--area",
                    area,
                    "--kind",
                    item.impact,
                    "--evidence",
                    item.detail[:400],
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=REPO_ROOT,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if proc.returncode != 0 or not proc.stdout.strip():
            continue
        try:
            verdict = json.loads(proc.stdout)
        except json.JSONDecodeError:
            continue
        if isinstance(verdict, dict) and verdict.get("action") == "suppress":
            out[item.id] = f"human verdict '{verdict.get('last_verdict')}' recorded in finding_history"
    return out


# ---------------------------------------------------------------------------
# quota-aware budget
# ---------------------------------------------------------------------------


def load_config() -> dict[str, Any]:
    defaults = {
        "merged_lookback_days": 2,
        "budget_ladder": [
            {"max_five_hour_pct": 35, "max_seven_day_pct": 45, "items": 4},
            {"max_five_hour_pct": 55, "max_seven_day_pct": 65, "items": 3},
            {"max_five_hour_pct": 75, "max_seven_day_pct": 80, "items": 2},
            {"max_five_hour_pct": 88, "max_seven_day_pct": 92, "items": 1},
        ],
        "budget_when_unknown": 2,
        "budget_ceiling_pct": 88,
        "quota_cache_max_age_sec": 86400,
    }
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            defaults.update({k: v for k, v in user.items() if not k.startswith("_")})
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def read_quota(cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort quota reading from the statusline cache.

    Same limitation slack_watch.py documents: `claude -p` carries no rate_limits field,
    so this cache -- refreshed only when an interactive session renders -- is the sole
    place the percentage exists. It is therefore advisory. The staleness window here is
    much wider than slack_watch's 30 minutes (a full day) because the consequence is
    different: slack_watch uses it to *block* a launch, where a wrong read strands a
    request; this uses it to *size* a batch, where a wrong read just means today's run
    takes two items instead of three.
    """
    if not RATE_CACHE.exists():
        return None
    try:
        data = json.loads(RATE_CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    age = time.time() - float(data.get("captured_at", 0))
    if age > cfg.get("quota_cache_max_age_sec", 86400):
        return None
    five = (data.get("five_hour") or {}).get("used_percentage")
    seven = (data.get("seven_day") or {}).get("used_percentage")
    if five is None and seven is None:
        return None
    return {
        "five_hour_pct": float(five) if five is not None else 0.0,
        "seven_day_pct": float(seven) if seven is not None else 0.0,
        "age_sec": int(age),
    }


def compute_budget(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """How many items this run should take on.

    The founder asked for "2 a day, but take more when we can afford it". This is that
    rule, as data: walk the ladder from most-generous to least and take the first rung
    BOTH windows fit under. The 7-day window is in the test deliberately -- a Pro plan
    can look fine on the 5h window every single day and still burn the week by Thursday.
    """
    cfg = cfg or load_config()
    quota = read_quota(cfg)
    if quota is None:
        n = int(cfg.get("budget_when_unknown", 2))
        return {"items": n, "why": "no fresh quota reading; using the configured default", "quota": None}

    ceiling = float(cfg.get("budget_ceiling_pct", 88))
    if quota["five_hour_pct"] >= ceiling or quota["seven_day_pct"] >= ceiling:
        return {
            "items": 0,
            "why": (
                f"5h at {quota['five_hour_pct']:.0f}%, 7d at {quota['seven_day_pct']:.0f}% "
                f"— at/over the {ceiling:.0f}% ceiling, so this run stands down"
            ),
            "quota": quota,
        }

    for rung in cfg.get("budget_ladder", []):
        if quota["five_hour_pct"] < rung["max_five_hour_pct"] and quota["seven_day_pct"] < rung["max_seven_day_pct"]:
            return {
                "items": int(rung["items"]),
                "why": (
                    f"5h at {quota['five_hour_pct']:.0f}%, 7d at {quota['seven_day_pct']:.0f}% "
                    f"→ ladder rung <{rung['max_five_hour_pct']}%/<{rung['max_seven_day_pct']}%"
                ),
                "quota": quota,
            }

    return {
        "items": 1,
        "why": f"5h at {quota['five_hour_pct']:.0f}%, 7d at {quota['seven_day_pct']:.0f}% — below every rung, taking one",
        "quota": quota,
    }


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


def load_store() -> dict[str, Any]:
    if not INDEX_JSON.exists():
        return {"version": SCHEMA_VERSION, "updated": "", "last_sweep": "", "items": {}}
    try:
        data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"findings index is unreadable ({exc}); refusing to overwrite it")
    data.setdefault("items", {})
    return data


def save_store(store: dict[str, Any]) -> None:
    INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
    store["version"] = SCHEMA_VERSION
    store["updated"] = utc_now()
    tmp = INDEX_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(INDEX_JSON)  # atomic: a killed timer must not leave a half-written index


def _note(record: dict[str, Any], status: str, why: str) -> None:
    record["status"] = status
    record["status_reason"] = why
    record.setdefault("history", []).append({"at": utc_now(), "status": status, "why": why})


# ---------------------------------------------------------------------------
# the sweep
# ---------------------------------------------------------------------------


def sweep(*, dry_run: bool = False, skip_remote: bool = False) -> dict[str, Any]:
    cfg = load_config()
    store = load_store()
    records: dict[str, Any] = store["items"]

    # Which sources actually got scanned this run. An item can only be *closed* for
    # absence from a source that was genuinely looked at -- see the disappearance pass.
    # Without this, one `--no-remote` run (or a glab outage, or a missing ripgrep) would
    # close every item from the unscanned source as resolved, silently, in one tick.
    scanned = {"tree": True, "gitlab": not skip_remote}

    found: dict[str, Item] = {}

    docs = find_candidate_docs()
    markers = scan_code_markers()
    if docs is None or markers is None:
        scanned["tree"] = False
    for item in [*(i for p in (docs or []) for i in parse_doc(p)), *(markers or [])]:
        found.setdefault(item.id, item)

    closures: dict[str, str] = {}
    merged_seen: list[str] = []
    if not skip_remote:
        mr_items = scan_open_mrs()
        if mr_items is None:
            scanned["gitlab"] = False
        for item in mr_items or []:
            found.setdefault(item.id, item)
        closures, merged_seen = merged_mr_closures(int(cfg.get("merged_lookback_days", 2)))

    stats = {
        "new": 0,
        "reopened": 0,
        "closed_by_merge": 0,
        "gone": 0,
        "suppressed": 0,
        "unchanged": 0,
        # Items left untouched because their source wasn't scanned this run. Surfaced so
        # a degraded sweep reads as degraded rather than as a clean one that found less.
        "unverified": 0,
    }

    # 1. Merged-MR closures first. An item this loop shipped is `done`, and must be
    #    settled BEFORE the disappearance pass, or it would be miscounted as `gone`.
    for item_id, ref in closures.items():
        record = records.get(item_id)
        if record and record.get("status") != "done":
            record["mr"] = ref
            _note(record, "done", f"merged in {ref}")
            stats["closed_by_merge"] += 1

    # 2. Everything present in the tree/MRs right now.
    for item_id, item in found.items():
        record = records.get(item_id)
        if record is None:
            records[item_id] = item.to_new_record()
            stats["new"] += 1
            continue

        record["last_seen"] = today()
        # Refresh the volatile facts: line numbers move, prose gets edited, and the
        # priority signal should track the current wording rather than the wording it
        # had the day it was first indexed.
        record["source"]["line"] = item.source_line
        record["title"] = item.title
        record["detail"] = item.detail
        record["code_refs"] = item.code_refs
        record["priority"] = item.priority
        record["impact"] = item.impact
        if item.owner_skill:
            record["owner_skill"] = item.owner_skill

        if record.get("status") in ("done", "gone"):
            _note(record, "outstanding", "regressed — text reappeared after being closed")
            record["regressed"] = True
            stats["reopened"] += 1
        else:
            stats["unchanged"] += 1

    # 3. Anything the index knows that the sweep no longer finds -- but ONLY for sources
    #    this run actually scanned. Absence is evidence of resolution only if we looked.
    for item_id, record in records.items():
        if item_id in found or record.get("status") not in OPEN_STATUSES:
            continue
        source_kind = "gitlab" if str(record.get("source", {}).get("path", "")).startswith("gitlab:") else "tree"
        if not scanned[source_kind]:
            stats["unverified"] += 1
            continue
        if record.get("status") == "mr-open":
            _note(record, "done", f"source text gone after {record.get('mr') or 'an MR'} — treating as shipped")
        else:
            _note(record, "gone", "source text no longer present; closed without this loop shipping anything")
            stats["gone"] += 1

    # 4. Human verdicts win over everything above.
    open_items = [found[i] for i in found if records[i].get("status") in OPEN_STATUSES]
    for item_id, why in suppressed_ids(open_items).items():
        record = records.get(item_id)
        if record and record.get("status") != "suppressed":
            _note(record, "suppressed", why)
            stats["suppressed"] += 1

    store["last_sweep"] = utc_now()
    store["last_merged_refs"] = merged_seen
    store["sources_scanned"] = scanned
    budget = compute_budget(cfg)

    if not dry_run:
        save_store(store)
        render_markdown(store, budget)

    return {
        "stats": stats,
        "budget": budget,
        "total": len(records),
        "open": len(open_items),
        "sources_scanned": scanned,
        "store": store,
    }


def rank(records: dict[str, Any]) -> list[dict[str, Any]]:
    """Open items, most impactful first.

    Ties break on age: an old P2 outranks a fresh P2, so nothing starves at the bottom
    of the list forever. `attempts` sorts last-resort — an item this loop has already
    tried and failed twice steps aside for one nobody has attempted, rather than
    consuming the whole budget every day on the same immovable problem.
    """
    open_records = [r for r in records.values() if r.get("status") in OPEN_STATUSES]
    return sorted(
        open_records,
        key=lambda r: (
            r.get("priority", "P4"),
            r.get("attempts", 0),
            r.get("first_seen", "9999-99-99"),
            r.get("id", ""),
        ),
    )


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def render_markdown(store: dict[str, Any], budget: dict[str, Any]) -> None:
    records: dict[str, Any] = store["items"]
    ranked = rank(records)
    by_status: dict[str, int] = {}
    for record in records.values():
        by_status[record.get("status", "?")] = by_status.get(record.get("status", "?"), 0) + 1

    out: list[str] = []
    out.append("# Findings index")
    out.append("")
    out.append(
        "Generated by `scripts/findings_index.py sweep` — **do not hand-edit**, the next "
        "sweep overwrites it. Statuses are moved with `findings_index.py record`, and the "
        "worklist is consumed by the `findings-sweep` skill."
    )
    out.append("")
    out.append(f"- swept: `{store.get('last_sweep') or 'never'}`")
    out.append(f"- tracked: **{len(records)}** items — " + ", ".join(f"{k} {v}" for k, v in sorted(by_status.items())))
    out.append(f"- today's budget: **{budget['items']}** item(s) — {budget['why']}")
    out.append("")
    out.append("## Worklist (open, most impactful first)")
    out.append("")

    if not ranked:
        out.append("_Nothing outstanding._")
    else:
        out.append("| # | id | pri | impact | item | lives in | status |")
        out.append("|---|----|-----|--------|------|----------|--------|")
        for n, record in enumerate(ranked, 1):
            src = record.get("source", {})
            where = ", ".join(f"`{r}`" for r in record.get("code_refs", [])[:2])
            if not where:
                where = f"`{src.get('path', '?')}:{src.get('line', 0)}`"
            title = record.get("title", "").replace("|", "\\|")
            flag = " ⚠️regressed" if record.get("regressed") else ""
            out.append(
                f"| {n} | `{record['id']}` | {record.get('priority', '?')} | "
                f"{record.get('impact', '?')} | {title}{flag} | {where} | {record.get('status', '?')} |"
            )

    out.append("")
    out.append("## Detail")
    out.append("")
    for record in ranked:
        src = record.get("source", {})
        origin = src.get("ref") or f"{src.get('path', '?')}:{src.get('line', 0)}"
        out.append(f"### `{record['id']}` — {record.get('title', '')}")
        out.append("")
        out.append(f"- **priority**: {record.get('priority')} ({record.get('impact')})")
        out.append(f"- **status**: {record.get('status')} — {record.get('status_reason', '')}")
        out.append(f"- **documented in**: `{origin}` ({record.get('kind', '?')})")
        if record.get("code_refs"):
            out.append("- **lives in**: " + ", ".join(f"`{r}`" for r in record["code_refs"]))
        if record.get("owner_skill"):
            out.append(f"- **owner skill**: `{record['owner_skill']}`")
        out.append(f"- **first seen**: {record.get('first_seen')} · **attempts**: {record.get('attempts', 0)}")
        out.append("")
        out.append(f"> {record.get('detail', '')}")
        out.append("")

    closed = [r for r in records.values() if r.get("status") not in OPEN_STATUSES]
    if closed:
        out.append("## Closed")
        out.append("")
        for record in sorted(closed, key=lambda r: r.get("status", "")):
            ref = f" ({record['mr']})" if record.get("mr") else ""
            out.append(f"- `{record['id']}` **{record.get('status')}**{ref} — {record.get('title', '')}")
        out.append("")

    INDEX_MD.parent.mkdir(parents=True, exist_ok=True)
    INDEX_MD.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_sweep(args: argparse.Namespace) -> int:
    result = sweep(dry_run=args.dry_run, skip_remote=args.no_remote)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "store"}, indent=2))
        return 0
    stats, budget = result["stats"], result["budget"]
    print(f"swept {result['total']} tracked item(s), {result['open']} open")
    print(
        "  new {new}, reopened {reopened}, closed-by-merge {closed_by_merge}, "
        "gone {gone}, suppressed {suppressed}, unchanged {unchanged}".format(**stats)
    )
    unscanned = [name for name, ok in result["sources_scanned"].items() if not ok]
    if unscanned:
        print(
            f"  DEGRADED: {', '.join(unscanned)} not scanned — "
            f"{stats['unverified']} item(s) left as-is rather than closed"
        )
    print(f"  budget: {budget['items']} item(s) — {budget['why']}")
    if args.dry_run:
        print("  (dry run — nothing written)")
    else:
        print(f"  wrote {INDEX_MD.relative_to(REPO_ROOT)} and {INDEX_JSON.relative_to(REPO_ROOT)}")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    store = load_store()
    limit = args.limit if args.limit is not None else compute_budget()["items"]
    picks = rank(store["items"])[: max(0, limit)]
    if args.json:
        print(json.dumps({"limit": limit, "items": picks}, indent=2))
        return 0
    if not picks:
        print("nothing to pick up" if limit else "budget is 0 — standing down")
        return 0
    for n, record in enumerate(picks, 1):
        src = record.get("source", {})
        print(f"{n}. [{record.get('priority')}/{record.get('impact')}] {record['id']} — {record.get('title')}")
        print(f"     documented: {src.get('ref') or f'{src.get("path")}:{src.get("line")}'}")
        if record.get("code_refs"):
            print(f"     lives in:   {', '.join(record['code_refs'])}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    store = load_store()
    record = store["items"].get(args.id.lower())
    if record is None:
        print(f"unknown item id {args.id!r}", file=sys.stderr)
        return 1
    if args.status not in STATUSES:
        print(f"status must be one of: {', '.join(STATUSES)}", file=sys.stderr)
        return 1
    if args.status == "in-progress":
        record["attempts"] = record.get("attempts", 0) + 1
    if args.mr:
        record["mr"] = args.mr
    _note(record, args.status, args.why or f"set by {args.by or 'findings_index.py record'}")
    save_store(store)
    render_markdown(store, compute_budget())
    print(f"{args.id} → {args.status}")
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    budget = compute_budget()
    if args.json:
        print(json.dumps(budget, indent=2))
    else:
        print(f"{budget['items']} item(s) — {budget['why']}")
    return 0


def cmd_check() -> int:
    problems: list[str] = []
    try:
        store = load_store()
    except SystemExit as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    if store.get("version") != SCHEMA_VERSION and store.get("items"):
        problems.append(f"schema version {store.get('version')} != {SCHEMA_VERSION}")
    for item_id, record in store.get("items", {}).items():
        if record.get("status") not in STATUSES:
            problems.append(f"{item_id}: unknown status {record.get('status')!r}")
        if record.get("id") != item_id:
            problems.append(f"{item_id}: record id mismatch ({record.get('id')!r})")
        if not isinstance(record.get("source"), dict):
            problems.append(f"{item_id}: missing source block")
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    print("findings index OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate the store, exit 1 on problems")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("sweep", help="refresh the index from all sources")
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="compute only, write nothing")
    p.add_argument("--no-remote", action="store_true", help="skip glab (tree sources only)")

    p = sub.add_parser("next", help="the top open items, budget-sized")
    p.add_argument("--limit", type=int, default=None, help="override the quota-derived budget")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("record", help="move an item's status")
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True, help=f"one of: {', '.join(STATUSES)}")
    p.add_argument("--why", default="")
    p.add_argument("--mr", default="", help='MR reference, e.g. "!142"')
    p.add_argument("--by", default="")

    p = sub.add_parser("budget", help="how many items today's quota affords")
    p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.check:
        return cmd_check()
    if args.cmd == "sweep":
        return cmd_sweep(args)
    if args.cmd == "next":
        return cmd_next(args)
    if args.cmd == "record":
        return cmd_record(args)
    if args.cmd == "budget":
        return cmd_budget(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
