# Firmware Supply Chain — linux-firmware resolution pipeline

> Research note for Dongle Driver Rescue. Maps the deterministic chain
> `driver → requested firmware file → WHENCE entry (consumer driver, version,
> licence) → distro package / upstream origin → integrity verification`.
> Every external claim carries a numbered citation (see Sources at the end).
> Host-verified evidence is marked **[local]** with the command that produced it.
> Claims we could not fetch this session are flagged `[unverified]`.

Date: 2026-08-22 · Branch: main · Status: research complete, ready to inform implementation.

---

## 0. TL;DR

The kernel tells us the exact firmware filename it wants (`modinfo -F firmware`,
`dmesg`). The linux-firmware repo's `WHENCE` file is the authoritative index that
maps that filename to its consumer driver, version and licence. Distro packages
are the safe delivery channel; upstream integrity is anchored on **PGP-signed git
tags** (verified locally during this research) plus signed tarballs and a signed
`sha256sums.asc` published by kernel.org. We never host or fetch loose binaries;
we point at the origin and verify.

---

## 1. WHENCE: format and programmatic extraction

### 1.1 What WHENCE is

WHENCE sits at the root of the linux-firmware repository and states its own
purpose in the first lines:

```text
             **********
             * WHANCE *
             **********

This file attempts to document the origin and licensing information,
if known, for each piece of firmware distributed for use with the Linux
kernel.
```

(Verbatim from the fetched file — including the ASCII-art banner. Note the file
itself spells "WHENCE"; the banner reads "WHANCE" upstream.[1])

Repository: `git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git`
— "Repository of firmware blobs for use with the Linux kernel".[2]

### 1.2 Entry format (real excerpt)

Entries are separated by dashed rules (`----------…`) and use a flat
`Field: value` grammar. Real entry, fetched 2026-08-22:[1]

```text
Driver: mt7601u - MediaTek MT7601U Wireless MACs

File: mediatek/mt7601u.bin
Link: mt7601u.bin -> mediatek/mt7601u.bin
Version: 34

Licence: Redistributable. See LICENCE.ralink_a_mediatek_company_firmware for details
```

Observed field set across the file:

| Field | Meaning | Notes |
|---|---|---|
| `Driver:` | kernel module that requests these files | free text, first token = module name |
| `File:` | firmware path relative to `/lib/firmware` (or `/usr/lib/firmware`) | multiple per entry |
| `Link:` | symlink shipped by the repo, `name -> target` | must be resolved when matching filenames |
| `Version:` | vendor firmware version string | one line per `File:`, **positional** |
| `Licence:` | human pointer to a licence document | multiple possible; may be absent |
| `Info:` / `Source:` | provenance notes | optional |

**Licence relocation gotcha:** WHENCE still says `See LICENCE.xxx`, but the
licence documents moved under `LICENSES/`. Current tree contains e.g.
`LICENSES/LICENCE.rtlwifi_firmware.txt`, `LICENSES/LICENCE.mediatek`,
`LICENSES/LICENCE.open-ath9k-htc-firmware`. **[local]** `git ls-tree -r HEAD |
grep LICEN` on clone at commit `8c7fac62c0d1` (2026-08-21).

### 1.3 Parsing statistics (whole-file, this session)

A 40-line Python splitter over the fetched WHENCE (10,672 lines) produced:

```text
total parsed entries: 257
field coverage over entries: {'Driver': 257, 'File': 255, 'Licence': 215, 'Version': 123}
```

Consequences for implementation:

- `Driver:` is always present — file → consumer driver mapping is reliable.
- `Licence:` is missing in ~16% of entries → those files have **no declared
  redistribution basis**; the tool must report them as UNKNOWN-licence.
- `Version:` exists for less than half the entries; never treat it as required.

### 1.4 Extraction recipe: file → consumer driver → licence

