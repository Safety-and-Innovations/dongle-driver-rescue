"""Windows read-only diagnostics: command generators + pnputil parser.

This module NEVER executes PowerShell on Linux (SPEC §4). It only builds
documented, whitelisted command strings (windows-diagnostics.md §5.2) and
parses their captured text output. All input is untrusted (ADR 0002 S6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Whitelisted pnputil verbs for the diagnostic layer only.
_ALLOWED_PNPUTIL_FLAGS = ("/connected", "/deviceids", "/instanceid")

#: Device Instance ID grammar: USB\VID_xxxx&PID_yyyy[&MI_nn]\suffix or generic.
_INSTANCE_ID_OK = re.compile(r"^[A-Za-z0-9\\&_.\-]+$")


def build_pnputil_enum_devices_cmd(instance_id: str | None = None) -> str:
    """Whitelisted read-only enumeration command."""
    cmd = "pnputil /enum-devices /connected /deviceids"
    if instance_id is not None:
        if not _INSTANCE_ID_OK.match(instance_id) or "\n" in instance_id or '"' in instance_id.replace('\\"', ""):
            raise ValueError("invalid instance id")
        if any(c in instance_id for c in ('"', "&", "|", "<", ">", "%", "!", "$")):
            # '&' appears inside legit USB instance ids; allow it ONLY as part
            # of the VID/PID/MI separators pattern matched above.
            if not re.fullmatch(r"USB\\VID_[0-9A-Fa-f]{4}&PID_[0-9A-Fa-f]{4}(\\[^\s]+)?", instance_id):
                raise ValueError("invalid instance id")
        cmd += f' /instanceid "{instance_id}"'
    return cmd


def build_get_pnpdevice_cmd() -> str:
    """Read-only PowerShell pipeline (observe only)."""
    return (
        "Get-PnpDevice -PresentOnly "
        "| Where-Object InstanceId -like 'USB\\*'"
    )


@dataclass(frozen=True)
class WindowsDevice:
    instance_id: str | None
    description: str | None
    hardware_ids: tuple[str, ...]
    compatible_ids: tuple[str, ...]
    problem_code: int | None
    status: str | None


_FIELD = re.compile(r"^([A-Za-z][A-Za-z0-9 ]*?):\t+(.*)$")


def _norm_hwid(value: str) -> str:
    return value.strip().upper()


def parse_pnputil_output(text: str) -> list[WindowsDevice]:
    """Parse `pnputil /enum-devices /deviceids` text into devices.

    Deterministic: preserves file order; entries without an Instance ID are
    skipped (hostile/garbage blocks never crash the parser).
    """
    devices: list[WindowsDevice] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current and current.get("instance_id"):
            devices.append(
                WindowsDevice(
                    instance_id=current["instance_id"],
                    description=current.get("description"),
                    hardware_ids=tuple(current.get("hwids") or ()),
                    compatible_ids=tuple(current.get("compats") or ()),
                    problem_code=current.get("problem"),
                    status=current.get("status"),
                )
            )
        current = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            flush()
            continue
        m = _FIELD.match(line)
        if not m:
            continue  # garbage line without tabs -> ignored
        key, value = m.group(1).strip(), m.group(2).strip()
        if key == "Instance ID":
            flush()
            current = {"instance_id": value}
        elif current is None:
            continue
        elif key == "Device Description":
            current["description"] = value
        elif key == "Hardware IDs":
            current["hwids"] = [
                _norm_hwid(v) for v in value.split(" ") if v.strip()
            ]
        elif key == "Compatible IDs":
            current["compats"] = [
                _norm_hwid(v) for v in value.split(" ") if v.strip()
            ]
        elif key == "Problem Code":
            digits = "".join(re.findall(r"\d+", value))
            current["problem"] = int(digits) if digits else None
        elif key == "Status":
            current["status"] = value
    flush()
    return devices
