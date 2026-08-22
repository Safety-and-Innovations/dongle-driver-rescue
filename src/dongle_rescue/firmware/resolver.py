"""Firmware resolution pipeline (SPEC §9, state C).

Chain per docs/research/linux-kernel.md §6 (CONFIRMED sources): the dmesg
line names the exact file requested; data/chipsets.json maps file -> distro
package (verified against real .debs, mediatek-atheros.md §6); the action is
display-only and never automated (ADR 0002 S4-S5, SPEC §37).
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ..host import Host
from ..types import Confidence, Evidence, RecommendedAction, require_firmware_path

FIRMWARE_ROOT = "/lib/firmware"

#: Canonical dmesg/request_firmware failure message (fw_main.c:903).
_DMESG_FW = re.compile(r"Direct firmware load for (.+?) failed with error (-?\d+)")

#: Strict grammar for firmware filenames arriving from untrusted logs.
#: Alnum start, then alnum . _ - / only; no '..', no '//', no trailing '/'.
_FW_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")

#: Compressed on-disk forms the kernel firmware loader accepts post-5.19.
_COMPRESSED_FORMS = (".zst", ".xz")


@dataclass(frozen=True)
class FirmwareFailure:
    """One parsed dmesg firmware-load failure."""

    firmware_path: str
    error: int
    line_index: int
    valid: bool
    detail: str


def _fw_name_valid(name: str) -> bool:
    if not name or len(name) > 4096:
        return False
    if not _FW_NAME.fullmatch(name):
        return False
    return ".." not in name and "//" not in name and not name.endswith("/")


def parse_dmesg_firmware_failures(
    lines: Iterable[str],
) -> tuple[FirmwareFailure, ...]:
    """Extract firmware-load failures in input order; hostile names flagged."""
    out: list[FirmwareFailure] = []
    for i, line in enumerate(lines):
        m = _DMESG_FW.search(line)
        if not m:
            continue
        name, err = m.group(1), int(m.group(2))
        if _fw_name_valid(name):
            valid, detail = True, "accepted by firmware name grammar"
        else:
            valid, detail = False, (
                f"rejected by firmware name grammar (untrusted log content)"
            )
        out.append(FirmwareFailure(name, err, i, valid, detail))
    return tuple(out)


@dataclass
class FirmwareStatus:
    """Presence + provenance status for one required firmware file."""

    module: str
    normalized_path: str | None
    installed: bool | None
    found_form: str | None
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)
    failures: tuple[FirmwareFailure, ...] = field(default_factory=tuple)
    mapping: "PackageMapping | None" = None


def _exists_under_root(host: Host, full: str, root: str) -> bool:
    """exists() with symlink containment (ADR 0002 S3)."""
    if not host.exists(full):
        return False
    real = host.resolve_realpath(full)
    return real.startswith(root.rstrip("/") + "/")


def check_firmware_presence(
    host: Host,
    module: str,
    rel_path: str,
    *,
    root: str = FIRMWARE_ROOT,
) -> FirmwareStatus:
    """Is this firmware file present under the firmware root?

    Grammar-rejected requests are indeterminate (None), never a fake False.
    """
    if not _fw_name_valid(rel_path):
        return FirmwareStatus(
            module=module,
            normalized_path=None,
            installed=None,
            found_form=None,
            evidence=(
                Evidence(
                    source="<firmware-name-grammar>",
                    detail=f"path rejected: {rel_path!r}",
                ),
            ),
        )
    canon = require_firmware_path(rel_path)
    base = root.rstrip("/")
    for suffix, form in [("", "raw")] + [(s, s) for s in _COMPRESSED_FORMS]:
        cand = f"{canon}{suffix}"
        full = f"{base}/{cand}"
        if _exists_under_root(host, full, base):
            return FirmwareStatus(
                module=module,
                normalized_path=canon,
                installed=True,
                found_form=form,
                evidence=(Evidence(source=full, detail=f"{cand} present ({form})"),),
            )
    return FirmwareStatus(
        module=module,
        normalized_path=canon,
        installed=False,
        found_form=None,
        evidence=(Evidence(source=f"{base}/{canon}", detail="absent"),),
    )


# ------------------------------------------------------------------ KB lookup


def load_chipset_kb(path: str | Path | None = None) -> dict:
    p = (
        Path(path)
        if path
        else Path(__file__).resolve().parent.parent / "data" / "chipsets.json"
    )
    return json.loads(p.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class PackageMapping:
    chipset: str | None
    packages: tuple[str, ...]
    confidence: Confidence
    evidence: tuple[Evidence, ...]


_PKG_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")


def _clean_pkg_names(names: Iterable[object]) -> tuple[str, ...]:
    out: list[str] = []
    for n in names:
        if isinstance(n, str) and _PKG_NAME.fullmatch(n):
            out.append(n)
    return tuple(out)


def map_firmware_to_packages(kb: dict, rel_path: str) -> PackageMapping:
    """file -> owning chipset -> distro packages, strictly from the KB."""
    base = rel_path.rsplit("/", 1)[-1]
    for c in kb.get("chipsets", []):
        firmwares = c.get("firmware", [])
        hit = any(fw == rel_path or fw.rsplit("/", 1)[-1] == base for fw in firmwares)
        if not hit:
            continue
        ev = tuple(
            Evidence(source=e["source"], detail=e["detail"])
            for e in c.get("evidence", [])
            if isinstance(e, dict) and "source" in e and "detail" in e
        ) + (Evidence(source="data/chipsets.json", detail=f"{rel_path} -> {c['chipset']}"),)
        return PackageMapping(
            chipset=c.get("chipset"),
            packages=_clean_pkg_names(c.get("fw_package_debian", [])),
            confidence=Confidence(c.get("confidence", "UNKNOWN")),
            evidence=ev,
        )
    return PackageMapping(None, (), Confidence.UNKNOWN, ())


# ------------------------------------------------------- package manager layer


_MANAGER_CMD = {
    "apt": "apt-get install",
    "dnf": "dnf install",
    "pacman": "pacman -S",
}
_MANAGER_ORDER = ("apt", "dnf", "pacman")


def detect_package_managers(
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str, ...]:
    """Fixed detection order regardless of environment (deterministic)."""
    return tuple(m for m in _MANAGER_ORDER if which(m))


def build_install_command(manager: str, packages: list[str]) -> str:
    """Display-only install command; validates every token (S1/S3)."""
    if manager not in _MANAGER_CMD:
        raise ValueError(f"unsupported package manager: {manager!r}")
    for pkg in packages:
        if not isinstance(pkg, str) or not _PKG_NAME.fullmatch(pkg):
            raise ValueError(f"invalid package name: {pkg!r}")
    return f"{_MANAGER_CMD[manager]} {' '.join(packages)}"


# ------------------------------------------------------------------- decision


def recommend_firmware_action(
    st: FirmwareStatus, *, managers: tuple[str, ...]
) -> RecommendedAction:
    """State-C recommendation. Display-only; never automated (SPEC §37)."""
    if st.installed is True:
        return RecommendedAction(
            kind="no_action",
            explanation=(
                f"Firmware {st.normalized_path} is already present "
                f"(form: {st.found_form})."
            ),
            evidence=st.evidence,
        )
    pkgs = st.mapping.packages if st.mapping else ()
    cited = st.evidence + ((st.mapping.evidence if st.mapping else ()) or ())
    if pkgs:
        if managers:
            cmd: tuple[str, ...] = (
                build_install_command(managers[0], [pkgs[0]]),
            )
            extra = (
                f" Alternatives: {', '.join(pkgs[1:])}." if len(pkgs) > 1 else ""
            )
            explanation = (
                f"Firmware {st.normalized_path} (chipset {st.mapping.chipset}) "
                f"is missing. Install '{pkgs[0]}' via {managers[0]}, then reload "
                f"the module.{extra}"
            )
        else:
            cmd = ()
            explanation = (
                f"Firmware {st.normalized_path} (chipset {st.mapping.chipset}) "
                f"is missing. No package manager detected on this host; install "
                f"'{pkgs[0]}' manually from the distribution repository."
            )
        return RecommendedAction(
            kind="install_firmware_package",
            explanation=explanation,
            commands=cmd,
            requires_root=True,
            network_required=True,
            safe_for_automation=False,
            evidence=cited,
        )
    return RecommendedAction(
        kind="manual_package_lookup",
        explanation=(
            f"The owner of firmware {st.normalized_path} is unknown to the "
            f"knowledge base; look it up in the linux-firmware WHENCE index "
            f"of your distribution. Unknown owners are never guessed."
        ),
        safe_for_automation=False,
        evidence=cited,
    )


# --------------------------------------------------------------- orchestrator


def resolve_module_firmware(
    host: Host,
    *,
    module: str,
    firmware_paths: Iterable[str],
    dmesg_lines: Iterable[str],
    which: Callable[[str], str | None] = shutil.which,
    kb: dict | None = None,
) -> list[FirmwareStatus]:
    """Full chain for one module: presence + dmesg scars + package mapping."""
    kb = kb if kb is not None else load_chipset_kb()
    failures = parse_dmesg_firmware_failures(list(dmesg_lines))
    out: list[FirmwareStatus] = []
    for rel in firmware_paths:
        st = check_firmware_presence(host, module=module, rel_path=rel)
        base = rel.rsplit("/", 1)[-1]
        st.failures = tuple(
            f
            for f in failures
            if f.firmware_path == rel or f.firmware_path.rsplit("/", 1)[-1] == base
        )
        st.mapping = map_firmware_to_packages(kb, rel)
        out.append(st)
    return out
