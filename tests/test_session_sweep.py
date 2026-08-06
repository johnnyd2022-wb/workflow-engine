"""Tests for scripts/session_sweep.py and scripts/session_sweep_watch.py.

Pure over synthetic transcripts and state dicts, plus real (but disposable,
tmp_path-scoped) file locking — no live transcripts, no systemd, no network, no model
invocation.

What this file exists to prove, beyond "the functions run":

1. **The detectors actually fire, and stay quiet on the good shape.** A detector that
   silently stopped matching would make the sweep report "nothing found" and look exactly
   like a clean week. That failure is invisible without a negative control, so every
   house rule gets both directions.
2. **Redaction runs on everything that reaches the digest.** The digest is committed to an
   MR; the transcripts it derives from are not. A leak here is permanent.
3. **The correction detector separates a human correction from a headless skill
   dispatch.** Measured against a real week, dispatch prompts made the raw signal ~85%
   noise, and they carry the identical `userType`/`isSidechain` pair a real prompt does —
   so nothing structural distinguishes them and the content filter is load-bearing.
4. **`lease_id` stops a STALE writer**, not just a concurrent one. The flock proves nobody
   is mid-write; it does not prove the writer is still the current owner. A late watchdog
   from a superseded attempt can validly take the lock and would otherwise overwrite a
   newer outcome with an older one.
5. **A quiet week spawns nothing.** The free-quiet-week path is the single biggest token
   saving in the pipeline, and it is one boolean away from silently never triggering.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SWEEP_SCRIPT = REPO_ROOT / "scripts" / "session_sweep.py"
WATCH_SCRIPT = REPO_ROOT / "scripts" / "session_sweep_watch.py"


def _load(name: str, path: Path):
    """Load a script as a module.

    Registered in sys.modules *before* exec: these scripts use `from __future__ import
    annotations`, and @dataclass resolves its field types through
    `sys.modules[cls.__module__]`, which is None for a module that isn't registered yet.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sweep = _load("session_sweep", SWEEP_SCRIPT)


# ---------------------------------------------------------------------------
# Synthetic transcripts
# ---------------------------------------------------------------------------


def _assistant(uuid: str, ts: str, blocks: list[dict], *, session: str = "s1", usage: dict | None = None) -> dict:
    return {
        "type": "assistant",
        "uuid": uuid,
        "sessionId": session,
        "timestamp": ts,
        "cwd": "/home/johnny/workflow-engine",
        "gitBranch": "main",
        "message": {
            "role": "assistant",
            "model": "claude-opus-5",
            "content": blocks,
            "usage": usage
            or {
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 5,
            },
        },
    }


def _tool_use(block_id: str, name: str, tool_input: dict) -> dict:
    return {"type": "tool_use", "id": block_id, "name": name, "input": tool_input}


def _tool_result(
    uuid: str, ts: str, block_id: str, content: str, *, is_error: bool = False, session: str = "s1"
) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "sessionId": session,
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": block_id, "content": content, "is_error": is_error}],
        },
    }


def _prompt(uuid: str, ts: str, text: str, *, session: str = "s1") -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "sessionId": session,
        "timestamp": ts,
        "message": {"role": "user", "content": text},
    }


