"""Tests for scripts/agent_launch.py — the chain-stage launcher.

Pure over an injected routing dict: no herdr, no subprocess, no network. The point
of these tests is that a routing change which would silently spend the wrong quota
(or hand a grader write access) fails here rather than in an unattended run.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "agent_launch.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_launch", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_launch = _load_module()


@pytest.fixture
def routing() -> dict:
    """A minimal table exercising both engines and both access levels."""
    return {
        "engines": {
            "claude": {"bin": "claude", "models": {"opus": "opus", "sonnet": "sonnet"}},
            "codex": {"bin": "codex", "models": {"sol": "gpt-5.6-sol"}},
        },
        "defaults": {"timeout_ms": 1000, "tab_label_prefix": ""},
        "stages": {
            "build": {"engine": "claude", "model": "sonnet", "effort": "xhigh", "access": "write", "blocking": True},
            "security-audit": {
                "engine": "claude",
                "model": "sonnet",
                "effort": "high",
                "access": "read",
                "blocking": True,
            },
            "test-evaluator": {
                "engine": "codex",
                "model": "sol",
                "effort": "high",
                "codex_mode": "review",
                "access": "read",
                "blocking": True,
            },
            "spec-critic": {
                "engine": "codex",
                "model": "sol",
                "effort": "high",
                "codex_mode": "exec",
                "access": "read",
                "blocking": True,
            },
        },
    }


# --- resolution ------------------------------------------------------------


def test_resolve_stage_merges_engine_and_stage(routing):
    cfg = agent_launch.resolve_stage(routing, "build")
    assert cfg["_bin"] == "claude"
    assert cfg["_model_id"] == "sonnet"
    assert cfg["effort"] == "xhigh"


def test_unknown_stage_names_the_known_ones(routing):
    with pytest.raises(agent_launch.RoutingError) as exc:
        agent_launch.resolve_stage(routing, "nope")
    assert "build" in str(exc.value)


def test_unknown_engine_is_fatal(routing):
    routing["stages"]["build"]["engine"] = "ghost"
    with pytest.raises(agent_launch.RoutingError, match="unknown engine"):
        agent_launch.resolve_stage(routing, "build")


def test_unknown_model_is_fatal(routing):
    routing["stages"]["build"]["model"] = "turbo"
    with pytest.raises(agent_launch.RoutingError, match="unknown model"):
        agent_launch.resolve_stage(routing, "build")


# --- command construction --------------------------------------------------


def test_write_access_maps_to_accept_edits(routing):
    cfg = agent_launch.resolve_stage(routing, "build")
    cmd = agent_launch.build_command(cfg, prompt_file="/tmp/p.md")
    assert "--permission-mode acceptEdits" in cmd


def test_read_access_maps_to_auto(routing):
    """A read-only stage must never be launched with edit permissions."""
    cfg = agent_launch.resolve_stage(routing, "security-audit")
    cmd = agent_launch.build_command(cfg, prompt_file="/tmp/p.md")
    assert "--permission-mode auto" in cmd
    assert "acceptEdits" not in cmd


def test_read_access_withholds_the_edit_tools(routing):
    """`--permission-mode auto` auto-approves; it is not read-only. Without the tool
    denylist a Claude 'read' stage can edit the code it grades — which is how two
    stages sharing one worktree wrote overlapping fixes to the same files."""
    cfg = agent_launch.resolve_stage(routing, "security-audit")
    cmd = agent_launch.build_command(cfg, prompt_file="/tmp/p.md")
    assert "--disallowed-tools Edit Write NotebookEdit" in cmd


def test_write_access_keeps_the_edit_tools(routing):
    """The denylist must not leak onto stages whose whole job is writing code."""
    cfg = agent_launch.resolve_stage(routing, "build")
    cmd = agent_launch.build_command(cfg, prompt_file="/tmp/p.md")
    assert "--disallowed-tools" not in cmd


def test_claude_command_pipes_prompt_and_sets_model_and_effort(routing):
    cfg = agent_launch.resolve_stage(routing, "build")
    cmd = agent_launch.build_command(cfg, prompt_file="/tmp/p.md")
    assert cmd.startswith("cat /tmp/p.md | claude -p")
    assert "--model sonnet" in cmd
    assert "--effort xhigh" in cmd


def test_codex_review_uses_base_branch_and_read_only_sandbox(routing):
    cfg = agent_launch.resolve_stage(routing, "test-evaluator")
    cmd = agent_launch.build_command(cfg, prompt_file="/tmp/p.md", base="develop")
    assert "codex review --base develop" in cmd
    assert 'model="gpt-5.6-sol"' in cmd
    assert 'sandbox_mode="read-only"' in cmd


def test_codex_review_defaults_base_to_main(routing):
    cfg = agent_launch.resolve_stage(routing, "test-evaluator")
    cmd = agent_launch.build_command(cfg, prompt_file="/tmp/p.md")
    assert "--base main" in cmd


def test_codex_exec_sets_reasoning_effort_explicitly(routing):
    """gpt-5.6-sol defaults to `low` reasoning — an unset effort silently ships a
    shallow review, which is worse than no review because it looks like one."""
    cfg = agent_launch.resolve_stage(routing, "spec-critic")
    cmd = agent_launch.build_command(cfg, prompt_file="/tmp/p.md")
    assert 'model_reasoning_effort="high"' in cmd
    assert "codex exec" in cmd
    assert "--sandbox read-only" in cmd


def test_prompt_file_paths_are_shell_quoted(routing):
    cfg = agent_launch.resolve_stage(routing, "build")
    cmd = agent_launch.build_command(cfg, prompt_file="/tmp/a b.md")
    assert "'/tmp/a b.md'" in cmd


def test_mission_reporting_is_disabled_by_default(routing, monkeypatch):
    monkeypatch.delenv(agent_launch.MISSION_REPORT_ENV, raising=False)
    monkeypatch.setattr(agent_launch.shutil, "which", lambda name: "/bin/true")
    called = []
    monkeypatch.setattr(agent_launch, "_run", lambda argv, timeout=30: called.append(argv) or (0, "{}", ""))
    cfg = agent_launch.resolve_stage(routing, "build")
    assert (
        agent_launch._report_mission_start(
            stage="build", scope="auth", pane_id="w1:p2", tab_id="w1:t1", workdir="/tmp/wt", cfg=cfg
        )
        is None
    )
    assert called == []


def test_mission_reporting_failure_never_raises(routing, monkeypatch):
    monkeypatch.setenv(agent_launch.MISSION_REPORT_ENV, "1")
    monkeypatch.setattr(agent_launch.shutil, "which", lambda name: "/bin/mission-control")
    monkeypatch.setattr(agent_launch, "_run", lambda argv, timeout=30: (1, "", "state unavailable"))
    cfg = agent_launch.resolve_stage(routing, "build")
    assert (
        agent_launch._report_mission_start(
            stage="build", scope="auth", pane_id="w1:p2", tab_id="w1:t1", workdir="/tmp/wt", cfg=cfg
        )
        is None
    )


def test_mission_reporting_returns_run_id_when_enabled(routing, monkeypatch):
    monkeypatch.setenv(agent_launch.MISSION_REPORT_ENV, "1")
    monkeypatch.setattr(agent_launch.shutil, "which", lambda name: "/bin/mission-control")
    monkeypatch.setattr(agent_launch.uuid, "uuid4", lambda: type("U", (), {"hex": "abc123def456789"})())
    seen = []

    def fake_run(argv, timeout=30):
        seen.append((argv, timeout))
        return 0, '{"run_id":"chain-abc123def456"}', ""

    monkeypatch.setattr(agent_launch, "_run", fake_run)
    cfg = agent_launch.resolve_stage(routing, "build")
    result = agent_launch._report_mission_start(
        stage="build", scope="auth", pane_id="w1:p2", tab_id="w1:t1", workdir="/tmp/wt", cfg=cfg
    )
    assert result == "chain-abc123def456"
    assert seen[0][1] == 2
    assert "--pane-id" in seen[0][0]


def test_launch_cli_accepts_an_explicit_working_directory(monkeypatch, capsys):
    seen = {}

    def fake_launch(stage, **kwargs):
        seen.update(stage=stage, **kwargs)
        return {"pane_id": "w1:p2"}

    monkeypatch.setattr(agent_launch, "load_routing", lambda: {})
    monkeypatch.setattr(agent_launch, "launch", fake_launch)
    assert (
        agent_launch.main(
            ["launch", "build", "--scope", "auth", "--prompt-file", "/tmp/p.md", "--cwd", "/tmp/worktree"]
        )
        == 0
    )
    assert seen["cwd"] == "/tmp/worktree"
    assert json.loads(capsys.readouterr().out)["pane_id"] == "w1:p2"


def test_wait_returns_success_for_done_agent(monkeypatch):
    monkeypatch.setattr(agent_launch, "_herdr_json", lambda argv, timeout=5: {"pane": {"agent_status": "done"}})
    result = agent_launch.wait_for("w1:p2", timeout_ms=100, poll_interval=0.01, startup_grace=0)
    assert result["ok"] is True
    assert result["status"] == "done"


def test_wait_returns_failure_for_blocked_agent(monkeypatch):
    monkeypatch.setattr(agent_launch, "_herdr_json", lambda argv, timeout=5: {"pane": {"agent_status": "blocked"}})
    result = agent_launch.wait_for("w1:p2", timeout_ms=100, poll_interval=0.01, startup_grace=0)
    assert result["ok"] is False
    assert result["status"] == "blocked"


def test_wait_does_not_hang_when_noninteractive_agent_exits(monkeypatch):
    states = iter(["working", "unknown"])
    monkeypatch.setattr(agent_launch, "_herdr_json", lambda argv, timeout=5: {"pane": {"agent_status": next(states)}})
    monkeypatch.setattr(agent_launch.time, "sleep", lambda seconds: None)
    result = agent_launch.wait_for("w1:p2", timeout_ms=1000, poll_interval=0.01)
    assert result["ok"] is False
    assert result["status"] == "unknown"
    assert "exited" in result["detail"]


# --- table validation ------------------------------------------------------


def test_check_passes_on_a_coherent_table(routing, tmp_path):
    for stage in routing["stages"]:
        (tmp_path / stage).mkdir()
        (tmp_path / stage / "SKILL.md").write_text("x", encoding="utf-8")
    assert agent_launch.check(routing, skills_dir=tmp_path) == []


def test_check_rejects_a_grader_with_write_access(routing, tmp_path):
    """The fresh-eyes principle enforced at the permission layer: a grader that can
    edit what it grades is not an independent grader."""
    routing["stages"]["test-evaluator"]["access"] = "write"
    for stage in routing["stages"]:
        (tmp_path / stage).mkdir()
        (tmp_path / stage / "SKILL.md").write_text("x", encoding="utf-8")
    problems = agent_launch.check(routing, skills_dir=tmp_path)
    assert any("read-only" in p for p in problems)


def test_check_flags_unknown_effort(routing, tmp_path):
    routing["stages"]["build"]["effort"] = "turbo"
    for stage in routing["stages"]:
        (tmp_path / stage).mkdir()
        (tmp_path / stage / "SKILL.md").write_text("x", encoding="utf-8")
    problems = agent_launch.check(routing, skills_dir=tmp_path)
    assert any("unknown effort" in p for p in problems)


def test_check_flags_a_stage_with_no_skill(routing, tmp_path):
    """Catches routing that outlived the skill it points at."""
    problems = agent_launch.check(routing, skills_dir=tmp_path)
    assert any("no skill at" in p for p in problems)


def test_virtual_stages_need_no_skill_file(routing, tmp_path):
    assert "build" in agent_launch.VIRTUAL_STAGES
    problems = agent_launch.check(routing, skills_dir=tmp_path)
    assert not any(p.startswith("build:") for p in problems)


# --- the real table --------------------------------------------------------


def test_shipped_routing_table_is_valid():
    """The table this repo actually ships must pass its own checker."""
    assert agent_launch.check(agent_launch.load_routing()) == []


# --- concurrency: one writer per worktree ----------------------------------


def test_check_rejects_two_writers_in_one_parallel_group(routing):
    """The collision this guard exists for: every stage shares one worktree, so two
    write-access stages in the same turn edit the same files with no coordination —
    and both report success, because neither can see the other."""
    routing["stages"]["e2e-playwright"] = {
        "engine": "claude",
        "model": "sonnet",
        "effort": "high",
        "access": "write",
        "blocking": True,
    }
    routing["concurrency"] = {"parallel_groups": [["build", "e2e-playwright"]]}
    problems = agent_launch._check_parallel_groups(routing)
    assert len(problems) == 1
    assert "at most one writer" in problems[0]


def test_check_allows_a_reader_beside_a_writer(routing):
    """read ∥ write is the shape the chain actually declares, and it is safe."""
    routing["concurrency"] = {"parallel_groups": [["security-audit", "build"]]}
    assert agent_launch._check_parallel_groups(routing) == []


def test_check_flags_an_unknown_stage_in_a_parallel_group(routing):
    routing["concurrency"] = {"parallel_groups": [["build", "ghost"]]}
    assert "unknown stage(s) ghost" in agent_launch._check_parallel_groups(routing)[0]


def test_check_flags_a_stage_parallel_with_itself(routing):
    routing["concurrency"] = {"parallel_groups": [["build", "build"]]}
    assert "parallel with itself" in agent_launch._check_parallel_groups(routing)[0]


def test_a_table_declaring_no_concurrency_is_valid(routing):
    """Fully serial is always safe; absence of the block must not be an error."""
    assert agent_launch._check_parallel_groups(routing) == []


def test_shipped_table_declares_at_most_one_writer_per_group():
    """Guards the real table, not a fixture: if someone parallelises two writing
    stages, CI fails here before a run corrupts a worktree."""
    routing = agent_launch.load_routing()
    groups = routing["concurrency"]["parallel_groups"]
    assert groups, "the chain declares one parallel pair; an empty list means it was lost"
    for group in groups:
        writers = [s for s in group if routing["stages"][s]["access"] == "write"]
        assert len(writers) <= 1, f"{group} has multiple writers: {writers}"


def test_shipped_table_puts_opus_only_where_it_earns_it():
    """Guards the cost posture: Opus is the scarcest quota on a $20 plan, so it is
    reserved for spec work, where an error is most expensive to discover late."""
    routing = agent_launch.load_routing()
    opus_stages = {
        name for name in routing["stages"] if agent_launch.resolve_stage(routing, name)["_model_id"] == "opus"
    }
    assert opus_stages == {"spec-first"}


def test_shipped_table_routes_every_grader_to_a_separate_engine():
    """Graders run on Codex: fresh eyes and, on dual $20 plans, a separate quota pool."""
    routing = agent_launch.load_routing()
    for stage in ("spec-critic", "test-evaluator", "build-review"):
        assert agent_launch.resolve_stage(routing, stage)["engine"] == "codex"


def test_load_routing_rejects_malformed_json(tmp_path):
    bad = tmp_path / "routing.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(agent_launch.RoutingError, match="not valid JSON"):
        agent_launch.load_routing(bad)


def test_load_routing_reports_a_missing_table(tmp_path):
    with pytest.raises(agent_launch.RoutingError, match="not found"):
        agent_launch.load_routing(tmp_path / "absent.json")


def test_launch_refuses_outside_herdr(routing, monkeypatch):
    """Launching a tab outside Herdr would silently do nothing useful."""
    monkeypatch.delenv("HERDR_ENV", raising=False)
    with pytest.raises(agent_launch.RoutingError, match="not running inside Herdr"):
        agent_launch.launch("build", scope="x", prompt_file="/tmp/p.md", routing=routing)


def test_workspace_for_workdir_uses_the_worker_owning_that_checkout(monkeypatch, tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    monkeypatch.setattr(
        agent_launch,
        "_herdr_json",
        lambda argv, **_kwargs: {
            "agents": [
                {"workspace_id": "w-sauron", "foreground_cwd": str(tmp_path / "sauron")},
                {"workspace_id": "w-worker", "foreground_cwd": str(worker)},
            ]
        },
    )

    assert agent_launch._workspace_for_workdir(str(worker)) == "w-worker"


def test_workspace_for_workdir_refuses_to_fall_back_to_the_focused_workspace(monkeypatch, tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    monkeypatch.setattr(agent_launch, "_herdr_json", lambda argv, **_kwargs: {"agents": []})

    with pytest.raises(agent_launch.RoutingError, match="refusing to put a stage in the focused workspace"):
        agent_launch._workspace_for_workdir(str(worker))


def test_launch_places_the_stage_in_the_worker_workspace(routing, monkeypatch, tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    calls: list[list[str]] = []

    def fake_herdr(argv, **_kwargs):
        calls.append(argv)
        if argv[1:3] == ["agent", "list"]:
            return {"agents": [{"workspace_id": "w-worker", "foreground_cwd": str(worker)}]}
        if argv[1:3] == ["tab", "create"]:
            return {"tab": {"tab_id": "w-worker:t2"}, "root_pane": {"pane_id": "w-worker:p2"}}
        if argv[1:3] == ["pane", "run"]:
            return {}
        raise AssertionError(argv)

    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setattr(agent_launch, "_herdr_json", fake_herdr)
    monkeypatch.setattr(agent_launch, "_report_mission_start", lambda **_kwargs: None)

    result = agent_launch.launch("build", scope="demo", prompt_file="/tmp/p.md", routing=routing, cwd=str(worker))

    assert result["workspace_id"] == "w-worker"
    assert calls[1] == [
        "herdr",
        "tab",
        "create",
        "--workspace",
        "w-worker",
        "--label",
        "build·demo",
        "--cwd",
        str(worker),
        "--no-focus",
    ]


def test_close_stage_closes_only_a_completed_non_root_tab(monkeypatch):
    calls: list[list[str]] = []

    def fake_herdr(argv, **_kwargs):
        calls.append(argv)
        if argv[1:3] == ["pane", "get"]:
            return {"pane": {"agent_status": "unknown", "tab_id": "w-worker:t2", "workspace_id": "w-worker"}}
        if argv[1:3] == ["tab", "close"]:
            return {}
        raise AssertionError(argv)

    monkeypatch.setattr(agent_launch, "_herdr_json", fake_herdr)

    result = agent_launch.close_stage("w-worker:p2")
    assert result["closed"] is True
    assert result["workspace_closed"] is False
    assert calls[1] == ["herdr", "tab", "close", "w-worker:t2"]


def test_close_stage_closes_an_empty_stage_only_workspace(monkeypatch):
    calls: list[list[str]] = []

    def fake_herdr(argv, **_kwargs):
        calls.append(argv)
        if argv[1:3] == ["pane", "get"]:
            return {"pane": {"agent_status": "unknown", "tab_id": "w-stage:t2", "workspace_id": "w-stage"}}
        if argv[1:3] == ["tab", "close"]:
            raise agent_launch.RoutingError("herdr tab close failed: cannot close the last tab in a workspace")
        if argv[1:3] == ["workspace", "close"]:
            return {}
        raise AssertionError(argv)

    monkeypatch.setattr(agent_launch, "_herdr_json", fake_herdr)

    result = agent_launch.close_stage("w-stage:p2")

    assert result["closed"] is True
    assert result["workspace_closed"] is True
    assert calls[2] == ["herdr", "workspace", "close", "w-stage"]


def test_close_stage_refuses_a_live_agent_or_root_tab(monkeypatch):
    monkeypatch.setattr(
        agent_launch,
        "_herdr_json",
        lambda argv, **_kwargs: {
            "pane": {"agent_status": "working", "tab_id": "w-worker:t2", "workspace_id": "w-worker"}
        },
    )
    with pytest.raises(agent_launch.RoutingError, match="refusing to close active"):
        agent_launch.close_stage("w-worker:p2")

    monkeypatch.setattr(
        agent_launch,
        "_herdr_json",
        lambda argv, **_kwargs: {
            "pane": {"agent_status": "unknown", "tab_id": "w-worker:t1", "workspace_id": "w-worker"}
        },
    )
    with pytest.raises(agent_launch.RoutingError, match="refusing to close root"):
        agent_launch.close_stage("w-worker:p1")


def test_render_plan_lists_every_stage(routing):
    plan = agent_launch.render_plan(routing)
    for stage in routing["stages"]:
        assert stage in plan
    assert "advisory" in plan or "blocking" in plan


def test_cli_check_exits_zero_on_the_real_table(capsys):
    assert agent_launch.main(["--check"]) == 0


def test_cli_cmd_prints_a_runnable_command(capsys):
    assert agent_launch.main(["cmd", "build", "--prompt-file", "/tmp/p.md"]) == 0
    out = capsys.readouterr().out
    assert "claude -p" in out


def test_cli_unknown_stage_exits_one(capsys):
    assert agent_launch.main(["cmd", "ghost", "--prompt-file", "/tmp/p.md"]) == 1


def test_routing_json_is_documented():
    """Every stage carries a `why` — routing decisions that outlive their rationale
    are the ones nobody dares change."""
    routing = agent_launch.load_routing()
    for name, cfg in routing["stages"].items():
        assert cfg.get("why"), f"{name} has no rationale"


def test_routing_file_round_trips_as_json():
    raw = (REPO_ROOT / ".agents" / "model-routing.json").read_text(encoding="utf-8")
    assert json.loads(raw)["version"] == 1


# --- herdr envelope handling ------------------------------------------------------------
#
# Regression cover for a bug that made the entire `herdr-tabs` execution mode unusable:
# `_herdr_json` demanded a JSON envelope from every herdr call, but `herdr pane run` is
# fire-and-forget and exits 0 with empty stdout (herdr 0.7.3). So `launch` created the tab,
# then blew up on the very next call with "herdr returned non-JSON:" — and every skill that
# calls `agent_launch.py launch` silently fell back to subagents instead of running stages
# in their own labelled tabs, on their own engines.


def _fake_run(monkeypatch, *, code=0, out="", err=""):
    monkeypatch.setattr(agent_launch.shutil, "which", lambda _: "/usr/bin/herdr")
    monkeypatch.setattr(agent_launch, "_run", lambda argv, timeout=30: (code, out, err))


def test_empty_output_is_accepted_when_allowed(monkeypatch):
    """`herdr pane run` succeeds silently — that must not be an error."""
    _fake_run(monkeypatch, code=0, out="")
    assert agent_launch._herdr_json(["herdr", "pane", "run", "w1:p1", "cmd"], allow_empty=True) == {}


def test_empty_output_is_still_an_error_when_an_envelope_is_expected(monkeypatch):
    """Commands we read IDs out of must not silently yield an empty dict — that would
    turn a missing pane_id into a KeyError far from the cause."""
    _fake_run(monkeypatch, code=0, out="")
    with pytest.raises(agent_launch.RoutingError, match="returned no output"):
        agent_launch._herdr_json(["herdr", "tab", "create", "--label", "x"])


def test_nonzero_exit_reports_the_code(monkeypatch):
    _fake_run(monkeypatch, code=2, err="boom")
    with pytest.raises(agent_launch.RoutingError, match=r"exit 2"):
        agent_launch._herdr_json(["herdr", "pane", "run", "w1:p1", "cmd"], allow_empty=True)


def test_allow_empty_does_not_swallow_a_real_error_envelope(monkeypatch):
    """allow_empty relaxes *emptiness*, never error reporting."""
    _fake_run(monkeypatch, code=0, out=json.dumps({"error": "no such pane"}))
    with pytest.raises(agent_launch.RoutingError, match="no such pane"):
        agent_launch._herdr_json(["herdr", "pane", "run", "w9:p9", "cmd"], allow_empty=True)


def test_result_is_unwrapped_from_the_envelope(monkeypatch):
    _fake_run(monkeypatch, code=0, out=json.dumps({"id": "cli:tab:create", "result": {"tab": {"tab_id": "w1:t1"}}}))
    assert agent_launch._herdr_json(["herdr", "tab", "create"])["tab"]["tab_id"] == "w1:t1"
