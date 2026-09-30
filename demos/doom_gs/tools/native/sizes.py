#!/usr/bin/env python3
"""The bytes used and left in each area of the native replay's builds.

Usage:  python3 tools/native/sizes.py MAP [MAP ...]

Reads ld65 maps (src/native/Makefile writes build/native/obj/test.map and
card.map) and prints, for each segment, its area of docs/MEMORY_MAP.md
section 8, the bytes it takes, and the room its memory area leaves.
Standard library only.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# segment -> (the area in docs/MEMORY_MAP.md, its start, its size)
AREAS = {
    'RZP': ('zero page $48-$6F (replay)', 0x48, 0x28),
    'RSCR': ('main $17C2-$17FF scratch', 0x17C2, 0x3E),
    'MAINTAB': ('main $0800-$0BFF tables', 0x0800, 0x400),
    'AUXCODE': ('aux 0 $0200-$03FF drawers', 0x0200, 0x200),
    'AUXTAB': ('aux 0 $0800-$0BFF tables', 0x0800, 0x400),
    'TEXBLK': ('card bank 2 $D000-$DBFF texture rows', 0xD000, 0xC00),
    'FILLE': ('card bank 2 $DC00-$DCFF even fills', 0xDC00, 0x100),
    'FILLO': ('card bank 2 $DD00-$DDFF odd fills', 0xDD00, 0x100),
    'RHOT': ('card bank 2 $DE00-$DFFF draw pass', 0xDE00, 0x200),
    'RCODE': ('card $F900-$FEFF batches, gather', 0xF900, 0x600),
    'DRIVER': ('card $E000- test driver (not the game)', 0xE000, 0x1900),
    'RUNNER': ('card $E000- card runner (not the game)', 0xE000, 0xA00),
    'RUNBSS': ('card runner data (not the game)', 0xEA00, 0xF00),
    'BOOT': ('main $2000-$27FF card boot (not the game)', 0x2000, 0x800),
}


def segments(path: Path) -> List[Tuple[str, int, int]]:
    """(name, start, size) from the map's segment list."""
    out = []
    text = Path(path).read_text()
    part = text.split('Segment list:', 1)[1]
    for line in part.splitlines()[4:]:
        fields = line.split()
        if len(fields) != 5 or not re.match(r'^[0-9A-F]{6}$', fields[1]):
            break
        out.append((fields[0], int(fields[1], 16), int(fields[3], 16)))
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__.splitlines()[2], file=sys.stderr)
        return 2
    seen: Dict[str, Tuple[int, int]] = {}
    for path in argv:
        print(Path(path).name)
        for name, start, size in segments(Path(path)):
            area = AREAS.get(name)
            if area is None:
                print('  %-8s $%04X %5d bytes' % (name, start, size))
                continue
            what, first, room = area
            print('  %-8s %-44s %5d of %5d bytes, %5d left' % (
                name, what, size, room, room - size - (start - first)))
            seen[name] = (size, room)
    return 0


if __name__ == '__main__':
    sys.exit(main())
