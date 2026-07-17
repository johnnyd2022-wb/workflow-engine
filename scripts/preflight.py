#!/usr/bin/env python3
"""Deterministic environment preflight for agent workflows.

Answers, in one cheap pass, the questions every agent skill would otherwise re-derive
with tool calls and tokens: which ENVIRONMENT am I in, is the test DB up, is the app
server running, is the OTel collector listening, am I in Herdr, which scanners exist.

Design rules:
- stdlib only, no app imports. Importing the app loads config, opens KeePassXC, and
  starts the OTel exporter — all slow, some noisy. Preflight must never do that.
- every network probe is short-timeout and runs in parallel; the whole script is
  budgeted at ~2s wall clock.
- machine-readable first (`--json`). Agents parse capabilities; humans read the summary.
- it reports, it does not fix. Repair is the calling skill's decision.

Usage:
    python scripts/preflight.py                 # human summary
    python scripts/preflight.py --json          # full JSON
    python scripts/preflight.py --check app_server --quiet   # exit 0/1 only
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "app" / "config"

# app/utils/config_loader.py:16 — os.getenv("ENVIRONMENT", "local"). Unset means local,
# which is why an unset ENVIRONMENT silently picks up local.ini's otel_enabled = true
# and floods test output with exporter errors when no collector is listening.
DEFAULT_ENVIRONMENT = "local"

NET_TIMEOUT = 1.0
CMD_TIMEOUT = 8.0

OK = "ok"
DOWN = "down"
MISSING = "missing"
UNKNOWN = "unknown"


@dataclass
class Check:
    """One preflight result. `ok` drives capability flags; `detail` is for humans."""

    name: str
    status: str
    detail: str = ""
    critical: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == OK


def tcp_open(host: str, port: int, timeout: float = NET_TIMEOUT) -> bool:
    """True if something accepts a TCP connection. Cheapest liveness signal there is."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def http_probe(url: str, timeout: float = NET_TIMEOUT) -> tuple[bool, str]:
    """GET a URL, tolerating self-signed certs (local dev uses them).

    Any HTTP response — including 401/404/500 — proves a server is listening, which is
    the only thing this probe claims.
    """
    # urllib honours file:// and friends, so constrain the scheme before opening
    # anything: this URL is built from config values, and a config that can make a
    # probe read the filesystem is a config that can lie about the environment.
    if not url.startswith(("http://", "https://")):
        return False, f"refusing non-http(s) URL: {url[:40]}"

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        # The rule's concern is urllib honouring file:// on a dynamic URL; the scheme is
        # pinned to http(s) directly above, which the rule's pattern match cannot see.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:  # noqa: S310
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return True, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, str(getattr(exc, "reason", exc))


