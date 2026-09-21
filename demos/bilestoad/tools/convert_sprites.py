#!/usr/bin/env python3
"""Build the SHR sprite sets from the upstream shape data.

Source rows are 1-bit shape + mask on an 8-bit grid. The HGR blit squeezes
that grid to 7 pixels per byte; SHR 320 has the same 8/7 ratio, so one
source bit becomes one SHR pixel.

Inside the mask, the lit pixel is NOT(data bit). Pixels are classified as:
  fill A / fill B : alternating bits (an HGR artifact colour), by phase
  white           : lit with a lit neighbour
  black           : unlit with an unlit neighbour

The seven rotating sets ($00-$6F) are expanded from 16 to 64 angles. Each
master is rotated by at most +-11.25 degrees about its hot spot, then shaded
with a fixed top-left light. Sprites are 4 bits per pixel, colour 0 = clear,
stored for even and odd x (the odd form is shifted right by one pixel).

Outputs:
  sprites.bin     RamWorks bank images, BANK_SIZE bytes each
  sprite_dir.inc  ca65 tables: directory and resident small shapes
  sheet.png       contact sheet for a visual check
"""

import argparse
import math
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shapedata  # noqa: E402

ANGLES = 64
ROTATING_SETS = 7
BANK_BASE = 0x1000              # sprite data lives at $1000-$BFFF of a bank
BANK_SIZE = 0xB000
FIRST_BANK = 1
SCALE = 6                       # supersampling factor for rotation
FETCH_BYTES = 512               # engine slot size (SLOT_PAGES * 256)

CLEAR, FILL_A, FILL_B, WHITE, BLACK = range(5)

# Palette indexes (see engine.s PALETTE).
C_WHITE, C_LIGHT_GREY, C_DARK_GREY = 4, 5, 6
C_BODY = (7, 8, 9)              # light, mid, dark; remapped for player 2
C_RED, C_YELLOW, C_SPRITE_BLACK = 13, 14, 15
C_METAL = (C_WHITE, C_LIGHT_GREY, C_DARK_GREY)

# Which material each fill phase uses, per set.
SET_MATERIALS = {
    0: (C_BODY, C_METAL),       # head
    1: (C_BODY, C_METAL),       # shoulders and feet
    2: (C_BODY, C_METAL),       # torso
    3: (C_METAL, C_BODY),       # shield
    4: (C_BODY, C_METAL),       # arm
    5: (C_METAL, C_BODY),       # weapon
    6: (C_METAL, C_BODY),       # weapon
}
MARK_MATERIALS = ((C_RED, C_RED, C_RED), (C_YELLOW, C_YELLOW, C_YELLOW))


def classify(shape):
    """Return rows of classes on the source 8-bit grid."""
    width = shape["xsize"] * 8
    grid = []
    for row in range(shape["ysize"]):
        inside, lit = [], []
        for column in range(width):
            index = row * shape["xsize"] + column // 8
            bit = column % 8
            inside.append(not (shape["mask"][index] >> bit) & 1)
            lit.append(not (shape["data"][index] >> bit) & 1)
        line = []
        for x in range(width):
            if not inside[x]:
                line.append(CLEAR)
                continue

            def same(nx):
                return 0 <= nx < width and inside[nx] and lit[nx] == lit[x]

            if same(x - 1) or same(x + 1):
                line.append(WHITE if lit[x] else BLACK)
            else:
                phase = (x + (0 if lit[x] else 1)) & 1
                line.append(FILL_B if phase else FILL_A)
        grid.append(line)
    return grid


def rotate(grid, pivot, degrees):
    """Rotate a class grid about pivot. Return (grid, pivot)."""
    if not degrees:
        return grid, pivot
    height, width = len(grid), len(grid[0])
    pad = max(width, height)
    size = (width + 2 * pad) * SCALE, (height + 2 * pad) * SCALE
    big = Image.new("L", size, CLEAR)
    pixels = big.load()
    for y, line in enumerate(grid):
        for x, value in enumerate(line):
            if value:
                for dy in range(SCALE):
                    for dx in range(SCALE):
                        pixels[(x + pad) * SCALE + dx,
                               (y + pad) * SCALE + dy] = value
    center = ((pivot[0] + pad + 0.5) * SCALE, (pivot[1] + pad + 0.5) * SCALE)
    turned = big.rotate(degrees, resample=Image.NEAREST, center=center)
    data = turned.load()
    out = []
    for y in range(height + 2 * pad):
        line = []
        for x in range(width + 2 * pad):
            votes = [0] * 5
            for dy in range(SCALE):
                for dx in range(SCALE):
                    votes[data[x * SCALE + dx, y * SCALE + dy]] += 1
            solid = SCALE * SCALE - votes[CLEAR]
            if solid * 2 < SCALE * SCALE:
                line.append(CLEAR)
            else:
                line.append(max(range(1, 5), key=lambda c: votes[c]))
        out.append(line)
    return out, (pivot[0] + pad, pivot[1] + pad)


