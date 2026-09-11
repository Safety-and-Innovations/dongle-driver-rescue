# Research — MediaTek/Ralink (mt7601u + mt76 family) & Atheros (AR9271)

| Field | Value |
|---|---|
| Document | `docs/research/mediatek-atheros.md` |
| Date | 2026-08-22 |
| Revision | 2 (replaces the rev. 1 draft; corrects the ath9k_htc 1.4.0 firmware licence and closes the kernel versions that were UNKNOWN) |
| Responsible | forg3 |

Project rule (docs/SPEC.md §28): fact without citation/evidence = `UNKNOWN`.
Markers used below: **CONFIRMED** (verified in this session, embedded output),
**HIGH_CONFIDENCE** (primary source read, no local execution),
`[unverified]` (claim without attached primary source).

## 0. Method and sources

Three independent evidence chains, all primary source:

1. **Local host** — `modinfo` run against the real tree
   `/lib/modules/6.17.0-1020-oracle` (installed kernel, not the running one — see
   §8) and `grep` on `/lib/modules/6.17.0-1020-oracle/modules.alias`.
2. **Kernel code** — files downloaded from the canonical git
   `git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git` (`plain`
   endpoint, `master` branch) + shallow sparse clone for `#define` resolution.
3. **Entry version via tag probing** — for each key file, the
   same `plain/<file>?h=vX.Y` was queried on consecutive
   torvalds/linux tags; the 404→200 boundary delimits the merge window. This method
   uses only the canonical repository and is reproducible.

`WHENCE` cited is the `plain/WHENCE` from
`git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git`
(master as of this session, 10,672 lines; line numbers refer to that copy).

---

## 1. MT7601U — dedicated in-tree driver `mt7601u`

### 1.1 Kernel entry — CONFIRMED by probing

| Path | `?h=v4.1` | `?h=v4.2` |
|---|---|---|
| `drivers/net/wireless/mediatek/mt7601u/usb.c` | HTTP 404 | HTTP 200 |

Merge window: **kernel 4.2** (2015).

### 1.2 USB ID table — CONFIRMED (source: `mt7601u/usb.c`, master)

```c
static const struct usb_device_id mt7601u_device_table[] = {
	{ USB_DEVICE(0x0b05, 0x17d3) },
	{ USB_DEVICE(0x0e8d, 0x760a) },
	{ USB_DEVICE(0x0e8d, 0x760b) },
	{ USB_DEVICE(0x13d3, 0x3431) },
	{ USB_DEVICE(0x13d3, 0x3434) },
	{ USB_DEVICE(0x148f, 0x7601) },     /* canonical Ralink/MediaTek */
	{ USB_DEVICE(0x148f, 0x760a) },
	{ USB_DEVICE(0x148f, 0x760b) },
	{ USB_DEVICE(0x148f, 0x760c) },
	{ USB_DEVICE(0x148f, 0x760d) },
	{ USB_DEVICE(0x2001, 0x3d04) },
	{ USB_DEVICE(0x2717, 0x4106) },
	{ USB_DEVICE(0x2955, 0x0001) },
	{ USB_DEVICE(0x2955, 0x1001) },
	{ USB_DEVICE(0x2955, 0x1003) },
	{ USB_DEVICE(0x2a5f, 0x1000) },
	{ USB_DEVICE(0x7392, 0x7710) },
	{ 0, }
};
```

Host corroboration (REAL output, 1020 tree): `modinfo mt7601u.ko.zst` →

```text
license:        GPL
description:    MediaTek MT7601U USB Wireless LAN driver
firmware:       mt7601u.bin
depends:        mac80211,cfg80211
alias:          usb:v148Fp7601d*dc*dsc*dp*ic*isc*ip*in*
alias:          usb:v0B05p17D3d*dc*dsc*dp*ic*isc*ip*in*
alias:          usb:v2001p3D04d*dc*dsc*dp*ic*isc*ip*in*   (+14 others)
```