def run_cmd(args: list[str], timeout: float = CMD_TIMEOUT) -> tuple[int, str, str]:
    """Run a command, returning (exit_code, stdout, stderr) with the streams kept apart.

    Keeping them apart matters: alembic logs INFO lines to stderr and prints the revision
    to stdout, so a merged stream makes the last line a log message, not the answer.
    """
    try:
        proc = subprocess.run(  # noqa: S603
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=REPO_ROOT,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", "not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"


def revisions(stdout: str) -> set[str]:
    """Revision ids from `alembic current` / `alembic heads` stdout.

    Each line looks like `crm_revenue_baseline_target_001 (head)`; take the first token
    and ignore anything that leaked in from a logger.
    """
    found = set()
    for line in stdout.splitlines():
        token = line.strip().split()[0] if line.strip() else ""
        if token and not token.startswith(("INFO", "WARNING", "ERROR", "DEBUG")):
            found.add(token)
    return found


def parse_host_port(endpoint: str, default_port: int) -> tuple[str, int]:
    """Pull host/port out of an ini endpoint like http://localhost:4317."""
    cleaned = endpoint.split("://", 1)[-1].split("/", 1)[0]
    if ":" in cleaned:
        host, _, raw_port = cleaned.rpartition(":")
        try:
            return host or "localhost", int(raw_port)
        except ValueError:
            return cleaned, default_port
    return cleaned or "localhost", default_port


# --------------------------------------------------------------------------------------
# environment resolution
# --------------------------------------------------------------------------------------


def resolve_environment() -> tuple[Check, configparser.ConfigParser]:
    """Resolve ENVIRONMENT the same way the app does, and load that ini.

    An unset ENVIRONMENT is not an error — it means local. But it is worth stating
    loudly, because 'unset' also means: not test, not production, and the local defaults
    (otel on, debug on, KeePassXC secrets) are what's in play.
    """
    raw = os.getenv("ENVIRONMENT")
    was_set = raw is not None and raw.strip() != ""
    name = (raw or DEFAULT_ENVIRONMENT).strip().lower()

    parser = configparser.ConfigParser()
    config_file = CONFIG_DIR / f"{name}.ini"
    if config_file.exists():
        parser.read(config_file)
        status, detail = OK, f"{name} ({config_file.name})"
    else:
        status, detail = MISSING, f"{name}: no {config_file.name} in app/config/"

    if not was_set:
        detail += " — ENVIRONMENT unset, assuming local (not test, not production)"

    return (
        Check(
            name="environment",
            status=status,
            detail=detail,
            critical=True,
            data={
                "name": name,
                "was_set": was_set,
                "assumed": not was_set,
                "is_production": name == "production",
                "config_file": str(config_file.relative_to(REPO_ROOT)) if config_file.exists() else None,
            },
        ),
        parser,
    )


# --------------------------------------------------------------------------------------
# individual checks
# --------------------------------------------------------------------------------------


def check_venv() -> Check:
    venv = REPO_ROOT / ".venv"
    if not venv.exists():
        return Check("venv", MISSING, "no .venv — run: uv sync --extra dev", critical=True)
    py = venv / "bin" / "python"
    if not py.exists():
        return Check("venv", MISSING, ".venv exists but has no bin/python", critical=True)
    code, out, err = run_cmd([str(py), "--version"], timeout=5)
    return Check("venv", OK if code == 0 else DOWN, out or err or "unusable", critical=True)


def check_deps() -> Check:
    """Import the packages the suite actually needs.

    factory_boy lives in the dev extra and is imported by tests/conftest.py at collection
    time, so a venv without it fails every test with a conftest ImportError that looks
    nothing like 'missing dependency'.
    """
    py = REPO_ROOT / ".venv" / "bin" / "python"
    if not py.exists():
        return Check("deps", UNKNOWN, "no venv to check", critical=True)
    required = ["factory", "pytest", "pyotp", "flask", "sqlalchemy", "structlog", "requests"]
    probe = "import importlib.util,sys; print(','.join(m for m in sys.argv[1:] if importlib.util.find_spec(m) is None))"
    code, out, err = run_cmd([str(py), "-c", probe, *required], timeout=15)
    if code != 0:
        return Check("deps", UNKNOWN, f"probe failed: {err[:120]}", critical=True)
    missing = [m for m in out.strip().split(",") if m]
    if missing:
        return Check(
            "deps",
            MISSING,
            f"missing: {', '.join(missing)} — run: uv sync --extra dev",
            critical=True,
            data={"missing": missing},
        )
    return Check("deps", OK, f"{len(required)} core packages importable", critical=True)


def check_test_db(cfg: configparser.ConfigParser) -> Check:
    """Can we reach the database the ACTIVE config points at?

    The trap worth naming: test.ini uses `host = host.docker.internal` because the test
    app runs inside Docker. Run pytest from the host with ENVIRONMENT=test and psycopg2
    blocks on that name until it gives up — the suite looks hung, not misconfigured.
    Unset ENVIRONMENT resolves to local.ini, which points at localhost:8401 — the same
    test database, reachable from here.
    """
    host = cfg.get("database", "host", fallback="localhost")
    port = cfg.getint("database", "port", fallback=5432)
    name = cfg.get("database", "name", fallback="?")
    up = tcp_open(host, port)
    if up:
        return Check(
            "test_db",
            OK,
            f"{host}:{port}/{name}",
            critical=True,
            data={"host": host, "port": port, "name": name, "docker_hostname_trap": False},
        )

    docker_hostname = host in {"host.docker.internal", "postgres", "db"}
    if docker_hostname and tcp_open("localhost", port):
        advice = (
            f"{host}:{port} unreachable from this shell, but localhost:{port} is up — "
            f"'{host}' only resolves inside Docker. Run pytest with ENVIRONMENT unset (local.ini "
            "targets the same DB on localhost); ENVIRONMENT=test from the host will hang."
        )
    else:
        advice = f"{host}:{port}/{name} down — start: docker-compose -f docker-compose.test.yml up -d"

    return Check(
        "test_db",
        DOWN,
        advice,
        critical=True,
        data={"host": host, "port": port, "name": name, "docker_hostname_trap": docker_hostname},
    )


def check_app_server(cfg: configparser.ConfigParser) -> Check:
    """Is the dev app server up? This is the flag that gates the live-server test suites.

    tests/test_login_2fa_flow.py and tests/test_2fa_totp_optimized.py drive
    https://localhost:8005 with `requests` — 30 tests that fail with
    ConnectionRefusedError, not an assertion, when nothing is listening.
    """
    port = cfg.getint("app", "port", fallback=8005)
    host = "localhost"
    url = f"https://{host}:{port}/"
    if not tcp_open(host, port):
        return Check(
            "app_server",
            DOWN,
            f"{url} not listening — start: uv run workflow start (or python app/app.py)",
            data={"url": url, "port": port},
        )
    reachable, detail = http_probe(url)
    return Check(
        "app_server",
        OK if reachable else DOWN,
        f"{url} — {detail}",
        data={"url": url, "port": port},
    )


def check_otel(cfg: configparser.ConfigParser) -> Check:
    """Will this run emit OTel spans, and is anything there to receive them?

    The exporter is gated on BOTH flags — app/observability/tracing.py:21-24 and
    metrics.py:25-27 return early unless `otel_enabled and grafana_data_enabled`. So
    `otel_enabled = true` alone (local.ini's default) exports nothing and is not a
    problem. Note that OTEL_SDK_DISABLED=1 does NOT silence this stack: tracing.py
    constructs the TracerProvider by hand, and that env var only reaches the SDK's own
    auto-instrumentation entry points.
    """
    otel_enabled = cfg.getboolean("observability", "otel_enabled", fallback=False)
    grafana_enabled = cfg.getboolean("observability", "grafana_data_enabled", fallback=False)
    endpoint = cfg.get("observability", "otel_exporter_endpoint", fallback="http://localhost:4317")
    host, port = parse_host_port(endpoint, 4317)
    up = tcp_open(host, port)
    exporter_active = otel_enabled and grafana_enabled
    data = {
        "otel_enabled": otel_enabled,
        "grafana_data_enabled": grafana_enabled,
        "exporter_active": exporter_active,
        "endpoint": endpoint,
        "collector_up": up,
    }

    if not exporter_active:
        why = "grafana_data_enabled = false" if otel_enabled else "otel_enabled = false"
        return Check(
            "otel_collector",
            OK,
            f"no exporter ({why}) — collector {'up' if up else 'down'}, nothing will be sent either way",
            data=data,
        )
    if up:
        return Check("otel_collector", OK, f"exporter active, collector listening at {endpoint}", data=data)
    return Check(
        "otel_collector",
        DOWN,
        (
            f"exporter active (otel_enabled + grafana_data_enabled) but nothing at {endpoint} — "
            "expect export errors in output. Start: uv run workflow observability start"
        ),
        data=data,
    )


def check_docker() -> Check:
    if not shutil.which("docker"):
        return Check("docker", MISSING, "docker not on PATH")
    code, out, _ = run_cmd(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=10)
    if code != 0:
        return Check("docker", DOWN, "daemon not reachable")
    return Check("docker", OK, f"daemon {out.splitlines()[0] if out else 'up'}")


def check_observability_stack() -> Check:
    if not shutil.which("docker"):
        return Check("observability_stack", UNKNOWN, "docker not on PATH")
    code, out, _ = run_cmd(["docker", "ps", "--format", "{{.Names}}"], timeout=10)
    if code != 0:
        return Check("observability_stack", UNKNOWN, "cannot list containers")
    names = [n for n in out.splitlines() if n.strip()]
    interesting = [
        n
        for n in names
        if any(k in n.lower() for k in ("grafana", "alloy", "posthog", "lgtm", "loki", "tempo", "mimir"))
    ]
    if not interesting:
        return Check(
            "observability_stack",
            DOWN,
            "not running — start: uv run workflow observability start",
            data={"containers": []},
        )
    return Check("observability_stack", OK, f"{len(interesting)} containers up", data={"containers": interesting})


def check_git() -> Check:
    code, branch, _ = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=5)
    if code != 0:
        return Check("git", MISSING, "not a git repo", critical=True)
    _, porcelain, _ = run_cmd(["git", "status", "--porcelain"], timeout=10)
    dirty = bool(porcelain.strip())
    on_main = branch.strip() in {"main", "master"}
    detail = f"{branch.strip()}" + (" (dirty)" if dirty else " (clean)")
    if on_main:
        detail += " — on main; branch before committing"
    return Check(
        "git",
        OK,
        detail,
        data={"branch": branch.strip(), "dirty": dirty, "on_main": on_main},
    )


