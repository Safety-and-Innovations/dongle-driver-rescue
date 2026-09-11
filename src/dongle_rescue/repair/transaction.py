"""Repair transactions (SPEC §24, ADR 0003 D4/D6).

Deterministic content-hash ids (never timestamps), append-only JSONL journal,
pure rollback planner that describes inverse actions without executing them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from ..types import TransactionRecord, require_module_name


#: ``vid:pid`` as 4-digit hex, as reported by the kernel.
_VID_PID = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}")


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def transaction_id_from(
    before_state: dict,
    change: dict,
    after_state: dict,
    rollback_action: dict,
) -> str:
    """64-hex sha256 over the canonical form of all four fields."""
    payload = "|".join(
        _canonical(part)
        for part in (before_state, change, after_state, rollback_action)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_transaction(
    *,
    before: dict,
    change: dict,
    after: dict,
    rollback_action: dict,
) -> TransactionRecord:
    tid = transaction_id_from(before, change, after, rollback_action)
    return TransactionRecord(
        transaction_id=tid,
        before_state=before,
        change=change,
        after_state=after,
        rollback_action=rollback_action,
    )


class Journal:
    """Append-only JSONL journal. Corrupt lines surface, never swallow."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, rec: TransactionRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec.to_dict(), sort_keys=True) + "\n")

    def load(self) -> list[TransactionRecord]:
        if not self.path.exists():
            return []
        out: list[TransactionRecord] = []
        for lineno, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"journal corrupt at line {lineno}: {exc}") from exc
            out.append(
                TransactionRecord(
                    transaction_id=raw["transaction_id"],
                    before_state=raw["before_state"],
                    change=raw["change"],
                    after_state=raw["after_state"],
                    rollback_action=raw["rollback_action"],
                )
            )
        return out


def plan_rollback(rec: TransactionRecord) -> list[dict]:
    """Pure inverse-action description. Guarded steps => idempotent replay."""
    op = rec.rollback_action.get("op")
    steps: list[dict] = []
    if op == "noop":
        steps.append({"seq": 1, "action": "noop", "if_present": True})
        return steps
    if op == "remove_file":
        path = rec.rollback_action.get("path")
        if not (isinstance(path, str) and path.startswith("/") and os.path.normpath(path) == path):
            raise ValueError(f"rollback path must be absolute+normalized: {path!r}")
        restore = rec.rollback_action.get("restore_if_existed") or {}
        steps.append(
            {
                "seq": 1,
                "action": "remove_file",
                "path": path,
                "note": "restore only if before-state says it existed",
                "restore_sha256": restore.get("sha256"),
                "if_present": True,
            }
        )
        return steps
    if op == "remove_new_id":
        driver = rec.rollback_action.get("driver")
        vid_pid = rec.rollback_action.get("vid_pid")
        if not isinstance(driver, str) or not driver or not isinstance(vid_pid, str):
            raise ValueError("remove_new_id requires driver and vid_pid")
        # Same rigor `remove_file` applies to the path. Before, a non-empty
        # string was enough: `driver="x; id"` passed, and the rollback step
        # carried that to whoever would execute it. The journal lives on disk
        # and can be tampered with — it is untrusted input like any other
        # (ADR 0002 S6).
        driver = require_module_name(driver)
        if not _VID_PID.fullmatch(vid_pid):
            raise ValueError(f"invalid vid:pid for remove_new_id: {vid_pid!r}")
        steps.append(
            {
                "seq": 1,
                "action": "remove_new_id",
                "driver": driver,
                "vid_pid": vid_pid,
                "note": "rewrite new_id list without this pair; volatile by design",
                "if_present": True,
            }
        )
        return steps
    raise ValueError(f"unknown rollback op: {op!r}")
