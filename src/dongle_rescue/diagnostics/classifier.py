"""Five-state diagnosis classifier (SPEC §6).

Consumes a DiagnosisInput (device + identification) plus injected environment
views (bound driver, dmesg lines, modprobe.d contents, optional Host).
Priority: UNKNOWN > D (blocked) > C (firmware) > B (unbound) / E (no proven
in-tree claim) > A (working). State C also outranks A when a live dmesg
failure signature exists.

No disk access happens unless a Host is explicitly injected — classification
stays pure and testable (SPEC §20-22).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..firmware.resolver import (
    FirmwareStatus,
    detect_package_managers,
    map_firmware_to_packages,
    recommend_firmware_action,
)
from ..identification.resolver import DiagnosisInput
from ..types import (
    Confidence,
    Diagnosis,
    DiagnosisState,
    RecommendedAction,
)

_FW_FAIL = re.compile(r"Direct firmware load for (.+?) failed with error (-?\d+)")


def _dmesg_firmware_failures(dmesg_lines: Iterable[str]) -> list[tuple[str, int]]:
    out = []
    for line in dmesg_lines:
        m = _FW_FAIL.search(line)
        if m:
            out.append((m.group(1), int(m.group(2))))
    return out


def _blacklisted(module: str | None, modprobe_d: dict[str, str]) -> str | None:
    if not module:
        return None
    for path, content in sorted(modprobe_d.items()):
        for line in content.splitlines():
            stripped = line.split("#")[0].strip()
            if stripped in (f"blacklist {module}", f"install {module} /bin/false"):
                return path
    return None


def _kb_entry_for(chipset: str, kb: dict) -> dict | None:
    for entry in kb.get("chipsets", []):
        if entry.get("chipset") == chipset:
            return entry
    return None


def classify(
    identification: DiagnosisInput,
    *,
    bound_driver: str | None,
    dmesg_lines: Iterable[str],
    modprobe_d: dict[str, str],
    host=None,
    managers: tuple[str, ...] | None = None,
    kb: dict | None = None,
) -> Diagnosis:
    from ..firmware.resolver import load_chipset_kb

    res = identification
    dev = res.dev
    chipset_id = res.chipset_id
    candidates = list(res.candidates)
    kb = kb if kb is not None else load_chipset_kb()
    entry = _kb_entry_for(chipset_id.chipset, kb)
    failures = _dmesg_firmware_failures(list(dmesg_lines))

    primary = bound_driver or (candidates[0].module if candidates else None)

    def ev(*extra) -> tuple:
        return tuple(list(chipset_id.evidence) + list(extra))

    # ---- UNKNOWN device: manual chip id path (SPEC §11) ----
    if chipset_id.chipset == "UNKNOWN" and not candidates:
        return Diagnosis(
            device=dev,
            identification=chipset_id,
            driver_candidates=(),
            firmware=(),
            state=DiagnosisState.UNKNOWN_DEVICE,
            confidence=Confidence.UNKNOWN,
            recommended_action=RecommendedAction(
                kind="manual_chip_id",
                explanation=(
                    "The chipset could not be determined with sufficient "
                    "confidence. Inspect the printed chip marking on the board "
                    "and rerun with `dongle-rescue identify --chip <name>`."
                ),
                safe_for_automation=False,
                evidence=tuple(chipset_id.evidence),
            ),
            evidence=tuple(chipset_id.evidence),
        )

    # ---- D: module blocked ----
    blocked_by = _blacklisted(primary, modprobe_d)
    if blocked_by:
        return Diagnosis(
            device=dev,
            identification=chipset_id,
            driver_candidates=tuple(candidates),
            firmware=(),
            state=DiagnosisState.D_MODULE_BLOCKED,
            confidence=Confidence.CONFIRMED,
            recommended_action=RecommendedAction(
                kind="unblock_module",
                explanation=(
                    f"{primary} is blocked by {blocked_by}. Remove or comment "
                    f"the block after verifying why it was added."
                ),
                commands=(f"# inspect: grep -n '{primary}' {blocked_by}",),
                requires_root=True,
                safe_for_automation=False,
                evidence=ev(),
            ),
            evidence=ev(),
        )

    # ---- C: firmware missing (dmesg failure matching a KB-declared file,
    #      or disk absence when a Host is injected) ----
    fw_file: str | None = None
    if entry:
        declared = {f.rsplit("/", 1)[-1]: f for f in entry.get("firmware", [])}
        for failed_path, _err in failures:
            base = failed_path.rsplit("/", 1)[-1]
            if base in declared:
                fw_file = declared[base]
                break
        if fw_file is None and host is not None:
            for rel in entry.get("firmware", [])[:1]:
                from ..firmware.resolver import check_firmware_presence

                st = check_firmware_presence(host, primary or "?", rel)
                if st.installed is False:
                    fw_file = rel
                break

    if fw_file is not None:
        st = FirmwareStatus(
            module=primary or "?",
            normalized_path=fw_file,
            installed=False,
            found_form=None,
        )
        st.mapping = map_firmware_to_packages(kb, fw_file)
        action = recommend_firmware_action(
            st, managers=managers or detect_package_managers()
        )
        return Diagnosis(
            device=dev,
            identification=chipset_id,
            driver_candidates=tuple(candidates),
            firmware=(),
            state=DiagnosisState.C_FIRMWARE_MISSING,
            confidence=Confidence.CONFIRMED,
            recommended_action=action,
            evidence=ev(*action.evidence),
        )

    alias_candidates = [c for c in candidates if c.source == "modules.alias"]

    # ---- unbound: B vs E ----
    if not bound_driver:
        if alias_candidates:
            feasible = bool(entry and entry.get("new_id_feasible"))
            if feasible:
                action = RecommendedAction(
                    kind="bind_new_id",
                    explanation=(
                        f"The claiming driver ({alias_candidates[0].module}) "
                        f"accepts dynamic IDs; this device ID can be bound "
                        f"legitimately and persisted."
                    ),
                    safe_for_automation=False,
                    evidence=ev(),
                )
            else:
                action = RecommendedAction(
                    kind="diagnose_only",
                    explanation=(
                        "The claiming driver rejects dynamic IDs "
                        "(no_dynamic_id=1), so no legitimate local bind "
                        "exists; use the vendor reference channel for this "
                        "chipset. The tool points, never forces."
                    ),
                    commands=(),
                    safe_for_automation=False,
                    evidence=ev(),
                )
            return Diagnosis(
                device=dev,
                identification=chipset_id,
                driver_candidates=tuple(candidates),
                firmware=(),
                state=DiagnosisState.B_ID_UNBOUND,
                confidence=Confidence.HIGH_CONFIDENCE,
                recommended_action=action,
                evidence=ev(),
            )
        has_capability_detail = bool(
            entry
            and (
                entry.get("new_id_modules")
                or entry.get("preferred_module")
                or entry.get("new_id_feasible") is False
            )
        )
        if has_capability_detail:
            feasible = bool(entry and entry.get("new_id_feasible"))
            if feasible:
                module_hint = entry.get("preferred_module") or (
                    entry.get("new_id_modules") or ["the driver"]
                )[0]
                action = RecommendedAction(
                    kind="bind_new_id",
                    explanation=(
                        f"{chipset_id.chipset} is identified and its driver "
                        f"family accepts dynamic IDs; the ID can be bound "
                        f"after loading {module_hint}."
                    ),
                    commands=(),
                    safe_for_automation=False,
                    evidence=ev(),
                )
            else:
                action = RecommendedAction(
                    kind="diagnose_only",
                    explanation=(
                        "The claiming driver family rejects dynamic IDs "
                        "(no_dynamic_id=1); no legitimate local bind exists."
                    ),
                    commands=(),
                    safe_for_automation=False,
                    evidence=ev(),
                )
            return Diagnosis(
                device=dev,
                identification=chipset_id,
                driver_candidates=tuple(candidates),
                firmware=(),
                state=DiagnosisState.B_ID_UNBOUND,
                confidence=Confidence.HIGH_CONFIDENCE,
                recommended_action=action,
                evidence=ev(),
            )
        return Diagnosis(
            device=dev,
            identification=chipset_id,
            driver_candidates=tuple(candidates),
            firmware=(),
            state=DiagnosisState.E_NO_INTREE_DRIVER,
            confidence=chipset_id.confidence,
            recommended_action=RecommendedAction(
                kind="out_of_tree_pointer",
                explanation=(
                    f"No in-tree kernel alias claims {chipset_id.chipset} in "
                    f"this kernel tree; in-tree support is not proven. "
                    f"Out-of-tree drivers are never installed automatically."
                ),
                safe_for_automation=False,
                evidence=ev(),
            ),
            evidence=ev(),
        )

    # ---- bound: C-on-live-scar outranks A ----
    if failures:
        return Diagnosis(
            device=dev,
            identification=chipset_id,
            driver_candidates=tuple(candidates),
            firmware=(),
            state=DiagnosisState.C_FIRMWARE_MISSING,
            confidence=Confidence.PROBABLE,
            recommended_action=RecommendedAction(
                kind="install_firmware_package",
                explanation=(
                    f"A firmware request failed on this boot (dmesg); inspect "
                    f"the cited log lines before any reinstall."
                ),
                network_required=True,
                requires_root=True,
                safe_for_automation=False,
                evidence=ev(),
            ),
            evidence=ev(),
        )

    return Diagnosis(
        device=dev,
        identification=chipset_id,
        driver_candidates=tuple(candidates),
        firmware=(),
        state=DiagnosisState.A_WORKING,
        confidence=Confidence.CONFIRMED,
        recommended_action=RecommendedAction(
            kind="no_action",
            explanation=(
                f"{bound_driver} is bound and no failure signature was found."
            ),
            evidence=ev(),
        ),
        evidence=ev(),
    )
