"""Dry-run repair planner for diagnosis state B (SPEC §23).

Output is a display-only Plan: commands are strings the operator may run, and
the planner itself never executes anything (SPEC §37, ADR 0002 S1/S5). The
persistence file follows research/linux-kernel.md §4: a modprobe.d alias whose
value matches the device modalias pointing at the module.

Feasibility comes from the chipset KB: drivers with ``no_dynamic_id`` (e.g.
rtl8xxxu, realtek.md §1) cannot take new_id -> empty plan + official origin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..types import Confidence, Evidence, UsbDevice
from .transaction import create_transaction

MODPROBE_D_DIR = "/etc/modprobe.d"

_OFFICIAL_ORIGIN = (
    "https://www.kernel.org/ — linux-firmware & in-tree driver sources "
    "(git.kernel.org); distro kernel packages carry the module"
)


@dataclass(frozen=True)
class Plan:
    """SPEC §23 dry-run plan. All fields human-readable; nothing executed."""

    feasible: bool
    what: str = ""
    why: str = ""
    source: str = ""
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)
    confidence: str = ""
    files_affected: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    rollback: str = ""
    persistence_content: str | None = None
    requires_root: bool = True
    safe_for_automation: bool = False  # SPEC §37: refuse automation by default
    executed: bool = False
    transaction: Any = None  # TransactionRecord | None
    official_origin: str | None = None


#: Shared empty-plan instance for infeasible/unknown cases.
EMPTY_PLAN = Plan(
    feasible=False,
    what="no automated repair",
    why="repair not feasible or chipset unknown",
    source="-",
    confidence=Confidence.UNKNOWN.value,
    official_origin=_OFFICIAL_ORIGIN,
)


def _alias_for(dev: UsbDevice, module: str) -> str:
    """modprobe.d alias line matching this device (linux-kernel.md §4)."""
    return (
        f"alias usb:v{dev.vid.upper()}p{dev.pid.upper()}d*dc*dsc*dp*"
        f"icFFiscFFip00in* {module}\n"
    )


def _conf_name(dev: UsbDevice) -> str:
    return f"{MODPROBE_D_DIR}/ddr-{dev.vid}-{dev.pid}.conf"


def plan_state_b(
    *,
    device: UsbDevice,
    kb: dict[str, Any],
    bound_driver: str | None = None,
    loaded_module: str | None = None,
) -> Plan:
    """Build the state-B dry-run plan for one device against the KB."""
    entry = _kb_entry(kb, device, bound_driver)
    if entry is None and (bound_driver or loaded_module):
        # Fallback: the loaded/bound module itself is evidence of chipset
        # association — match the single KB entry declaring that module.
        mod = bound_driver or loaded_module
        hits = [
            e for e in kb.get("chipsets", [])
            if mod in e.get("modules", []) or mod in e.get("new_id_modules", [])
        ]
        if len(hits) == 1:
            entry = hits[0]
    if entry is None:
        return Plan(
            feasible=False,
            what="no automated repair",
            why=(
                f"chipset for {device.vid_pid} is not declared in the "
                f"knowledge base; identification stays UNKNOWN (SPEC §11)"
            ),
            source="chipsets.json",
            confidence=Confidence.UNKNOWN.value,
            official_origin=_OFFICIAL_ORIGIN,
        )

    if not entry.get("new_id_feasible", False):
        notes = entry.get("notes", "")
        return Plan(
            feasible=False,
            what="no automated repair",
            why=(
                f"driver(s) {entry.get('modules')} claim this chipset but do "
                f"not accept dynamic IDs ({notes}); binding by new_id is not "
                f"feasible. Use a driver that supports this ID or update the "
                f"kernel."
            ),
            source=f"chipsets.json[{entry['chipset']}]",
            confidence=entry.get("confidence", "UNKNOWN"),
            evidence=_kb_evidence(entry, device),
            official_origin=_OFFICIAL_ORIGIN,
        )

    candidates = entry.get("new_id_modules") or [
        m for m in entry.get("modules", []) if m != "rtl8xxxu"
    ]
    module = loaded_module if loaded_module in candidates else (
        bound_driver if bound_driver in candidates else None
    )
    if module is None:
        module = candidates[0]
    target = (
        f"/sys/bus/usb/drivers/{module}/new_id"
    )
    vid_pid = f"{device.vid} {device.pid}"
    conf_path = _conf_name(device)
    alias_line = _alias_for(device, module)
    persistence_cmd = (
        f"printf '%s\\n' '{alias_line.rstrip(chr(10))}' | "
        f"sudo tee -a {conf_path}"
    )
    commands = [
        f"echo '{vid_pid}' | sudo tee {target}",
        persistence_cmd,
    ]

    before_state = {
        "kind": "modprobe_d_file",
        "path": conf_path,
        "existed": False,
        "sha256": None,
    }
    after_state = {
        "kind": "modprobe_d_file",
        "path": conf_path,
        "existed": True,
        "content_sha256": _sha256_text(alias_line),
    }

    plan = Plan(
        feasible=True,
        what=(
            f"Bind {device.vid_pid} to module {module} via new_id and persist "
            f"the bind as a modprobe.d alias for reboot survival."
        ),
        why=(
            f"The chipset KB declares {device.vid_pid} as "
            f"{entry['chipset']}, served by {module}, which accepts dynamic "
            f"IDs; no driver is currently bound."
            if bound_driver is None
            else f"The chipset KB declares {device.vid_pid} as "
            f"{entry['chipset']}; module {module} accepts dynamic IDs."
        ),
        source=f"chipsets.json[{entry['chipset']}]; linux-kernel.md §3-§4",
        confidence=entry.get("confidence", Confidence.UNKNOWN.value),
        evidence=_kb_evidence(entry, device),
        files_affected=[conf_path],
        commands=commands,
        rollback=(
            f"Remove {conf_path} (transaction rollback_action remove_file); "
            f"the volatile new_id disappears on reload/reboot."
        ),
        persistence_content=alias_line,
        requires_root=True,
        safe_for_automation=False,
        executed=False,
    )
    plan.transaction.__class__  # keep dataclass frozen; attach below instead
    object.__setattr__(
        plan,
        "transaction",
        create_transaction(
            before=before_state,
            change={
                "op": "create_modprobe_alias",
                "content": alias_line,
                "new_id": vid_pid,
                "driver": module,
            },
            after=after_state,
            rollback_action={"op": "remove_file", "path": conf_path},
        ),
    )
    return plan


def _kb_entry(kb: dict[str, Any], dev: UsbDevice, bound_driver: str | None = None) -> dict[str, Any] | None:
    """KB lookup by explicit usb_ids first, then by VID/PID hex in any
    declared alias string (device modalias carries vXXXXpYYYY)."""
    vid_pid = dev.vid_pid
    prefix = f"v{dev.vid.upper()}p{dev.pid.upper()}"
    for e in kb.get("chipsets", []):
        ids = [i.lower() for i in e.get("usb_ids", [])]
        if vid_pid in ids:
            return e
    for e in kb.get("chipsets", []):
        if any(prefix in str(a) for a in e.get("aliases", [])):
            return e
    return None


def _kb_evidence(entry: dict[str, Any], dev: UsbDevice) -> tuple[Evidence, ...]:
    evs = [
        Evidence(
            source="src/dongle_rescue/data/chipsets.json",
            detail=(
                f"{entry['chipset']}: modules={entry.get('modules')} "
                f"new_id_feasible={entry.get('new_id_feasible')}"
            ),
        ),
        Evidence(
            source="docs/research/linux-kernel.md §3",
            detail="usb_store_new_id accepts 'VID PID' (min 2 fields)",
        ),
    ]
    for e in entry.get("evidence", []):
        evs.append(Evidence(source=str(e.get("source", "")), detail=str(e.get("detail", ""))))
    return tuple(evs)


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
