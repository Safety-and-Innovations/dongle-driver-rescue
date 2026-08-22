"""USB device enumeration from sysfs (SPEC §7 layers 1-2).

Evidence-based layout (verified on kernel 6.17, see tests/fixtures/sysfs):
- device node (e.g. 1-2): idVendor, idProduct, bcdDevice, bDeviceClass,
  bDeviceSubClass, bDeviceProtocol, manufacturer, product, serial, uevent.
- interface node (e.g. 1-2:1.0): modalias, bInterfaceClass, driver symlink.
The device node has NO modalias; the modalias lives on interfaces.
"""

from __future__ import annotations

import os

from ..types import Evidence, UsbDevice
from ..host import Host, HostError

USB_DEVICES_ROOT = "/sys/bus/usb/devices"
_HEX = set("0123456789abcdefABCDEF")


def _read_attr(host: Host, path: str, name: str) -> str | None:
    """Read one sysfs attribute; returns stripped value or None."""
    try:
        raw = host.read(f"{path}/{name}")
    except HostError:
        return None
    return raw.strip() or None


def _is_hex4(value: str | None) -> bool:
    return value is not None and len(value) == 4 and all(c in _HEX for c in value)


def _is_device_node(name: str) -> bool:
    """Device nodes: '1-2', '1-2.3'; interfaces carry ':' and roots are 'usbN'."""
    return ":" not in name and not name.startswith("usb")


def enumerate_usb_devices(host: Host, root: str = USB_DEVICES_ROOT) -> list[UsbDevice]:
    """Enumerate complete, valid USB devices. Deterministic order (ADR 0003 D4).

    Incomplete entries (missing ids) are skipped — a dongle always exposes
    idVendor/idProduct; anything else is a hub quirk, not diagnosable.
    """
    try:
        entries = host.listdir(root)
    except HostError:
        return []
    devices: list[UsbDevice] = []
    for name in sorted(entries):  # stable order independent of readdir
        if not _is_device_node(name):
            continue
        path = f"{root}/{name}"
        vid = _read_attr(host, path, "idVendor")
        pid = _read_attr(host, path, "idProduct")
        bcd = _read_attr(host, path, "bcdDevice")
        if not (_is_hex4(vid) and _is_hex4(pid) and _is_hex4(bcd)):
            continue
        assert vid is not None and pid is not None and bcd is not None
        dc = int(_read_attr(host, path, "bDeviceClass") or "0", 16)
        dsc = int(_read_attr(host, path, "bDeviceSubClass") or "0", 16)
        dp = int(_read_attr(host, path, "bDeviceProtocol") or "0", 16)
        try:
            dev = UsbDevice(
                sysfs_path=path,
                vid=vid,
                pid=pid,
                bcd_device=bcd,
                device_class=dc,
                device_subclass=dsc,
                device_protocol=dp,
                manufacturer=_read_attr(host, path, "manufacturer"),
                product=_read_attr(host, path, "product"),
                serial=_read_attr(host, path, "serial"),
                modalias=_build_device_modalias(vid, pid, bcd, dc, dsc, dp),
            )
        except (ValueError, OSError):
            continue
        devices.append(dev)
    return devices


def _build_device_modalias(
    vid: str, pid: str, bcd: str, dc: int, dsc: int, dp: int
) -> str:
    """Canonical device-level modalias (kernel usb modalias format)."""
    return (
        f"usb:v{vid.upper()}p{pid.upper()}d{bcd.upper()}"
        f"dc{dc:02X}dsc{dsc:02X}dp{dp:02X}"
    )


def interface_modalias(host: Host, interface_path: str) -> str | None:
    """Read modalias from an interface node (1-2:1.0), where the kernel puts it."""
    return _read_attr(host, interface_path, "modalias")


def bound_driver(host: Host, path: str) -> str | None:
    """Name of the driver bound at this node (device or interface), or None.

    Reads the 'driver' symlink target basename without following outside sysfs.
    """
    link = f"{path}/driver"
    try:
        target = host.resolve_realpath(link)
    except (HostError, OSError):
        return None
    if not host.exists(f"{target}"):
        return None
    return os.path.basename(target)


def device_evidence(dev: UsbDevice) -> list[Evidence]:
    """Evidence trail for a device identity read (SPEC §7 layer 1-2)."""
    evs = [
        Evidence(source=f"{dev.sysfs_path}/idVendor", detail=dev.vid),
        Evidence(source=f"{dev.sysfs_path}/idProduct", detail=dev.pid),
        Evidence(source=f"{dev.sysfs_path}/bcdDevice", detail=dev.bcd_device),
    ]
    if dev.product:
        evs.append(Evidence(source=f"{dev.sysfs_path}/product", detail=dev.product))
    return evs
