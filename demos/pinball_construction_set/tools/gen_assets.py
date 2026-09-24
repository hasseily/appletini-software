#!/usr/bin/env python3
"""Convert the text art in assets/*.txt into build/assets.s, assets.inc, PCS.SPR and a preview.

Inputs
  assets/*.txt        sprite art, one character per pixel (build/art_format.md),
                      plus "derive NAME = OP SOURCE" lines (OP: fliph, flipv,
                      copy; rot90/rot180/rot270 also work on square art). Every
                      file is read, in name order; the art may be incomplete:
                      a sprite that no file defines becomes a placeholder.
  assets/font.txt     optional glyph overrides of the upstream 5x7 font
                      ("glyph CODE NAME [ADVANCE]" then 7 rows of '#'/'.').
  build/parts.json    the part templates (tools/parts.py): kit order, frames,
                      sprite box and hot y of every library part.
  CDRAW.S / CDRAW.s   the upstream font (FONT and CWIDTH tables), looked for
                      in build/baseline and in the upstream clone.

Outputs (in --build)
  assets.s            ca65 source, segment RODATA: the directory and per-id
                      tables, the sprites that stay in main memory, the
                      palette, the font
  assets.inc          SPR_<NAME> ids, SPR_COUNT, per part kind SPR_<KIND>_FIRST
                      / _FRAMES / _W / _H / _HOTY, font constants
  PCS.SPR             the sprites that live in the auxiliary language card
                      (loaded by src/loader.s); format below
  assets_preview.png  every sprite decoded from its encoded form, at 4x, and
                      the font (only if Pillow imports)

Sprite ids: the parts come first, in the editor's kit order (parts.json),
every kind's frames at consecutive ids (<base>_0 .. <base>_N-1: the runtime
walks frames by adding 4 to its directory pointer), then the drop-target
singles, then the UI sprites, then any extra sprite the art defines. The
names are fixed in this file (PART_SPRITE_NAMES, AUX_SPRITES, UI_SPRITES);
assets.inc is the contract the other modules and tools build on.

A sprite the art does not define is reported and replaced by a visible
violet/white checker of the right size (the parts.json box for a part, 8x8
for a UI sprite) so the build always succeeds; --strict makes it an error.
A part frame drawn at another size than its parts.json box keeps the drawn
size (the artists cover the collision polygon, which can exceed the HGR byte
box); every frame of a kind must be the same size.

Where the sprites live (docs/DESIGN.md sections 4 and 7): the auxiliary
language card, which ProDOS never touches. REGIONS lists its areas in fill
order; a sprite (both variants) goes into the first region with room, in id
order, and what is left over is assembled into RODATA. spr_bank tells the
blitter how to reach an id: bit 2 = the auxiliary card (ALTZP on), bit 1 =
bank 1 of $D000-$DFFF instead of bank 2 (Bosconian's codes: 0, 4, 6).

PCS.SPR: "BSPR", u8 region count, then per region u16 load address, u16
length, u8 bank code (5 bytes each), then the region blobs in order.

Sprite variant format (docs/DESIGN.md section 4, Bosconian's run format):
  byte 0: height H, byte 1: width in bytes W of this variant, then one or
  more run records per row: run_off, run_len, run_len bytes of pixel pairs
  (high nibble = left pixel). Bit 7 of run_off set (RUN_MORE) means another
  run of the same row follows; a transparent gap of at least SPLIT_GAP bytes
  between opaque bytes starts a new run. An empty row is run_off = $FF,
  run_len = 0 (EMPTY_ROW_BYTES). The blitter keeps the background wherever a
  nibble is 0 (per-pixel transparency through its mask table), so the
  transparent pixels inside a run cost nothing visually. The "odd" variant
  is the image shifted right by one pixel and is one byte wider when the
  pixel width is even. spr_dir holds the even and odd variant addresses.

Only the Python standard library is required. Pillow is optional and used
for the preview picture only.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ASSETS = PROJECT_DIR / "assets"
DEFAULT_BUILD = PROJECT_DIR / "build"
DEFAULT_PARTS = DEFAULT_BUILD / "parts.json"
FONT_OVERRIDE_NAME = "font.txt"
# where the upstream CDRAW source is looked for (first hit wins)
CDRAW_CANDIDATES = (
    PROJECT_DIR / "build" / "baseline" / "CDRAW.s",
    PROJECT_DIR / "upstream" / "source_disc1" / "CDRAW.S",
    Path("/home/user/billbudge/pcs_appleii/source_disc1/CDRAW.S"),
)

# Empty row record: run_off $FF, then a run_len byte of 0.
EMPTY_ROW_BYTES = (0xFF, 0x00)
# run_off flag: more runs follow in this row. run_off is a byte column, at
# most 126 (MAX_WIDTH below), so bit 7 is free.
RUN_MORE = 0x80
# a gap of this many fully transparent bytes between opaque bytes splits a
# row into two runs (a shorter gap costs as much as a run header and is
# stored as nibble-0 pixels, which the blitter leaves transparent)
SPLIT_GAP = 2
MAX_WIDTH = 253            # (w + 1 + 1) // 2 <= 127 keeps run_off below RUN_MORE
MAX_HEIGHT = 255

# Palette 0, docs/DESIGN.md section 3: (index, name, R, G, B) 4-bit parts.
PALETTE = (
    (0, "black", 0x0, 0x0, 0x0),
    (1, "dark grey", 0x3, 0x3, 0x3),
    (2, "grey", 0x7, 0x7, 0x7),
    (3, "light grey", 0xB, 0xB, 0xB),
    (4, "white", 0xF, 0xF, 0xF),
    (5, "dark red", 0x9, 0x0, 0x0),
    (6, "red", 0xF, 0x3, 0x3),
    (7, "orange", 0xF, 0x8, 0x0),
    (8, "yellow", 0xF, 0xF, 0x3),
    (9, "dark green", 0x0, 0x6, 0x3),
    (10, "green", 0x3, 0xC, 0x3),
    (11, "navy", 0x1, 0x2, 0x4),
    (12, "blue", 0x3, 0x9, 0xF),
    (13, "cyan", 0x6, 0xE, 0xF),
    (14, "violet", 0x9, 0x3, 0xE),
    (15, "brown", 0x9, 0x6, 0x3),
)

# Pixel characters of the art files (build/art_format.md). '.' is
# transparent (None); the letters are palette indices 1..15 in this order.
PIXEL_CHARS = {".": None}
for _k, _c in enumerate("dglWrROYeGnBCVb", start=1):
    PIXEL_CHARS[_c] = _k

# the placeholder checker of a missing sprite: violet and white
PLACEHOLDER_COLORS = (14, 4)
PLACEHOLDER_UI_SIZE = (8, 8)

# Bank code bits of spr_bank (the same values as src/loader.s and Bosconian).
BANK_RODATA = 0        # main memory, always mapped
BANK_1 = 2             # bank 1 of $D000-$DFFF instead of bank 2
BANK_AUX = 4           # the auxiliary card: ALTZP on while blitting
BANK_RW1 = 8           # RamWorks bank 1, main-range address: raw rows, not
                       # blitted but fetched row by row (aux_fetch_rows)

# Sprite regions in fill order: (name, bank code, first address, size).
# $D000-$FFEF of the auxiliary card is bank 2 of $D000-$DFFF plus
# $E000-$FFEF; the top 16 bytes are left alone (vectors). Bank 1 adds
# another 4 KB. The main card is not used: ProDOS lives there. RamWorks
# bank 1 above the overlay layer ($2000-$9FFF) holds the RAW sprites.
REGIONS = (
    ("AUX_LC2", BANK_AUX, 0xD000, 0x2FF0),
    ("AUX_LC1", BANK_AUX | BANK_1, 0xD000, 0x1000),
    ("RW1_RAW", BANK_RW1, 0xA000, 0x2000),
)
# Sprites stored as raw rows (ceil(w/2) bytes per row, high nibble = left
# pixel, no runs, nothing transparent) in the BANK_RW1 region: pictures
# drawn whole by a row fetch, too big for the card. Only the even variant
# exists; spr_dir points both entries at it. A raw sprite cannot fall back
# to RODATA (the blitter does not read raw rows and main.s DRAWLOGO fetches
# from RamWorks whatever spr_bank says), and it is drawn in the logo band
# (docs/DESIGN.md section 3: 160 pixels wide, rows 0-63).
RAW_SPRITES: frozenset[str] = frozenset({"logo"})
RAW_MAX_W = 160
RAW_MAX_H = 64
# Sprites that must stay in main memory whatever the room in the card (for
# a routine that cannot switch banks). Empty: every drawing routine of the
# port switches ALTZP itself (docs/DESIGN.md section 4).
MAIN_ONLY: frozenset[str] = frozenset()
# Sprites only ever drawn at an even x: no odd variant is stored and the
# directory's odd entry points at the even variant (a blit at an odd x
# would land one pixel to the left). Only names whose every drawing
# position is fixed and even belong here: the logo band starts at x = 160;
# tools/layout.py puts the tool icons at x = 260/290, the paint swatches at
# 266/296, the polygon icon at 166, the wiring-kit icons at 258..266 and
# 160/168, and the slider scales at the upstream's 182/238 (main.s draws
# the knob at the scale's x). Cursors, the caret, the parts and anything
# not yet placed by a module (mag_grid, logo_ball) keep both variants.
EVEN_ONLY: frozenset[str] = frozenset({
    "logo", "poly_icon", "slide_scale", "slide_knob",
    "tool_hand", "tool_pointer", "tool_scissor", "tool_hammer", "tool_brush",
    "tool_play", "tool_magnifier", "tool_world", "tool_wire", "tool_disk",
    "swatch_W", "swatch_R", "swatch_O", "swatch_Y", "swatch_G", "swatch_B",
    "swatch_C", "swatch_V",
    "wire_hand", "wire_plier", "wire_screwdriver", "wire_note", "wire_andgate",
})

SPR_FILE_MAGIC = b"BSPR"
SPR_FILE_NAME = "PCS.SPR"

# Part templates whose sprite base name is not the lower-case template name.
PART_SPRITE_NAMES = {
    "LEFTFLIPPER": "lflip",
    "RIGHTFLIPPER": "rflip",
    "LFLIPPER2": "lflip2",
    "RFLIPPER2": "rflip2",
}

# Sprites the play code draws that are not part kinds: the single dropped
# target of a horizontal (DROP1) and of a vertical (DROP2) bank, drawn by
# RUN.S DRAWTARG at 8-pixel steps. (name, width, height, note); the sizes
# are the upstream DROPTXB / DROPTYB bitmaps and only matter for the
# placeholder.
AUX_SPRITES = (
    ("dropx_0", 7, 3, "dropped target of a horizontal bank (RUN.S DROPTXB)"),
    ("dropy_0", 7, 7, "dropped target of a vertical bank (RUN.S DROPTYB)"),
)

# UI sprites: (name, upstream bitmap and size, use). The names are the
# artists' (assets/ui.txt); the sizes are what the original drew
# (build/upstream_icons.txt) and are documentation only: the art sets the
# size, and a missing UI sprite is an 8x8 placeholder.
UI_SPRITES = (
    # cursors (drawn last, with save-under; hot spot = top-left pixel)
    ("cur_hand", "HAND 14x12", "hand cursor: kit, world, disk"),
    ("cur_pointer", "POINTER 7x7", "arrow cursor: points mode"),
    ("cur_scissor", "SCISSOR 14x11", "scissors cursor: cut"),
    ("cur_hammer", "HAMMER 14x11", "hammer cursor: nail"),
    ("cur_brush", "BRUSH 7x8", "brush cursor: paint"),
    # tool strip icons (x 258..319)
    ("tool_hand", "HAND 14x12", "hand tool"),
    ("tool_pointer", "POINTER 7x7", "pointer tool"),
    ("tool_scissor", "SCISSOR 14x11", "scissors tool"),
    ("tool_hammer", "HAMMER 14x11", "hammer tool"),
    ("tool_brush", "BRUSH 7x8", "brush tool"),
    ("tool_play", "PLAYICON 14x10", "play"),
    ("tool_magnifier", "MAGNIFIER 14x10", "magnifier"),
    ("tool_world", "WORLD 14x10", "world (gravity, speed...)"),
    ("tool_wire", "ANDG 21x10", "wiring kit"),
    ("tool_disk", "DISK 14x11", "disk"),
    # the eight paint swatches (docs/DESIGN.md section 3), named by their
    # pixel letter
    ("swatch_W", "WHITEPAINT 14x7", "paint: white (4)"),
    ("swatch_R", "REDPAINT 14x7", "paint: red (6)"),
    ("swatch_O", "-", "paint: orange (7)"),
    ("swatch_Y", "-", "paint: yellow (8)"),
    ("swatch_G", "GREENPAINT 14x7", "paint: green (10)"),
    ("swatch_B", "BLUEPAINT 14x7", "paint: blue (12)"),
    ("swatch_C", "-", "paint: cyan (13)"),
    ("swatch_V", "VIOLETPAINT 14x7", "paint: violet (14)"),
    # wiring kit (WIRE.S): its cursors and icons
    ("wire_hand", "HAND 14x12", "wiring kit: hand"),
    ("wire_plier", "PLIER 21x15", "wiring kit: pliers"),
    ("wire_screwdriver", "SCREWDRIVER 7x16", "wiring kit: screwdriver"),
    ("wire_note", "NOTE 7x12", "wiring kit: sound note icon"),
    ("wire_andgate", "ANDGATE 28x13", "wiring kit: AND gate icon"),
    # editor
    ("poly_icon", "POLYICON 21x16", "kit: the plain polygon"),
    ("slide_scale", "SL1B 7x28", "world screen: slider scale"),
    ("slide_knob", "SLDX 6x6", "world screen: slider knob"),
    ("mag_grid", "-", "magnifier: pixel grid tile"),
    ("caret", "-", "text caret of the file name entry"),
    ("logo_ball", "MBALL 5x5", "balls left, drawn in the logo band"),
    ("logo", "LOGO 160x64", "the logo band picture"),
)

# The upstream mini font (CDRAW.S): 36 glyphs of 7 rows, bit 0 = leftmost
# pixel, 7 pixels wide; codes 0..9 digits, 10..35 letters, 36 space.
FONT_GLYPHS = 37
FONT_ROWS = 7
FONT_SPACE = 36
FONT_UPSTREAM_COUNT = 36
# Fallback copy of the upstream tables (MIT licence), used and reported
# when no CDRAW source is found; the test checks extraction against it.
FONT_FALLBACK = (
    "0E1B1B1B1B1B0E 0607060606060F 0E1B180C06031F 0E1B180C181B0E 1B1B1B1F181818"
    " 1F030F18181B0E 0E1B030F1B1B0E 1F180C06060606 0E1B1B0E1B1B0E 0E1B1B1E181B0E"
    " 0E1B1B1F1B1B1B 0F1B1B0F1B1B0F 0E1B0303031B0E 0F1B1B1B1B1B0F 1F03030F03031F"
    " 1F03030F030303 0E1B031F1B1B0E 1B1B1B1F1B1B1B 0F06060606060F 3C1818181B1B0E"
    " 331B0F070F1B33 0303030303031F 777F6B63636363 33373B33333333 1F1B1B1B1B1B1F"
    " 0F1B1B0F030303 0E1B1B1B1B0E18 0F1B1B0F1B1B1B 0E1B030E181B0E 3F0C0C0C0C0C0C"
    " 1B1B1B1B1B1B0E 1B1B1B1B1B0E04 636363636B7F63 331E0C0C0C1E33 3333331E0C0C0C"
    " 1F180C0603031F"
)
CWIDTH_FALLBACK = ("05040505050505050505" "05050505050505050406060507"
                   "06050505050506050507060605" "04")


class AssetError(Exception):
    pass


def glyph_label(code: int) -> str:
    if code < 10:
        return chr(ord("0") + code)
    if code < FONT_SPACE:
        return chr(ord("A") + code - 10)
    return "space"


# --------------------------------------------------------------------- parsing

def parse_art(path: Path, grids: dict[str, list[list[int | None]]] | None = None,
              sources: dict[str, str] | None = None) -> list[str]:
    """Read one art file into grids (name -> rows of pixel values, None =
    transparent). Returns the names it defined. A derive source may be any
    sprite read so far (this file or an earlier one). Names starting with
    "_" are helpers that only derive lines use."""
    if grids is None:
        grids = {}
    lines = path.read_text().split("\n")
    defined: list[str] = []
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
            name = words[1]
            try:
                w, h = int(words[2]), int(words[3])
            except ValueError:
                raise AssetError(f"{path}:{i}: expected 'sprite NAME W H'") from None
            check_name(path, i, name)
            if name in grids:
                raise AssetError(f"{path}:{i}: sprite {name} defined twice"
                                 + (f" (first in {sources[name]})" if sources and name in sources else ""))
            if not 1 <= w <= MAX_WIDTH or not 1 <= h <= MAX_HEIGHT:
                raise AssetError(f"{path}:{i}: {name}: size {w}x{h} is outside "
                                 f"1..{MAX_WIDTH} x 1..{MAX_HEIGHT}")
            grid = []
            for r in range(h):
                if i >= len(lines):
                    raise AssetError(f"{path}:{i}: {name}: file ends inside rows")
                row = lines[i].rstrip("\r\n")
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
            defined.append(name)
        elif words[0] == "derive":
            # derive NAME = OP SOURCE     OP: copy fliph flipv rot90 rot180 rot270
            if len(words) != 5 or words[2] != "=":
                raise AssetError(f"{path}:{i}: expected 'derive NAME = OP SOURCE'")
            name, op, source = words[1], words[3], words[4]
            check_name(path, i, name)
            if name in grids:
                raise AssetError(f"{path}:{i}: sprite {name} defined twice")
            if source not in grids:
                raise AssetError(f"{path}:{i}: derive {name}: unknown source {source}")
            try:
                grids[name] = transform(grids[source], op)
            except AssetError as err:
                raise AssetError(f"{path}:{i}: derive {name}: {err}") from None
            defined.append(name)
        else:
            raise AssetError(f"{path}:{i}: unknown directive {words[0]!r}")
    if sources is not None:
        for name in defined:
            sources[name] = path.name
    return defined


NAME_RE = re.compile(r"^_?[A-Za-z][A-Za-z0-9_]*$")


def check_name(path: Path, line: int, name: str) -> None:
    # SPR_<UPPER> and spr_<name>_even must be valid ca65 symbols (build_all
    # rejects two names with the same upper-case form)
    if not NAME_RE.match(name):
        raise AssetError(f"{path}:{line}: bad sprite name {name!r} "
                         "(letters, digits and _ only, starting with a letter)")


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


def art_files(assets_dir: Path) -> list[Path]:
    """The art files, in name order; the font override is not one of them."""
    if not assets_dir.is_dir():
        return []
    return sorted(p for p in assets_dir.glob("*.txt") if p.name != FONT_OVERRIDE_NAME)


def load_art(assets_dir: Path):
    """Return (grids, sources: name -> file name) of every art file."""
    grids: dict[str, list[list[int | None]]] = {}
    sources: dict[str, str] = {}
    for path in art_files(assets_dir):
        parse_art(path, grids, sources)
    return grids, sources


def load_parts(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text())
    except OSError as err:
        raise AssetError(f"cannot read {path} ({err}); run tools/parts.py first") from None
    except ValueError as err:
        raise AssetError(f"{path}: not JSON ({err})") from None
    parts = data.get("parts") if isinstance(data, dict) else None
    if not isinstance(parts, list):
        raise AssetError(f"{path}: no 'parts' list")
    for p in parts:
        for key in ("name", "kind"):
            if key not in p:
                raise AssetError(f"{path}: a part lacks {key!r}")
        if "bitmap" in p:
            for key in ("box", "hoty", "frames"):
                if key not in p:
                    raise AssetError(f"{path}: {p['name']} lacks {key!r}")
    return parts


def part_sprite_base(template_name: str) -> str:
    """Sprite base name of a part template: <base>_<frame>."""
    return PART_SPRITE_NAMES.get(template_name, template_name.lower())


# ------------------------------------------------------------------------ font

def _bytes_after_label(lines: list[str], label: str, count: int, path: Path) -> list[int]:
    """The first `count` bytes of the HEX (Merlin) or .byte (ca65) lines that
    start at the line labelled `label`."""
    start = None
    for k, line in enumerate(lines):
        word = line.split(None, 1)[0] if line.strip() else ""
        if word in (label, label + ":"):
            start = k
            break
    if start is None:
        raise AssetError(f"{path}: no {label} table")
    out: list[int] = []
    for line in lines[start:]:
        text = line.split(";", 1)[0]
        if line.lstrip().startswith("*"):
            text = ""
        m = re.search(r"\bHEX\s+([0-9A-Fa-f, ]+)", text)
        if m:
            out.extend(bytes.fromhex(m.group(1).replace(",", "").replace(" ", "")))
        else:
            m = re.search(r"\.byte\s+(.*)$", text)
            if m:
                out.extend(int(v.strip().lstrip("$"), 16) for v in m.group(1).split(","))
            elif line is not lines[start]:
                if out:
                    break
        if len(out) >= count:
            break
    if len(out) < count:
        raise AssetError(f"{path}: {label} has {len(out)} bytes, expected {count}")
    return out[:count]


def extract_font(path: Path) -> tuple[list[list[int]], list[int]]:
    """(36 glyphs of 7 upstream bytes, bit 0 = leftmost; 37 CWIDTH bytes)."""
    lines = path.read_text(errors="replace").split("\n")
    font = _bytes_after_label(lines, "FONT", FONT_UPSTREAM_COUNT * FONT_ROWS, path)
    cwidth = _bytes_after_label(lines, "CWIDTH", FONT_GLYPHS, path)
    glyphs = [font[k * FONT_ROWS:(k + 1) * FONT_ROWS] for k in range(FONT_UPSTREAM_COUNT)]
    return glyphs, cwidth


def fallback_font() -> tuple[list[list[int]], list[int]]:
    glyphs = [list(bytes.fromhex(g)) for g in FONT_FALLBACK.split()]
    return glyphs, list(bytes.fromhex(CWIDTH_FALLBACK))


def find_cdraw(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit
    for p in CDRAW_CANDIDATES:
        if p.is_file():
            return p
    return None


def reverse7(value: int) -> int:
    """Upstream row (bit 0 = leftmost of 7 pixels) -> bit 7 = leftmost."""
    out = 0
    for k in range(7):
        if value & (1 << k):
            out |= 0x80 >> k
    return out


def upstream_font(cdraw: Path | None) -> tuple[list[list[int]], list[int], str]:
    """The port's font from the upstream: (37 glyphs of 7 bytes, bit 7 =
    leftmost; 37 advances in pixels; where it came from). Code 36 is the
    blank space glyph."""
    if cdraw is not None:
        glyphs, cwidth = extract_font(cdraw)
        origin = str(cdraw)
    else:
        glyphs, cwidth = fallback_font()
        origin = "built-in copy"
    font7 = [[reverse7(b) for b in g] for g in glyphs] + [[0] * FONT_ROWS]
    # CWIDTH is the advance minus one (PRCHAR adds it with the carry set)
    adv = [c + 1 for c in cwidth]
    return font7, adv, origin


def glyph_code(word: str) -> int:
    """'A'..'Z' -> 10..35, '0'..'9' -> 0..9, 'space' -> 36, or a number."""
    if word.lower() == "space":
        return FONT_SPACE
    if len(word) == 1 and word.isalpha():
        return 10 + ord(word.upper()) - ord("A")
    return int(word)


def parse_font_override(path: Path) -> dict[int, tuple[list[int], int | None]]:
    """glyph CODE NAME [ADVANCE] then 7 rows of 7 (or 8) '#'/'.' characters.
    Returns code -> (7 row bytes with bit 7 = leftmost, advance or None)."""
    lines = path.read_text().split("\n")
    glyphs: dict[int, tuple[list[int], int | None]] = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        words = line.split()
        if words[0] != "glyph" or len(words) not in (3, 4):
            raise AssetError(f"{path}:{i}: expected 'glyph CODE NAME [ADVANCE]'")
        try:
            code = glyph_code(words[1])
            adv = int(words[3]) if len(words) == 4 else None
        except ValueError:
            raise AssetError(f"{path}:{i}: bad glyph code or advance") from None
        if not 0 <= code < FONT_GLYPHS:
            raise AssetError(f"{path}:{i}: glyph code {code} outside 0..{FONT_GLYPHS - 1}")
        if code in glyphs:
            raise AssetError(f"{path}:{i}: glyph {code} defined twice")
        if adv is not None and not 1 <= adv <= 8:
            raise AssetError(f"{path}:{i}: glyph {code}: advance {adv} outside 1..8")
        rows = []
        for r in range(FONT_ROWS):
            if i >= len(lines):
                raise AssetError(f"{path}:{i}: glyph {code}: file ends inside rows")
            row = lines[i].rstrip("\r\n")
            i += 1
            if len(row) not in (7, 8) or set(row) - {"#", "."}:
                raise AssetError(f"{path}:{i}: glyph {code} row {r}: bad row {row!r}")
            if len(row) == 8 and row[7] == "#":
                # glyphs are 7 pixels wide: cdraw.s draws 8 pixels into a
                # 4-byte arena row, and at an odd x the 8th would spill
                raise AssetError(f"{path}:{i}: glyph {code} row {r}: column 8 must be '.' "
                                 "(glyphs are 7 pixels wide)")
            value = 0
            for c in row.ljust(8, "."):
                value = (value << 1) | (1 if c == "#" else 0)
            rows.append(value)
        glyphs[code] = (rows, adv)
    return glyphs


def build_font(cdraw: Path | None, override: Path | None):
    """(font7, adv, origin, overridden codes)."""
    font7, adv, origin = upstream_font(cdraw)
    overridden: list[int] = []
    if override is not None and override.is_file():
        for code, (rows, a) in parse_font_override(override).items():
            font7[code] = rows
            if a is not None:
                adv[code] = a
            overridden.append(code)
    return font7, adv, origin, sorted(overridden)


# -------------------------------------------------------------------- encoding

def encode_raw(grid: list[list[int | None]]) -> bytes:
    """Raw rows: ceil(w/2) bytes per row, high nibble = left pixel;
    transparent pixels become colour 0 (the picture is drawn whole)."""
    w = len(grid[0])
    out = bytearray()
    for row in grid:
        px = [p or 0 for p in row] + [0] * (w & 1)
        for k in range(0, len(px), 2):
            out.append((px[k] << 4) | px[k + 1])
    return bytes(out)


def encode_variant(grid: list[list[int | None]], shift: int) -> tuple[bytes, int]:
    """Encode one pre-shifted variant. Returns (bytes, hole_count).

    hole_count is the number of transparent pixels that lie inside a run
    (stored as nibble 0; the blitter leaves the background there).
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
    """Inverse of encode_variant: returns (grid of width_bytes*2, bytes used).
    Pixels outside every run are None; a nibble 0 inside a run is 0."""
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


