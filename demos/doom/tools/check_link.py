#!/usr/bin/env python3
"""Check the link's four files and report the memory each space uses.

Run by the Makefile after ld65 (src/doom.cfg). Checks what the loader and
the kernel rely on:

  DOOM.SYSTEM  starts with code at $2000 and ends below $4000 (the LC.BIN
               stage at $6000 and the loader's buffers are above it)
  RENDER.BIN   $0200 up, ends below VIEWBUF ($8B80)
  LC.BIN       exactly 16,384 bytes; the jump table at $E000 (offset
               $1000) starts with JMP; the IRQ vector (offset $2FFE)
               points into the card
  GAME.BIN     $0200 up, ends below the C stack ($B800)

and prints, from the map file, the bytes used and free of each memory
area (RENDER main, LC banks, GAME bank 1, zero page). --json writes the
same numbers for the tests.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

AREAS = {   # name: (start, size, what) -- src/doom.cfg
    "KZP": (0x0002, 0x00DE, "zero page, kernel and renderer"),
    "CZP": (0x00E0, 0x0020, "zero page, cc65"),
    "LOADER": (0x2000, 0x2000, "DOOM.SYSTEM"),
    "RLOW": (0x0200, 0x0200, "RENDER $0200-$03FF"),
    "RTEXT": (0x0400, 0x0800, "RENDER $0400-$0BFF (read-only)"),
    "RMAIN": (0x0C00, 0x7F80, "RENDER $0C00-$8B7F"),
    "LC2": (0xD000, 0x1000, "LC bank 2 $D000-$DFFF"),
    "LCHI": (0xE000, 0x1FFA, "LC $E000-$FFF9"),
    "LCVEC": (0xFFFA, 0x0006, "LC vectors"),
    "LC1": (0xD000, 0x1000, "LC bank 1 $D000-$DFFF"),
    "GAME": (0x0200, 0xB600, "GAME bank 1 $0200-$B7FF"),
}


def area_usage(map_text: str) -> dict:
    """{memory area: bytes used}, from the map's segment list and the cfg's
    segment-to-area assignment."""
    cfg = (Path(__file__).resolve().parents[1] / "src/doom.cfg").read_text()
    seg_area = dict(re.findall(r"^\s*(\w+):\s*load\s*=\s*(\w+)", cfg, re.M))
    used = {name: 0 for name in AREAS}
    part = map_text.split("Segment list:")[1].split("Exports list")[0]
    for line in part.splitlines():
        m = re.match(r"^(\w+)\s+([0-9A-F]{6})\s+([0-9A-F]{6})\s+([0-9A-F]{6})", line)
        if m and m.group(1) in seg_area:
            used[seg_area[m.group(1)]] += int(m.group(4), 16)
    return used


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", type=Path, default=Path("build"))
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    b = args.build
    errors = []
    system = (b / "DOOM.SYSTEM").read_bytes()
    render = (b / "RENDER.BIN").read_bytes()
    lc = (b / "LC.BIN").read_bytes()
    game = (b / "GAME.BIN").read_bytes()
    if system[0] not in (0xD8, 0x78, 0xA2, 0x4C):
        errors.append(f"DOOM.SYSTEM starts with ${system[0]:02X}, not code")
    if 0x2000 + len(system) > 0x4000:
        errors.append(f"DOOM.SYSTEM is {len(system)} bytes: past $3FFF")
    if 0x0200 + len(render) > 0x8B80:
        errors.append(f"RENDER.BIN is {len(render)} bytes: reaches the view buffer")
    if len(lc) != 0x4000:
        errors.append(f"LC.BIN is {len(lc)} bytes, not 16384")
    elif lc[0x1000] != 0x4C:
        errors.append("LC.BIN: no JMP at $E000")
    else:
        irq = lc[0x2FFE] | (lc[0x2FFF] << 8)
        if irq < 0xD000:
            errors.append(f"LC.BIN: the IRQ vector is ${irq:04X}")
    if 0x0200 + len(game) > 0xB800:
        errors.append(f"GAME.BIN is {len(game)} bytes: reaches the C stack")
    used = area_usage((b / "doom.map").read_text())
    report = {name: dict(start=start, size=size, used=used[name], free=size - used[name],
                         what=what) for name, (start, size, what) in AREAS.items()}
    report["files"] = {"DOOM.SYSTEM": len(system), "RENDER.BIN": len(render),
                       "LC.BIN": len(lc), "GAME.BIN": len(game)}
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    if not args.quiet:
        for name, (start, size, what) in AREAS.items():
            print(f"  {name:7s} {what:34s} {used[name]:6d} used {size - used[name]:6d} free")
    for error in errors:
        print("check_link: " + error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
