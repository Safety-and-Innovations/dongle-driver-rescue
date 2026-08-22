"""Synthetic pnputil output fixture, faithful to documented format.

Format per windows-diagnostics.md §1.3 (Microsoft Learn pnputil syntax):
fields are 'Name:<tabs>Value', entries separated by blank lines.
"""

PNPUTIL_SAMPLE = """\
Microsoft PnP Utility

Instance ID:\t\t\t USB\\VID_0BDA&PID_8811\\5&23c4b87&0&2
Device Description:\t\t\t 802.11ac NIC
Class Name:\t\t\t Net
Status:\t\t\t ERROR
Problem Code:\t\t\t 28
Hardware IDs:\t\t\t USB\\VID_0BDA&PID_8811 USB\\VID_0BDA&PID_C811
Compatible IDs:\t\t\t USB\\Class_FF\\Vendor_0BDA

Instance ID:\t\t\t USB\\VID_148F&PID_7601\\5&23c4b87&0&3
Device Description:\t\t\t MT7601U Wireless Adapter
Class Name:\t\t\t Net
Status:\t\t\t OK
Hardware IDs:\t\t\t USB\\VID_148F&PID_7601 USB\\VID_148F&PID_7601&MI_00

Instance ID:\t\t\t USB\\VID_0A12&PID_0001\\6&1f4d2c3&0&4
Device Description:\t\t\t CSR8510 A10
Class Name:\t\t\t Bluetooth
Status:\t\t\t OK
"""

SAMPLE_DEVICES = [
    {
        "instance_id": "USB\\VID_0BDA&PID_8811\\5&23c4b87&0&2",
        "status": "ERROR",
        "problem": 28,
    },
    {
        "instance_id": "USB\\VID_148F&PID_7601\\5&23c4b87&0&3",
        "status": "OK",
    },
    {
        "instance_id": "USB\\VID_0A12&PID_0001\\6&1f4d2c3&0&4",
        "status": "OK",
    },
]
