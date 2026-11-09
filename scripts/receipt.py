#!/usr/bin/env python3
"""Check receipts bound to the tree they ran on (lean workflow, .agents/verification-tiers.md).

A test result is only evidence for the code it ran against. `run` executes a check and
records its command, exit status, log and a digest of the working tree; `status` says which
receipts still match the tree now. Any edit after a run makes that receipt stale, so a
reviewer or an MR description can't quote a pass for code that has since changed.

    python3 scripts/receipt.py run --name unit -- uv run pytest tests/test_x.py -q
    python3 scripts/receipt.py status            # fresh / stale / failed, one line each
    python3 scripts/receipt.py status --json

Receipts live in .agents/tmp/receipts/ (gitignored scratch, per checkout). A skipped or
not-collected run is recorded as what it was: exit 5 from pytest is "no tests ran", not a pass.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STORE = REPO / ".agents" / "tmp" / "receipts"
PYTEST_NO_TESTS = 5


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def tree_digest(cwd: Path = REPO) -> str:
    """The content of the working tree (tracked changes and untracked files), as a git tree id.

    Content, not history: committing the same files keeps the digest, so a receipt stays fresh
    across a commit and goes stale only when a file actually changes. Built in a throwaway
    index, so the real index is untouched. Scratch under .agents/tmp/ is left out.
    """
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}

        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout

        git("read-tree", "HEAD")
        git("add", "-A", "--", ".")
        # Scratch (receipts, drafts) never counts, whether or not this repo ignores it.
        git("rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", ".agents/tmp")
        return git("write-tree").strip()[:16]


def _verdict(exit_code: int) -> str:
    if exit_code == 0:
        return "passed"
    if exit_code == PYTEST_NO_TESTS:
        return "no-tests"
    return "failed"


def run(name: str, command: list[str], *, cwd: Path = REPO, store: Path = STORE) -> dict:
    store.mkdir(parents=True, exist_ok=True)
    digest = tree_digest(cwd)
    log = store / f"{name}.log"
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(command, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT)
    receipt = {
        "name": name,
        "command": command,
        "exit_code": proc.returncode,
        "verdict": _verdict(proc.returncode),
        "tree": digest,
        "head": _git("rev-parse", "--short", "HEAD", cwd=cwd).strip(),
        "log": str(log.relative_to(cwd)) if log.is_relative_to(cwd) else str(log),
        "seconds": round(time.monotonic() - started, 1),
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    # The tree can't have changed during the run without the receipt saying so.
    if tree_digest(cwd) != digest:
        receipt["verdict"] = "stale"
        receipt["note"] = "the tree changed while the check ran"
    (store / f"{name}.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def status(*, cwd: Path = REPO, store: Path = STORE) -> list[dict]:
    now = tree_digest(cwd)
    out = []
    for path in sorted(store.glob("*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        fresh = receipt["tree"] == now and receipt["verdict"] != "stale"
        out.append({**receipt, "fresh": fresh, "state": receipt["verdict"] if fresh else "stale"})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a check and record its receipt")
    r.add_argument("--name", required=True)
    r.add_argument("command", nargs=argparse.REMAINDER)
    s = sub.add_parser("status", help="which receipts match the tree now")
    s.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            ap.error("give the command after --")
        receipt = run(args.name, command)
        print(
            f"{receipt['name']}: {receipt['verdict']} (exit {receipt['exit_code']}, {receipt['seconds']}s) tree {receipt['tree']} log {receipt['log']}"
        )
        return 0 if receipt["verdict"] == "passed" else 1
    rows = status()
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['name']}: {row['state']} (ran {row['at']} on {row['head']}, exit {row['exit_code']})")
        if not rows:
            print("no receipts yet")
    return 0 if all(row["state"] == "passed" for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
