#!/usr/bin/env python3
"""Group error logs into deduplicated signatures for prod-sentinel.

Reading thousands of log lines into an agent's context to notice "the same NoneType
error 400 times" is the most expensive possible way to do a group-by. This script does
the grouping deterministically and hands back a short list of distinct error signatures
with counts and sample request_ids — the only part that needs judgment.

Sources:
    loki   Grafana Loki HTTP API (the local stack exposes :3100)
    file   newline-delimited JSON logs (structlog's `log_format = json` output)

Usage:
    python scripts/error_scan.py --source file --path /var/log/app.jsonl --since 24h
    python scripts/error_scan.py --source loki --url http://localhost:3100 --since 1h
    python scripts/error_scan.py --source file --path x.jsonl --known .agents/reports/prod-sentinel/known-issues.md

Exit codes: 0 = ran (new signatures may or may not exist), 1 = source unreachable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

# Volatile substrings that would otherwise split one bug into many signatures.
NOISE_PATTERNS = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), "<ts>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<addr>"),
    (re.compile(r"'[^']{40,}'"), "'<long>'"),
    (re.compile(r"\b\d+\b"), "<n>"),
]

ERROR_LEVELS = {"error", "critical", "exception", "fatal"}


@dataclass
class Signature:
    """One distinct error, however many times it occurred."""

    key: str
    fingerprint: str
    count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    sample_request_ids: list[str] = field(default_factory=list)
    sample_message: str = ""
    paths: set[str] = field(default_factory=set)
    orgs: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "key": self.key,
            "count": self.count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "sample_request_ids": self.sample_request_ids[:5],
            "sample_message": self.sample_message[:300],
            "paths": sorted(self.paths)[:5],
            "affected_orgs": len(self.orgs),
        }


def normalize(text: str) -> str:
    """Strip the volatile parts so the same bug collapses to one signature."""
    out = text
    for pattern, placeholder in NOISE_PATTERNS:
        out = pattern.sub(placeholder, out)
    return " ".join(out.split())[:400]


def parse_since(value: str) -> timedelta:
    match = re.fullmatch(r"(\d+)([mhd])", value.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"bad --since {value!r}; use e.g. 30m, 24h, 7d")
    amount, unit = int(match.group(1)), match.group(2)
    return {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]


def is_error(record: dict[str, Any]) -> bool:
    level = str(record.get("level") or record.get("severity") or record.get("levelname") or "").lower()
    if level in ERROR_LEVELS:
        return True
    status = record.get("status") or record.get("status_code")
    try:
        return int(status) >= 500
    except (TypeError, ValueError):
        return False


def signature_of(record: dict[str, Any]) -> tuple[str, str]:
    """Build a stable key for an error record: exception type + normalized message.

    Falls back to event name + path so a 500 with no traceback still groups sanely.
    """
    exc_type = record.get("exception_type") or record.get("exc_type") or ""
    message = str(record.get("event") or record.get("message") or record.get("msg") or "")
    exception = str(record.get("exception") or record.get("traceback") or "")

    if exception:
        # Last traceback line is usually "ModuleNotFoundError: No module named 'x'"
        tail = [ln.strip() for ln in exception.strip().splitlines() if ln.strip()]
        if tail:
            message = tail[-1]
            if not exc_type and ":" in message:
                exc_type = message.split(":", 1)[0]

    route = str(record.get("route") or record.get("path") or "")
    key = " | ".join(part for part in (exc_type, normalize(message), route) if part)
    return key or "<unclassified>", sha256((key or "<unclassified>").encode()).hexdigest()[:12]


def load_file(path: Path, cutoff: datetime) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if within_window(record, cutoff):
                records.append(record)
    return records


def within_window(record: dict[str, Any], cutoff: datetime) -> bool:
    raw = record.get("timestamp") or record.get("time") or record.get("@timestamp")
    if not raw:
        return True  # undated line: keep it rather than silently dropping evidence
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp >= cutoff


def load_loki(base_url: str, query: str, cutoff: datetime, limit: int = 5000) -> list[dict[str, Any]]:
    # urllib honours file:// (and ftp://, and more), so pin the scheme before opening a
    # caller-supplied --url. A log scanner that can be pointed at the filesystem is a
    # log scanner that can be made to read secrets and call them error records.
    if not base_url.startswith(("http://", "https://")):
        raise SystemExit(f"--url must be http(s), got: {base_url[:40]}")

    params = urllib.parse.urlencode(
        {
            "query": query,
            "start": str(int(cutoff.timestamp() * 1e9)),
            "end": str(int(datetime.now(timezone.utc).timestamp() * 1e9)),
            "limit": str(limit),
            "direction": "backward",
        }
    )
    url = f"{base_url.rstrip('/')}/loki/api/v1/query_range?{params}"
    try:
        # The rule's concern is urllib honouring file:// on a dynamic URL; base_url is
        # pinned to http(s) at the top of this function, which the pattern cannot see.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
            payload = json.load(resp)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"loki unreachable at {base_url}: {exc}")

    records = []
    for stream in payload.get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for _ts, line in stream.get("values", []):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                record = {"event": line, "level": labels.get("level", "error")}
            record.setdefault("level", labels.get("level", ""))
            records.append(record)
    return records


def known_fingerprints(path: Path | None) -> set[str]:
    """Fingerprints already triaged, read from the registry's markdown table."""
    if not path or not path.exists():
        return set()
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.search(r"\|\s*`?([0-9a-f]{12})`?\s*\|", line)
        if match:
            found.add(match.group(1))
    return found


