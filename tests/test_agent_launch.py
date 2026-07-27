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
