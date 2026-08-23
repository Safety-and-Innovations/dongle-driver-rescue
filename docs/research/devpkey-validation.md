# DEVPKEY name validation — Windows diagnostics layer

Validation of the device-property key names used by the diagnostic layer
(`windows-diagnostics.md` §1.2/§6) against official Microsoft Learn pages,
fetched 2026-08-23. Primary sources: `learn.microsoft.com/windows-hardware/drivers/install/devpkey-device-*`
(reference pages for `Devpkey.h`), the PnpDevice PowerShell module docs, and
the current `pnputil` syntax/examples pages. Third-party items (GitHub issues,
Stack Overflow) used only as secondary corroboration and labeled as such.

## Validation matrix

| Key | exists | type (DevProp) | type seen in PowerShell | min OS | Doc URL (Microsoft Learn) | PowerShell-usable | confidence |
|---|---|---|---|---|---|---|---|
| `DEVPKEY_Device_ProblemCode` | Y | `DEVPROP_TYPE_INT32` | `UInt32` (docs ex. 4 + live) | Windows Vista+ | https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-problemcode | Y — demonstrated verbatim in Get-PnpDeviceProperty docs Ex. 4 | High |
| `DEVPKEY_Device_ProblemStatus` | Y | `DEVPROP_TYPE_NTSTATUS` | numeric/hex (live) | **Windows 8+** | https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-problemstatus | Y — same `-KeyName` mechanism; live community use (ACPI deadlock repro, G-Helper #4900) | High |
| `DEVPKEY_Device_BusReportedDeviceDesc` | Y | `DEVPROP_TYPE_STRING` | `String` | Windows 7+ | https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-busreporteddevicedesc | Y — standard `-KeyName` string; also via `Win32_PnPEntity.GetDeviceProperties('DEVPKEY_Device_BusReportedDeviceDesc')` (SO 69362886). Value is bus-driver-supplied (IRP_MN_QUERY_DEVICE_TEXT) → can be absent on some devices; handle null | High (key), Medium (per-device presence) |
| `DEVPKEY_Device_DriverInfPath` | Y | `DEVPROP_TYPE_STRING` | `String` | Windows Vista+ (registry fallback `InfPath` pre-Vista) | https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-driverinfpath | Y — same mechanism; printed live by pnputil as `oem119.inf` (microsoft/MIDI #186) | High |
| `DEVPKEY_Device_DriverVersion` | Y | `DEVPROP_TYPE_STRING` | `String` | Windows Vista+ (registry fallback `DriverVersion` pre-Vista) | https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-driverversion | Y — same mechanism; printed live by pnputil (MIDI #186) | High |
| `DEVPKEY_Device_HardwareIds` (control) | Y | `DEVPROP_TYPE_STRING_LIST` | `StringList` | Windows Vista+ | https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-hardwareids | Y — shown in Get-PnpDeviceProperty docs Ex. 1 output | High |
| `DEVPKEY_Device_CompatibleIds` (control) | Y | `DEVPROP_TYPE_STRING_LIST` | `StringList` | Windows Vista+ | https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-compatibleids | Y — docs Ex. 1 output | High |
| `DEVPKEY_Device_Class` (control) | Y | `DEVPROP_TYPE_STRING` | `String` | Windows Vista+ | https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-class | Y — docs Ex. 1 output | High |
| `DEVPKEY_Device_ClassGuid` (control) | Y | `DEVPROP_TYPE_GUID` | `Guid` | Windows Vista+ | https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-classguid | Y — docs Ex. 4 uses it as `-KeyName` | High |

All nine keys are defined in `Devpkey.h` (header stated on every reference
page; source markdown confirmed in MicrosoftDocs/windows-driver-docs,
`windows-driver-docs-pr/install/devpkey-device-*.md`). Every minOS ≤ our
scope floor (Win10 1903).

## Name-mapping caveats (Get-PnpDeviceProperty)

1. **Two accepted forms.** `-KeyName` accepts the DEVPKEY short name
   (`'DEVPKEY_Device_ProblemCode'`, docs Example 4) or the `{GUID} PID` pair
   (`'{4340A6C5-93FA-4706-972C-7B648008A5A7} 3'`, Example 3). Output rows
   always carry `KeyName` = friendly DEVPKEY name plus `Key` = {GUID} PID.
2. **Type remapping.** The cmdlet surfaces DevProp types as WMI/PS types
   (`Win32_PnPDeviceProperty*` classes): STRING→String, STRING_LIST→StringList,
   GUID→Guid. Notably the DevProp page types ProblemCode as
   `DEVPROP_TYPE_INT32` while the cmdlet reports `UInt32` (both are official
   MS sources). Treat problem codes as small non-negative ints; don't do
   signed/unsigned arithmetic on them.
3. **Friendly ≠ guaranteed present.** A property row is returned only if the
   device/property store has it (e.g., BusReportedDeviceDesc is empty for
   buses whose driver reports nothing; ProblemStatus is `STATUS_SUCCESS`/0
   when no extra context exists — that is itself documented semantics, not an
   error).
4. **Module age.** PnpDevice module docs published for Server 2016+/Win10 era;
   cmdlets exist since Win8.1 — irrelevant here given scope ≥ 1903.

## pnputil cross-check (`/enum-devices`)

Per the current syntax page
(https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/pnputil-command-syntax):

| Flag | Available starting in |
|---|---|
| `/connected`, `/disconnected`, `/instanceid`, `/class`, `/problem [<code>]`, `/relations` | Win10 1903 |
| `/drivers` | Win10 2004 |
| `/deviceids`, `/bus`, `/services`, `/stack`, `/interfaces`, **`/properties`** | **Win11 21H2** |
| `/deviceid`, `/resources` | Win11 22H2 |

Findings:

- **ProblemCode: YES, on both Win10 and Win11 — but not via `/properties` on
  Win10.** Plain `pnputil /enum-devices` (and `/problem` filtered runs) print
  friendly labels `Problem Code:` (with `CM_PROB_*` symbol) and
  `Problem Status:` when set. Official example in MS Learn
  (test-a-driver-package-manual-deployment.md):
  `pnputil /enum-devices /problem /deviceids` →
  `Problem Code: 52 (0x34) [CM_PROB_UNSIGNED_DRIVER]` /
  `Problem Status: 0xC0000428`. Community sample (SO 77133423) shows the same
  labels from plain `pnputil /enum-devices` on Win10-era builds.
- **`/properties` on "Win10 2004+": NO.** The flag is annotated **Windows 11
  21H2** in the current doc. Our earlier "Win10 2004" reading was wrong; git
  history of the doc (MicrosoftDocs/windows-driver-docs commit 3977687149,
  2022-11-09) shows the old Win10-era flag for hardware/compatible IDs was
  `/ids` (documented since 1903), later re-documented as `/deviceids` under
  the Win11 21H2 grouping. On any Win10 build, expect `pnputil /enum-devices`
  to reject unknown flags — parse errors defensively or gate on OS version.
- **BusReportedDeviceDesc via pnputil: Win11 21H2+ only, high-probability but
  unverified verbatim.** `/properties` is documented as "display all device
  properties", and observed `/properties` dumps print raw `DEVPKEY_Device_*`
  names (`DeviceDesc`, `DriverVersion`, `DriverInfPath`, … — microsoft/MIDI
  #186; SO 73490266 for PowerData). No public sample was found showing
  `DEVPKEY_Device_BusReportedDeviceDesc` in a pnputil dump specifically
  (DxDiag prints it under its own format, which is unrelated). Treat
  "pnputil prints BusReportedDeviceDesc" as expected-but-confirm-on-box; for
  Win10 targets use PowerShell instead — pnputil has no equivalent there.

## READY FOR DOCS PATCH

Exact replacement sentences for `docs/research/windows-diagnostics.md`.

**(a) §1.2 — replace the ProblemStatus parenthetical:**

Old:
> Codes 10/28 (`unverified as a PowerShell-facing key name; documented as the
> device-property mechanism on the CM_PROB pages`).[11][12]

New:
> Codes 10/28. `DEVPKEY_Device_ProblemStatus` is an official `Devpkey.h` key
> (`DEVPROP_TYPE_NTSTATUS`, Windows 8+ — inside our 1903+ scope), retrievable
> with the same `Get-PnpDeviceProperty -KeyName 'DEVPKEY_Device_ProblemStatus'`
> mechanism; see devpkey-device-problemstatus on Microsoft Learn.[11][12][24]

**(b) §1.2 — replace the "additional keys" paragraph:**

Old:
> Additional keys commonly useful for chipset attribution —
> `DEVPKEY_Device_BusReportedDeviceDesc`, `DEVPKEY_Device_DriverInfPath`,
> `DEVPKEY_Device_DriverVersion` `[unverified names — validate against
> devpkey.h on a live box before relying on them]`.

New:
> Additional keys commonly useful for chipset attribution — all validated as
> official `Devpkey.h` symbols with Microsoft Learn reference pages
> (2026-08-23): `DEVPKEY_Device_BusReportedDeviceDesc` (`DEVPROP_TYPE_STRING`,
> Windows 7+), `DEVPKEY_Device_DriverInfPath` (`DEVPROP_TYPE_STRING`,
> Windows Vista+; registry counterpart `InfPath`),
> `DEVPKEY_Device_DriverVersion` (`DEVPROP_TYPE_STRING`, Windows Vista+;
> registry counterpart `DriverVersion`). Each is a valid
> `Get-PnpDeviceProperty -KeyName` string; the only live-box step left is a
> smoke test of the generated commands, not name validation.[24]
> Caveat kept: `BusReportedDeviceDesc` is supplied by the bus driver
> (IRP_MN_QUERY_DEVICE_TEXT) and may be empty for some devices — read as
> nullable.

**(c) §1.3 — fix the pnputil flag availability list:**

Old:
> `/deviceids` ("display hardware and compatible IDs", Win10 2004),
> `/properties`, and since Win10 2004 `/drivers` ("display matching and
> installed drivers").

New:
> `/connected | /disconnected`, `/instanceid <id>`, `/problem [<code>]`,
> `/relations` since Win10 1903; `/drivers` ("display matching and installed
> drivers") since Win10 2004; `/deviceids` ("display hardware and compatible
> IDs"), `/bus`, `/services`, `/stack`, `/interfaces` and `/properties`
> ("display all device properties") since **Windows 11 21H2** — on Win10 the
> HW/compatible-ID flag was `/ids`. Plain `/enum-devices` already prints
> `Problem Code:`/`Problem Status:` labels for problem devices on Win10 and
> Win11; `/properties` additionally dumps every property under raw
> `DEVPKEY_*` names (Win11 21H2+ only — never assume it on Win10).[6]

**(d) §6 — resolve the first open item:**

Old:
> - DEVPKEY names beyond those shown in official examples
>   (`BusReportedDeviceDesc`, `DriverInfPath`, `DriverVersion`,
>   `ProblemStatus`) need validation on a real Windows box `[unverified]`.

New:
> - RESOLVED 2026-08-23 (docs-level): `BusReportedDeviceDesc`,
>   `DriverInfPath`, `DriverVersion`, `ProblemStatus` are official
>   `Devpkey.h` keys with Learn reference pages and are accepted by
>   `Get-PnpDeviceProperty` (see devpkey-validation.md). Residual live-box
>   risk reduced to command smoke-testing and the nullable
>   `BusReportedDeviceDesc` value.

Suggested new source entry for the citation ledger:
`[24] Microsoft Learn, DEVPKEY_Device_Xxx reference pages (ProblemCode,
ProblemStatus, BusReportedDeviceDesc, DriverInfPath, DriverVersion,
HardwareIds, CompatibleIds, Class, ClassGuid) + PnPUtil Command Syntax +
Get-PnpDeviceProperty (PnpDevice module) — fetched 2026-08-23.`
