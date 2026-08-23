#!/usr/bin/env python3
"""Launch a chain stage as its own Herdr tab, on the engine `.agents/model-routing.json` says.

Why this exists: the routing table (which model, which effort, how much filesystem
access) is a policy decision that drifts the moment it lives inline in prose. Skills
call `agent_launch.py launch <stage>` and get the right flags by construction; the
policy changes in one JSON file.

The second reason is visibility. A stage launched here runs in a labelled Herdr tab
the founder can watch and scroll back through, instead of inside the orchestrator's
process where only a verdict line escapes.

    python scripts/agent_launch.py plan                      # show the routing table
    python scripts/agent_launch.py cmd security-audit --scope inventory --prompt-file P
    python scripts/agent_launch.py launch security-audit --scope inventory --prompt-file P
    python scripts/agent_launch.py wait w1:pK --timeout 600000
    python scripts/agent_launch.py --check                   # CI: routing matches the skills

Stdlib only, no app imports: this runs before (and independently of) the app.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTING_PATH = REPO_ROOT / ".agents" / "model-routing.json"
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"

# Stages that are chain steps rather than skills of their own. Everything else in the
# routing table must resolve to a real SKILL.md, or --check fails.
VIRTUAL_STAGES = {"build", "build-review", "security-tenant-audit", "findings-review"}

# The edit tools withheld from a Claude-engine `access: read` stage. Bash is deliberately
# NOT withheld — graders need it to run semgrep, pytest and git — so this is a guardrail,
# not a sandbox: a stage that shells out can still write. Only Codex's `--sandbox
# read-only` closes that hole. The structural guarantee is one writer per worktree
# (see PARALLEL group validation below), not this list.
READ_ONLY_DENIED_TOOLS = ("Edit", "Write", "NotebookEdit")
MISSION_REPORT_ENV = "MISSION_CONTROL_REPORT"


class RoutingError(RuntimeError):
    """Raised when the routing table cannot answer the question asked of it."""


def load_routing(path: Path = ROUTING_PATH) -> dict[str, Any]:
    """Read the routing table. A malformed table is fatal — guessing a model is worse
    than stopping, because the wrong guess silently spends the wrong quota."""
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise RoutingError(f"routing table not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RoutingError(f"routing table is not valid JSON: {exc}") from exc


def resolve_stage(routing: dict[str, Any], stage: str) -> dict[str, Any]:
    """Return the merged engine+stage config for one stage."""
    stages = routing.get("stages", {})
    if stage not in stages:
        known = ", ".join(sorted(stages))
        raise RoutingError(f"unknown stage {stage!r}. Known stages: {known}")
    cfg = dict(stages[stage])
    engine_name = cfg.get("engine")
    engines = routing.get("engines", {})
    if engine_name not in engines:
        raise RoutingError(f"stage {stage!r} names unknown engine {engine_name!r}")
    engine = engines[engine_name]
    model_key = cfg.get("model")
    if model_key not in engine.get("models", {}):
        raise RoutingError(f"stage {stage!r} names unknown model {model_key!r} for engine {engine_name!r}")
    cfg["_bin"] = engine["bin"]
    cfg["_model_id"] = engine["models"][model_key]
    cfg["_stage"] = stage
    return cfg


def build_command(cfg: dict[str, Any], *, prompt_file: str, base: str | None = None) -> str:
    """Build the shell command Herdr types into the new tab.

    The prompt is piped or substituted from a file so the typed line stays short —
    a long quoted prompt on the command line is where quoting bugs live.
    """
    engine = cfg["engine"]
    quoted_prompt = shlex.quote(prompt_file)

    if engine == "claude":
        parts = [
            cfg["_bin"],
            "-p",
            "--model",
            cfg["_model_id"],
            "--effort",
            cfg["effort"],
            "--permission-mode",
            "acceptEdits" if cfg["access"] == "write" else "auto",
        ]
        if cfg["access"] == "read":
            # `--permission-mode auto` is not read-only — it auto-approves. Without this,
            # a Claude "read" stage can edit the code it grades, which is how two stages
            # in one worktree end up writing overlapping fixes to the same file. Codex
            # gets a real syscall sandbox below; this is the nearest Claude equivalent.
            parts += ["--disallowed-tools", *READ_ONLY_DENIED_TOOLS]
        return f"cat {quoted_prompt} | " + " ".join(shlex.quote(p) for p in parts)

    if engine == "codex":
        mode = cfg.get("codex_mode", "exec")
        sandbox = "read-only" if cfg["access"] == "read" else "workspace-write"
        if mode == "review":
            parts = [
                cfg["_bin"],
                "review",
                "--base",
                base or "main",
                "-c",
                f'model="{cfg["_model_id"]}"',
                "-c",
                f'model_reasoning_effort="{cfg["effort"]}"',
                "-c",
                f'sandbox_mode="{sandbox}"',
                "-",
            ]
            return f"cat {quoted_prompt} | " + " ".join(shlex.quote(p) for p in parts)
        parts = [
            cfg["_bin"],
            "exec",
            "--sandbox",
            sandbox,
            "-m",
            cfg["_model_id"],
            "-c",
            f'model_reasoning_effort="{cfg["effort"]}"',
        ]
        return " ".join(shlex.quote(p) for p in parts) + f' "$(cat {quoted_prompt})"'

    raise RoutingError(f"no command builder for engine {engine!r}")


def _run(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)


def _report_mission_start(
    *,
    stage: str,
    scope: str,
    pane_id: str,
    tab_id: str,
    workdir: str,
    cfg: dict[str, Any],
) -> str | None:
    """Best-effort shadow telemetry. It is opt-in and cannot affect launch.

    Mission Control is deliberately an observer during its proving period. A missing
    binary, malformed response, timeout, or write failure therefore returns ``None``;
    the stage has already launched and its execution semantics remain unchanged.
    """
    if os.getenv(MISSION_REPORT_ENV) != "1" or not shutil.which("mission-control"):
        return None
    run_id = f"chain-{uuid.uuid4().hex[:12]}"
    argv = [
        "mission-control",
        "report",
        "start",
        "--run-id",
        run_id,
        "--pane-id",
        pane_id,
        "--tab-id",
        tab_id,
        "--worktree",
        workdir,
        "--agent",
        cfg["engine"],
        "--model",
        cfg["_model_id"],
        "--skill",
        stage,
        "--stage",
        stage,
        "--scope",
        scope,
        "--goal",
        f"Run {stage} for {scope or 'current scope'}",
        "--done-when",
        "The stage report exists and its explicit verdict has been recorded",
    ]
    code, out, _ = _run(argv, timeout=2)
    if code != 0:
        return None
    try:
        value = json.loads(out)
    except json.JSONDecodeError:
        return None
    return str(value.get("run_id")) if value.get("run_id") else None


def _herdr_json(argv: list[str], timeout: int = 30, *, allow_empty: bool = False) -> dict[str, Any]:
    """Call herdr and parse its JSON envelope. Herdr IDs are opaque — always read them
    from the response, never guess them from sidebar order.

    Not every herdr subcommand answers with an envelope. `pane run` in particular is
    fire-and-forget: it dispatches the command to the pane and exits 0 with an empty
    stdout (verified against herdr 0.7.3). Demanding JSON from it made every
    `agent_launch.py launch` die with "herdr returned non-JSON:" *after* the tab had
    already been created — so the whole herdr-tabs execution mode was unusable and every
    caller silently fell back to subagents. Pass `allow_empty=True` for those commands;
    exit status stays the real success signal.
    """
    if not shutil.which("herdr"):
        raise RoutingError("herdr CLI not found on PATH")
    code, out, err = _run(argv, timeout=timeout)
    if code != 0:
        raise RoutingError(f"herdr {' '.join(argv[1:3])} failed (exit {code}): {err or out}")

    out = out.strip()
    if not out:
        if allow_empty:
            return {}
        raise RoutingError(f"herdr {' '.join(argv[1:3])} returned no output (exit {code}); expected a JSON envelope")

    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        raise RoutingError(f"herdr {' '.join(argv[1:3])} returned non-JSON: {out[:200]}") from exc
    if "error" in payload:
        raise RoutingError(f"herdr error: {payload['error']}")
    return payload.get("result", payload)


def _workspace_for_workdir(workdir: str) -> str:
    """Return the live Herdr workspace whose running agent owns the workdir.

    herdr tab create otherwise defaults to the focused workspace. A coordinator
    can be focused while it dispatches a worker's review chain, which used to put
    that worker's stage tabs inside the coordinator's workspace. Match the live
    agent's actual checkout and refuse to guess when it is absent.
    """
    target = Path(workdir).resolve()
    result = _herdr_json(["herdr", "agent", "list"])
    agents = result.get("agents")
    if not isinstance(agents, list):
        raise RoutingError("herdr agent list returned an unexpected response")
    matches: set[str] = set()
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        candidate = agent.get("foreground_cwd") or agent.get("cwd")
        workspace_id = agent.get("workspace_id")
        if not isinstance(candidate, str) or not isinstance(workspace_id, str):
            continue
        try:
            if Path(candidate).resolve() == target:
                matches.add(workspace_id)
        except OSError:
            continue
    if len(matches) == 1:
        return matches.pop()
    if not matches:
        raise RoutingError(f"no live Herdr workspace owns {target}; refusing to put a stage in the focused workspace")
    raise RoutingError(f"multiple live Herdr workspaces own {target}: {', '.join(sorted(matches))}")


def launch(
    stage: str,
    *,
    scope: str,
    prompt_file: str,
    base: str | None = None,
    routing: dict[str, Any] | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Create a labelled tab and start the stage's agent in it. Never steals focus."""
    routing = routing or load_routing()
    cfg = resolve_stage(routing, stage)
    if os.getenv("HERDR_ENV") != "1":
        raise RoutingError("not running inside Herdr (HERDR_ENV != 1); use subagent mode instead")

    prefix = routing.get("defaults", {}).get("tab_label_prefix", "")
    label = f"{prefix}{stage}·{scope}" if scope else f"{prefix}{stage}"
    workdir = cwd or str(REPO_ROOT)
    workspace_id = _workspace_for_workdir(workdir)

    tab = _herdr_json(
        ["herdr", "tab", "create", "--workspace", workspace_id, "--label", label, "--cwd", workdir, "--no-focus"]
    )
    tab_id = tab["tab"]["tab_id"]
    pane_id = tab["root_pane"]["pane_id"]

    command = build_command(cfg, prompt_file=prompt_file, base=base)
    # `pane run` is fire-and-forget and prints nothing on success — see _herdr_json.
    _herdr_json(["herdr", "pane", "run", pane_id, command], allow_empty=True)

    mission_run_id = _report_mission_start(
        stage=stage,
        scope=scope,
        pane_id=pane_id,
        tab_id=tab_id,
        workdir=workdir,
        cfg=cfg,
    )

    return {
        "stage": stage,
        "scope": scope,
        "engine": cfg["engine"],
        "model": cfg["_model_id"],
        "effort": cfg["effort"],
        "access": cfg["access"],
        "blocking": cfg["blocking"],
        "tab_id": tab_id,
        "pane_id": pane_id,
        "label": label,
        "workspace_id": workspace_id,
        "command": command,
        "mission_run_id": mission_run_id,
    }


