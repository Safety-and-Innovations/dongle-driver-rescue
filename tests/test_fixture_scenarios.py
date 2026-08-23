"""Fixture-tree integration tests (SPEC §20): full pipeline over scenarios.

Each scenario lives in tests/fixtures/tree/<name>/ with virtual roots:
  sys/    -> /sys
  lib/firmware -> /lib/firmware
  lib/modules  -> /lib/modules
Provenance of every scenario is documented in tests/fixtures/tree/README.md.
Golden byte-a-byte outputs (ADR 0003 D4) live in tests/fixtures/golden/.
"""

from __future__ import annotations

import json
import os

import pytest

from dongle_rescue.host import firmware_exists
from dongle_rescue.linux.modules_alias import match_with_lines, read_alias_lines
from dongle_rescue.usb.enumeration import bound_driver, enumerate_usb_devices
from tests.fixtures import FixtureRootHost


def _host(scenario: str) -> FixtureRootHost:
    h = FixtureRootHost()
    h.use_scenario(scenario)
    return h


def test_scenario_rtl8811cu_unbound_enumerates_and_finds_no_driver():
    host = _host("rtl8811cu_unbound")
    devs = enumerate_usb_devices(host)
    assert [d.vid_pid for d in devs] == ["0bda:8811"]
    assert bound_driver(host, "/sys/bus/usb/devices/1-2:1.0") is None


def test_scenario_rtl8811cu_alias_matches_rtw_8821cu():
    host = _host("rtl8811cu_unbound")
    lines = read_alias_lines(host, "6.17.0-test")
    rows = match_with_lines(
        "usb:v0BDAp8811d0200dc00dsc00dp00icFFiscFFip00in00", lines
    )
    assert [r.module for r in rows] == ["rtw_8821cu"]


def test_scenario_mt7601_ok_is_bound_and_firmware_present():
    host = _host("mt7601_ok")
    devs = enumerate_usb_devices(host)
    assert [d.vid_pid for d in devs] == ["148f:7601"]
    iface = "/sys/bus/usb/devices/1-3:1.0"
    assert bound_driver(host, iface) == "mt7601u"
    assert firmware_exists(host, "mt7601u.bin") is True


def test_scenario_collision_760a_lists_two_candidates_in_file_order():
    """mediatek-atheros.md §5: one VID:PID -> two modules; dmesg arbitrates."""
    host = _host("collision_760a")
    lines = read_alias_lines(host, "6.17.0-test")
    rows = match_with_lines(
        "usb:v148Fp760Ad0000dc00dsc00dp00icFFisc00ip00in00", lines
    )
    assert [r.module for r in rows] == ["mt7601u", "mt76x0u"]
    # neither is bound (no driver symlink in this scenario)
    assert (
        bound_driver(host, "/sys/bus/usb/devices/1-4:1.0") is None
    )


def test_fixture_host_refuses_paths_outside_virtual_roots():
    host = _host("rtl8811cu_unbound")
    from dongle_rescue.host import HostError

    with pytest.raises(HostError):
        host.read("/etc/passwd")


def test_symlink_escape_is_contained():
    """S3: a fixture driver link pointing outside the root must not exist."""
    host = _host("mt7601_ok")
    real = host.resolve_realpath("/sys/bus/usb/devices/1-3:1.0/driver")
    assert real.endswith("drivers/mt7601u") and host.exists(real)


def test_all_scenarios_deterministic_across_two_runs():
    for scenario in ("rtl8811cu_unbound", "mt7601_ok", "collision_760a"):
        a = [d.to_dict() for d in enumerate_usb_devices(_host(scenario))]
        b = [d.to_dict() for d in enumerate_usb_devices(_host(scenario))]
        assert a == b
