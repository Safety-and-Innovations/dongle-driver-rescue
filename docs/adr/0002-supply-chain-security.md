# ADR 0002 — Security and supply-chain policy

- **Status:** Accepted
- **Date:** 2026-08-22
- **Responsible:** Lead Engineering Agent (ox-alpha)

## Context

The product performs privileged operations (driver bind/unbind, sysfs writes,
modprobe.d/udev persistence) and consumes hostile data: USB strings,
dmesg output, remote-repository metadata, web page content.
SPEC §§14, 29, 37 define an independent red team and forbid installing
web-found artifacts without full validation.

## Decisions

### S1 — Minimal execution surface

No intermediate shell. Every subprocess is invoked with an argument list
(`subprocess.run([...], shell=False)`). No externally sourced data (USB string,
firmware file name, log output) ever enters a command, command
template, or concatenated path without passing through the S2/S3 validation layer.

### S2 — Strict executable allowlist

The core keeps a single `ALLOWED_BINARIES` table with verified absolute paths
(`/usr/bin/modinfo`, `/usr/bin/journalctl`, ...). An executable outside the table =
configuration error, never a fallback.

### S3 — Identifier validation

Every identifier crossing the external→internal→system boundary goes through a
closed grammar:

- VID/PID: exactly 4 hex digits, case-insensitive, zero-padded.
- Module name: `[a-z0-9_-]{1,64}`.
- Firmware path: normalized, `..` forbidden, symlink resolved before
  any use, mandatory `/lib/firmware/` prefix.

### S4 — Download policy (supply chain)

Accepted source order for external artifacts:

1. Distro package via the native manager (`apt`, `dnf`, `pacman`) —
   distro-signed, existing channel.
2. Upstream `linux-firmware` git checkout/tag with a pinned commit hash.

Forbidden in V1: downloading loose binaries from mirrors, self-hosting
firmware/drivers, automatic out-of-tree driver installation (state E only
**points at** the upstream repository, never clones/builds without explicit confirmation).

Every network action logs what/where/when in structured logs;
`--no-network` shuts off every network path by construction (feature flag checked
at the single network egress point).

### S5 — Privilege

Diagnostics run unprivileged whenever possible; dmesg reads may
require a suitable group — the tool reports this, it does not self-elevate. Repair
operations require explicitly declared root and display a dry-run plan first.

### S6 — External content is untrusted input

Web research output, READMEs, issues, or pages never become execution instructions
or configuration values without passing through S2–S4. This applies to both agents and code.

### S7 — Privacy

No telemetry, accounts, or cloud (SPEC §30). The only possible traffic is
package/repository metadata queries for firmware resolution, logged and
switchable off.

## Consequences

- Red team (Milestone 7) validates S1–S7 with real exploitation scenarios.
- `tests/fixtures/malicious/` fixtures exercise S3 against hostile inputs.
