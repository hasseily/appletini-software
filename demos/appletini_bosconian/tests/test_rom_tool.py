#!/usr/bin/env python3
"""Tests for tools/bosco_rom.py with a synthetic ROM set (no Namco data).

The tests build tile and sprite ROM images with an independent encoder that
follows MAME's charlayout_2bpp / spritelayout_bosco bit layout, plus made-up
colour PROMs, and check that the tool decodes them back, applies the colour
PROMs the way bosco_v.cpp does, finds the parts in a zip or a directory, and
writes a sprites.txt that gen_assets.py accepts.

Run:  python3 tests/test_rom_tool.py        (from the project directory)
"""

import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import bosco_rom  # noqa: E402
import gen_assets  # noqa: E402
from pathlib import Path  # noqa: E402


# ---------------------------------------------------------------- encoders

def setbit(buf: bytearray, bit: int) -> None:
    buf[bit >> 3] |= 0x80 >> (bit & 7)


def encode_gfx(grids, layout) -> bytes:
    """Inverse of bosco_rom.decode_gfx, written from the MAME layout tables."""
    buf = bytearray(layout["count"] * layout["inc"] // 8)
    for n, grid in enumerate(grids):
        base = n * layout["inc"]
        for y, row in enumerate(grid):
            for x, pen in enumerate(row):
                nplanes = len(layout["planes"])
                for i, plane in enumerate(layout["planes"]):
                    if (pen >> (nplanes - 1 - i)) & 1:   # first plane = high bit (MAME)
                        setbit(buf, base + plane + layout["yoff"][y] + layout["xoff"][x])
    return bytes(buf)


def crc32_forge(prefix: bytes, target: int) -> bytes:
    """prefix + 4 bytes whose CRC32 is target (CRC is affine over GF(2))."""
    import zlib
    base = zlib.crc32(prefix + bytes(4)) & 0xFFFFFFFF
    columns = []
    for bit in range(32):
        tail = (1 << bit).to_bytes(4, "little")
        columns.append((zlib.crc32(prefix + tail) & 0xFFFFFFFF) ^ base)
    # solve sum(x_bit * columns[bit]) = target ^ base by Gaussian elimination
    rows = [(columns[bit], 1 << bit) for bit in range(32)]   # (value, which x bits)
    want = target ^ base
    solution = 0
    for pivot in range(31, -1, -1):
        idx = next((i for i, (v, _) in enumerate(rows) if v >> pivot & 1), None)
        if idx is None:
            continue
        pv, px = rows.pop(idx)
        rows = [(v ^ pv, x ^ px) if v >> pivot & 1 else (v, x) for v, x in rows]
        if want >> pivot & 1:
            want ^= pv
            solution ^= px
    assert want == 0, "CRC system has no solution"
    out = prefix + solution.to_bytes(4, "little")
    assert zlib.crc32(out) & 0xFFFFFFFF == target
    return out


def diamond(size: int, pen: int, edge_pen: int):
    """A filled diamond with a differently coloured edge, pen 0 outside."""
    c = size // 2
    grid = []
    for y in range(size):
        row = []
        for x in range(size):
            d = abs(x - c) + abs(y - c)
            if d <= c - 3:
                row.append(pen)
            elif d <= c - 1:
                row.append(edge_pen)
            else:
                row.append(0)
        grid.append(row)
    return grid


def make_romset(tmp: str, as_zip: bool):
    """Synthetic tiles/sprites/PROMs. Returns (path, tiles, sprites, palette, lookup)."""
    tiles = []
    for n in range(256):
        # tile n: a pattern that depends on n so every tile is distinct
        tiles.append([[((x + y + n) % 4) if ((x * 3 + y * 5 + n) % 7) else 0
                       for x in range(8)] for y in range(8)])
    sprites = []
    for n in range(64):
        if n == 5:
            sprites.append(diamond(16, 3, 1))
        else:
            sprites.append([[((x * y + n) % 4) for x in range(16)] for y in range(16)])
    # palette PROM: 32 bytes, index 0 black, index 15 black (sprite transparent),
    # 1 = red, 2 = green, 3 = blue, 4 = white ...
    pal = bytearray(32)
    pal[1] = 0x07            # red bits 0-2
    pal[2] = 0x38            # green bits 3-5
    pal[3] = 0xC0            # blue bits 6-7
    pal[4] = 0xFF            # white
    pal[5] = 0x1C            # a mixed colour
    for i in range(6, 15):
        pal[i] = i * 9 & 0xFF
    pal[15] = 0x00
    pal[16] = 0x00           # tile colours 16..31
    pal[17] = 0x07
    pal[18] = 0x38
    pal[19] = 0xC0
    pal[20] = 0xFF
    for i in range(21, 31):
        pal[i] = i * 7 & 0xFF
    pal[31] = 0x00
    # lookup: code c, pen p -> palette index. code 0: pen0 transparent (15),
    # pens 1..3 -> 1 red, 2 green, 4 white. code 1: pen 0 -> 3 (opaque blue),
    # code 2: everything transparent.
    lookup = bytearray(256)
    for code in range(64):
        for pen in range(4):
            lookup[code * 4 + pen] = (code + pen) & 0x0F
    lookup[0:4] = bytes([15, 1, 2, 4])
    lookup[4:8] = bytes([3, 1, 2, 4])
    lookup[8:12] = bytes([15, 15, 15, 15])

    # bullet dots: dot n is a 2x2 block of pen (n & 3) at the top left, the
    # rest transparent (pen 4); dot 7 is a full block of pen 1
    dots = []
    for n in range(8):
        if n == 7:
            dots.append([[1] * 4 for _ in range(4)])
        else:
            dots.append([[(n & 3) if (x < 2 and y < 2) else 4 for x in range(4)]
                         for y in range(4)])
    files = {
        "bos1_14.5d": encode_gfx(tiles, bosco_rom.TILE_LAYOUT),
        "bos1_13.5e": encode_gfx(sprites, bosco_rom.SPRITE_LAYOUT),
        "bos1-6.6b": bytes(pal),
        "bos1-5.4m": bytes(lookup),
        "bos1-4.2r": encode_gfx(dots, bosco_rom.DOT_LAYOUT).ljust(0x100, b"\0"),
        "bos1_1.3n": bytes(0x1000),      # a code ROM: same size as the graphics
    }
    if as_zip:
        path = os.path.join(tmp, "bosco.zip")
        with zipfile.ZipFile(path, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
    else:
        path = os.path.join(tmp, "bosco")
        os.mkdir(path)
        for name, data in files.items():
            with open(os.path.join(path, name), "wb") as f:
                f.write(data)
    return path, tiles, sprites, bytes(pal), bytes(lookup)


class DecodeTest(unittest.TestCase):
    def test_tile_bit_positions_follow_mame(self):
        # pixel x=4,y=0 pen 2 -> plane 0 (the high bit), xoff 0: byte 0 bit 7
        # pixel x=0,y=0 pen 1 -> plane 1 (offset 4, the low bit), xoff 64: byte 8 bit 3
        # pixel x=7,y=3 pen 3 -> plane 0 xoff 3 + y 24: byte 3 bit 4; plane 1: byte 3 bit 0
        rom = bytearray(0x1000)
        rom[0] = 0x80
        rom[8] = 0x08
        rom[3] = 0x10 | 0x01
        grids = bosco_rom.decode_gfx(bytes(rom), bosco_rom.TILE_LAYOUT)
        t = grids[0]
        self.assertEqual(t[0][4], 2)
        self.assertEqual(t[0][0], 1)
        self.assertEqual(t[3][7], 3)
        self.assertEqual(sum(sum(r) for r in t), 6)
        self.assertTrue(all(sum(sum(r) for r in g) == 0 for g in grids[1:]))

    def test_sprite_bit_positions_follow_mame(self):
        # sprite 1 starts at byte 64. pixel x=12,y=0 pen 2 -> plane 0, xoff 0: byte 64 bit 7
        # pixel x=0,y=8 pen 2 -> xoff 64 + yoff 256: byte 64+40 bit 7
        rom = bytearray(0x1000)
        rom[64] = 0x80
        rom[64 + 40] = 0x80
        grids = bosco_rom.decode_gfx(bytes(rom), bosco_rom.SPRITE_LAYOUT)
        s = grids[1]
        self.assertEqual(s[0][12], 2)
        self.assertEqual(s[8][0], 2)
        self.assertEqual(sum(sum(r) for r in s), 4)

    def test_roundtrip_all_tiles_and_sprites(self):
        tmp = tempfile.mkdtemp()
        try:
            path, tiles, sprites, _pal, _lut = make_romset(tmp, as_zip=False)
            parts, notes = bosco_rom.load_romset(Path(path))
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(bosco_rom.decode_gfx(parts["tiles"], bosco_rom.TILE_LAYOUT), tiles)
        self.assertEqual(bosco_rom.decode_gfx(parts["sprites"], bosco_rom.SPRITE_LAYOUT),
                         sprites)
        # synthetic data never has MAME's CRCs: every part was found by name
        self.assertEqual(len(notes), 5)

    def test_palette_formula(self):
        colors = bosco_rom.decode_palette(bytes([0x00, 0xFF, 0x07, 0x38, 0xC0, 0x01]) + bytes(26))
        self.assertEqual(colors[0], (0, 0, 0))
        self.assertEqual(colors[1], (0xFF, 0xFF, 0xDE))
        self.assertEqual(colors[2], (0xFF, 0, 0))
        self.assertEqual(colors[3], (0, 0xFF, 0))
        self.assertEqual(colors[4], (0, 0, 0xDE))
        self.assertEqual(colors[5], (0x21, 0, 0))
        self.assertEqual(len(colors), 32)

    def test_lookup_and_transparency(self):
        lut = bytes(range(256))
        # sprite: low nibble; tile: low nibble | 0x10
        self.assertEqual(bosco_rom.sprite_pen_color(lut, 1, 2), (4 + 2) & 0x0F)
        self.assertEqual(bosco_rom.tile_pen_color(lut, 1, 2), 0x16)
        grid = [[0, 1, 2, 3]]
        # code 3: entries 12..15 -> 12,13,14,15: pen 3 is transparent for sprites
        col = bosco_rom.colorize(grid, lut, 3, is_tile=False)
        self.assertEqual(col, [[12, 13, 14, None]])
        col = bosco_rom.colorize(grid, lut, 3, is_tile=True)
        self.assertEqual(col, [[0x1C, 0x1D, 0x1E, None]])


class RomsetTest(unittest.TestCase):
    def test_zip_by_name_and_wrong_size_rejected(self):
        tmp = tempfile.mkdtemp()
        try:
            path, _t, _s, pal, lut = make_romset(tmp, as_zip=True)
            parts, notes = bosco_rom.load_romset(Path(path))
            self.assertEqual(parts["palette"], pal)
            self.assertEqual(parts["lookup"], lut)
            self.assertEqual(len(parts["tiles"]), 0x1000)
            self.assertTrue(all("found by name" in n for n in notes))
            # a set without the sprite ROM is refused with a listing
            bad = os.path.join(tmp, "bad.zip")
            with zipfile.ZipFile(path) as src, zipfile.ZipFile(bad, "w") as dst:
                for info in src.infolist():
                    if info.filename != "bos1_13.5e":
                        dst.writestr(info.filename, src.read(info.filename))
            with self.assertRaises(bosco_rom.RomError) as ctx:
                bosco_rom.load_romset(Path(bad))
            self.assertIn("sprites", str(ctx.exception))
            self.assertIn("bos1_14.5d", str(ctx.exception))
        finally:
            shutil.rmtree(tmp)

    def test_crc_match_wins_over_names(self):
        tmp = tempfile.mkdtemp()
        try:
            # a 32-byte file with the palette PROM's real CRC but a strange name
            data = crc32_forge(bytes(range(28)), bosco_rom.ROM_PARTS["palette"]["crc"])
            self.assertEqual(len(data), 32)
            path, *_ = make_romset(tmp, as_zip=False)
            with open(os.path.join(path, "weird.bin"), "wb") as f:
                f.write(data)
            parts, notes = bosco_rom.load_romset(Path(path))
            self.assertEqual(parts["palette"], data)
            self.assertFalse(any(n.startswith("palette") for n in notes))
        finally:
            shutil.rmtree(tmp)


class ConvertTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path, self.tiles, self.sprites, self.pal, self.lut = make_romset(self.tmp, True)
        self.parts, _ = bosco_rom.load_romset(Path(self.path))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_map(self, text: str) -> Path:
        p = Path(self.tmp) / "map.txt"
        p.write_text(text)
        return p

    def test_project_map_maps_every_sprite(self):
        entries, font_map = bosco_rom.parse_map(Path(ROOT) / "assets" / "rom_map.txt")
        self.assertEqual(set(entries), {n for n, _, _ in gen_assets.SPRITES})
        self.assertTrue(all(e.mapped for e in entries.values()))
        kinds = {e.kind for e in entries.values()}
        self.assertEqual(kinds, {"sprite", "sprites", "tile", "tilemap", "dot"})
        # every 16x16 ship heading is one of the ROM's three headings, flipped
        for base in ("SHIP", "ITYPE", "PTYPE", "ETYPE", "SPY"):
            codes = {entries[f"{base}_{h}"].indices[0] for h in range(8)}
            self.assertEqual(len(codes), 3, base)
            self.assertEqual(entries[f"{base}_2"].ops, ["fliph"])
            self.assertEqual(entries[f"{base}_5"].ops, ["rot180"])
            self.assertEqual(entries[f"{base}_6"].ops, [])
        # the base parts are tile grids of the arcade's own tile codes
        for name, w, h in gen_assets.SPRITES:
            if name.startswith(("POD", "CORE")):
                e = entries[name]
                self.assertEqual(e.kind, "tilemap", name)
                self.assertEqual((e.tw * 8, e.th * 8), (w, h), name)
                self.assertTrue(any(c is not None for c in e.cells), name)
        self.assertEqual(font_map["0"], 0x00)
        self.assertEqual(font_map["9"], 0x09)
        self.assertEqual(font_map["A"], 0x0A)
        self.assertEqual(font_map["Z"], 0x23)
        self.assertEqual(font_map["-"], 0x26)

    def test_convert_mixes_rom_and_drawn_art(self):
        m = self.write_map("SHIP_0: sprite 5 color 0\n"
                           "SHIP_1: sprite 5 color 0 rot90\n"
                           "MINE: tiles 0x10 0x11 0x20 0x21 color 1 center\n"
                           "ICON_BASE: tile 7 color 1\n"
                           "SHOT_ENEMY: sprite 5 color 0 crop 6 6 4 4 center\n"
                           "ITYPE_0: ?\n")
        out = Path(self.tmp) / "out"
        summary = bosco_rom.convert(self.parts, m, Path(ROOT) / "assets" / "sprites.txt", out)
        self.assertEqual(summary["mapped"], ["SHIP_0", "SHIP_1", "MINE", "SHOT_ENEMY",
                                             "ICON_BASE"])
        self.assertIn("ITYPE_0", summary["unmapped"])
        self.assertEqual(summary["lost"], 0)
        grids = gen_assets.parse_sprites(out / "sprites.txt")
        art = gen_assets.parse_sprites(Path(ROOT) / "assets" / "sprites.txt")
        # unmapped entries are the drawn art
        self.assertEqual(grids["ITYPE_0"], art["ITYPE_0"])
        self.assertEqual(grids["BIGEXPL_0"], art["BIGEXPL_0"])
        # the diamond: pen 3 -> palette 4 (white) -> SHR white (1); its edge
        # pen 1 -> palette 1 (red) -> SHR red (2); pen 0 -> palette 15 -> transparent.
        # Its opaque part is 15x15 (columns 1..15 of the source); fit crops it
        # and puts it at 0,0 of the 16x16 box, so row 7 is the widest row.
        ship = grids["SHIP_0"]
        self.assertEqual(len(ship), 16)
        self.assertEqual(ship[7][:15], [2, 2] + [1] * 11 + [2, 2])
        self.assertIsNone(ship[7][15])
        self.assertEqual(ship[8][8], 1)
        self.assertEqual(ship[8][2], 2)
        self.assertIsNone(ship[0][0])
        self.assertEqual([row[7] for row in ship[:15]], [2, 2] + [1] * 11 + [2, 2])
        # rot90 of a symmetric diamond is the same picture
        self.assertEqual(grids["SHIP_1"], ship)
        # the 2x2 tile block is 16x16 and uses tile colours (code 1: pen 0 opaque
        # blue -> palette 17+? tile lookup |0x10) -- every pixel is opaque
        mine = grids["MINE"]
        self.assertEqual((len(mine), len(mine[0])), (16, 16))
        self.assertTrue(all(p is not None for row in mine for p in row))
        # crop 4x4 of the diamond centre, centred in the 4x4 shot box
        shot = grids["SHOT_ENEMY"]
        self.assertEqual((len(shot), len(shot[0])), (4, 4))
        self.assertTrue(all(p == 1 for row in shot for p in row))
        # the whole file builds like the drawn art does
        encoded, _font, _g, _blobs = gen_assets.build_all(Path(ROOT) / "assets",
                                                          out / "sprites.txt")
        self.assertEqual(len(encoded), gen_assets.SPR_COUNT)
        self.assertTrue((out / "colors.txt").exists())
        text = (out / "colors.txt").read_text()
        self.assertIn("SHIP_0", text)
        # without a font: line the font is the drawn one
        self.assertEqual(gen_assets.parse_font(out / "font8.txt"),
                         gen_assets.parse_font(Path(ROOT) / "assets" / "font8.txt"))

    def test_tilemap_dot_and_font_sources(self):
        m = self.write_map("ASTEROID_0: tilemap 2 2\n"
                           "    10:41 11:01\n"
                           "    20:c1 ..\n"
                           "SHOT_PLAYER: dot 1\n"
                           "SHOT_ENEMY: dot 7 fliph\n"
                           "MISSILE_0: dot 0\n"
                           "font: digits 0x10 minus 0x30\n")
        out = Path(self.tmp) / "out2"
        summary = bosco_rom.convert(self.parts, m, Path(ROOT) / "assets" / "sprites.txt", out)
        self.assertEqual(summary["mapped"], ["ASTEROID_0", "SHOT_PLAYER", "SHOT_ENEMY",
                                             "MISSILE_0"])
        self.assertEqual(summary["glyphs"], 11)
        grids = gen_assets.parse_sprites(out / "sprites.txt")
        # tile attribute: colour code in the low 6 bits, bit 6 clear = mirrored,
        # bit 7 = upside down (bosco_v.cpp: TILE_FLIPYX(attr >> 6) ^ TILE_FLIPX)
        conv = bosco_rom.Converter(self.parts)
        tiles = bosco_rom.decode_gfx(self.parts["tiles"], bosco_rom.TILE_LAYOUT)
        lookup = self.parts["lookup"]

        def tile(code, attr):
            g = bosco_rom.colorize(tiles[code], lookup, attr & 0x3F, True)
            if not attr & 0x40:
                g = [row[::-1] for row in g]
            if attr & 0x80:
                g = g[::-1]
            return [[None if p is None else conv.shr_index(p, "x") for p in row] for row in g]

        rock = grids["ASTEROID_0"]
        self.assertEqual([row[:8] for row in rock[:8]], tile(0x10, 0x41))
        self.assertEqual([row[8:] for row in rock[:8]], tile(0x11, 0x01))
        self.assertEqual([row[:8] for row in rock[8:]], tile(0x20, 0xC1))
        self.assertTrue(all(p is None for row in rock[8:] for p in row[8:]), "empty cell")
        # dot 1: a 2x2 block of pen 1 (bullet palette entry 30 of this PROM)
        # drawn upside down and mirrored like the arcade's bullets, fit into
        # the 2x4 box
        c = conv.shr_index(bosco_rom.DOT_FIRST_COLOR - 1, "x")
        shot = grids["SHOT_PLAYER"]
        self.assertEqual(shot, [[None, None], [c, c], [c, c], [None, None]])
        # dot 7 is a full block of pen 1; dot 0 is pen 0 = opaque black
        self.assertEqual(grids["SHOT_ENEMY"], [[c] * 4 for _ in range(4)])
        missile = grids["MISSILE_0"]
        self.assertEqual(sum(p == 0 for row in missile for p in row), 4)
        self.assertEqual(sum(p is None for row in missile for p in row), 12)
        # the font: '0'..'9' from tiles 0x10.., '-' from 0x30, the rest drawn
        font = gen_assets.parse_font(out / "font8.txt")
        drawn = gen_assets.parse_font(Path(ROOT) / "assets" / "font8.txt")
        for ch, code in list(zip("0123456789", range(0x10, 0x1A))) + [("-", 0x30)]:
            rows = [int("".join("1" if p else "0" for p in row), 2) for row in tiles[code]]
            self.assertEqual(font[ord(ch) - 32], rows, ch)
        self.assertEqual(font[ord("A") - 32], drawn[ord("A") - 32])
        self.assertEqual(font[0], drawn[0])

    def test_map_errors(self):
        for bad, msg in (("SHIP_0: sprite 5\n", "color"),
                         ("NOPE: sprite 5 color 0\n", "unknown sprite"),
                         ("SHIP_0: sprite 5 color 0\nSHIP_0: ?\n", "twice"),
                         ("SHIP_0: sprite 99 color 0\n", None),
                         ("SHIP_0: tiles 1 2 3 color 0\n", "4 indices"),
                         ("SHIP_0: sprite 5 color 64\n", "0..63"),
                         ("SHIP_0: sprite 5 color 0 wobble\n", "unknown option"),
                         ("SHIP_0: tilemap 2 2 10:41 11:01 20:41\n", "needs 4 cells"),
                         ("SHIP_0: tilemap 2 2 10:41 zz 20:41 21:01\n", "not CODE:ATTR"),
                         ("SHIP_0: dot 1 color 2\n", "no color"),
                         ("SHIP_0: dot 9\n", "0..7"),
                         ("font: digits\n", "RUN N pairs"),
                         ("font: vowels 3\n", "font run")):
            m = self.write_map(bad)
            with self.assertRaises(bosco_rom.RomError, msg=bad) as ctx:
                bosco_rom.convert(self.parts, m, Path(ROOT) / "assets" / "sprites.txt",
                                  Path(self.tmp) / "o")
            if msg:
                self.assertIn(msg, str(ctx.exception))

    def test_pixels_outside_the_box_are_counted(self):
        # a 16x16 sprite placed at 8,8 in a 16x16 box loses three quarters
        m = self.write_map("SHIP_0: sprite 7 color 1 at 8 8\n")
        summary = bosco_rom.convert(self.parts, m, Path(ROOT) / "assets" / "sprites.txt",
                                    Path(self.tmp) / "o")
        self.assertEqual(summary["lost"], 16 * 16 - 8 * 8)

    def test_command_line(self):
        m = self.write_map("SHIP_0: sprite 5 color 0\n")
        out = Path(self.tmp) / "cli"
        rc = bosco_rom.main([self.path, "--map", str(m), "--out", str(out), "--quiet"])
        self.assertEqual(rc, 0)
        self.assertTrue((out / "sprites.txt").exists())
        rc = bosco_rom.main([os.path.join(self.tmp, "missing.zip"), "--quiet"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