def placeholder_grid(w: int, h: int) -> list[list[int | None]]:
    """A 2x2 checker of the placeholder colours: visibly not art."""
    a, b = PLACEHOLDER_COLORS
    return [[a if ((x // 2) + (y // 2)) % 2 == 0 else b for x in range(w)]
            for y in range(h)]


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
    blobs in region order. A raw sprite has no RODATA fallback (see
    RAW_SPRITES): AssetError when it fits no raw region."""
    blobs = [bytearray() for _ in regions]
    for e in encoded:
        e["bank"] = BANK_RODATA
        e["even_addr"] = e["odd_addr"] = None
        if e["name"] in MAIN_ONLY:
            continue
        need = len(e["even"]) + len(e["odd"])
        for k, (_name, bank, base, size) in enumerate(regions):
            if (bank == BANK_RW1) != bool(e.get("raw")):
                continue
            if len(blobs[k]) + need <= size:
                e["bank"] = bank
                e["even_addr"] = base + len(blobs[k])
                blobs[k] += e["even"]
                if e.get("even_only"):
                    e["odd_addr"] = e["even_addr"]
                else:
                    e["odd_addr"] = base + len(blobs[k])
                    blobs[k] += e["odd"]
                break
        else:
            if e.get("raw"):
                raise AssetError(f"{e['name']}: {need} raw bytes fit in no raw-row region "
                                 "(bank 8 full or absent; a raw picture cannot live in RODATA)")
    return blobs


def spr_file_bytes(blobs, regions=REGIONS) -> bytes:
    """PCS.SPR image: header, region table (non-empty regions), blobs."""
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
        raise AssetError(f"not a {SPR_FILE_NAME} file")
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
        raise AssetError(f"{SPR_FILE_NAME} length does not match its table")
    return out


def region_name(bank: int, regions=REGIONS) -> str:
    for name, code, _base, _size in regions:
        if code == bank:
            return name
    return "RODATA"


# ---------------------------------------------------------------- sprite list

def sprite_list(parts: list[dict]) -> list[dict]:
    """The fixed ids: part frames in kit order, the drop-target singles, the
    UI sprites. Each entry: name, kind (template name or None), frame, w, h
    (the placeholder size), hoty, group."""
    entries: list[dict] = []
    seen: set[str] = set()

    def add(**e):
        if e["name"] in seen:
            raise AssetError(f"sprite id list: {e['name']} listed twice")
        seen.add(e["name"])
        entries.append(e)

    for p in parts:
        if "bitmap" not in p:
            continue
        base = part_sprite_base(p["name"])
        w, h = p["box"]
        for f in range(int(p["frames"])):
            add(name=f"{base}_{f}", kind=p["name"], frame=f, w=int(w), h=int(h),
                hoty=int(p["hoty"]), group="part")
    for name, w, h, _note in AUX_SPRITES:
        add(name=name, kind=None, frame=0, w=w, h=h, hoty=0, group="aux")
    for name, _up, _use in UI_SPRITES:
        w, h = PLACEHOLDER_UI_SIZE
        add(name=name, kind=None, frame=0, w=w, h=h, hoty=0, group="ui")
    return entries


def build_all(assets_dir: Path, parts_path: Path = DEFAULT_PARTS,
              cdraw: Path | None = None, font_override: Path | None = None,
              regions=REGIONS) -> dict:
    """Read everything and encode. Returns a dict:
    encoded (per id: name, kind, frame, w, h, hoty, grid, even, odd, holes,
    placeholder, source, bank, even_addr, odd_addr), parts, kinds (per part
    kind: name, kind, first, frames, w, h, hoty), font7, font_adv,
    font_origin, font_overridden, blobs, missing, extra, resized, files."""
    parts = load_parts(parts_path)
    grids, sources = load_art(assets_dir)
    if cdraw is None:
        cdraw = find_cdraw()
    if font_override is None:
        font_override = assets_dir / FONT_OVERRIDE_NAME
    font7, adv, origin, overridden = build_font(cdraw, font_override)

    entries = sprite_list(parts)
    listed = {e["name"] for e in entries}
    extra = sorted(n for n in grids if n not in listed and not n.startswith("_"))
    for name in extra:
        entries.append(dict(name=name, kind=None, frame=0, w=len(grids[name][0]),
                            h=len(grids[name]), hoty=0, group="extra"))
    upper: dict[str, str] = {}
    for e in entries:
        other = upper.setdefault(e["name"].upper(), e["name"])
        if other != e["name"]:
            raise AssetError(f"sprites {other} and {e['name']} would both be "
                             f"SPR_{e['name'].upper()}")

    encoded = []
    missing: list[str] = []
    resized: list[str] = []
    for e in entries:
        name = e["name"]
        if name in grids:
            grid = grids[name]
            w, h = len(grid[0]), len(grid)
            if e["group"] == "part" and (w, h) != (e["w"], e["h"]):
                resized.append(f"{name} {w}x{h} (parts.json box {e['w']}x{e['h']})")
            placeholder = False
            source = sources[name]
        else:
            w, h = e["w"], e["h"]
            grid = placeholder_grid(w, h)
            placeholder = True
            source = None
            missing.append(name)
        raw = name in RAW_SPRITES
        if raw:
            if w > RAW_MAX_W or h > RAW_MAX_H:
                raise AssetError(f"{name}: {w}x{h} does not fit the logo band "
                                 f"({RAW_MAX_W}x{RAW_MAX_H})")
            even, holes = encode_raw(grid), 0
        else:
            even, holes = encode_variant(grid, 0)
        even_only = raw or name in EVEN_ONLY
        odd = b"" if even_only else encode_variant(grid, 1)[0]
        encoded.append(dict(name=name, kind=e["kind"], frame=e["frame"], w=w, h=h,
                            hoty=e["hoty"], group=e["group"], grid=grid, even=even,
                            odd=odd, even_only=even_only, raw=raw, holes=holes,
                            placeholder=placeholder, source=source))

    # every frame of a kind has one size (the L-record has one height/width)
    kinds = []
    for p in parts:
        k = dict(name=p["name"], kind=int(p["kind"]), first=0, frames=0, w=0, h=0, hoty=0)
        if "bitmap" in p:
            frames = [e for e in encoded if e["kind"] == p["name"]]
            sizes = {(e["w"], e["h"]) for e in frames}
            if len(sizes) != 1:
                raise AssetError(f"{p['name']}: its frames differ in size: "
                                 + ", ".join(f"{e['name']} {e['w']}x{e['h']}" for e in frames))
            first = encoded.index(frames[0])
            for f, e in enumerate(frames):
                assert encoded[first + f] is e and e["frame"] == f
            k.update(first=first, frames=len(frames), w=frames[0]["w"], h=frames[0]["h"],
                     hoty=frames[0]["hoty"])
        kinds.append(k)

    blobs = place_sprites(encoded, regions)
    return dict(encoded=encoded, parts=parts, kinds=kinds, font7=font7, font_adv=adv,
                font_origin=origin, font_overridden=overridden, blobs=blobs,
                missing=missing, extra=extra, resized=resized,
                files=[p.name for p in art_files(assets_dir)], regions=regions)


# --------------------------------------------------------------------- writing

def byte_lines(data: bytes, per_line: int = 16) -> list[str]:
    lines = []
    for k in range(0, len(data), per_line):
        chunk = data[k:k + per_line]
        lines.append("    .byte " + ",".join(f"${b:02X}" for b in chunk))
    return lines


def label_of(name: str, variant: str) -> str:
    """The label of a variant; an EVEN_ONLY or RAW sprite has only the even one."""
    if name in EVEN_ONLY or name in RAW_SPRITES:
        variant = "even"
    return f"spr_{name}_{variant}"


def totals_of(result: dict) -> dict[str, int]:
    encoded = result["encoded"]
    count = len(encoded)
    even_total = sum(len(e["even"]) for e in encoded)
    odd_total = sum(len(e["odd"]) for e in encoded)
    rodata_sprites = sum(len(e["even"]) + len(e["odd"]) for e in encoded
                         if e["bank"] == BANK_RODATA)
    tables = count * 8              # spr_dir 4 + w, h, hoty, bank
    font_total = FONT_GLYPHS * FONT_ROWS + FONT_GLYPHS
    pal = len(palette_bytes())
    return dict(count=count, even=even_total, odd=odd_total, sprites=even_total + odd_total,
                rodata_sprites=rodata_sprites, tables=tables, font=font_total, palette=pal,
                lc=sum(len(b) for b in result["blobs"]),
                rodata=rodata_sprites + tables + font_total + pal)


def write_assets_s(path: Path, result: dict) -> dict[str, int]:
    encoded = result["encoded"]
    regions = result["regions"]
    blobs = result["blobs"]
    font7, adv = result["font7"], result["font_adv"]
    pal = palette_bytes()
    t = totals_of(result)
    count = t["count"]

    out = []
    out.append("; Pinball Construction Set for the Appletini -- sprite directory, font and")
    out.append("; palette tables. Generated by tools/gen_assets.py from assets/*.txt,")
    out.append("; build/parts.json and the upstream font; do not edit, edit the art.")
    out.append(";")
    out.append("; Interface (segment RODATA only: no code, no zero page, no bus traffic,")
    out.append("; these tables are only ever read):")
    out.append(";   spr_dir    SPR_COUNT entries of 4 bytes: even variant address, odd")
    out.append(";              variant address (in the auxiliary language card or here)")
    out.append(";   spr_w      pixel width per id        spr_h     height (rows) per id")
    out.append(";   spr_hoty   rows above the L-record y  spr_bank  0 main, 4 aux LC bank 2,")
    out.append(";              (flippers reach up)                  6 aux LC bank 1,")
    out.append(";                                                   8 raw rows, RamWorks 1")
    out.append(";   palette0   16 entries, little-endian $0RGB (docs/DESIGN.md section 3)")
    out.append(f";   font7      {FONT_GLYPHS} glyphs x {FONT_ROWS} rows, bit 7 = leftmost pixel; codes 0-9 digits,")
    out.append(f";              10-35 A-Z, {FONT_SPACE} space   font_adv  advance in pixels per glyph")
    out.append(";   SPR_COUNT  number of ids (assets.inc names every id)")
    out.append(";")
    out.append("; Variant format: height, width_bytes, then per row one or more runs:")
    out.append("; run_off, run_len, run_len bytes (high nibble = left pixel); run_off bit 7")
    out.append(f"; (${RUN_MORE:02X}) = another run of this row follows. Empty row = "
               f"{', '.join(f'${b:02X}' for b in EMPTY_ROW_BYTES)}.")
    out.append("; Nibble 0 is transparent (the blitter's mask table keeps the background).")
    if any(e["even_only"] for e in encoded):
        out.append("; Even-only sprites (drawn at an even x only, both directory entries are")
        out.append("; the even variant): " + ", ".join(e["name"] for e in encoded if e["even_only"]))
    out.append(";")
    out.append(f"; Font: {result['font_origin']}"
               + (f"; overridden glyphs: {', '.join(glyph_label(c) for c in result['font_overridden'])}"
                  if result["font_overridden"] else ""))
    out.append(f"; Art files: {', '.join(result['files']) or 'none'}")
    if result["missing"]:
        out.append(f"; Placeholders (art not drawn yet): {', '.join(result['missing'])}")
    if result["extra"]:
        out.append(f"; Extra sprites (ids after the fixed list): {', '.join(result['extra'])}")
    if result["resized"]:
        out.append("; Part frames drawn at another size than the parts.json box:")
        for note in result["resized"]:
            out.append(f";   {note}")
    out.append(";")
    out.append("; Byte totals:")
    out.append(f";   even variants : {t['even']:6d}")
    out.append(f";   odd variants  : {t['odd']:6d}")
    out.append(f";   in {SPR_FILE_NAME:<11s}: {t['lc']:6d}  (auxiliary card and RamWorks)")
    out.append(f";   in RODATA     : {t['rodata_sprites']:6d}  (sprites)")
    out.append(f";   id tables     : {t['tables']:6d}  (8 bytes x {count})")
    out.append(f";   font          : {t['font']:6d}")
    out.append(f";   palette       : {t['palette']:6d}")
    out.append(f";   RODATA total  : {t['rodata']:6d}")
    out.append(";")
    out.append("; Regions (bank code, $first-$last, used/size):")
    for (name, bank, base, size), blob in zip(regions, blobs):
        out.append(f";   {name:<9s} bank {bank}  ${base:04X}-${base + size - 1:04X}"
                   f"  {len(blob):5d}/{size}")
    out.append(";")
    out.append(";   id  name              w   h hoty  even  odd  where")
    for i, e in enumerate(encoded):
        where = region_name(e["bank"], regions)
        if e["even_addr"] is not None:
            where += f" ${e['even_addr']:04X}"
        if e["placeholder"]:
            where += "  PLACEHOLDER"
        odd = "   -" if e["even_only"] else f"{len(e['odd']):4d}"
        out.append(f";  {i:3d}  {e['name']:<16s} {e['w']:3d} {e['h']:3d} {e['hoty']:3d}   "
                   f"{len(e['even']):4d} {odd}  {where}")
    out.append("")
    out.append("    .export spr_dir, spr_w, spr_h, spr_hoty, spr_bank")
    out.append("    .export palette0, font7, font_adv, SPR_COUNT")
    out.append(f"SPR_COUNT = {count}")
    out.append("")
    out.append(f"; language-card sprites: addresses inside {SPR_FILE_NAME}'s regions")
    for e in encoded:
        if e["even_addr"] is not None:
            out.append(f"{label_of(e['name'], 'even')} = ${e['even_addr']:04X}    "
                       f"; {region_name(e['bank'], regions)}")
            if not e["even_only"]:
                out.append(f"{label_of(e['name'], 'odd')} = ${e['odd_addr']:04X}")
    out.append("")
    out.append('    .segment "RODATA"')
    out.append("")
    for e in encoded:
        if e["even_addr"] is not None:
            continue
        for variant in (("even",) if e["even_only"] else ("even", "odd")):
            data = e[variant]
            per_row = (e["w"] + 1) // 2 if e.get("raw") else data[1]
            out.append(f"{label_of(e['name'], variant)}:    ; {e['w']}x{e['h']}, {variant}, "
                       f"{per_row} bytes/row, {len(data)} bytes")
            out.extend(byte_lines(data))
        out.append("")
    out.append("; directory: even variant address, odd variant address per id")
    out.append("spr_dir:")
    for i, e in enumerate(encoded):
        out.append(f"    .word {label_of(e['name'], 'even')}, {label_of(e['name'], 'odd')}"
                   f"    ; {i:3d} {e['name']}")
    out.append("spr_w:")
    out.extend(byte_lines(bytes(e["w"] for e in encoded)))
    out.append("spr_h:")
    out.extend(byte_lines(bytes(e["h"] for e in encoded)))
    out.append("; rows of the sprite box above the L-record y (raised flipper frames)")
    out.append("spr_hoty:")
    out.extend(byte_lines(bytes(e["hoty"] for e in encoded)))
    out.append("; bank code per id: 0 main memory; bit 2 auxiliary language card (ALTZP),")
    out.append("; bit 1 its bank 1 of $D000-$DFFF instead of bank 2; bit 3 raw rows in")
    out.append("; RamWorks bank 1 (not blittable: fetch the rows)")
    out.append("spr_bank:")
    out.extend(byte_lines(bytes(e["bank"] for e in encoded)))
    out.append("")
    out.append("; palette 0: 16 entries, little-endian $0RGB (byte0 = G<<4|B, byte1 = R)")
    out.append("palette0:")
    for idx, name, r, g, b in PALETTE:
        out.append(f"    .byte ${(g << 4) | b:02X},${r:02X}    ; {idx:2d} {name} "
                   f"${r:X}{g:X}{b:X}")
    out.append("")
    out.append(f"; {FONT_GLYPHS} glyphs x {FONT_ROWS} rows, bit 7 = leftmost pixel "
               f"(0-9, A-Z, space)")
    out.append("font7:")
    for code, glyph in enumerate(font7):
        out.append("    .byte " + ",".join(f"${b:02X}" for b in glyph)
                   + f"    ; {code:2d} {glyph_label(code)}")
    out.append("; advance in pixels per glyph (the upstream CWIDTH + 1)")
    out.append("font_adv:")
    out.extend(byte_lines(bytes(adv)))
    out.append("")
    path.write_text("\n".join(out))
    return t


def write_assets_inc(path: Path, result: dict) -> None:
    encoded = result["encoded"]
    kinds = result["kinds"]
    out = []
    out.append("; Pinball Construction Set for the Appletini -- sprite ids and part frame")
    out.append("; tables. Generated by tools/gen_assets.py; do not edit.")
    out.append(";")
    out.append("; SPR_<NAME> is the id of sprite <name> (assets/*.txt); the sprite tables of")
    out.append("; assets.s (spr_dir, spr_w, spr_h, spr_hoty, spr_bank) are indexed by it and")
    out.append("; an L-record's sprite pointer is spr_dir + 4*id. A part kind's frames have")
    out.append("; consecutive ids: SPR_<KIND>_FIRST is frame 0, SPR_<KIND>_FRAMES the count,")
    out.append("; SPR_<KIND>_W/_H the sprite box (pixels, rows) and SPR_<KIND>_HOTY the rows")
    out.append("; of the box above the L-record y. Polygon-only kinds have zeros.")
    out.append("")
    out.append(".ifndef ASSETS_INC")
    out.append("ASSETS_INC = 1")
    out.append("")
    out.append(f"SPR_COUNT = {len(encoded)}")
    out.append(f"KIND_COUNT = {len(kinds)}")
    out.append("")
    out.append("; bank codes of spr_bank (defined here unless the includer has its own)")
    out.append(".ifndef SPR_BANK_AUX")
    out.append(f"SPR_BANK_RODATA = {BANK_RODATA}")
    out.append(f"SPR_BANK_1 = {BANK_1}")
    out.append(f"SPR_BANK_AUX = {BANK_AUX}")
    out.append(f"SPR_BANK_RW1 = {BANK_RW1}")
    out.append(".endif")
    out.append("")
    out.append("; part kinds in kit order (build/parts.json)")
    for k in kinds:
        n = k["name"]
        out.append(f"SPR_{n}_FIRST = {k['first']}    ; kind {k['kind']}"
                   + ("" if k["frames"] else " (polygon only)"))
        out.append(f"SPR_{n}_FRAMES = {k['frames']}")
        out.append(f"SPR_{n}_W = {k['w']}")
        out.append(f"SPR_{n}_H = {k['h']}")
        out.append(f"SPR_{n}_HOTY = {k['hoty']}")
    out.append("")
    out.append("; sprite ids")
    group = None
    for i, e in enumerate(encoded):
        if e["group"] != group:
            group = e["group"]
            out.append(f"; {dict(part='part frames', aux='drop-target singles', ui='UI sprites', extra='extra sprites in the art')[group]}")
        note = "    ; placeholder" if e["placeholder"] else ""
        out.append(f"SPR_{e['name'].upper()} = {i}{note}")
    out.append("")
    out.append("; font7 / font_adv")
    out.append(f"FONT_GLYPHS = {FONT_GLYPHS}")
    out.append(f"FONT_ROWS = {FONT_ROWS}")
    out.append("FONT_DIGIT0 = 0")
    out.append("FONT_A = 10")
    out.append(f"FONT_SPACE = {FONT_SPACE}")
    out.append("")
    out.append(".endif")
    out.append("")
    path.write_text("\n".join(out))


def write_preview(path: Path, result: dict) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    encoded = result["encoded"]
    font7 = result["font7"]
    scale = 4
    pad = 6
    label_h = 11
    max_w = 1200
    cells = []
    x = y = row_h = 0
    for e in encoded:
        cw = max(e["w"] * scale, 15 * len(e["name"]) // 2 + 8) + pad
        ch = e["h"] * scale + label_h + pad
        if x + cw > max_w and x > 0:
            x, y, row_h = 0, y + row_h, 0
        cells.append((x, y, e))
        x += cw
        row_h = max(row_h, ch)
    sprites_h = y + row_h
    glyph_cell = 9 * scale
    per_row = max_w // glyph_cell
    font_rows = (FONT_GLYPHS + per_row - 1) // per_row
    font_h = label_h + font_rows * (FONT_ROWS + 2) * scale
    img = Image.new("RGB", (max_w, sprites_h + font_h + pad), (24, 24, 32))
    draw = ImageDraw.Draw(img)
    rgb = {idx: (r * 17, g * 17, b * 17) for idx, _n, r, g, b in PALETTE}
    for cx, cy, e in cells:
        # decode the encoded bytes so the preview shows what the blitter draws
        if e.get("raw"):
            grid = [[p or 0 for p in row] for row in e["grid"]]
        else:
            grid, _ = decode_variant(e["even"])
        ox, oy = cx + 2, cy + label_h
        draw.rectangle((ox - 1, oy - 1, ox + e["w"] * scale, oy + e["h"] * scale),
                       outline=(60, 60, 80), fill=(0, 0, 0))
        for yy, row in enumerate(grid):
            for xx in range(e["w"]):
                p = row[xx]
                if not p:
                    continue
                draw.rectangle((ox + xx * scale, oy + yy * scale,
                                ox + xx * scale + scale - 1, oy + yy * scale + scale - 1),
                               fill=rgb[p])
        colour = (255, 120, 255) if e["placeholder"] else (200, 200, 200)
        draw.text((cx + 2, cy), f"{encoded.index(e)} {e['name']}", fill=colour)
    fy = sprites_h + label_h
    draw.text((2, sprites_h), "font7 (0-9, A-Z, space) with font_adv", fill=(200, 200, 200))
    for code, glyph in enumerate(font7):
        gx = (code % per_row) * glyph_cell + 2
        gy = fy + (code // per_row) * (FONT_ROWS + 2) * scale
        adv = result["font_adv"][code]
        draw.rectangle((gx, gy + FONT_ROWS * scale, gx + adv * scale - 1,
                        gy + FONT_ROWS * scale + 1), fill=(90, 90, 120))
        for yy, bits in enumerate(glyph):
            for xx in range(8):
                if bits & (0x80 >> xx):
                    draw.rectangle((gx + xx * scale, gy + yy * scale,
                                    gx + xx * scale + scale - 1, gy + yy * scale + scale - 1),
                                   fill=(255, 255, 255))
    img.save(path)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS,
                        help="directory of the art files (default assets/)")
    parser.add_argument("--parts", type=Path, default=DEFAULT_PARTS,
                        help="parts.json from tools/parts.py (default build/parts.json)")
    parser.add_argument("--cdraw", type=Path, default=None,
                        help="CDRAW source with the FONT/CWIDTH tables (default: "
                             "build/baseline/CDRAW.s or the upstream clone)")
    parser.add_argument("--font", type=Path, default=None,
                        help=f"glyph override file (default assets/{FONT_OVERRIDE_NAME})")
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--strict", action="store_true",
                        help="fail when a sprite is missing instead of using a placeholder")
    parser.add_argument("--quiet", action="store_true",
                        help="print only the diagnostics (missing, extra, resized sprites)")
    args = parser.parse_args(argv)

    try:
        result = build_all(args.assets, args.parts, find_cdraw(args.cdraw), args.font)
        if args.strict and result["missing"]:
            raise AssetError("missing sprites (--strict): " + ", ".join(result["missing"]))
    except (AssetError, OSError, ValueError) as err:
        print(f"gen_assets: {err}", file=sys.stderr)
        return 1

    args.build.mkdir(parents=True, exist_ok=True)
    totals = write_assets_s(args.build / "assets.s", result)
    write_assets_inc(args.build / "assets.inc", result)
    spr = spr_file_bytes(result["blobs"], result["regions"])
    (args.build / SPR_FILE_NAME).write_bytes(spr)
    # the preview is a convenience: a Pillow problem must not fail the build
    # after the three real outputs are written (make would then keep them
    # as up to date although the tool reported an error)
    try:
        preview = write_preview(args.build / "assets_preview.png", result)
    except Exception as err:  # noqa: BLE001
        print(f"gen_assets: preview not written ({type(err).__name__}: {err})",
              file=sys.stderr)
        preview = False

    # the diagnostics always show: the art is being drawn while the port is built
    if result["missing"]:
        print(f"gen_assets: {len(result['missing'])} sprites not drawn yet, placeholders "
              f"used: {', '.join(result['missing'])}", file=sys.stderr)
    if result["extra"]:
        print(f"gen_assets: extra sprites in the art (ids appended): "
              f"{', '.join(result['extra'])}", file=sys.stderr)
    if result["resized"]:
        print("gen_assets: part frames drawn at another size than the parts.json box: "
              + "; ".join(result["resized"]), file=sys.stderr)
    if result["font_origin"] == "built-in copy":
        print("gen_assets: no CDRAW source found, the built-in copy of the font is used",
              file=sys.stderr)
    if not args.quiet:
        print(f"{totals['count']} sprites: {totals['sprites']} bytes (even {totals['even']}, "
              f"odd {totals['odd']}); {SPR_FILE_NAME}: {len(spr)} bytes in "
              f"{sum(1 for b in result['blobs'] if b)} regions; RODATA: {totals['rodata']} "
              f"bytes (sprites {totals['rodata_sprites']}, tables {totals['tables']}, "
              f"font {totals['font']}, palette {totals['palette']})")
        for (name, _bank, _base, size), blob in zip(result["regions"], result["blobs"]):
            print(f"  {name:<9s} {len(blob):5d}/{size} bytes")
        in_rodata = [e["name"] for e in result["encoded"] if e["bank"] == BANK_RODATA]
        if in_rodata:
            print(f"  RODATA sprites: {', '.join(in_rodata)}")
        print(f"font: {result['font_origin']}")
        print("preview:", "written" if preview else "skipped (Pillow not installed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
