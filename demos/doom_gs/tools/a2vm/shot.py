#!/usr/bin/env python3
"""Turn an a2vm screen dump into a PNG, as the Appletini shows it.

Usage:  python3 tools/a2vm/shot.py DUMP... [--out DIR]

A DUMP is a file a2vm writes with the `shot` action (NAME.shr: the magic
A2VMSHR1, the NEWVIDEO register $C029, aux bank 0 $2000-$9FFF, then main
$2000-$9FFF), or an a2vm snapshot (NAME.ram, main first, then the
language card, then the aux banks; NEWVIDEO from NAME.json).

The picture is 640x400 and follows a2sim.py's shr_image(), itself a copy
of appletini-one's ps_sources/frontend/apple_cycle_renderer.c:

  - PAL256: with the SHR4 magic D3 C8 D2 B4 at aux $9DFC and a palette
    entry of aux $9E00-$9FFF whose selector nibble (the high nibble of its
    second byte) is 2, the frame is 320x100 index bytes from aux $2000
    through the 256 colours at $9E00, each pixel 2x4 on the output. The
    paging byte at aux $9DF8 selects interlace (1: aux rows 0-99, main
    100-199, each 2x2) or page-flip merge (2: aux and main averaged,
    (a & b) + ((a ^ b) >> 1) per channel); anything else is progressive.
  - Otherwise standard SHR: scan-line control bytes at $9D00, 16 palettes
    at $9E00, 320 mode (two pixels a byte, each 2x2) or 640 mode (four,
    from colours 8-11, 12-15, 0-3, 4-7, each 1x2). With the SHR4 magic, a
    320-mode pixel whose colour has selector 2 shows the whole byte
    through the PAL256 palette. Fill mode is not modelled.
  - Colours are $0RGB, each channel times 16; NEWVIDEO bit 5 turns them
    into luminance, (77 R + 150 G + 29 B) >> 8.

Only zlib from the standard library writes the PNG.
"""

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

MAGIC = b'A2VMSHR1'
SCREEN = 0x8000                 # $2000-$9FFF
SHR4_MAGIC = bytes((0xd3, 0xc8, 0xd2, 0xb4))
WIDTH, HEIGHT = 640, 400
RAM_MAIN = 0
RAM_AUX0 = 0x10000 + 0x4000 + 0x1000


def rgb(raw, newvideo):
    r, g, b = (raw >> 8 & 15) * 16, (raw >> 4 & 15) * 16, (raw & 15) * 16
    if newvideo & 0x20:
        y = (r * 77 + g * 150 + b * 29) >> 8
        return (y, y, y)
    return (r, g, b)


def palette256(screen, newvideo):
    """The 256 PAL256 colours of $9E00-$9FFF (offset $7E00 of a screen)."""
    return [rgb(screen[0x7e00 + 2 * i] | screen[0x7e01 + 2 * i] << 8, newvideo)
            for i in range(256)]


def pal256_active(aux):
    return (aux[0x7dfc:0x7e00] == SHR4_MAGIC and
            any(aux[a] >> 4 == 2 for a in range(0x7e01, 0x8000, 2)))


def field(screen, newvideo):
    """The 100 rows of 320 colours of a PAL256 field."""
    colours = palette256(screen, newvideo)
    return [[colours[b] for b in screen[row * 320:(row + 1) * 320]]
            for row in range(100)]


def render_pal256(aux, main, newvideo):
    paged = aux[0x7df8]
    if paged == 1:
        rows = field(aux, newvideo) + field(main, newvideo)
        return [[p for p in row for _ in range(2)] for row in rows
                for _ in range(2)]
    rows = field(aux, newvideo)
    if paged == 2:
        other = field(main, newvideo)
        rows = [[tuple((a & b) + ((a ^ b) >> 1) for a, b in zip(p, q))
                 for p, q in zip(row, row2)]
                for row, row2 in zip(rows, other)]
    return [[p for p in row for _ in range(2)] for row in rows
            for _ in range(4)]


def render_standard(aux, newvideo):
    shr4 = aux[0x7dfc:0x7e00] == SHR4_MAGIC
    wide = palette256(aux, newvideo) if shr4 else None
    rows = []
    for row in range(200):
        scb = aux[0x7d00 + row]
        base = 0x7e00 + (scb & 15) * 32
        table, selectors = [], []
        for index in range(16):
            low, high = aux[base + index * 2], aux[base + index * 2 + 1]
            table.append(rgb(low | high << 8, newvideo))
            selectors.append(high >> 4 if shr4 else 0)
        line = aux[row * 160:(row + 1) * 160]
        pixels = []
        for byte in line:
            if scb & 0x80:
                for k, dot in enumerate((byte >> 6 & 3, byte >> 4 & 3,
                                         byte >> 2 & 3, byte & 3)):
                    pixels.append(table[dot + (8, 12, 0, 4)[k]])
            else:
                for dot in (byte >> 4, byte & 15):
                    colour = wide[byte] if selectors[dot] == 2 else table[dot]
                    pixels.extend((colour, colour))
        rows.extend((pixels, pixels))
    return rows


def render(aux, main, newvideo):
    """The 400 rows of 640 (R, G, B) of the screen. `aux` and `main` are
    $2000-$9FFF of aux bank 0 and main memory."""
    if pal256_active(aux):
        return render_pal256(aux, main, newvideo)
    return render_standard(aux, newvideo)


def rgb_bytes(rows):
    return b''.join(bytes(c for pixel in row for c in pixel) for row in rows)


def png(rows):
    """The rows as an 8-bit RGB PNG."""
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data +
                struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))

    header = struct.pack('>IIBBBBB', len(rows[0]), len(rows), 8, 2, 0, 0, 0)
    raw = b''.join(b'\0' + bytes(c for pixel in row for c in pixel)
                   for row in rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) +
            chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def load(path):
    """(aux, main, newvideo) of a dump or a snapshot."""
    path = Path(path)
    data = path.read_bytes()
    if data[:8] == MAGIC:
        if len(data) != 9 + 2 * SCREEN:
            raise ValueError('%s: a dump is %d bytes' % (path, 9 + 2 * SCREEN))
        return data[9:9 + SCREEN], data[9 + SCREEN:], data[8]
    state = json.loads(path.with_suffix('.json').read_text())
    aux = data[RAM_AUX0 + 0x2000:RAM_AUX0 + 0xa000]
    main = data[RAM_MAIN + 0x2000:RAM_MAIN + 0xa000]
    return aux, main, state['switches']['newvideo']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('dumps', nargs='+', type=Path)
    parser.add_argument('--out', type=Path)
    arguments = parser.parse_args(argv)
    if arguments.out:
        arguments.out.mkdir(parents=True, exist_ok=True)
    for dump in arguments.dumps:
        rows = render(*load(dump))
        target = (arguments.out or dump.parent) / (dump.stem + '.png')
        target.write_bytes(png(rows))
        colours = len({pixel for row in rows for pixel in row})
        print('%s: %dx%d, %d colours' % (target, len(rows[0]), len(rows),
                                         colours))
    return 0


if __name__ == '__main__':
    sys.exit(main())
