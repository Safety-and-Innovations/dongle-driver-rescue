"""Functional verification after repair (SPEC §25).

Verdict semantics:
- ``HARDWARE_FUNCTIONAL``: every check passed AND no critical error lines.
- ``NOT_FUNCTIONAL``: at least one check failed.
- ``UNKNOWN``: a host read failed mid-check — honesty over optimism (SPEC §37).

Wi-Fi checks: interface present → driver bound → firmware loaded (dmesg
arbitration) → no critical errors. Bluetooth: hci adapter → driver bound →
firmware loaded. Scan/link tests need a live radio and stay out of V1's pure
core; the report marks them as not_run when requested offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..host import Host, HostError

_FW_FAIL = re.compile(r"Direct firmware load for (.+?) failed with error (-?\d+)")

_WIFI = "wifi"
_BT = "bt"


@dataclass(frozen=True)
class CheckResult:
    """One verification step with its evidence source."""

    name: str
    passed: bool | None  # None = indeterminate (host failure)
    detail: str
    source: str


@dataclass(frozen=True)
class VerificationReport:
    kind: str
    verdict: str  # HARDWARE_FUNCTIONAL | NOT_FUNCTIONAL | UNKNOWN
    checks: tuple[CheckResult, ...] = field(default_factory=tuple)
    critical_errors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "verdict": self.verdict,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail,
                 "source": c.source}
                for c in self.checks
            ],
            "critical_errors": list(self.critical_errors),
        }


def _read(host: Host, path: str) -> str | None:
    try:
        return host.read(path).strip() or None
    except (HostError, OSError):
        return None


def verify_device(
    host: Host,
    *,
    kind: str,
    sysfs_iface: str,
    dmesg_lines: list[str] | None = None,
    netdev_hint: str | None = None,
) -> VerificationReport:
    if kind not in (_WIFI, _BT):
        raise ValueError(f"unknown device kind: {kind!r}")

    dmesg_lines = list(dmesg_lines or [])
    failures = [l for l in dmesg_lines if _FW_FAIL.search(l)]
    criticals = [
        l for l in dmesg_lines
        if re.search(r"device descriptor read|Lockdown:|module verification failed", l)
    ]

    checks: list[CheckResult] = []

    def add(name: str, passed: bool | None, detail: str, source: str) -> None:
        checks.append(CheckResult(name, passed, detail, source))

    # ---- adapter / interface presence ----
    if kind == _WIFI:
        iface_name, iface_src = _wifi_iface(host, netdev_hint)
        add("interface_present", iface_name is not None,
            f"netdev {iface_name}" if iface_name else "no netdev with phy80211",
            "/sys/class/net/*/phy80211/name")
        adapter_ok = iface_name is not None
    else:
        hci = _bt_adapter(host)
        add("hci_adapter_present", hci is not None,
            f"adapter {hci}" if hci else "no /sys/class/bluetooth/hci*",
            "/sys/class/bluetooth/hci*/address")
        adapter_ok = hci is not None

    # ---- driver bound ----
    drv = _read(host, sysfs_iface + "/driver")
    add("driver_bound", bool(drv),
        f"bound to {drv}" if drv else f"no driver bound at {sysfs_iface}",
        sysfs_iface + "/driver")

    # ---- firmware loaded (dmesg arbitration; SPEC §9 chain closes in logs) ----
    fw_failed = bool(failures)
    add("firmware_loaded", (not fw_failed) and adapter_ok and bool(drv),
        ("firmware failure in log" if fw_failed
         else "no firmware failure signature for this session"),
        "dmesg: 'Direct firmware load ... failed'")

    # ---- critical errors ----
    if criticals:
        add("no_critical_errors", False,
            f"{len(criticals)} critical line(s)", "dmesg")
    else:
        add("no_critical_errors", True, "none found", "dmesg")

    if any(c.passed is None for c in checks):
        verdict = "UNKNOWN"
    elif all(c.passed for c in checks):
        verdict = "HARDWARE_FUNCTIONAL"
    else:
        verdict = "NOT_FUNCTIONAL"
    return VerificationReport(kind=kind, verdict=verdict,
                              checks=tuple(checks),
                              critical_errors=tuple(criticals))


def _wifi_iface(host: Host, hint: str | None) -> tuple[str | None, str]:
    base = "/sys/class/net"
    try:
        names = host.listdir(base)
    except (HostError, OSError):
        return None, base
    candidates = [hint] if hint else names
    for n in sorted(candidates):
        phy = f"{base}/{n}/phy80211/name"
        if _read(host, phy):
            return n, phy
    return None, base


def _bt_adapter(host: Host) -> str | None:
    base = "/sys/class/bluetooth"
    try:
        names = host.listdir(base)
    except (HostError, OSError):
        return None
    for n in sorted(names):
        if _read(host, f"{base}/{n}/address"):
            return n
    return None
