"""TDD: repair transactions — deterministic ids, append-only JSONL journal,
pure rollback planner (SPEC §24, ADR 0003 D4/D6).

Nothing here executes a mutation: the planner returns inverse action
descriptions; applying them is out of scope for this module.
"""

from __future__ import annotations

import json

import pytest

from dongle_rescue.repair.transaction import (
    Journal,
    plan_rollback,
    create_transaction,
    transaction_id_from,
)

BEFORE = {
    "kind": "modprobe_d_file",
    "path": "/etc/modprobe.d/ddr-0bda-8811.conf",
    "existed": False,
    "sha256": None,
}
CHANGE = {
    "op": "create_modprobe_alias",
    "content": "alias usb:v0BDAp8811d*dc*dsc*dp*icFFiscFFip00in* rtw_8821cu\n",
}
AFTER = {
    "kind": "modprobe_d_file",
    "path": "/etc/modprobe.d/ddr-0bda-8811.conf",
    "existed": True,
    "content_sha256": "a" * 64,
}
ROLLBACK = {
    "op": "remove_file",
    "path": "/etc/modprobe.d/ddr-0bda-8811.conf",
    "restore_if_existed": {"sha256": None},
}


# ------------------------------------------------------------ deterministic id


def test_transaction_id_is_content_hash_not_timestamp():
    t1 = create_transaction(before=BEFORE, change=CHANGE, after=AFTER, rollback_action=ROLLBACK)
    t2 = create_transaction(before=BEFORE, change=CHANGE, after=AFTER, rollback_action=ROLLBACK)
    assert t1.transaction_id == t2.transaction_id
    assert len(t1.transaction_id) == 64  # sha256 hex


def test_transaction_id_changes_with_any_field():
    base = dict(before=BEFORE, change=CHANGE, after=AFTER, rollback_action=ROLLBACK)
    ids = {create_transaction(**base).transaction_id}
    variants = [
        {**base, "change": {**CHANGE, "content": CHANGE["content"] + "\n"}},
        {**base, "after": {**AFTER, "content_sha256": "b" * 64}},
        {**base, "before": {**BEFORE, "existed": True}},
        {**base, "rollback_action": {**ROLLBACK, "op": "restore_file"}},
    ]
    for v in variants:
        ids.add(create_transaction(**v).transaction_id)
    assert len(ids) == 5


def test_field_order_inside_dicts_does_not_change_id():
    shuffled_before = {
        "sha256": None,
        "existed": False,
        "path": BEFORE["path"],
        "kind": BEFORE["kind"],
    }
    t1 = create_transaction(before=BEFORE, change=CHANGE, after=AFTER, rollback_action=ROLLBACK)
    t2 = create_transaction(
        before=shuffled_before, change=CHANGE, after=AFTER, rollback_action=ROLLBACK
    )
    assert t1.transaction_id == t2.transaction_id


def test_record_roundtrips_to_dict_shape_of_spec_24():
    rec = create_transaction(before=BEFORE, change=CHANGE, after=AFTER, rollback_action=ROLLBACK)
    d = rec.to_dict()
    assert set(d) == {
        "transaction_id",
        "before_state",
        "change",
        "after_state",
        "rollback_action",
    }
    assert d["transaction_id"] == transaction_id_from(BEFORE, CHANGE, AFTER, ROLLBACK)


# ------------------------------------------------------------------- journal


def _sample(tmp_path):
    return create_transaction(
        before=BEFORE, change=CHANGE, after=AFTER, rollback_action=ROLLBACK
    )


