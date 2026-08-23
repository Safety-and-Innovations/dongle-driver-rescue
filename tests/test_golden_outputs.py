"""Golden byte-a-byte regression (ADR 0003 D4): canonical JSON, stable keys.

Regenerate with:  DDR_REGEN_GOLDENS=1 pytest tests/test_golden_outputs.py
Golden files live in tests/fixtures/golden/ and are compared as exact bytes.
"""

from __future__ import annotations

import json
import os

import pytest

from tests.fixtures import FixtureRootHost
from dongle_rescue.firmware.resolver import (
    check_firmware_presence,
    map_firmware_to_packages,
    parse_dmesg_firmware_failures,
)
from dongle_rescue.linux.modules_alias import match_with_lines, read_alias_lines
from dongle_rescue.repair.planner import plan_state_b
from dongle_rescue.repair.transaction import create_transaction
from dongle_rescue.usb.enumeration import enumerate_usb_devices

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "golden")


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _golden(name: str, payload) -> None:
    """Compare bytes against the golden file (or regenerate under env flag)."""
    path = os.path.join(GOLDEN_DIR, name)
    rendered = (_canon(payload) + "\n").encode("utf-8")
    if os.environ.get("DDR_REGEN_GOLDENS") == "1":
        with open(path, "wb") as fh:
            fh.write(rendered)
    assert os.path.exists(path), f"golden file missing: {name}"
    with open(path, "rb") as fh:
        expected = fh.read()
    assert rendered == expected, (
        f"golden mismatch for {name}:\n expected={expected!r}\n actual  ={rendered!r}"
    )


def _host(scenario):
    h = FixtureRootHost()
    h.use_scenario(scenario)
    return h


def test_golden_enumeration_rtl8811cu_unbound():
    devs = enumerate_usb_devices(_host("rtl8811cu_unbound"))
    _golden("enumeration_rtl8811cu_unbound.json", [d.to_dict() for d in devs])


def test_golden_alias_match_collision_760a():
    lines = read_alias_lines(_host("collision_760a"), "6.17.0-test")
    rows = match_with_lines(
        "usb:v148Fp760Ad0000dc00dsc00dp00icFFisc00ip00in00", lines
    )
    _golden(
        "alias_collision_760a.json",
        [{"pattern": r.pattern, "module": r.module, "raw": r.raw} for r in rows],
    )


def test_golden_dmesg_parse_rtl8188eu():
    from tests.fixtures import DMESG_FW_MISSING_RTL8188EU

    failures = parse_dmesg_firmware_failures(DMESG_FW_MISSING_RTL8188EU)
    _golden(
        "dmesg_parse_rtl8188eu.json",
        [
            {
                "firmware_path": f.firmware_path,
                "error": f.error,
                "valid": f.valid,
            }
            for f in failures
        ],
    )


def test_golden_firmware_presence_and_mapping_mt7601():
    st = check_firmware_presence(
        _host("mt7601_ok"), module="mt7601u", rel_path="mt7601u.bin"
    )
    mapping = map_firmware_to_packages(
        __import__("json").loads(
            open(
                os.path.join(
                    os.path.dirname(__file__), "..", "src/dongle_rescue/data/chipsets.json"
                ),
                encoding="utf-8",
            ).read()
        ),
        "mt7601u.bin",
    )
    payload = {
        "installed": st.installed,
        "found_form": st.found_form,
        "normalized_path": st.normalized_path,
        "evidence": [e.to_dict() for e in st.evidence],
        "mapping": {
            "chipset": mapping.chipset,
            "packages": list(mapping.packages),
            "confidence": mapping.confidence.value,
        },
    }
    _golden("firmware_mt7601_ok.json", payload)


def _kb_for_planner():
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


def test_golden_plan_state_b_feasible_bytes():
    from conftest import make_device

    plan = plan_state_b(
        device=make_device(vid="0bda", pid="8811"),
        kb=_kb_for_planner(),
        bound_driver=None,
        loaded_module="rtw_8821cu",
    )
    tx = plan.transaction
    payload = {
        "feasible": plan.feasible,
        "what": plan.what,
        "why": plan.why,
        "source": plan.source,
        "confidence": plan.confidence,
        "files_affected": sorted(plan.files_affected),
        "commands": plan.commands,
        "rollback": plan.rollback,
        "persistence_content": plan.persistence_content,
        "requires_root": plan.requires_root,
        "safe_for_automation": plan.safe_for_automation,
        "executed": plan.executed,
        "transaction_id": tx.transaction_id if tx else None,
    }
    _golden("plan_state_b_feasible.json", payload)


def test_golden_transaction_determinism_two_runs_same_id():
    rec_a = create_transaction(
        before={"path": "/etc/modprobe.d/ddr-0bda-8811.conf", "existed": False},
        change={"op": "create_modprobe_alias"},
        after={"existed": True},
        rollback_action={"op": "remove_file", "path": "/etc/modprobe.d/ddr-0bda-8811.conf"},
    )
    rec_b = create_transaction(
        after={"existed": True},
        rollback_action={"op": "remove_file", "path": "/etc/modprobe.d/ddr-0bda-8811.conf"},
        before={"path": "/etc/modprobe.d/ddr-0bda-8811.conf", "existed": False},
        change={"op": "create_modprobe_alias"},
    )
    assert rec_a.transaction_id == rec_b.transaction_id
    _golden("transaction_record.json", rec_a.to_dict())