def close_stage(pane_id: str) -> dict[str, Any]:
    """Close a completed chain-stage tab after its verdict has been handed back.

    Stage tabs are disposable. Refuse to touch a live process or a workspace's
    root tab: either case is a real worker, not a completed review stage.
    """
    result = _herdr_json(["herdr", "pane", "get", pane_id], timeout=5)
    pane = result.get("pane", result)
    if not isinstance(pane, dict):
        raise RoutingError(f"herdr pane get returned an unexpected response for {pane_id}")
    status = str(pane.get("agent_status") or "unknown")
    tab_id = pane.get("tab_id")
    workspace_id = pane.get("workspace_id")
    if not isinstance(tab_id, str) or not isinstance(workspace_id, str):
        raise RoutingError(f"pane {pane_id} has no tab/workspace identity")
    if tab_id == f"{workspace_id}:t1":
        raise RoutingError(f"refusing to close root worker tab {tab_id}")
    if status not in {"idle", "done", "unknown"}:
        raise RoutingError(f"refusing to close active stage pane {pane_id} (status {status})")
    try:
        _herdr_json(["herdr", "tab", "close", tab_id], timeout=10, allow_empty=True)
    except RoutingError as exc:
        # Herdr protects the final tab in a workspace. This can happen when a
        # worker exited and only its completed stage remains. It is still safe
        # to remove because this helper has already rejected live/root panes.
        if "cannot close the last tab in a workspace" not in str(exc):
            raise
        _herdr_json(["herdr", "workspace", "close", workspace_id], timeout=10, allow_empty=True)
        return {
            "pane_id": pane_id,
            "tab_id": tab_id,
            "status": status,
            "closed": True,
            "workspace_closed": True,
        }
    return {"pane_id": pane_id, "tab_id": tab_id, "status": status, "closed": True, "workspace_closed": False}