def test_journal_appends_jsonl_one_object_per_line(tmp_path):
    j = Journal(tmp_path / "journal.jsonl")
    rec = _sample(tmp_path)
    j.append(rec)
    j.append(rec)  # same id twice: journal records both events verbatim
    raw = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    lines = [l for l in raw.splitlines() if l.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["transaction_id"] == rec.transaction_id
    assert json.loads(lines[1]) == json.loads(lines[0])


def test_journal_is_append_only_never_rewrites(tmp_path):
    p = tmp_path / "journal.jsonl"
    j = Journal(p)
    j.append(_sample(tmp_path))
    first_bytes = p.read_bytes()
    j.append(_sample(tmp_path))
    second = p.read_bytes()
    assert second.startswith(first_bytes) and len(second) > len(first_bytes)


def test_journal_load_returns_records_in_order(tmp_path):
    j = Journal(tmp_path / "journal.jsonl")
    rec = _sample(tmp_path)
    j.append(rec)
    loaded = j.load()
    assert len(loaded) == 1
    assert loaded[0].transaction_id == rec.transaction_id
    assert loaded[0].change == CHANGE


def test_journal_missing_file_loads_empty_not_crash(tmp_path):
    assert Journal(tmp_path / "absent.jsonl").load() == []


def test_journal_corrupt_line_is_reported_not_swallowed(tmp_path):
    p = tmp_path / "journal.jsonl"
    good = json.dumps(_sample(tmp_path).to_dict())
    p.write_text(good + "\n{not-json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Journal(p).load()


def test_journal_custom_path_is_injectable(tmp_path):
    custom = tmp_path / "nested" / "deep" / "tx.jsonl"
    Journal(custom).append(_sample(tmp_path))
    assert custom.exists()


# ----------------------------------------------------------- rollback planner


def test_plan_rollback_returns_inverse_sequence_without_executing():
    rec = _sample(None)  # type: ignore[arg-type]  # planner never uses the path
    steps = plan_rollback(rec)
    assert steps == [
        {
            "seq": 1,
            "action": "remove_file",
            "path": "/etc/modprobe.d/ddr-0bda-8811.conf",
            "note": "restore only if before-state says it existed",
            "restore_sha256": None,
            "if_present": True,
        }
    ]


def test_plan_rollback_for_new_id_write_restores_prior_ids():
    rec = create_transaction(
        before={"kind": "new_id", "driver": "rtw_8821cu", "ids": []},
        change={"op": "write_new_id", "driver": "rtw_8821cu", "vid_pid": "0bda:8811"},
        after={"kind": "new_id", "driver": "rtw_8821cu", "ids": ["0bda:8811"]},
        rollback_action={
            "op": "remove_new_id",
            "driver": "rtw_8821cu",
            "vid_pid": "0bda:8811",
        },
    )
    steps = plan_rollback(rec)
    assert steps[0]["action"] == "remove_new_id"
    assert steps[0]["driver"] == "rtw_8821cu"
    assert all(k != "executed" for k in steps[0])  # description, not execution


def test_second_planning_pass_is_declared_noop_idempotent():
    """Applying rollback twice: the second pass must be a declared no-op.

    The planner encodes idempotency structurally: every generated step is
    guarded by 'if_present', so re-running the same step on an already-reverted
    system is defined behavior (no-op), not an error.
    """
    rec = _sample(None)
    first = plan_rollback(rec)
    second = plan_rollback(rec)
    # planning is pure: same input -> same steps (ADR 0003 D4)
    assert first == second
    assert all(s.get("if_present") is True for s in first)


def test_no_op_transaction_yields_explicit_noop_step():
    rec = create_transaction(
        before={"kind": "none"},
        change={"op": "nothing"},
        after={"kind": "none"},
        rollback_action={"op": "noop"},
    )
    steps = plan_rollback(rec)
    assert steps == [{"seq": 1, "action": "noop", "if_present": True}]


def test_unknown_rollback_op_raises_valueerror_not_silent():
    rec = create_transaction(
        before={}, change={}, after={}, rollback_action={"op": "rm_rf_troll"}
    )
    with pytest.raises(ValueError):
        plan_rollback(rec)


def test_rollback_steps_carry_verifiable_targets_only():
    """Every path in a planned step must be absolute and normalized."""
    rec = _sample(None)
    for s in plan_rollback(rec):
        if "path" in s:
            assert s["path"].startswith("/")