```python
import re, sys

def parse_whence(path):
    entries, cur = [], None
    rule = re.compile(r'^-{20,}\s*$')
    field = re.compile(r'^(Driver|File|Link|Version|Licence|Info|Source):\s*(.*)$')
    for line in open(path, encoding='utf-8', errors='replace'):
        if rule.match(line):
            if cur and (cur.get('File') or cur.get('Link')):
                entries.append(cur)
            cur = {'raw': []}
            continue
        m = field.match(line)
        if cur is not None and m:
            cur.setdefault(m.group(1), []).append(m.group(2).strip())
        elif cur is not None:
            cur['raw'].append(line.rstrip())
    if cur and (cur.get('File') or cur.get('Link')):
        entries.append(cur)
    return entries

def resolve(entries, filename):
    """Return every WHENCE entry that declares `filename` directly or via Link."""
    hits = []
    for e in entries:
        files   = {f.strip() for f in e.get('File', [])}
        linked  = {l.split('->')[0].strip() for l in e.get('Link', [])}
        if filename in files | linked:
            hits.append({
                'driver':  e.get('Driver', ['UNKNOWN'])[0],
                'files':   sorted(files),
                'version': e.get('Version'),
                'licence': e.get('Licence', []),
            })
    return hits
```

Matching rules learned from the data:

1. Match the basename **after resolving `Link:` aliases** (e.g. dmesg says
   `mt7601u.bin`, WHENCE declares `mediatek/mt7601u.bin` + a `Link:`).
2. One entry can cover many drivers' worth of files (the big `btusb` entry holds
   all `rtl_bt/*` blobs together with Intel ones); extract the per-driver
   conclusion from the `Driver:` line, not from entry granularity.
3. If several entries declare the same file (rare), report both — conflict =
   `CONFLICT/UNKNOWN`, per SPEC §17.

### 1.5 Our target firmwares as WHENCE declares them today

All excerpts verbatim from the fetched WHENCE (2026-08-22):[1]

| Firmware file | Consumer driver (`Driver:`) | Version | Licence line |
|---|---|---|---|
| `rtlwifi/rtl8188eufw.bin` (RTL8188EU/EUS) | `rtl8xxxu - Realtek 802.11n WLAN driver for RTL8XXX USB devices` | 28.0 | Redistributable. See LICENCE.rtlwifi_firmware.txt |
| `mediatek/mt7601u.bin` (+ `Link: mt7601u.bin ->`) | `mt7601u - MediaTek MT7601U Wireless MACs` | 34 | Redistributable. See LICENCE.ralink_a_mediatek_company_firmware |
| `htc_9271.fw` v1.3.1 and `ath9k_htc/htc_9271-1.4.0.fw` v1.4.0 (AR9271) | `ath9k_htc - Atheros HTC devices (USB)` | 1.3.1 / 1.4.0 | old files: Redistributable, LICENCE.atheros_firmware; `-1.4.0`: **"Free software"**, LICENCE.open-ath9k-htc-firmware |
| `rtl_bt/rtl8761b_fw.bin`, `rtl8761b_config.bin`, `rtl8761bu_fw.bin`, `rtl8761bu_config.bin` (+ alias links such as `rtl8761a_config.bin -> rtl8761bu_config.bin`) | `btusb - Bluetooth USB driver` | e.g. `1339_02.00` | Redistributable. See LICENCE.rtlwifi_firmware.txt |

Notable: RTL8188EU firmware is now declared under the unified `rtl8xxxu`
consumer driver — older documentation saying "rtl8188eu" driver is stale. The
tool must derive the consumer driver from WHENCE at runtime, never from a
hardcoded memory of it.

---

## 2. Kernel firmware search order (`request_firmware`)

Definitive source: `drivers/base/firmware_loader/main.c` in the kernel tree:[3]

```c
/* direct firmware loading support */
static char fw_path_para[256];
static const char * const fw_path[] = {
	fw_path_para,
	"/lib/firmware/updates/" UTS_RELEASE,
	"/lib/firmware/updates",
	"/lib/firmware/" UTS_RELEASE,
	"/lib/firmware"
};

/*
 * Typical usage is that passing 'firmware_class.path=$CUSTOMIZED_PATH'
 * from kernel command line because firmware_class is generally built in
 * kernel instead of module.
 */
module_param_string(path, fw_path_para, sizeof(fw_path_para), 0644);
MODULE_PARM_DESC(path, "customized firmware image search path with a higher priority than default path");
```

Effective search order (first hit wins):

1. `firmware_class.path=` kernel cmdline parameter (custom path, highest priority);
2. `/lib/firmware/updates/<UTS_RELEASE>` — distro drop-in fixes for one kernel;
3. `/lib/firmware/updates`;
4. `/lib/firmware/<UTS_RELEASE>` (`UTS_RELEASE` = `uname -r`);
5. `/lib/firmware`.