Total aliases in the 1020 tree: **17** — 1:1 match with the code table.
Note: **no 0BDA ID** belongs to mt7601u; Realtek VID on this chipset does not
exist in the upstream tables (the "0BDA?" hypothesis from the brief is refuted by the
primary source).

### 1.3 Requested firmware — CONFIRMED

`mt7601u/usb.h` (master, line 11):

```c
#define MT7601U_FIRMWARE	"mt7601u.bin"
```

`mt7601u/mcu.c` (master, lines 405–430) — the driver tries two paths:

```c
static const char * const mt7601u_fw_paths[] = {
	"mediatek/" MT7601U_FIRMWARE,
	MT7601U_FIRMWARE,
};
...
	for (i = 0; i < MT7601U_FIRMWARE_PATHS; i++) {
		ret = request_firmware(&fw, mt7601u_fw_paths[i], dev->dev);
		if (ret == 0)
			break;
	}
	if (ret)
		return ret;
```

About "**MT765023ROM**": that name **does not appear** in either `mcu.c`/`usb.h` at
`v4.2` or on master — in both, the request is literally `mt7601u.bin`.
The MT765023ROM name circulates as a vendor-SDK ROM identifier
`[unverified]`; for the product, the only relevant name is what the module requests
(`mt7601u.bin`, also confirmed by `MODULE_FIRMWARE()` in `usb.c:364`,
which feeds the modinfo `firmware:` field).

### 1.4 Messages on missing/corrupt — CONFIRMED (code strings)

| Layer | Exact message | Origin |
|---|---|---|
| Firmware core | `Direct firmware load for mt7601u.bin failed with error -2` | canonical pattern, documented in `docs/research/linux-kernel.md` §6 (`fw_main.c:903`); `-2` = ENOENT |
| Driver (invalid image) | `Invalid firmware image` → `-ENOENT` | `mcu.c:499` |
| Driver (upload) | `Error: firmware upload timed out` / `Error: firmware upload urb failed:%d` | `mcu.c:318/323` |
| Success | `Firmware Version: %d.%d.%02d Build: %x Build time: %.16s` | `mcu.c:453` |

### 1.5 Anti-relabel hook in the probe itself — CONFIRMED

`mt7601u/usb.c` (`mt7601u_probe`, master):

```c
	asic_rev = mt7601u_rr(dev, MT_ASIC_VERSION);
	mac_rev = mt7601u_rr(dev, MT_MAC_CSR0);
	dev_info(dev->dev, "ASIC revision: %08x MAC revision: %08x\n",
	 asic_rev, mac_rev);
	if ((asic_rev >> 16) != 0x7601) {
		ret = -ENODEV;
		goto err;
	}
```

Even if an ID is injected via `new_id`, the hardware must answer with
ASIC revision `7601xxxx` — a direct silicon read, immune to the box label.
Expected success log in dmesg: `ASIC revision: ...`.

### 1.6 Firmware licence (WHENCE:1673–1679) — HIGH_CONFIDENCE

```text
File: mediatek/mt7601u.bin
Version: 34
Link: mt7601u.bin -> mediatek/mt7601u.bin

Licence: Redistributable. See LICENCE.ralink_a_mediatek_company_firmware for details

Downloaded from http://www.mediatek.com/en/downloads/
```

The root symlink explains why both paths in `mt7601u_fw_paths[]`
work with a single package.

---

## 2. MT7610U / MT7612U — `mt76` family (`mt76x0u` / `mt76x2u`)

### 2.1 Entry versions — CONFIRMED by probing

| Path | previous tag (404) | next tag (200) | Window |
|---|---|---|---|
| `mt76/Makefile` + `mt76/mt76.h` (core, PCIe) | v4.15 | v4.16 | **4.16** |
| `mt76/mt76x0/usb.c` (MT7610U USB) | v4.18 | v4.19 | **4.19** |
| `mt76/mt76x2/usb.c` (MT7612U USB) | v4.19 | v4.20 | **4.20** |
| `mt76/mt7921/usb.c` (MT7921AU USB) | v5.17 | v5.18 | **5.18** (§3) |

