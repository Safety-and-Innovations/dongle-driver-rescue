# CSR8510 Genuine-vs-Clone Detection Research

## (a) VID:PID-Based Detection Is Impossible

**Confirmed:** The Linux `btusb` driver matches all CSR BlueCore devices by a single hardcoded VID:PID entry:

```c
// /tmp/dynid/btusb.c:182
{ USB_DEVICE(0x0a12, 0x0001), .driver_info = BTUSB_CSR },
```

Every CSR8510 dongle — genuine or clone — reports `0a12:0001`. This is because clones deliberately squat the original Cambridge Silicon Radio ID. The VID/PID alone cannot distinguish real from fake hardware.

## (b) LMP-Based Detection Procedure

The Linux kernel uses **HCI Read Local Version Information** to detect clones by comparing three fields:

| Check | Logic | Source |
|-------|-------|--------|
| Manufacturer code | Must equal `10` (CSR) | `btusb_setup_csr()` line 2579 |
| HCI rev == LMP subver | Both store the same firmware build number | line 2580 |
| Firmware number vs BT version | Firmware too low for claimed BT version | lines 2594-2612 |

### Detection Algorithm (from btusb.c:2567-2618)

```c
// Line 2579-2581: Primary check
if (manufacturer != 10 || hci_rev != lmp_subver)
    is_fake = true;

// Line 2594-2612: Firmware/BT-version mismatch checks
// e.g., LMP subver 0x73 = BT 1.1 only; if HCI reports BT 4.0, it's fake
else if (lmp_subver <= 0x034e && hci_ver > BLUETOOTH_VER_1_1)
    is_fake = true;
// ... etc
```

### Known Fake bcdDevice Values
```
0x0100, 0x0134, 0x1915, 0x2520, 0x7558, 0x8891
```
(Source: btusb.c:2569)

### LMP Subversion Reference Table (btusb.c:2583-2588)

| BT Version | Known Genuine LMP Subversions |
|------------|-------------------------------|
| 1.1 | 0x0073, 0x020d, 0x033c, 0x034e |
| 1.2 | 0x04d9, 0x0529 |
| 2.0 | 0x07a6, 0x07ad, 0x0c5c |
| 2.1 | 0x149c, 0x1735, 0x1899 |
| 4.0 | 0x1d86, 0x2031, **0x22bb** |

**Genuine CSR8510 A10**: `LMP ver=9 subver=22bb` (0x22bb = Bluetooth 4.0)

### btmon Command Sequence
```bash
btmon --trace
# Then plug in dongle; watch for:
# HCI Event: Command Complete (0x0e) plen 12
# Read Local Version Information (0x04|0x0001)
```

Or check dmesg:
```bash
dmesg | grep -i "csr\|bluetooth"
# Output: "CSR: Setting up dongle with HCI ver=X rev=XXXX; LMP ver=X subver=XXXX; manufacturer=Y"
```

### Sources
- Linux kernel: `net/bluetooth/btusb.c` (lines 2533-2670)
- Kernel commit: `cde1a8a` - "Bluetooth: btusb: Fix and detect most of the Chinese Bluetooth controllers"
- Fix repo: https://github.com/hhsnake/csr8510-fix

## (c) READY FOR CHIPSETS.JSON Fragment

```json
{
  "chipset": "CSR8510",
  "notes": "clone-detection-via-LMP",
  "evidence": [
    "VID:PID 0a12:0001 is generic and shared by clones (btusb.c:182)",
    "Kernel detects clones via HCI Read Local Version (btusb.c:2544)",
    "Genuine CSR: manufacturer==10 AND hci_rev==lmp_subver (btusb.c:2579-2580)",
    "Known fake bcdDevices: 0x0100, 0x0134, 0x1915, 0x2520, 0x7558, 0x8891 (btusb.c:2569)",
    "Genuine CSR8510 A10 LMP subver: 0x22bb for BT 4.0 (hhsnake/csr8510-fix)",
    "Fake with LMP 0x73 claiming BT 4.0 is dead giveaway (kernel commit cde1a8a)"
  ],
  "confidence": "HIGH"
}
```

## Summary

- **VID:PID alone is useless** for clone detection — clones squat `0a12:0001`
- **LMP-based detection works** by checking: (1) manufacturer code == 10, (2) HCI rev == LMP subver, (3) firmware version is consistent with claimed BT version
- **Genuine CSR8510** reports `LMP subver=0x22bb` with `manufacturer=10`
- **Clones** typically show mismatched HCI rev/LMP subver, wrong manufacturer, or firmware numbers inconsistent with claimed Bluetooth version
- Linux kernel already implements this detection; user-space can query via `btmon` or dmesg
