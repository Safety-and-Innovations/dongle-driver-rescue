# Research — kernel log access without root & pending reboot

Date: 2026-08-23 · Experiment host: Ubuntu 24.04 arm64 VM (user
`ubuntu`, groups `adm cdrom sudo dip lxd docker`).

## 1. Observed access matrix (CONFIRMED on this host)

| Command | argv (shell=False) | Result |
|---|---|---|
| dmesg | `/usr/bin/dmesg` | `dmesg: read kernel buffer failed: Operation not permitted`, **exit 1** (`dmesg_restrict=1`) |
| journalctl | `/usr/bin/journalctl -k --no-pager -o short` | works, **exit 0** — user in `adm` group |

Documented rules: `dmesg_restrict=1` requires CAP_SYSLOG; journal reads are
allowed for members of `systemd-journal`/`adm`/`wheel`
(man sd_journal_access / journald.conf). Both binaries live in
`/usr/bin/` here; on split-usr systems they may be in `/bin` (same file).

## 2. Recommended strategy (ADR 0002 S1/S2)

1. Try `/usr/bin/journalctl -k --no-pager -o short` (covers Ubuntu/Fedora/
   Arch with systemd; exit 0 without root for the groups above).
2. Fallback `/usr/bin/dmesg`; denial mapped to HostError with the observed
   message and instruction ("add the user to the adm/systemd-journal group or
   re-run privileged").
3. Never an intermediate shell; literal argv arrays.

## 3. Pending reboot (linux-kernel.md §6 item 1)

Signals, by false-positive risk:

1. **Installed kernel newer than `uname -r`** in `/lib/modules/` — strong
   signal; numeric comparison (abinum included); incomparable strings NEVER
   count as newer (conservative).
   CONFIRMED here: 1018/1019/1020 modules + uname 1018 + dpkg linux-image
   1018/1020 → real pending.
2. **`/var/run/reboot-required`** (empty marker, root-owned) — coarse, but
   rarely a false positive. Present on this host.

## 4. READY FOR IMPLEMENTATION

Implemented in `src/dongle_rescue/linux/log_access.py`:
`JOURNALCTL_ARGV`/`DMESG_ARGV`, `collect_kernel_log()` (deterministic plan
for doctor) and `reboot_pending(host, running_release)` → `(True|False|None,
explanation)`; None = indeterminate (SPEC §37). Tests:
tests/test_log_access.py.
