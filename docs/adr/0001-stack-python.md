# ADR 0001 — V1 language and stack

- **Status:** Accepted
- **Date:** 2026-08-22
- **Responsible:** forg3
- **Deciders:** Lead Agent; review by the Milestone 3 gate

## Context

The SPEC (§31) requires choosing a stack based on: security, OS integration,
maintenance, portability, binary-generation capability, test ease, and
native-API integration — not personal preference. Candidates evaluated:
Rust, Go, Python, C/C++.

Facts verified on the reference host (Ubuntu 24.04, kernel 6.17):

| Fact | Evidence |
|---|---|
| Rust/Go toolchains missing | `rustc`, `cargo`, `go` not installed; installing via rustup/golang would add a network dependency to the build cycle |
| Entire domain toolchain is executable from Python | `lsusb`, `modinfo`, `journalctl`, `udevadm`, `modprobe`, `iw`, `bluetoothctl` are OS binaries that the tool invokes and whose output it parses |
| Python 3.12 present | `python3 --version` = 3.12.3 |
| All relevant "native API" is sysfs + netlink + text logs | `/sys/bus/usb/devices/*`, `/lib/modules/$(uname -r)/modules.alias`, dmesg — access via stdlib (`os`, `pathlib`, `subprocess`) |

Analysis by criterion:

- **OS integration:** technical tie among all four languages; all call
  the same binaries and read the same files.
- **Binary-generation capability:** Rust/Go produce a single binary; Python requires
  PyInstaller/Shiv (acceptable for a technician tool).
- **Security:** language does not eliminate this product's dominant risk class
  (command injection, path traversal in log-sourced firmware names, hostile-input
  parsing). The control is at the design layer — see ADR 0002.
- **Test/fixture ease:** pytest with parametrization over synthetic
  sysfs fixtures is the most direct path to requirement §20 (testing without
  physical hardware) and §22 (failure injection).
- **Maintenance:** the real team is lean; a mature parse/CLI ecosystem matters.

## Decision

**Python 3.12+ (stdlib only in V1 for the core; pytest as a
development dependency).** Executable packaging via the `dongle-rescue` entry point;
standalone binary generation (PyInstaller) is deferred to Milestone 8.

## Consequences

- Zero runtime dependency beyond the interpreter already present on target distros.
- Modules that would require a C extension (e.g. own raw netlink) stay out of V1;
  everything goes through OS CLIs, which also isolates the security surface.
- Revisit this ADR if a performance requirement arises that Python cannot meet
  (unlikely: the bottleneck is subprocess I/O, not CPU).

## Rejected alternatives

- **Rust:** better binary and memory-safe, but higher iteration cost for a
  V1 whose dominant risk is evidence-logic correctness, not performance.
- **Go:** good single binary; loses to Python in test-fixture expressiveness
  and in the external contribution curve (top of the Linux community funnel).
- **C/C++:** memory-unsafe in a product that parses hostile input — worst
  option for the threat profile (ADR 0002).
