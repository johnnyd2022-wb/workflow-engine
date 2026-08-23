"""Unit tests for scripts/findings_index.py — the documented-findings index.

The index is consumed unattended: a daily timer hands the top items straight to a skill
that edits code and opens an MR. So the properties worth pinning are the ones whose
failure is *silent*:

  - **Signature stability.** If an id churned when a report was reflowed, every item
    would look new every day, statuses would reset, and the loop would re-fix work it
    already shipped.
  - **The actionability gates.** The first real sweep produced 182 items whose P0 head
    was format templates out of a SKILL.md and findings a human had already ruled
    false-positive. Re-raising a rejected finding is the specific failure
    `finding_history.py` exists to prevent, and these gates are what enforce it here.
  - **Classification honesty.** `auth\\w*` matching "author" and bare `token` matching
    "token cost" both really happened, and both promoted noise to the top of a
    security-first worklist.
  - **The self-healing state machine.** Closing an item nobody fixed loses real work;
    failing to close one that merged makes the loop redo it.

DB-free and network-free: every source function is stubbed, and the store is redirected
at a tmp dir. No Postgres, no glab, no real index touched.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "findings_index", Path(__file__).resolve().parents[1] / "scripts" / "findings_index.py"
)
fi = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = fi
_SPEC.loader.exec_module(fi)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Redirect the index at a tmp dir and cut every external source by default."""
    monkeypatch.setattr(fi, "INDEX_JSON", tmp_path / "findings-index.json")
    monkeypatch.setattr(fi, "INDEX_MD", tmp_path / "findings-index.md")
    monkeypatch.setattr(fi, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(fi, "find_candidate_docs", lambda: [])
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [])
    monkeypatch.setattr(fi, "scan_open_mrs", lambda: [])
    monkeypatch.setattr(fi, "merged_mr_closures", lambda days: ({}, []))
    monkeypatch.setattr(fi, "suppressed_ids", lambda items: {})
    monkeypatch.setattr(fi, "compute_budget", lambda cfg=None: {"items": 2, "why": "test", "quota": None})
    return tmp_path


def make_item(**kw):
    defaults = dict(
        id="",
        title="t",
        detail="d",
        kind="finding",
        source_path="a/b.md",
        source_line=1,
    )
    defaults.update(kw)
    if not defaults["id"]:
        defaults["id"] = fi.make_id(defaults["source_path"], defaults["detail"])
    return fi.Item(**defaults)


def write_doc(tmp_path, monkeypatch, name, text):
    """Put a markdown file on disk and point parse_doc's relative-path maths at it."""
    monkeypatch.setattr(fi, "REPO_ROOT", tmp_path)
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- signature stability ---------------------------------------------------------------


def test_id_survives_reflow_and_emphasis():
    """A report rewrapped by an editor must not mint a new item."""
    a = fi.make_id("r.md", "- **Cross-org `process_id`** produces an uncaught 500 instead of a clean 400")
    b = fi.make_id("r.md", "- Cross-org process_id produces an   uncaught 500 instead of a clean 400")
    assert a == b


def test_id_survives_line_number_drift():
    """`backend.py:3591` -> `backend.py:3604` after an edit above it is the same finding."""
    a = fi.make_id("r.md", "validate source_execution_id in backend.py:3591 against the org")
    b = fi.make_id("r.md", "validate source_execution_id in backend.py:3604 against the org")
    assert a == b


def test_id_is_scoped_by_source_file():
    """The same sentence in two reports is two claims; closing one must not close both."""
    assert fi.make_id("a.md", "same text here entirely") != fi.make_id("b.md", "same text here entirely")


def test_id_changes_when_the_claim_changes():
    a = fi.make_id("r.md", "tenant isolation gap in the inventory list endpoint")
    b = fi.make_id("r.md", "performance budget breach on the dashboard page")
    assert a != b


# --- actionability gates ---------------------------------------------------------------


def test_report_with_clean_verdict_contributes_nothing(tmp_path, monkeypatch):
    """A report that closed itself owes no work, however many bullets it lists."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """# SECURITY: x
verdict: clean

## Findings
- F1 [fix] app/a.py:1 a real sounding finding about tenant isolation and org_id
""",
    )
    assert fi.parse_doc(path) == []


def test_bolded_verdict_is_still_recognised(tmp_path, monkeypatch):
    """Several reports write `verdict: **patched**` -- the emphasis markers must not
    stop `patched` from reaching the word class and closing the report."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """# SECURITY: x
verdict: **patched**

## Findings
- F1 [fix] app/a.py:1 a real sounding finding about tenant isolation and org_id
""",
    )
    assert fi.parse_doc(path) == []


def test_within_budget_verdict_is_treated_as_closed(tmp_path, monkeypatch):
    """perf-guardrails reports spell a clean pass `within-budget`, not `clean`/`patched` --
    its own trailing footer restates it as `patched`, confirming it means the same thing."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """# perf-guardrails: x
Verdict: **within-budget**

### A gap that was actually closed in this same pass
- added a new measure entry and fixed the triage script to match

VERDICT: patched
""",
    )
    assert fi.parse_doc(path) == []


def test_file_level_accepted_risk_verdict_is_treated_as_closed(tmp_path, monkeypatch):
    """A human already signed off accepted-risk in the report's own header -- that is a
    human verdict already on record, not a suppression this script is minting itself."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """# SECURITY: x
verdict: **accepted-risk** — signed off by the repo owner, 2026-07-17

