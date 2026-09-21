#!/usr/bin/env python3
"""Convert the text art in assets/ into build/assets.s, assets.h and a preview.

Inputs (see the header comments of each file for the exact syntax):
  assets/sprites.txt   sprite art, one character per pixel, plus "derive"
                       lines that rotate or mirror an earlier sprite
  assets/font8.txt     64 glyphs of 8x8 pixels for ASCII 32..95

Outputs:
  build/assets.s            ca65 source, segment RODATA (docs/DESIGN.md section 4)
  build/assets.h            SPR_* ids and a comment table of ids and sizes
  build/assets_preview.png  all sprites on a grid at 4x (only if Pillow imports)

Sprite format written for video.s (docs/DESIGN.md section 4):
  byte 0: height H, byte 1: width in bytes W of this variant, then H row
  records: run_off, run_len, run_len bytes of pixel pairs (high nibble = left
  pixel). An empty row is stored as run_off = $FF followed by run_len = 0
  (EMPTY_ROW_BYTES below), so every row record starts with two header bytes.
  The "odd" variant is the image shifted right by one pixel and is one byte
  wider when the pixel width is even.

Only the Python standard library is required. Pillow is optional and used
for the preview picture only.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ASSETS = PROJECT_DIR / "assets"
DEFAULT_BUILD = PROJECT_DIR / "build"

# Empty row record: run_off $FF, then a run_len byte of 0. Set to (0xFF,) if
# video.s expects a single byte per empty row.
EMPTY_ROW_BYTES = (0xFF, 0x00)

# Sprite id list, fixed by docs/DESIGN.md section 9 (name, width, height).
SPRITES = (
    [(f"SHIP_{i}", 16, 16) for i in range(8)]
    + [(f"ITYPE_{i}", 12, 12) for i in range(8)]
    + [(f"PTYPE_{i}", 12, 12) for i in range(8)]
    + [(f"ETYPE_{i}", 12, 12) for i in range(4)]
    + [(f"MINE_{i}", 12, 12) for i in range(2)]
    + [(f"ASTEROID_{i}", 16, 16) for i in range(2)]
    + [("POD", 16, 16), ("CORE_CLOSED", 16, 16), ("CORE_OPEN", 16, 16)]
    + [(f"EXPL_{i}", 16, 16) for i in range(4)]
    + [("SHOT_PLAYER", 2, 6), ("SHOT_ENEMY", 4, 4)]
    + [(f"MISSILE_{i}", 6, 8) for i in range(2)]
    + [("ICON_SHIP", 8, 8), ("ICON_BASE", 8, 8), ("POD_HIT", 16, 16)]
    + [(f"BIGEXPL_{i}", 32, 32) for i in range(4)]
    + [("SHOT_PLAYER_H", 6, 2), ("SHOT_PLAYER_D", 4, 4)]
)
SPR_COUNT = len(SPRITES)
assert SPR_COUNT == 52

# #define names that bosco.h uses for the first id of each group (or the only
# id). Every other id is reached from these by adding an offset.
SPR_DEFINES = (
    ("SPR_SHIP_0", 0), ("SPR_ITYPE_0", 8), ("SPR_PTYPE_0", 16),
    ("SPR_ETYPE_0", 24), ("SPR_MINE_0", 28), ("SPR_ASTEROID_0", 30),
    ("SPR_POD", 32), ("SPR_CORE_CLOSED", 33), ("SPR_CORE_OPEN", 34),
    ("SPR_EXPL_0", 35), ("SPR_SHOT_PLAYER", 39), ("SPR_SHOT_ENEMY", 40),
    ("SPR_MISSILE_0", 41), ("SPR_ICON_SHIP", 43), ("SPR_ICON_BASE", 44),
    ("SPR_POD_HIT", 45), ("SPR_BIGEXPL_0", 46), ("SPR_SHOT_PLAYER_H", 50),
    ("SPR_SHOT_PLAYER_D", 51),
)

# Palette 0, docs/DESIGN.md section 3: (index, name, R, G, B) with 4-bit parts.
PALETTE = (
    (0, "black", 0x0, 0x0, 0x0),
    (1, "white", 0xF, 0xF, 0xF),
    (2, "light gray", 0xA, 0xA, 0xA),
    (3, "dark gray", 0x5, 0x5, 0x5),
    (4, "red", 0xF, 0x0, 0x0),
    (5, "orange", 0xF, 0x8, 0x0),
    (6, "yellow", 0xF, 0xF, 0x0),
    (7, "green", 0x0, 0xC, 0x0),
    (8, "cyan", 0x0, 0xF, 0xF),
    (9, "blue", 0x0, 0x0, 0xF),
    (10, "dark blue", 0x0, 0x0, 0x8),
    (11, "magenta", 0xF, 0x0, 0xF),
    (12, "pink", 0xF, 0x8, 0xB),
    (13, "brown", 0x8, 0x4, 0x0),
    (14, "dark green", 0x0, 0x6, 0x0),
    (15, "light blue", 0x8, 0xB, 0xF),
)

# Pixel characters of sprites.txt. '.' is transparent (None).
PIXEL_CHARS = {
    ".": None,
    "k": 0, "W": 1, "l": 2, "d": 3, "R": 4, "O": 5, "Y": 6, "G": 7,
    "C": 8, "B": 9, "N": 10, "M": 11, "P": 12, "b": 13, "g": 14, "L": 15,
}

FONT_FIRST = 32
FONT_COUNT = 64


class AssetError(Exception):
    pass


# --------------------------------------------------------------------- parsing

def parse_sprites(path: Path) -> dict[str, list[list[int | None]]]:
    """Return name -> grid (rows of pixel values, None = transparent)."""
    lines = path.read_text().split("\n")
    grids: dict[str, list[list[int | None]]] = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        words = line.split()
        if words[0] == "sprite":
            if len(words) != 4:
                raise AssetError(f"{path}:{i}: expected 'sprite NAME W H'")
            name, w, h = words[1], int(words[2]), int(words[3])
            if name in grids:
                raise AssetError(f"{path}:{i}: sprite {name} defined twice")
            grid = []
            for r in range(h):
                if i >= len(lines):
                    raise AssetError(f"{path}:{i}: {name}: file ends inside rows")
                row = lines[i].rstrip("\n")
                i += 1
                if len(row) != w:
                    raise AssetError(
                        f"{path}:{i}: {name} row {r}: {len(row)} chars, expected {w}")
                try:
                    grid.append([PIXEL_CHARS[c] for c in row])
                except KeyError as err:
                    raise AssetError(
                        f"{path}:{i}: {name} row {r}: bad pixel char {err}") from None
            grids[name] = grid
        elif words[0] == "derive":
            # derive NAME = OP SOURCE
            if len(words) != 5 or words[2] != "=":
                raise AssetError(f"{path}:{i}: expected 'derive NAME = OP SOURCE'")
            name, op, source = words[1], words[3], words[4]
            if name in grids:
                raise AssetError(f"{path}:{i}: sprite {name} defined twice")
            if source not in grids:
                raise AssetError(f"{path}:{i}: derive {name}: unknown source {source}")
            try:
                grids[name] = transform(grids[source], op)
            except AssetError as err:
                raise AssetError(f"{path}:{i}: derive {name}: {err}") from None
        else:
            raise AssetError(f"{path}:{i}: unknown directive {words[0]!r}")
    return grids


def transform(grid: list[list[int | None]], op: str) -> list[list[int | None]]:
    h = len(grid)
    w = len(grid[0])
    if op == "copy":
        return [row[:] for row in grid]
    if op == "fliph":
        return [row[::-1] for row in grid]
    if op == "flipv":
        return [row[:] for row in grid[::-1]]
    if op in ("rot90", "rot180", "rot270"):
        if op == "rot180":
            return [row[::-1] for row in grid[::-1]]
        if w != h:
            raise AssetError(f"{op} needs a square sprite, got {w}x{h}")
        if op == "rot90":      # clockwise: new(x, y) = old(y, w-1-x)
            return [[grid[w - 1 - x][y] for x in range(w)] for y in range(h)]
        return [[grid[x][w - 1 - y] for x in range(w)] for y in range(h)]  # rot270
    raise AssetError(f"unknown operation {op!r}")


def parse_font(path: Path) -> list[list[int]]:
    """Return 64 glyphs, each 8 bytes (bit 7 = left pixel)."""
    lines = path.read_text().split("\n")
    glyphs: dict[int, list[int]] = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        words = line.split()
        if words[0] != "glyph" or len(words) < 2:
            raise AssetError(f"{path}:{i}: expected 'glyph CODE NAME'")
        code = int(words[1])
        if not FONT_FIRST <= code < FONT_FIRST + FONT_COUNT:
            raise AssetError(f"{path}:{i}: glyph code {code} outside 32..95")
        if code in glyphs:
            raise AssetError(f"{path}:{i}: glyph {code} defined twice")
        rows = []
        for r in range(8):
            if i >= len(lines):
                raise AssetError(f"{path}:{i}: glyph {code}: file ends inside rows")
            row = lines[i].rstrip("\n")
            i += 1
            if len(row) != 8 or set(row) - {"#", "."}:
                raise AssetError(f"{path}:{i}: glyph {code} row {r}: bad row {row!r}")
            value = 0
            for c in row:
                value = (value << 1) | (1 if c == "#" else 0)
            rows.append(value)
        glyphs[code] = rows
    missing = [c for c in range(FONT_FIRST, FONT_FIRST + FONT_COUNT) if c not in glyphs]
    if missing:
        raise AssetError(f"{path}: missing glyphs: {missing}")
    return [glyphs[c] for c in range(FONT_FIRST, FONT_FIRST + FONT_COUNT)]


# -------------------------------------------------------------------- encoding

def encode_variant(grid: list[list[int | None]], shift: int) -> tuple[bytes, int]:
    """Encode one pre-shifted variant. Returns (bytes, hole_count).

    hole_count is the number of transparent pixels that lie inside a run and
    therefore become black when drawn.
    """
    h = len(grid)
    w = len(grid[0])
    width_bytes = (w + shift + 1) // 2
    out = bytearray((h, width_bytes))
    holes = 0
    for row in grid:
        pixels: list[int | None] = [None] * (width_bytes * 2)
        for x, p in enumerate(row):
            pixels[x + shift] = p
        opaque = [i for i, p in enumerate(pixels) if p is not None]
        if not opaque:
            out.extend(EMPTY_ROW_BYTES)
            continue
        first_byte = opaque[0] // 2
        last_byte = opaque[-1] // 2
        run = pixels[first_byte * 2:(last_byte + 1) * 2]
        holes += sum(1 for p in run[opaque[0] - first_byte * 2: opaque[-1] - first_byte * 2 + 1]
                     if p is None)
        out.append(first_byte)
        out.append(last_byte - first_byte + 1)
        for k in range(0, len(run), 2):
            left = run[k] or 0
            right = run[k + 1] or 0
            out.append((left << 4) | right)
    return bytes(out), holes


def decode_variant(data: bytes) -> tuple[list[list[int | None]], int]:
    """Inverse of encode_variant: returns (grid of width_bytes*2, bytes used)."""
    h, width_bytes = data[0], data[1]
    pos = 2
    grid = []
    for _ in range(h):
        run_off = data[pos]
        if run_off == 0xFF:
            pos += len(EMPTY_ROW_BYTES)
            grid.append([None] * (width_bytes * 2))
            continue
        run_len = data[pos + 1]
        pos += 2
        row: list[int | None] = [None] * (width_bytes * 2)
        for k in range(run_len):
            b = data[pos + k]
            row[(run_off + k) * 2] = b >> 4
            row[(run_off + k) * 2 + 1] = b & 15
        pos += run_len
        grid.append(row)
    return grid, pos


def palette_bytes() -> bytes:
    out = bytearray()
    for _idx, _name, r, g, b in PALETTE:
        out.append((g << 4) | b)
        out.append(r)
    return bytes(out)


# --------------------------------------------------------------------- writing

def byte_lines(data: bytes, per_line: int = 16) -> list[str]:
    lines = []
    for k in range(0, len(data), per_line):
        chunk = data[k:k + per_line]
        lines.append("    .byte " + ",".join(f"${b:02X}" for b in chunk))
    return lines


def build_all(assets_dir: Path):
    grids = parse_sprites(assets_dir / "sprites.txt")
    font = parse_font(assets_dir / "font8.txt")

    missing = [n for n, _, _ in SPRITES if n not in grids]
    if missing:
        raise AssetError(f"sprites.txt: missing sprites: {', '.join(missing)}")
    extra = sorted(set(grids) - {n for n, _, _ in SPRITES})
    if extra:
        raise AssetError(f"sprites.txt: unknown sprites: {', '.join(extra)}")

    encoded = []   # per id: dict(name, w, h, even, odd, holes)
    for name, w, h in SPRITES:
        grid = grids[name]
        if len(grid) != h or len(grid[0]) != w:
            raise AssetError(
                f"{name}: size {len(grid[0])}x{len(grid)}, DESIGN.md says {w}x{h}")
        even, holes_e = encode_variant(grid, 0)
        odd, holes_o = encode_variant(grid, 1)
        encoded.append(dict(name=name, w=w, h=h, grid=grid, even=even, odd=odd,
                            holes=holes_e))
    return encoded, font, grids


def write_assets_s(path: Path, encoded, font) -> dict[str, int]:
    pal = palette_bytes()
    even_total = sum(len(e["even"]) for e in encoded)
    odd_total = sum(len(e["odd"]) for e in encoded)
    tables = SPR_COUNT * 6
    font_total = FONT_COUNT * 8
    totals = dict(even=even_total, odd=odd_total, tables=tables,
                  font=font_total, palette=len(pal))
    totals["total"] = sum(totals.values())

    out = []
    out.append("; Generated by tools/gen_assets.py from assets/sprites.txt and")
    out.append("; assets/font8.txt. Do not edit; edit the text art instead.")
    out.append(";")
    out.append("; Sprite format (docs/DESIGN.md section 4): height, width_bytes, then")
    out.append("; per row: run_off, run_len, run_len bytes (high nibble = left pixel).")
    out.append(f"; Empty row = {', '.join(f'${b:02X}' for b in EMPTY_ROW_BYTES)}"
               f" ({len(EMPTY_ROW_BYTES)} bytes, no pixel data).")
    out.append(";")
    out.append("; Byte totals:")
    out.append(f";   even variants : {even_total:6d}")
    out.append(f";   odd variants  : {odd_total:6d}")
    out.append(f";   id tables     : {tables:6d}  (6 tables x {SPR_COUNT})")
    out.append(f";   font          : {font_total:6d}")
    out.append(f";   palette       : {len(pal):6d}")
    out.append(f";   total         : {totals['total']:6d}")
    out.append(";")
    out.append(";  id  name           w  h  even  odd")
    for i, e in enumerate(encoded):
        out.append(f";  {i:2d}  {e['name']:<13s} {e['w']:2d} {e['h']:2d}  "
                   f"{len(e['even']):4d} {len(e['odd']):4d}")
    out.append("")
    out.append("    .export _spr_even_lo, _spr_even_hi, _spr_odd_lo, _spr_odd_hi")
    out.append("    .export _spr_width, _spr_height, _font8, _palette0")
    out.append(f"SPR_COUNT = {SPR_COUNT}")
    out.append("")
    out.append('    .segment "RODATA"')
    out.append("")
    for i, e in enumerate(encoded):
        for variant in ("even", "odd"):
            data = e[variant]
            out.append(f"spr_{i:02d}_{variant}:    ; {e['name']} {e['w']}x{e['h']}, "
                       f"{variant}, {data[1]} bytes/row, {len(data)} bytes")
            out.extend(byte_lines(data))
        out.append("")

    def table(label: str, kind: str, variant: str):
        out.append(f"{label}:")
        names = [f"spr_{i:02d}_{variant}" for i in range(SPR_COUNT)]
        for k in range(0, SPR_COUNT, 8):
            out.append(f"    .{kind} " + ",".join(names[k:k + 8]))

    table("_spr_even_lo", "lobytes", "even")
    table("_spr_even_hi", "hibytes", "even")
    table("_spr_odd_lo", "lobytes", "odd")
    table("_spr_odd_hi", "hibytes", "odd")
    out.append("_spr_width:")
    out.extend(byte_lines(bytes(e["w"] for e in encoded)))
    out.append("_spr_height:")
    out.extend(byte_lines(bytes(e["h"] for e in encoded)))
    out.append("")
    out.append("; 64 glyphs x 8 rows, ASCII 32..95, bit 7 = leftmost pixel")
    out.append("_font8:")
    for k, glyph in enumerate(font):
        code = FONT_FIRST + k
        label = chr(code) if code > 32 else "space"
        out.append("    .byte " + ",".join(f"${b:02X}" for b in glyph)
                   + f"    ; {code} {label}")
    out.append("")
    out.append("; palette 0: 16 entries, little-endian $0RGB (byte0 = G<<4|B, byte1 = R)")
    out.append("_palette0:")
    for idx, name, r, g, b in PALETTE:
        out.append(f"    .byte ${(g << 4) | b:02X},${r:02X}    ; {idx:2d} {name} "
                   f"{r:X}{g:X}{b:X}")
    out.append("")
    path.write_text("\n".join(out))
    return totals


def write_assets_h(path: Path, encoded) -> None:
    out = []
    out.append("/* Generated by tools/gen_assets.py. Do not edit. */")
    out.append("/*")
    out.append(" * Sprite ids (docs/DESIGN.md section 9). The SPR_* values below are the")
    out.append(" * same as in bosco.h; the compiler reports a mismatch if they differ.")
    out.append(" *")
    out.append(" *  id  name           w  h")
    for i, e in enumerate(encoded):
        out.append(f" *  {i:2d}  {e['name']:<13s} {e['w']:2d} {e['h']:2d}")
    out.append(" */")
    out.append("#ifndef ASSETS_H")
    out.append("#define ASSETS_H")
    out.append("")
    for name, value in SPR_DEFINES:
        out.append(f"#define {name} {value}")
    out.append(f"#define SPR_COUNT {SPR_COUNT}")
    out.append("")
    out.append("extern const unsigned char spr_even_lo[SPR_COUNT];")
    out.append("extern const unsigned char spr_even_hi[SPR_COUNT];")
    out.append("extern const unsigned char spr_odd_lo[SPR_COUNT];")
    out.append("extern const unsigned char spr_odd_hi[SPR_COUNT];")
    out.append("extern const unsigned char spr_width[SPR_COUNT];")
    out.append("extern const unsigned char spr_height[SPR_COUNT];")
    out.append("extern const unsigned char font8[64 * 8];")
    out.append("extern const unsigned char palette0[32];")
    out.append("")
    out.append("#endif")
    out.append("")
    path.write_text("\n".join(out))


def write_preview(path: Path, encoded, font) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    scale = 4
    cols = 10
    cell = 36 * scale          # 32 px sprite + margin
    label_h = 10
    rows = math.ceil(SPR_COUNT / cols)
    font_rows = 4
    font_h = font_rows * 9 * scale + label_h
    img = Image.new("RGB", (cols * cell, rows * (cell + label_h) + font_h), (24, 24, 32))
    draw = ImageDraw.Draw(img)
    rgb = {idx: (r * 17, g * 17, b * 17) for idx, _n, r, g, b in PALETTE}
    for i, e in enumerate(encoded):
        # decode the encoded bytes so the preview shows what the blitter draws
        grid, _ = decode_variant(e["even"])
        ox = (i % cols) * cell + 2 * scale
        oy = (i // cols) * (cell + label_h) + label_h
        draw.rectangle((ox - 1, oy - 1, ox + e["w"] * scale, oy + e["h"] * scale),
                       outline=(60, 60, 80), fill=(0, 0, 0))
        for y, row in enumerate(grid):
            for x in range(e["w"]):
                p = row[x]
                if p is None:
                    continue
                draw.rectangle((ox + x * scale, oy + y * scale,
                                ox + x * scale + scale - 1, oy + y * scale + scale - 1),
                               fill=rgb[p])
        draw.text((ox, oy - label_h), f"{i} {e['name']}", fill=(200, 200, 200))
    # font strip
    fy = rows * (cell + label_h) + label_h
    draw.text((2, fy - label_h), "font8 (ASCII 32..95)", fill=(200, 200, 200))
    for k, glyph in enumerate(font):
        gx = (k % 16) * 9 * scale + 2
        gy = fy + (k // 16) * 9 * scale
        for y, bits in enumerate(glyph):
            for x in range(8):
                if bits & (0x80 >> x):
                    draw.rectangle((gx + x * scale, gy + y * scale,
                                    gx + x * scale + scale - 1, gy + y * scale + scale - 1),
                                   fill=(255, 255, 255))
    img.save(path)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        encoded, font, _grids = build_all(args.assets)
    except (AssetError, OSError, ValueError) as err:
        print(f"gen_assets: {err}", file=sys.stderr)
        return 1

    args.build.mkdir(parents=True, exist_ok=True)
    totals = write_assets_s(args.build / "assets.s", encoded, font)
    write_assets_h(args.build / "assets.h", encoded)
    preview = write_preview(args.build / "assets_preview.png", encoded, font)

    if not args.quiet:
        holes = [(e["name"], e["holes"]) for e in encoded if e["holes"]]
        print(f"assets.s: {totals['total']} bytes "
              f"(even {totals['even']}, odd {totals['odd']}, tables {totals['tables']}, "
              f"font {totals['font']}, palette {totals['palette']})")
        if holes:
            print("transparent pixels inside runs (drawn black): "
                  + ", ".join(f"{n}={c}" for n, c in holes))
        print("preview:", "written" if preview else "skipped (Pillow not installed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
