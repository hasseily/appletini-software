#!/usr/bin/env python3
"""Check tools/gen_assets.py output against docs/DESIGN.md sections 3, 4 and 9.

Run:  python3 tests/test_assets.py        (from the project directory)

The test runs the generator into a temporary build directory, parses the
generated assets.s back into bytes with its own small parser, decodes every
sprite variant and compares it with an independent reading of the text art.
If ca65/ld65/cc65 are installed it also assembles and links assets.s and
compiles a C file that includes both bosco.h and build/assets.h.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "tools"
ASSETS = PROJECT / "assets"
GEN = TOOLS / "gen_assets.py"

sys.path.insert(0, str(TOOLS))
import gen_assets  # noqa: E402

# Independent copy of docs/DESIGN.md section 9.
DESIGN_SPRITES = (
    [("SHIP_%d" % i, 16, 16) for i in range(8)]
    + [("ITYPE_%d" % i, 12, 12) for i in range(8)]
    + [("PTYPE_%d" % i, 12, 12) for i in range(8)]
    + [("ETYPE_%d" % i, 12, 12) for i in range(4)]
    + [("MINE_%d" % i, 12, 12) for i in range(2)]
    + [("ASTEROID_%d" % i, 16, 16) for i in range(2)]
    + [("POD", 16, 16), ("CORE_CLOSED", 16, 16), ("CORE_OPEN", 16, 16)]
    + [("EXPL_%d" % i, 16, 16) for i in range(4)]
    + [("SHOT_PLAYER", 2, 6), ("SHOT_ENEMY", 4, 4)]
    + [("MISSILE_%d" % i, 6, 8) for i in range(2)]
    + [("ICON_SHIP", 8, 8), ("ICON_BASE", 8, 8), ("POD_HIT", 16, 16)]
    + [("BIGEXPL_%d" % i, 32, 32) for i in range(4)]
    + [("SHOT_PLAYER_H", 6, 2), ("SHOT_PLAYER_D", 4, 4)]
)
SPR_COUNT = len(DESIGN_SPRITES)
DESIGN_IDS = {
    "SPR_SHIP_0": 0, "SPR_ITYPE_0": 8, "SPR_PTYPE_0": 16, "SPR_ETYPE_0": 24,
    "SPR_MINE_0": 28, "SPR_ASTEROID_0": 30, "SPR_POD": 32, "SPR_CORE_CLOSED": 33,
    "SPR_CORE_OPEN": 34, "SPR_EXPL_0": 35, "SPR_SHOT_PLAYER": 39,
    "SPR_SHOT_ENEMY": 40, "SPR_MISSILE_0": 41, "SPR_ICON_SHIP": 43,
    "SPR_ICON_BASE": 44, "SPR_POD_HIT": 45, "SPR_BIGEXPL_0": 46,
    "SPR_SHOT_PLAYER_H": 50, "SPR_SHOT_PLAYER_D": 51, "SPR_COUNT": 52,
}
# docs/DESIGN.md section 3, as (R, G, B) 4-bit values.
DESIGN_PALETTE = [
    (0, 0, 0), (0xF, 0xF, 0xF), (0xA, 0xA, 0xA), (5, 5, 5), (0xF, 0, 0),
    (0xF, 8, 0), (0xF, 0xF, 0), (0, 0xC, 0), (0, 0xF, 0xF), (0, 0, 0xF),
    (0, 0, 8), (0xF, 0, 0xF), (0xF, 8, 0xB), (8, 4, 0), (0, 6, 0), (8, 0xB, 0xF),
]
MAX_TOTAL_BYTES = 16 * 1024
EMPTY = gen_assets.EMPTY_ROW_BYTES


# ---------------------------------------------------------------- helpers

def parse_asm(text: str):
    """Return (blocks, tables): label -> bytes for .byte blocks, label -> list
    of symbol names for .lobytes/.hibytes tables, in file order."""
    blocks: dict[str, bytearray] = {}
    tables: dict[str, tuple[str, list[str]]] = {}
    order: list[str] = []
    label = None
    for raw in text.split("\n"):
        line = raw.split(";", 1)[0].rstrip()
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", line)
        if m:
            label = m.group(1)
            order.append(label)
            continue
        s = line.strip()
        if s.startswith(".byte"):
            vals = [int(v.strip()[1:], 16) for v in s[5:].split(",")]
            blocks.setdefault(label, bytearray()).extend(vals)
        elif s.startswith(".lobytes") or s.startswith(".hibytes"):
            kind = s.split()[0][1:]
            names = [n.strip() for n in s.split(None, 1)[1].split(",")]
            t = tables.setdefault(label, (kind, []))
            t[1].extend(names)
    return blocks, tables, order


def own_grid_transform(grid, op):
    """Second implementation of the derive operations, for cross-checking."""
    h, w = len(grid), len(grid[0])
    if op == "copy":
        return [r[:] for r in grid]
    if op == "fliph":
        return [r[::-1] for r in grid]
    if op == "flipv":
        return [r[:] for r in reversed(grid)]
    if op == "rot180":
        return [r[::-1] for r in reversed(grid)]
    assert w == h
    out = [[None] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if op == "rot90":
                out[y][x] = grid[h - 1 - x][y]      # clockwise
            elif op == "rot270":
                out[y][x] = grid[x][w - 1 - y]      # counter-clockwise
            else:
                raise ValueError(op)
    return out


def own_parse_sprites(path: Path):
    grids = {}
    lines = path.read_text().split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        i += 1
        if not s or s.startswith("#"):
            continue
        w = s.split()
        if w[0] == "sprite":
            name, width, height = w[1], int(w[2]), int(w[3])
            rows = lines[i:i + height]
            i += height
            grids[name] = [[gen_assets.PIXEL_CHARS[c] for c in r] for r in rows]
            assert all(len(r) == width for r in rows), name
        elif w[0] == "derive":
            grids[w[1]] = own_grid_transform(grids[w[4]], w[3])
    return grids


def own_parse_font(path: Path):
    glyphs = {}
    lines = path.read_text().split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        i += 1
        if s.startswith("glyph"):
            code = int(s.split()[1])
            rows = lines[i:i + 8]
            i += 8
            glyphs[code] = [int(r.replace("#", "1").replace(".", "0"), 2) for r in rows]
    return glyphs


# ---------------------------------------------------------------- tests

class GeneratorRun(unittest.TestCase):
    """Run the generator once for the whole test module."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="bosco_assets_"))
        cls.build = cls.tmp / "build"
        r = subprocess.run([sys.executable, str(GEN), "--build", str(cls.build),
                            "--quiet"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("gen_assets.py failed:\n" + r.stdout + r.stderr)
        cls.asm_text = (cls.build / "assets.s").read_text()
        cls.h_text = (cls.build / "assets.h").read_text()
        cls.blocks, cls.tables, cls.order = parse_asm(cls.asm_text)
        cls.grids = own_parse_sprites(ASSETS / "sprites.txt")
        cls.font = own_parse_font(ASSETS / "font8.txt")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestSpriteFormat(GeneratorRun):

    def variant(self, i, name):
        return bytes(self.blocks[f"spr_{i:02d}_{name}"])

    def test_all_sprites_present_with_design_sizes(self):
        self.assertEqual(len(DESIGN_SPRITES), 52)
        for i, (name, w, h) in enumerate(DESIGN_SPRITES):
            self.assertIn(name, self.grids, f"{name} missing in sprites.txt")
            g = self.grids[name]
            self.assertEqual((len(g[0]), len(g)), (w, h), name)
            even = self.variant(i, "even")
            odd = self.variant(i, "odd")
            self.assertEqual(even[0], h, f"{name} even height")
            self.assertEqual(odd[0], h, f"{name} odd height")
            self.assertEqual(even[1], (w + 1) // 2, f"{name} even width_bytes")
            self.assertEqual(odd[1], (w + 2) // 2, f"{name} odd width_bytes")
            self.assertLessEqual(even[1], 32)
            self.assertLessEqual(odd[1], 32)

    def check_variant(self, name, grid, data, shift):
        """Walk the row records by hand and compare with the source art."""
        h, wb = data[0], data[1]
        w = len(grid[0])
        pos = 2
        for y in range(h):
            row = grid[y]
            opaque = [x for x, p in enumerate(row) if p is not None]
            run_off = data[pos]
            if not opaque:
                self.assertEqual(run_off, 0xFF, f"{name} row {y}: expected empty")
                self.assertEqual(tuple(data[pos:pos + len(EMPTY)]), EMPTY)
                pos += len(EMPTY)
                continue
            self.assertNotEqual(run_off, 0xFF, f"{name} row {y}: not empty")
            run_len = data[pos + 1]
            pos += 2
            first_byte = (opaque[0] + shift) // 2
            last_byte = (opaque[-1] + shift) // 2
            self.assertEqual(run_off, first_byte, f"{name} row {y} run_off")
            self.assertEqual(run_len, last_byte - first_byte + 1, f"{name} row {y} run_len")
            self.assertLess(run_off, wb)
            self.assertLessEqual(run_off + run_len, wb)
            pixels = data[pos:pos + run_len]
            pos += run_len
            for x in range(w):
                sx = x + shift
                b = sx // 2 - run_off
                if b < 0 or b >= run_len:
                    self.assertIsNone(row[x], f"{name} row {y} x {x} outside run")
                    continue
                val = pixels[b] >> 4 if sx % 2 == 0 else pixels[b] & 15
                expect = 0 if row[x] is None else row[x]
                self.assertEqual(val, expect, f"{name} row {y} x {x} shift {shift}")
            # the pixel shifted in at the left of the odd variant is black
            if shift == 1 and run_off == 0:
                self.assertEqual(pixels[0] >> 4, 0, f"{name} row {y}: odd fill pixel")
        self.assertEqual(pos, len(data), f"{name}: trailing bytes")

    def test_even_and_odd_variants_match_the_art(self):
        for i, (name, _w, _h) in enumerate(DESIGN_SPRITES):
            self.check_variant(name, self.grids[name], self.variant(i, "even"), 0)
            self.check_variant(name, self.grids[name], self.variant(i, "odd"), 1)

    def test_rows_are_convex(self):
        """No transparent pixel inside a run (they would be drawn black)."""
        for name, w, h in DESIGN_SPRITES:
            for y, row in enumerate(self.grids[name]):
                opaque = [x for x, p in enumerate(row) if p is not None]
                if opaque:
                    inside = row[opaque[0]:opaque[-1] + 1]
                    self.assertNotIn(None, inside, f"{name} row {y} has a hole")

    def test_generator_rotation_matches_reference(self):
        gen_grids = gen_assets.parse_sprites(ASSETS / "sprites.txt")
        for name, _w, _h in DESIGN_SPRITES:
            self.assertEqual(gen_grids[name], self.grids[name], name)
        # rot90 is clockwise: the top-left pixel moves to the top-right.
        g = [[1, None], [None, None]]
        self.assertEqual(gen_assets.transform(g, "rot90"), [[None, 1], [None, None]])
        self.assertEqual(gen_assets.transform(g, "rot180"), [[None, None], [None, 1]])
        self.assertEqual(gen_assets.transform(g, "rot270"), [[None, None], [1, None]])

    def test_heading_sprites_are_rotations(self):
        """Heading 4 (S) is the N sprite turned 180 degrees only if drawn so;
        instead check the derive rules: E rotated 90 is S, NE rotated 90 is SE."""
        for base in ("SHIP", "ITYPE", "PTYPE"):
            g = self.grids
            self.assertEqual(g[f"{base}_3"], own_grid_transform(g[f"{base}_1"], "rot90"))
            self.assertEqual(g[f"{base}_4"], own_grid_transform(g[f"{base}_2"], "rot90"))
            self.assertEqual(g[f"{base}_5"], own_grid_transform(g[f"{base}_1"], "rot180"))
            self.assertEqual(g[f"{base}_6"], own_grid_transform(g[f"{base}_2"], "rot180"))
            self.assertEqual(g[f"{base}_7"], own_grid_transform(g[f"{base}_1"], "rot270"))

    def test_art_uses_the_directed_colors(self):
        g = self.grids

        def colors(name):
            return {p for row in g[name] for p in row if p is not None}

        self.assertTrue({1, 8} <= colors("SHIP_0"))          # white + cyan cockpit
        self.assertIn(8, colors("ITYPE_0"))                  # cyan
        self.assertIn(9, colors("PTYPE_0"))                  # blue
        self.assertIn(11, colors("ETYPE_0"))                 # magenta
        self.assertTrue({11, 12} <= colors("MINE_0"))        # magenta/pink
        self.assertNotEqual(g["MINE_0"], g["MINE_1"])        # blink
        self.assertTrue({3, 13} <= colors("ASTEROID_0"))     # gray/brown
        self.assertTrue({7, 14} <= colors("POD"))            # green/dark green
        self.assertTrue({5, 6} & colors("CORE_OPEN"))        # orange/yellow center
        self.assertFalse({5, 6} & colors("CORE_CLOSED"))
        self.assertEqual(colors("SHOT_PLAYER") - {1}, {12})  # pink
        self.assertEqual(colors("SHOT_PLAYER_H"), colors("SHOT_PLAYER"))
        self.assertEqual(colors("SHOT_PLAYER_D"), colors("SHOT_PLAYER"))
        self.assertEqual(g["SHOT_PLAYER_H"], [list(c) for c in zip(*g["SHOT_PLAYER"])])
        self.assertIn(6, colors("SHOT_ENEMY"))               # yellow
        self.assertIn(15, colors("MISSILE_0"))               # light blue
        self.assertTrue({1, 6} <= colors("POD_HIT"))         # white/yellow
        for i in range(4):
            self.assertIn(5 if i == 0 else (6, 4, 3)[i - 1], colors(f"EXPL_{i}"))
        # explosions grow: count opaque pixels
        counts = [sum(p is not None for row in g[f"BIGEXPL_{i}"] for p in row)
                  for i in range(3)]
        self.assertEqual(counts, sorted(counts))


class TestTablesFontPalette(GeneratorRun):

    def test_tables_index_variants_in_id_order(self):
        for label, kind, variant in (("_spr_even_lo", "lobytes", "even"),
                                     ("_spr_even_hi", "hibytes", "even"),
                                     ("_spr_odd_lo", "lobytes", "odd"),
                                     ("_spr_odd_hi", "hibytes", "odd")):
            k, names = self.tables[label]
            self.assertEqual(k, kind, label)
            self.assertEqual(names, [f"spr_{i:02d}_{variant}" for i in range(SPR_COUNT)], label)
        self.assertEqual(list(self.blocks["_spr_width"]), [w for _n, w, _h in DESIGN_SPRITES])
        self.assertEqual(list(self.blocks["_spr_height"]), [h for _n, _w, h in DESIGN_SPRITES])

    def test_exports_and_segment(self):
        for sym in ("_spr_even_lo", "_spr_even_hi", "_spr_odd_lo", "_spr_odd_hi",
                    "_spr_width", "_spr_height", "_font8", "_palette0"):
            self.assertRegex(self.asm_text, r"\.export[^\n]*\b" + sym + r"\b")
            self.assertIn(sym, self.order)
        self.assertIn('.segment "RODATA"', self.asm_text)
        self.assertIsNotNone(re.search(r"^;.*total\s*:\s*\d+", self.asm_text, re.M))

    def test_font(self):
        font = bytes(self.blocks["_font8"])
        self.assertEqual(len(font), 64 * 8)
        self.assertEqual(sorted(self.font), list(range(32, 96)))
        for code in range(32, 96):
            k = code - 32
            self.assertEqual(list(font[k * 8:k * 8 + 8]), self.font[code], f"glyph {code}")
        self.assertEqual(font[0:8], bytes(8))                  # space is blank
        self.assertTrue(all(any(font[k * 8:k * 8 + 8]) for k in range(1, 64)))
        # bit 7 = leftmost pixel: 'L' (76) has its stem on the left, so bit 7
        # is set on every row but the last blank one; ']' has nothing there.
        stem = font[(76 - 32) * 8:(76 - 32) * 8 + 7]
        self.assertTrue(all(b & 0x80 for b in stem))
        bracket = font[(93 - 32) * 8:(93 - 32) * 8 + 8]
        self.assertFalse(any(b & 0x80 for b in bracket))

    def test_palette(self):
        pal = bytes(self.blocks["_palette0"])
        self.assertEqual(len(pal), 32)
        for i, (r, g, b) in enumerate(DESIGN_PALETTE):
            self.assertEqual(pal[2 * i], (g << 4) | b, f"palette {i} byte 0")
            self.assertEqual(pal[2 * i + 1], r, f"palette {i} byte 1")

    def test_total_size(self):
        total = sum(len(v) for v in self.blocks.values()) + 4 * SPR_COUNT
        self.assertLess(total, MAX_TOTAL_BYTES)
        m = re.search(r";\s*total\s*:\s*(\d+)", self.asm_text)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), total)


class TestHeader(GeneratorRun):

    def test_defines_match_bosco_h(self):
        bosco = (PROJECT / "bosco.h").read_text()
        for name, value in DESIGN_IDS.items():
            self.assertRegex(self.h_text, rf"#define {name} {value}\b", name)
            self.assertRegex(bosco, rf"#define {name} {value}\b", name)
        self.assertIn("#ifndef ASSETS_H", self.h_text)

    @unittest.skipUnless(shutil.which("cc65"), "cc65 not installed")
    def test_both_headers_compile_together(self):
        src = self.tmp / "both.c"
        src.write_text('#include "bosco.h"\n#include "assets.h"\n'
                       "const unsigned char *p(void) { return spr_width + SPR_BIGEXPL_0; }\n"
                       "unsigned char n(void) { return SPR_COUNT + SPR_POD_HIT; }\n")
        r = subprocess.run(["cc65", "-t", "none", "--cpu", "65c02", "--standard", "c99",
                            "-Oirs", "-Werror", "-I", str(PROJECT), "-I", str(self.build),
                            "-o", str(self.tmp / "both.s"), str(src)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestAssemble(GeneratorRun):

    @unittest.skipUnless(shutil.which("ca65") and shutil.which("ld65"), "cc65 tools missing")
    def test_assemble_and_link_layout(self):
        obj = self.tmp / "assets.o"
        r = subprocess.run(["ca65", "-t", "none", "--cpu", "65c02",
                            str(self.build / "assets.s"), "-o", str(obj)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = self.tmp / "raw.cfg"
        cfg.write_text("MEMORY { ROM: start = $4000, size = $8000, file = %O; }\n"
                       "SEGMENTS { RODATA: load = ROM, type = ro; }\n")
        binary = self.tmp / "assets.bin"
        r = subprocess.run(["ld65", "-C", str(cfg), "-o", str(binary), str(obj)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = binary.read_bytes()
        # rebuild the expected image: variants in id order, then the tables
        expected = bytearray()
        addr = {}
        for i in range(SPR_COUNT):
            for v in ("even", "odd"):
                addr[f"spr_{i:02d}_{v}"] = 0x4000 + len(expected)
                expected += self.blocks[f"spr_{i:02d}_{v}"]
        for label in ("_spr_even_lo", "_spr_even_hi", "_spr_odd_lo", "_spr_odd_hi"):
            kind, names = self.tables[label]
            for n in names:
                a = addr[n]
                expected.append(a & 0xFF if kind == "lobytes" else a >> 8)
        for label in ("_spr_width", "_spr_height", "_font8", "_palette0"):
            expected += self.blocks[label]
        self.assertEqual(len(data), len(expected))
        self.assertEqual(data, bytes(expected))


class TestErrors(unittest.TestCase):

    def test_wrong_size_and_missing_sprite_are_rejected(self):
        tmp = Path(tempfile.mkdtemp(prefix="bosco_bad_"))
        try:
            shutil.copy(ASSETS / "font8.txt", tmp / "font8.txt")
            text = (ASSETS / "sprites.txt").read_text()
            (tmp / "sprites.txt").write_text(text.replace("sprite POD 16 16", "sprite POD 16 15", 1))
            with self.assertRaises(gen_assets.AssetError):
                gen_assets.build_all(tmp)
            (tmp / "sprites.txt").write_text(text.replace("sprite POD 16 16", "sprite PODX 16 16", 1))
            with self.assertRaises(gen_assets.AssetError):
                gen_assets.build_all(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_encode_decode_roundtrip(self):
        grid = [[None, 3, None], [None, None, None], [1, 2, 3]]
        even, holes = gen_assets.encode_variant(grid, 0)
        self.assertEqual(list(even[:2]), [3, 2])
        self.assertEqual(holes, 0)
        dec, used = gen_assets.decode_variant(even)
        self.assertEqual(used, len(even))
        self.assertEqual(dec[0][:2], [0, 3])
        self.assertEqual(dec[1], [None] * 4)
        self.assertEqual(dec[2][:3], [1, 2, 3])
        odd, _ = gen_assets.encode_variant(grid, 1)
        self.assertEqual(list(odd[:2]), [3, 2])
        # shifted right: the 3 lands at x=2, byte 1, high nibble
        self.assertEqual(list(odd[2:5]), [1, 1, 0x30])


if __name__ == "__main__":
    unittest.main(verbosity=2)
