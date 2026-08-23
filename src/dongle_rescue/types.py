"""Core domain types shared by every module.

Contracts (ADR 0003):
- Every derived fact carries an Evidence trail; conclusions without evidence
  are not constructible in the diagnosis flow.
- Confidence is a closed five-level scale (SPEC §28).
- Output must be deterministic: stable ordering, no wall-clock in comparable
  fields (SPEC §27, §34-D4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Confidence(str, Enum):
    """Closed confidence scale. Never invent a sixth level."""

    CONFIRMED = "CONFIRMED"
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    UNKNOWN = "UNKNOWN"


class DiagnosisState(str, Enum):
    """Five-state diagnostic machine (SPEC §6)."""

    A_WORKING = "A"  # correct driver, device working -> NO_ACTION_REQUIRED
    B_ID_UNBOUND = "B"  # driver exists, VID:PID not associated
    C_FIRMWARE_MISSING = "C"  # firmware requested and absent
    D_MODULE_BLOCKED = "D"  # blacklist / conflict / secure boot
    E_NO_INTREE_DRIVER = "E"  # no in-tree driver for chipset
    UNKNOWN_DEVICE = "UNKNOWN"  # chipset not determinable (SPEC §11)


@dataclass(frozen=True)
class Evidence:
    """One verifiable observation backing a conclusion.

    `source` names where the fact came from (file path, command line,
    package metadata). `detail` carries the raw observation. Deterministic:
    no timestamps here.
    """

    source: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "detail": self.detail}


class UsbDevice:
    """Layer-1/2 identity of one USB device (SPEC §7).

    Built only from validated reads of sysfs (or fixtures mirroring it).
    vid/pid are 4-digit lowercase hex without 0x prefix. bcd_device is a
    4-hex-digit string as reported by the kernel.
    """

    __slots__ = (
        "sysfs_path",
        "vid",
        "pid",
        "bcd_device",
        "device_class",
        "device_subclass",
        "device_protocol",
        "manufacturer",
        "product",
        "serial",
        "modalias",
    )

    def __init__(
        self,
        *,
        sysfs_path: str,
        vid: str,
        pid: str,
        bcd_device: str,
        device_class: int,
        device_subclass: int,
        device_protocol: int,
        manufacturer: str | None,
        product: str | None,
        serial: str | None,
        modalias: str | None,
    ) -> None:
        _require_hex4(vid, "vid")
        _require_hex4(pid, "pid")
        _require_hex4(bcd_device, "bcd_device")
        object.__setattr__(self, "sysfs_path", sysfs_path)
        object.__setattr__(self, "vid", vid.lower())
        object.__setattr__(self, "pid", pid.lower())
        object.__setattr__(self, "bcd_device", bcd_device.lower())
        object.__setattr__(self, "device_class", device_class)
        object.__setattr__(self, "device_subclass", device_subclass)
        object.__setattr__(self, "device_protocol", device_protocol)
        object.__setattr__(self, "manufacturer", manufacturer)
        object.__setattr__(self, "product", product)
        object.__setattr__(self, "serial", serial)
        object.__setattr__(self, "modalias", modalias)

    @property
    def vid_pid(self) -> str:
        return f"{self.vid}:{self.pid}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sysfs_path": self.sysfs_path,
            "vid": self.vid,
            "pid": self.pid,
            "bcd_device": self.bcd_device,
            "b_device_class": self.device_class,
            "b_device_subclass": self.device_subclass,
            "b_device_protocol": self.device_protocol,
            "manufacturer": self.manufacturer,
            "product": self.product,
            "serial": self.serial,
            "modalias": self.modalias,
        }


def _require_hex4(value: str, name: str) -> None:
    if len(value) != 4 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ValueError(f"{name} must be exactly 4 hex digits, got {value!r}")


def require_module_name(value: str) -> str:
    """Kernel module name grammar (ADR 0002 S3). Raises ValueError.

    O primeiro caractere precisa ser alfanumerico. A gramatica anterior era
    ``[a-z0-9_-]{1,64}``, que aceitava nome iniciado por hifen (``-rf``,
    ``--force``): usado como ARGUMENTO de comando, um nome desses deixa de ser
    nome e vira flag. Nenhum modulo real do kernel comeca com hifen, entao
    fechar isso nao custa nada.
    """
    import re

    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise ValueError(f"invalid kernel module name: {value!r}")
    return value


def require_firmware_path(value: str) -> str:
    """Firmware relative path grammar (ADR 0002 S3): no .., no leading /.

    Returns the normalized relative path usable under any firmware root.
    """
    import posixpath

    if not value or value.startswith("/") or "\\" in value:
        raise ValueError(f"invalid firmware path: {value!r}")
    norm = posixpath.normpath(value)
    if norm.startswith("..") or norm == "." or "\x00" in norm:
        raise ValueError(f"invalid firmware path: {value!r}")
    if any(part in ("", ".", "..") for part in norm.split("/")):
        raise ValueError(f"invalid firmware path: {value!r}")
    return norm


@dataclass(frozen=True)
class DriverCandidate:
    """One module that claims (via modules.alias or chipset KB) this device."""

    module: str
    source: str  # e.g. "modules.alias", "chipsets.json"
    confidence: Confidence
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FirmwareRequirement:
    """A firmware file a module may request (modinfo -F firmware)."""

    module: str
    firmware_path: str  # validated relative path
    installed: bool | None  # None = could not determine
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ChipsetId:
    """Consolidated identification result (SPEC §7-§8, ADR 0003 D5)."""

    chipset: str  # canonical name, e.g. "RTL8811CU"; "UNKNOWN" when unresolved
    family: str  # vendor family, e.g. "realtek-wifi", "csr-bt"
    confidence: Confidence
    revision_note: str | None = None  # silicon revision distinction when known
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RecommendedAction:
    """What the tool recommends; never executed without explicit consent."""

    kind: str  # "no_action" | "bind_new_id" | "install_firmware_package" |
    #          "unblock_module" | "manual_chip_id" | "out_of_tree_pointer" ...
    explanation: str
    commands: tuple[str, ...] = field(default_factory=tuple)  # dry-run display only
    requires_root: bool = False
    network_required: bool = False
    safe_for_automation: bool = False  # SPEC §37: prefer refusing automation
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Diagnosis:
    """Complete diagnosis output for one device (SPEC §27 shape)."""

    device: UsbDevice
    identification: ChipsetId
    driver_candidates: tuple[DriverCandidate, ...]
    firmware: tuple[FirmwareRequirement, ...]
    state: DiagnosisState
    confidence: Confidence
    recommended_action: RecommendedAction
    evidence: tuple[Evidence, ...]

    def to_dict(self) -> dict[str, Any]:
        from . import SCHEMA_VERSION

        return {
            "schema_version": SCHEMA_VERSION,
            "device": self.device.to_dict(),
            "identification": {
                "chipset": self.identification.chipset,
                "family": self.identification.family,
                "confidence": self.identification.confidence.value,
                "revision_note": self.identification.revision_note,
                "evidence": [e.to_dict() for e in self.identification.evidence],
            },
            "evidence": [e.to_dict() for e in self.evidence],
            "driver_candidates": [
                {
                    "module": c.module,
                    "source": c.source,
                    "confidence": c.confidence.value,
                    "evidence": [e.to_dict() for e in c.evidence],
                }
                for c in self.driver_candidates
            ],
            "firmware": [
                {
                    "module": f.module,
                    "firmware_path": f.firmware_path,
                    "installed": f.installed,
                    "evidence": [e.to_dict() for e in f.evidence],
                }
                for f in self.firmware
            ],
            "diagnosis": {
                "state": self.state.value,
                "confidence": self.confidence.value,
            },
            "recommended_action": {
                "kind": self.recommended_action.kind,
                "explanation": self.recommended_action.explanation,
                "commands": list(self.recommended_action.commands),
                "requires_root": self.recommended_action.requires_root,
                "network_required": self.recommended_action.network_required,
                "safe_for_automation": self.recommended_action.safe_for_automation,
                "evidence": [e.to_dict() for e in self.recommended_action.evidence],
            },
        }


@dataclass(frozen=True)
class TransactionRecord:
    """Repair transaction (SPEC §24). Rollback must be idempotent."""

    transaction_id: str
    before_state: dict[str, Any]
    change: dict[str, Any]
    after_state: dict[str, Any]
    rollback_action: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "before_state": self.before_state,
            "change": self.change,
            "after_state": self.after_state,
            "rollback_action": self.rollback_action,
        }