def wait_for(
    pane_id: str,
    timeout_ms: int = 1800000,
    *,
    poll_interval: float = 0.5,
    startup_grace: float = 30.0,
) -> dict[str, Any]:
    """Wait for a stage without mistaking an exited agent for success.

    Non-interactive Claude/Codex processes return the pane to its shell, which Herdr
    reports as ``unknown``. Waiting only for ``idle`` can therefore hang for the full
    timeout after quota failures or ordinary process exit. Poll the semantic state so
    blocked and exited stages return an explicit failure. ``unknown`` before an agent
    first appears gets a startup grace period; after a recognized state it means the
    agent left the pane and cannot prove successful completion.
    """
    started = time.monotonic()
    deadline = started + timeout_ms / 1000
    seen_agent = False
    last_status = "unknown"
    while time.monotonic() < deadline:
        try:
            result = _herdr_json(["herdr", "pane", "get", pane_id], timeout=5)
        except RoutingError as exc:
            return {"pane_id": pane_id, "ok": False, "status": "unknown", "detail": str(exc)[:400]}
        pane = result.get("pane", result)
        status = str(pane.get("agent_status") or "unknown") if isinstance(pane, dict) else "unknown"
        last_status = status
        if status in {"working", "blocked", "idle", "done"}:
            seen_agent = True
        if status in {"idle", "done"}:
            return {"pane_id": pane_id, "ok": True, "status": status, "detail": f"agent settled: {status}"}
        if status == "blocked":
            return {"pane_id": pane_id, "ok": False, "status": status, "detail": "agent needs input"}
        if status == "unknown" and (seen_agent or time.monotonic() - started >= startup_grace):
            return {
                "pane_id": pane_id,
                "ok": False,
                "status": status,
                "detail": "agent exited or was never detected; inspect its report/transcript",
            }
        time.sleep(max(0.01, poll_interval))
    return {"pane_id": pane_id, "ok": False, "status": last_status, "detail": "timed out waiting for agent"}


