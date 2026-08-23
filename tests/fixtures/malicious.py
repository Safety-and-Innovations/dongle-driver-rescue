"""Malicious-input fixtures (SPEC §10, ADR 0002 S3/S6, SPEC §20 'malicious').

These strings are DATA. Every parser in the product must consume them without
crashing, executing, or echoing them into commands. Sources: red-team patterns
from SPEC §14 (USB metadata maliciosa, path malicioso) and S3 grammar rules.
"""

# USB string descriptors are attacker-controlled on real dongles.
MALICIOUS_USB_STRINGS = {
    "product": "802.11n\nUSB; rm -rf /\x01\x02",  # newline + control chars
    "manufacturer": "Realtek %s%s%s%n",  # format-string bait
    "serial": "../../etc/shadow",  # traversal-shaped serial
}

# Firmware names as they would appear in dmesg 'Direct firmware load for ...'
MALICIOUS_FIRMWARE_NAMES = [
    "../../../etc/shadow",  # path traversal
    "/etc/passwd",  # absolute escape
    "..\\..\\windows\\system32",  # windows-style backslash
    "rtlwifi/%s.bin",  # format specifier
    "rtlwifi/*.bin",  # glob injection
    "fw$(reboot).bin",  # command substitution bait
    "fw`id`.bin",  # backtick substitution bait
    "a" * 4096 + ".bin",  # oversized name (>4KB total line)
    "\t fw-with-leading-tab.bin",
]

# A modalias far beyond any kernel-emitted length (>4KB).
GiantModalias = "usb:v148Fp7601d0100dc00dsc00dp00icFFisc00ip00in" + "*" * 4200

DMESG_MALICIOUS_LINES = [
    f"[ 1.0] usb 1-2: Direct firmware load for {name} failed with error -2"
    for name in MALICIOUS_FIRMWARE_NAMES[:6]
]

# modprobe.d content that tries to look like a directive it is not.
MALICIOUS_MODPROBE_D = {
    "/etc/modprobe.d/evil.conf": (
        "blacklist mt7601u # blacklist rtw_8821cu\n"
        "install mt7601u /bin/false && rm -rf /\n"
        "; not-a-directive\n"
    ),
}

# Alias rows with hostile patterns (bracket globs must stay literal).
MALICIOUS_ALIAS_ROWS = [
    "alias usb:v[A-Z]*p* mt7601u",  # fnmatch-style bracket glob
    "alias usb:v148Fp760?d* mt76x0u",  # question-mark glob
    "alias usb:* ../../../evil",  # module field shaped like traversal
]