def check_glab() -> Check:
    if not shutil.which("glab"):
        return Check("glab", MISSING, "glab not on PATH — MRs cannot be opened")
    code, out, err = run_cmd(["glab", "auth", "status"], timeout=15)
    authed = code == 0
    return Check(
        "glab", OK if authed else DOWN, "authenticated" if authed else f"not authenticated: {(err or out)[:100]}"
    )


def check_herdr() -> Check:
    """Herdr presence decides whether verification runs adversarially (Codex-as-Breaker)
    or through subagents. Both are valid; the skills just need to know which.
    """
    in_herdr = os.getenv("HERDR_ENV") == "1"
    if not in_herdr:
        return Check("herdr", OK, "not in Herdr — subagent verification", data={"in_herdr": False, "partner": None})
    pane = os.getenv("HERDR_PANE_ID", "?")
    workspace = os.getenv("HERDR_WORKSPACE_ID", "")
    partner = None
    if shutil.which("herdr") and workspace:
        code, out, _ = run_cmd(["herdr", "pane", "list", "--workspace", workspace], timeout=10)
        if code == 0:
            try:
                payload = json.loads(out)
                panes = payload.get("result", payload).get("panes", []) if isinstance(payload, dict) else []
                for p in panes:
                    agent = (p.get("agent") or "").lower()
                    if agent and agent != "claude" and p.get("pane_id") != pane:
                        partner = {"pane_id": p.get("pane_id"), "agent": agent, "status": p.get("agent_status")}
                        break
            except (json.JSONDecodeError, AttributeError):
                partner = None
    detail = f"pane {pane}"
    detail += f", partner {partner['agent']} ({partner['status']})" if partner else ", no partner pane detected"
    return Check("herdr", OK, detail, data={"in_herdr": True, "pane_id": pane, "partner": partner})