Real content of `Makefile @v4.16` (confirms it is the mt76 core, not a homonymous header):

```make
obj-$(CONFIG_MT76_CORE) += mt76.o
obj-$(CONFIG_MT76x2E) += mt76x2e.o
```

### 2.2 Requested firmwares — CONFIRMED (real modinfo, 1020 tree)

```text
===== mt76x0u =====
firmware:       mediatek/mt7610u.bin
firmware:       mediatek/mt7610e.bin
depends:        mt76x02-usb,mt76x0-common,mt76x02-lib,mt76,mac80211,mt76-usb
(total 25 aliases)

===== mt76x2u =====
license:        Dual BSD/GPL
author:         Lorenzo Bianconi <lorenzo.bianconi83@gmail.com>
firmware:       mt7662_rom_patch.bin
firmware:       mt7662.bin
depends:        mt76x02-usb,mt76,mt76x02-lib,mt76x2-common,mac80211,mt76-usb
(total 15 aliases)
```

Corresponding defines in the source (master): `mt76x0/mt76x0.h:23–26`
(`MT7610E_FIRMWARE "mediatek/mt7610e.bin"`, `MT7650E_FIRMWARE
"mediatek/mt7650e.bin"` — PCIe-only — and `MT7610U_FIRMWARE
"mediatek/mt7610u.bin"`) and `mt76x2/mt76x2.h:19–20`
(`MT7662_FIRMWARE "mt7662.bin"`, `MT7662_ROM_PATCH "mt7662_rom_patch.bin"`).
The mt76x2u names are root-level (no `mediatek/` prefix) because
linux-firmware itself publishes `mt7662*.bin -> mediatek/mt7662*.bin` symlinks
(WHENCE:6091–6097) — same solution as mt7601u.

Fine detail captured in the code (`mt76x0/usb_mcu.c:75–79`): the USB path
tries **first** the equivalent PCIe-chip firmware (`mt7610e.bin`) and only
then falls back to `mt7610u.bin` — which is why both appear in modinfo.
The detector must accept either as "satisfies the request".

### 2.3 Difference from the old out-of-tree drivers

| Aspect | Out-of-tree MediaTek SDK (`mt7610u_sta`/`mt7612u_sta` `[unverified]` names) | In-tree `mt76x0u`/`mt76x2u` |
|---|---|---|
| Build | DKMS + kernel headers + compiler | none; module ships in the `linux-modules-extra` package |
| Framework | SDK's own stack | native mac80211/cfg80211 |
| Firmware | manufacturer-CD binaries, own paths | linux-firmware files (`mediatek/*`, `mt7662*.bin`) with WHENCE-declared licence |
| New IDs | manual patch | upstream commit (kernel-versioned table) |
| State B (ID off-table) | `new_id` usually works | same; mechanism in `docs/research/linux-kernel.md` §3 |

Product consequence: for State E on these chipsets, the correct recommendation
is a **kernel/distro upgrade**, not DKMS — since 4.20 every MT7612U has a
maintained in-tree driver.

---

## 3. MT7921AU — `mt7921u`

### 3.1 Minimum kernel — CONFIRMED by probing

`mt76/mt7921/usb.c`: HTTP 404 on `v5.17`, HTTP 200 on `v5.18` → USB support
entered in the **kernel 5.18 window** (2022). Declarable minimum kernel: **5.18**
(distro with backport may have it earlier; detect via the running kernel's
`modules.alias`, never by nominal version).

### 3.2 ID table — CONFIRMED (source: `mt7921/usb.c`, master)

