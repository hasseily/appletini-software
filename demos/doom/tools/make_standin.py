#!/usr/bin/env python3
"""Write a tiny stand-in data set for the platform (docs/DESIGN.md section 8).

The converter (tools/wad2a2.py) writes the real build/data; until it
exists, and for the platform's own tests, this writes a data set with the
same shape and only what the kernel and the GAME skeleton read:

  DIR.1         data file: PLAYPAL, 14 palettes x 256 entries x 2 bytes
                (byte 2i = G<<4|B, byte 2i+1 = $20|R, the converter's
                PAL256 order) at DD_DIR_BANK:DD_PLAYPAL. From the WAD's
                PLAYPAL when --wad is given, else a synthetic one.
  PROBE.1       data file: the probe array, PROBE_COUNT elements of
                PROBE_SIZE bytes in chunks of 2^PROBE_LOG2 elements, one
                chunk per bank from PROBE_BANK, each at $0200. Element i
                is probe_element(i): the tests recompute it.
  doomdata.inc  DD_DIR_BANK, DD_PLAYPAL, DD_FIRST_BANK, DD_LAST_BANK (the
                converter's names) and DD_PROBE_BANK/ADDR/SIZE/LOG2/COUNT
  doomdata.h    the same as C macros
  manifest.json {"standin": true, "files": [...], ...}

Data file format (tools/wad2a2.py's, read by src/kernel/loader.s): a
256-byte header, "A2DM", version 1, segment count n (<= 49), two zero
bytes, n entries of bank u8, address u16, length u16 from +8, zero padding;
then the segments' bytes in entry order. `data_file` builds one.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

MAGIC = b"A2DM"
HEADER = 256
MAX_SEGS = 49
DIR_BANK = 2
PLAYPAL_ADDR = 0x0200
PROBE_BANK = 3
PROBE_ADDR = 0x0200
PROBE_SIZE = 4
PROBE_LOG2 = 12                 # 4,096 elements (16 KB) per chunk
PROBE_COUNT = 3 * 4096 + 100    # four chunks: banks 3, 4, 5 and a partial 6


def data_file(segments: list[tuple[int, int, bytes]]) -> bytes:
    """A data file of (bank, address, bytes) segments."""
    if not 1 <= len(segments) <= MAX_SEGS:
        raise ValueError(f"1..{MAX_SEGS} segments")
    head = bytearray(MAGIC + bytes((1, len(segments), 0, 0)))
    for bank, address, data in segments:
        if not (2 <= bank < 128 and address >= 0x0200 and data
                and address + len(data) <= 0xC000):
            raise ValueError(f"bad segment {bank}:{address:04X}+{len(data)}")
        head += struct.pack("<BHH", bank, address, len(data))
    head += bytes(HEADER - len(head))
    return bytes(head) + b"".join(data for _b, _a, data in segments)


def parse_data_file(data: bytes) -> list[tuple[int, int, bytes]]:
    """The (bank, address, bytes) segments of a data file."""
    if data[:4] != MAGIC or data[4] != 1:
        raise ValueError("not a data file")
    count = data[5]
    offset = HEADER
    out = []
    for i in range(count):
        bank, address, length = struct.unpack_from("<BHH", data, 8 + 5 * i)
        out.append((bank, address, data[offset:offset + length]))
        offset += length
    return out


def probe_element(i: int) -> bytes:
    return bytes(((i * 7) & 0xFF, (i >> 8) & 0xFF, (i * 13 + 5) & 0xFF, 0xA5 ^ (i & 0xFF)))


def probe_location(i: int) -> tuple[int, int]:
    """(bank, address) of probe element i."""
    return (PROBE_BANK + (i >> PROBE_LOG2),
            PROBE_ADDR + (i & ((1 << PROBE_LOG2) - 1)) * PROBE_SIZE)


def wad_playpal(path: Path) -> bytes:
    data = path.read_bytes()
    count, offset = struct.unpack_from("<ii", data, 4)
    for i in range(count):
        pos, size, name = struct.unpack_from("<ii8s", data, offset + 16 * i)
        if name.rstrip(b"\0") == b"PLAYPAL":
            return data[pos:pos + size]
    raise SystemExit(f"{path}: no PLAYPAL")


def synthetic_playpal() -> bytes:
    """14 palettes: palette 0 a hue wheel with ramps, the others tinted."""
    import colorsys
    out = bytearray()
    for p in range(14):
        for i in range(256):
            hue, level = (i >> 4) / 16, ((i & 15) + 1) / 16
            r, g, b = colorsys.hsv_to_rgb(hue, 0.8 if i >= 16 else 0.0, level)
            if p:
                r = min(1.0, r + p / 20)
            out += bytes(int(c * 255) for c in (r, g, b))
    return bytes(out)


def rgb444(playpal: bytes) -> bytes:
    """PLAYPAL (14 x 256 x RGB888) -> 14 x 512 bytes (G<<4|B, $20|R),
    each channel round(v * 15 / 255) as the converter does."""
    out = bytearray()
    for i in range(0, 14 * 768, 3):
        r, g, b = (round(c * 15 / 255) for c in playpal[i:i + 3])
        out += bytes(((g << 4) | b, 0x20 | r))
    return bytes(out)


def build(out: Path, wad: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    playpal = rgb444(wad_playpal(wad) if wad else synthetic_playpal())
    (out / "DIR.1").write_bytes(data_file([(DIR_BANK, PLAYPAL_ADDR, playpal)]))
    chunk = 1 << PROBE_LOG2
    segments = []
    for start in range(0, PROBE_COUNT, chunk):
        blob = b"".join(probe_element(i) for i in range(start, min(PROBE_COUNT, start + chunk)))
        segments.append((PROBE_BANK + start // chunk, PROBE_ADDR, blob))
    (out / "PROBE.1").write_bytes(data_file(segments))
    last = max(s[0] for s in segments)
    symbols = dict(DD_FIRST_BANK=DIR_BANK, DD_LAST_BANK=last, DD_DIR_BANK=DIR_BANK,
                   DD_PLAYPAL=PLAYPAL_ADDR, DD_NUM_PALETTES=14,
                   DD_PROBE_BANK=PROBE_BANK, DD_PROBE_ADDR=PROBE_ADDR,
                   DD_PROBE_SIZE=PROBE_SIZE, DD_PROBE_LOG2=PROBE_LOG2,
                   DD_PROBE_COUNT=PROBE_COUNT)
    (out / "doomdata.inc").write_text(
        "; stand-in data set (tools/make_standin.py)\n" +
        "".join(f"{k} = ${v:04X}\n" for k, v in symbols.items()))
    (out / "doomdata.h").write_text(
        "/* stand-in data set (tools/make_standin.py) */\n" +
        "".join(f"#define {k} 0x{v:04X}u\n" for k, v in symbols.items()))
    manifest = dict(standin=True, files=["DIR.1", "PROBE.1"], symbols=symbols,
                    playpal="wad" if wad else "synthetic",
                    banks_used=sorted({DIR_BANK} | {s[0] for s in segments}))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=Path("build/standin/data"))
    parser.add_argument("--wad", type=Path, default=None,
                        help="take PLAYPAL from this WAD (optional)")
    args = parser.parse_args()
    manifest = build(args.out, args.wad if args.wad and args.wad.is_file() else None)
    print(f"stand-in data in {args.out}: {', '.join(manifest['files'])} "
          f"(PLAYPAL {manifest['playpal']}, banks {manifest['banks_used']})")


if __name__ == "__main__":
    main()
