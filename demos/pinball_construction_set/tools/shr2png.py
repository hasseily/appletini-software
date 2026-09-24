#!/usr/bin/env python3
"""Decode a 32 KB AUX $2000-$9FFF Super Hi-Res dump into a PNG.

Only the standard 320-pixel mode is decoded (what Appletini Bosconian
uses): 160 bytes per row, two 4-bit pixels per byte, high nibble on the
left; SCB at $9D00 + y (low 4 bits = palette); 16 palettes of 16 entries
at $9E00, each entry two bytes little-endian $0RGB, scaled x17 to 8 bits.

Uses only the standard library (zlib, struct), like
appletini-one/scripts/render_shr4.py.

Usage: shr2png.py IN.bin OUT.png [--scale N]
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path


BANK_SIZE = 0x8000
BASE = 0x2000
ROW_BYTES = 160
WIDTH = 320
HEIGHT = 200
SCB = 0x9D00
PALETTES = 0x9E00


def decode_rows(bank: bytes) -> list[bytes]:
    """Return 200 rows of 320 RGB pixels (960 bytes each)."""
    if len(bank) < BANK_SIZE:
        raise ValueError(f"dump is {len(bank)} bytes; need {BANK_SIZE}")

    def entry(palette: int, index: int) -> bytes:
        offset = PALETTES - BASE + palette * 32 + index * 2
        raw = bank[offset] | (bank[offset + 1] << 8)
        return bytes((((raw >> 8) & 0xF) * 17, ((raw >> 4) & 0xF) * 17,
                      (raw & 0xF) * 17))

    palettes = [[entry(p, i) for i in range(16)] for p in range(16)]
    rows = []
    for y in range(HEIGHT):
        palette = palettes[bank[SCB - BASE + y] & 0x0F]
        row = bytearray()
        offset = y * ROW_BYTES
        for byte in bank[offset:offset + ROW_BYTES]:
            row += palette[byte >> 4]
            row += palette[byte & 0x0F]
        rows.append(bytes(row))
    return rows


def write_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))

    with open(path, "wb") as out:
        out.write(b"\x89PNG\r\n\x1a\n")
        out.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        out.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        out.write(chunk(b"IEND", b""))


def convert(dump: bytes, output: Path, scale: int = 1) -> None:
    rows = decode_rows(dump)
    if scale > 1:
        scaled = []
        for row in rows:
            wide = b"".join(row[i:i + 3] * scale for i in range(0, len(row), 3))
            scaled.extend([wide] * scale)
        rows = scaled
    write_png(output, WIDTH * scale, HEIGHT * scale, rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("input", type=Path, help="32768-byte AUX $2000-$9FFF dump")
    parser.add_argument("output", type=Path, help="PNG to write")
    parser.add_argument("--scale", type=int, default=1, help="integer upscale factor")
    args = parser.parse_args(argv)
    try:
        convert(args.input.read_bytes(), args.output, max(1, args.scale))
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
