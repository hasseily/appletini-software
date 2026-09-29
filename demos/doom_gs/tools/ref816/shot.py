#!/usr/bin/env python3
"""Turn a dump of the IIgs super hi-res screen into a PNG.

Usage:  python3 tools/ref816/shot.py DUMP... [--out DIR] [--border PIXELS]

A dump is $E1:2000-$9FFF as ref816 writes it (--shot-frame, --shot-cycle):
32,000 bytes of pixels (200 rows of 160 bytes), 200 scan-line control
bytes at offset $7D00, 16 palettes of 16 colours at $7E00 (a colour is
$0RGB, 4 bits each), then two bytes the machine adds: the border
register $C034 and the new-video register $C029. A 32,768-byte dump
without them has a black border.

Each row uses the palette of its control byte (bits 0-3). A row with bit
7 set is in 640 mode: a byte is four pixels of 2 bits, from colours
8-11, 12-15, 0-3 and 4-7 of the palette. Otherwise it is in 320 mode: a
byte is two pixels of 4 bits, high nibble first; with bit 5 (fill mode)
set, colour 0 repeats the pixel to its left. The picture is 320x200
when all rows are in 320 mode, else 640x400 with every row and every
320-mode pixel doubled. --border adds that many pixels on each side in
the border colour, one of the 16 fixed colours of the IIgs.

The PNG is written with zlib from the standard library. Each DUMP.shr
gives DUMP.png, in --out when given. The script prints the size and the
colour statistics of each picture.

view_stats tells a 3D view of the game from a flat picture: the game
draws its view in rows 0-167 and its status bar in rows 168-199 (Doom's
ST_Y), each with palettes of its own. A smaller view has a black border
around it.
"""

import argparse
import statistics
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Tuple

PIXEL_BYTES = 32000
ROWS = 200
ROW_BYTES = 160
SCB = 0x7d00
PALETTES = 0x7e00
SCREEN = 0x8000
SCB_640 = 0x80
SCB_FILL = 0x20

# The border colours of $C034, as $0RGB (the IIgs's 16 standard colours,
# those of the low-resolution graphics modes).
BORDER_COLOURS = (
    0x000, 0xd03, 0x009, 0xd2d, 0x072, 0x555, 0x22f, 0x6af,
    0x850, 0xf60, 0xaaa, 0xf98, 0x1d0, 0xff0, 0x4f9, 0xfff)

# The palette entry of each pixel of a 640-mode byte, high bits first.
COLOURS_640 = (8, 12, 0, 4)

STATUS_ROW = 168        # the first row of the game's status bar

RGB = Tuple[int, int, int]


class Picture(NamedTuple):
    width: int
    height: int
    rows: List[List[RGB]]


class Stats(NamedTuple):
    width: int
    height: int
    colours: int
    commonest_share: float      # of the pixels, in the commonest colour


class ViewStats(NamedTuple):
    """The rows above STATUS_ROW (the view) against those below it."""
    view_colours: int           # distinct colours in the view
    row_colours: float          # median of the distinct colours of a row
    distinct_rows: int          # of the STATUS_ROW rows of the view
    status_palettes_apart: bool  # no palette of the view in the status bar
    status_rows_in_view: int    # status bar rows equal to a view row
    window: Tuple[int, int, int, int]   # left, top, width, height of the
                                        # pixels that are not black


def full_3d_view(stats: ViewStats) -> bool:
    """Whether `stats` are those of the game's 3D view at full size: most
    of its rows different, with colours enough for walls, floor and
    ceiling, and a status bar of its own below."""
    return (stats.view_colours >= 8 and
            stats.distinct_rows >= STATUS_ROW // 2 and
            stats.status_palettes_apart and
            stats.status_rows_in_view == 0 and
            stats.window == (0, 0, ROW_BYTES * 2, STATUS_ROW))


def rgb(colour: int) -> RGB:
    """A $0RGB colour as 8-bit components."""
    return ((colour >> 8 & 15) * 17, (colour >> 4 & 15) * 17,
            (colour & 15) * 17)


def palette(screen: bytes, number: int) -> List[RGB]:
    start = PALETTES + 32 * number
    return [rgb(c) for c in struct.unpack_from('<16H', screen, start)]