def render_plan(routing: dict[str, Any]) -> str:
    """Human-readable routing table — what runs where, and on whose quota."""
    lines = ["stage                   engine  model            effort  access  gate"]
    lines.append("-" * 74)
    for name in routing.get("stages", {}):
        cfg = resolve_stage(routing, name)
        gate = "blocking" if cfg["blocking"] else "advisory"
        lines.append(
            f"{name:<23} {cfg['engine']:<7} {cfg['_model_id']:<16} {cfg['effort']:<7} {cfg['access']:<7} {gate}"
        )

    groups = routing.get("concurrency", {}).get("parallel_groups", [])
    lines.append("")
    lines.append("concurrency: everything is serial except these groups (max one writer each)")
    for group in groups:
        lines.append("  " + " ∥ ".join(group))
    if not groups:
        lines.append("  (none — fully serial)")
    return "\n".join(lines)


def check(routing: dict[str, Any], skills_dir: Path = SKILLS_DIR) -> list[str]:
    """Return a list of routing problems. Empty list means the table is coherent.

    Catches the drift that matters: a stage routed to a skill that no longer exists,
    a grader accidentally given write access, or an unknown effort level.
    """
    problems: list[str] = []
    valid_effort = {"low", "medium", "high", "xhigh", "max", "ultra"}
    # A grader that can edit the thing it grades is not an independent grader.
    graders = {
        "spec-critic",
        "test-evaluator",
        "build-review",
        "security-tenant-audit",
        "security-audit",
        "findings-review",
    }

    for name in routing.get("stages", {}):
        try:
            cfg = resolve_stage(routing, name)
        except RoutingError as exc:
            problems.append(str(exc))
            continue
        if cfg["effort"] not in valid_effort:
            problems.append(f"{name}: unknown effort {cfg['effort']!r}")
        if cfg["access"] not in {"read", "write"}:
            problems.append(f"{name}: access must be 'read' or 'write', got {cfg['access']!r}")
        if name in graders and cfg["access"] != "read":
            problems.append(f"{name}: grader stages must be read-only (fresh-eyes principle)")
        if name not in VIRTUAL_STAGES and not (skills_dir / name / "SKILL.md").exists():
            problems.append(f"{name}: no skill at {skills_dir / name / 'SKILL.md'}")

    problems.extend(_check_parallel_groups(routing))
    return problems