## Findings
- a real sounding finding about tenant isolation that the owner has already accepted
""",
    )
    assert fi.parse_doc(path) == []


def test_report_with_findings_open_verdict_contributes(tmp_path, monkeypatch):
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """# SECURITY: x
verdict: findings-open

## Findings
- F1 [fix] app/a.py:1 cross-org process_id returns a 500 instead of a clean 400
""",
    )
    items = fi.parse_doc(path)
    assert len(items) == 1
    assert items[0].priority == "P0"


def test_trailing_verdict_does_not_reopen_a_clean_report(tmp_path, monkeypatch):
    """Reports restate the verdict in a footer; the header is authoritative."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """# SECURITY: x
verdict: clean

## Findings
- F1 [fix] app/a.py:1 something about org_id scoping that sounds actionable

VERDICT: findings-open
""",
    )
    assert fi.parse_doc(path) == []


def test_false_positive_and_accepted_risk_are_not_re_raised(tmp_path, monkeypatch):
    """Re-surfacing a finding a human already rejected is the exact failure mode
    finding_history.py was built to stop. The disposition tag must be honoured here too."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """# SECURITY: x
verdict: findings-open

## Findings
- F1 [false-positive] app/a.py:1 constant query with no user input, not injection
- F2 [accepted-risk] app/b.py:2 org_id filter omitted deliberately on a PK lookup
- F3 [fix] app/c.py:3 cross-org leak in the summary endpoint
""",
    )
    items = fi.parse_doc(path)
    assert [i.detail[:2] for i in items] == ["F3"]


def test_already_patched_finding_is_not_re_indexed(tmp_path, monkeypatch):
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """# SECURITY: x
verdict: findings-open

## Findings
- F1 [fix] app/a.py:1 missing org_id scope on the lookup
  patch: 4f2a1b9 added the org_id filter and a regression test
- F2 [fix] app/b.py:2 second missing org_id scope on another lookup
  patch: not applied
""",
    )
    items = fi.parse_doc(path)
    assert [i.detail[:2] for i in items] == ["F2"]


def test_format_template_placeholders_are_rejected(tmp_path, monkeypatch):
    """`- F1 [fix|false-positive|accepted-risk] <file:line> <description>` is a spec of
    what a finding looks like, not a finding. These dominated the first real P0 list."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "skills/s.md",
        """## Findings
- F1 [fix|false-positive|accepted-risk] <file:line> <one-line description>
- F2 [fix] app/real.py:10 an actual cross-org leak in the export path
""",
    )
    items = fi.parse_doc(path)
    assert [i.detail[:2] for i in items] == ["F2"]


def test_ticked_checkbox_and_resolved_prose_are_skipped(tmp_path, monkeypatch):
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Follow-ups
- [x] this one is done and should not be indexed at all
- [ ] this one is still open and needs the org_id scope added
- ✅ resolved in !120, the migration guard now covers this case
""",
    )
    items = fi.parse_doc(path)
    assert len(items) == 1
    assert "still open" in items[0].detail


def test_bullets_outside_a_findings_heading_are_ignored(tmp_path, monkeypatch):
    """Heading scoping is what keeps the index signal-dense; policy prose that merely
    says 'follow-up' must contribute nothing."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Summary
- we ran the audit and everything looked broadly reasonable to us

## Follow-ups
- add the missing org_id filter to the summary lookup for defense in depth
""",
    )
    items = fi.parse_doc(path)
    assert len(items) == 1
    assert "org_id filter" in items[0].detail


def test_sibling_heading_closes_a_findings_section(tmp_path, monkeypatch):
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Findings
- the reconciliation path leaks a 500 on cross-org process ids

## Attempted but clean
- probed the wastage idempotency path and found nothing wrong there
""",
    )
    items = fi.parse_doc(path)
    assert len(items) == 1
    assert "reconciliation" in items[0].detail


def test_heading_that_declares_itself_fixed_does_not_open_a_section(tmp_path, monkeypatch):
    """`## Known Issues Fixed (this review)` matches the 'known issues' pattern, but the
    heading itself says these are already fixed -- it must not be read as an open
    'known-issue' section."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Known Issues Fixed (this review)
- Cross-tenant step lookup in `DAGTracer.add_step_order_connections` queried by ID alone
  with no join back to `Execution.org_id`. Fixed to match the file's documented pattern.
""",
    )
    assert fi.parse_doc(path) == []


def test_nested_closed_subheading_closes_a_still_open_ancestor_section(tmp_path, monkeypatch):
    """A deeper subheading ("### Closed this review") never satisfies `level <=
    section[0]` against its shallower ancestor ("## Known gaps"), so without an explicit
    check every bullet under it inherited the ancestor's open kind forever. A later
    sibling *heading* that actually names a still-open kind ("## Still outstanding")
    must keep working normally."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Known gaps

### Closed this review
- the org_id filter was missing on the join and has now been added, see the regression test

## Still outstanding
- the export endpoint has no rate limit and could be abused for a denial of service
""",
    )
    items = fi.parse_doc(path)
    assert len(items) == 1
    assert "rate limit" in items[0].detail


def test_negated_closure_phrasing_does_not_falsely_close_a_section(tmp_path, monkeypatch):
    """'not closed' / 'not fixed' must not trip the closed-heading check -- these headings
    are explicitly saying the work is still owed."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Known coverage gaps (not closed this pass, documented honestly)
- the summary endpoint still leaks another org's execution ids through the join
""",
    )
    items = fi.parse_doc(path)
    assert len(items) == 1
    assert "leaks another org's execution ids" in items[0].detail


