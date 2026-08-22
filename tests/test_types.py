"""Smoke tests for core contracts (ADR 0003)."""

from __future__ import annotations

import pytest

from dongle_rescue.types import (
    Confidence,
    DiagnosisState,
    Evidence,
    UsbDevice,
    require_firmware_path,
    require_module_name,
)


class TestConfidence:
    def test_exactly_five_levels(self):
        assert len(Confidence) == 5
        assert Confidence.UNKNOWN.value == "UNKNOWN"

    def test_diagnosis_states(self):
        assert {s.value for s in DiagnosisState} == {"A", "B", "C", "D", "E", "UNKNOWN"}


class TestUsbDevice:
    def _device(self, vid="0bda", pid="8811"):
        return UsbDevice(
            sysfs_path="/sys/bus/usb/devices/1-2",
            vid=vid,
            pid=pid,
            bcd_device="0200",
            device_class=0,
            device_subclass=0,
            device_protocol=0,
            manufacturer="Realtek",
            product="802.11ac NIC",
            serial=None,
            modalias=f"usb:v{vid.upper()}p{pid.upper()}d0200dc00dsc00dp00ic00isc00ip00",
        )

    def test_accepts_valid_ids(self):
        d = self._device()
        assert d.vid_pid == "0bda:8811"

    @pytest.mark.parametrize("bad", ["", "bda", "0bda1", "0bdX", "0x881"])
    def test_rejects_bad_vid(self, bad):
        with pytest.raises(ValueError):
            self._device(vid=bad)

    def test_normalizes_case(self):
        d = self._device(vid="0BDA", pid="8811")
        assert d.vid == "0bda" and d.pid == "8811"


class TestGrammars:
    @pytest.mark.parametrize(
        ("value", "ok"),
        [
            ("rtl8xxxu", True),
            ("btusb", True),
            ("ath9k_htc", True),
            ("mt7921u", True),
            ("Rtl", False),  # uppercase rejected by grammar (module names are lowercase)
            ("a" * 65, False),
            ("bad;name", False),
            ("../escape", False),
        ],
    )
    def test_module_names(self, value, ok):
        if ok:
            assert require_module_name(value) == value
        else:
            with pytest.raises(ValueError):
                require_module_name(value)

    @pytest.mark.parametrize(
        ("value", "ok"),
        [
            ("rtlwifi/rtl8192cufw_B.bin", True),
            ("rtl_bt/rtl8761b_fw.bin", True),
            ("htc_9271.fw", True),
            ("/etc/passwd", False),
            ("../../etc/passwd", False),
            ("rtl/../..//etc/shadow", False),
            ("", False),
            ("a\\b.bin", False),
        ],
    )
    def test_firmware_paths(self, value, ok):
        if ok:
            assert require_firmware_path(value)
        else:
            with pytest.raises(ValueError):
                require_firmware_path(value)


def test_evidence_is_deterministic():
    e = Evidence(source="/sys/bus/usb/devices/1-2/idVendor", detail="0bda")
    assert e.to_dict() == {"source": "/sys/bus/usb/devices/1-2/idVendor", "detail": "0bda"}