def _check_parallel_groups(routing: dict[str, Any]) -> list[str]:
    """Validate the declared parallel groups.

    Every stage in the chain shares ONE worktree. Two write-access stages running in the
    same turn edit the same tree with no coordination, and the failure is silent: both
    agents "succeed", and whichever wrote last wins. Declaring concurrency as data lets
    that be a CI failure instead of a corrupted run.
    """
    problems: list[str] = []
    stages = routing.get("stages", {})
    groups = routing.get("concurrency", {}).get("parallel_groups", [])

    for group in groups:
        label = " ∥ ".join(group)
        unknown = [s for s in group if s not in stages]
        if unknown:
            problems.append(f"parallel group [{label}]: unknown stage(s) {', '.join(unknown)}")
            continue
        if len(set(group)) != len(group):
            problems.append(f"parallel group [{label}]: a stage cannot run in parallel with itself")
            continue
        writers = [s for s in group if stages[s].get("access") == "write"]
        if len(writers) > 1:
            problems.append(
                f"parallel group [{label}]: {len(writers)} write-access stages "
                f"({', '.join(writers)}) — one shared worktree allows at most one writer"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate the routing table, exit 1 on problems")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("plan", help="print the routing table")

    for name in ("cmd", "launch"):
        p = sub.add_parser(name, help="build (cmd) or build-and-run (launch) a stage")
        p.add_argument("stage")
        p.add_argument("--scope", default="", help="feature slug, used in the tab label")
        p.add_argument("--prompt-file", required=True, help="file holding the stage prompt")
        p.add_argument("--base", default=None, help="base branch for codex review stages")
        p.add_argument("--cwd", default=None, help="working directory for the Herdr tab (launch only)")

    w = sub.add_parser("wait", help="block until a pane's agent is idle")
    w.add_argument("pane_id")
    w.add_argument("--timeout", type=int, default=1800000)

    c = sub.add_parser("close", help="close a completed, non-root chain-stage tab")
    c.add_argument("pane_id")

    args = parser.parse_args(argv)

    try:
        routing = load_routing()
        if args.check:
            problems = check(routing)
            for p in problems:
                print(f"FAIL {p}", file=sys.stderr)
            print("routing OK" if not problems else f"{len(problems)} problem(s)")
            return 1 if problems else 0
        if args.cmd == "plan" or args.cmd is None:
            print(render_plan(routing))
            return 0
        if args.cmd == "cmd":
            cfg = resolve_stage(routing, args.stage)
            print(build_command(cfg, prompt_file=args.prompt_file, base=args.base))
            return 0
        if args.cmd == "launch":
            print(
                json.dumps(
                    launch(args.stage, scope=args.scope, prompt_file=args.prompt_file, base=args.base, cwd=args.cwd)
                )
            )
            return 0
        if args.cmd == "wait":
            result = wait_for(args.pane_id, args.timeout)
            print(json.dumps(result))
            return 0 if result["ok"] else 1
        if args.cmd == "close":
            print(json.dumps(close_stage(args.pane_id)))
            return 0
    except RoutingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