```c
static const struct usb_device_id mt7921u_device_table[] = {
	{ USB_DEVICE_AND_INTERFACE_INFO(0x0e8d, 0x7902, 0xff, 0xff, 0xff),
		.driver_info = (kernel_ulong_t)MT7902_FIRMWARE_WM },
	{ USB_DEVICE_AND_INTERFACE_INFO(0x0e8d, 0x7961, 0xff, 0xff, 0xff),
		.driver_info = (kernel_ulong_t)MT7921_FIRMWARE_WM },
	/* Comfast CF-952AX */
	{ USB_DEVICE_AND_INTERFACE_INFO(0x3574, 0x6211, 0xff, 0xff, 0xff), ...
	/* Netgear, Inc. [A8000,AXE3000] */
	{ USB_DEVICE_AND_INTERFACE_INFO(0x0846, 0x9060, 0xff, 0xff, 0xff), ...
	/* Netgear, Inc. A7500 */
	{ USB_DEVICE_AND_INTERFACE_INFO(0x0846, 0x9065, 0xff, 0xff, 0xff), ...
	/* TP-Link TXE50UH */
	{ USB_DEVICE_AND_INTERFACE_INFO(0x35bc, 0x0107, 0xff, 0xff, 0xff), ...
	{ },
};
```

real modinfo (1020 tree): 5 aliases, all `icFFiscFFipFF`; firmwares
`mediatek/WIFI_MT7961_patch_mcu_1_2_hdr.bin` +
`mediatek/WIFI_RAM_CODE_MT7961_1.bin`; `Dual BSD/GPL`.

### 3.3 Quirks

1. **Mandatory interface-class match** (`USB_DEVICE_AND_INTERFACE_INFO`
   with `ff/ff/ff`): an equal VID:PID with a different class does **not** match.
   The tool parser must implement the modalias `ic/isc/ip` scope,
   otherwise it generates State B false positives.
2. **Firmware selection via `driver_info`**: the same driver serves MT7921
   (`WIFI_MT7961_*_1*`) and MT7902/MT7922 — the correct file depends on the ID, and
   `driver_info` carries that decision. There is no "one firmware fits all".
3. **MT7920 variant** (`mt76/mt792x.h:55–56`): uses
   `mediatek/WIFI_MT7961_patch_mcu_1a_2_hdr.bin` (WHENCE:6231–6234) — a family
   of similar names, different content; confusing the two is a classic error.

### 3.4 WHENCE (6231–6256) — HIGH_CONFIDENCE

```text
File: mediatek/WIFI_MT7961_patch_mcu_1a_2_hdr.bin      (MT7920 variant)
File: mediatek/WIFI_RAM_CODE_MT7961_1a.bin
Licence: Redistributable. See LICENCE.mediatek for details.

File: mediatek/WIFI_MT7961_patch_mcu_1_2_hdr.bin
Version: 20260224110909a
File: mediatek/WIFI_RAM_CODE_MT7961_1.bin
Version: 20260224110949
Licence: Redistributable. See LICENCE.mediatek for details.
```

---

## 4. AR9271 — `ath9k_htc`

### 4.1 ID table — CONFIRMED (`ath/ath9k/hif_usb.c`, master)

AR9271 group (verbatim excerpt; 27 aliases in the 1020 tree):

```c
static const struct usb_device_id ath9k_hif_usb_ids[] = {
	{ USB_DEVICE(0x0cf3, 0x9271) }, /* Atheros */
	{ USB_DEVICE(0x0cf3, 0x1006) }, /* Atheros */
	{ USB_DEVICE(0x0846, 0x9030) }, /* Netgear N150 */
	{ USB_DEVICE(0x07b8, 0x9271) }, /* Altai WA1011N-GU */
	{ USB_DEVICE(0x07D1, 0x3A10) }, /* Dlink Wireless 150 */
	{ USB_DEVICE(0x13D3, 0x3327) }, /* Azurewave */
	...
	{ USB_DEVICE(0x0cf3, 0xb002) }, /* Ubiquiti WifiStation */
	{ USB_DEVICE(0x057c, 0x8403) }, /* AVM FRITZ!WLAN 11N v2 USB */
	...
	{ USB_DEVICE(0x0cf3, 0x7015),
	  .driver_info = AR9287_USB },  /* Atheros */
	{ USB_DEVICE(0x0cf3, 0x7010),
	  .driver_info = AR9280_USB },  /* Atheros */
	...
	{ USB_DEVICE(0x0cf3, 0x20ff),
	  .driver_info = STORAGE_DEVICE },
	{ },
};
```

