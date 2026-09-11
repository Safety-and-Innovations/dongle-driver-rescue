# ARCHITECTURE — Dongle Driver Rescue V1

- **Status:** Baseline approved in Milestone 3 (consolidation after research)
- **Stack:** Python 3.12+ stdlib ([ADR 0001](adr/0001-stack-python.md))
- **Principles:** cited evidence for every conclusion, UNKNOWN valid,
  deterministic output ([ADR 0003](adr/0003-evidence-determinism.md))

## Module map

```text
src/dongle_rescue/
├── cli/            # argparse; commands identify|diagnose|repair|verify|
│                   # rollback|history|report|doctor; flags --json --verbose
│                   # --debug --non-interactive --no-network
├── core/           # types.py (domain), diagnosis.py (A-E machine),
│                   # confidence.py (assignment rules)
├── usb/            # enumeration via sysfs + lsusb fallback; descriptor
│                   # parsing; modalias builder
├── linux/          # modules.alias parser, modinfo wrapper, dmesg/journalctl
│                   # reader, udev/modprobe.d inspectors
├── windows/        # V1 read-only: Get-PnpDevice/pnputil parsers
│                   # (documented, runs only on Windows hosts)
├── identification/ # SPEC §7 layer chain; revision-based resolution
│                   # (btrtl ic_id_table etc.)
├── drivers/        # modules.alias candidates + chipsets.json base;
│                   # new_id feasibility (incl. .no_dynamic_id)
├── firmware/       # modinfo -F firmware → dmesg → WHENCE index → distro
│                   # package (ADR 0002 S4)
├── diagnostics/    # B/C/D/E state detectors over evidence
├── repair/         # transactions, dry-run planner, new_id/bind executor,
│                   # modprobe.d/udev persistence
├── rollback/       # idempotent transaction journal
├── verification/   # post-repair: interface/iw scan/HCI adapter checks
├── security/       # S1-S7 validation (binary allowlist, grammars)
├── provenance/     # Evidence objects and serialization
├── reporting/      # human-readable text (SPEC §40 format) + JSON schema v1
└── data/           # chipsets.json generated from docs/research/*.md
```

## Main flow (`dongle-rescue diagnose`)

```text
usb.enumerate ──► identification.resolve ──► drivers.candidates
                                              │
             ┌────────────────────────────────┤
             ▼                                ▼
       firmware.requirements            diagnostics.classify ──► A-E/UNKNOWN state
              │                                │
              └────────────► reporting.emit ◄──┘
                             (text | deterministic JSON)
```

## Cross-module invariants

1. No module talks to disk/system directly: everything via `host.Host`
   (injection; tests use synthetic fixtures).
2. External boundaries go through the `types.py` grammars
   (hex4, module name, firmware path).
3. `chipsets.json` is versioned data with confidence+citation per line;
   regenerated from research docs, never hand-edited in code.
4. Repair exists only as a plan (dry-run) + transaction with rollback;
   execution requires explicit consent.
5. Network: a single egress point, switchable off with `--no-network`.

## Open decisions → RESOLVED by research (M2)

1. **`new_id` feasibility per driver** (`docs/research/realtek.md` §1,
   `linux-kernel.md` §3): `rtl8xxxu` has `.no_dynamic_id = 1` — State B for
   Realtek AC chips has NO dynamic-bind repair; the planner consults
   a per-module capability matrix (`drivers/new_id_feasible: bool`) and produces
   a diagnosis+alternative when infeasible.
2. **Bind persistence**: alias in `/etc/modprobe.d/*.conf`
   (`linux-kernel.md` §4) — declarative, reversible, survives upgrades.
3. **Firmware packages**: file→package map per distro family
   (`firmware-supply-chain.md`, `mediatek-atheros.md` §6); source is always
   the distro package manager or upstream git with hash (ADR 0002 S4).
4. **Alias collisions are real** (`mediatek-atheros.md` §5): multiple
   candidates per VID:PID; dmesg + bound driver arbitrate.
5. **Kernel divergence** (real host): always diagnose against the running
   tree and flag a pending reboot (new kernel installed).
