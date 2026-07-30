"""Environment state: a JSON-backed store with an environment-owned audit log.

Key invariant: the audit log is written by the ENVIRONMENT on every tool call,
never by the agent. Auditability metrics are computed over this log.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from typing import Any


class EnvState:
    def __init__(self, seed_db_path: str | Path):
        with open(seed_db_path) as f:
            seed = json.load(f)
        self.data: dict[str, Any] = copy.deepcopy(seed)
        # Runtime sections (not part of the seed snapshot)
        self.data.setdefault("screening_results", [])   # list of match dicts (flattened)
        self.data.setdefault("case", {"status": "open", "flags": [], "notes": []})
        self.data.setdefault("doc_requests", [])
        self.data.setdefault("account_open", {"status": "none"})
        self.data.setdefault("escalations", [])
        self.audit_log: list[dict[str, Any]] = []
        self._seq = 0

    def log(self, tool: str, args: dict[str, Any], result: Any) -> int:
        self._seq += 1
        self.audit_log.append(
            {"seq": self._seq, "tool": tool, "args": args, "result_digest": _digest(result)}
        )
        return self._seq


def _digest(result: Any, limit: int = 400) -> str:
    s = json.dumps(result, default=str)
    return s if len(s) <= limit else s[:limit] + "..."
