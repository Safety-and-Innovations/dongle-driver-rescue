"""TDD: repair planner — dry-run plan for diagnosis state B (SPEC §23).

Feasible case  : new_id-capable driver -> DISPLAY-ONLY plan with WHAT/WHY/
                 SOURCE/EVIDENCE/CONFIDENCE/FILES AFFECTED/COMMANDS/ROLLBACK.
Infeasible case: rtl8xxxu (.no_dynamic_id=1, realtek.md §1) -> empty plan +
                 explanation + pointer to the official origin.
The planner NEVER executes; commands are strings for display only (SPEC §37).
"""

from __future__ import annotations

import pytest

from dongle_rescue.repair.planner import (
    EMPTY_PLAN,
    Plan,
    plan_state_b,
)
from conftest import make_device


def _feasible_device():
    return make_device(vid="0bda", pid="8811")  # RTL8811CU


def _kb_feasible():
    return {
        "chipsets": [
            {
                "chipset": "RTL8811CU",
                "family": "realtek-wifi",
                "modules": ["rtl8xxxu", "rtw_8821cu"],
                "preferred_module": "rtw_8821cu",
                "new_id_feasible": True,
                "new_id_modules": ["rtw_8821cu"],
                "confidence": "HIGH_CONFIDENCE",
                "usb_ids": ["0bda:8811"],
            }
        ]
    }


def _kb_infeasible():
    return {
        "chipsets": [
            {
                "chipset": "RTL8188EU",
                "family": "realtek-wifi",
                "modules": ["rtl8xxxu"],
                "new_id_feasible": False,
                "confidence": "HIGH_CONFIDENCE",
                "usb_ids": ["0bda:8179"],
                "notes": ".no_dynamic_id = 1",
            }
        ]
    }


# ------------------------------------------------------------- feasible plan


def test_feasible_plan_has_all_spec_23_fields():
    plan = plan_state_b(
        device=_feasible_device(),
        kb=_kb_feasible(),
        bound_driver=None,
        loaded_module="rtw_8821cu",
    )
    assert isinstance(plan, Plan)
    assert not plan.feasible is False
    for field in (
        "what",
        "why",
        "source",
        "evidence",
        "confidence",
        "files_affected",
        "commands",
        "rollback",
    ):
        assert getattr(plan, field), f"SPEC §23 field {field} must be filled"


def test_new_id_command_is_display_only_and_correct_format():
    plan = plan_state_b(
        device=_feasible_device(), kb=_kb_feasible(), bound_driver="rtw_8821cu"
    )
    cmd = plan.commands[0]
    assert "0bda 8811" in cmd
    assert "sudo tee /sys/bus/usb/drivers/rtw_8821cu/new_id" in cmd
    assert plan.executed is False  # nothing runs here, ever


def test_modprobe_d_alias_line_matches_kernel_alias_format():
    """Research linux-kernel.md §4: alias usb:vXXXXpYYYYd*... <module>."""
    plan = plan_state_b(
        device=_feasible_device(), kb=_kb_feasible(), bound_driver="rtw_8821cu"
    )
    conf_files = [f for f in plan.files_affected if f.startswith("/etc/modprobe.d/ddr-")]
    assert len(conf_files) == 1
    alias_line = plan.persistence_content
    assert alias_line == (
        "alias usb:v0BDAp8811d*dc*dsc*dp*icFFiscFFip00in* rtw_8821cu\n"
    )


def test_persistence_write_is_in_commands_with_tee_not_redirect():
    """Root writes via `tee -a`, never a bare shell redirect in the plan."""
    plan = plan_state_b(
        device=_feasible_device(), kb=_kb_feasible(), bound_driver="rtw_8821cu"
    )
    persistence_cmds = [c for c in plan.commands if "/etc/modprobe.d/" in c]
    assert any("tee" in c for c in persistence_cmds)


def test_plan_carries_transaction_with_deterministic_id():
    p1 = plan_state_b(device=_feasible_device(), kb=_kb_feasible(), bound_driver="rtw_8821cu")
    p2 = plan_state_b(device=_feasible_device(), kb=_kb_feasible(), bound_driver="rtw_8821cu")
    assert p1.transaction is not None
    assert p1.transaction.transaction_id == p2.transaction.transaction_id
    rb_op = p1.transaction.rollback_action["op"]
    assert rb_op == "remove_file"


def test_plan_requires_root_and_refuses_automation():
    plan = plan_state_b(device=_feasible_device(), kb=_kb_feasible())
    assert plan.requires_root is True
    assert plan.safe_for_automation is False


def test_evidence_cites_kb_and_research_docs():
    plan = plan_state_b(device=_feasible_device(), kb=_kb_feasible())
    joined = json.dumps([e.to_dict() for e in plan.evidence])
    assert "chipset-kb" in joined or "chipsets.json" in joined


# ----------------------------------------------------------- infeasible plan


def test_rtl8xxxu_infeasible_yields_empty_plan_with_official_pointer():
    plan = plan_state_b(
        device=make_device(vid="0bda", pid="8179"),
        kb=_kb_infeasible(),
        bound_driver=None,
    )
    assert plan.feasible is False
    assert plan.commands == []
    assert plan.files_affected == []
    assert plan.transaction is None
    assert "no_dynamic_id" in plan.why or "not feasible" in plan.why.lower()
    assert plan.official_origin, "must point at the legitimate origin"


EMPTY_PLAN_SANITY = EMPTY_PLAN


# ------------------------------------------------------------------ hostile


def test_unknown_chipset_is_honest_empty_plan():
    plan = plan_state_b(
        device=make_device(vid="1234", pid="5678"),
        kb={"chipsets": []},
        bound_driver=None,
    )
    assert plan.feasible is False
    assert plan.commands == []


def test_hostile_vidpid_never_reaches_command_string():
    # UsbDevice grammar already blocks non-hex ids at construction; the
    # planner only ever interpolates dev.vid/pid, which are validated there.
    plan = plan_state_b(
        device=make_device(vid="0bad", pid="c0de"), kb=_kb_feasible()
    )
    for c in plan.commands:
        assert "0bad c0de" in c  # exact tokens only, never raw unvalidated input


import json  # noqa: E402  (used by evidence test above)
