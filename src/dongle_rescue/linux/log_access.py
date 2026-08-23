"""Log collection + reboot-pending detection — CONFIRMED on this host
(Ubuntu 24.04 arm64 VM, 2026-08-23) per research/research_log_access.md.

Observed facts (all ran as the unprivileged 'ubuntu' user):
- /proc/sys/kernel/dmesg_restrict = 1
- dmesg(1): "read kernel buffer failed: Operation not permitted", exit code 1
- journalctl -k --no-pager: WORKS (exit 0) — user in 'adm' group
- /var/run/reboot-required exists (empty marker file, root-owned)
- /lib/modules holds 6.17.0-{1018,1019,1020}-oracle; uname = ...1018-oracle;
  dpkg has linux-image for 1018 and 1020 → reboot pending (1020 not running)

Strategy (ADR 0002 S1/S2): journalctl first (works unprivileged on Ubuntu/
Fedora defaults), dmesg fallback with defined HostError mapping. Never a
shell; argv arrays only.
"""

from __future__ import annotations

import platform

from ..host import Host, HostError

JOURNALCTL_ARGV = ["/usr/bin/journalctl", "-k", "--no-pager", "-o", "short"]
DMESG_ARGV = ["/usr/bin/dmesg"]

_DMESG_DENIED = "Operation not permitted"


def plan_kernel_log_access(host: Host, release: str | None = None) -> tuple[bool, str]:
    """Descreve COMO obter o log do kernel nesta máquina, sem executar nada.

    O núcleo puro não pode criar processos (SPEC §37): quem roda os argv é a
    camada de CLI. Esta função inspeciona o ambiente e devolve
    ``(journalctl_disponivel, texto_do_plano)``.

    Renomeada de ``collect_kernel_log``: aquele nome prometia coletar o log,
    mas a função devolvia ``None`` em todos os caminhos e não era chamada por
    nada — nem produção, nem teste (confirmado por cobertura: as linhas nunca
    executavam). Trazia ainda uma sonda inútil que lia ``/proc/self/cmdline``
    e descartava o resultado com ``del``.
    """
    alvo = release or platform.release()
    tem_journalctl = False
    try:
        tem_journalctl = bool(host.exists(JOURNALCTL_ARGV[0]))
    except (HostError, OSError):
        tem_journalctl = False

    if tem_journalctl:
        plano = (
            f"kernel {alvo}: rode {' '.join(JOURNALCTL_ARGV)}; "
            f"se falhar, caia para {' '.join(DMESG_ARGV)} "
            f"(negado => '{_DMESG_DENIED}', saída 1 quando dmesg_restrict=1; "
            "entre no grupo adm/systemd-journal ou repita com privilégio)."
        )
    else:
        plano = (
            f"kernel {alvo}: {JOURNALCTL_ARGV[0]} não encontrado; "
            f"use {' '.join(DMESG_ARGV)} "
            f"(negado => '{_DMESG_DENIED}', saída 1 quando dmesg_restrict=1; "
            "repita com privilégio para ler o buffer do kernel)."
        )
    return tem_journalctl, plano


def reboot_pending(host: Host, running_release: str | None = None) -> tuple[bool | None, str]:
    """Detect installed-but-not-running kernel (linux-kernel.md §6 item 1).

    Signals ranked by false-positive risk:
      1. /var/run/reboot-required exists (Ubuntu marker) — coarse but rare FP.
      2. A linux-image newer than uname -r present in /lib/modules/ — needs
         version comparison to avoid counting older kernels.
      Returns (None, reason) when nothing can be determined.
    """
    running = running_release or platform.release()
    marker = "/var/run/reboot-required"
    try:
        has_marker = host.exists(marker)
    except (HostError, OSError):
        has_marker = False

    modules_root = "/lib/modules"
    try:
        installed = set(host.listdir(modules_root))
    except (HostError, OSError):
        installed = set()

    newer = sorted(
        rel for rel in installed
        if rel != running and _version_gt(rel, running)
    )
    if newer:
        detail = (
            f"installed kernel(s) {', '.join(newer)} newer than running "
            f"{running}; driver/firmware may exist only in the future tree"
        )
        return True, detail
    if has_marker:
        return True, "reboot-required marker present"
    if installed:
        return False, f"running {running} is the newest installed kernel"
    return None, f"cannot list {modules_root}"


def _version_gt(candidate: str, baseline: str) -> bool:
    """Numeric-aware comparison of kernel release strings (abipkg suffix kept).

    6.17.0-1020-oracle > 6.17.0-1018-oracle. Non-comparable strings never
    claim superiority (conservative: no false reboot-pending).
    """
    def key(rel: str):
        head = rel.split("-")[0]
        parts = []
        for chunk in head.split("."):
            parts.append(int(chunk) if chunk.isdigit() else -1)
        abinum = -1
        tail = rel.split("-")
        if len(tail) > 1 and tail[1].isdigit():
            abinum = int(tail[1])
        return (*parts, abinum)

    try:
        return key(candidate) > key(baseline)
    except (ValueError, IndexError):
        return False
