#!/usr/bin/env python3
"""Pack STARFALL's linked overlays into STARFALL.PAK.

The pack has one TPK1 entry, DATA: "SF", the item count, a zero, then a
little-endian offset (32 bits), length (16 bits) and run address (16 bits)
for each item, then the items. The order on the command line is the order of
SF_OVL_* in examples/starfall/main.c.

AREA=FILE is an overlay. Its run address is the start of its memory area in
the label file of the link. NAME@AREA=FILE is the art of a boss, from
tools/starfall_bosses.py. It runs after everything that the overlay of AREA
uses, its variables included. Its strips and one frame slot for each part
must fit in the rest of the area.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets  # noqa: E402


def labels(path):
    """Label name to value, from an ld65 -Ln file."""
    found = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "al":
            found[parts[2].lstrip(".")] = int(parts[1], 16)
    return found


def area(symbols, name):
    """Start, last used address plus one, and end of a memory area."""
    try:
        start = symbols["__" + name + "_START__"]
        return start, symbols["__" + name + "_LAST__"], start + symbols["__" + name + "_SIZE__"]
    except KeyError:
        raise SystemExit("no memory area " + name + " in the label file") from None


def build(items, symbols):
    """The DATA entry for (name, area, art, bytes) items, in order."""
    head = bytearray(b"SF" + bytes((len(items), 0)))
    body = bytearray()
    offset = 4 + 8 * len(items)
    for name, where, art, data in items:
        start, last, end = area(symbols, where)
        if not data or len(data) > 0xFFFF:
            raise SystemExit(name + " is empty or too large")
        run = start
        if art:
            strips, slots = struct.unpack_from("<HH", data)
            if last + strips + slots > end:
                raise SystemExit(f"{name} needs {last + strips + slots - end} more bytes in the window")
            run = last
        head += struct.pack("<IHH", offset + len(body), len(data), run)
        body += data
    return bytes(head + body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True, help="label file of the link")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("item", nargs="+", help="AREA=FILE or NAME@AREA=FILE, in SF_OVL_* order")
    args = parser.parse_args()
    symbols = labels(args.labels)
    items = []
    for item in args.item:
        key, _, path = item.partition("=")
        name, _, where = key.partition("@")
        if not name or not path:
            raise SystemExit("items are AREA=FILE or NAME@AREA=FILE")
        items.append((name, where or name, bool(where), Path(path).read_bytes()))
    data = build(items, symbols)
    args.output.write_bytes(assets.pack([("DATA", data)]))
    print("STARFALL.PAK: " + ", ".join(f"{name} {len(blob)} bytes" for name, _, _, blob in items)
          + f"; {len(data)} bytes of data")


if __name__ == "__main__":
    main()
