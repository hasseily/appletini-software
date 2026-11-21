#!/usr/bin/env python3
"""Build the ONEWWW prototype: ONEWWW.SYSTEM and a bootable ProDOS disk.

Run from any folder: python demos/onewww/build_onewww.py
Needs ca65 and ld65 on PATH (or the CA65 and LD65 variables). The boot
blocks and the PRODOS kernel come from the demo disk template.
"""
import math
import os
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "appletini_demos/appletini_webserver"))
from mono_disk import BLOCK, ENTRY, extract  # noqa: E402

TEMPLATE = HERE.parent / "appletini_demos/assets/AD8088 MSDOS.hdv"
OUT = HERE / "build"


def build_disk(template, volume, files, total=280):
    """Root-only ProDOS disk of `total` blocks (140 KiB)."""
    bitmap = 6
    image = bytearray(total * BLOCK)
    image[:2 * BLOCK] = template[:2 * BLOCK]
    for number in range(2, 6):
        struct.pack_into("<HH", image, number * BLOCK,
                         number - 1 if number > 2 else 0,
                         number + 1 if number < 5 else 0)
    header = bytearray(ENTRY)
    header[0] = 0xF0 | len(volume)
    header[1:1 + len(volume)] = volume.encode("ascii")
    stamp = (26 << 9) | (11 << 5) | 21
    struct.pack_into("<H", header, 24, stamp)
    header[28:33] = bytes((0, 0, 0xE3, ENTRY, 13))
    struct.pack_into("<HHH", header, 33, len(files), bitmap, total)
    image[2 * BLOCK + 4:2 * BLOCK + 43] = header
    next_block = 7
    for slot, (name, payload, filetype, aux) in enumerate(files, 1):
        count = max(1, math.ceil(len(payload) / BLOCK))
        key = next_block
        next_block += count + (count > 1)
        first = key + (count > 1)
        if count > 1:
            for i in range(count):
                image[key * BLOCK + i] = (first + i) & 255
                image[key * BLOCK + 256 + i] = (first + i) >> 8
        image[first * BLOCK:first * BLOCK + len(payload)] = payload
        entry = bytearray(ENTRY)
        entry[0] = ((2 if count > 1 else 1) << 4) | len(name)
        entry[1:1 + len(name)] = name.encode("ascii")
        entry[16] = filetype
        struct.pack_into("<HH", entry, 17, key, count + (count > 1))
        entry[21:24] = len(payload).to_bytes(3, "little")
        struct.pack_into("<H", entry, 24, stamp)
        entry[30] = 0xE3
        struct.pack_into("<H", entry, 31, aux)
        struct.pack_into("<H", entry, 37, 2)
        at = 2 * BLOCK + 4 + slot * ENTRY
        image[at:at + ENTRY] = entry
    if next_block > total:
        raise ValueError("disk full")
    for block in range(next_block, total):
        image[bitmap * BLOCK + block // 8] |= 0x80 >> (block % 8)
    return bytes(image)


def main():
    OUT.mkdir(exist_ok=True)
    ca65 = os.environ.get("CA65", "ca65")
    ld65 = os.environ.get("LD65", "ld65")
    subprocess.run([ca65, "--cpu", "6502", "-o", str(OUT / "onewww.o"),
                    str(HERE / "onewww.s")], check=True)
    subprocess.run([ld65, "-C", str(HERE / "onewww.cfg"), "-o",
                    str(OUT / "ONEWWW.SYSTEM"), str(OUT / "onewww.o")],
                   check=True)
    program = (OUT / "ONEWWW.SYSTEM").read_bytes()
    template = TEMPLATE.read_bytes()
    disk = build_disk(template, "ONEWWW", [
        ("PRODOS", extract(template, "PRODOS"), 0xFF, 0),
        ("ONEWWW.SYSTEM", program, 0xFF, 0x2000)])
    assert extract(disk, "ONEWWW.SYSTEM") == program
    (OUT / "ONEWWW.po").write_bytes(disk)
    print(f"ONEWWW.SYSTEM {len(program)} bytes; disk {OUT / 'ONEWWW.po'}")


if __name__ == "__main__":
    main()