def test_not_findings_heading_does_not_open_a_section(tmp_path, monkeypatch):
    """'## Not findings (checked, no issue)' contains the word "findings", which alone
    would open a `finding` section -- but the heading's own title says the opposite: this
    is a real convention this repo's reports use (migration-safety.md, security-audit.md,
    perf-guardrails.md, e2e-playwright.md all write '(not a finding)' / '(no issues
    found)' / '(not findings...)' variants) to record a checked-and-clean result inline.
    Sweeping those bullets in as open findings is exactly the noise the actionability
    gates exist to keep out."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Not findings (checked, no issue)
- Multiple heads: none (`alembic heads` -> single head).
- The pg_guard trigger-function revisions correctly restore the prior body on downgrade.

## Other checks performed (no issues found)
- AC5 boundary correctly always rejected by the existing check -- no gap.

### CSP note (not a finding -- existing app-wide posture)
Inline script matches the app-wide CSP convention already in place.
""",
    )
    assert fi.parse_doc(path) == []


def test_findings_not_actioned_heading_still_opens_a_section(tmp_path, monkeypatch):
    """Contrast case for the fix above: '## Findings not actioned (chain stage,
    read-only)' puts 'not' *after* 'Findings', reporting real findings a read-only stage
    declined to patch -- not a declaration that nothing was found. These must stay open
    so the next stage picks them up."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Findings not actioned (this run patches nothing -- chain stage, read-only)
- F1: the export endpoint has no rate limit and could be abused for a denial of service
""",
    )
    items = fi.parse_doc(path)
    assert len(items) == 1
    assert "rate limit" in items[0].detail


def test_no_gap_found_heading_variants_do_not_open_a_section(tmp_path, monkeypatch):
    """This repo's spec-critic and observability reports also write '(not gaps)' and
    'no gap(s) found' -- variants of the checked-and-clean convention that
    `\\bnot a gap\\b` / `\\bno issues?\\b` don't catch on their own. Real misfire: both
    headings below appear verbatim in `.agents/reports/process_templates/spec-critic.md`
    (99, 116) and indexed 11 non-findings as open P0/P1 items -- including a bullet whose
    own text ends '... AC7 explicitly tests cross-org 404 ... No gap.' -- because neither
    heading contains the word 'finding' or 'issue'."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Assumptions judged reasonable (not gaps)
- Full three-industry MVP in one build -- explicitly surfaced as an override of the PRD's own phased-rollout plan.

## Other checks performed, no gap found
- Tenant scoping: decided and grounded -- resolved via g.current_org_id server-side. No gap.

## Scanned, no gap found
- AC5/AC6 path-traversal 400s: considered and not instrumented, routine background noise.
""",
    )
    assert fi.parse_doc(path) == []


def test_bullet_syntax_inside_a_fenced_code_block_is_not_a_finding(tmp_path, monkeypatch):
    """A YAML/code snippet quoted as evidence inside a finding often contains lines that
    look exactly like markdown bullets (`- "**/app.py"`). This is exactly what
    `.agents/reports/shell/security-audit.md`'s F3 finding does, and it produced a
    standalone garbage item per fenced list line -- the fence must gate bullet scanning
    off, the same way a heading does, since these are code contents, not report prose."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Findings
### F3 [fix] `.semgrep/rules/python-multitenant.yml:26-28` -- exclude list is too broad, which is exactly why the scanner reported 0 findings on the real gap
```yaml
paths:
  exclude:
    - "**/auth_routes.py"
    - "**/app.py"
```
recommendation: narrow the exclude list.
""",
    )
    items = fi.parse_doc(path)
    assert items == [], f"fenced code-block lines were indexed as findings: {[i.detail for i in items]}"


def test_bullet_continuation_passes_through_an_embedded_fence(tmp_path, monkeypatch):
    """A bullet's own multi-line body legitimately embeds a fenced snippet as evidence,
    followed by more prose -- e.g. a `python` block then a 'Recommended fix:' sentence,
    the real shape of `.agents/reports/traceability/security-audit.md`'s F3 finding.
    Stopping continuation at the fence (rather than passing through it) truncates the
    bullet and silently drops that trailing prose -- including, in the real report, the
    part naming the recommended fix."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Findings
- **`GET /api/x` 500s on bad input.** No try/except around the parse call:
  ```python
  page = int(request.args.get("page", 1))
  ```
  Recommended fix: wrap in try/except and return 400 at `app/x.py:12`.
""",
    )
    items = fi.parse_doc(path)
    assert len(items) == 1
    assert "Recommended fix" in items[0].detail
    assert "app/x.py:12" in items[0].code_refs


def test_h1_document_title_does_not_open_an_unclosable_section(tmp_path, monkeypatch):
    """`docs/findings-sweep-setup.md`'s own title, '# Findings sweep -- setup', contains
    the word 'findings' and (before this fix) opened a level-1 `finding` section. A
    level-1 section can only be closed by another level-1 heading -- and this repo writes
    exactly one H1 per doc -- so the whole rest of the file, every `##` subsection's
    prose bullets included, was swept in as findings. Level-1 headings are this repo's
    document titles, never section markers, so they must never open a section."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "docs/x.md",
        """# Findings sweep -- setup

## Files
- `scripts/findings_index.py` -- the index builder.

