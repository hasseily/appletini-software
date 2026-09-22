#!/usr/bin/env python3
"""Convert the graphics of a Bosconian arcade ROM set into this project's sprite art.

The repository holds no Namco data. This tool reads the MAME ROM set that
you own (bosco.zip or an unpacked directory; the bosco, bosco3, bosco1,
bosco1o, boscoo and boscomd sets all share the same graphics ROMs and colour
PROMs), decodes the 8x8 tiles, 16x16 sprites, the 4x4 bullet dots and the
colour PROMs exactly as MAME's galaga.cpp and bosco_v.cpp do, and writes
into --out (build/rom):

  sheet.png      every tile, sprite and dot with its index, drawn in the
                 colour code given by --sheet-code (default: a grey ramp)
  palettes.png   the 64 four-colour codes of the sprites and of the tiles
  sprites.txt    the project's sprite text art: every SPR_ entry that
                 assets/rom_map.txt maps is taken from the ROM graphics, the
                 rest is copied from assets/sprites.txt (the drawn art)
  font8.txt      the project's font with the arcade digits and letters put
                 in where the map's "font:" line says
  colors.txt     the arcade colours used and the palette entry each became

assets/rom_map.txt says which tile, sprite, tile grid or dot (and which
colour code) makes each SPR_ entry; see its header for the syntax.
Entries marked "?" are not mapped: sheet.png and palettes.png are what you
look at to fill them in.

Usage:
  python3 tools/bosco_rom.py ROMSET [--map assets/rom_map.txt] [--out build/rom]
  make ROMS=/path/to/bosco.zip        # runs this tool, then builds with its output

ROM parts are found by CRC32 first (the values in MAME's driver), then by
their MAME file names. Only the Python standard library is needed; Pillow is
used for the two PNG sheets when it is installed.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_assets  # noqa: E402  (PALETTE, PIXEL_CHARS, SPRITES, parse_sprites, transform)

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MAP = PROJECT_DIR / "assets" / "rom_map.txt"
DEFAULT_ART = PROJECT_DIR / "assets" / "sprites.txt"
DEFAULT_FONT = PROJECT_DIR / "assets" / "font8.txt"
DEFAULT_OUT = PROJECT_DIR / "build" / "rom"

# The ROM parts this tool needs, as MAME's galaga.cpp lists them.
ROM_PARTS = {
    "tiles": dict(size=0x1000, crc=0xA956D3C5, names=("bos1_14.5d", "5300.5d")),
    "sprites": dict(size=0x1000, crc=0xE869219C,
                    names=("bos1_13.5e", "5300.5e", "5300.5f")),
    "dots": dict(size=0x0100, crc=0x9B69B543, names=("bos1-4.2r", "prom.2r")),
    "palette": dict(size=0x0020, crc=0xD2B96FB0, names=("bos1-6.6b", "prom.6b")),
    "lookup": dict(size=0x0100, crc=0x4E15D59C, names=("bos1-5.4m", "prom.4m")),
}

# MAME gfx layouts (bit offsets, MSB of byte 0 = bit 0). As in MAME's
# gfx_element::decode, the first plane is the most significant pen bit.
# charlayout_2bpp, spritelayout_bosco and dotlayout in galaga.cpp.
TILE_LAYOUT = dict(
    w=8, h=8, planes=(0, 4),
    xoff=(64, 65, 66, 67, 0, 1, 2, 3),
    yoff=tuple(y * 8 for y in range(8)),
    inc=16 * 8, count=256,
)
SPRITE_LAYOUT = dict(
    w=16, h=16, planes=(0, 4),
    xoff=(64, 65, 66, 67, 128, 129, 130, 131, 192, 193, 194, 195, 0, 1, 2, 3),
    yoff=tuple(y * 8 for y in range(8)) + tuple(256 + y * 8 for y in range(8)),
    inc=64 * 8, count=64,
)
DOT_LAYOUT = dict(
    w=4, h=4, planes=(5, 6, 7),     # "2 bits color + 1 bit transparency"
    xoff=(0, 8, 16, 24),
    yoff=(0, 32, 64, 96),
    inc=16 * 8, count=8,
)
SPRITE_TRANSPARENT = 0x0F   # bosco_v.cpp: transpen_mask(gfx(1), color, 0x0f)
TILE_TRANSPARENT = 0x1F     # bosco_v.cpp: configure_groups(gfx(0), 0x1f)
DOT_TRANSPARENT_BIT = 4     # draw_bullets: transmask 0xf0, pens 4..7 see-through
DOT_FIRST_COLOR = 31        # bullets lookup table: pen p -> palette 31 - p

CHAR_FOR_INDEX = {v: k for k, v in gen_assets.PIXEL_CHARS.items() if v is not None}
TRANSPARENT_CHAR = "."
BLANK_CELL = ".."

# "font:" line: which characters a tile run stands for.
FONT_RUNS = {"digits": "0123456789", "letters": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
             "space": " ", "minus": "-"}


class RomError(Exception):
    pass


# ------------------------------------------------------------------ ROM set

def load_romset(path: Path) -> tuple[dict[str, bytes], list[str]]:
    """Return {part: bytes} for ROM_PARTS and a list of notes (warnings)."""
    path = Path(path)
    entries: dict[str, tuple[int, int, bytes | None]] = {}  # name -> (crc, size, data)
    if path.is_dir():
        for f in sorted(path.iterdir()):
            if f.is_file():
                data = f.read_bytes()
                entries[f.name.lower()] = (zlib.crc32(data) & 0xFFFFFFFF, len(data), data)
        reader = None
    elif zipfile.is_zipfile(path):
        reader = zipfile.ZipFile(path)
        for info in reader.infolist():
            if not info.is_dir():
                entries[Path(info.filename).name.lower()] = (info.CRC, info.file_size, None)
    else:
        raise RomError(f"{path} is neither a zip file nor a directory")

    def data_of(name: str) -> bytes:
        crc, size, data = entries[name]
        if data is None:
            assert reader is not None
            data = reader.read(next(i.filename for i in reader.infolist()
                                    if Path(i.filename).name.lower() == name))
        return data

    parts: dict[str, bytes] = {}
    notes: list[str] = []
    for part, want in ROM_PARTS.items():
        by_crc = [n for n, (crc, size, _d) in entries.items()
                  if crc == want["crc"] and size == want["size"]]
        if by_crc:
            parts[part] = data_of(by_crc[0])
            continue
        by_name = [n for n in want["names"] if n in entries]
        if by_name:
            name = by_name[0]
            if entries[name][1] != want["size"]:
                raise RomError(f"{name}: {entries[name][1]} bytes, expected {want['size']}")
            parts[part] = data_of(name)
            notes.append(f"{part}: {name} found by name, its CRC "
                         f"{entries[name][0]:08x} is not MAME's {want['crc']:08x}")
            continue
        listing = ", ".join(sorted(entries)) or "(empty)"
        raise RomError(f"no {part} ROM (CRC {want['crc']:08x} or one of "
                       f"{', '.join(want['names'])}) in {path}; found: {listing}")
    return parts, notes


# ------------------------------------------------------------------ decoding

def readbit(data: bytes, bit: int) -> int:
    return (data[bit >> 3] >> (7 - (bit & 7))) & 1


def decode_gfx(data: bytes, layout: dict) -> list[list[list[int]]]:
    """Return count grids of h rows x w pens, MAME style."""
    grids = []
    nplanes = len(layout["planes"])
    for n in range(layout["count"]):
        base = n * layout["inc"]
        grid = []
        for y in range(layout["h"]):
            row = []
            for x in range(layout["w"]):
                pen = 0
                for i, plane in enumerate(layout["planes"]):
                    pen |= readbit(data, base + plane + layout["yoff"][y]
                                   + layout["xoff"][x]) << (nplanes - 1 - i)
                row.append(pen)
            grid.append(row)
        grids.append(grid)
    return grids


def decode_palette(prom: bytes) -> list[tuple[int, int, int]]:
    """The 32 core colours: 3 bits red, 3 bits green, 2 bits blue (bosco_v.cpp)."""
    weights = (0x21, 0x47, 0x97)
    colors = []
    for byte in prom[:32]:
        r = sum(w for i, w in enumerate(weights) if (byte >> i) & 1)
        g = sum(w for i, w in enumerate(weights) if (byte >> (3 + i)) & 1)
        b = 0x47 * ((byte >> 6) & 1) + 0x97 * ((byte >> 7) & 1)
        colors.append((r, g, b))
    return colors


def sprite_pen_color(lookup: bytes, code: int, pen: int) -> int:
    """Palette index (0..15) of a sprite pen; SPRITE_TRANSPARENT means see-through."""
    return lookup[(code & 0x3F) * 4 + (pen & 3)] & 0x0F


def tile_pen_color(lookup: bytes, code: int, pen: int) -> int:
    """Palette index (16..31) of a tile pen; TILE_TRANSPARENT means see-through."""
    return (lookup[(code & 0x3F) * 4 + (pen & 3)] & 0x0F) | 0x10


def dot_pen_color(pen: int) -> int | None:
    """Palette index (28..31) of a bullet pen, None where see-through."""
    if pen & DOT_TRANSPARENT_BIT:
        return None
    return DOT_FIRST_COLOR - (pen & 3)


def colorize(grid, lookup: bytes, code: int, is_tile: bool):
    """Pens -> palette indices, None where transparent."""
    fn = tile_pen_color if is_tile else sprite_pen_color
    transparent = TILE_TRANSPARENT if is_tile else SPRITE_TRANSPARENT
    out = []
    for row in grid:
        out.append([None if fn(lookup, code, p) == transparent else fn(lookup, code, p)
                    for p in row])
    return out


def tile_flips(attr: int) -> tuple[bool, bool]:
    """(flipx, flipy) of a tile attribute: TILE_FLIPYX(attr >> 6) ^ TILE_FLIPX."""
    return not (attr & 0x40), bool(attr & 0x80)


# ------------------------------------------------------------------ SHR palette

def shr_rgb(entry) -> tuple[int, int, int]:
    _idx, _name, r, g, b = entry
    return (r * 17, g * 17, b * 17)


def nearest_shr(rgb: tuple[int, int, int]) -> int:
    """Index of the closest palette 0 colour (weighted RGB distance)."""
    best, best_d = 0, None
    for entry in gen_assets.PALETTE:
        pr, pg, pb = shr_rgb(entry)
        d = 3 * (rgb[0] - pr) ** 2 + 4 * (rgb[1] - pg) ** 2 + 2 * (rgb[2] - pb) ** 2
        if best_d is None or d < best_d:
            best, best_d = entry[0], d
    return best


# ------------------------------------------------------------------ map file

class MapEntry:
    def __init__(self, name: str, line_no: int):
        self.name = name
        self.line_no = line_no
        self.kind = None        # "sprite", "sprites", "tile", "tiles", "tilemap", "dot"
        self.indices: list[int] = []
        self.cells: list[tuple[int, int] | None] = []   # tilemap: (code, attr) or None
        self.tw = self.th = 0   # tilemap size in tiles
        self.color = None
        self.ops: list[str] = []
        self.place = "fit"      # "fit", "center", ("at", x, y)
        self.crop = None        # (x, y, w, h)
        self.mapped = False

    def source_text(self) -> str:
        if self.kind == "tilemap":
            return f"tilemap {self.tw}x{self.th}"
        text = f"{self.kind} {' '.join(str(i) for i in self.indices)}"
        if self.color is not None:
            text += f" color {self.color}"
        return text


def logical_lines(path: Path) -> list[tuple[int, str]]:
    """Join indented continuation lines onto the line before them."""
    out: list[tuple[int, str]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.split("#", 1)[0].rstrip()
        if not text.strip():
            continue
        if text[0] in " \t" and out:
            out[-1] = (out[-1][0], out[-1][1] + " " + text.strip())
        else:
            out.append((line_no, text.strip()))
    return out


def parse_map(path: Path) -> tuple[dict[str, MapEntry], dict[str, int]]:
    """Parse rom_map.txt.

    Lines: NAME: source [options]; "?" leaves an entry unmapped; a line that
    starts with white space continues the previous one. "font: digits N
    letters N ..." maps characters of the font to tile runs. Returns
    (entries by sprite name, font map char -> tile index)."""
    entries: dict[str, MapEntry] = {}
    font_map: dict[str, int] = {}
    known = set(gen_assets.SPRITE_SIZES)
    for line_no, line in logical_lines(path):
        if ":" not in line:
            raise RomError(f"{path}:{line_no}: expected NAME: source")
        name, rest = (s.strip() for s in line.split(":", 1))
        tokens = rest.split()

        def num(tok: str) -> int:
            try:
                return int(tok, 0)
            except ValueError:
                raise RomError(f"{path}:{line_no}: bad number {tok!r}") from None

        if name == "font":
            if len(tokens) % 2:
                raise RomError(f"{path}:{line_no}: font needs RUN N pairs")
            for run, tok in zip(tokens[0::2], tokens[1::2]):
                if run not in FONT_RUNS:
                    raise RomError(f"{path}:{line_no}: font run must be one of "
                                   f"{', '.join(FONT_RUNS)}")
                first = num(tok)
                for k, ch in enumerate(FONT_RUNS[run]):
                    if not 0 <= first + k < 256:
                        raise RomError(f"{path}:{line_no}: font tiles run past 255")
                    font_map[ch] = first + k
            continue
        if name not in known:
            raise RomError(f"{path}:{line_no}: unknown sprite {name}")
        if name in entries:
            raise RomError(f"{path}:{line_no}: {name} mapped twice")
        entry = MapEntry(name, line_no)
        entries[name] = entry
        if not tokens or "?" in tokens:
            continue
        pos = 0

        def cell(tok: str) -> tuple[int, int] | None:
            if tok == BLANK_CELL:
                return None
            if ":" not in tok:
                raise RomError(f"{path}:{line_no}: tilemap cell {tok!r} is not CODE:ATTR")
            code, attr = tok.split(":", 1)
            try:
                code_v, attr_v = int(code, 16), int(attr, 16)
            except ValueError:
                raise RomError(f"{path}:{line_no}: tilemap cell {tok!r} is not hex") from None
            if not 0 <= code_v < 256 or not 0 <= attr_v < 256:
                raise RomError(f"{path}:{line_no}: tilemap cell {tok!r} out of range")
            return (code_v, attr_v)

        kind = tokens[pos]
        pos += 1
        try:
            if kind in ("sprite", "tile", "dot"):
                entry.kind = kind
                entry.indices = [num(tokens[pos])]
                pos += 1
            elif kind in ("tiles", "sprites"):
                entry.kind = kind
                while pos < len(tokens) and tokens[pos][0].isdigit():
                    entry.indices.append(num(tokens[pos]))
                    pos += 1
                if len(entry.indices) != 4:
                    raise RomError(f"{path}:{line_no}: {kind} needs 4 indices (2x2, row-major)")
            elif kind == "tilemap":
                entry.kind = kind
                entry.tw, entry.th = num(tokens[pos]), num(tokens[pos + 1])
                pos += 2
                if not 1 <= entry.tw <= 16 or not 1 <= entry.th <= 16:
                    raise RomError(f"{path}:{line_no}: tilemap size must be 1..16 tiles")
                n = entry.tw * entry.th
                entry.cells = [cell(t) for t in tokens[pos:pos + n]]
                if len(entry.cells) != n:
                    raise RomError(f"{path}:{line_no}: tilemap {entry.tw}x{entry.th} needs "
                                   f"{n} cells (CODE:ATTR or ..)")
                pos += n
                entry.place = "center"
            else:
                raise RomError(f"{path}:{line_no}: source must be sprite, sprites, tile, "
                               "tiles, tilemap or dot")
        except IndexError:
            raise RomError(f"{path}:{line_no}: {kind}: missing numbers") from None
        while pos < len(tokens):
            tok = tokens[pos]
            pos += 1
            try:
                if tok == "color":
                    entry.color = num(tokens[pos])
                    pos += 1
                elif tok in ("fliph", "flipv", "rot90", "rot180", "rot270"):
                    entry.ops.append(tok)
                elif tok in ("fit", "center"):
                    entry.place = tok
                elif tok == "at":
                    entry.place = ("at", num(tokens[pos]), num(tokens[pos + 1]))
                    pos += 2
                elif tok == "crop":
                    entry.crop = tuple(num(t) for t in tokens[pos:pos + 4])
                    if len(entry.crop) != 4:
                        raise RomError(f"{path}:{line_no}: crop needs x y w h")
                    pos += 4
                else:
                    raise RomError(f"{path}:{line_no}: unknown option {tok!r}")
            except IndexError:
                raise RomError(f"{path}:{line_no}: {tok}: missing numbers") from None
        if entry.kind in ("sprite", "sprites", "tile", "tiles"):
            if entry.color is None:
                raise RomError(f"{path}:{line_no}: {name} needs a color code")
            if not 0 <= entry.color < 64:
                raise RomError(f"{path}:{line_no}: color code must be 0..63")
        elif entry.color is not None:
            raise RomError(f"{path}:{line_no}: {entry.kind} takes no color code "
                           "(tilemap cells carry their own, dots have fixed colours)")
        entry.mapped = True
    return entries, font_map


# ------------------------------------------------------------------ building art

def bbox(grid):
    ys = [y for y, row in enumerate(grid) if any(p is not None for p in row)]
    xs = [x for row in grid for x, p in enumerate(row) if p is not None]
    if not ys:
        return None
    return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def sub_grid(grid, x, y, w, h):
    return [row[x:x + w] for row in grid[y:y + h]]


def place(grid, w: int, h: int, mode, name: str):
    """Put grid (any size) into a w x h box: fit (crop to content, center),
    center (no crop) or at x y (top-left offset). Pixels outside are dropped."""
    if mode == "fit":
        box = bbox(grid)
        if box is None:
            raise RomError(f"{name}: the ROM graphic is empty")
        grid = sub_grid(grid, *box)
    gh, gw = len(grid), len(grid[0])
    if isinstance(mode, tuple):
        ox, oy = mode[1], mode[2]
    else:
        ox, oy = (w - gw) // 2, (h - gh) // 2
    out = [[None] * w for _ in range(h)]
    lost = 0
    for y, row in enumerate(grid):
        for x, p in enumerate(row):
            if p is None:
                continue
            tx, ty = x + ox, y + oy
            if 0 <= tx < w and 0 <= ty < h:
                out[ty][tx] = p
            else:
                lost += 1
    return out, lost


def paste(dest, src, x0: int, y0: int) -> None:
    for y, row in enumerate(src):
        for x, p in enumerate(row):
            dest[y0 + y][x0 + x] = p


class Converter:
    def __init__(self, parts: dict[str, bytes]):
        self.tiles = decode_gfx(parts["tiles"], TILE_LAYOUT)
        self.sprites = decode_gfx(parts["sprites"], SPRITE_LAYOUT)
        self.dots = decode_gfx(parts["dots"], DOT_LAYOUT)
        self.palette = decode_palette(parts["palette"])
        self.lookup = parts["lookup"]
        self.shr_of_arcade: dict[int, int] = {}   # arcade palette index -> SHR index
        self.used: dict[int, set[str]] = {}       # arcade palette index -> sprite names

    def shr_index(self, arcade_index: int, name: str) -> int:
        if arcade_index not in self.shr_of_arcade:
            rgb = self.palette[arcade_index]
            self.shr_of_arcade[arcade_index] = 0 if rgb == (0, 0, 0) else nearest_shr(rgb)
        self.used.setdefault(arcade_index, set()).add(name)
        return self.shr_of_arcade[arcade_index]

    def tile(self, code: int, attr: int):
        """One coloured 8x8 tile as the hardware shows it for this attribute."""
        grid = colorize(self.tiles[code], self.lookup, attr & 0x3F, True)
        flipx, flipy = tile_flips(attr)
        if flipx:
            grid = gen_assets.transform(grid, "fliph")
        if flipy:
            grid = gen_assets.transform(grid, "flipv")
        return grid

    def dot(self, n: int):
        """One bullet dot as drawn on an unflipped screen (draw_bullets flips both ways)."""
        grid = [[dot_pen_color(p) for p in row] for row in self.dots[n]]
        return gen_assets.transform(grid, "rot180")

    def source_grid(self, entry: MapEntry):
        """Decoded, coloured (palette indices / None) graphic of a map entry."""
        if entry.kind in ("sprite", "sprites"):
            for idx in entry.indices:
                if not 0 <= idx < len(self.sprites):
                    raise RomError(f"{entry.name}: sprite index {idx} is not 0..63")
            grids = [colorize(self.sprites[i], self.lookup, entry.color, False)
                     for i in entry.indices]
            if entry.kind == "sprite":
                return grids[0]
            top = [a + b for a, b in zip(grids[0], grids[1])]
            bottom = [a + b for a, b in zip(grids[2], grids[3])]
            return top + bottom
        if entry.kind == "dot":
            idx = entry.indices[0]
            if not 0 <= idx < len(self.dots):
                raise RomError(f"{entry.name}: dot index {idx} is not 0..7")
            return self.dot(idx)
        if entry.kind == "tilemap":
            out = [[None] * (entry.tw * 8) for _ in range(entry.th * 8)]
            for k, cell in enumerate(entry.cells):
                if cell is None:
                    continue
                code, attr = cell
                paste(out, self.tile(code, attr), (k % entry.tw) * 8, (k // entry.tw) * 8)
            return out
        for idx in entry.indices:
            if not 0 <= idx < len(self.tiles):
                raise RomError(f"{entry.name}: tile index {idx} is not 0..255")
        tiles = [colorize(self.tiles[i], self.lookup, entry.color, True)
                 for i in entry.indices]
        if entry.kind == "tile":
            return tiles[0]
        top = [a + b for a, b in zip(tiles[0], tiles[1])]
        bottom = [a + b for a, b in zip(tiles[2], tiles[3])]
        return top + bottom

    def build(self, entry: MapEntry, w: int, h: int):
        grid = self.source_grid(entry)
        if entry.crop:
            cx, cy, cw, ch = entry.crop
            grid = sub_grid(grid, cx, cy, cw, ch)
            if not grid or not grid[0]:
                raise RomError(f"{entry.name}: crop {entry.crop} is empty")
        for op in entry.ops:
            grid = gen_assets.transform(grid, op)
        grid, lost = place(grid, w, h, entry.place, entry.name)
        shr = [[None if p is None else self.shr_index(p, entry.name) for p in row]
               for row in grid]
        return shr, lost

    def glyph(self, code: int) -> list[int]:
        """A tile as an 8-row 1-bit glyph (any pen but 0 is ink, bit 7 = left)."""
        if not 0 <= code < len(self.tiles):
            raise RomError(f"font: tile index {code} is not 0..255")
        rows = []
        for row in self.tiles[code]:
            value = 0
            for pen in row:
                value = (value << 1) | (1 if pen else 0)
            rows.append(value)
        return rows


def grid_lines(grid) -> list[str]:
    return ["".join(TRANSPARENT_CHAR if p is None else CHAR_FOR_INDEX[p] for p in row)
            for row in grid]


def write_font(conv: Converter, font_map: dict[str, int], art_font: Path,
               out_path: Path) -> int:
    """font8.txt: the drawn font with the mapped characters replaced by tiles."""
    glyphs = gen_assets.parse_font(art_font)
    replaced = 0
    lines = [
        "# Generated by tools/bosco_rom.py: the drawn font of assets/font8.txt with",
        "# the characters that rom_map.txt's font: line maps taken from the arcade",
        "# tiles. Do not edit.",
        "",
    ]
    for k, rows in enumerate(glyphs):
        code = gen_assets.FONT_FIRST + k
        ch = chr(code)
        if ch in font_map:
            rows = conv.glyph(font_map[ch])
            replaced += 1
            origin = f"tile 0x{font_map[ch]:02x}"
        else:
            origin = "drawn"
        lines.append(f"glyph {code} {'space' if ch == ' ' else ch}    # {origin}")
        for value in rows:
            lines.append("".join("#" if value & (0x80 >> x) else "." for x in range(8)))
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return replaced


def convert(parts: dict[str, bytes], map_path: Path, art_path: Path,
            out_dir: Path, sheet_code: int | None = None,
            font_path: Path = DEFAULT_FONT) -> dict:
    """Write sprites.txt, font8.txt, colors.txt and the sheets. Returns a summary dict."""
    entries, font_map = parse_map(map_path)
    art = gen_assets.parse_sprites(art_path)
    conv = Converter(parts)
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Generated by tools/bosco_rom.py from the arcade ROM set and",
        f"# {map_path.name}; unmapped entries are copied from {art_path.name}.",
        "# Do not edit: edit the map or the drawn art and run the tool again.",
        "",
    ]
    mapped, unmapped, lost_total = [], [], 0
    for name, w, h in gen_assets.SPRITES:
        entry = entries.get(name)
        if entry is not None and entry.mapped:
            grid, lost = conv.build(entry, w, h)
            lost_total += lost
            mapped.append(name)
            lines.append(f"# {name}: {entry.source_text()}"
                         + (f" ({lost} pixels outside the box)" if lost else ""))
        else:
            if name not in art:
                raise RomError(f"{art_path}: missing sprite {name}")
            grid = art[name]
            unmapped.append(name)
            lines.append(f"# {name}: drawn art")
        if len(grid) != h or len(grid[0]) != w:
            raise RomError(f"{name}: {len(grid[0])}x{len(grid)}, expected {w}x{h}")
        lines.append(f"sprite {name} {w} {h}")
        lines.extend(grid_lines(grid))
        lines.append("")
    (out_dir / "sprites.txt").write_text("\n".join(lines), encoding="utf-8")

    glyphs = write_font(conv, font_map, font_path, out_dir / "font8.txt")

    report = ["# arcade palette index: RGB -> SHR palette entry (used by)"]
    for idx in sorted(conv.used):
        r, g, b = conv.palette[idx]
        shr = conv.shr_of_arcade[idx]
        entry = gen_assets.PALETTE[shr]
        report.append(f"{idx:2d}: #{r:02x}{g:02x}{b:02x} -> {shr:2d} {entry[1]} "
                      f"({', '.join(sorted(conv.used[idx]))})")
    report.append("")
    report.append("# full arcade palette")
    for idx, (r, g, b) in enumerate(conv.palette):
        report.append(f"{idx:2d}: #{r:02x}{g:02x}{b:02x}")
    (out_dir / "colors.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    sheets = write_sheets(conv, out_dir, sheet_code)
    return dict(mapped=mapped, unmapped=unmapped, lost=lost_total, sheets=sheets,
                colors=len(conv.used), glyphs=glyphs)


# ------------------------------------------------------------------ sheets

def write_sheets(conv: Converter, out_dir: Path, sheet_code: int | None) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False

    scale = 3
    grey = {0: None, 1: (0x60, 0x60, 0x60), 2: (0xA0, 0xA0, 0xA0), 3: (0xF0, 0xF0, 0xF0)}

    def pen_rgb(pen: int, is_tile: bool):
        if sheet_code is None:
            return grey[pen]
        return pen_rgb_code(conv, sheet_code, pen, is_tile)

    def dot_rgb(pen: int, _is_tile: bool):
        idx = dot_pen_color(pen)
        return None if idx is None else conv.palette[idx]

    def draw_set(grids, size, per_row, is_tile, title, rgb_of, scale):
        cell_w = size * scale + 4
        cell_h = size * scale + 14
        rows = (len(grids) + per_row - 1) // per_row
        img = Image.new("RGB", (max(per_row * cell_w + 4, 200), rows * cell_h + 16),
                        (0x20, 0x20, 0x30))
        draw = ImageDraw.Draw(img)
        draw.text((4, 2), title, fill=(255, 255, 255))
        for n, grid in enumerate(grids):
            ox = 4 + (n % per_row) * cell_w
            oy = 16 + (n // per_row) * cell_h
            for y, row in enumerate(grid):
                for x, pen in enumerate(row):
                    rgb = rgb_of(pen, is_tile)
                    if rgb is None:
                        rgb = (0x10, 0x10, 0x18) if (x + y) & 1 else (0x18, 0x18, 0x24)
                    draw.rectangle([ox + x * scale, oy + y * scale,
                                    ox + x * scale + scale - 1, oy + y * scale + scale - 1],
                                   fill=rgb)
            draw.text((ox, oy + size * scale + 1), f"{n:02x}", fill=(200, 200, 100))
        return img

    parts = [
        draw_set(conv.tiles, 8, 16, True, "tiles (bos1_14.5d), hex index", pen_rgb, scale),
        draw_set(conv.sprites, 16, 8, False, "sprites (bos1_13.5e), hex index", pen_rgb, scale),
        draw_set(conv.dots, 4, 8, False, "bullet dots (bos1-4.2r), as drawn", dot_rgb, 8),
    ]
    sheet = Image.new("RGB", (max(p.width for p in parts), sum(p.height for p in parts)),
                      (0x20, 0x20, 0x30))
    y = 0
    for p in parts:
        sheet.paste(p, (0, y))
        y += p.height
    sheet.save(out_dir / "sheet.png")

    # 64 colour codes x 4 pens, sprites on the left, tiles on the right
    cw, ch = 14, 9
    pal = Image.new("RGB", (2 * (4 * cw + 40) + 8, 64 * ch + 14), (0x20, 0x20, 0x30))
    draw = ImageDraw.Draw(pal)
    draw.text((4, 1), "code: sprite pens 0-3 | tile pens 0-3", fill=(255, 255, 255))
    for code in range(64):
        y = 13 + code * ch
        draw.text((2, y - 1), f"{code:02x}", fill=(200, 200, 100))
        for col, is_tile in enumerate((False, True)):
            x0 = 24 + col * (4 * cw + 40)
            for pen in range(4):
                rgb = pen_rgb_code(conv, code, pen, is_tile)
                x = x0 + pen * cw
                if rgb is None:
                    draw.rectangle([x, y, x + cw - 2, y + ch - 2], outline=(90, 90, 90))
                else:
                    draw.rectangle([x, y, x + cw - 2, y + ch - 2], fill=rgb)
    pal.save(out_dir / "palettes.png")
    return True


def pen_rgb_code(conv: Converter, code: int, pen: int, is_tile: bool):
    fn = tile_pen_color if is_tile else sprite_pen_color
    idx = fn(conv.lookup, code, pen)
    if idx == (TILE_TRANSPARENT if is_tile else SPRITE_TRANSPARENT):
        return None
    return conv.palette[idx]


# ------------------------------------------------------------------ main

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("romset", type=Path, help="bosco.zip or an unpacked directory")
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--art", type=Path, default=DEFAULT_ART,
                        help="drawn sprite art used for unmapped entries")
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT,
                        help="drawn font that the arcade digits and letters go into")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sheet-code", type=lambda s: int(s, 0), default=None,
                        help="colour code (0..63) to draw sheet.png with; default grey ramp")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        parts, notes = load_romset(args.romset)
        summary = convert(parts, args.map, args.art, args.out, args.sheet_code, args.font)
    except (RomError, gen_assets.AssetError, OSError, ValueError) as err:
        print(f"bosco_rom: {err}", file=sys.stderr)
        return 1

    if not args.quiet:
        for note in notes:
            print(f"note: {note}")
        print(f"{args.out / 'sprites.txt'}: {len(summary['mapped'])} sprites from the ROM, "
              f"{len(summary['unmapped'])} from the drawn art, "
              f"{summary['colors']} arcade colours mapped; font8.txt: "
              f"{summary['glyphs']} glyphs from the ROM")
        if summary["lost"]:
            print(f"{summary['lost']} ROM pixels fell outside their sprite boxes "
                  "(use crop, at or a bigger sprite)")
        if summary["unmapped"]:
            print("not mapped yet: " + ", ".join(summary["unmapped"]))
        print("sheets:", "sheet.png and palettes.png written" if summary["sheets"]
              else "skipped (Pillow not installed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
