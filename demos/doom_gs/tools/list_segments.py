#!/usr/bin/env python3
"""Print the segments of the upstream release image, and what they total.

Usage:  python3 tools/list_segments.py [IMAGE] [--dump DIR]

IMAGE defaults to build/release/doom-hd.hdv (tools/fetch_upstream.py puts
it there). --dump writes one file for each bank of the loaded memory
image; DIR must be inside build/, because the files hold upstream's code.
"""

import argparse
import sys
from pathlib import Path

from v816 import hdv, memimage

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build'
DEFAULT_IMAGE = BUILD / 'release' / 'doom-hd.hdv'
FLAG_NAMES = {0: '-', hdv.SEG_PIC: 'PIC', hdv.SEG_B1: 'B1'}


def segment_table(image):
    """The lines of the table of segments of `image`."""
    lines = [' #  address   end         bytes  flags  block  count  kind',
             '--  --------  --------  -------  -----  -----  -----  ----']
    for segment in image.segments:
        lines.append(
            '%2d  $%02X:%04X  $%02X:%04X  %7d  %-5s  %5d  %5d  %s' % (
                segment.index,
                segment.address >> 16, segment.address & 0xffff,
                (segment.end - 1) >> 16, (segment.end - 1) & 0xffff,
                len(segment.data), FLAG_NAMES[segment.flags],
                segment.first_block, segment.block_count,
                hdv.kind(image, segment)))
    return lines


def summary(image):
    """The lines that say what the header and the segments add up to."""
    sums = hdv.totals(image)
    code = sums.get(hdv.KIND_CODE_BANK0, 0) + sums.get(hdv.KIND_CODE, 0)
    address, store = image.level_store()
    lines = [
        'volume %s, disk %d of %d, build %08X'
        % (image.volume_name, image.disk, image.disks, image.build_id),
        'loader: %d bytes at $%04X' % (len(image.loader),
                                       image.loader_address),
        'entry point: $%02X:%04X' % (image.entry >> 16,
                                     image.entry & 0xffff),
        'segments: %d' % len(image.segments),
        'code segments: %d bytes' % code,
    ]
    lines += ['  %-20s %9d bytes' % (name, sums[name]) for name in sums]
    lines.append('level store: %d bytes at $%02X:%04X, %d banks'
                 % (len(store), address >> 16, address & 0xffff,
                    image.store_banks))
    return lines


def overlap_lines(memory):
    """The lines that report segments loaded over other segments."""
    return ['segment %d overwrites %d bytes of segment %d at $%06X'
            % (o.later, o.length, o.earlier, o.address)
            for o in memory.overlaps]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('image', nargs='?', default=str(DEFAULT_IMAGE))
    parser.add_argument('--dump', metavar='DIR',
                        help='write the banks of the memory image to DIR')
    args = parser.parse_args(argv)
    if not Path(args.image).exists():
        sys.exit('%s: not found; run tools/fetch_upstream.py' % args.image)
    image = hdv.load(args.image)
    memory = memimage.MemoryImage.from_segments(image.segments)
    print('\n'.join(segment_table(image)))
    print()
    print('\n'.join(summary(image)))
    print('\n'.join(overlap_lines(memory) or ['no segment overlaps another']))
    if args.dump:
        target = Path(args.dump).resolve()
        if BUILD.resolve() not in target.parents:
            sys.exit('%s is not inside %s' % (target, BUILD))
        paths = memory.dump(str(target))
        print('%d banks written to %s' % (len(paths), target))


if __name__ == '__main__':
    main()