## How the loop closes
- Source text gone, no MR from this loop -> `gone` (someone removed it by hand).
- A closed finding reappears -> reopened and flagged `regressed`.
""",
    )
    assert fi.parse_doc(path) == []


def test_multi_line_bullet_is_gathered_whole(tmp_path, monkeypatch):
    """Findings here wrap across several lines; truncating at the newline loses the part
    that names the file, which is the half the skill needs to act."""
    path = write_doc(
        tmp_path,
        monkeypatch,
        "reports/x.md",
        """## Findings
- **Cross-org process_id produces a 500.** The service calls create_execution
  inside a try block, and the repository raises a bare ValueError at
  `app/core/db/repositories/execution_repo.py:76` which nothing converts.
""",
    )
    items = fi.parse_doc(path)
    assert len(items) == 1
    assert "app/core/db/repositories/execution_repo.py:76" in items[0].code_refs


# --- classification --------------------------------------------------------------------


def test_author_in_a_footer_is_not_a_security_finding():
    """`auth\\w*` also matches 'author', which appears in nearly every report footer."""
    tier, _ = fi.classify_priority("Report authored by the review-feature orchestrator, transcribed verbatim", "r.md")
    assert tier != "P0"


def test_llm_token_cost_is_not_a_security_finding():
    """A docs proposal about skill economics was ranked P0 because it said 'token cost'."""
    tier, _ = fi.classify_priority("Payoff: tells us which skills earn their token cost", "docs/x.md")
    assert tier != "P0"


def test_real_auth_token_is_still_security():
    tier, impact = fi.classify_priority("the session token is not rotated on privilege change", "r.md")
    assert (tier, impact) == ("P0", "security")


def test_lead_wins_over_a_passing_mention_deep_in_the_body():
    """Findings run 1200 chars; classifying on the whole body made everything P0."""
    body = "Dashboard render exceeds the LCP budget by 400ms. " + ("filler prose. " * 40) + " unauthorized access"
    tier, impact = fi.classify_priority(body, "r.md")
    assert (tier, impact) == ("P2", "performance")


def test_body_signal_cannot_claim_the_top_two_tiers():
    body = "Some unclassifiable lead sentence here. " + ("padding. " * 40) + " possible sql-injection somewhere"
    tier, _ = fi.classify_priority(body, "r.md")
    assert tier not in ("P0", "P1")


def test_security_audit_source_path_raises_priority():
    """A finding written by the security audit is a security finding even if its prose
    never says so."""
    tier, impact = fi.classify_priority(
        "the regex misses schema-qualified identifiers", ".agents/reports/x/security-audit.md"
    )
    assert (tier, impact) == ("P0", "security")


def test_source_hint_never_lowers_an_existing_tier():
    tier, _ = fi.classify_priority("cross-org data leak in the export path", ".agents/reports/perf/x.md")
    assert tier == "P0"


def test_cosmetic_sorts_to_the_bottom():
    tier, impact = fi.classify_priority("nice-to-have: tidy up the wording on the empty state", "r.md")
    assert (tier, impact) == ("P4", "cosmetic")


def test_code_refs_ignore_bare_filenames_without_a_line():
    """A prose mention of 'config.toml' is not a locator; 'app/x.py:12' is."""
    refs = fi.extract_code_refs("see config.toml and also app/core/x.py:12 plus a/b.py")
    assert "app/core/x.py:12" in refs and "a/b.py" in refs
    assert "config.toml" not in refs


# --- budget ----------------------------------------------------------------------------


def test_budget_takes_more_when_both_windows_are_quiet(monkeypatch, tmp_path):
    """The founder's ask: 2 a day baseline, but pick up more when the quota affords it."""
    monkeypatch.setattr(fi, "CONFIG_PATH", tmp_path / "c.json")
    monkeypatch.setattr(fi, "read_quota", lambda cfg: {"five_hour_pct": 10.0, "seven_day_pct": 12.0, "age_sec": 5})
    result = fi.compute_budget()
    assert result["items"] == 4
    assert result["quota"] is not None


def test_budget_ladder_steps_down_as_the_five_hour_window_fills(monkeypatch, tmp_path):
    monkeypatch.setattr(fi, "CONFIG_PATH", tmp_path / "c.json")
    seen = []
    for pct in (10.0, 45.0, 65.0, 80.0):
        monkeypatch.setattr(
            fi, "read_quota", lambda cfg, p=pct: {"five_hour_pct": p, "seven_day_pct": 10.0, "age_sec": 5}
        )
        seen.append(fi.compute_budget()["items"])
    assert seen == sorted(seen, reverse=True), f"budget must not grow as quota fills: {seen}"
    assert seen[0] > seen[-1]


def test_weekly_window_can_hold_the_budget_down_on_a_quiet_day(monkeypatch, tmp_path):
    """A Pro plan can look fine on the 5h window daily and still burn the week by
    Thursday; the 7d window is in the test for exactly that."""
    monkeypatch.setattr(fi, "CONFIG_PATH", tmp_path / "c.json")
    monkeypatch.setattr(fi, "read_quota", lambda cfg: {"five_hour_pct": 5.0, "seven_day_pct": 85.0, "age_sec": 5})
    assert fi.compute_budget()["items"] == 1


def test_budget_stands_down_at_the_ceiling(monkeypatch, tmp_path):
    monkeypatch.setattr(fi, "CONFIG_PATH", tmp_path / "c.json")
    monkeypatch.setattr(fi, "read_quota", lambda cfg: {"five_hour_pct": 94.0, "seven_day_pct": 20.0, "age_sec": 5})
    result = fi.compute_budget()
    assert result["items"] == 0
    assert "ceiling" in result["why"]


