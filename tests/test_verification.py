"""TDD: functional verification layer (SPEC §25).

Success is HARDWARE FUNCTIONAL, never INSTALLATION COMPLETED. The checker
consumes a Host (real or fixture) and reports per-check evidence:
  wifi: interface present -> driver bound -> firmware loaded -> no critical errors
  bt:   hci adapter present -> driver bound -> firmware loaded
Any indeterminate check (host failure) degrades the verdict to UNKNOWN,
never to a fake PASS.
"""

from __future__ import annotations

import pytest

from dongle_rescue.host import Host, HostError
from dongle_rescue.verification.checker import (
    CheckResult,
    VerificationReport,
    verify_device,
)


class ScriptedHost(Host):
    """Fake host with scripted reads; unscripted paths raise HostError."""

    def __init__(self, files: dict[str, str] | None = None):
        self.files = dict(files or {})

    def read(self, path):
        if path in self.files:
            return self.files[path]
        raise HostError(f"read {path}: No such file")

    def exists(self, path):
        return path in self.files

    def listdir(self, path):
        prefix = path.rstrip("/") + "/"
        names = {
            k[len(prefix):].split("/")[0]
            for k in self.files
            if k.startswith(prefix)
        }
        return sorted(names)

    def resolve_realpath(self, path):
        return path


def _wifi_host(**overrides):
    files = {
        # class/net layout: interface created by the bound driver
        "/sys/class/net/wlan0/phy80211/name": "phy0",
        # bound driver on the usb interface node
        "/sys/bus/usb/devices/1-2:1.0/driver": "mt7601u",
        # firmware loaded marker comes from dmesg absence of failures + module state
        "/sys/module/mt7601u/refcnt": "1\n",
    }
    files.update(overrides)
    return ScriptedHost(files)


# ------------------------------------------------------------------- checks


def test_all_checks_pass_yields_hardware_functional():
    host = _wifi_host()
    rep = verify_device(
        host, kind="wifi", sysfs_iface="/sys/bus/usb/devices/1-2:1.0"
    )
    assert isinstance(rep, VerificationReport)
    assert rep.verdict == "HARDWARE_FUNCTIONAL"
    assert all(c.passed for c in rep.checks)
    assert not rep.critical_errors


def test_no_interface_means_not_functional():
    host = _wifi_host()
    host.files.pop("/sys/class/net/wlan0/phy80211/name")
    rep = verify_device(host, kind="wifi", sysfs_iface="/sys/bus/usb/devices/1-2:1.0")
    assert rep.verdict == "NOT_FUNCTIONAL"
    iface_check = rep.checks[0]
    assert iface_check.name == "interface_present"
    assert iface_check.passed is False


def test_driver_unbound_means_not_functional_with_explanation():
    host = _wifi_host()
    host.files.pop("/sys/bus/usb/devices/1-2:1.0/driver")
    rep = verify_device(host, kind="wifi", sysfs_iface="/sys/bus/usb/devices/1-2:1.0")
    assert rep.verdict == "NOT_FUNCTIONAL"
    drv = next(c for c in rep.checks if c.name == "driver_bound")
    assert drv.passed is False
    assert drv.detail  # explainable


def test_firmware_failure_in_dmesg_blocks_functional_verdict():
    host = _wifi_host()
    dmesg = [
        "[ 9.1] mt7601u 1-2:1.0: Direct firmware load for mt7601u.bin failed with error -2",
    ]
    rep = verify_device(
        host, kind="wifi", sysfs_iface="/sys/bus/usb/devices/1-2:1.0",
        dmesg_lines=dmesg,
    )
    fw = next(c for c in rep.checks if c.name == "firmware_loaded")
    assert fw.passed is False
    assert rep.verdict == "NOT_FUNCTIONAL"


def test_bluetooth_kind_checks_hci_adapter():
    host = ScriptedHost({
        "/sys/class/bluetooth/hci0/address": "00:11:22:33:44:55\n",
        "/sys/bus/usb/devices/1-5:1.0/driver": "btusb",
    })
    rep = verify_device(host, kind="bt", sysfs_iface="/sys/bus/usb/devices/1-5:1.0")
    assert rep.verdict == "HARDWARE_FUNCTIONAL"
    names = [c.name for c in rep.checks]
    assert "hci_adapter_present" in names


def test_unknown_kind_is_refused_not_guessed():
    with pytest.raises(ValueError):
        verify_device(_wifi_host(), kind="serial", sysfs_iface="x")


def test_every_check_carries_evidence_source():
    rep = verify_device(
        _wifi_host(), kind="wifi", sysfs_iface="/sys/bus/usb/devices/1-2:1.0"
    )
    for c in rep.checks:
        assert c.source


def test_report_is_deterministic_two_runs_identical():
    host = _wifi_host()
    a = verify_device(host, kind="wifi", sysfs_iface="/sys/bus/usb/devices/1-2:1.0")
    b = verify_device(host, kind="wifi", sysfs_iface="/sys/bus/usb/devices/1-2:1.0")
    assert a.to_dict() == b.to_dict()


def test_to_dict_shape_for_json_output():
    rep = verify_device(
        _wifi_host(), kind="wifi", sysfs_iface="/sys/bus/usb/devices/1-2:1.0"
    )
    d = rep.to_dict()
    assert d["verdict"] == "HARDWARE_FUNCTIONAL"
    assert isinstance(d["checks"], list) and d["checks"]
