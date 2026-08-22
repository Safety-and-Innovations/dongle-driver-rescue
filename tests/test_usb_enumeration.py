"""Synthetic sysfs tree: one QEMU hub (real host evidence) + one fake RTL8811CU dongle.

Layout verified on kernel 6.17 (Ubuntu 24.04, Oracle 6.17.0 kernel):
device nodes carry id*/bcd*/bDevice* + strings; modalias lives on interfaces.
"""

from __future__ import annotations

import os

import pytest

from dongle_rescue.host import Host
from dongle_rescue.usb.enumeration import (
    bound_driver,
    enumerate_usb_devices,
    interface_modalias,
)


class FakeHost(Host):
    """Minimal in-memory host over a dict of path -> content (symlinks too)."""

    def __init__(self, files: dict[str, str], links: dict[str, str] | None = None):
        self.files = {os.path.normpath(k): v for k, v in files.items()}
        self.links = {os.path.normpath(k): v for k, v in (links or {}).items()}

    def read(self, path: str) -> str:
        p = os.path.normpath(path)
        if p in self.files:
            return self.files[p]
        raise Exception(f"read {path}: No such file")

    def exists(self, path: str) -> bool:
        p = os.path.normpath(path)
        return p in self.files or p in self.links

    def listdir(self, path: str) -> list[str]:
        p = os.path.normpath(path)
        prefix = p.rstrip("/") + "/"
        names = {
            k[len(prefix):].split("/")[0]
            for k in list(self.files) + list(self.links)
            if k.startswith(prefix)
        }
        return sorted(names)

    def resolve_realpath(self, path: str) -> str:
        p = os.path.normpath(path)
        return self.links.get(p, p)


@pytest.fixture()
def host() -> FakeHost:
    files = {}
    # device node 1-2: fake RTL8811CU dongle (Realtek VID 0bda)
    base = "/sys/bus/usb/devices/1-2"
    files.update(
        {
            f"{base}/idVendor": "0bda\n",
            f"{base}/idProduct": "8811\n",
            f"{base}/bcdDevice": "0200\n",
            f"{base}/bDeviceClass": "00\n",
            f"{base}/bDeviceSubClass": "00\n",
            f"{base}/bDeviceProtocol": "00\n",
            f"{base}/manufacturer": "Realtek\n",
            f"{base}/product": "802.11ac NIC\n",
            f"{base}/serial": "12345678\n",
        }
    )
    # interface 1-2:1.0 with vendor-specific class + modalias (kernel behavior)
    iface = f"{base}:1.0"
    files[f"{iface}/bInterfaceClass"] = "ff\n"
    files[f"{iface}/modalias"] = (
        "usb:v0BDAp8811d0200dc00dsc00dp00icFFisc00ip00in00\n"
    )
    # hub device without serial, incomplete sibling without ids (must be skipped)
    hub = "/sys/bus/usb/devices/1-1"
    files.update(
        {
            f"{hub}/idVendor": "1d6b\n",
            f"{hub}/idProduct": "0002\n",
            f"{hub}/bcdDevice": "0617\n",
            f"{hub}/bDeviceClass": "09\n",
            f"{hub}/product": "EHCI Host Controller\n",
            "/sys/bus/usb/devices/1-3/idVendor": "bad\n",  # incomplete: skipped
        }
    )
    links = {
        f"{iface}/driver": "../../../bus/usb/drivers/rtl8xxxu",
    }
    return FakeHost(files, links)


def test_enumerates_only_complete_devices(host: FakeHost):
    devs = enumerate_usb_devices(host)
    assert [d.vid_pid for d in devs] == ["0bda:8811", "1d6b:0002"]  # sorted, stable


def test_device_identity_fields(host: FakeHost):
    dev = enumerate_usb_devices(host)[0]
    assert dev.vid == "0bda"
    assert dev.pid == "8811"
    assert dev.bcd_device == "0200"
    assert dev.manufacturer == "Realtek"
    assert dev.product == "802.11ac NIC"
    assert dev.serial == "12345678"


def test_device_modalias_format_matches_kernel(host: FakeHost):
    dev = enumerate_usb_devices(host)[0]
    assert dev.modalias == "usb:v0BDAp8811d0200dc00dsc00dp00"


def test_modalias_read_from_interface_node(host: FakeHost):
    m = interface_modalias(host, "/sys/bus/usb/devices/1-2:1.0")
    assert m == "usb:v0BDAp8811d0200dc00dsc00dp00icFFisc00ip00in00"


def test_bound_driver_from_symlink(host: FakeHost):
    assert bound_driver(host, "/sys/bus/usb/devices/1-2:1.0") == "rtl8xxxu"
    assert bound_driver(host, "/sys/bus/usb/devices/1-2") is None


def test_empty_root_yields_empty_list():
    assert enumerate_usb_devices(FakeHost({})) == []
