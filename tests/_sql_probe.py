"""Shared helper for asserting a request runs no SQL beyond a small allowlist.

Used by the Compliant Tools purity tests: a solve request may only run the auth
middleware's user/org load and the blueprint gate's one feature_subscriptions lookup —
nothing else, and never a write. Robust to identifier quoting and CTEs (a regex over raw
SQL text is otherwise trivially bypassed — see test-evaluator round 3).
"""

from __future__ import annotations

import re

GATE_INFRA_TABLES = frozenset({"users", "organisations", "feature_subscriptions"})
_WRITE_KW = ("insert into", "update ", "delete from", "merge into", "truncate ")
_FROM_JOIN = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_.]*)")
_CTE = re.compile(r"(?:\bwith\s+|,\s*)([a-z_][a-z0-9_]*)\s+as\s*\(")


def normalise(statement: str) -> str:
    return " ".join(statement.split()).lower().replace('"', "").replace("`", "")


def sql_beyond_gate_infra(seen: list[str], allowed: frozenset[str] = GATE_INFRA_TABLES) -> list[str]:
    """Return every statement in `seen` that writes, or reads a table outside `allowed`."""
    out: list[str] = []
    for raw in seen:
        s = normalise(raw)
        if any(kw in s for kw in _WRITE_KW):
            out.append(f"WRITE: {raw[:120]}")
            continue
        tables = {m.group(1) for m in _FROM_JOIN.finditer(s)}
        cte_aliases = {m.group(1) for m in _CTE.finditer(s)}
        offending = tables - allowed - cte_aliases
        if offending:
            out.append(f"READ {sorted(offending)}: {raw[:120]}")
    return out
