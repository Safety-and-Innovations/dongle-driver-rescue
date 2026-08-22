"""Repair transactions: deterministic ids, append-only journal, rollback planner.

Contracts (SPEC §24, ADR 0003 D4/D6):
- ``transaction_id`` derives ONLY from content (sha256 over canonical JSON of
  the four fields). No wall-clock, no counter -> two runs on the same state
  produce the same id (regression-testable byte-a-byte).
- The journal is append-only JSONL at an injectable path. Loading reports
  corrupt lines instead of swallowing them.
- The rollback planner is PURE: given a record it returns the sequence of
  inverse action descriptions. It never executes anything. Every step carries
  ``if_present=True`` so re-applying a rollback is a declared no-op — that is
  the structural encoding of idempotency.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..types import TransactionRecord

__all__ = [
    "Journal",
    "create_transaction",
    "plan_rollback",
    "transaction_id_from",
]

def _canonical_json(obj: dict[str, Any]) -> str:
    """Canonical JSON: sorted keys, compact separators, ASCII-escaped."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def transaction_id_from(
    before_state: dict[str, Any],
    change: dict[str, Any],
    after_state: dict[str, Any],
    rollback_action: dict[str, Any],
) -> str:
    """sha256 over the canonical JSON of the four content fields (ADR D4)."""
    payload = _canonical_json(
        {
            "schema": 1,
            "before_state": before_state,
            "change": change,
            "after_state": after_state,
            "rollback_action": rollback_action,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_transaction(
    *,
    before: dict[str, Any],
    change: dict[str, Any],
    after: dict[str, Any],
    rollback_action: dict[str, Any],
) -> TransactionRecord:
    """Build one record with its content-derived deterministic id."""
    tid = transaction_id_from(before, change, after, rollback_action)
    return TransactionRecord(
        transaction_id=tid,
        before_state=before,
        change=change,
        after_state=after,
        rollback_action=rollback_action,
    )


class Journal:
    """Append-only JSONL journal of TransactionRecords (path injectable)."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)

    @property
    def path(self) -> str:
        return self._path

    def append(self, record: TransactionRecord) -> None:
        """Serialize one record as a single JSON line; never rewrite history."""
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        line = json.dumps(record.to_dict(), sort_keys=True, ensure_ascii=True)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def load(self) -> list[TransactionRecord]:
        """All records in file order; corrupt lines raise ValueError."""
        if not os.path.exists(self._path):
            return []
        out: list[TransactionRecord] = []
        with open(self._path, encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                if not raw.strip():
                    continue
                try:
                    d = json.loads(raw)
                    rec = TransactionRecord(
                        transaction_id=d["transaction_id"],
                        before_state=d["before_state"],
                        change=d["change"],
                        after_state=d["after_state"],
                        rollback_action=d["rollback_action"],
                    )
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise ValueError(
                        f"journal {self._path} line {lineno}: corrupt entry ({exc})"
                    ) from exc
                # Integrity: stored id must equal recomputed id from content.
                expected = transaction_id_from(
                    rec.before_state, rec.change, rec.after_state, rec.rollback_action
                )
                if rec.transaction_id != expected:
                    raise ValueError(
                        f"journal {self._path} line {lineno}: transaction_id "
                        f"does not match content (tampered or foreign writer)"
                    )
                out.append(rec)
        return out


def plan_rollback(record: TransactionRecord) -> list[dict[str, Any]]:
    """Pure inverse-action planner. NEVER executes.

    Idempotency is structural: each step declares ``if_present=True``, meaning
    "apply only if the target is in post-change state"; running the same step
    again on an already-reverted system is a defined no-op, so applying the
    rollback twice yields the same second action declared as no-op (SPEC §24).
    """
    steps: list[dict[str, Any]] = []
    op = record.rollback_action.get("op")
    seq = 0

    def add(step: dict[str, Any]) -> None:
        nonlocal seq
        seq += 1
        steps.append({"seq": seq, **step})

    if op == "noop":
        add({"action": "noop", "if_present": True})
    elif op == "remove_file":
        path = _require_path(record.rollback_action)
        restore = record.rollback_action.get("restore_if_existed") or {}
        add(
            {
                "action": "remove_file",
                "path": path,
                "note": "restore only if before-state says it existed",
                "restore_sha256": restore.get("sha256"),
                "if_present": True,
            }
        )
        prev = record.before_state.get("content_sha256")
        if record.before_state.get("existed") and prev:
            add(
                {
                    "action": "restore_file",
                    "path": path,
                    "expect_sha256": prev,
                    "note": "file existed before this transaction",
                    "if_present": True,
                }
            )
    elif op == "remove_new_id":
        ra = record.rollback_action
        driver = ra.get("driver")
        vid_pid = ra.get("vid_pid")
        if not driver or not vid_pid:
            raise ValueError(f"incomplete remove_new_id action: {record.rollback_action!r}")
        add(
            {
                "action": "remove_new_id",
                "driver": driver,
                "vid_pid": vid_pid,
                "note": "volatile dynid removal; absent already => no-op",
                "if_present": True,
            }
        )
    else:
        raise ValueError(f"unknown rollback op: {op!r}")

    return steps


def _require_path(action: dict[str, Any]) -> str:
    path = action.get("path")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or ".." in path.split("/")
        or "//" in path
    ):
        raise ValueError(f"rollback action has invalid absolute path: {path!r}")
    return os.path.normpath(path)
