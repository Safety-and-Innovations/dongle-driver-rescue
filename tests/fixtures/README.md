# tests/fixtures — synthetic evidence tree (SPEC §20, §22)

No physical hardware is required. Every fixture derives from a cited research
document and exists to make the pipeline deterministic and hostile-input aware.

## Layout

```
fixtures/
├── __init__.py            # FixtureRootHost + dmesg line fixtures (cited)
├── malicious.py           # red-team strings: traversal, %s, globs, >4KB
├── windows_pnputil_sample.py  # pnputil /enum-devices output (windows-diagnostics.md §1.3)
├── golden/                # byte-a-byte regression outputs (ADR 0003 D4)
└── tree/                  # virtual filesystems per scenario
    ├── rtl8811cu_unbound/ # state B feasible — sysfs layout per linux-kernel.md §1
    ├── mt7601_ok/         # state A — bound driver + firmware present (mediatek-atheros.md §1)
    ├── collision_760a/    # 148f:760a claimed by mt7601u AND mt76x0u (mediatek-atheros.md §5)
    └── modprobe.d_blacklisted/  # state D — blacklist syntax per linux-kernel.md §5
```

## Virtual roots (FixtureRootHost)

`sys/` → `/sys` · `lib/firmware` → `/lib/firmware` · `lib/modules` → `/lib/modules`

Symlinks resolve inside the scenario root only; escapes report the virtual
path and `exists()` returns False (S3 containment).

## Golden regeneration

```
DDR_REGEN_GOLDENS=1 pytest tests/test_golden_outputs.py
```

Golden files are canonical JSON (sorted keys, compact separators) compared as
exact bytes. Never edit by hand — regenerate from a reviewed change.

## dmesg fixtures (`__init__.py`)

- `DMESG_FW_MISSING_RTL8188EU`: canonical failure pattern
  `Direct firmware load for rtlwifi/rtl8188eufw.bin failed with error -2`
  (linux-kernel.md §6, CONFIRMED).
- `DMESG_SECURE_BOOT_REJECTION`: lockdown/module-verification shape
  (linux-kernel.md §5; exact message to be revalidated per kernel target).
- `DMESG_DESCRIPTOR_ERROR`: device descriptor read failures (-71, EPROTO).