def crop(grid, pivot):
    rows = [y for y, line in enumerate(grid) if any(line)]
    if not rows:
        return [[CLEAR]], (0, 0)
    columns = [x for line in grid for x, v in enumerate(line) if v]
    top, bottom = min(rows), max(rows)
    left, right = min(columns), max(columns)
    cut = [line[left:right + 1] for line in grid[top:bottom + 1]]
    return cut, (pivot[0] - left, pivot[1] - top)


def shade(grid, materials):
    """Return rows of palette indexes with a top-left light."""
    height, width = len(grid), len(grid[0])

    def is_fill(x, y):
        return 0 <= x < width and 0 <= y < height and \
            grid[y][x] in (FILL_A, FILL_B)

    out = []
    for y in range(height):
        line = []
        for x in range(width):
            value = grid[y][x]
            if value == CLEAR:
                line.append(0)
            elif value == WHITE:
                line.append(C_WHITE)
            elif value == BLACK:
                line.append(C_SPRITE_BLACK)
            else:
                ramp = materials[0 if value == FILL_A else 1]
                lit = not (is_fill(x - 1, y) and is_fill(x, y - 1))
                dark = not (is_fill(x + 1, y) and is_fill(x, y + 1))
                line.append(ramp[0] if lit and not dark else
                            ramp[2] if dark and not lit else ramp[1])
        out.append(line)
    return out


def pack(pixels, odd):
    """Pack palette indexes to bytes; return (width in bytes, data)."""
    rows = [([0] if odd else []) + line for line in pixels]
    width = (len(rows[0]) + 1) // 2
    data = bytearray()
    for line in rows:
        line = line + [0] * (width * 2 - len(line))
        for index in range(0, width * 2, 2):
            data.append((line[index] << 4) | line[index + 1])
    return width, bytes(data)