def test_unknown_quota_falls_back_to_the_configured_default(monkeypatch, tmp_path):
    """An absent reading must not stand the loop down — the cache only refreshes on an
    interactive render, so 'no reading' is the normal state on an unattended box."""
    monkeypatch.setattr(fi, "CONFIG_PATH", tmp_path / "c.json")
    monkeypatch.setattr(fi, "read_quota", lambda cfg: None)
    result = fi.compute_budget()
    assert result["items"] == 2
    assert result["quota"] is None


def test_stale_quota_reading_is_treated_as_absent(tmp_path, monkeypatch):
    cache = tmp_path / "rate.json"
    cache.write_text(json.dumps({"captured_at": 0, "five_hour": {"used_percentage": 99}}), encoding="utf-8")
    monkeypatch.setattr(fi, "RATE_CACHE", cache)
    assert fi.read_quota({"quota_cache_max_age_sec": 60}) is None


# --- the self-healing state machine ----------------------------------------------------


def test_new_item_is_indexed_as_outstanding(store, monkeypatch):
    item = make_item(detail="a fresh finding about the org_id scope on exports")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    result = fi.sweep()
    assert result["stats"]["new"] == 1
    assert result["store"]["items"][item.id]["status"] == "outstanding"


def test_second_sweep_does_not_duplicate_an_unchanged_item(store, monkeypatch):
    item = make_item(detail="a stable finding that will be seen twice in a row")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    fi.sweep()
    result = fi.sweep()
    assert result["stats"] == {**result["stats"], "new": 0, "unchanged": 1}
    assert len(result["store"]["items"]) == 1


def test_merged_mr_trailer_closes_the_items_it_fixed(store, monkeypatch):
    """The loop's feedback path: the skill writes `Findings-Index: <id>` into the MR, and
    this is how it learns the work landed without anyone editing the index."""
    item = make_item(detail="a finding that will be fixed and merged by an MR")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    fi.sweep()
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [])
    monkeypatch.setattr(fi, "merged_mr_closures", lambda days: ({item.id: "!142"}, ["!142"]))
    result = fi.sweep()
    record = result["store"]["items"][item.id]
    assert record["status"] == "done"
    assert record["mr"] == "!142"
    assert result["stats"]["closed_by_merge"] == 1


def test_merge_closure_wins_over_the_disappearance_pass(store, monkeypatch):
    """Order matters: an item whose text is gone BECAUSE it was fixed must read 'done',
    never 'gone'. Getting this backwards would log real shipped work as vanished."""
    item = make_item(detail="fixed and its source text removed in the same MR")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    fi.sweep()
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [])
    monkeypatch.setattr(fi, "merged_mr_closures", lambda days: ({item.id: "!150"}, ["!150"]))
    result = fi.sweep()
    assert result["store"]["items"][item.id]["status"] == "done"
    assert result["stats"]["gone"] == 0


def test_vanished_item_nobody_shipped_is_closed_as_gone(store, monkeypatch):
    item = make_item(detail="a finding whose text someone deleted by hand")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    fi.sweep()
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [])
    result = fi.sweep()
    assert result["store"]["items"][item.id]["status"] == "gone"
    assert result["stats"]["gone"] == 1


def test_vanished_item_with_an_open_mr_is_treated_as_shipped(store, monkeypatch):
    item = make_item(detail="a finding this loop fixed, with its MR still open")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    fi.sweep()
    store_data = fi.load_store()
    store_data["items"][item.id]["status"] = "mr-open"
    store_data["items"][item.id]["mr"] = "!7"
    fi.save_store(store_data)
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [])
    result = fi.sweep()
    assert result["store"]["items"][item.id]["status"] == "done"


def test_reappearing_item_is_reopened_and_flagged_regressed(store, monkeypatch):
    """A finding that comes back is a regression, and must be loud rather than silently
    re-indexed as routine new work."""
    item = make_item(detail="a finding that will be closed and then come back again")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    fi.sweep()
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [])
    fi.sweep()
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    result = fi.sweep()
    record = result["store"]["items"][item.id]
    assert record["status"] == "outstanding"
    assert record["regressed"] is True
    assert result["stats"]["reopened"] == 1


def test_explicit_gone_verdict_survives_a_sweep_that_still_finds_the_text(store, monkeypatch):
    """findings-sweep's Step 1 verifies a stale finding against current code and records
    `gone` while the report prose describing it is still sitting there unedited -- these
    are historical audit reports, not TODOs someone deletes when the fix ships. Without
    `closed_explicitly`, the very next sweep would re-find that same unchanged text, see
    a `gone` status, and reopen it as "regressed" -- discarding the verification and
    silently re-queuing already-fixed work every single day, forever. `_note(...,
    explicit=True)` is exactly what `cmd_record` (the CLI path `findings_index.py record`
    takes) calls; this pins that record()->sweep() round trip, not just `_note` alone."""
    item = make_item(detail="a finding whose report prose nobody will ever edit")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    fi.sweep()

    store_data = fi.load_store()
    fi._note(
        store_data["items"][item.id],
        "gone",
        "verified against current code: already fixed elsewhere",
        explicit=True,
    )
    fi.save_store(store_data)

    # The source text never moved -- the report was never edited -- so the tree scan
    # finds the exact same item again on the next sweep.
    result = fi.sweep()
    record = result["store"]["items"][item.id]
    assert record["status"] == "gone"
    assert not record.get("regressed")
    assert result["stats"]["reopened"] == 0


