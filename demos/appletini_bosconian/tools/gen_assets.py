#!/usr/bin/env python3
"""Convert the text art in assets/ into build/assets.s, assets.h, BOSCO.SPR and a preview.

Inputs (see the header comments of each file for the exact syntax):
  assets/sprites.txt   sprite art, one character per pixel, plus "derive"
                       lines that rotate, mirror or pad an earlier sprite
                       (--sprites FILE reads another file in the same format,
                       such as build/rom/sprites.txt from tools/bosco_rom.py)
  assets/font8.txt     64 glyphs of 8x8 pixels for ASCII 32..95
                       (--font FILE reads another one, e.g. build/rom/font8.txt)

Outputs:
  build/assets.s            ca65 source, segment RODATA: the id tables, the
                            sprites that stay in main memory, font, palette
  build/BOSCO.SPR           the sprites that live in the language cards; the
                            game loads it at start (loader.s). Format below.
  build/assets.h            SPR_* ids and a comment table of ids and sizes
  build/assets_preview.png  all sprites on a grid at 4x (only if Pillow imports)

Where the sprites live (docs/DESIGN.md section 2): the run-encoded arcade
graphics (about 21 KB) do not fit the free main memory, so most of them are
loaded into the auxiliary language card, which ProDOS never touches (the
main card is ProDOS's own). REGIONS lists the areas in fill order; a sprite
(both of its variants) goes into the first region with room, and what is
left over is assembled into RODATA. _spr_bank tells video.s how to reach an
id: bit 2 = the auxiliary card (ALTZP on while blitting), bit 1 = bank 1 of
$D000-$DFFF instead of bank 2. The two panel icons always stay in main
memory (MAIN_ONLY) because panel_sprite does not switch banks, and so does
the panel's CONDITION caption.

BOSCO.SPR: "BSPR", u8 region count, then per region u16 load address,
u16 length, u8 bank code (5 bytes each), then the region blobs in order.

Sprite format written for video.s (docs/DESIGN.md section 4):
  byte 0: height H, byte 1: width in bytes W of this variant, then one or
  more run records per row: run_off, run_len, run_len bytes of pixel pairs
  (high nibble = left pixel). Bit 7 of run_off set (RUN_MORE) means another
  run of the same row follows; a transparent gap of at least SPLIT_GAP bytes
  between opaque bytes starts a new run, so that big holes (the inside of an
  explosion, the space between wing tips) stay see-through. Smaller gaps are
  stored as black pixels. An empty row is run_off = $FF, run_len = 0
  (EMPTY_ROW_BYTES below), so every record starts with two header bytes.
  The "odd" variant is the image shifted right by one pixel and is one byte
  wider when the pixel width is even.

Only the Python standard library is required. Pillow is optional and used
for the preview picture only.
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ASSETS = PROJECT_DIR / "assets"
DEFAULT_BUILD = PROJECT_DIR / "build"

# Empty row record: run_off $FF, then a run_len byte of 0. Set to (0xFF,) if
# video.s expects a single byte per empty row.
EMPTY_ROW_BYTES = (0xFF, 0x00)
# run_off flag: more runs follow in this row. run_off itself is at most 31
# (sprites are at most 64 pixels wide), so bit 7 is free.
RUN_MORE = 0x80
# a gap of this many fully transparent bytes between opaque bytes splits a
# row into two runs (smaller gaps are drawn black)
SPLIT_GAP = 2

# The six cannon pods of a base in drawing order (docs/DESIGN.md section 9):
# axis pod, four corner pods, axis pod. A corner pod is drawn with its strut,
# which the arcade replaces together with the pod when it is destroyed, so
# its box is 24x24; the axis pods are plain 16x16 objects.
POD_SIZES = (16, 24, 24, 24, 24, 16)


def _pods(prefix: str):
    return [(f"{prefix}{i}", s, s) for i, s in enumerate(POD_SIZES)]


# Sprite id list, fixed by docs/DESIGN.md section 9 (name, width, height).
# The sizes are those of the arcade graphics: 16x16 sprites, 2x2-tile
# objects, the base parts cut from the arcade's tile grids, the bullet dots.
SPRITES = (
    [(f"SHIP_{i}", 16, 16) for i in range(8)]          # 0..7   headings N NE E SE S SW W NW
    + [(f"ITYPE_{i}", 16, 16) for i in range(8)]       # 8..15
    + [(f"PTYPE_{i}", 16, 16) for i in range(8)]       # 16..23
    + [(f"ETYPE_{i}", 16, 16) for i in range(8)]       # 24..31
    + [(f"SPY_{i}", 16, 16) for i in range(8)]         # 32..39
    + [("MINE", 16, 16)]                               # 40
    + [(f"ASTEROID_{i}", 16, 16) for i in range(3)]    # 41..43
    + [(f"EXPL_{i}", 16, 16) for i in range(3)]        # 44..46
    + [(f"BIGEXPL_{i}", 32, 32) for i in range(3)]     # 47..49
    + [("CORE_V", 32, 40), ("CORE_H", 40, 32)]         # 50, 51
    + _pods("POD_V")                                   # 52..57  top UL UR LL LR bottom
    + _pods("PODDEAD_V")                               # 58..63  the same pods destroyed
    + _pods("POD_H")                                   # 64..69  left TL TR BL BR right
    + _pods("PODDEAD_H")                               # 70..75
    + [("SHOT_PLAYER", 2, 4), ("SHOT_PLAYER_H", 4, 2)] # 76, 77
    + [("SHOT_PLAYER_D1", 4, 4), ("SHOT_PLAYER_D2", 4, 4)]  # 78, 79  "/" and "\"
    + [("SHOT_ENEMY", 4, 4)]                           # 80
    + [(f"MISSILE_{i}", 4, 4) for i in range(2)]       # 81, 82
    + [("ICON_SHIP", 16, 16), ("ICON_BASE", 8, 8)]     # 83, 84
    + [("CAPTION_COND", 62, 8)]                        # 85  the panel's CONDITION caption
)
SPR_COUNT = len(SPRITES)
assert SPR_COUNT == 86
SPRITE_SIZES = {name: (w, h) for name, w, h in SPRITES}

# Sprites that must stay in main memory (drawn by panel_sprite, which does
# not switch language-card banks).
MAIN_ONLY = {"ICON_SHIP", "ICON_BASE", "CAPTION_COND"}

# #define names that bosco.h uses for the first id of each group (or the only
# id). Every other id is reached from these by adding an offset.
SPR_DEFINES = (
    ("SPR_SHIP_0", 0), ("SPR_ITYPE_0", 8), ("SPR_PTYPE_0", 16),
    ("SPR_ETYPE_0", 24), ("SPR_SPY_0", 32), ("SPR_MINE", 40),
    ("SPR_ASTEROID_0", 41), ("SPR_EXPL_0", 44), ("SPR_BIGEXPL_0", 47),
    ("SPR_CORE_V", 50), ("SPR_CORE_H", 51), ("SPR_POD_V0", 52),
    ("SPR_PODDEAD_V0", 58), ("SPR_POD_H0", 64), ("SPR_PODDEAD_H0", 70),
    ("SPR_SHOT_PLAYER", 76), ("SPR_SHOT_PLAYER_H", 77),
    ("SPR_SHOT_PLAYER_D1", 78), ("SPR_SHOT_PLAYER_D2", 79),
    ("SPR_SHOT_ENEMY", 80), ("SPR_MISSILE_0", 81), ("SPR_ICON_SHIP", 83),
    ("SPR_ICON_BASE", 84), ("SPR_CAPTION_COND", 85),
)
for _name, _value in SPR_DEFINES:
    assert SPRITES[_value][0] == _name[4:], (_name, _value)

# Palette 0, docs/DESIGN.md section 3: the arcade's colour PROM, black first
# (its 15 colours plus black fill the 16 entries exactly). (index, name,
# R, G, B) with 4-bit parts: the 8-bit arcade values divided by 17.
PALETTE = (
    (0, "black", 0x0, 0x0, 0x0),
    (1, "white", 0xD, 0xD, 0xD),        # #dedede
    (2, "red", 0xF, 0x0, 0x0),          # #ff0000
    (3, "orange", 0xF, 0x6, 0x0),       # #ff6800
    (4, "yellow", 0xF, 0xF, 0x0),       # #ffff00
    (5, "purple", 0x9, 0x0, 0xD),       # #9700de
    (6, "pink", 0xF, 0x6, 0xD),         # #ff68de
    (7, "cyan", 0x0, 0xF, 0xD),         # #00ffde
    (8, "blue", 0x0, 0x6, 0xD),         # #0068de
    (9, "brown", 0x6, 0x2, 0x0),        # #682100
    (10, "green", 0x0, 0xB, 0x0),       # #00b800
    (11, "violet", 0x6, 0x0, 0xD),      # #6800de
    (12, "dark teal", 0x2, 0x4, 0x4),   # #214747
    (13, "gold", 0xD, 0x9, 0x0),        # #de9700
    (14, "dark red", 0xB, 0x2, 0x0),    # #b82100
    (15, "gray", 0x9, 0x9, 0x9),        # #979797
)

# Pixel characters of sprites.txt. '.' is transparent (None).
PIXEL_CHARS = {
    ".": None,
    "k": 0, "W": 1, "R": 2, "O": 3, "Y": 4, "P": 5, "M": 6, "C": 7,
    "B": 8, "b": 9, "G": 10, "V": 11, "d": 12, "g": 13, "r": 14, "l": 15,
}

# Bank code bits of _spr_bank (bosco.inc has the same values).
BANK_RODATA = 0        # main memory, always mapped
BANK_1 = 2             # bank 1 of $D000-$DFFF instead of bank 2
BANK_AUX = 4           # the auxiliary card: ALTZP on while blitting

# Sprite regions in fill order: (name, bank code, first address, size).
# $D000-$FFEF of the auxiliary card is bank 2 of $D000-$DFFF plus
# $E000-$FFEF; the top 16 bytes are left alone (vectors). Bank 1 adds
# another 4 KB. The main card is not used: ProDOS lives there.
REGIONS = (
    ("AUX_LC2", BANK_AUX, 0xD000, 0x2FF0),
    ("AUX_LC1", BANK_AUX | BANK_1, 0xD000, 0x1000),
)
SPR_FILE_MAGIC = b"BSPR"
SPR_FILE_NAME = "BOSCO.SPR"

FONT_FIRST = 32
FONT_COUNT = 64


class AssetError(Exception):
    pass


# --------------------------------------------------------------------- parsing

def parse_sprites(path: Path) -> dict[str, list[list[int | None]]]:
    """Return name -> grid (rows of pixel values, None = transparent).

    Names starting with "_" are helpers: they may be any size and are only
    used as sources of derive lines.
    """
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
            # derive NAME = OP SOURCE          OP: copy fliph flipv rot90 rot180 rot270
            # derive NAME = pad SOURCE [X Y]   SOURCE centred in NAME's box, or its
            #                                  top-left corner put at X,Y
            if len(words) < 5 or words[2] != "=":
                raise AssetError(f"{path}:{i}: expected 'derive NAME = OP SOURCE'")
            name, op, source = words[1], words[3], words[4]
            if name in grids:
                raise AssetError(f"{path}:{i}: sprite {name} defined twice")
            if source not in grids:
                raise AssetError(f"{path}:{i}: derive {name}: unknown source {source}")
            try:
                if op == "pad":
                    if name not in SPRITE_SIZES:
                        raise AssetError("pad needs a listed sprite name")
                    w, h = SPRITE_SIZES[name]
                    if len(words) == 5:
                        grids[name] = pad_grid(grids[source], w, h)
                    elif len(words) == 7:
                        grids[name] = pad_grid(grids[source], w, h,
                                               int(words[5]), int(words[6]))
                    else:
                        raise AssetError("expected 'derive NAME = pad SOURCE [X Y]'")
                else:
                    if len(words) != 5:
                        raise AssetError("expected 'derive NAME = OP SOURCE'")
                    grids[name] = transform(grids[source], op)
            except AssetError as err:
                raise AssetError(f"{path}:{i}: derive {name}: {err}") from None
        else:
            raise AssetError(f"{path}:{i}: unknown directive {words[0]!r}")
    return grids


def pad_grid(grid, w: int, h: int, ox: int | None = None, oy: int | None = None):
    """Put grid into a w x h box of transparent pixels, centred unless an
    offset of its top-left corner is given."""
    gh, gw = len(grid), len(grid[0])
    if ox is None:
        ox = (w - gw) // 2
    if oy is None:
        oy = (h - gh) // 2
    if ox < 0 or oy < 0 or ox + gw > w or oy + gh > h:
        raise AssetError(f"pad: {gw}x{gh} at {ox},{oy} does not fit in {w}x{h}")
    out = [[None] * w for _ in range(h)]
    for y, row in enumerate(grid):
        for x, p in enumerate(row):
            out[oy + y][ox + x] = p
    return out


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
        opaque_bytes = [k for k in range(width_bytes)
                        if pixels[2 * k] is not None or pixels[2 * k + 1] is not None]
        if not opaque_bytes:
            out.extend(EMPTY_ROW_BYTES)
            continue
        # split the row at gaps of SPLIT_GAP or more transparent bytes
        runs: list[tuple[int, int]] = []      # (first byte, last byte)
        start = prev = opaque_bytes[0]
        for k in opaque_bytes[1:]:
            if k - prev - 1 >= SPLIT_GAP:
                runs.append((start, prev))
                start = k
            prev = k
        runs.append((start, prev))
        for n, (first_byte, last_byte) in enumerate(runs):
            run = pixels[first_byte * 2:(last_byte + 1) * 2]
            first_px = next(i for i, p in enumerate(run) if p is not None)
            last_px = len(run) - 1 - next(i for i, p in enumerate(run[::-1]) if p is not None)
            holes += sum(1 for p in run[first_px:last_px + 1] if p is None)
            out.append(first_byte | (RUN_MORE if n + 1 < len(runs) else 0))
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
        row: list[int | None] = [None] * (width_bytes * 2)
        while True:
            run_off = data[pos]
            if run_off == 0xFF:
                pos += len(EMPTY_ROW_BYTES)
                break
            more = run_off & RUN_MORE
            run_off &= ~RUN_MORE & 0xFF
            run_len = data[pos + 1]
            pos += 2
            for k in range(run_len):
                b = data[pos + k]
                row[(run_off + k) * 2] = b >> 4
                row[(run_off + k) * 2 + 1] = b & 15
            pos += run_len
            if not more:
                break
        grid.append(row)
    return grid, pos


def palette_bytes() -> bytes:
    out = bytearray()
    for _idx, _name, r, g, b in PALETTE:
        out.append((g << 4) | b)
        out.append(r)
    return bytes(out)


# ------------------------------------------------------------------- placement

def place_sprites(encoded, regions=REGIONS) -> list[bytearray]:
    """Give every id a home: the first region with room for both variants
    (first fit, in id order), else RODATA. Sets bank, even_addr and odd_addr
    on each entry (addresses are None in RODATA) and returns the region
    blobs in region order."""
    blobs = [bytearray() for _ in regions]
    for e in encoded:
        e["bank"] = BANK_RODATA
        e["even_addr"] = e["odd_addr"] = None
        if e["name"] in MAIN_ONLY:
            continue
        need = len(e["even"]) + len(e["odd"])
        for k, (_name, bank, base, size) in enumerate(regions):
            if len(blobs[k]) + need <= size:
                e["bank"] = bank
                e["even_addr"] = base + len(blobs[k])
                blobs[k] += e["even"]
                e["odd_addr"] = base + len(blobs[k])
                blobs[k] += e["odd"]
                break
    return blobs


def spr_file_bytes(blobs, regions=REGIONS) -> bytes:
    """BOSCO.SPR image: header, region table (non-empty regions), blobs."""
    used = [(reg, blob) for reg, blob in zip(regions, blobs) if blob]
    out = bytearray(SPR_FILE_MAGIC)
    out.append(len(used))
    for (_name, bank, base, _size), blob in used:
        out += struct.pack("<HHB", base, len(blob), bank)
    for _reg, blob in used:
        out += blob
    return bytes(out)


def parse_spr_file(data: bytes) -> list[tuple[int, int, int, bytes]]:
    """Inverse of spr_file_bytes: [(load address, length, bank, blob)]."""
    if data[:4] != SPR_FILE_MAGIC:
        raise AssetError("not a BOSCO.SPR file")
    count = data[4]
    table = []
    pos = 5
    for _ in range(count):
        addr, length, bank = struct.unpack_from("<HHB", data, pos)
        pos += 5
        table.append((addr, length, bank))
    out = []
    for addr, length, bank in table:
        out.append((addr, length, bank, data[pos:pos + length]))
        pos += length
    if pos != len(data):
        raise AssetError("BOSCO.SPR length does not match its table")
    return out


# --------------------------------------------------------------------- writing

def byte_lines(data: bytes, per_line: int = 16) -> list[str]:
    lines = []
    for k in range(0, len(data), per_line):
        chunk = data[k:k + per_line]
        lines.append("    .byte " + ",".join(f"${b:02X}" for b in chunk))
    return lines


def build_all(assets_dir: Path, sprites_path: Path | None = None,
              font_path: Path | None = None, regions=REGIONS):
    grids = parse_sprites(sprites_path or assets_dir / "sprites.txt")
    font = parse_font(font_path or assets_dir / "font8.txt")

    missing = [n for n, _, _ in SPRITES if n not in grids]
    if missing:
        raise AssetError(f"sprites.txt: missing sprites: {', '.join(missing)}")
    extra = sorted(n for n in grids if n not in SPRITE_SIZES and not n.startswith("_"))
    if extra:
        raise AssetError(f"sprites.txt: unknown sprites: {', '.join(extra)}")

    encoded = []   # per id: dict(name, w, h, grid, even, odd, holes, bank, addrs)
    for name, w, h in SPRITES:
        grid = grids[name]
        if len(grid) != h or len(grid[0]) != w:
            raise AssetError(
                f"{name}: size {len(grid[0])}x{len(grid)}, DESIGN.md says {w}x{h}")
        even, holes_e = encode_variant(grid, 0)
        odd, _holes_o = encode_variant(grid, 1)
        encoded.append(dict(name=name, w=w, h=h, grid=grid, even=even, odd=odd,
                            holes=holes_e))
    blobs = place_sprites(encoded, regions)
    return encoded, font, grids, blobs


def region_name(bank: int, regions=REGIONS) -> str:
    for name, code, _base, _size in regions:
        if code == bank:
            return name
    return "RODATA"


def write_assets_s(path: Path, encoded, font, blobs, regions=REGIONS) -> dict[str, int]:
    pal = palette_bytes()
    even_total = sum(len(e["even"]) for e in encoded)
    odd_total = sum(len(e["odd"]) for e in encoded)
    rodata_sprites = sum(len(e["even"]) + len(e["odd"]) for e in encoded
                         if e["bank"] == BANK_RODATA)
    tables = SPR_COUNT * 7
    font_total = FONT_COUNT * 8
    totals = dict(even=even_total, odd=odd_total, tables=tables,
                  font=font_total, palette=len(pal), sprites=even_total + odd_total,
                  rodata_sprites=rodata_sprites, lc=sum(len(b) for b in blobs))
    totals["rodata"] = rodata_sprites + tables + font_total + len(pal)

    out = []
    out.append("; Generated by tools/gen_assets.py from the sprite text art and")
    out.append("; the font. Do not edit; edit the text art instead.")
    out.append(";")
    out.append("; Sprite format (docs/DESIGN.md section 4): height, width_bytes, then")
    out.append("; per row one or more runs: run_off, run_len, run_len bytes (high nibble")
    out.append(f"; = left pixel); run_off bit 7 (${RUN_MORE:02X}) = another run of this row follows.")
    out.append(f"; Empty row = {', '.join(f'${b:02X}' for b in EMPTY_ROW_BYTES)}"
               f" ({len(EMPTY_ROW_BYTES)} bytes, no pixel data).")
    out.append(";")
    out.append("; Byte totals:")
    out.append(f";   even variants : {even_total:6d}")
    out.append(f";   odd variants  : {odd_total:6d}")
    out.append(f";   in BOSCO.SPR  : {totals['lc']:6d}  (language cards)")
    out.append(f";   in RODATA     : {rodata_sprites:6d}  (sprites)")
    out.append(f";   id tables     : {tables:6d}  (7 tables x {SPR_COUNT})")
    out.append(f";   font          : {font_total:6d}")
    out.append(f";   palette       : {len(pal):6d}")
    out.append(f";   RODATA total  : {totals['rodata']:6d}")
    out.append(";")
    out.append("; Regions (bank code, $first-$last, used/size):")
    for (name, bank, base, size), blob in zip(regions, blobs):
        out.append(f";   {name:<9s} bank {bank}  ${base:04X}-${base + size - 1:04X}"
                   f"  {len(blob):5d}/{size}")
    out.append(";")
    out.append(";  id  name             w  h  even  odd  where")
    for i, e in enumerate(encoded):
        where = region_name(e["bank"], regions)
        if e["even_addr"] is not None:
            where += f" ${e['even_addr']:04X}"
        out.append(f";  {i:2d}  {e['name']:<15s} {e['w']:2d} {e['h']:2d}  "
                   f"{len(e['even']):4d} {len(e['odd']):4d}  {where}")
    out.append("")
    out.append("    .export _spr_even_lo, _spr_even_hi, _spr_odd_lo, _spr_odd_hi")
    out.append("    .export _spr_width, _spr_height, _spr_bank, _font8, _palette0")
    out.append(f"SPR_COUNT = {SPR_COUNT}")
    out.append("")
    out.append("; language-card sprites: addresses inside BOSCO.SPR's regions")
    for i, e in enumerate(encoded):
        if e["even_addr"] is not None:
            out.append(f"spr_{i:02d}_even = ${e['even_addr']:04X}    ; {e['name']} "
                       f"{region_name(e['bank'], regions)}")
            out.append(f"spr_{i:02d}_odd  = ${e['odd_addr']:04X}")
    out.append("")
    out.append('    .segment "RODATA"')
    out.append("")
    for i, e in enumerate(encoded):
        if e["even_addr"] is not None:
            continue
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
    out.append("; bank code per id: 0 main memory; bit 2 auxiliary language card (ALTZP),")
    out.append("; bit 1 its bank 1 of $D000-$DFFF instead of bank 2")
    out.append("_spr_bank:")
    out.extend(byte_lines(bytes(e["bank"] for e in encoded)))
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


def write_assets_h(path: Path, encoded, regions=REGIONS) -> None:
    out = []
    out.append("/* Generated by tools/gen_assets.py. Do not edit. */")
    out.append("/*")
    out.append(" * Sprite ids (docs/DESIGN.md section 9). The SPR_* values below are the")
    out.append(" * same as in bosco.h; the compiler reports a mismatch if they differ.")
    out.append(" *")
    out.append(" *  id  name             w  h  where")
    for i, e in enumerate(encoded):
        out.append(f" *  {i:2d}  {e['name']:<15s} {e['w']:2d} {e['h']:2d}  "
                   f"{region_name(e['bank'], regions)}")
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
    out.append("extern const unsigned char spr_bank[SPR_COUNT];")
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
    cell = 44 * scale          # 40 px sprite + margin
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
    parser.add_argument("--sprites", type=Path, default=None,
                        help="sprite text art to use instead of assets/sprites.txt "
                             "(tools/bosco_rom.py writes one from the arcade ROMs)")
    parser.add_argument("--font", type=Path, default=None,
                        help="font to use instead of assets/font8.txt")
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        encoded, font, _grids, blobs = build_all(args.assets, args.sprites, args.font)
    except (AssetError, OSError, ValueError) as err:
        print(f"gen_assets: {err}", file=sys.stderr)
        return 1

    args.build.mkdir(parents=True, exist_ok=True)
    totals = write_assets_s(args.build / "assets.s", encoded, font, blobs)
    write_assets_h(args.build / "assets.h", encoded)
    spr = spr_file_bytes(blobs)
    (args.build / SPR_FILE_NAME).write_bytes(spr)
    preview = write_preview(args.build / "assets_preview.png", encoded, font)

    if not args.quiet:
        holes = [(e["name"], e["holes"]) for e in encoded if e["holes"]]
        print(f"sprites: {totals['sprites']} bytes (even {totals['even']}, odd "
              f"{totals['odd']}); {SPR_FILE_NAME}: {len(spr)} bytes in "
              f"{sum(1 for b in blobs if b)} regions; RODATA: {totals['rodata']} bytes "
              f"(sprites {totals['rodata_sprites']}, tables {totals['tables']}, "
              f"font {totals['font']}, palette {totals['palette']})")
        for (name, _bank, _base, size), blob in zip(REGIONS, blobs):
            print(f"  {name:<9s} {len(blob):5d}/{size} bytes")
        if holes:
            print("transparent pixels inside runs (drawn black): "
                  + ", ".join(f"{n}={c}" for n, c in holes))
        print("preview:", "written" if preview else "skipped (Pillow not installed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
