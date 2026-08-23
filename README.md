# Dongle Driver Rescue

Deterministic diagnostician and recovery tool for USB Wi-Fi/Bluetooth dongles
on Linux (Windows read-only diagnostics in V1).

> A cheap Chinese Wi-Fi/BT USB dongle barely works on Windows and never works
> on Linux. This tool finds out what the thing **actually is** (chipset, not
> the brand on the box) and what legitimate fix applies — or says plainly that
> it cannot tell.

## Why it is different

It keeps **no proprietary database**. Every Linux system already ships a
complete, kernel-generated map (`/lib/modules/$(uname -r)/modules.alias`,
`modinfo`, WHENCE-indexed firmware metadata). The tool walks that existing
chain — `USB → VID:PID → modalias → module → firmware requirement → dmesg →
package → repair → verify` — cites the evidence for every conclusion, and
answers `UNKNOWN` when the evidence runs out. When it does not know, it says
so. That is the difference from every "driver updater" on the market.

## Five diagnostic states

| State | Meaning | V1 action |
|---|---|---|
| **A** | Correct driver bound, device working | none (`NO_ACTION_REQUIRED`) |
| **B** | Driver exists, this VID:PID is not in its table | dynamic bind via `new_id` where the driver allows it (Realtek `rtl8xxxu` refuses — diagnosed, not forced) |
| **C** | Firmware file missing (`dmesg: Direct firmware load ... failed`) | point to the distro package that contains it |
| **D** | Module blocked (blacklist, Secure Boot, conflict) | identify the block |
| **E** | No in-tree driver for the chipset | say so; point to maintained out-of-tree repos, never auto-install |

## Non-negotiable limits

- No INF editing, no signature bypass, no unsigned drivers, ever.
- No telemetry, no account, no cloud. Network only when resolving package
  metadata, always logged, always switchable off (`--no-network`).
- Never redistributes firmware or drivers — points at official origins.
- Every change is a dry-run plan first, then a transaction with idempotent
  rollback.

## Status

V1 under active development (Python 3.12, stdlib-only core).
See [docs/SPEC.md](docs/SPEC.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
and [docs/adr/](docs/adr/) for design decisions with citations.

### What is done / what is coming

- ✅ Research base complete with embedded evidence:
      [docs/research/](docs/research/) — kernel/firmware chains for the
      MediaTek/Ralink/Atheros targets (`mediatek-atheros.md`: merge windows
      pinned from git.kernel.org — mt76 core 4.16, mt76x0u 4.19, mt76x2u 4.20,
      mt7921u 5.18; real ID collisions documented), Realtek
      (`realtek.md`), firmware supply chain and Windows diagnostics.
- ✅ USB enumeration core and typed models (`src/dongle_rescue/usb/`),
      chipset knowledge base with per-entry confidence
      (`src/dongle_rescue/data/chipsets.json`).
- ✅ Firmware resolver (`dongle_rescue.firmware`): dmesg parsing, presence
      check, package mapping, display-only install commands.
- ✅ Diagnosis engine for states A–E (`dongle_rescue.diagnostics.classifier`)
      and chipset resolution (`dongle_rescue.identification`).
- ✅ Repair planner + append-only transaction journal with content-hash ids
      and a pure rollback planner (`dongle_rescue.repair`).
- ✅ Functional verification layer (`dongle_rescue.verification`): success is
      *hardware functional*, never *installation completed*.
- ✅ Full CLI: `identify | diagnose | repair --dry-run | verify | rollback |
      history | report | doctor`, with JSON output.
- ✅ Fixture tree, failure injection and byte-exact golden outputs.
- ✅ Offensive security audit (S1–S7): 7 critical findings fixed, 45
      regression tests — [docs/SECURITY-AUDIT-2026-08.md](docs/SECURITY-AUDIT-2026-08.md).
- 🔜 Windows repair actions (V1 ships Windows read-only diagnostics).

## Development

> ### ⚠️ Clone and run this repository on Linux (or WSL), never on Windows
>
> The fixture tree reproduces the kernel's sysfs layout, which contains
> directories such as `sys/bus/usb/devices/1-3:1.0`. **The colon is a reserved
> character on NTFS**, so those paths cannot exist on Windows. Git checks them
> out under mangled 8.3 names (`1HIVA8~9.0`), reports the real files as
> *deleted* and the mangled ones as *untracked*.
>
> A `git add -A` in that state **deletes the fixtures from the repository** and
> commits the mangled directories in their place. If you already have a broken
> Windows checkout, discard it and clone again inside WSL — do not try to fix
> it in place.
>
> `tests/conftest.py` fails fast with an explicit message when it detects this,
> instead of producing dozens of confusing errors.

```sh
uv venv --python python3.12 .venv
uv pip install --python .venv/bin/python pytest pytest-cov
PYTHONPATH=src .venv/bin/python -m pytest tests/
PYTHONPATH=src .venv/bin/python -m dongle_rescue.cli.main doctor
PYTHONPATH=src .venv/bin/python -m dongle_rescue.cli.main diagnose --json
```

Without `uv`, the standard library works just as well:

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install pytest pytest-cov
```

## License

MIT — © forg3
