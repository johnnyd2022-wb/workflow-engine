#!/usr/bin/env python3
"""Reduce a window of Claude Code transcripts to a small, reviewable digest.

Why this exists: the sessions themselves are the only honest record of how this system
actually behaves — which skills fire, which commands get retried three times, where a run
burned 200k tokens re-reading the same file, where the user had to interrupt and correct.
That record is ~127MB of JSONL. Handing it to a model is both impossible (context) and
exactly the waste the sweep is supposed to find.

So the model never reads a transcript. This script streams them, applies a fixed set of
deterministic detectors, and writes a digest measured in kilobytes. The model reasons over
the digest and pulls individual evidence excerpts on demand with `show`.

Two properties this file is responsible for, because nothing downstream can recover them:

  **Determinism.** Every signal here is computed by code with a test, not by a model's
  impression of a transcript. A finding the sweep raises can therefore be re-derived
  exactly, which is what makes the reviewer's spot-check cheap: same input, same digest.

  **Redaction.** Transcripts contain whatever the user pasted and whatever a command
  printed — tokens, connection strings, keys. Everything that lands in the digest goes
  through `redact()` first. See REDACTIONS.

Usage:
    python3 scripts/session_sweep.py digest                 # last 7 days -> report dir
    python3 scripts/session_sweep.py digest --days 14 --json # digest.json on stdout
    python3 scripts/session_sweep.py show --session ID --uuid UUID   # one excerpt
    python3 scripts/session_sweep.py --check                # self-test the detectors

Stdlib only, no app imports: this runs on a timer, before and independently of the app.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
DEFAULT_TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_REPORT_DIR = REPO_ROOT / ".agents" / "reports" / "session-sweep"

SCHEMA_VERSION = 1

# How many items of each signal survive into the digest, and how long any single quoted
# string may be. These bound the digest's size, which is the whole point of the file: a
# digest that grows with the transcripts would reintroduce the problem it exists to solve.
TOP_N = 12
MAX_EVIDENCE = 3
MAX_SNIPPET = 240

# Relative token *weights*, not prices: Anthropic bills a cache read at 0.1x and a cache
# write at 1.25x a normal input token. Used only to rank sessions by burn so the ranking
# isn't dominated by cheap cache reads. Deliberately not called "cost" — this file has no
# business asserting dollar figures.
CACHE_READ_WEIGHT = 0.1
CACHE_WRITE_WEIGHT = 1.25


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

# Ordered: the first pattern that matches a span wins. Each is deliberately shaped to the
# credential formats this repo actually touches (see docs/supply-chain-security.md and
# scripts/local_secrets.py) plus the generic high-entropy vendor prefixes.
REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # postgres://user:password@host — the password is the only part worth hiding, but the
    # whole credential pair goes, since the username is half of one.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*)://[^\s:/@]+:[^\s@]+@"), r"\1://[REDACTED]@"),
    # Vendor-prefixed keys: sk-ant-..., glpat-..., xoxb-..., ghp_..., AKIA...
    (re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{16,}"), "[REDACTED-KEY]"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{10,}"), "[REDACTED-KEY]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[REDACTED-KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED-KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}"), "[REDACTED-KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"), "[REDACTED-JWT]"),
    # Anything that names itself a secret and then assigns one. Covers env assignments,
    # ini keys, and CLI flags in one shape: NAME<sep>VALUE.
    (
        re.compile(
            # The name prefix is OPTIONAL: a bare `password = '...'` is the commonest
            # shape of all and an earlier version, which required at least one leading
            # character, matched every prefixed variant and missed exactly that one.
            r"(?i)\b([a-z0-9_]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key))"
            r"(\s*[:=]\s*|\s+)"
            r"(\"[^\"]*\"|'[^']*'|[^\s,;)]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    # -----BEGIN ... PRIVATE KEY-----
    (re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*-----", re.S), "[REDACTED-PEM]"),
)


def redact(text: str) -> str:
    """Strip credential-shaped substrings. Applied to every string entering the digest.

    This is a best-effort filter, not a proof — it cannot recognise a secret that looks
    like ordinary prose. It is the reason the digest is safe to commit to an MR while the
    transcripts it derives from are not, so it runs on *everything*, including strings
    that "obviously" hold no secret. Cheap, and the failure mode of skipping it is
    permanent (a key in git history).
    """
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def snippet(text: str, limit: int = MAX_SNIPPET) -> str:
    """Redact, collapse whitespace, and truncate — the standard shape for a quoted string."""
    flat = " ".join(redact(text).split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "…"


# ---------------------------------------------------------------------------
# House rules — repo-specific known-bad commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HouseRule:
    """A command shape this repo has already decided is wrong, with the reason.

    These are the highest-value detections in the file because they need no judgment: the
    correct behaviour is already written down somewhere (CLAUDE.md, a skill, a memory),
    and the transcript shows an agent doing the other thing anyway. That gap is either an
    agent that ignored its instructions or an instruction that isn't reaching the agent —
    and the second one is a fixable defect in the skills, which is what the sweep is for.

    Adding a row requires a test proving it fires on the bad shape and stays quiet on the
    good one. Same discipline as scripts/mr_conflict_plan.py's allow-list: a detector that
    was never proven to fire is a detector nobody should trust.
    """

    rule_id: str
    pattern: re.Pattern[str]
    why: str
    fix: str
    # Shapes that look like the pattern but are legitimate. Checked first.
    exempt: re.Pattern[str] | None = None

    def matches(self, command: str) -> bool:
        if self.exempt is not None and self.exempt.search(command):
            return False
        return bool(self.pattern.search(command))


HOUSE_RULES: tuple[HouseRule, ...] = (
    HouseRule(
        rule_id="environment-test-from-host",
        pattern=re.compile(r"\bENVIRONMENT\s*=\s*test\b.*\b(pytest|python|uv run)\b"),
        why=(
            "test.ini points at host.docker.internal, which only resolves inside the test "
            "container — running pytest this way from a host shell hangs instead of failing."
        ),
        fix="Run pytest with ENVIRONMENT unset; it resolves to local, which targets localhost:8401.",
    ),
    HouseRule(
        rule_id="workflow-upgrade-db",
        pattern=re.compile(r"\bworkflow\s+upgrade-db\b"),
        why="Migrations are driven through alembic directly; the CLI wrapper is not the supported path.",
        fix="Use `uv run alembic upgrade head`.",
    ),
    HouseRule(
        rule_id="shell-read-instead-of-read-tool",
        pattern=re.compile(r"(?:^|[|;&]\s*)(?:cat|head|tail)\s+(?!-)[^|;&]*\.(?:py|md|json|ini|toml|ya?ml|js|html)\b"),
        why=(
            "Reading a file through the shell bypasses the Read tool's line numbers and "
            "range support, so the whole file lands in context and cannot be cited by line."
        ),
        fix="Use the Read tool, with offset/limit when only part of the file is needed.",
        # A pipeline that *processes* a file (greps it, counts it, feeds a script) is a
        # legitimate shell job, not a substitute for Read. So is a heredoc write.
        exempt=re.compile(r"\|\s*(?:grep|rg|jq|wc|sed|awk|python|sort|uniq|head|tail)\b|<<'?EOF|>>?\s"),
    ),
    HouseRule(
        rule_id="git-force-push",
        pattern=re.compile(r"\bgit\s+push\b.*(?:--force\b|--force-with-lease\b|(?<![\w-])-f(?![\w-]))"),
        why=".agents/autonomy.md bars force-push without explicit human approval.",
        fix="Push a normal follow-up commit; if history genuinely must be rewritten, escalate.",
    ),
    HouseRule(
        rule_id="production-environment",
        pattern=re.compile(r"\bENVIRONMENT\s*=\s*production\b"),
        why=".agents/autonomy.md bars production access outright — no reads, no migrations.",
        fix="Stop and report. There is no authorised path to production from a skill run.",
    ),
    HouseRule(
        rule_id="system-python3",
        pattern=re.compile(r"(?<![\w/])/usr/bin/python3\b"),
        why="/usr/bin/python3 is 3.10 on this box on purpose; pyproject requires >=3.14.",
        fix="Use `python3` (the uv shim) or an explicit ~/.local/bin/python3.",
    ),
    HouseRule(
        rule_id="pytest-no-such-path",
        pattern=re.compile(r"\bpytest\b[^|;&]*\s-k\s+\S+\s+-k\s+"),
        why="Two -k selectors in one pytest invocation silently keeps only the last one.",
        fix="Combine the selectors into one expression with `or`/`and`.",
    ),
)


# ---------------------------------------------------------------------------
# Record streaming
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """One tool_use and whatever came back for it."""

    uuid: str
    tool: str
    session: str
    ts: str
    command: str = ""  # Bash command / file path / skill name — the identifying input
    is_error: bool = False
    error_text: str = ""
    result_chars: int = 0


@dataclass
class SessionStats:
    session_id: str
    path: Path
    project: str = ""
    branch: str = ""
    title: str = ""
    first_ts: str = ""
    last_ts: str = ""
    turns: int = 0
    models: Counter = field(default_factory=Counter)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    tools: Counter = field(default_factory=Counter)
    errors: int = 0
    interruptions: int = 0
    skills: Counter = field(default_factory=Counter)
    agents: Counter = field(default_factory=Counter)
    user_prompts: int = 0

    @property
    def weighted_input(self) -> int:
        return int(self.input_tokens + self.cache_write * CACHE_WRITE_WEIGHT + self.cache_read * CACHE_READ_WEIGHT)

    @property
    def cache_churn_pct(self) -> float:
        """Share of cached input that had to be *written* rather than read back.

        Deliberately not "cache hit rate": measured across a real week, hit rate read
        100.0% for every session (uncached input is only ever the turn's delta), so it
        distinguishes nothing. Churn does — it rises when the prefix keeps being
        invalidated, which is what a long session re-reading files, or a skill that
        rewrites its own context, actually looks like in the token numbers.
        """
        total = self.cache_read + self.cache_write
        return round(100.0 * self.cache_write / total, 1) if total else 0.0


def iter_transcripts(root: Path, since: datetime) -> Iterator[Path]:
    """Transcript files whose mtime is inside the window.

    mtime is a pre-filter only — a file touched yesterday can still hold records from a
    month ago, so every record is checked against the window individually below. The
    pre-filter is what keeps a weekly run off the other ~110MB.
    """
    if not root.exists():
        return
    cutoff = since.timestamp()
    for path in sorted(root.rglob("*.jsonl")):
        try:
            if path.stat().st_mtime >= cutoff:
                yield path
        except OSError:
            continue


def parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed records, skipping unparseable lines.

    A truncated final line is normal — a session being written to right now has one. It is
    not worth failing a weekly sweep over, so malformed lines are counted, not raised.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def _tool_identity(name: str, tool_input: Any) -> str:
    """The string that identifies a tool call for repetition/violation detection.

    Not the whole input: two Reads of the same file with different offsets are the same
    call for "am I re-reading this" purposes, and a Bash command's identity is its command
    line, not its description.
    """
    if not isinstance(tool_input, dict):
        return ""
    for key in ("command", "file_path", "path", "pattern", "skill", "subagent_type", "url"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _result_text(content: Any) -> str:
    """Flatten a tool_result's content to text; it may be a string or a content-block list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


COMMAND_NAME_RE = re.compile(r"<command-name>/?([a-z0-9][a-z0-9:_-]*)</command-name>")
INTERRUPT_RE = re.compile(r"\[Request interrupted by user")
# Deliberately narrow. "no" and "wrong" alone fire on ordinary prose ("no need to", "the
# wrong branch was fixed"); these shapes are near-always the user redirecting the agent.
CORRECTION_RE = re.compile(
    r"(?i)(?:^|[.!?]\s+)(?:no[,.]|nope\b|stop\b|don't\b|do not\b|that's wrong\b|that is wrong\b|"
    r"wrong\b|actually,|i said\b|why did you\b|you were supposed to\b|revert\b|undo\b)"
)

# A headless skill dispatch arrives on the transcript as an ordinary user prompt — same
# `userType: external`, same `isSidechain: false` — so there is no flag that separates
# "the human typed this" from "another skill injected this". Verified against a real week:
# every in-window prompt carried that identical pair. Two content-shaped filters stand in:
DISPATCH_MARKERS = re.compile(
    r"(?:Read and follow the skill at:|Base directory for this skill:|"
    r"<command-name>|<local-command-|You are (?:being )?invoked (?:by|as)\b)"
)
# ...and a length ceiling. A real correction is terse ("no, use alembic"); a dispatch is a
# multi-paragraph brief that routinely contains prohibitions ("do not edit files") which
# read exactly like corrections to the regex above. Without this the signal was ~85% noise.
MAX_CORRECTION_CHARS = 600


def is_human_correction(text: str) -> bool:
    """Whether a prompt is the user redirecting the agent, rather than a skill dispatch."""
    if len(text) > MAX_CORRECTION_CHARS or DISPATCH_MARKERS.search(text):
        return False
    return bool(CORRECTION_RE.search(text))


def collect(
    paths: list[Path], since: datetime, until: datetime
) -> tuple[dict[str, SessionStats], list[ToolCall], list[dict[str, Any]]]:
    """Single pass over every in-window record.

    Returns per-session stats, the flattened tool-call log, and the user prompts (kept
    separately because correction/interrupt detection reads them as text).
    """
    sessions: dict[str, SessionStats] = {}
    calls: list[ToolCall] = []
    prompts: list[dict[str, Any]] = []

    for path in paths:
        pending: dict[str, ToolCall] = {}
        for record in iter_records(path):
            ts = parse_ts(record.get("timestamp"))
            rec_type = record.get("type")

            session_id = record.get("sessionId") or record.get("session_id") or path.stem
            if rec_type == "ai-title":
                stats = sessions.get(session_id)
                if stats is not None and isinstance(record.get("aiTitle"), str):
                    stats.title = snippet(record["aiTitle"], 100)
                continue
            if rec_type not in {"user", "assistant"}:
                continue
            if ts is None or ts < since or ts > until:
                continue

            stats = sessions.get(session_id)
            if stats is None:
                stats = SessionStats(session_id=session_id, path=path)
                sessions[session_id] = stats
            if not stats.first_ts:
                stats.first_ts = record["timestamp"]
            stats.last_ts = record["timestamp"]
            if not stats.project and isinstance(record.get("cwd"), str):
                stats.project = record["cwd"]
            if isinstance(record.get("gitBranch"), str) and record["gitBranch"]:
                stats.branch = record["gitBranch"]

            message = record.get("message") or {}
            content = message.get("content")

            if rec_type == "assistant":
                stats.turns += 1
                model = message.get("model")
                if isinstance(model, str) and model and model != "<synthetic>":
                    stats.models[model] += 1
                usage = message.get("usage") or {}
                stats.input_tokens += int(usage.get("input_tokens") or 0)
                stats.output_tokens += int(usage.get("output_tokens") or 0)
                stats.cache_read += int(usage.get("cache_read_input_tokens") or 0)
                stats.cache_write += int(usage.get("cache_creation_input_tokens") or 0)

                for block in content if isinstance(content, list) else []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = block.get("name") or "?"
                    stats.tools[name] += 1
                    identity = _tool_identity(name, block.get("input"))
                    if name == "Skill":
                        stats.skills[identity or "?"] += 1
                    elif name == "Agent":
                        stats.agents[identity or "?"] += 1
                    call = ToolCall(
                        uuid=str(record.get("uuid") or ""),
                        tool=name,
                        session=session_id,
                        ts=record.get("timestamp") or "",
                        command=identity,
                    )
                    block_id = block.get("id")
                    if isinstance(block_id, str):
                        pending[block_id] = call
                    calls.append(call)
                continue

            # rec_type == "user": either a tool_result carrier or a real prompt.
            saw_tool_result = False
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                saw_tool_result = True
                text = _result_text(block.get("content"))
                call = pending.pop(block.get("tool_use_id") or "", None)
                if call is None:
                    continue
                call.result_chars = len(text)
                if block.get("is_error"):
                    call.is_error = True
                    call.error_text = text
                    stats.errors += 1

            text_content = content if isinstance(content, str) else _result_text(content)
            if INTERRUPT_RE.search(text_content):
                stats.interruptions += 1
            if saw_tool_result or not text_content.strip():
                continue

            stats.user_prompts += 1
            for name in COMMAND_NAME_RE.findall(text_content):
                stats.skills[name] += 1
            prompts.append(
                {
                    "session": session_id,
                    "uuid": str(record.get("uuid") or ""),
                    "ts": record.get("timestamp") or "",
                    "text": text_content,
                }
            )

    return sessions, calls, prompts


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def _evidence(items: list[Any]) -> list[dict[str, str]]:
    """Evidence pointers, capped. Pointers, not excerpts — `show` fetches the excerpt.

    This is what makes the reviewer's job cheap: a finding cites (session, uuid) and the
    reviewer resolves exactly the ones it doubts, instead of the digest inlining full
    transcript text for findings nobody questions.
    """
    out = []
    for item in items[:MAX_EVIDENCE]:
        if isinstance(item, ToolCall):
            out.append({"session": item.session, "uuid": item.uuid, "ts": item.ts})
        elif isinstance(item, dict):
            out.append({"session": item.get("session", ""), "uuid": item.get("uuid", ""), "ts": item.get("ts", "")})
    return out


def normalise_error(text: str) -> str:
    """Collapse an error message to a signature that survives incidental variation.

    Line numbers, pids, temp paths, hex ids and timings differ between two instances of
    the same underlying failure. Without this every error is unique and the "this failed
    nine times this week" signal — the one worth acting on — never appears.
    """
    flat = " ".join(redact(text).split())[:400]
    flat = re.sub(r"\b[0-9a-f]{7,40}\b", "<hex>", flat)
    flat = re.sub(r"/tmp/[^\s'\"]+", "<tmp>", flat)
    flat = re.sub(r"\b\d+\b", "<n>", flat)
    return flat[:200]


def detect_house_rules(calls: list[ToolCall]) -> list[dict[str, Any]]:
    """Commands this repo has already ruled against. Highest-signal detector here."""
    hits: dict[str, list[ToolCall]] = defaultdict(list)
    for call in calls:
        if call.tool != "Bash" or not call.command:
            continue
        for rule in HOUSE_RULES:
            if rule.matches(call.command):
                hits[rule.rule_id].append(call)
    by_id = {rule.rule_id: rule for rule in HOUSE_RULES}
    out = []
    for rule_id, matched in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        rule = by_id[rule_id]
        out.append(
            {
                "rule_id": rule_id,
                "count": len(matched),
                "sessions": sorted({c.session for c in matched}),
                "why": rule.why,
                "fix": rule.fix,
                "example": snippet(matched[0].command),
                "evidence": _evidence(matched),
            }
        )
    return out


def detect_error_clusters(calls: list[ToolCall], min_count: int = 2) -> list[dict[str, Any]]:
    """Failures that recurred. One failure is life; the same failure five times is a defect."""
    groups: dict[str, list[ToolCall]] = defaultdict(list)
    for call in calls:
        if call.is_error and call.error_text:
            groups[normalise_error(call.error_text)].append(call)
    out = []
    for sig, matched in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(matched) < min_count:
            continue
        out.append(
            {
                "signature": sig,
                "count": len(matched),
                "tool": Counter(c.tool for c in matched).most_common(1)[0][0],
                "sessions": sorted({c.session for c in matched}),
                "example_command": snippet(matched[0].command),
                "evidence": _evidence(matched),
            }
        )
    return out[:TOP_N]


def detect_repeated_commands(calls: list[ToolCall], min_count: int = 3) -> list[dict[str, Any]]:
    """The same command run over and over inside one session.

    Re-running an identical command is usually one of two fixable things: the agent forgot
    it already had the answer, or a skill's instructions tell it to re-derive state it was
    already handed. Both are token waste with a written fix.
    """
    groups: dict[tuple[str, str, str], list[ToolCall]] = defaultdict(list)
    for call in calls:
        if call.command and call.tool in {"Bash", "Read", "Grep", "Glob"}:
            groups[(call.session, call.tool, call.command)].append(call)
    out = []
    for (session, tool, command), matched in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(matched) < min_count:
            continue
        out.append(
            {
                "session": session,
                "tool": tool,
                "command": snippet(command),
                "count": len(matched),
                "errors": sum(1 for c in matched if c.is_error),
                "evidence": _evidence(matched),
            }
        )
    return out[:TOP_N]


def detect_oversized_results(calls: list[ToolCall], threshold: int = 40_000) -> list[dict[str, Any]]:
    """Single tool results large enough to be worth a narrower command.

    A 200k-character Bash result is a whole context window's worth of tokens spent on
    output nobody asked to be complete. The fix is almost always in the skill that told
    the agent to run it that way.
    """
    big = [c for c in calls if c.result_chars >= threshold]
    big.sort(key=lambda c: -c.result_chars)
    return [
        {
            "session": call.session,
            "tool": call.tool,
            "command": snippet(call.command),
            "result_chars": call.result_chars,
            "evidence": _evidence([call]),
        }
        for call in big[:TOP_N]
    ]


def detect_interventions(prompts: list[dict[str, Any]], sessions: dict[str, SessionStats]) -> dict[str, Any]:
    """Where the human had to step in — interrupts and corrections.

    The strongest available proxy for "the agent did the wrong thing", because it is the
    user saying so at the time. Cheap to detect, and every hit points at a skill whose
    instructions let the wrong thing happen.
    """
    corrections = [p for p in prompts if is_human_correction(p["text"])]
    return {
        "interruptions": sum(s.interruptions for s in sessions.values()),
        "interrupted_sessions": sorted(s.session_id for s in sessions.values() if s.interruptions),
        "correction_count": len(corrections),
        "corrections": [
            {
                "session": p["session"],
                "text": snippet(p["text"], 200),
                "evidence": _evidence([p]),
            }
            for p in corrections[:TOP_N]
        ],
    }


def skill_roster(skills_dir: Path = SKILLS_DIR) -> list[str]:
    if not skills_dir.exists():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if (p / "SKILL.md").exists())


