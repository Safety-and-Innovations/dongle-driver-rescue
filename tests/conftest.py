"""Shared synthetic fixtures (SPEC §20): no physical hardware required.

All fixtures are deterministic and hostile-input aware (ADR 0002 S3/S6):
strings coming from "USB" are treated as untrusted input everywhere.
"""

from __future__ import annotations

import pathlib

import pytest

from dongle_rescue.host import Host, HostError
from dongle_rescue.types import UsbDevice


class FakeHost(Host):
    """Minimal in-memory host over a dict of path -> content (symlinks too)."""

    def __init__(self, files: dict[str, str] | None = None, links: dict[str, str] | None = None):
        import os

        self.files = {os.path.normpath(k): v for k, v in (files or {}).items()}
        self.links = {os.path.normpath(k): v for k, v in (links or {}).items()}

    def read(self, path: str) -> str:
        import os

        p = os.path.normpath(path)
        if p in self.files:
            return self.files[p]
        raise HostError(f"read {path}: No such file")

    def exists(self, path: str) -> bool:
        import os

        p = os.path.normpath(path)
        return p in self.files or p in self.links

    def listdir(self, path: str) -> list[str]:
        import os

        p = os.path.normpath(path)
        prefix = p.rstrip("/") + "/"
        names = {
            k[len(prefix):].split("/")[0]
            for k in list(self.files) + list(self.links)
            if k.startswith(prefix)
        }
        return sorted(names)

    def resolve_realpath(self, path: str) -> str:
        import os

        p = os.path.normpath(path)
        if p in self.links:
            return os.path.normpath(os.path.join(os.path.dirname(p), self.links[p]))
        return p


def make_device(
    *,
    vid: str,
    pid: str,
    bcd: str = "0200",
    product: str | None = "802.11ac NIC",
    manufacturer: str | None = "Realtek",
    modalias: str | None = None,
    sysfs_path: str = "/sys/bus/usb/devices/1-2",
) -> UsbDevice:
    """Build a UsbDevice with canonical defaults (device-level modalias)."""
    dc = dsc = dp = 0
    if modalias is None:
        modalias = (
            f"usb:v{vid.upper()}p{pid.upper()}d{bcd.upper()}dc{dc:02X}dsc{dsc:02X}dp{dp:02X}"
        )
    return UsbDevice(
        sysfs_path=sysfs_path,
        vid=vid,
        pid=pid,
        bcd_device=bcd,
        device_class=dc,
        device_subclass=dsc,
        device_protocol=dp,
        manufacturer=manufacturer,
        product=product,
        serial=None,
        modalias=modalias,
    )


#: Synthetic modules.alias covering the fixture scenarios of the task brief.
ALIAS_MT7601_BOUND_SCENARIO = [
    "# aliases begin",
    "alias usb:v148Fp7601d*dc*dsc*dp*ic*isc*ip*in* mt7601u",
    "alias usb:v148Fp760Ad*dc*dsc*dp*ic*isc*ip*in* mt7601u",  # collision member 1
    "alias usb:v148Fp760Ad*dc*dsc*dp*ic*isc*ip*in* mt76x0u",  # collision member 2
    "alias usb:v0CF3p9271d*dc*dsc*dp*ic*isc*ip*in* ath9k_htc",
    "alias pci:v000010ECd00008168sv*sd*bc*sc*i* r8169",
]

#: KB subset mirroring src/dongle_rescue/data/chipsets.json entry shape.
KB_SYNTHETIC = {
    "chipsets": [
        {
            "chipset": "RTL8811CU",
            "family": "realtek-wifi",
            "modules": ["rtw_8821cu"],
            "preferred_module": "rtw_8821cu",
            "firmware": ["rtlwifi/rtl8821aefw.bin"],
            "fw_package_debian": ["firmware-realtek"],
            "new_id_feasible": True,
            "new_id_modules": ["rtw_8821cu"],
            "confidence": "HIGH_CONFIDENCE",
            "usb_ids": ["0bda:8811"],
            "notes": "fixture",
        },
        {
            "chipset": "MT7601U",
            "family": "mediatek-wifi",
            "modules": ["mt7601u"],
            "firmware": ["mt7601u.bin"],
            "fw_package_debian": ["firmware-mediatek"],
            "new_id_feasible": True,
            "new_id_modules": ["mt7601u"],
            "confidence": "CONFIRMED",
            "usb_ids": ["148f:7601", "148f:760a"],
        },
        {
            "chipset": "MT7610U",
            "family": "mediatek-wifi",
            "modules": ["mt76x0u"],
            "firmware": ["mediatek/mt7610u.bin"],
            "fw_package_debian": ["firmware-mediatek"],
            "new_id_feasible": True,
            "new_id_modules": ["mt76x0u"],
            "confidence": "CONFIRMED",
            "usb_ids": ["148f:760a"],
        },
        {
            "chipset": "AR9271",
            "family": "atheros-wifi",
            "modules": ["ath9k_htc"],
            "firmware": ["ath9k_htc/htc_9271-1.4.0.fw"],
            "fw_package_debian": ["firmware-atheros"],
            "new_id_feasible": True,
            "confidence": "CONFIRMED",
            "usb_ids": ["0cf3:9271"],
        },
        {
            "chipset": "RTL8188EU",
            "family": "realtek-wifi",
            "modules": ["rtl8xxxu"],
            "firmware": ["rtlwifi/rtl8188eufw.bin"],
            "fw_package_debian": ["firmware-realtek"],
            "new_id_feasible": False,
            "confidence": "HIGH_CONFIDENCE",
            "usb_ids": ["0bda:8179"],
        },
    ]
}


@pytest.fixture()
def fake_host() -> FakeHost:
    return FakeHost()


@pytest.fixture()
def kb_synthetic() -> dict:
    return KB_SYNTHETIC


@pytest.fixture()
def alias_lines_synthetic() -> list[str]:
    return list(ALIAS_MT7601_BOUND_SCENARIO)

# ---------------------------------------------------------------------------
# Platform guard for the fixture tree.
#
# The fixtures mirror the kernel sysfs and contain directories like
# `sys/bus/usb/devices/1-3:1.0`. A colon is a reserved character on NTFS: on a
# Windows checkout those paths DO NOT EXIST — git writes mangled 8.3 names
# (`1HIVA8~9.0`) and marks the real files as deleted. Running the suite that
# way produces dozens of confusing errors, and a `git add -A` deletes the
# fixtures from the repository. Better to fail early, with an explicit reason.
# ---------------------------------------------------------------------------

_TREE = pathlib.Path(__file__).parent / "fixtures" / "tree"
_EXPECTED = [
    _TREE / "mt7601_ok/sys/bus/usb/devices/1-3:1.0",
    _TREE / "rtl8811cu_unbound/sys/bus/usb/devices/1-2:1.0",
    _TREE / "collision_760a/sys/bus/usb/devices/1-4:1.0",
]


def pytest_configure(config):
    missing = [p for p in _EXPECTED if not p.is_dir()]
    if not missing:
        return
    raise pytest.UsageError(
        "incomplete fixture tree: "
        + ", ".join(str(p.relative_to(_TREE.parent)) for p in missing)
        + ".\n\nDirectories with ':' do not exist on NTFS. This repository must "
        "be cloned and run on Linux or WSL — never on a Windows checkout. "
        "If you already have a broken Windows checkout, discard it and clone "
        "again inside WSL; do NOT run `git add -A` there, it deletes the fixtures."
    )
