"""TDD: diagnostics classifier — five-state machine (SPEC §6)."""

from __future__ import annotations

from conftest import ALIAS_MT7601_BOUND_SCENARIO, KB_SYNTHETIC, make_device
from dongle_rescue.diagnostics.classifier import classify
from dongle_rescue.identification.resolver import resolve_device
from dongle_rescue.types import Confidence, DiagnosisState


def _res(vid, pid):
    return resolve_device(make_device(vid=vid, pid=pid), ALIAS_MT7601_BOUND_SCENARIO, KB_SYNTHETIC)


def test_state_a_working_device():
    d = classify(
        _res("148f", "7601"),
        bound_driver="mt7601u",
        dmesg_lines=[],
        modprobe_d={},
    )
    assert d.state == DiagnosisState.A_WORKING
    assert d.recommended_action.kind == "no_action"
    assert d.confidence == Confidence.CONFIRMED


def test_state_b_feasible_bind():
    d = classify(
        _res("0bda", "8811"),
        bound_driver=None,
        dmesg_lines=[],
        modprobe_d={},
    )
    assert d.state == DiagnosisState.B_ID_UNBOUND
    assert d.recommended_action.kind == "bind_new_id"
    assert d.recommended_action.safe_for_automation is False


def test_state_b_infeasible_points_to_origin_never_promises_bind():
    d = classify(
        _res("0bda", "8179"),  # RTL8188EU via rtl8xxxu (no_dynamic_id)
        bound_driver=None,
        dmesg_lines=[],
        modprobe_d={},
    )
    assert d.state == DiagnosisState.B_ID_UNBOUND
    assert d.recommended_action.kind != "bind_new_id"
    assert d.recommended_action.commands == ()
    assert d.recommended_action.explanation  # explains the refusal


def test_state_c_firmware_missing_from_dmesg():
    dmesg = [
        "[ 9.1] mt7601u 1-2:1.0: Direct firmware load for mt7601u.bin failed with error -2",
    ]
    d = classify(
        _res("148f", "7601"),
        bound_driver="mt7601u",
        dmesg_lines=dmesg,
        modprobe_d={},
    )
    assert d.state == DiagnosisState.C_FIRMWARE_MISSING
    assert d.recommended_action.kind == "install_firmware_package"
    assert any("firmware-mediatek" in c for c in d.recommended_action.commands)


def test_state_d_blacklisted_module():
    d = classify(
        _res("148f", "7601"),
        bound_driver=None,
        dmesg_lines=[],
        modprobe_d={
            "/etc/modprobe.d/blacklist.conf": "blacklist mt7601u\n",
        },
    )
    assert d.state == DiagnosisState.D_MODULE_BLOCKED
    assert d.recommended_action.kind == "unblock_module"


def test_state_e_chipset_known_but_no_in_tree_claim():
    # AR9271 is in the KB but this scenario's alias list is empty: no kernel
    # row claims it in-tree. The SAME synthetic KB must be passed to classify,
    # otherwise the real chipsets.json (which has alias evidence for AR9271)
    # leaks in and the device classifies as B instead of E.
    from conftest import make_device as md
    res = resolve_device(
        md(vid="0cf3", pid="9271"), [], KB_SYNTHETIC  # alias empty
    )
    d = classify(
        res, bound_driver=None, dmesg_lines=[], modprobe_d={}, kb=KB_SYNTHETIC
    )
    assert d.state == DiagnosisState.E_NO_INTREE_DRIVER
    assert d.recommended_action.kind == "out_of_tree_pointer"


def test_unknown_device_yields_manual_chip_id():
    d = classify(
        _res("1234", "5678"),
        bound_driver=None,
        dmesg_lines=[],
        modprobe_d={},
    )
    assert d.state == DiagnosisState.UNKNOWN_DEVICE
    assert d.recommended_action.kind == "manual_chip_id"


def test_state_c_outranks_a_when_bound_but_firmware_failing():
    dmesg = [
        "[ 9.1] mt7601u 1-2:1.0: Direct firmware load for mt7601u.bin failed with error -2",
    ]
    d = classify(
        _res("148f", "7601"),
        bound_driver="mt7601u",
        dmesg_lines=dmesg,
        modprobe_d={},
    )
    assert d.state == DiagnosisState.C_FIRMWARE_MISSING
