"""TDD: windows/enum_ps.py — command generators and pnputil output parser.

This module NEVER executes PowerShell on Linux (SPEC §4): it only builds
documented command strings (whitelist windows-diagnostics.md §5.2) and parses
their text output from fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from dongle_rescue.windows.enum_ps import (
    build_get_pnpdevice_cmd,
    build_pnputil_enum_devices_cmd,
    parse_pnputil_output,
)
from fixtures.windows_pnputil_sample import (
    PNPUTIL_SAMPLE,
    SAMPLE_DEVICES,
)


def test_enum_devices_cmd_uses_only_whitelisted_flags():
    cmd = build_pnputil_enum_devices_cmd()
    assert cmd == "pnputil /enum-devices /connected /deviceids"
    for forbidden in ("/add-driver", "/delete-driver", "/install",
                      "/restart-device", "/remove-device", "/scan-devices",
                      "/enable-device", "/disable-device"):
        assert forbidden not in cmd


def test_enum_devices_cmd_accepts_instanceid():
    cmd = build_pnputil_enum_devices_cmd(instance_id="USB\\VID_0BDA&PID_8811\\5&23c4b87&0&2")
    assert '/instanceid "USB\\VID_0BDA&PID_8811\\5&23c4b87&0&2"' in cmd
    assert cmd.startswith("pnputil /enum-devices")


def test_enum_devices_cmd_rejects_injection_in_instanceid():
    import pytest
    with pytest.raises(ValueError):
        build_pnputil_enum_devices_cmd(instance_id='USB\\x" & del C:\\ & "')
    with pytest.raises(ValueError):
        build_pnputil_enum_devices_cmd(instance_id="USB\nVID")


def test_get_pnpdevice_cmd_is_read_only_pipeline():
    cmd = build_get_pnpdevice_cmd()
    assert cmd.startswith("Get-PnpDevice -PresentOnly")
    assert "| Where-Object InstanceId -like 'USB\\*'" in cmd
    assert not any(
        bad in cmd
        for bad in ("Enable-", "Disable-", "pnputil /install", "Set-ItemProperty")
    )


def test_parse_full_sample_fixture():
    devs = parse_pnputil_output(PNPUTIL_SAMPLE)
    assert len(devs) == len(SAMPLE_DEVICES)
    by_iid = {d.instance_id: d for d in devs}
    assert "USB\\VID_0BDA&PID_8811\\5&23c4b87&0&2" in by_iid
    d = by_iid["USB\\VID_0BDA&PID_8811\\5&23c4b87&0&2"]
    assert d.hardware_ids == ("USB\\VID_0BDA&PID_8811", "USB\\VID_0BDA&PID_C811")
    assert d.problem_code == 28
    assert d.status == "ERROR"


def test_parse_problemcode_absent_means_zero():
    devs = parse_pnputil_output(PNPUTIL_SAMPLE)
    ok = [d for d in devs if d.status == "OK"]
    assert ok and all(d.problem_code is None for d in ok)


def test_parse_is_deterministic_and_ordered():
    a = parse_pnputil_output(PNPUTIL_SAMPLE)
    b = parse_pnputil_output(PNPUTIL_SAMPLE)
    assert [d.instance_id for d in a] == [d.instance_id for d in b]


def test_parse_hostile_device_with_no_instance_id_is_skipped():
    text = (
        "Instance ID:\t\t\t USB\\VID_OK\\1\r\n"
        "Device Description:\t\t Broken Entry Without Ids\r\n"
        "   \r\n"
        "Garbage line without tabs\r\n"
    )
    devs = parse_pnputil_output(text)
    assert len(devs) == 1
    assert devs[0].instance_id == "USB\\VID_OK\\1"


def test_parse_empty_input_yields_empty_list():
    assert parse_pnputil_output("") == []
    assert parse_pnputil_output("\r\n\r\n") == []


def test_hwids_are_normalized_uppercase_tuples():
    devs = parse_pnputil_output(PNPUTIL_SAMPLE)
    mt = [d for d in devs if "148F" in d.instance_id]
    assert mt[0].hardware_ids == (
        "USB\\VID_148F&PID_7601",
        "USB\\VID_148F&PID_7601&MI_00",
    )