def _write_transcript(root: Path, name: str, records: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
TS = NOW.isoformat()


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

# Fake credentials, assembled from fragments so they never appear as contiguous literals
# in this source file.
#
# The blocking `gitleaks` CI job scans this file like any other, and a realistic-looking
# token written inline fails that gate — it did, on the first pipeline for this branch,
# with six findings. The tempting fix (allowlist this path in .gitleaks.toml) is
# explicitly barred by that file's own rules: "Never allowlist a path that is still live
# in the tree." It would also disarm the scanner for every future edit to this file,
# which is precisely where a real pasted secret would land.
#
# Splitting the literal keeps the gate fully armed here while the value handed to
# redact() at runtime is byte-for-byte what it has to cope with in a real transcript.
FAKE_GITLAB_PAT = "glpat-" + "abcdefghij1234567890"
FAKE_ANTHROPIC_KEY = "sk-ant-" + "api03-AAAABBBBCCCCDDDD"
FAKE_SLACK_TOKEN = "xoxb-" + "1111-2222-abcdefghijkl"
FAKE_AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
FAKE_DB_PASSWORD = "hunter2"
FAKE_PASSPHRASE = "correct horse battery"


@pytest.mark.parametrize(
    "raw, must_not_contain",
    [
        (f"export GITLAB_TOKEN={FAKE_GITLAB_PAT}", FAKE_GITLAB_PAT),
        (f"ANTHROPIC_API_KEY={FAKE_ANTHROPIC_KEY}", FAKE_ANTHROPIC_KEY),
        (f"postgresql://workflow_rw:{FAKE_DB_PASSWORD}@localhost:8401/db", FAKE_DB_PASSWORD),
        (f"SLACK_BOT_TOKEN={FAKE_SLACK_TOKEN}", FAKE_SLACK_TOKEN),
        (f"password = '{FAKE_PASSPHRASE}'", FAKE_PASSPHRASE),
        (f"aws_access_key = {FAKE_AWS_KEY}", FAKE_AWS_KEY),
    ],
)
def test_redact_removes_credentials(raw: str, must_not_contain: str) -> None:
    assert must_not_contain not in sweep.redact(raw)


def test_redact_leaves_ordinary_text_alone() -> None:
    ordinary = "uv run pytest tests/test_executions.py -v"
    assert sweep.redact(ordinary) == ordinary


def test_snippet_redacts_and_truncates() -> None:
    out = sweep.snippet(f"token={FAKE_GITLAB_PAT} " + "x" * 500)
    assert "glpat" not in out
    assert len(out) <= sweep.MAX_SNIPPET + 1  # +1 for the ellipsis


# ---------------------------------------------------------------------------
# House rules — both directions, per rule
# ---------------------------------------------------------------------------

BAD_COMMANDS = {
    "environment-test-from-host": "ENVIRONMENT=test uv run pytest tests/ -v",
    "workflow-upgrade-db": "uv run workflow upgrade-db",
    "shell-read-instead-of-read-tool": "cat scripts/preflight.py",
    "git-force-push": "git push --force-with-lease origin feat/x",
    "production-environment": "ENVIRONMENT=production python app/app.py",
    "system-python3": "/usr/bin/python3 scripts/skill_graph.py",
    "pytest-no-such-path": "uv run pytest -k foo -k bar",
}


@pytest.mark.parametrize("rule_id, command", sorted(BAD_COMMANDS.items()))
def test_house_rule_fires_on_the_bad_shape(rule_id: str, command: str) -> None:
    rule = next(r for r in sweep.HOUSE_RULES if r.rule_id == rule_id)
    assert rule.matches(command), f"{rule_id} did not fire on {command!r}"


def test_every_house_rule_has_a_bad_shape_test() -> None:
    """A rule with no fixture is a rule nobody proved fires — same discipline as
    mr_conflict_plan.py's allow-list, where a new row needs a fixture before it counts."""
    assert {r.rule_id for r in sweep.HOUSE_RULES} == set(BAD_COMMANDS)


@pytest.mark.parametrize(
    "command",
    [
        "uv run pytest tests/ -v",
        "uv run alembic upgrade head",
        "python3 scripts/skill_graph.py --check",
        "git push origin feat/x",
        "git push -u origin feat/x",
        # A pipeline that *processes* a file is a legitimate shell job, not a Read substitute.
        "cat scripts/preflight.py | grep -c def",
        "head -20 uv.lock | wc -l",
        "cat <<'EOF' > /tmp/x.py",
    ],
)
def test_house_rules_stay_quiet_on_good_commands(command: str) -> None:
    firing = [r.rule_id for r in sweep.HOUSE_RULES if r.matches(command)]
    assert not firing, f"{firing} false-positived on {command!r}"


def test_self_check_passes() -> None:
    assert sweep.check() == 0


# ---------------------------------------------------------------------------
# Correction detection
# ---------------------------------------------------------------------------


def test_short_human_correction_is_detected() -> None:
    assert sweep.is_human_correction("no, use alembic for that")
    assert sweep.is_human_correction("stop. that's wrong, revert it")


def test_skill_dispatch_is_not_a_correction() -> None:
    """The exact shape that made this signal ~85% noise against a real week: a headless
    dispatch carrying a prohibition, indistinguishable from a human prompt by flags."""
    dispatch = (
        "Read and follow the skill at: .claude/skills/review-feature/SKILL.md\n"
        "Scope: compliance-checks. Do not edit files outside the scope."
    )
    assert not sweep.is_human_correction(dispatch)


def test_long_prompt_containing_a_prohibition_is_not_a_correction() -> None:
    long_brief = "Audit the execution slice. " * 40 + " Do not edit application code."
    assert len(long_brief) > sweep.MAX_CORRECTION_CHARS
    assert not sweep.is_human_correction(long_brief)


def test_local_command_block_is_not_a_correction() -> None:
    assert not sweep.is_human_correction("<command-name>/model</command-name> no, opus")


# ---------------------------------------------------------------------------
# Collection and detectors
# ---------------------------------------------------------------------------


def test_collect_pairs_tool_calls_with_their_results(tmp_path: Path) -> None:
    _write_transcript(
        tmp_path,
        "s1",
        [
            _assistant("a1", TS, [_tool_use("t1", "Bash", {"command": "uv run pytest"})]),
            _tool_result("u1", TS, "t1", "boom", is_error=True),
        ],
    )
    sessions, calls, _ = sweep.collect(list(tmp_path.glob("*.jsonl")), NOW - timedelta(days=7), NOW)
    assert len(calls) == 1
    assert calls[0].tool == "Bash"
    assert calls[0].is_error is True
    assert calls[0].error_text == "boom"
    assert sessions["s1"].errors == 1


def test_records_outside_the_window_are_ignored(tmp_path: Path) -> None:
    old = (NOW - timedelta(days=30)).isoformat()
    _write_transcript(
        tmp_path,
        "s1",
        [
            _assistant("a1", old, [_tool_use("t1", "Bash", {"command": "echo old"})]),
            _assistant("a2", TS, [_tool_use("t2", "Bash", {"command": "echo new"})]),
        ],
    )
    _, calls, _ = sweep.collect(list(tmp_path.glob("*.jsonl")), NOW - timedelta(days=7), NOW)
    assert [c.command for c in calls] == ["echo new"]


def test_malformed_lines_do_not_abort_the_scan(tmp_path: Path) -> None:
    path = tmp_path / "s1.jsonl"
    good = json.dumps(_assistant("a1", TS, [_tool_use("t1", "Bash", {"command": "echo ok"})]))
    path.write_text(f"not json at all\n{good}\n{{truncated", encoding="utf-8")
    _, calls, _ = sweep.collect([path], NOW - timedelta(days=7), NOW)
    assert [c.command for c in calls] == ["echo ok"]


def test_detect_repeated_commands_needs_three(tmp_path: Path) -> None:
    calls = [sweep.ToolCall(uuid=f"u{i}", tool="Read", session="s1", ts=TS, command="/a.py") for i in range(3)]
    calls.append(sweep.ToolCall(uuid="u9", tool="Read", session="s1", ts=TS, command="/b.py"))
    found = sweep.detect_repeated_commands(calls)
    assert [f["command"] for f in found] == ["/a.py"]
    assert found[0]["count"] == 3


def test_detect_error_clusters_normalises_incidental_variation() -> None:
    calls = [
        sweep.ToolCall(
            uuid="u1",
            tool="Bash",
            session="s1",
            ts=TS,
            command="x",
            is_error=True,
            error_text="Exit code 2: file line 12 not found",
        ),
        sweep.ToolCall(
            uuid="u2",
            tool="Bash",
            session="s2",
            ts=TS,
            command="x",
            is_error=True,
            error_text="Exit code 2: file line 987 not found",
        ),
    ]
    clusters = sweep.detect_error_clusters(calls)
    assert len(clusters) == 1, "line numbers should not fork one failure into two clusters"
    assert clusters[0]["count"] == 2
    assert sorted(clusters[0]["sessions"]) == ["s1", "s2"]


def test_detect_house_rules_groups_and_counts() -> None:
    calls = [
        sweep.ToolCall(uuid=f"u{i}", tool="Bash", session="s1", ts=TS, command="ENVIRONMENT=test uv run pytest tests/")
        for i in range(2)
    ]
    found = sweep.detect_house_rules(calls)
    assert len(found) == 1
    assert found[0]["rule_id"] == "environment-test-from-host"
    assert found[0]["count"] == 2
    assert found[0]["fix"]


def test_evidence_pointers_are_capped() -> None:
    calls = [sweep.ToolCall(uuid=f"u{i}", tool="Bash", session="s1", ts=TS, command="x") for i in range(10)]
    assert len(sweep._evidence(calls)) == sweep.MAX_EVIDENCE


def test_skill_usage_separates_builtin_commands_from_roster_skills(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    (skills_dir / "review-feature").mkdir(parents=True)
    (skills_dir / "review-feature" / "SKILL.md").write_text("x", encoding="utf-8")
    (skills_dir / "fix-bug").mkdir(parents=True)
    (skills_dir / "fix-bug" / "SKILL.md").write_text("x", encoding="utf-8")

    stats = sweep.SessionStats(session_id="s1", path=tmp_path / "s1.jsonl")
    stats.skills.update({"review-feature": 2, "model": 3})

    usage = sweep.detect_skill_usage({"s1": stats}, skills_dir)
    assert usage["invoked"] == [("review-feature", 2)]
    assert ("model", 3) in usage["builtin_commands"]
    assert usage["never_invoked"] == ["fix-bug"]


def test_build_digest_end_to_end_is_redacted_and_bounded(tmp_path: Path) -> None:
    _write_transcript(
        tmp_path,
        "s1",
        [
            _assistant("a1", TS, [_tool_use("t1", "Bash", {"command": "ENVIRONMENT=test uv run pytest"})]),
            _tool_result("u1", TS, "t1", "hung", is_error=True),
            _prompt("p1", TS, "no, don't do that"),
            _assistant("a2", TS, [_tool_use("t2", "Bash", {"command": f"export TOKEN={FAKE_GITLAB_PAT}"})]),
        ],
    )
    digest = sweep.build_digest(days=7, transcript_root=tmp_path, skills_dir=tmp_path / "none", now=NOW)

    assert digest["schema"] == sweep.SCHEMA_VERSION
    assert digest["scanned"]["sessions"] == 1
    rule_ids = [v["rule_id"] for v in digest["signals"]["house_rule_violations"]]
    assert "environment-test-from-host" in rule_ids
    assert digest["signals"]["interventions"]["correction_count"] == 1
    assert FAKE_GITLAB_PAT not in json.dumps(digest), "digest leaked a credential"


def test_show_record_returns_the_named_record_redacted(tmp_path: Path) -> None:
    _write_transcript(tmp_path, "s1", [_prompt("p1", TS, f"token={FAKE_GITLAB_PAT} hello")])
    out = sweep.show_record("s1", "p1", tmp_path)
    assert "hello" in out
    assert FAKE_GITLAB_PAT not in out


def test_show_record_reports_a_miss_rather_than_raising(tmp_path: Path) -> None:
    assert "no record found" in sweep.show_record("nope", "nope", tmp_path)


# ---------------------------------------------------------------------------
# Watcher: state, lease fencing, quiet-week gate
# ---------------------------------------------------------------------------


@pytest.fixture()
def watch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The watcher module with its state/config/report paths redirected into tmp_path."""
    module = _load("session_sweep_watch", WATCH_SCRIPT)
    monkeypatch.setattr(module, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(module, "LOCK_PATH", tmp_path / "state.lock")
    monkeypatch.setattr(module, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(module, "LOG_DIR", tmp_path / "reports")
    return module


def test_iso_week_is_stable_within_a_week(watch) -> None:
    monday = datetime(2026, 8, 3, tzinfo=UTC)
    sunday = datetime(2026, 8, 9, tzinfo=UTC)
    assert watch.iso_week(monday) == watch.iso_week(sunday)
    assert watch.iso_week(datetime(2026, 8, 10, tzinfo=UTC)) != watch.iso_week(monday)


def test_update_week_round_trips(watch) -> None:
    watch.update_week("2026-W32", lambda e: e.update({"status": "handed_off", "lease_id": "abc"}))
    entry = watch.load_state()["weeks"]["2026-W32"]
    assert entry["status"] == "handed_off"
    assert entry["lease_id"] == "abc"
    assert entry["updated"]


def test_finalize_applies_when_the_lease_matches(watch) -> None:
    watch.update_week("2026-W32", lambda e: e.update({"status": "handed_off", "lease_id": "lease-a"}))
    assert watch.finalize("2026-W32", "lease-a", "authored", mr_ref="!12", findings=3) is True
    entry = watch.load_state()["weeks"]["2026-W32"]
    assert entry["status"] == "authored"
    assert entry["mr_ref"] == "!12"
    assert entry["findings"] == 3
    assert "lease_id" not in entry, "a settled outcome must release the lease"


def test_finalize_rejects_a_stale_lease(watch) -> None:
    """The race this closes: an old run's watchdog finishing late, after a newer
    reservation has already replaced it. It can validly acquire the lock — the lock proves
    nobody is mid-write, not that the writer is still the current owner."""
    watch.update_week("2026-W32", lambda e: e.update({"status": "handed_off", "lease_id": "lease-new"}))
    assert watch.finalize("2026-W32", "lease-old", "stalled") is False
    entry = watch.load_state()["weeks"]["2026-W32"]
    assert entry["status"] == "handed_off"
    assert entry["lease_id"] == "lease-new"


def test_concurrent_writers_do_not_lose_updates(watch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def bump(n: int) -> None:
        watch.update_week(f"w{n}", lambda e: e.update({"status": "handed_off"}))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(bump, range(24)))
    assert len(watch.load_state()["weeks"]) == 24


def test_count_signals_ignores_always_populated_groups(watch) -> None:
    """skill_usage and the session table are populated every single week. Counting them
    would make min_signals_to_launch unreachable and silently disable the quiet-week
    saving — the one path that keeps a clean week free."""
    digest = {
        "signals": {
            "house_rule_violations": [],
            "error_clusters": [],
            "repeated_commands": [],
            "oversized_results": [],
            "interventions": {"correction_count": 0, "interruptions": 0},
            "skill_usage": {"never_invoked": ["a", "b", "c"], "invoked": [("x", 1)]},
        }
    }
    assert watch.count_signals(digest) == 0

    digest["signals"]["error_clusters"] = [{"count": 3}]
    digest["signals"]["interventions"]["correction_count"] = 2
    assert watch.count_signals(digest) == 3


def test_quiet_week_records_no_findings_and_spawns_nothing(watch, monkeypatch: pytest.MonkeyPatch) -> None:
    quiet = {
        "scanned": {"sessions": 4, "tool_calls": 100},
        "signals": {
            "house_rule_violations": [],
            "error_clusters": [],
            "repeated_commands": [],
            "oversized_results": [],
            "interventions": {"correction_count": 0, "interruptions": 0},
        },
    }
    monkeypatch.setattr(watch, "build_digest", lambda cfg, week: (Path("/tmp/x"), quiet))
    monkeypatch.setattr(watch, "launch", lambda *a, **k: pytest.fail("a quiet week must not launch a model"))

    assert watch.tick({"min_signals_to_launch": 1}) == 0
    entry = watch.load_state()["weeks"][watch.iso_week()]
    assert entry["status"] == "no-findings"
    assert entry["findings"] == 0


def test_noisy_week_launches_the_author_phase(watch, monkeypatch: pytest.MonkeyPatch) -> None:
    noisy = {
        "scanned": {"sessions": 9, "tool_calls": 900},
        "signals": {
            "house_rule_violations": [{"rule_id": "x"}],
            "error_clusters": [],
            "repeated_commands": [],
            "oversized_results": [],
            "interventions": {"correction_count": 0, "interruptions": 0},
        },
    }
    launched: list[str] = []
    monkeypatch.setattr(watch, "build_digest", lambda cfg, week: (Path("/tmp/x"), noisy))
    monkeypatch.setattr(watch, "launch", lambda cfg, phase, *a, **k: launched.append(phase))

    watch.tick({"min_signals_to_launch": 1})
    assert launched == [watch.PHASE_AUTHOR]


def test_authored_week_advances_to_the_review_phase(watch, monkeypatch: pytest.MonkeyPatch) -> None:
    week = watch.iso_week()
    watch.update_week(week, lambda e: e.update({"status": "authored", "findings": 2, "digest_dir": "/tmp/x"}))
    launched: list[str] = []
    monkeypatch.setattr(watch, "launch", lambda cfg, phase, *a, **k: launched.append(phase))
    monkeypatch.setattr(watch, "build_digest", lambda *a, **k: pytest.fail("must not rebuild the digest"))

    watch.tick({})
    assert launched == [watch.PHASE_REVIEW]


@pytest.mark.parametrize("status", ["reviewed", "no-findings", "stalled"])
def test_terminal_weeks_are_inert(watch, monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    week = watch.iso_week()
    watch.update_week(week, lambda e: e.update({"status": status}))
    monkeypatch.setattr(watch, "build_digest", lambda *a, **k: pytest.fail("must not rebuild"))
    monkeypatch.setattr(watch, "launch", lambda *a, **k: pytest.fail("must not launch"))
    assert watch.tick({}) == 0


def test_in_flight_week_is_left_alone(watch, monkeypatch: pytest.MonkeyPatch) -> None:
    week = watch.iso_week()
    watch.update_week(week, lambda e: e.update({"status": "handed_off", "phase": "author", "lease_id": "l"}))
    monkeypatch.setattr(watch, "launch", lambda *a, **k: pytest.fail("must not relaunch a live run"))
    assert watch.tick({"agent_timeout_sec": 3600, "crash_grace_sec": 120}) == 0


def test_stale_handed_off_week_is_retried(watch, monkeypatch: pytest.MonkeyPatch) -> None:
    week = watch.iso_week()
    stale = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
    watch.update_week(week, lambda e: e.update({"status": "handed_off", "phase": "author", "lease_id": "l"}))
    # Reach past update_week's own timestamp to simulate a run that died hours ago.
    state = watch.load_state()
    state["weeks"][week]["updated"] = stale
    watch.STATE_PATH.write_text(json.dumps(state), encoding="utf-8")

    launched: list[str] = []
    monkeypatch.setattr(watch, "launch", lambda cfg, phase, *a, **k: launched.append(phase))
    watch.tick({"agent_timeout_sec": 3600, "crash_grace_sec": 120})
    assert launched == ["author"]


def test_launch_marks_stalled_once_attempts_are_exhausted(watch, monkeypatch: pytest.MonkeyPatch) -> None:
    week = watch.iso_week()
    # `phase` matters: the cap is per phase, so exhausting it requires the SAME phase's
    # count. A real `handed_off` entry always carries it (launch()'s reserve() writes it).
    watch.update_week(week, lambda e: e.update({"status": "handed_off", "phase": watch.PHASE_AUTHOR, "attempt": 2}))
    monkeypatch.setattr(watch, "spawn", lambda *a, **k: pytest.fail("must not spawn past the cap"))
    monkeypatch.setattr(watch, "ensure_worktree", lambda cfg, slug: pytest.fail("must not cut a worktree"))
    watch.launch({"max_attempts": 2}, watch.PHASE_AUTHOR, week, Path("/tmp/x"))
    assert watch.load_state()["weeks"][week]["status"] == "stalled"


def test_attempt_counter_resets_between_phases(watch, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: the counter is per PHASE, not per week.

    Carrying the author's count into the review phase meant an author that needed two
    attempts left the reviewer starting at three — instantly over the cap, so the review
    silently never ran and the week stalled with an unreviewed MR already open.
    """
    week = watch.iso_week()
    watch.update_week(
        week,
        lambda e: e.update(
            {"status": "authored", "phase": watch.PHASE_AUTHOR, "attempt": 2, "worktree_slug": "sweep-x"}
        ),
    )
    monkeypatch.setattr(watch, "_quota_ok", lambda cfg: (True, "ok"))
    monkeypatch.setattr(watch, "ensure_worktree", lambda cfg, slug: Path("/tmp/wt"))
    spawned: list[str] = []
    monkeypatch.setattr(watch, "spawn", lambda cfg, phase, *a, **k: spawned.append(phase) or Path("/tmp/l"))

    watch.launch({"max_attempts": 2}, watch.PHASE_REVIEW, week, Path("/tmp/x"))

    assert spawned == [watch.PHASE_REVIEW], "review phase must get its own attempt budget"
    entry = watch.load_state()["weeks"][week]
    assert entry["attempt"] == 1
    assert entry["status"] == "handed_off"


def test_held_author_phase_resumes_as_author_not_review(watch, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a mid-run quota wall can hold EITHER phase.

    Hardcoding the review phase here would skip a held author phase entirely and try to
    review an MR that was never opened.
    """
    week = watch.iso_week()
    watch.update_week(
        week,
        lambda e: e.update({"status": "held_for_capacity", "phase": watch.PHASE_AUTHOR, "digest_dir": "/tmp/x"}),
    )
    launched: list[str] = []
    monkeypatch.setattr(watch, "launch", lambda cfg, phase, *a, **k: launched.append(phase))
    monkeypatch.setattr(watch, "build_digest", lambda *a, **k: pytest.fail("must not rebuild the digest"))

    watch.tick({})
    assert launched == [watch.PHASE_AUTHOR]


def test_held_review_phase_resumes_as_review(watch, monkeypatch: pytest.MonkeyPatch) -> None:
    week = watch.iso_week()
    watch.update_week(
        week,
        lambda e: e.update({"status": "held_for_capacity", "phase": watch.PHASE_REVIEW, "digest_dir": "/tmp/x"}),
    )
    launched: list[str] = []
    monkeypatch.setattr(watch, "launch", lambda cfg, phase, *a, **k: launched.append(phase))
    watch.tick({})
    assert launched == [watch.PHASE_REVIEW]


def test_record_cli_resolves_the_week_from_the_lease(watch) -> None:
    week = watch.iso_week()
    watch.update_week(week, lambda e: e.update({"status": "handed_off", "lease_id": "lease-z"}))
    watch.CONFIG_PATH.write_text(json.dumps({"version": 1}), encoding="utf-8")

    rc = watch.main(["record", "--lease-id", "lease-z", "--status", "authored", "--mr", "!44", "--findings", "2"])
    assert rc == 0
    entry = watch.load_state()["weeks"][week]
    assert entry["status"] == "authored"
    assert entry["mr_ref"] == "!44"


def test_record_cli_ignores_an_unknown_lease(watch) -> None:
    watch.CONFIG_PATH.write_text(json.dumps({"version": 1}), encoding="utf-8")
    assert watch.main(["record", "--lease-id", "nobody", "--status", "reviewed"]) == 0
    assert watch.load_state()["weeks"] == {}


def test_spawn_rejects_a_crash_grace_too_small_to_bound_a_stop(watch, tmp_path: Path) -> None:
    """Below 2s there is no positive TimeoutStopSec strictly inside crash_grace_sec, so
    the 'dead before the watcher retries' guarantee cannot hold. Fail loudly rather than
    rounding up and hoping."""
    with pytest.raises(ValueError, match="crash_grace_sec"):
        watch.spawn({"crash_grace_sec": 1}, watch.PHASE_AUTHOR, "2026-W32", "lease", tmp_path, "prompt")


def test_author_command_runs_codex_unattended_with_high_effort(watch, tmp_path: Path) -> None:
    """The three flags that make this run without a human: approvals never, a
    workspace-write sandbox rooted at the worktree, and an EXPLICIT effort — gpt-5.6-sol
    defaults to low, so an unset effort ships a shallow review that still looks like one."""
    cmd = watch._agent_command({"author_model": "gpt-5.6-sol", "author_effort": "high"}, watch.PHASE_AUTHOR, tmp_path)
    assert "codex" in cmd
    assert 'approval_policy="never"' in cmd
    assert "--sandbox workspace-write" in cmd
    assert 'model_reasoning_effort="high"' in cmd
    assert "gpt-5.6-sol" in cmd
    assert f"--cd {tmp_path}" in cmd


def test_reviewer_command_runs_claude_opus_without_edit_authority(watch, tmp_path: Path) -> None:
    cmd = watch._agent_command({"reviewer_model": "opus", "reviewer_effort": "high"}, watch.PHASE_REVIEW, tmp_path)
    assert "claude" in cmd
    assert "--model opus" in cmd
    assert "--permission-mode auto" in cmd
    assert "acceptEdits" not in cmd


def test_author_prompt_points_at_the_skill_and_carries_the_lease(watch, tmp_path: Path) -> None:
    prompt = watch.build_prompt(
        watch.PHASE_AUTHOR, week="2026-W32", lease_id="lease-q", digest_dir=tmp_path, worktree=tmp_path, entry={}
    )
    assert watch.SKILL_PATH in prompt
    assert "lease-q" in prompt
    assert "digest.json" in prompt


def test_reviewer_prompt_points_at_the_index_not_the_digest(watch, tmp_path: Path) -> None:
    """The whole point of Phase B: the reviewer works from the findings index, so the
    prompt must not hand it the digest as its entry point."""
    prompt = watch.build_prompt(
        watch.PHASE_REVIEW,
        week="2026-W32",
        lease_id="l",
        digest_dir=tmp_path,
        worktree=tmp_path,
        entry={"mr_ref": "!9"},
    )
    assert "findings-index.json" in prompt
    assert "!9" in prompt