Implementation-relevant facts:

- On distros using `/usr/lib/firmware`, `/lib` is a symlink to `/usr/lib`, so
  both spellings denote the same tree (**[local]** Ubuntu 24.04: `/lib ->
  usr/lib`). Debian ships firmware under `/usr/lib/firmware` explicitly
  (**[local]** `dpkg -c` outputs below).
- Compressed firmware is supported by the loader (xz/zst code paths live in the
  same `main.c`; `CONFIG_FW_LOADER_COMPRESS_*`). **[local]** Ubuntu noble ships
  most blobs as `.bin.zst` inside the package — the tool must compare filenames
  with compression suffixes tolerated.
- CPU microcode (`intel-ucode/`, `amd-ucode/`, Debian packages
  `intel-microcode`/`amd64-microcode` in `non-free-firmware` **[local]**) flows
  through the same loader mechanism with architecture-specific filenames; it
  lives inside the same firmware tree rather than adding a new search path
  `[unverified — not re-sourced this session]`.
- Failure shape the tool parses from `dmesg`:
  `Direct firmware load for <file> failed with error -2` (SPEC §6 state C).

---

## 3. Distro packaging: which package owns each target file

### 3.1 Ubuntu 24.04 (noble) — verified against the real archive

**[local]** `apt-cache policy linux-firmware` on this host:

```text
linux-firmware:
  Installed: (none)
  Candidate: 20240318.git3b128b60-0ubuntu2.29
     500 http://ports.ubuntu.com/ubuntu-ports noble-updates/main arm64 Packages
```

**[local]** Downloaded the candidate `.deb`
(`linux-firmware_20240318.git3b128b60-0ubuntu2.29_arm64.deb`, 655 MB) and listed
its contents — **all targets ship in the single `linux-firmware` package
(component `main`)**, zstd-compressed:

```text
./lib/firmware/ath9k_htc/htc_9271-1.4.0.fw.zst
./lib/firmware/htc_9271.fw.zst
./lib/firmware/rtl_bt/rtl8761b_config.bin.zst
./lib/firmware/rtl_bt/rtl8761b_fw.bin.zst
./lib/firmware/rtl_bt/rtl8761bu_config.bin.zst
./lib/firmware/rtl_bt/rtl8761bu_fw.bin.zst
./lib/firmware/rtlwifi/rtl8188eufw.bin.zst
./lib/firmware/mt7601u.bin.zst            (Contents index)
./lib/firmware/mediatek/mt7601u.bin.zst   (Contents index)
```

Ubuntu also keeps a small universe split package: `firmware-ath9k-htc`
provides `lib/firmware/ath9k_htc/htc_9271-1.4.0.fw` **[local]**, from
`noble/universe Contents-arm64.gz`. Runtime resolution should therefore prefer
`dpkg -S <path>` / Contents lookup over hardcoded package names.

### 3.2 Debian 13 (trixie) — verified against real `.deb`s

Debian keeps the classic split packages, component `non-free-firmware`
(source package `firmware-nonfree`, version `20250410-2`) **[local]**, downloaded
and inspected:

| Package | Contains (targets) |
|---|---|
| `firmware-realtek` | `rtlwifi/rtl8188eufw.bin`, `rtl_bt/rtl8761b_{fw,config}.bin`, `rtl_bt/rtl8761bu_{fw,config}.bin` |
| `firmware-mediatek` | `mediatek/mt7601u.bin` + top-level symlink `mt7601u.bin -> mediatek/mt7601u.bin` |
| `firmware-atheros` | `htc_9271.fw` (legacy name only — **no** `ath9k_htc/-1.4.0` variant observed inside this `.deb`) |
| `firmware-misc-nonfree` | none of our targets anymore (mt7601u moved out) |

Metapackages `firmware-linux` / `firmware-linux-nonfree` exist in the same
component **[local]**. Note the Debian↔Ubuntu divergence on AR9271 (Ubuntu has
the 1.4.0 blob, Debian trixie showed only the legacy name): package contents are
a runtime lookup, never a constant.