def scan(records: list[dict[str, Any]], known: set[str]) -> dict[str, Any]:
    groups: dict[str, Signature] = {}
    counts_by_level: dict[str, int] = defaultdict(int)

    for record in records:
        counts_by_level[str(record.get("level", "?")).lower()] += 1
        if not is_error(record):
            continue
        key, fingerprint = signature_of(record)
        sig = groups.get(fingerprint)
        if sig is None:
            sig = Signature(key=key, fingerprint=fingerprint)
            sig.sample_message = str(record.get("event") or record.get("message") or "")
            groups[fingerprint] = sig
        sig.count += 1
        stamp = str(record.get("timestamp") or record.get("time") or "")
        if stamp:
            sig.first_seen = min(sig.first_seen or stamp, stamp)
            sig.last_seen = max(sig.last_seen, stamp)
        rid = record.get("request_id") or record.get("correlation_id")
        if rid and str(rid) not in sig.sample_request_ids:
            sig.sample_request_ids.append(str(rid))
        if record.get("path") or record.get("route"):
            sig.paths.add(str(record.get("route") or record.get("path")))
        if record.get("org_id") and str(record.get("org_id")) != "None":
            sig.orgs.add(str(record["org_id"]))

    ranked = sorted(groups.values(), key=lambda s: s.count, reverse=True)
    new = [s for s in ranked if s.fingerprint not in known]
    return {
        "scanned_records": len(records),
        "levels": dict(counts_by_level),
        "error_records": sum(s.count for s in ranked),
        "distinct_signatures": len(ranked),
        "known_signatures": len(ranked) - len(new),
        "new_signatures": [s.to_dict() for s in new],
        "all_signatures": [s.to_dict() for s in ranked],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Group error logs into deduplicated signatures.")
    ap.add_argument("--source", choices=["loki", "file"], required=True)
    ap.add_argument("--path", type=Path, help="file source: newline-delimited JSON logs")
    ap.add_argument("--url", default="http://localhost:3100", help="loki source: base URL")
    ap.add_argument(
        "--query",
        default='{service_name="workflow-engine"} |= "error"',
        help="loki source: LogQL selector",
    )
    ap.add_argument("--since", default="24h", help="window: 30m, 24h, 7d")
    ap.add_argument("--known", type=Path, help="known-issues registry to dedupe against")
    ap.add_argument("--json", action="store_true", help="emit JSON (default: summary)")
    args = ap.parse_args()

    cutoff = datetime.now(timezone.utc) - parse_since(args.since)

    if args.source == "file":
        if not args.path or not args.path.exists():
            print(f"no such log file: {args.path}", file=sys.stderr)
            return 1
        records = load_file(args.path, cutoff)
    else:
        records = load_loki(args.url, args.query, cutoff)

    report = scan(records, known_fingerprints(args.known))
    report["window"] = args.since
    report["source"] = args.source

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"scanned {report['scanned_records']} records over {args.since} ({args.source})")
    print(f"errors: {report['error_records']} across {report['distinct_signatures']} distinct signatures")
    print(f"new (not in registry): {len(report['new_signatures'])}\n")
    for sig in report["new_signatures"][:10]:
        print(f"  [{sig['fingerprint']}] x{sig['count']:<5} {sig['key'][:90]}")
        if sig["sample_request_ids"]:
            print(f"      request_ids: {', '.join(sig['sample_request_ids'][:3])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
