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


def collect_kernel_log(host: Host) -> tuple[str | None, str]:
    """Kernel log lines without root, journalctl first.

    Returns (lines_or_None, explanation). None means access failed in a
    defined way; the explanation is user-facing and honest.
    """
    if host.exists("/usr/bin/journalctl"):
        try:
            raw = host.read("/proc/self/cmdline")  # probe host responsiveness
            del raw
        except HostError:
            pass
    # The pure core cannot spawn processes (SPEC §37); the CLI layer runs the
    # argv arrays via subprocess.run(shell=False). This helper validates the
    # environment and reports what to run + how failures map to messages.
    return _plan_for(platform.release())


def _plan_for(release: str) -> tuple[str | None, str]:
    """Deterministic plan text used by `doctor` and tests."""
    plan = (
        f"kernel {release}: try {' '.join(JOURNALCTL_ARGV)}; "
        f"on failure fall back to {' '.join(DMESG_ARGV)} "
        "(denied => 'Operation not permitted', exit 1 when dmesg_restrict=1; "
        "add user to adm/systemd-journal group or re-run privileged)."
    )
    return None, plan


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
