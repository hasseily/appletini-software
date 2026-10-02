#!/usr/bin/env python3
"""The sizes of the tic images (milestone 10, docs/GAME.md 5.5): each
part's bytes in the lockstep build against its budget (2.4: upstream's
bytes x 1.3), the core's and each slot's fill, GCODE0-1's, the driver's
area, the banks.

Usage:  python3 tools/native/gsizes.py [--image game] [--out FILE]

A part's bytes are its modules' (its fragment's sources) in every code
segment of the image but the driver's area (test-only code: counted
apart).
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import glayout as GL, grun as G, llayout as LL  # noqa: E402,F401
from native import ticrun as TR  # noqa: E402


def part_bytes(b) -> Dict[str, Dict[str, int]]:
    parts = TR.module_parts()
    out: Dict[str, Dict[str, int]] = {}
    for module, seg, lo, hi in G.contributions(b):
        part = parts.get(module)
        if part is None:
            continue
        key = 'driver' if seg in ('DRIVER', 'DESC') else 'code'
        d = out.setdefault(part, {'code': 0, 'driver': 0})
        d[key] += hi - lo
    return out


def gcode_fill(b) -> List[str]:
    """GCODE0-1: the W image and the core in GCODE0 at W's addresses, the
    groups packed from $0200 (grun.Image's)."""
    at = {LL.GCODE0: G.GROUP_FIRST, LL.GCODE1: G.GROUP_FIRST}
    for n, lo, hi, data in G.groups_of(b):
        pages = (len(data) + 0xFF) >> 8
        bank = LL.GCODE0
        if at[bank] + (pages << 8) > G.GCODE0_GROUP_END:
            bank = LL.GCODE1
        at[bank] += pages << 8
    return ['GCODE0: groups $0200-$%04X (%d pages of %d), W and the core '
            '$6000-$99FF' % (at[LL.GCODE0] - 1, (at[LL.GCODE0] - 0x200) >> 8,
                             (G.GCODE0_GROUP_END - 0x200) >> 8),
            'GCODE1: groups $0200-$%04X (%d pages of %d)' % (
                at[LL.GCODE1] - 1, (at[LL.GCODE1] - 0x200) >> 8,
                (LL.ROOM[1] - 0x200) >> 8)]


def report(image: str = 'game') -> str:
    b = G.load_build(G.GAME / image, image)
    pb = part_bytes(b)
    lines = ['%-10s %6s %6s %6s %7s' % ('part', 'bytes', 'budget', 'over',
                                         'driver')]
    total = budget = 0
    for p in GL.PARTS:
        d = pb.get(p['name'], {'code': 0, 'driver': 0})
        over = 100.0 * (d['code'] - p['native']) / p['native']
        total += d['code']
        budget += p['native']
        lines.append('%-10s %6d %6d %5.1f%% %7d' % (
            p['name'], d['code'], p['native'], over, d['driver']))
    lines.append('%-10s %6d %6d %5.1f%%' % ('all', total, budget,
                                            100.0 * (total - budget) /
                                            budget))
    lines.append('')
    lines += G.sizes(b)
    lines += gcode_fill(b)
    lines += [x for x in GL.report() if x.startswith('banks:')]
    return '\n'.join(lines) + '\n'


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--image', default='game')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    text = report(args.image)
    print(text, end='')
    if args.out:
        args.out.write_text(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