def test_human_suppression_overrides_an_open_item(store, monkeypatch):
    item = make_item(detail="something a human already ruled a false positive")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    monkeypatch.setattr(fi, "suppressed_ids", lambda items: {item.id: "human said false-positive"})
    result = fi.sweep()
    assert result["store"]["items"][item.id]["status"] == "suppressed"


def test_suppressed_item_stays_off_the_worklist(store, monkeypatch):
    item = make_item(detail="a suppressed item that must never be offered again")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    monkeypatch.setattr(fi, "suppressed_ids", lambda items: {item.id: "accepted risk"})
    result = fi.sweep()
    assert fi.rank(result["store"]["items"]) == []


# --- absence is only evidence if we actually looked -------------------------------------
#
# The disappearance pass closes items whose source text is gone. That is correct only for
# sources the run actually scanned. glab being missing/unauthed/down and ripgrep being
# absent are both *expected* degraded states, and the first version treated them as "that
# source has no findings" — which closed every item from that source as resolved, in one
# tick, with no error. Silent index-wide data loss.


def test_glab_outage_does_not_close_mr_sourced_items(store, monkeypatch):
    mr_item = make_item(source_path="gitlab:!42", detail="a follow-up written into an open MR description")
    monkeypatch.setattr(fi, "scan_open_mrs", lambda: [mr_item])
    fi.sweep()

    # glab now fails entirely — scan_open_mrs signals "couldn't look", not "found none".
    monkeypatch.setattr(fi, "scan_open_mrs", lambda: None)
    result = fi.sweep()
    record = result["store"]["items"][mr_item.id]
    assert record["status"] == "outstanding", "a glab outage must not close MR-sourced items"
    assert result["stats"]["unverified"] == 1
    assert result["sources_scanned"]["gitlab"] is False


def test_skip_remote_does_not_close_mr_sourced_items(store, monkeypatch):
    """`--no-remote` is a legitimate offline mode, not a statement that MRs are clean."""
    mr_item = make_item(source_path="gitlab:!42", detail="a follow-up written into an open MR description")
    monkeypatch.setattr(fi, "scan_open_mrs", lambda: [mr_item])
    fi.sweep()
    result = fi.sweep(skip_remote=True)
    assert result["store"]["items"][mr_item.id]["status"] == "outstanding"


def test_missing_ripgrep_does_not_close_tree_sourced_items(store, monkeypatch):
    tree_item = make_item(source_path=".agents/reports/x.md", detail="a finding documented in a report")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [tree_item])
    fi.sweep()

    monkeypatch.setattr(fi, "find_candidate_docs", lambda: None)
    monkeypatch.setattr(fi, "scan_code_markers", lambda: None)
    result = fi.sweep()
    assert result["store"]["items"][tree_item.id]["status"] == "outstanding"
    assert result["sources_scanned"]["tree"] is False


def test_a_scanned_source_still_closes_its_vanished_items(store, monkeypatch):
    """The guard must not be so broad that it stops the loop self-healing at all."""
    tree_item = make_item(source_path=".agents/reports/x.md", detail="a finding that really does get removed")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [tree_item])
    fi.sweep()
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [])  # scanned, genuinely absent
    result = fi.sweep()
    assert result["store"]["items"][tree_item.id]["status"] == "gone"


def test_rg_distinguishes_no_matches_from_cannot_run(monkeypatch):
    """Exit 1 is 'no matches' (empty list); a missing binary is None."""
    monkeypatch.setattr(fi.shutil, "which", lambda name: None)
    assert fi._rg(["--files"]) is None


# --- ranking ---------------------------------------------------------------------------


def test_security_outranks_performance_which_outranks_cosmetic(store, monkeypatch):
    items = [
        make_item(source_path="a.md", detail="nice-to-have polish on the empty state wording"),
        make_item(source_path="b.md", detail="dashboard LCP exceeds the performance budget"),
        make_item(source_path="c.md", detail="cross-org data leak in the inventory export"),
    ]
    for item in items:
        item.priority, item.impact = fi.classify_priority(item.detail, item.source_path)
    monkeypatch.setattr(fi, "scan_code_markers", lambda: items)
    result = fi.sweep()
    order = [r["impact"] for r in fi.rank(result["store"]["items"])]
    assert order == ["security", "performance", "cosmetic"]


def test_repeatedly_attempted_item_yields_to_an_untried_peer(store, monkeypatch):
    """Otherwise one immovable finding consumes the whole budget every single day."""
    stuck = make_item(source_path="a.md", detail="an immovable finding about org_id scoping in exports")
    fresh = make_item(source_path="b.md", detail="a fresh finding about org_id scoping in imports")
    for item in (stuck, fresh):
        item.priority, item.impact = fi.classify_priority(item.detail, item.source_path)
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [stuck, fresh])
    fi.sweep()
    data = fi.load_store()
    data["items"][stuck.id]["attempts"] = 3
    fi.save_store(data)
    assert fi.rank(fi.load_store()["items"])[0]["id"] == fresh.id


def test_closed_items_never_appear_on_the_worklist(store, monkeypatch):
    item = make_item(detail="a finding that gets closed and must stay closed")
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [item])
    fi.sweep()
    data = fi.load_store()
    data["items"][item.id]["status"] = "done"
    fi.save_store(data)
    assert fi.rank(fi.load_store()["items"]) == []


