# Research — Realtek Wi-Fi & Bluetooth chipsets

- **Sources:** upstream kernel source collected in `~/.research_realtek`
  (files cited as `file:line` below), complete WHENCE from linux-firmware
  (10,672 lines), local host `modules.alias` (kernel 6.17.0-oracle).
- **Rule:** every fact cites a source; without evidence = `UNKNOWN`.

## 1. Critical finding — `rtl8xxxu` rejects `new_id`

```c
static struct usb_driver rtl8xxxu_driver = {
    ...
    .id_table = dev_table,
    .no_dynamic_id = 1,
```
— `drivers_net_wireless_realtek_rtl8xxxu_core.c:8289`

**Product consequence (CONFIRMED):** State B repair by writing to
`/sys/bus/usb/drivers/rtl8xxxu/new_id` **does not work** for the whole family
covered by rtl8xxxu (RTL8188/8192/8811/8812/8821/8814 USB). The repair plan B
for these chips must declare this and point to a legitimate alternative
(rebuilding is not a V1 option; report the missing ID + official origin).
Drivers that accept `new_id`: any `usb_driver` without this flag
(mechanism in `drivers/usb/core/driver.c`, collection `/tmp/ksrc/driver.c`).

The `dev_table` has **122** `USB_DEVICE(_AND_INTERFACE_INFO)` entries
covering VID 0x0bda and OEMs (TP-Link 0x2357, D-Link 0x2001, Mercusys 0x2c4e,
Edimax 0x07b8, Netgear 0x0846 etc.) — all with interface class 0xff/0xff/0xff
on AC chips (`rtl8xxxu_core.c`, count verified via grep).

## 2. Wi-Fi — chipset → in-tree module mapping

| Chipset | In-tree module | Firmware (WHENCE:line) | Confidence |
|---|---|---|---|
| RTL8188EU | r8188eu (outside rtl8xxxu on 6.x) or rtl8xxxu | `rtlwifi/rtl8188eufw.bin` (WHENCE:3521); variant `rtl8188efw.bin` (:3356) | HIGH_CONFIDENCE |
| RTL8192EU | rtl8xxxu | via dev_table (IDs 0x818c, 2357:0107, 2019:ab33, 2001:3312...) | CONFIRMED (source: table) |
| RTL8811CU / RTL8821CU | rtl8xxxu | `rtlwifi/rtl8821aefw.bin` + `_wowlan`/`_29` (:3375-3378) | HIGH_CONFIDENCE |
| RTL8812AU / RTL8814AU | rtl8xxxu | `rtlwifi/rtl8812aefw.bin` (:3365) | HIGH_CONFIDENCE |
| RTL8192CU (legacy) | rtl8192cu (rtlwifi) | `rtl8192cufw{,_A,_B,_TMSC}.bin` (:3280-83) | CONFIRMED |

UNKNOWN / confirm at implementation time: which module claims each exact PID on
each kernel version (r8188eu was removed from mainline in 6.9 and some chips
migrated to rtl8xxxu — check against the target distro's `modules.alias` at runtime,
not here).

## 3. Bluetooth — firmware decision already in the kernel (`btrtl`)

Official `ic_id_table` — `drivers_bluetooth_btrtl.c:106` ff. Format:
`IC_INFO(lmp_subver, hci_rev, hci_ver, bus)` → `fw_name`/`cfg_name`.
Defines in `btrtl.c:25-33`; matching at `:350` (LMPSUBV/HCIREV match_flags).

| Chip | lmp_subver | hci_rev | hci_ver | Bus | Firmware |
|---|---|---|---|---|---|
| 8723A | 0x1200 | 0xb | 0x6 | USB | `rtl_bt/rtl8723a_fw` |
| 8723B | 0x8723 | 0xb | 0x6 | USB | `rtl_bt/rtl8723b_fw` + `_config` |
| 8821A | 0x8821 | 0xa | 0x6 | USB | `rtl_bt/rtl8821a_fw` + `_config` |
| 8821C | 0x8821 | 0xc | 0x8 | USB | `rtl_bt/rtl8821c_fw` + `_config` |
| 8761A | 0x8761 | 0xa | 0x6 | USB | `rtl_bt/rtl8761a_fw` + `_config` |
| 8761B | 0x8761 | 0xb | 0xa | UART | `rtl_bt/rtl8761b_fw` + `_config` |
| 8761BU | 0x8761 | 0xb | 0xa | **USB** | `rtl_bt/rtl8761bu_fw` + `_config` |
| 8761CU | 0x8761 | 0xe | — | USB | `rtl_bt/rtl8761cu_fw` + `_config` |

**RTL8761B vs BU finding (CONFIRMED):** same `lmp_subver=0x8761`,
`hci_rev=0xb`, `hci_ver=0xa` — what distinguishes them is the **bus**
(HCI_UART vs HCI_USB). "RTL8761BUV" is not a separate table entry: it is the BU
with packaging variation. Classic manual-table error avoided: copy the
kernel's decision, including the bus field.
Extra proof: the driver itself validates the project post-download and rejects mismatches
with `"firmware is for %x but this is a %x"` (`btrtl.c:747-751`).

## 4. Silicon revisions — RTL8192CU A/B/TMSC cut

WHENCE:3280-3291 declares four files and the exact provenance:

```text
rtl8192cufw_A.bin:    Rtl8192CUFwUMCACutImgArray   (UMC A-cut)
rtl8192cufw_B.bin:    Rtl8192CUFwUMCBCutImgArray   (UMC B-cut)
rtl8192cufw_TMSC.bin: Rtl8192CUFwTSMCImgArray      (fab TSMC)
```

Driver selection by hardware version: `IS_VENDOR_UMC_A_CUT(rtlhal->version)`
(`rtlwifi/rtl8192cu_hw.c:894`). For the tool: when the module exposes more than
one candidate firmware for the same chip, the diagnostic lists ALL files
the module may request (`modinfo -F firmware`) and uses the driver log
(dmesg) as arbiter of the actually requested file — never chooses alone.

## 5. CSR8510 clones

The collection captured no specific primary evidence about CSR clone detection
(divergent LMP subversion). Status: **UNKNOWN** — pointer to confirm:
`drivers/bluetooth/btusb.c` known blacklists and clone LMP reports
(technical forums; would require an experiment with physical hardware).

## 6. Local verification (host)

Host with three Oracle 6.17 kernels installed: the running one (1018) ships
no wireless/BT modules; installed 1020 ships **194 wireless modules**
(`find /lib/modules/6.17.0-1020-oracle -path '*wireless*' -name '*.ko*'`),
including `rtl8xxxu.ko`, `mt7601u.ko`, `ath9k_htc.ko`, `btusb.ko`, `btrtl.ko`
(paths verified via find on this host). Implications:

1. Test fixtures load synthetic `modules.alias` lines
   derived from these sources (not from the host).
2. Diagnostics always query the **running** kernel tree and flag
   divergence from kernels installed pending reboot.
3. "Kernel with no drivers at all" is a real State E scenario the product must
   diagnose explicitly, not an exception.