def check_tools() -> Check:
    """Scanners and runners the verification chain shells out to."""
    wanted = {
        "semgrep": "security-audit scanner pass",
        "gitleaks": "secret scanning",
        "uv": "dependency + command runner",
        "alembic": "migrations (via uv run)",
        "playwright": "e2e-playwright",
    }
    present, absent = {}, {}
    for tool, why in wanted.items():
        path = shutil.which(tool)
        if path:
            present[tool] = path
        else:
            # uv-managed tools are runnable via `uv run <tool>` without being on PATH
            code = run_cmd(["uv", "run", "--no-sync", tool, "--version"], timeout=10)[0] if shutil.which("uv") else 1
            (present if code == 0 else absent)[tool] = f"uv run {tool}" if code == 0 else why
    status = OK if not absent else MISSING
    detail = f"{len(present)}/{len(wanted)} available" + (f" — missing: {', '.join(absent)}" if absent else "")
    return Check("tools", status, detail, data={"present": sorted(present), "absent": sorted(absent)})


def check_keepass(env_name: str) -> Check:
    """Local secrets come from KeePassXC (config_loader.py:42). Only local uses it."""
    if env_name != "local":
        return Check("keepass", OK, f"not used in {env_name}", data={"needed": False})
    if not shutil.which("keepassxc-cli"):
        return Check(
            "keepass",
            MISSING,
            "keepassxc-cli not on PATH — local secrets fall back to ini values",
            data={"needed": True},
        )
    return Check("keepass", OK, "keepassxc-cli present (unlock state not probed)", data={"needed": True})


def check_migrations(db_up: bool) -> Check:
    """Are there unapplied migrations? Only answerable with a live DB."""
    if not db_up:
        return Check("migrations", UNKNOWN, "test DB down — cannot compare heads")
    code, out, err = run_cmd(["uv", "run", "alembic", "current"], timeout=45)
    if code != 0:
        return Check(
            "migrations",
            UNKNOWN,
            f"alembic current failed: {(err or out).splitlines()[-1][:100] if (err or out) else 'no output'}",
        )
    current = revisions(out)
    head_code, head_out, _ = run_cmd(["uv", "run", "alembic", "heads"], timeout=45)
    heads = revisions(head_out) if head_code == 0 else set()

    if not current:
        return Check(
            "migrations", DOWN, "no revision applied — run: uv run alembic upgrade head", data={"at_head": False}
        )
    at_head = bool(heads) and heads.issubset(current)
    pending = sorted(heads - current)
    return Check(
        "migrations",
        OK if at_head else DOWN,
        (
            f"at head ({', '.join(sorted(current))})"
            if at_head
            else f"pending: {', '.join(pending) or 'unknown'} — run: uv run alembic upgrade head"
        ),
        data={"current": sorted(current), "heads": sorted(heads), "at_head": at_head},
    )