def detect_skill_usage(sessions: dict[str, SessionStats], skills_dir: Path = SKILLS_DIR) -> dict[str, Any]:
    """Which skills actually fired, and which never do.

    A skill nothing invokes is dead weight the router still has to describe — the runtime
    counterpart to scripts/skill_graph.py's static orphan check. skill_graph proves a skill
    is *reachable*; this proves whether it was ever *reached*.
    """
    used: Counter = Counter()
    for stats in sessions.values():
        used.update(stats.skills)
    roster = skill_roster(skills_dir)
    roster_set = set(roster)
    # `/model`, `/clear`, `/compact` and friends arrive through the same <command-name>
    # marker as a real skill invocation but are built-in CLI commands. Counting them as
    # skills inflates usage and, worse, makes the never-invoked list look shorter than it
    # is — the one number here that should drive a decision about deleting a skill.
    return {
        "invoked": [(name, count) for name, count in used.most_common(30) if name in roster_set],
        "builtin_commands": [(name, count) for name, count in used.most_common() if name not in roster_set],
        "roster_size": len(roster),
        "never_invoked": [name for name in roster if name not in used] if roster else [],
    }


def build_digest(
    *,
    days: int,
    transcript_root: Path = DEFAULT_TRANSCRIPT_ROOT,
    skills_dir: Path = SKILLS_DIR,
    now: datetime | None = None,
) -> dict[str, Any]:
    until = now or datetime.now(UTC)
    since = until - timedelta(days=days)
    paths = list(iter_transcripts(transcript_root, since))
    sessions, calls, prompts = collect(paths, since, until)

    tool_totals: Counter = Counter()
    for stats in sessions.values():
        tool_totals.update(stats.tools)

    ranked = sorted(sessions.values(), key=lambda s: -(s.weighted_input + s.output_tokens))
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": until.isoformat(),
        "window": {"days": days, "since": since.isoformat(), "until": until.isoformat()},
        "scanned": {"files": len(paths), "sessions": len(sessions), "tool_calls": len(calls)},
        "totals": {
            "turns": sum(s.turns for s in sessions.values()),
            "user_prompts": sum(s.user_prompts for s in sessions.values()),
            "input_tokens": sum(s.input_tokens for s in sessions.values()),
            "output_tokens": sum(s.output_tokens for s in sessions.values()),
            "cache_read_tokens": sum(s.cache_read for s in sessions.values()),
            "cache_write_tokens": sum(s.cache_write for s in sessions.values()),
            "weighted_input_tokens": sum(s.weighted_input for s in sessions.values()),
            "tool_errors": sum(s.errors for s in sessions.values()),
            "tools": tool_totals.most_common(20),
        },
        "sessions": [
            {
                "id": s.session_id,
                "title": s.title,
                "project": snippet(s.project, 120),
                "branch": snippet(s.branch, 80),
                "started": s.first_ts,
                "ended": s.last_ts,
                "turns": s.turns,
                "models": s.models.most_common(3),
                "output_tokens": s.output_tokens,
                "weighted_input_tokens": s.weighted_input,
                "cache_churn_pct": s.cache_churn_pct,
                "tool_errors": s.errors,
                "interruptions": s.interruptions,
                "top_tools": s.tools.most_common(5),
                "skills": s.skills.most_common(5),
            }
            for s in ranked[:TOP_N]
        ],
        "signals": {
            "house_rule_violations": detect_house_rules(calls),
            "error_clusters": detect_error_clusters(calls),
            "repeated_commands": detect_repeated_commands(calls),
            "oversized_results": detect_oversized_results(calls),
            "interventions": detect_interventions(prompts, sessions),
            "skill_usage": detect_skill_usage(sessions, skills_dir),
        },
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(digest: dict[str, Any]) -> str:
    """A human-readable view of the same numbers. The JSON is what the sweep reads."""
    window = digest["window"]
    totals = digest["totals"]
    signals = digest["signals"]
    lines = [
        "# Session sweep digest",
        "",
        f"Window: {window['since'][:10]} → {window['until'][:10]} ({window['days']}d) · "
        f"{digest['scanned']['sessions']} sessions, {digest['scanned']['tool_calls']} tool calls "
        f"across {digest['scanned']['files']} transcripts",
        "",
        "## Totals",
        "",
        f"- Turns: {totals['turns']:,} across {totals['user_prompts']:,} user prompts",
        f"- Output tokens: {totals['output_tokens']:,}",
        f"- Weighted input tokens: {totals['weighted_input_tokens']:,} "
        f"(cache read {totals['cache_read_tokens']:,}, cache write {totals['cache_write_tokens']:,})",
        f"- Tool errors: {totals['tool_errors']:,}",
        "",
    ]

    violations = signals["house_rule_violations"]
    lines += ["## House-rule violations", ""]
    if violations:
        for item in violations:
            lines.append(f"- **{item['rule_id']}** ×{item['count']} — {item['why']}")
            lines.append(f"  - fix: {item['fix']}")
            lines.append(f"  - e.g. `{item['example']}`")
    else:
        lines.append("_none_")
    lines.append("")

    lines += ["## Recurring failures", ""]
    if signals["error_clusters"]:
        for item in signals["error_clusters"]:
            lines.append(f"- ×{item['count']} ({item['tool']}) `{item['signature']}`")
    else:
        lines.append("_none_")
    lines.append("")

    lines += ["## Repeated identical commands", ""]
    if signals["repeated_commands"]:
        for item in signals["repeated_commands"]:
            lines.append(f"- ×{item['count']} {item['tool']} `{item['command']}` ({item['session'][:8]})")
    else:
        lines.append("_none_")
    lines.append("")

    interventions = signals["interventions"]
    lines += [
        "## Human interventions",
        "",
        f"- Interruptions: {interventions['interruptions']}",
        f"- Corrections: {interventions['correction_count']}",
        "",
    ]
    for item in interventions["corrections"][:5]:
        lines.append(f"  - `{item['text']}`")
    lines.append("")

    usage = signals["skill_usage"]
    lines += [
        "## Skill usage",
        "",
        f"- Invoked: {', '.join(f'{n}×{c}' for n, c in usage['invoked'][:15]) or '_none_'}",
        f"- Never invoked ({len(usage['never_invoked'])}/{usage['roster_size']}): "
        f"{', '.join(usage['never_invoked']) or '_none_'}",
        "",
        "## Heaviest sessions",
        "",
        "| session | title | turns | out | weighted in | churn% | errors |",
        "|---|---|--:|--:|--:|--:|--:|",
    ]
    for s in digest["sessions"]:
        lines.append(
            f"| `{s['id'][:8]}` | {s['title'] or '—'} | {s['turns']} | {s['output_tokens']:,} | "
            f"{s['weighted_input_tokens']:,} | {s['cache_churn_pct']} | {s['tool_errors']} |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# show — resolve one evidence pointer
# ---------------------------------------------------------------------------


def show_record(session: str, uuid: str, transcript_root: Path = DEFAULT_TRANSCRIPT_ROOT, chars: int = 2000) -> str:
    """Fetch exactly one record by (session, uuid), redacted.

    The counterpart to the pointers in `evidence`: a reviewer verifies a finding by pulling
    the one record it rests on, not by reading the session. Bounded by `chars` so a single
    lookup cannot itself become the context blowout this whole file exists to avoid.
    """
    # The file named for the session is tried first, but it is only a hint: bridged and
    # resumed sessions put records under a differently-named file, so a miss falls through
    # to a full scan rather than reporting "not found" for a record that exists.
    candidates = sorted(transcript_root.rglob("*.jsonl"), key=lambda p: p.stem != session)
    for path in candidates:
        for record in iter_records(path):
            if str(record.get("uuid") or "") != uuid:
                continue
            rec_session = record.get("sessionId") or record.get("session_id") or ""
            if session and rec_session and rec_session != session:
                continue
            body = json.dumps(record.get("message") or record, indent=2, ensure_ascii=False)
            header = f"# {path.name}\n# {record.get('type')} @ {record.get('timestamp')}\n"
            return header + redact(body)[:chars]
    return f"no record found for session={session} uuid={uuid}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def check() -> int:
    """Self-test the detectors against inline fixtures.

    Not a substitute for tests/test_session_sweep.py — it exists so the systemd unit can
    prove the detectors still fire before spending a model run on their output. A sweep
    driven by a silently broken detector reports "nothing found" and looks like success.
    """
    failures: list[str] = []

    bad = [
        ("environment-test-from-host", "ENVIRONMENT=test uv run pytest tests/ -v"),
        ("workflow-upgrade-db", "uv run workflow upgrade-db"),
        ("shell-read-instead-of-read-tool", "cat scripts/preflight.py"),
        ("git-force-push", "git push --force origin feat/x"),
        ("production-environment", "ENVIRONMENT=production python app/app.py"),
        ("system-python3", "/usr/bin/python3 scripts/skill_graph.py"),
    ]
    for rule_id, command in bad:
        rule = next(r for r in HOUSE_RULES if r.rule_id == rule_id)
        if not rule.matches(command):
            failures.append(f"{rule_id} failed to fire on {command!r}")

    good = [
        "uv run pytest tests/ -v",
        "uv run alembic upgrade head",
        "cat scripts/preflight.py | grep -c def",
        "git push origin feat/x",
        "python3 scripts/skill_graph.py --check",
    ]
    for command in good:
        for rule in HOUSE_RULES:
            if rule.matches(command):
                failures.append(f"{rule.rule_id} false-positived on {command!r}")

    # Assembled from fragments, not written inline: the blocking `gitleaks` CI job scans
    # this file, and a realistic token literal fails that gate. Allowlisting the path is
    # barred by .gitleaks.toml's own rules for a path still live in the tree.
    fake_pat = "glpat-" + "abcdefghijklmnop"
    if fake_pat in redact(f"export GITLAB_TOKEN={fake_pat}"):
        failures.append("redact() leaked a glpat token")

    if failures:
        for line in failures:
            print(f"  ✗ {line}", file=sys.stderr)
        print(f"session_sweep self-check: {len(failures)} failure(s)", file=sys.stderr)
        return 1
    print(f"session_sweep self-check: {len(HOUSE_RULES)} rules, redaction ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="self-test the detectors, exit 1 on failure")
    sub = parser.add_subparsers(dest="command")

    p_digest = sub.add_parser("digest", help="build the window digest")
    p_digest.add_argument("--days", type=int, default=7)
    p_digest.add_argument("--transcript-root", type=Path, default=DEFAULT_TRANSCRIPT_ROOT)
    p_digest.add_argument("--out", type=Path, default=None, help="directory to write digest.json/.md into")
    p_digest.add_argument("--json", action="store_true", help="print digest.json to stdout instead")

    p_show = sub.add_parser("show", help="resolve one evidence pointer")
    p_show.add_argument("--session", required=True)
    p_show.add_argument("--uuid", required=True)
    p_show.add_argument("--transcript-root", type=Path, default=DEFAULT_TRANSCRIPT_ROOT)
    p_show.add_argument("--chars", type=int, default=2000)

    args = parser.parse_args(argv)

    if args.check:
        return check()

    if args.command == "show":
        print(show_record(args.session, args.uuid, args.transcript_root, args.chars))
        return 0

    if args.command != "digest":
        parser.print_help()
        return 2

    digest = build_digest(days=args.days, transcript_root=args.transcript_root)
    if args.json:
        print(json.dumps(digest, indent=2, ensure_ascii=False))
        return 0

    out_dir = args.out or (DEFAULT_REPORT_DIR / digest["window"]["until"][:10])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "digest.json").write_text(json.dumps(digest, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "digest.md").write_text(render_markdown(digest), encoding="utf-8")
    size = (out_dir / "digest.json").stat().st_size
    print(
        f"digest: {digest['scanned']['sessions']} sessions, "
        f"{digest['scanned']['tool_calls']} tool calls -> {out_dir}/digest.json ({size:,} bytes)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
