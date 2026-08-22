# Windows Diagnostics — read-only enumeration, cross-reference and signature checks

> Research note for Dongle Driver Rescue. V1 **diagnoses** Windows; it never
> repairs it. Everything in this document is either read-only observation or
> explanation output. All external claims cite official Microsoft Learn pages
> (numbered, Sources at the end). Host-verified items are marked **[local]**;
> claims not re-fetched this session are flagged `[unverified]`.

Date: 2026-08-22 · Branch: main · Scope: Windows 10 1903+ / Windows 11.

---

## 0. Ground rules

From SPEC §4 — the tool must never on Windows: edit an INF, inject Hardware IDs
into one, break signatures, enable test signing as a normal procedure, disable
Driver Signature Enforcement, or install unsigned drivers to "make it work".
When a device is not legitimately served by a driver, the entire permitted
output is: `diagnose + explain + point to the adequate official origin`
(SPEC §4). Sections 1–4 below are the evidence base for exactly that pipeline;
section 5 is the enforced whitelist/blacklist.

---

## 1. PnP enumeration (SetupAPI-backed, PowerShell / PnPUtil)

### 1.1 Get-PnpDevice

`Get-PnpDevice` "returns basic information about Plug and Play (PnP) devices";
parameters include `-PresentOnly` ("Present devices are physically in the system
or attached to it"), `-Class`, `-FriendlyName`, `-InstanceId` (alias `DeviceId`)
and `-Status` with accepted values `OK, ERROR, DEGRADED, UNKNOWN`.[8] Official
example filtering problem devices:

```powershell
Get-PnpDevice -PresentOnly -Status ERROR,DEGRADED,UNKNOWN
```

USB dongles filter naturally by instance path prefix — the docs' own examples
show instance IDs like `USB\VID_8087&PID_0024\5&3541780&0&1`:[8]

```powershell
Get-PnpDevice -Class Net -PresentOnly | Where-Object InstanceId -like 'USB\*'
Get-PnpDevice -Class Bluetooth -PresentOnly | Where-Object InstanceId -like 'USB\*'
```

### 1.2 Device properties: Device Instance ID, Hardware IDs, Compatible IDs

`Get-PnpDeviceProperty` "gets detailed properties for a PnP device"; property
keys have friendly names of the form `DEVPKEY_XXX`.[9] The documentation's own
example output shows exactly the fields we capture:

```text
InstanceId KeyName                                   Type       Data
---------- -------                                   ----       ----
SWD\PRI... DEVPKEY_Device_DeviceDesc                 String     Local Print Queue
SWD\PRI... DEVPKEY_Device_HardwareIds                StringList {PRINTENUM\LocalPrintQueue}
SWD\PRI... DEVPKEY_Device_CompatibleIds              StringList {GenPrintQueue, SWD\GenericRaw, SWD\Generic}
SWD\PRI... DEVPKEY_Device_Class                      String     PrintQueue
SWD\PRI... DEVPKEY_Device_ClassGuid                  Guid       {1ED2BBF9-11F0-4084-B21F-AD83A8E6DCDC}
```

Capture set per device (read-only):

```powershell
$dev = Get-PnpDevice -PresentOnly | Where-Object InstanceId -like 'USB\VID_*'
Get-PnpDeviceProperty -InstanceId $dev.InstanceId -KeyName `
  'DEVPKEY_Device_DeviceDesc','DEVPKEY_Device_HardwareIds',`
  'DEVPKEY_Device_CompatibleIds','DEVPKEY_Device_ProblemCode'
```

`DEVPKEY_Device_ProblemCode` is demonstrated as a `UInt32` in the same
page[9]; deeper root cause is exposed by `DEVPKEY_Device_ProblemStatus`, which
the CM_PROB pages direct driver developers to for the failure code behind
Codes 10/28 (`unverified as a PowerShell-facing key name; documented as the
device-property mechanism on the CM_PROB pages`).[11][12]

Additional keys commonly useful for chipset attribution —
`DEVPKEY_Device_BusReportedDeviceDesc`, `DEVPKEY_Device_DriverInfPath`,
`DEVPKEY_Device_DriverVersion` `[unverified names — validate against
devpkey.h on a live box before relying on them]`.

### 1.3 pnputil: same data without PowerShell

PnPUtil ships in every Windows since Vista in `%windir%\system32`.[7]
Command syntax facts from Microsoft Learn:[6]

- `PNPUTIL /enum-devices` — available since **Windows 10 1903**; flags:
  `/connected | /disconnected`, `/instanceid <id>`, `/problem [<code>]`,
  `/deviceids` ("display hardware and compatible IDs", Win10 2004),
  `/properties`, and since Win10 2004 `/drivers` ("display matching and
  installed drivers").
- `PNPUTIL /enum-drivers` — available since **Windows 10 1607**; optional
  `/class` (Win11 21H2) and `/files` (Win11 22H2).

Workhorse queries (all read-only):

```console
pnputil /enum-devices /connected /deviceids /properties
pnputil /enum-devices /problem            ; rem only problem devices
pnputil /enum-devices /instanceid "USB\VID_0BDA&PID_8189\5&23c4b87&0&2" /drivers
pnputil /enum-drivers                     ; rem third-party (OEM) packages only
```

### 1.4 Problem codes (CM_PROB) — the four that matter plus two secondary

Defined in Cfg.h; Device Manager displays them as "Code N".[10]

| Code | Name | Exact display message | What it means for us |
|---|---|---|---|
| 28 | `CM_PROB_FAILED_INSTALL` | "The drivers for this device are not installed. (Code 28)"[11] | **State-B/No-driver anchor.** Underlying status `0xC0000490 STATUS_PNP_NO_COMPAT_DRIVERS`: "PnP could not find a compatible driver… Examine the hardware IDs and compatible IDs of the device in question and compare to the hardware ID(s) that the INF specifies under the Models sections."[11] |
| 10 | `CM_PROB_FAILED_START` | "This device cannot start. (Code 10)"[12] | Driver matched but a stack driver failed `IRP_MN_START_DEVICE`; check `DEVPKEY_Device_ProblemStatus` for the failure code.[12] |
| 43 | `CM_PROB_FAILED_POST_START` | "Windows has stopped this device because it has reported problems. (Code 43)"[13] | A driver reported the device failed (invalidated device state → `PNP_DEVICE_FAILED`). Classic on counterfeit/failing dongles; pairs with our SUSPECTED_CLONE classifier. |
| 45 | `CM_PROB_PHANTOM` | "Currently, this hardware device is not connected to the computer. (Code 45)"[14] | Phantom record: device not present. Only appears when `DEVMGR_SHOW_NONPRESENT_DEVICES` is set[14] — useful for history mining, harmless otherwise. |
| 22 | `CM_PROB_DISABLED` | (disabled by user/policy)[10] | Distinguish "broken" from "turned off". |
| 52 | `CM_PROB_UNSIGNED_DRIVER` | signature policy block[10] | Direct signal for our signature diagnostics (§3). |

Full table: Codes 1–57 mapped to `CM_PROB_*` names.[10]

---

## 2. DriverStore: crossing Hardware ID → declaring INF (without editing anything)

Concept (quotes): the Driver Store is "a trusted collection of inbox and
non-Microsoft driver packages… Only the driver packages in the Driver Store can
be installed on a device". Copying a package into it is *staging*, and staging
requires verification: the INF must point at a catalog file whose hashes cover
the INF and referenced files, signed by a trusted signature.[15] Once staged,
files "shouldn't be removed or modified in any way".[15]

Cross-reference procedure (strictly read-only):

1. **List staged third-party packages:** `pnputil /enum-drivers`. Output gives
   `oem#.inf`, original name, class, version and date per package.
   Caveat with citation: PnPUtil "lists only driver packages that aren't in-box
   packages"[7] — an in-box INF that matches our HWID will NOT appear here.
2. **Ask the ranking engine directly** instead of reimplementing rank logic:
   `pnputil /enum-devices /instanceid <ID> /drivers` displays "matching and
   installed drivers" for that device[6] — this is the legitimate answer to
   "which INF claims this HWID and how well".
   The selection model behind it: Windows searches the Driver Store first, then
   separately searches Windows Update/DevicePath for a better match, always
   installing from the store copy.[22]
3. **In-box coverage sweep (text-level, still read-only):** scan
   `%SystemRoot%\INF\*.inf` and
   `C:\Windows\System32\DriverStore\FileRepository\<inf>\*` files for the
   device's HWIDs inside their `[Models]` sections. This mirrors what Code 28
   debugging guidance says PnP itself does: compare device hardware/compatible
   IDs against the IDs the INF declares under its Models sections.[11]
4. **Registry view (read-only)**: enumerate
   `HKLM\SYSTEM\CurrentControlSet\Enum\USB\<VID_xxxx&PID_yyyy>` via
   `Get-ChildItem`/`Get-ItemProperty` to correlate instance records with
   installed services `[unverified key layout — standard location, confirm on
   live box]`.

Nothing above stages, deletes or edits anything. The DriverStore itself must
never be touched outside staging[15] — we don't stage.

---

## 3. Catalogs and signature verification

### 3.1 Why the `.cat` file is the thing to check

"A digitally signed catalog file (*.cat*) can be used as a digital signature for
an arbitrary collection of files… PnP device installation recognizes the signed
catalog file of a driver package as the digital signature for the driver
package." Any post-signing change invalidates it — "even a single-byte change to
correct a misspelling invalidates the digital signature".[16] This is precisely
why editing an INF (our absolute prohibition) cannot ever be a legitimate fix:
it destroys the package's signature basis.[16] Catalog files are installed under
`%SystemRoot%\System32\CatRoot` automatically during staging, and must not be
added/removed manually.[16]

Signature categories Windows assigns before install — including "Altered"
(signed but modified) and "Unsigned" — and the resulting silent-install vs.
prompt behavior are tabulated on the PnP-installation signatures page.[17]

Policy backdrop: since Windows 10 1607, Windows "will not load any new
kernel-mode drivers which are not signed by the [Hardware] Dev Portal"
(certification or attestation signing).[18] Consequence for state E/B fixes:
there is no legitimate self-service route to a working kernel driver for an
unsupported ID — only the vendor's signed package via WU/OEM.

### 3.2 Practical checks (PowerShell)

`Get-AuthenticodeSignature` gets "information about the Authenticode signature
for a file"; note the precedence rule: "If the file is both embedded signed and
Windows catalog signed, the Windows catalog signature is used," and unsigned
files return an object with blank fields.[19] Status values come from the
`SignatureStatus` enum (`Valid, UnknownError, NotSigned, HashMismatch,
NotTrusted, NotSupportedFileFormat, Incompatible`) — and the enum doc carries
the caveat we propagate verbatim into reports: `Valid` means only that the
signature is syntactically valid; "It does not imply trust in any way".[20]

```powershell
$sys = (Get-PnpDeviceProperty -InstanceId $id -KeyName 'DEVPKEY_Device_DriverInfPath') # locate pkg dir first
Get-ChildItem C:\Windows\System32\DriverStore\FileRepository\*\*.sys |
  Get-AuthenticodeSignature |
  Select-Object Path, Status, StatusMessage, @{n='Signer';e={$_.SignerCertificate.Subject}}
```

API-level concept: **WinVerifyTrust** performs the verification; action GUIDs
include `DRIVER_ACTION_VERIFY` ("Verify the authenticity of a Windows Hardware
Quality Labs (WHQL) signed driver") and `WINTRUST_ACTION_GENERIC_VERIFY_V2`
(Authenticode policy provider); success criterion is strict — return value
zero, "No other value besides zero should be considered a successful
return".[21] Command-line equivalent used by vendors: `signtool verify /kp`
(kernel-policy check) `[command shown in MS Learn release-signing walkthrough;
flag syntax unverified against current WDK docs]`.

---

## 4. State B on Windows: known chipset, no claiming INF

Definition mapping: a USB Wi-Fi/BT dongle whose Hardware IDs (from §1.2)
match a known chipset family (e.g. `USB\VID_0BDA&PID_C811` → RTL8821CU) while
no staged or in-box INF declares that exact HWID — surfaced as Code 28 /
`STATUS_PNP_NO_COMPAT_DRIVERS` when PnP ran out of compatible drivers.[11]

**Correct V1 output** (nothing more):

1. **Diagnosis**: instance ID, VID/PID/bcdDevice, full Hardware/Compatible ID
   lists, problem code + status, the searched INF surfaces (OEM list, in-box
   sweep result, matching-rank query).
2. **Explanation**: "the driver family exists but no package on this machine
   declares this device ID" — phrased from the Models-section semantics,[11]
   plus the signature constraint that forbids us from fixing it locally.[16][18]
3. **Pointer to the legitimate origin** of a reference driver for the chipset:

| Chipset family | Legitimate origin to point at |
|---|---|
| All targets (first choice) | **Windows Update** automatic flow — Windows itself searches WU for a better match than the store copy[22]; and the **Microsoft Update Catalog** (https://www.catalog.update.microsoft.com/) for manual retrieval of the exact signed driver package.[23] |
| Realtek WLAN/BT (RTL81xx/87xx/88xx) | Realtek does not maintain a stable public per-chip download portal for these parts; reference drivers reach users via OEM/WU/Catalog. Vendor site pointers (`https://www.realtek.com/Downloads`) `[unverified — do not deep-link; resolve at runtime]`. |
| MediaTek/Ralink (MT76xx) | Same reality: WU/OEM/Catalog are the dependable channels; MediaTek's public driver area has been unstable historically `[unverified]`. |
| Qualcomm Atheros (AR9271) | No official Windows driver page exists for this legacy USB part; channel = Windows Update / OEM `[unverified]`. |
| Broadcom/CSR BT (BCM20702, CSR8510) | Typically in-box or WU-delivered; CSR8510 clones are a known counterfeit vector (SPEC §10) — diagnose, don't chase drivers. |

Rule inherited from IDEIA/SPEC: if a legitimate origin cannot be identified,
say so plainly — the tool reports that no legitimate source was found rather
than improvising one.

---

## 5. Absolute restrictions and the safe command whitelist

### 5.1 Never executed by this tool (V1 and beyond)

Forbidden operations, each tied to its reason:

| Forbidden | Reason |
|---|---|
| Edit any `.INF` (add/change HWIDs) | Invalidates the package catalog signature — "even a single-byte change" breaks it[16]; forces user toward test signing. |
| `pnputil /add-driver`, `/delete-driver`, `/install` variants | Mutates DriverStore; repair is out of scope.[15] |
| `pnputil /restart-device`, `/remove-device`, `/scan-devices`, `/enable-device`, `/disable-device` | State-changing device operations.[6] |
| `Enable-PnpDevice` / `Disable-PnpDevice` | State-changing cmdlets (same module as the read ones).[8] |
| `bcdedit /set testsigning yes`; disabling Driver Signature Enforcement (boot menu / ntdsig) | Degrades platform security; SPEC §4 hard prohibition.[18] |
| `inf2cat`+`signtool sign` on any package; adding certs to Root/TrustedPublisher stores | Manufacturing our own trust — prohibited. |
| Writes under `C:\Windows\System32\CatRoot`, DriverStore FileRepository, `%SystemRoot%\INF` | Store locations are managed by Windows only.[15][16] |

### 5.2 Read-only commands the diagnostic layer may run

```powershell
Get-PnpDevice [-PresentOnly] [-Class …] [-Status …]                 # observe
Get-PnpDeviceProperty -InstanceId … -KeyName …                      # observe
Get-CimInstance Win32_PnPEntity                                     # observe [unverified field mapping]
Get-AuthenticodeSignature <file>                                    # verify signature
Get-FileHash <file> -Algorithm SHA256                               # inventory hash
Get-ChildItem/Get-ItemProperty on HKLM\...\Enum, %SystemRoot%\INF,  # read
  DriverStore\FileRepository, CatRoot listings
```

```console
pnputil /enum-devices [/connected|/disconnected|/instanceid X|/problem|/deviceids|/properties|/drivers]
pnputil /enum-drivers [/class X] [/files]
pnputil /enum-interfaces ; pnputil /enum-containers                ; rem observe-only
signtool verify /pa <file>                                          ; rem verify-only use
```

Everything else defaults to **not executed**; any new command must be added to
this whitelist after review, never improvised at runtime.

---

## 6. Risks & open items

- DEVPKEY names beyond those shown in official examples
  (`BusReportedDeviceDesc`, `DriverInfPath`, `DriverVersion`,
  `ProblemStatus`) need validation on a real Windows box `[unverified]`.
- Win32_PnPSignedDriver CIM query could replace part of the INF sweep; needs a
  live-box check before adoption `[unverified]`.
- Vendor download URLs are deliberately left unresolved (see §4); the product
  must ship them as runtime-resolvable hints, not hardcoded deep links, because
  they rot — the Microsoft-controlled channels (WU, Update Catalog) are the
  stable contract.[22][23]
- Phantom/history mining (Code 45 records) requires the
  `DEVMGR_SHOW_NONPRESENT_DEVICES` visibility quirk[14] — decide whether V1
  reads phantom records at all.

---

## Sources

<!-- rendered from citation ledger -->