Older releases (≤ bookworm) used the same package names but lived in
`non-free` before the `non-free-firmware` component was introduced
`[unverified — not re-sourced this session]`.

### 3.3 Fedora / Arch — resolution commands, not hardcoded names

Fedora ships `linux-firmware` and splits per-family subpackages; Arch ships a
monolithic `linux-firmware` (plus an optional whence-docs split). Exact current
subpackage names were **not** fetched this session `[unverified]`; the tool
must resolve at runtime:

```sh
# Fedora / RPM family
dnf provides '*/lib/firmware/rtlwifi/rtl8188eufw.bin'
rpm -qf /usr/lib/firmware/rtlwifi/rtl8188eufw.bin          # installed?

# Arch
pacman -Fy && pacman -F 'rtl8188eufw.bin'                  # which pkg owns file
pacman -Qo /usr/lib/firmware/htc_9271.fw                   # installed?
```

### 3.4 Detecting the package manager present on the host

Order: read `/etc/os-release` (`ID=`/`ID_LIKE=`), then confirm the binary
exists. Never assume (SPEC §5):

| Signal | Resolver command (read-only) |
|---|---|
| `apt` present (Debian/Ubuntu) | `dpkg -S /lib/firmware/<file>` ; offline: `apt-file search <file>` (if installed) or Contents index |
| `dnf`/`rpm` present (Fedora/RHEL) | `dnf provides '*<file>'` ; `rpm -qf <path>` |
| `pacman` present (Arch) | `pacman -Fy && pacman -F <basename>` ; `pacman -Qo <path>` |

---

## 4. Integrity: what officially exists upstream

Verified **[local]** on 2026-08-22 against the live infrastructure:

1. **Release tags are annotated AND PGP-signed.** Fetched tag object `20260810`
   from the upstream repo; `git cat-file -p` shows
   `tagger Josh Boyer <jwboyer@kernel.org>` followed by a `-----BEGIN PGP
   SIGNATURE-----` block. With the signer's key fetched from
   `keyserver.ubuntu.com`, `git verify-tag 20260810` returned:
   ```text
   gpg: Good signature from "Josh Boyer <jwboyer@kernel.org>" [unknown]
   ```
   Signing fingerprint: `4CDE8575E547BF835FE15807A31B6BD72486CFD6`. Tag → commit:
   `20260810 → 2135b2f7714a3a514c989b9728f51f36144cab6f` (`git ls-remote`).
2. **Tarballs are published with detached signatures and a signed checksum
   file.** The kernel.org directory lists, next to every release tarball, a
   `.tar.sign`, and a directory-wide `sha256sums.asc`:[4]
   ```text
   linux-firmware-20260810.tar.gz / .tar.xz / .tar.sign
   ...
   sha256sums.asc
   ```
3. **There is no per-file hash manifest inside the git tree itself**
   (`git ls-tree -r HEAD | grep -iE 'sha256|md5|sum'` finds only unrelated
   toolchain files **[local]**) — per-file hashes must be computed by us from a
   pinned ref.

### 4.1 Secure acquisition policy (product rule)