# --- store integrity -------------------------------------------------------------------


def test_check_rejects_an_unknown_status(store):
    fi.save_store(
        {
            "version": fi.SCHEMA_VERSION,
            "items": {
                "abc": {"id": "abc", "status": "banana", "source": {}},
            },
        }
    )
    assert fi.cmd_check() == 1


def test_check_rejects_an_id_mismatch(store):
    fi.save_store(
        {
            "version": fi.SCHEMA_VERSION,
            "items": {
                "abc": {"id": "def", "status": "outstanding", "source": {}},
            },
        }
    )
    assert fi.cmd_check() == 1


def test_check_passes_a_well_formed_store(store, monkeypatch):
    monkeypatch.setattr(fi, "scan_code_markers", lambda: [make_item(detail="a perfectly ordinary finding here")])
    fi.sweep()
    assert fi.cmd_check() == 0


def test_unreadable_store_is_never_silently_overwritten(store):
    """Losing the index to a truncated write would silently drop every recorded status."""
    fi.INDEX_JSON.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        fi.load_store()


# --- the real finding_history contract -------------------------------------------------
#
# These call the ACTUAL script rather than a stub, because the bug they exist to catch was
# invisible to a stub: the first version of suppressed_ids omitted `--json` and read a
# `decision` key that does not exist (it is `action`). Both failures are silent — the
# lookup simply never matches, and a finding a human already rejected gets re-raised every
# day forever. A stubbed test cannot see that; only one that speaks the real protocol can.


@pytest.fixture
def history_store(tmp_path, monkeypatch):
    """Point finding_history.py's store at a tmp dir; the subprocess inherits the env."""
    monkeypatch.setenv("HISTORY_DIR", str(tmp_path / "history"))
    return tmp_path


def _record_verdict(verdict: str, area: str, kind: str, evidence: str) -> int:
    import subprocess

    return subprocess.run(
        [
            sys.executable,
            str(fi.FINDING_HISTORY),
            "record",
            "--area",
            area,
            "--kind",
            kind,
            "--evidence",
            evidence,
            "--verdict",
            verdict,
            "--skill",
            "test",
        ],
        capture_output=True,
        text=True,
        cwd=fi.REPO_ROOT,
        check=False,
    ).returncode


def test_human_false_positive_is_read_back_as_a_suppression(history_store):
    """The whole point of the integration: a human's recorded rejection must silence the
    item, using the real key names and the real --json flag."""
    item = make_item(source_path=".agents/reports/x/review.md", detail="a finding a human will reject")
    item.impact = "security"
    assert _record_verdict("false-positive", ".agents/reports/x", "security", item.detail[:400]) == 0
    assert item.id in fi.suppressed_ids([item])


def test_accepted_risk_also_suppresses(history_store):
    item = make_item(source_path=".agents/reports/x/review.md", detail="a finding a human knowingly accepts")
    item.impact = "security"
    assert _record_verdict("accepted-risk", ".agents/reports/x", "security", item.detail[:400]) == 0
    assert item.id in fi.suppressed_ids([item])


def test_confirmed_verdict_does_not_suppress(history_store):
    """Only false-positive/accepted-risk suppress. Suppressing on 'confirmed' would bury
    exactly the findings that most need working."""
    item = make_item(source_path=".agents/reports/x/review.md", detail="a real confirmed defect worth fixing")
    item.impact = "security"
    assert _record_verdict("confirmed", ".agents/reports/x", "security", item.detail[:400]) == 0
    assert fi.suppressed_ids([item]) == {}


def test_item_with_no_recorded_verdict_is_not_suppressed(history_store):
    item = make_item(source_path=".agents/reports/x/review.md", detail="a finding nobody has ever ruled on")
    item.impact = "security"
    assert fi.suppressed_ids([item]) == {}


# --- the timer entrypoint's spend gates ------------------------------------------------
#
# These matter for cost, not correctness: the whole design is that the free sweep runs
# daily and the expensive model only starts when there is both budget and work. A
# regression here would not break anything visibly -- it would just quietly start
# spending quota on days it should have stood down.

_RUN_SPEC = importlib.util.spec_from_file_location(
    "findings_sweep_run", Path(__file__).resolve().parents[1] / "scripts" / "findings_sweep_run.py"
)
fsr = importlib.util.module_from_spec(_RUN_SPEC)
sys.modules[_RUN_SPEC.name] = fsr
_RUN_SPEC.loader.exec_module(fsr)