# --------------------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------------------


def run_all(skip_slow: bool = False) -> dict[str, Any]:
    env_check, cfg = resolve_environment()
    env_name = env_check.data["name"]

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            "venv": pool.submit(check_venv),
            "deps": pool.submit(check_deps),
            "test_db": pool.submit(check_test_db, cfg),
            "app_server": pool.submit(check_app_server, cfg),
            "otel_collector": pool.submit(check_otel, cfg),
            "docker": pool.submit(check_docker),
            "observability_stack": pool.submit(check_observability_stack),
            "git": pool.submit(check_git),
            "glab": pool.submit(check_glab),
            "herdr": pool.submit(check_herdr),
            "tools": pool.submit(check_tools),
            "keepass": pool.submit(check_keepass, env_name),
        }
        results: dict[str, Check] = {name: fut.result() for name, fut in futures.items()}

    results["environment"] = env_check
    if not skip_slow:
        results["migrations"] = check_migrations(results["test_db"].ok)

    capabilities = {
        "app_server": results["app_server"].ok,
        "test_db": results["test_db"].ok,
        "otel_collector": bool(results["otel_collector"].data.get("collector_up")),
        "observability_stack": results["observability_stack"].ok,
        "docker": results["docker"].ok,
        "glab": results["glab"].ok,
        "in_herdr": bool(results["herdr"].data.get("in_herdr")),
        "herdr_partner": bool(results["herdr"].data.get("partner")),
        "deps": results["deps"].ok,
    }

    # The decisions callers actually want, made once here instead of re-derived per skill.
    decisions = {
        "live_server_tests": "run" if capabilities["app_server"] else "skip",
        "live_server_reason": (
            f"app server up at {results['app_server'].data.get('url')}"
            if capabilities["app_server"]
            else "no app server listening; suites driving it would fail on connection, not assertions"
        ),
        "verification_mode": (
            "herdr-adversarial" if capabilities["in_herdr"] and capabilities["herdr_partner"] else "subagents"
        ),
        "otel_exporter_active": bool(results["otel_collector"].data.get("exporter_active")),
        "can_open_mr": capabilities["glab"],
        "db_writes_allowed": env_name != "production",
    }

    blockers = [c.name for c in results.values() if c.critical and not c.ok]
    advice = [c.detail for c in results.values() if not c.ok and c.detail]

    return {
        "ok": not blockers,
        "environment": env_check.data,
        "capabilities": capabilities,
        "decisions": decisions,
        "blockers": blockers,
        "advice": advice,
        "checks": {name: asdict(c) for name, c in sorted(results.items())},
    }


ICONS = {OK: "✓", DOWN: "✗", MISSING: "✗", UNKNOWN: "?"}


def render(report: dict[str, Any]) -> str:
    lines = []
    env = report["environment"]
    banner = f"ENVIRONMENT={env['name']}" + (" (assumed — var unset)" if env["assumed"] else "")
    lines.append(f"preflight: {banner}")
    lines.append("")
    for name, check in report["checks"].items():
        if name == "environment":
            continue
        lines.append(f"  {ICONS.get(check['status'], '?')} {name:<20} {check['detail']}")
    lines.append("")
    dec = report["decisions"]
    lines.append(f"  live-server tests : {dec['live_server_tests']} ({dec['live_server_reason']})")
    lines.append(f"  verification mode : {dec['verification_mode']}")
    lines.append(f"  otel exporter     : {'active' if dec['otel_exporter_active'] else 'inactive (nothing exported)'}")
    lines.append("")
    lines.append("  BLOCKED: " + ", ".join(report["blockers"]) if report["blockers"] else "  ready")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic environment preflight for agent workflows.")
    ap.add_argument("--json", action="store_true", help="emit the full JSON report")
    ap.add_argument("--check", metavar="NAME", help="run everything but exit on one capability's state")
    ap.add_argument("--quiet", action="store_true", help="no output, exit code only")
    ap.add_argument("--skip-slow", action="store_true", help="skip migration head comparison")
    args = ap.parse_args()

    report = run_all(skip_slow=args.skip_slow)

    if args.check:
        caps = report["capabilities"]
        if args.check not in caps:
            print(f"unknown capability: {args.check}. known: {', '.join(sorted(caps))}", file=sys.stderr)
            return 2
        value = caps[args.check]
        if not args.quiet:
            print(f"{args.check}: {'yes' if value else 'no'}")
        return 0 if value else 1

    if args.quiet:
        return 0 if report["ok"] else 1

    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