def overlap(a, pivot_a, b, pivot_b):
    cells_a = {(x - pivot_a[0], y - pivot_a[1])
               for y, line in enumerate(a) for x, v in enumerate(line) if v}
    cells_b = {(x - pivot_b[0], y - pivot_b[1])
               for y, line in enumerate(b) for x, v in enumerate(line) if v}
    return len(cells_a & cells_b) / max(1, len(cells_a | cells_b))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("upstream")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    memory, _ = shapedata.assemble(args.upstream)
    shapes = shapedata.read_shapes(memory)

    def master(index):
        shape = shapes[index]
        hot_x = shape["hot_x"] - 256 * (shape["hot_x"] > 127)
        hot_y = shape["hot_y"] - 256 * (shape["hot_y"] > 127)
        grid = classify(shape)
        # The fill phase is not consistent between the upstream masters.
        # Make the majority phase of each master the primary material.
        count_a = sum(line.count(FILL_A) for line in grid)
        count_b = sum(line.count(FILL_B) for line in grid)
        if count_b > count_a:
            swap = {FILL_A: FILL_B, FILL_B: FILL_A}
            grid = [[swap.get(v, v) for v in line] for line in grid]
        # The hot spot is in HGR pixels; the grid is 8/7 wider.
        return grid, (round(hot_x * 8 / 7), hot_y)

    # Find the turn direction: which sign of rotation maps angle n to n+1.
    score = {1: 0.0, -1: 0.0}
    for index in range(32, 48):
        grid, pivot = master(index)
        following = master(32 + (index - 31) % 16)
        for sign in (1, -1):
            turned = crop(*rotate(grid, pivot, sign * 22.5))
            score[sign] += overlap(*turned, *crop(*following))
    direction = 1 if score[1] >= score[-1] else -1
    print("turn direction %+d (scores %.2f / %.2f)" %
          (direction, score[1], score[-1]))

    banks = [bytearray()]
    directory = []              # (bank, even addr, odd addr, we, wo, h, hx, hy)
    largest = 0
    sheet = Image.new("RGB", (ANGLES * 40, ROTATING_SETS * 56), (0, 60, 0))
    preview = {0: (0, 60, 0), 4: (255, 255, 255), 5: (170, 170, 170),
               6: (90, 90, 90), 7: (255, 210, 80), 8: (230, 140, 30),
               9: (140, 70, 10), 13: (220, 0, 0), 14: (255, 240, 0),
               15: (16, 16, 24)}

    def store(pixels):
        # Both x forms of a sprite go into the same bank.
        forms = [pack(pixels, odd) for odd in (False, True)]
        # The engine fetches FETCH_BYTES from the start of a form. That read
        # must end below $C000, or it would touch the I/O soft switches.
        if len(banks[-1]) + len(forms[0][1]) + FETCH_BYTES > BANK_SIZE:
            banks[-1].extend(bytes(BANK_SIZE - len(banks[-1])))
            banks.append(bytearray())
        entry = []
        for width, data in forms:
            entry.append((FIRST_BANK + len(banks) - 1,
                          BANK_BASE + len(banks[-1]), width, len(data)))
            banks[-1].extend(data)
        return entry

    for group in range(ROTATING_SETS):
        for angle in range(ANGLES):
            base = ((angle + 2) // 4) % 16
            residual = (angle - base * 4 + 32) % 64 - 32
            grid, pivot = master(group * 16 + base)
            grid, pivot = crop(*rotate(grid, pivot,
                                       direction * residual * 5.625))
            pixels = shade(grid, SET_MATERIALS[group])
            (bank_e, addr_e, w_e, size_e), (bank_o, addr_o, w_o, size_o) = \
                store(pixels)
            largest = max(largest, size_e, size_o)
            directory.append((bank_e, addr_e, bank_o, addr_o, w_e, w_o,
                              len(pixels), pivot[0], pivot[1]))
            for y, line in enumerate(pixels):
                for x, value in enumerate(line):
                    if value and x < 40 and y < 56:
                        sheet.putpixel((angle * 40 + x, group * 56 + y),
                                       preview[value])
    banks[-1].extend(bytes(BANK_SIZE - len(banks[-1])))

    # Small shapes stay resident in main memory.
    small_lines, small_dir = [], []
    for index in range(ROTATING_SETS * 16, shapedata.SHAPE_COUNT):
        shape = shapes[index]
        if shape is None:
            small_dir.append(None)
            continue
        grid, pivot = crop(*master(index))
        pixels = shade(grid, MARK_MATERIALS)
        forms = [pack(pixels, odd) for odd in (False, True)]
        small_dir.append((index, forms, len(pixels), pivot))
        for odd, (width, data) in enumerate(forms):
            small_lines.append("small_%02x_%d:" % (index, odd))
            for start in range(0, len(data), 16):
                small_lines.append("    .byte " + ",".join(
                    "$%02X" % b for b in data[start:start + 16]))

    lines = ["; Generated by tools/convert_sprites.py. Do not edit.",
             "; Directory record (10 bytes): bank, even address, odd address,",
             "; even width, odd width, height, hot x, hot y.",
             "; Bank 0 = resident in main memory.",
             "SPRDIR_RECORD = 10",
             "SPRITE_ANGLES = %d" % ANGLES,
             "SPRITE_BANKS = %d" % len(banks),
             "SPRITE_FIRST_BANK = %d" % FIRST_BANK,
             "SPRITE_MAX_BYTES = %d" % largest,
             "SMALL_FIRST = $%02X" % (ROTATING_SETS * 16),
             "FLOWER_FIRST = %d" % len(small_dir), "", "sprdir:"]
    for e in directory:
        assert e[0] == e[2]
        lines.append("    .byte %d,$%02X,$%02X,$%02X,$%02X,%d,%d,%d,$%02X,$%02X"
                     % (e[0], e[1] & 255, e[1] >> 8, e[3] & 255, e[3] >> 8,
                        e[4], e[5], e[6], e[7] & 255, e[8] & 255))
    lines.append("smalldir:")
    for item in small_dir:
        if item is None:
            lines.append("    .res 10, 0")
            continue
        index, forms, height, pivot = item
        lines.append("    .byte 0,<small_%02x_0,>small_%02x_0,<small_%02x_1,"
                     ">small_%02x_1,%d,%d,%d,$%02X,$%02X" % (
                         index, index, index, index, forms[0][0],
                         forms[1][0], height, pivot[0] & 255, pivot[1] & 255))
    # Two flowers, new art for this port (the upstream flower is a 7x7 bitmap
    # inside the game code). '.' clear, w white, y yellow, r red.
    flower_art = (
        ("...ww...", ".wwyyww.", "wwyyyyww", "wwyyyyww", ".wwyyww.",
         "...ww...", "........"),
        ("..r..r..", ".rryyrr.", "..yyyy..", ".rryyrr.", "..r..r..",
         "........", "........"),
    )
    key = {".": 0, "w": C_WHITE, "y": C_YELLOW, "r": C_RED}
    for number, art in enumerate(flower_art):
        pixels = [[key[c] for c in row] for row in art]
        forms = [pack(pixels, odd) for odd in (False, True)]
        lines.append("    .byte 0,<flower_%d_0,>flower_%d_0,<flower_%d_1,"
                     ">flower_%d_1,%d,%d,%d,0,0" % (
                         number, number, number, number, forms[0][0],
                         forms[1][0], len(pixels)))
        for odd, (width, data) in enumerate(forms):
            small_lines.append("flower_%d_%d:" % (number, odd))
            small_lines.append("    .byte " + ",".join(
                "$%02X" % b for b in data))
    lines.append("")
    lines.extend(small_lines)
    (out_dir / "sprite_dir.inc").write_text("\n".join(lines) + "\n")
    (out_dir / "sprites.bin").write_bytes(b"".join(bytes(b) for b in banks))
    sheet.resize((sheet.width * 2, sheet.height * 2)).save(
        out_dir / "sheet.png")
    print("%d sprites, %d banks, largest %d bytes" %
          (len(directory), len(banks), largest))


if __name__ == "__main__":
    main()