@pytest.fixture
def runner(monkeypatch, tmp_path):
    """Stub the index calls and record whether a worktree/agent was ever started."""
    launched: list[str] = []
    monkeypatch.setattr(fsr, "LOG_PATH", tmp_path / "run-log.jsonl")
    monkeypatch.setattr(fsr, "cut_worktree", lambda slug: launched.append(f"worktree:{slug}") or (tmp_path, "b"))
    monkeypatch.setattr(fsr, "cleanup", lambda path, branch: None)
    monkeypatch.setattr(fsr.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(fsr, "run", lambda *a, **k: launched.append("agent") or (0, "", ""))
    return launched


def _index_stub(monkeypatch, *, budget_items, open_items):
    def fake(args):
        if args[0] == "sweep":
            return {
                "total": 10,
                "open": open_items,
                "stats": {},
                "budget": {"items": budget_items, "why": "test"},
            }
        return {"items": [{"id": "abc12345", "priority": "P0"}] * open_items}

    monkeypatch.setattr(fsr, "index_json", fake)


def test_zero_budget_spends_nothing(runner, monkeypatch):
    """A stood-down run must not cut a worktree or start an agent."""
    _index_stub(monkeypatch, budget_items=0, open_items=5)
    assert fsr.main([]) == 0
    assert runner == []


def test_empty_index_spends_nothing_even_with_budget(runner, monkeypatch):
    """Budget available but nothing outstanding — launching a model to discover that is
    exactly the waste this script exists to avoid."""
    _index_stub(monkeypatch, budget_items=4, open_items=0)
    assert fsr.main([]) == 0
    assert runner == []


def test_budget_and_work_launches_the_agent(runner, monkeypatch):
    _index_stub(monkeypatch, budget_items=2, open_items=2)
    assert fsr.main([]) == 0
    assert any(x.startswith("worktree:") for x in runner)
    assert "agent" in runner


def test_agent_launches_with_auto_permission_mode(monkeypatch, tmp_path):
    """`acceptEdits` only auto-approves file Edit/Write tools, not Bash -- git commit/push
    and `glab mr create` would still hit an interactive approval wall a headless `-p`
    session can never clear. This happened for real on 2026-08-08: a run finished all its
    analysis, staged the intended diff, and then sat blocked at `git commit` for 40
    minutes with no MR. Every other autonomous launcher here (mr_conflict_watch.py,
    worktree_sweep_watch.py) uses `auto`; this pins findings_sweep_run.py to the same
    choice so the regression can't silently come back."""
    calls: list[list[str]] = []
    monkeypatch.setattr(fsr, "LOG_PATH", tmp_path / "run-log.jsonl")
    monkeypatch.setattr(fsr, "cut_worktree", lambda slug: (tmp_path, "b"))
    monkeypatch.setattr(fsr, "cleanup", lambda path, branch: None)
    monkeypatch.setattr(fsr.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(fsr, "run", lambda cmd, **k: calls.append(cmd) or (0, "", ""))
    _index_stub(monkeypatch, budget_items=1, open_items=1)

    assert fsr.main([]) == 0
    assert calls, "agent was never launched"
    cmd = calls[0]
    assert "--permission-mode" in cmd
    mode = cmd[cmd.index("--permission-mode") + 1]
    assert mode == "auto", f"acceptEdits cannot run Bash (git commit/push, glab) -- got {mode!r}"
    assert mode != "acceptEdits"


def test_dry_run_decides_but_never_launches(runner, monkeypatch):
    _index_stub(monkeypatch, budget_items=4, open_items=4)
    assert fsr.main(["--dry-run"]) == 0
    assert runner == []


def test_force_overrides_a_zero_budget(runner, monkeypatch):
    """Manual escape hatch — a human at the keyboard can overrule the ladder."""
    _index_stub(monkeypatch, budget_items=0, open_items=3)
    assert fsr.main(["--force"]) == 0
    assert "agent" in runner


def test_failed_sweep_does_not_launch(runner, monkeypatch):
    """If the index could not be refreshed, the worklist is untrustworthy — working from
    a stale index means re-fixing shipped work."""
    monkeypatch.setattr(fsr, "index_json", lambda args: None)
    assert fsr.main([]) == 1
    assert runner == []


def test_mr_trailer_parses_multiple_ids():
    ids = fi.TRAILER_RE.search("body text\nFindings-Index: a1b2c3d4, 09d144c1\nmore text")
    assert ids is not None
    assert [i.strip() for i in ids.group("ids").split(",")] == ["a1b2c3d4", "09d144c1"]


# --- MR description parsing -------------------------------------------------------------


def test_mr_description_bullet_under_a_findings_heading_is_indexed():
    items = fi._parse_mr_description(
        "## Follow-ups\n- the export endpoint has no rate limit and could be abused for a DoS\n",
        "gitlab:!1",
    )
    assert len(items) == 1
    assert items[0].kind == "follow-up"


def test_mr_description_unchecked_task_box_is_indexed_outside_any_heading():
    """GitLab renders `- [ ]` as a task list; this repo uses it for agreed-but-deferred
    work with no heading wrapping it at all, unlike every other bullet source here."""
    items = fi._parse_mr_description("- [ ] wire the rate limiter before merging\n", "gitlab:!1")
    assert len(items) == 1
    assert items[0].kind == "mr-task"


def test_mr_description_checked_task_box_is_not_indexed():
    items = fi._parse_mr_description("- [x] wire the rate limiter before merging\n", "gitlab:!1")
    assert items == []


def test_mr_description_fenced_yaml_bullet_is_not_indexed():
    """The same fence bug `parse_doc` had: a `- "..."` list line inside a fenced snippet
    must not be read as a real bullet just because a findings section is open above it."""
    items = fi._parse_mr_description(
        '## Follow-ups\n```yaml\npaths:\n  exclude:\n    - "**/auth_routes.py"\n```\n',
        "gitlab:!1",
    )
    assert items == []


def test_mr_description_fenced_task_box_is_not_indexed():
    """A `- [ ]` inside a fenced snippet (e.g. quoted as an example) must not be read as
    a real agreed-but-deferred task -- the checkbox path matches anywhere in the
    description, unguarded by section, so it needs its own fence check."""
    items = fi._parse_mr_description("```bash\n# example only\n- [ ] not a real task\n```\n", "gitlab:!1")
    assert items == []
