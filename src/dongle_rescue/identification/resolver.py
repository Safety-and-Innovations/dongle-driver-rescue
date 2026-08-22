"""Chipset identification: SPEC §7 evidence chain over modules.alias + KB."""

from __future__ import annotations

from dataclasses import dataclass

from ..host import Host
from ..linux.modules_alias import match_with_lines, read_alias_lines
from ..types import ChipsetId, Confidence, DriverCandidate, Evidence, UsbDevice


@dataclass(frozen=True)
class DiagnosisInput:
    """Device + identification result, as the classifier consumes it."""

    dev: UsbDevice
    chipset_id: ChipsetId
    candidates: tuple[DriverCandidate, ...]
    missing_link: str | None = None




def _sanitize(value: str | None) -> str | None:
    """Single-line, control-char-free form for Evidence detail fields."""
    if value is None:
        return None
    cleaned = "".join(c for c in value if c.isprintable())
    return cleaned or None


def _kb_entry(kb: dict, vid: str, pid: str) -> dict | None:
    target = f"{vid}:{pid}"
    for entry in kb.get("chipsets", []):
        if target in [str(i).lower() for i in entry.get("usb_ids", [])]:
            return entry
    return None


def resolve_device(
    device: UsbDevice,
    alias_lines: list[str],
    kb: dict,
) -> DiagnosisInput:
    """Layer 2-4 chain: modalias match + KB cross-reference.

    Deterministic; every candidate cites the exact alias row or KB entry.
    """
    vid, pid = device.vid, device.pid
    kb_entry = _kb_entry(kb, vid, pid)

    rows = match_with_lines(device.modalias or "", alias_lines)
    candidates: list[DriverCandidate] = [
        DriverCandidate(
            module=row.module,
            source="modules.alias",
            confidence=Confidence.HIGH_CONFIDENCE,
            evidence=(
                Evidence(
                    source="modules.alias",
                    detail=f"{row.module} claims {device.modalias}: {row.raw.strip()}",
                ),
            ),
        )
        for row in rows
    ]

    if kb_entry is not None:
        claimed = {c.module for c in candidates}
        for module in kb_entry.get("modules", []):
            if module in claimed:
                continue
            candidates.append(
                DriverCandidate(
                    module=module,
                    source="chipsets.json",
                    confidence=Confidence(kb_entry.get("confidence", "PROBABLE")),
                    evidence=(
                        Evidence(
                            source="chipsets.json",
                            detail=(
                                f"KB entry {kb_entry['chipset']} lists module "
                                f"{module} for {vid}:{pid}"
                            ),
                        ),
                    ),
                )
            )
        chipset = ChipsetId(
            chipset=kb_entry["chipset"],
            family=kb_entry.get("family", "unknown"),
            confidence=Confidence(
                "CONFIRMED"
                if rows
                else kb_entry.get("confidence", "HIGH_CONFIDENCE")
            ),
            revision_note=_sanitize(kb_entry.get("notes")),
            evidence=(
                Evidence(
                    source="data/chipsets.json",
                    detail=f"VID:PID {vid}:{pid} -> {kb_entry['chipset']}",
                ),
            )
            + (
                (Evidence(source="modules.alias", detail="kernel alias confirms claim"),)
                if rows
                else ()
            ),
        )
        missing = (
            None
            if rows
            else (
                "VID:PID known to the knowledge base but no kernel alias claims it "
                "in this kernel tree — driver may be absent from this kernel"
            )
        )
        return DiagnosisInput(device, chipset, tuple(candidates), missing)

    if candidates:
        return DiagnosisInput(
            device,
            ChipsetId(
                chipset="UNKNOWN",
                family="unknown",
                confidence=Confidence.PROBABLE,
                revision_note=None,
                evidence=(
                    Evidence(
                        source="modules.alias",
                        detail=(
                            f"kernel claims {vid}:{pid} via "
                            f"{', '.join(dict.fromkeys(c.module for c in candidates))} "
                            f"but the chipset name is not in the knowledge base"
                        ),
                    ),
                ),
            ),
            tuple(candidates),
            "kernel-level claim exists; human-readable chipset name unknown",
        )

    return DiagnosisInput(
        device,
        ChipsetId(
            chipset="UNKNOWN",
            family="unknown",
            confidence=Confidence.UNKNOWN,
            evidence=(
                Evidence(
                    source="modules.alias+chipsets.json",
                    detail=(
                        f"no alias and no KB entry for {vid}:{pid}; "
                        f"manual identification required (SPEC §11)"
                    ),
                ),
            ),
        ),
        (),
        "no evidence at any layer for this VID:PID",
    )


def load_alias_for_running_kernel(host: Host, release: str) -> list[str]:
    try:
        return read_alias_lines(host, release)
    except Exception:
        return []