`0CF3:20FF` = device in CD-ROM mode (ZeroCD); the driver itself performs
ejection (`send_eject_command`, code comment: "An exact copy of the
function from zd1211rw") before normal matching. Relevant detail for
State D: a "dead" AR9271 may just be in storage mode.

### 4.2 Firmware — names, fallback chain and versions

Definitions (`ath9k/hif_usb.h:21–37`, master, verbatim):

```c
#define FIRMWARE_AR7010_1_1     "htc_7010.fw"
#define FIRMWARE_AR9271         "htc_9271.fw"

#define MAJOR_VERSION_REQ 1
#define MINOR_VERSION_REQ 3

#define FIRMWARE_MINOR_IDX_MAX  4
#define FIRMWARE_MINOR_IDX_MIN  3
#define HTC_FW_PATH	"ath9k_htc"
#define HTC_9271_MODULE_FW  HTC_FW_PATH "/htc_9271-" \
		__stringify(MAJOR_VERSION_REQ) \
		"." __stringify(FIRMWARE_MINOR_IDX_MAX) ".0.fw"
```

Selection algorithm (`hif_usb.c:1158–1218`, master): starts at
`FIRMWARE_MINOR_IDX_MAX` and descends; while `idx > 3` it requests
`ath9k_htc/htc_<chip>-1.<idx>.0.fw` (in practice `htc_9271-1.4.0.fw`);
when it reaches `idx == 3` it switches to the legacy name `htc_9271.fw`
(code comment: "stable version 1.3, **deprecated**"); below that:

```c
	} else if (hif_dev->fw_minor_index < FIRMWARE_MINOR_IDX_MIN) {
		dev_err(&hif_dev->udev->dev, "no suitable firmware found!\n");
		return -ENOENT;
```

real modinfo (1020 tree):

```text
firmware:       ath9k_htc/htc_9271-1.4.0.fw
firmware:       ath9k_htc/htc_7010-1.4.0.fw
license:        Dual BSD/GPL
depends:        ath9k_hw,ath9k_common,ath,mac80211,cfg80211
```

### 4.3 1.3 vs 1.4 and openfw compatibility — CORRECTION of rev. 1

WHENCE (296–308), verbatim:

```text
File: htc_9271.fw
Version: 1.3.1
File: htc_7010.fw
Version: 1.3.1

Licence: Redistributable. See LICENCE.atheros_firmware for details

File: ath9k_htc/htc_7010-1.4.0.fw
Version: 1.4.0
File: ath9k_htc/htc_9271-1.4.0.fw
Version: 1.4.0

Licence: Free software. See LICENCE.open-ath9k-htc-firmware for details
```

Correct reading (rev. 1 of this document had the licences inverted — error corrected):

- **Legacy 1.3.1** (`htc_9271.fw`, root): proprietary redistributable blob
  (`LICENCE.atheros_firmware`); the kernel still accepts it as a last resort
  (`MINOR_IDX_MIN == 3`), but it is deprecated.
- **1.4.0** (`ath9k_htc/htc_9271-1.4.0.fw`): this is **openfw** — free firmware,
  built from QCA's open-ath9k-htc-firmware project
  (`LICENCE.open-ath9k-htc-firmware`). It is first in the request chain.
- openfw↔1.3 compatibility: the driver reports/requires major 1 minor ≥ 3
  (`MINOR_VERSION_REQ 3`); openfw builds published with version 1.3 are
  accepted by the same chain `[unverified]` — the contract verifiable in code
  is the `MAJOR_VERSION_REQ/MINOR_VERSION_REQ` pair, not the file.

### 4.4 Behaviour when firmware is missing — CONFIRMED

Async chain: `request_firmware_nowait(...)` → `!fw` callback → new
attempt with the next name → chain exhausted:

1. `Direct firmware load for ath9k_htc/htc_9271-1.4.0.fw failed with error -2`
   (core, one line per attempted name);
2. `ath9k_htc: Failed to get firmware <name>` (`hif_usb.c`, callback);
   or `ath9k_htc: Async request for firmware <name> failed` (enqueue failure);
3. `no suitable firmware found!` + `-ENOENT`;
4. `ath9k_hif_usb_firmware_fail()` → `device_release_driver(dev)` — the
   device is **detached** from the driver. External symptom: interface disappears /
   nothing is created, no panic. Fix: install the firmware package and
   reconnect/rebind (the driver does not re-probe by itself after release).

---

## 5. Consolidated table — representative VID:PID → module → firmware → licence

Sources: `usb_device_id` tables cited per section + real modinfo (1020 tree) +
WHENCE master. Confidence per SPEC §28.

| Chipset | Representative VID:PID (primary source) | Module (min kernel) | Requested firmware (modinfo) | Licence (WHENCE) | Confidence |
|---|---|---|---|---|---|
| MT7601U | `148F:7601`, `148F:760A/B/C/D`, `0E8D:760A/B`, `13D3:3431/3434`, `2001:3D04`, `2717:4106`, `2955:0001/1001/1003`, `2A5F:1000`, `7392:7710`, `0B05:17D3` | `mt7601u` (4.2) | `mt7601u.bin` (v34) | `LICENCE.ralink_a_mediatek_company_firmware` (Redistributable) | CONFIRMED |
| MT7610U | `0E8D:7610`, `148F:7610`, `148F:761A`, `148F:760A`, `13B1:003E`, `7392:A711/B711/C711`, `2357:0105/010B/0123`, `0DF6:0075/0079`, `2019:AB31`, `2001:3D02`, `0586:3425`, `07B8:7610`, `04BB:0951`, `057C:8502`, `293C:5702`, `20F4:806B`, `0B05:17D1/17DB` | `mt76x0u` (4.19; mt76 core 4.16) | `mediatek/mt7610u.bin`, `mediatek/mt7610e.bin` (E→U fallback) | `LICENCE.mediatek` (Redistributable) | CONFIRMED |
| MT7612U | `0E8D:7612`, `0E8D:7632`, `7392:B711`, `0B05:180B/1833/17EB`, `057C:8503`, `0846:9014/9053`, `045E:02E6/02FE`, `2357:0137`, `2C4E:0103`, `056E:400A`, `0471:2126/7600` | `mt76x2u` (4.20) | `mt7662.bin` (v1.9) + `mt7662_rom_patch.bin` (v0.0.2_P69) | `LICENCE.ralink_a_mediatek_company_firmware` (Redistributable) | CONFIRMED |
| MT7921AU | `0E8D:7961`, `3574:6211` (Comfast CF-952AX), `0846:9060/9065` (Netgear), `35BC:0107` (TP-Link TXE50UH) — all `icFFiscFFipFF` | `mt7921u` (5.18) | `mediatek/WIFI_MT7961_patch_mcu_1_2_hdr.bin` + `mediatek/WIFI_RAM_CODE_MT7961_1.bin` | `LICENCE.mediatek` (Redistributable) | CONFIRMED |
| AR9271 | `0CF3:9271`, `0CF3:1006`, `0CF3:B002/B003`, `07B8:9271`, `0846:9030`, `07D1:3A10`, `13D3:3327…3350`, `057C:8403`, `0471:209E`, `1EDA:2315`, `040D:3801`, `04CA:4605`; ZeroCD `0CF3:20FF`; AR9280 group `0CF3:7010/7015` etc. | `ath9k_htc` (ancient; ≥3.x) | `ath9k_htc/htc_9271-1.4.0.fw` → fallback `htc_9271.fw` (1.3.1) | 1.4.0: `LICENCE.open-ath9k-htc-firmware` (**Free software**); 1.3.1: `LICENCE.atheros_firmware` (Redistributable) | CONFIRMED |
| RT2870/RT3070 (reference for fake "MT76xx") | `148F:2870/3070/3071/3072`, `148F:5370/5372/5572`, `148F:3572/3573`, `8516:2070…3572`, `0B05:1732/1742/1760/1761/1784/1790/17A7/17AD/17BC/17E8` (real subset) | `rt2800usb` (≥2.6.31) | `rt2870.bin` (v36) | `LICENCE.ralink-firmware.txt` (Redistributable) | CONFIRMED (modinfo + WHENCE:1708–1714) |

Debian packages pointed at in rev. 1 (`firmware-mediatek`,
`firmware-atheros`, today also the new unified `linux-firmware`) remain
valid; the `dpkg-deb` verification done then is still recorded in
`git log` (commit `8dda872`).

---

## 6. Known pitfalls

### 6.1 Real ID collisions between modules (same alias, two owners)

`modules.alias` scan of the 1020 tree (evidence with line numbers):

| Alias | Contenders | Evidence |
|---|---|---|
| `usb:v148Fp760Ad*` | `mt7601u` **and** `mt76x0u` | both in the alias list (§1.2, §2.2); in the code: `USB_DEVICE(0x148f, 0x760a)` in both drivers |
| `usb:v7392pB711d*` | `mt76x0u` **and** `mt76x2u` | same; divergent comments ("Edimax/Elecom" × "Edimax EW 7722 UAC") |
| `usb:v0471p2126d*` | `mt76x2u` **and** `rt2800usb` | `modules.alias:17835` (mt76x2u, "LiteOn WN4516R module") × `:18108` (rt2800usb) |
| `usb:v13B1p0043d*` (outside MTK/Ath scope, inter-family example) | `rtw88_8822bu` **and** `rtw88_8822cu` | `modules.alias:18649` × `:18671` |

How the kernel resolves it (observable behaviour, CONFIRMED in its consequence):
`modules.alias` maps the same alias to several modules; udev/kmod loads
all candidates, and the USB core binds the device to the first registered driver
whose `id_table` matches — order depends on the load sequence
(initramfs/distro), therefore **not a hardware property** `[unverified]`
for the internal kmod details; what is verifiable is the result: the
bound driver visible in `/sys/.../driver` may vary between systems.

Mandatory rule for the tool: **one VID:PID → zero, one or N modules**.
Diagnostics list all candidates; the arbiter is the interface node's `driver` symlink
plus the real probe `dmesg`. Repair never assumes a single candidate.

### 6.2 "MT7601"-relabelled dongles

- Driver defence: ASIC revision `0x7601` check in probe (§1.5) —
  wrong silicon becomes `-ENODEV` even with an injected ID.
- Tool defence: cross-check bcdDevice + interface class + register
  response (when a driver is bound) before asserting chipset; commercial
  label is never evidence (SPEC §7).
- `148F:760A` case: legitimate ID in **two** generations (mt7601u and mt76x0u) —
  disambiguate by interface class and probe response.

### 6.3 Fake "MT76xx" on old Ralink silicon

RT28xx/RT33xx/RT53xx/RT55xx-family IDs belong to `rt2800usb`
(§5 table, last row). Dongle sold as "MT7601 AC600" with ID
`148F:3070` is rt2870-era Ralink: the right driver is `rt2800usb` + `rt2870.bin`,
and promising 802.11ac is label lying. Classification: the detector decides by
ID (SPEC §7), records `SUSPECTED_CLONE` when descriptors diverge from those
expected for the chipset (SPEC §10).

### 6.4 ZeroCD on AR9271

`0CF3:20FF` is storage mode; the driver ejects and would re-enumerate. If ejection fails
(virtual machine, bad USB slot), diagnostics should suggest `usb_modeswitch`
or another port before concluding State E.

---

## 7. Handoff

**What changed** — Rev. 2 fully replaces rev. 1: (a) closed the
kernel windows that were UNKNOWN (mt76 core 4.16; mt76x0u 4.19;
mt76x2u 4.20; mt7921u 5.18; mt7601u 4.2) via tag probing on the canonical
repository; (b) corrected the inverted ath9k_htc licences (1.4.0 = openfw/free
software; 1.3.1 = deprecated redistributable blob); (c) added the verbatim
ID tables for four drivers, the ath9k_htc firmware fallback chain,
the mt7601u anti-relabel hook and three real ID collisions
with line evidence.

**How it was verified** — real `modinfo` against `/lib/modules/6.17.0-1020-oracle`
(output embedded above); `grep` on that tree's `modules.alias`; source files
downloaded from `git.kernel.org` (torvalds/linux and linux-firmware, `plain`
endpoints, explicit tags); every version claim backed by an
HTTP 404/200 pair on consecutive tags. Items without an attached source are marked
`[unverified]`.

**What unblocks next** — (1) per-chipset minimum-kernel matrix ready for
`SUPPORTED_OS.md` and State C fixtures (exact per-module firmware names);
(2) modalias parser with `ic/isc/ip` scope specified (mt7921u case);
(3) multi-candidate disambiguation rule for the diagnostic engine
(§6.1 collisions); (4) canonical dmesg messages for the State C detector
already catalogued per layer (core × driver).

**What risk remains** — (1) WHENCE line numbers drift with upstream;
re-pull the file when the detector is implemented; (2) the internal
kmod ordering mechanics under concurrent loads of competing modules is not a
stable contract `[unverified]` — the tool must always arbitrate by the
system's actual state, never by theory; (3) openfw builds with a reported
version ≠ 1.4 may follow different chains — validate with physical hardware
before automating ath9k_htc repair; (4) listed collisions reflect the
6.17 tree — new entries may appear with each kernel.

---

## 8. Environment note (useful negative evidence)

The **running** kernel on this host (`6.17.0-1018-oracle`) packages
none of the target modules (`modinfo mt7601u` → "Module not found";
`linux-modules-extra` missing for that release), while the
**installed** 1019/1020 trees contain all of them. Already covered as a product requirement in
`docs/research/linux-kernel.md` §6 (always resolve against `uname -r` and flag
"pending reboot"). Recorded here because it explains why the modinfo outputs
in this document explicitly use the 1020 tree.

## Sources

Primary (all consulted in this session):

- torvalds/linux, `plain` master: `drivers/net/wireless/mediatek/mt7601u/{usb.c,usb.h,mcu.c}`,
  `drivers/net/wireless/mediatek/mt76/{Makefile,mt76.h}`, `mt76/mt76x0/{usb.c,usb_mcu.c,mt76x0.h}`,
  `mt76/mt76x2/{usb.c,mt76x2.h}`, `mt76/mt7921/usb.c`, `mt76/mt792x.h`,
  `drivers/net/wireless/ath/ath9k/{hif_usb.c,hif_usb.h}`
- torvalds/linux, tag probing: same paths at `?h=v4.1…v5.18` (§2.1 table)
- linux-firmware, `plain/WHENCE` master (lines 296–308, 1673–1679, 1708–1714,
  6079–6103, 6231–6256)
- Host: `/lib/modules/6.17.0-1020-oracle/` — `modinfo` (embedded outputs §1.2,
  §2.2, §3.2, §4.2) and `modules.alias` (lines 17835, 18108, 18649, 18671)