- **Never download a loose `.bin` from a mirror/search result.** Allowed
  origins only: (a) the distro package manager (integrity enforced by the
  distro's repo signatures), or (b) an upstream git checkout pinned to a
  **signed tag** (verify with `git verify-tag` against kernel.org keyring) or an
  explicit commit hash recorded in the transaction.
- Record in every repair transaction (SPEC §24 fields): origin URL, resolved
  package/version **or** upstream tag+commit, per-file SHA-256, licence id.
  Offline hash cross-check against upstream is deterministic:
  `git cat-file blob <pinned-commit>:<fw-path> | sha256sum`.
- Tarball route (if ever needed) must verify `sha256sums.asc` GPG signature
  before trusting any digest.[4]
- A file already present on disk is validated by comparing its SHA-256 to the
  pinned-ref blob hash — never by "looks plausible".

---

## 5. Licensing and redistribution

WHENCE's own header frames everything: it documents "origin and licensing
information, if known" — the *if known* matters; absence of a `Licence:` line
means no declared basis, not permission.[1]

Upstream also maintains `LICENSE-CRITERIA.md`, describing which licences the
project accepts for submissions — useful context that these terms are actively
governed, not historical accident.[5]

### 5.1 Key clauses from the actual licence texts governing our targets

Fetched verbatim from `LICENSES/` at upstream HEAD **[local]**:

**LICENCE.rtlwifi_firmware.txt (Realtek — covers rtlwifi/*.bin and rtl_bt/*.bin):**

```text
Redistribution.  Redistribution and use in binary form, without
modification, are permitted provided that the following conditions are
met:
* Redistributions must reproduce the above copyright notice and the
  following disclaimer in the documentation and/or other materials
  provided with the distribution.
* Neither the name of Realtek Semiconductor Corporation nor the names of its
  suppliers may be used to endorse or promote products derived from this
  software without specific prior written permission.
* No reverse engineering, decompilation, or disassembly of this software
  is permitted.
```

**LICENCE.ralink_a_mediatek_company_firmware (Ralink/MediaTek — mt7601u.bin):**
same structure: binary-form redistribution without modification permitted,
copyright notice reproduction required, no reverse engineering, limited patent
grant. **[local]**

**LICENCE.atheros_firmware (binary-only family — htc_9271.fw v1.3.1 et al.):**
binary-form redistribution without modification permitted; patent grant is
explicitly scoped to use "in conjunction with an Atheros Chipset". **[local]**

**LICENCE.open-ath9k-htc-firmware (ath9k_htc/htc_9271-1.4.0.fw):** different
class — "Free software" per WHENCE; source-available (public repository
`https://github.com/qca/open-ath9k-htc-firmware` referenced in the licence text
itself) and allows redistribution in source **and binary form, with or without
modification**, subject to the stated conditions. **[local]**[1]

### 5.2 What this permits, and what this product does anyway

Permitted by the licences above (when reproduced with their notices):
redistribution of unmodified binaries — which is exactly why distros may ship
them. Prohibited: modification, reverse engineering, use of vendor names;
entries without any `Licence:` line carry no grant at all.

**Product decision (SPEC §3, IDEIA "limites"):** we redistribute nothing and
host nothing. The tool reports origin + licence and delegates acquisition to the
distro package manager or the user's direct download from the official source.
This sidesteps the entire legal surface while keeping the diagnosis fully
deterministic.

---

## 6. Resolution pipeline (spec-shaped summary)

```text
filename (dmesg / modinfo -F firmware)
  → normalize: strip .zst/.xz suffix, resolve WHENCE Link: aliases
  → WHENCE @ pinned upstream commit: {consumer driver, version, licence}
  → licence gate: declared redistributable? else UNKNOWN
  → package layer: dpkg -S / dnf provides / pacman -F  → owning package
  → if absent: propose install via the distro package manager ONLY
      (never curl a raw blob; never host it ourselves)
  → verify installed file SHA-256 against pinned upstream blob
  → reload module → functional radio check (SPEC §25)
UNKNOWN when: file absent from WHENCE · entry lacks Licence ·
no owning package found · hash mismatch after install.
```

---

## 7. Verification log (this session)

| Check | Result |
|---|---|
| WHENCE fetched from upstream `plain/WHENCE` (10,672 lines) | OK — excerpts embedded above |
| WHENCE parsed programmatically | 257 entries; coverage stats §1.3 |
| Kernel `fw_path[]` read from torvalds tree `main.c` | OK — verbatim §2 |
| Ubuntu noble `linux-firmware` .deb downloaded & inspected | all targets present (zst) §3.1 |
| Ubuntu Contents-arm64.gz greps | firmware-ath9k-htc split pkg confirmed §3.1 |
| Debian trixie firmware-{realtek,mediatek,misc-nonfree,atheros} debs inspected | mappings §3.2 |
| linux-firmware clone @ `8c7fac62c0d1` | LICENSES/ layout, no hash manifests §1.2, §4 |
| Tag `20260810` GPG verification | **Good signature** (Josh Boyer, kernel.org) §4 |
| cdn.kernel.org release dir listing | `.tar.sign` + `sha256sums.asc` present §4 |

Host context: Ubuntu 24.04.4 LTS arm64 VM; the host itself has **no**
linux-firmware installed (`dpkg -l | grep -i firmware` shows only fwupd) —
which is why upstream/archive evidence was pulled fresh instead of reading local
copies.

---

## Sources

<!-- rendered from citation ledger; see ids in prose -->

