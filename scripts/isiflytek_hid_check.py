#!/usr/bin/env python3
"""Check whether a HID report map contains the iFLYTEK "smart_ctrl" fingerprint
that libxdriver_xiri_d.so's isIflytekDev() requires.

The 31-byte signature is a 31-byte vendor Output report followed by a 31-byte
Input report (usage range 0x00-0x1F, 8-bit), ending with End Collection. On a
CMCC box, svciflybl/libxdriver scan every hidraw descriptor for this pattern
("hid(%s) desc same" / "desc not same"); a device without it is ignored.

Usage:
  python isiflytek_hid_check.py --hex <report map hex>     # e.g. read of HID report map (0x2A4B)
  python isiflytek_hid_check.py --hidraw /dev/hidraw0      # Linux: read descriptor via ioctl
"""
import argparse
import struct
import sys

# 31-byte vendor Output (0x91) + Input (0x81) report pair + End Collection,
# extracted from libxdriver_xiri_d.so .rodata @0x5C4A (memcmp anchor in isIflytekDev).
SIGNATURE = bytes.fromhex(
    "150026ff001900291f7508951f9100"   # LogicalMin 0, LogicalMax 255, Usage 0..0x1F, Size 8, Count 31, Output
    "150026ff001900291f7508951f8100c0"  # same again, Input, End Collection
)


def scan(desc: bytes) -> int:
    return desc.find(SIGNATURE)


def check_hidraw(path: str) -> int:
    import fcntl

    HIDIOCGRDESCSIZE = 0x80044801
    HIDIOCGRDESC = 0x90044802
    fd = open(path, "rb", buffering=0)
    size = struct.unpack("<i", fcntl.ioctl(fd, HIDIOCGRDESCSIZE, b"\0" * 4))[0]
    buf = struct.pack("<i", size) + b"\0" * 4096
    buf = fcntl.ioctl(fd, HIDIOCGRDESC, buf)
    desc = buf[4:4 + size]
    print(f"{path}: report descriptor, {size} bytes")
    return scan(desc)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--hex", help="report map as hex string")
    g.add_argument("--hidraw", help="path to a hidraw device (Linux)")
    args = ap.parse_args()

    if args.hex:
        h = args.hex.lower().replace(" ", "").replace(":", "")
        desc, where = bytes.fromhex(h), "report map hex"
    else:
        desc, where = check_hidraw(args.hidraw), args.hidraw

    off = scan(desc)
    if off >= 0:
        print(f"{where}: iFLYTEK smart_ctrl signature FOUND at offset {off} "
              f"-> isIflytekDev would accept this device (then run the Trinity challenge)")
        return 0
    print(f"{where}: iFLYTEK smart_ctrl signature NOT FOUND "
          f"-> isIflytekDev would REJECT this device (\"hid(%s) desc not same\")")
    return 1


if __name__ == "__main__":
    sys.exit(main())