def row_pixels(screen: bytes, row: int) -> Tuple[bool, List[RGB]]:
    """(640 mode, the colours of the row's pixels)."""
    control = screen[SCB + row]
    colours = palette(screen, control & 15)
    data = screen[row * ROW_BYTES:(row + 1) * ROW_BYTES]
    if control & SCB_640:
        return True, [colours[COLOURS_640[i] + (byte >> (6 - 2 * i) & 3)]
                      for byte in data for i in range(4)]
    indexes = [nibble for byte in data for nibble in (byte >> 4, byte & 15)]
    if control & SCB_FILL:
        for i in range(1, len(indexes)):
            if indexes[i] == 0:
                indexes[i] = indexes[i - 1]
    return False, [colours[i] for i in indexes]


def render(dump: bytes, border: int = 0) -> Picture:
    """The picture of `dump`, with `border` pixels of border colour."""
    if len(dump) not in (SCREEN, SCREEN + 2):
        raise ValueError('a dump is %d or %d bytes, not %d'
                         % (SCREEN, SCREEN + 2, len(dump)))
    border_colour = rgb(BORDER_COLOURS[dump[SCREEN] & 15]
                        if len(dump) > SCREEN else 0)
    lines = [row_pixels(dump, row) for row in range(ROWS)]
    wide = any(is_640 for is_640, _ in lines)
    rows = []
    for is_640, pixels in lines:
        if wide and not is_640:
            pixels = [p for p in pixels for _ in range(2)]
        rows.extend([pixels] * (2 if wide else 1))
    if border:
        width = len(rows[0]) + 2 * border
        edge = [border_colour] * border
        rows = ([[border_colour] * width] * border +
                [edge + row + edge for row in rows] +
                [[border_colour] * width] * border)
    return Picture(len(rows[0]), len(rows), rows)


def png(picture: Picture) -> bytes:
    """`picture` as an 8-bit RGB PNG."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack('>I', len(data)) + kind + data +
                struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))

    header = struct.pack('>IIBBBBB', picture.width, picture.height, 8, 2,
                         0, 0, 0)
    raw = b''.join(b'\0' + bytes(c for pixel in row for c in pixel)
                   for row in picture.rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) +
            chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def view_stats(dump: bytes) -> ViewStats:
    """The statistics of the view and the status bar of a 320x200 dump.
    A 3D view has many different rows with many colours, and a status
    bar with palettes and rows of its own."""
    picture = render(dump)
    if picture.height != ROWS:
        raise ValueError('the view statistics are for 320-mode screens')
    view, status = picture.rows[:STATUS_ROW], picture.rows[STATUS_ROW:]
    palettes = [dump[SCB + row] & 15 for row in range(ROWS)]
    rows = {tuple(row) for row in view}
    lit = [(x, y) for y, row in enumerate(view) for x, pixel in
           enumerate(row) if pixel != (0, 0, 0)]
    window = (0, 0, 0, 0)
    if lit:
        xs, ys = [x for x, _ in lit], [y for _, y in lit]
        window = (min(xs), min(ys), max(xs) - min(xs) + 1,
                  max(ys) - min(ys) + 1)
    return ViewStats(
        len({pixel for row in view for pixel in row}),
        statistics.median(len(set(row)) for row in view), len(rows),
        not set(palettes[:STATUS_ROW]) & set(palettes[STATUS_ROW:]),
        sum(1 for row in status if tuple(row) in rows), window)


def stats(picture: Picture) -> Stats:
    counts = Counter(pixel for row in picture.rows for pixel in row)
    total = picture.width * picture.height
    return Stats(picture.width, picture.height, len(counts),
                 counts.most_common(1)[0][1] / total)


def convert(path: Path, out: Optional[Path] = None,
            border: int = 0) -> Tuple[Path, Stats]:
    """Write the PNG of the dump at `path`; return its path and stats."""
    picture = render(path.read_bytes(), border)
    target = (out or path.parent) / (path.stem + '.png')
    target.write_bytes(png(picture))
    return target, stats(picture)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('dumps', nargs='+', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--border', type=int, default=0)
    arguments = parser.parse_args(argv)
    if arguments.out:
        arguments.out.mkdir(parents=True, exist_ok=True)
    for dump in arguments.dumps:
        target, info = convert(dump, arguments.out, arguments.border)
        print('%s: %dx%d, %d colours, commonest %.1f%%'
              % (target, info.width, info.height, info.colours,
                 100 * info.commonest_share))
    return 0


if __name__ == '__main__':
    sys.exit(main())
