#!/usr/bin/env python3
"""Check tools/gen_assets.py output against docs/DESIGN.md sections 2, 3, 4 and 9.

Run:  python3 tests/test_assets.py        (from the project directory)

The test runs the generator into a temporary build directory, parses the
generated assets.s and BOSCO.SPR back into bytes with its own small
parser, decodes every sprite variant and compares it with an independent
reading of the text art. If ca65/ld65/cc65 are installed it also assembles
and links assets.s and compiles a C file that includes both bosco.h and
build/assets.h.
"""

from __future__ import annotations

import re
import shutil
import struct
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
POD_SIZES = (16, 24, 24, 24, 24, 16)
DESIGN_SPRITES = (
    [("SHIP_%d" % i, 16, 16) for i in range(8)]
    + [("ITYPE_%d" % i, 16, 16) for i in range(8)]
    + [("PTYPE_%d" % i, 16, 16) for i in range(8)]
    + [("ETYPE_%d" % i, 16, 16) for i in range(8)]
    + [("SPY_%d" % i, 16, 16) for i in range(8)]
    + [("MINE", 16, 16)]
    + [("ASTEROID_%d" % i, 16, 16) for i in range(3)]
    + [("EXPL_%d" % i, 16, 16) for i in range(3)]
    + [("BIGEXPL_%d" % i, 32, 32) for i in range(3)]
    + [("CORE_V", 32, 40), ("CORE_H", 40, 32)]
    + [("POD_V%d" % i, s, s) for i, s in enumerate(POD_SIZES)]
    + [("PODDEAD_V%d" % i, s, s) for i, s in enumerate(POD_SIZES)]
    + [("POD_H%d" % i, s, s) for i, s in enumerate(POD_SIZES)]
    + [("PODDEAD_H%d" % i, s, s) for i, s in enumerate(POD_SIZES)]
    + [("SHOT_PLAYER", 2, 4), ("SHOT_PLAYER_H", 4, 2)]
    + [("SHOT_PLAYER_D1", 4, 4), ("SHOT_PLAYER_D2", 4, 4)]
    + [("SHOT_ENEMY", 4, 4)]
    + [("MISSILE_%d" % i, 4, 4) for i in range(2)]
    + [("ICON_SHIP", 16, 16), ("ICON_BASE", 8, 8), ("CAPTION_COND", 62, 8)]
)
SPR_COUNT = len(DESIGN_SPRITES)
DESIGN_IDS = {
    "SPR_SHIP_0": 0, "SPR_ITYPE_0": 8, "SPR_PTYPE_0": 16, "SPR_ETYPE_0": 24,
    "SPR_SPY_0": 32, "SPR_MINE": 40, "SPR_ASTEROID_0": 41, "SPR_EXPL_0": 44,
    "SPR_BIGEXPL_0": 47, "SPR_CORE_V": 50, "SPR_CORE_H": 51, "SPR_POD_V0": 52,
    "SPR_PODDEAD_V0": 58, "SPR_POD_H0": 64, "SPR_PODDEAD_H0": 70,
    "SPR_SHOT_PLAYER": 76, "SPR_SHOT_PLAYER_H": 77, "SPR_SHOT_PLAYER_D1": 78,
    "SPR_SHOT_PLAYER_D2": 79, "SPR_SHOT_ENEMY": 80, "SPR_MISSILE_0": 81,
    "SPR_ICON_SHIP": 83, "SPR_ICON_BASE": 84, "SPR_CAPTION_COND": 85, "SPR_COUNT": 86,
}
# docs/DESIGN.md section 3: the arcade colour PROM, as (R, G, B) 4-bit values.
DESIGN_PALETTE = [
    (0, 0, 0), (0xD, 0xD, 0xD), (0xF, 0, 0), (0xF, 6, 0), (0xF, 0xF, 0),
    (9, 0, 0xD), (0xF, 6, 0xD), (0, 0xF, 0xD), (0, 6, 0xD), (6, 2, 0),
    (0, 0xB, 0), (6, 0, 0xD), (2, 4, 4), (0xD, 9, 0), (0xB, 2, 0), (9, 9, 9),
]
# colour indices by name (DESIGN.md section 3)
BLACK, WHITE, RED, ORANGE, YELLOW, PURPLE, PINK, CYAN = range(8)
BLUE, BROWN, GREEN, VIOLET, DTEAL, GOLD, DRED, GRAY = range(8, 16)
EMPTY = gen_assets.EMPTY_ROW_BYTES
RUN_MORE = 0x80
SPLIT_GAP = 2
# docs/DESIGN.md section 2: the auxiliary language card regions
DESIGN_REGIONS = [(0xD000, 0x2FF0, 4), (0xD000, 0x1000, 6)]
MAIN_ONLY = {"ICON_SHIP", "ICON_BASE", "CAPTION_COND"}


# ---------------------------------------------------------------- helpers

def parse_asm(text: str):
    """Return (blocks, tables, consts, order): label -> bytes for .byte
    blocks, label -> (kind, names) for .lobytes/.hibytes tables, symbol ->
    value for 'name = $XXXX' lines, labels in file order."""
    blocks: dict[str, bytearray] = {}
    tables: dict[str, tuple[str, list[str]]] = {}
    consts: dict[str, int] = {}
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
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\$([0-9A-Fa-f]+)$", line.strip())
        if m:
            consts[m.group(1)] = int(m.group(2), 16)
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
    return blocks, tables, consts, order


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


def own_pad(grid, w, h, ox=None, oy=None):
    gh, gw = len(grid), len(grid[0])
    if ox is None:
        ox = (w - gw) // 2
    if oy is None:
        oy = (h - gh) // 2
    out = [[None] * w for _ in range(h)]
    for y, row in enumerate(grid):
        for x, p in enumerate(row):
            out[oy + y][ox + x] = p
    return out


def own_parse_sprites(path: Path):
    sizes = {n: (w, h) for n, w, h in DESIGN_SPRITES}
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
            if w[3] == "pad":
                tw, th = sizes[w[1]]
                if len(w) == 7:
                    grids[w[1]] = own_pad(grids[w[4]], tw, th, int(w[5]), int(w[6]))
                else:
                    grids[w[1]] = own_pad(grids[w[4]], tw, th)
            else:
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


def own_decode(data: bytes):
    """Independent reading of a variant: (height, width_bytes, rows, used) with a
    row as a list of pixel values (None = not drawn, 0..15 drawn)."""
    h, wb = data[0], data[1]
    pos = 2
    rows = []
    for _ in range(h):
        row = [None] * (wb * 2)
        while True:
            off, ln = data[pos], data[pos + 1]
            pos += 2
            if off == 0xFF:
                assert ln == 0
                break
            more = off & RUN_MORE
            off &= 0x7F
            for k in range(ln):
                b = data[pos + k]
                row[(off + k) * 2] = b >> 4
                row[(off + k) * 2 + 1] = b & 15
            pos += ln
            if not more:
                break
        rows.append(row)
    return h, wb, rows, pos


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
        cls.spr = (cls.build / "BOSCO.SPR").read_bytes()
        cls.blocks, cls.tables, cls.consts, cls.order = parse_asm(cls.asm_text)
        cls.grids = own_parse_sprites(ASSETS / "sprites.txt")
        cls.font = own_parse_font(ASSETS / "font8.txt")
        cls.regions = cls.parse_spr(cls.spr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def parse_spr(data: bytes):
        """Own reading of BOSCO.SPR: [(address, bank, blob)]."""
        assert data[:4] == b"BSPR"
        count = data[4]
        table = [struct.unpack_from("<HHB", data, 5 + 5 * i) for i in range(count)]
        pos = 5 + 5 * count
        out = []
        for addr, length, bank in table:
            out.append((addr, bank, data[pos:pos + length]))
            pos += length
        assert pos == len(data)
        return out

    def bank_of(self, i):
        return self.blocks["_spr_bank"][i]

    def variant(self, i, name):
        """Bytes of variant `name` of id i, from RODATA or from the card."""
        label = f"spr_{i:02d}_{name}"
        if label in self.blocks:
            return bytes(self.blocks[label])
        addr = self.consts[label]
        bank = self.bank_of(i)
        for base, rbank, blob in self.regions:
            if rbank == bank and base <= addr < base + len(blob):
                _h, _wb, _rows, used = own_decode(blob[addr - base:])
                return bytes(blob[addr - base:addr - base + used])
        raise AssertionError(f"{label} at ${addr:04X} bank {bank} is in no region")


class TestSpriteFormat(GeneratorRun):

    def test_all_sprites_present_with_design_sizes(self):
        self.assertEqual(SPR_COUNT, 86)
        self.assertEqual(gen_assets.SPRITES, DESIGN_SPRITES)
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
        """Decode the run records by hand and compare with the source art."""
        h, wb, rows, used = own_decode(data)
        self.assertEqual(used, len(data), f"{name}: trailing bytes")
        w = len(grid[0])
        for y in range(h):
            row = grid[y]
            drawn = rows[y]
            for x in range(wb * 2):
                src = row[x - shift] if 0 <= x - shift < w else None
                if src is not None:
                    self.assertEqual(drawn[x], src, f"{name} row {y} x {x} shift {shift}")
                else:
                    self.assertIn(drawn[x], (None, 0), f"{name} row {y} x {x}: not black")
            # a run never starts or ends on a transparent byte
            opaque_bytes = [k for k in range(wb) if drawn[2 * k] is not None]
            for k in opaque_bytes:
                pair = (row[2 * k - shift] if 0 <= 2 * k - shift < w else None,
                        row[2 * k + 1 - shift] if 0 <= 2 * k + 1 - shift < w else None)
                if pair == (None, None):
                    # a black byte inside a run: the gap around it is short
                    left = [j for j in opaque_bytes if j < k and any(
                        p is not None for p in (row[2 * j - shift] if 0 <= 2 * j - shift < w else None,
                                                row[2 * j + 1 - shift] if 0 <= 2 * j + 1 - shift < w else None))]
                    self.assertTrue(left, f"{name} row {y}: run starts on a transparent byte")

    def test_even_and_odd_variants_match_the_art(self):
        for i, (name, _w, _h) in enumerate(DESIGN_SPRITES):
            self.check_variant(name, self.grids[name], self.variant(i, "even"), 0)
            self.check_variant(name, self.grids[name], self.variant(i, "odd"), 1)

    def test_wide_gaps_become_separate_runs(self):
        # 16 px row: 2 opaque, 8 transparent (4 bytes), 6 opaque -> two runs
        grid = [[1, 1] + [None] * 8 + [2] * 6]
        even, holes = gen_assets.encode_variant(grid, 0)
        self.assertEqual(holes, 0)
        self.assertEqual(list(even), [1, 8, 0 | RUN_MORE, 1, 0x11, 5, 3, 0x22, 0x22, 0x22])
        _h, _wb, rows, used = own_decode(even)
        self.assertEqual(used, len(even))
        self.assertEqual(rows[0], [1, 1] + [None] * 8 + [2] * 6)
        self.assertEqual(gen_assets.decode_variant(even)[0], rows)
        # a gap of one byte (2 px) is filled with black inside one run
        grid = [[1, 1, None, None, 2, 2]]
        even, holes = gen_assets.encode_variant(grid, 0)
        self.assertEqual(holes, 2)
        self.assertEqual(list(even), [1, 3, 0, 3, 0x11, 0x00, 0x22])
        # the odd variant shifts the gap onto other byte boundaries
        # (6 px wide -> 4 bytes shifted; the gap becomes bytes 1 and 2)
        odd, _ = gen_assets.encode_variant([[1] + [None] * 4 + [2]], 1)
        self.assertEqual(list(odd), [1, 4, 0 | RUN_MORE, 1, 0x01, 3, 1, 0x20])

    def test_heading_sprites_are_rotations(self):
        """The drawn art turns three headings into eight: E rotated 90 is S,
        NE rotated 90 is SE, and the 12x12 fighters are padded to 16x16."""
        g = self.grids
        for base in ("SHIP", "ITYPE", "PTYPE", "SPY"):
            self.assertEqual(g[f"{base}_3"], own_grid_transform(g[f"{base}_1"], "rot90"), base)
            self.assertEqual(g[f"{base}_5"], own_grid_transform(g[f"{base}_1"], "rot180"), base)
            self.assertEqual(g[f"{base}_7"], own_grid_transform(g[f"{base}_1"], "rot270"), base)
        for base in ("SHIP", "ITYPE", "PTYPE"):
            self.assertEqual(g[f"{base}_4"], own_grid_transform(g[f"{base}_2"], "rot90"), base)
            self.assertEqual(g[f"{base}_6"], own_grid_transform(g[f"{base}_2"], "rot180"), base)
        for base in ("ITYPE", "PTYPE", "SPY"):
            self.assertEqual(g[f"{base}_0"], own_pad(g[f"_{base}_0"], 16, 16), base)
        self.assertEqual(g["ETYPE_2"], own_grid_transform(g["ETYPE_0"], "rot90"))
        self.assertEqual(g["ICON_SHIP"], g["SHIP_0"])
        # the generator agrees with this reader on every listed sprite
        gen_grids = gen_assets.parse_sprites(ASSETS / "sprites.txt")
        for name, _w, _h in DESIGN_SPRITES:
            self.assertEqual(gen_grids[name], self.grids[name], name)
        # rot90 is clockwise: the top-left pixel moves to the top-right.
        t = [[1, None], [None, None]]
        self.assertEqual(gen_assets.transform(t, "rot90"), [[None, 1], [None, None]])
        self.assertEqual(gen_assets.transform(t, "rot180"), [[None, None], [None, 1]])
        self.assertEqual(gen_assets.transform(t, "rot270"), [[None, None], [1, None]])
        self.assertEqual(gen_assets.pad_grid(t, 4, 3, 1, 0)[0], [None, 1, None, None])

    def test_art_uses_the_arcade_palette(self):
        g = self.grids

        def colors(name):
            return {p for row in g[name] for p in row if p is not None}

        self.assertTrue({WHITE, CYAN} <= colors("SHIP_0"))       # white + cyan cockpit
        self.assertIn(CYAN, colors("ITYPE_0"))
        self.assertIn(BLUE, colors("PTYPE_0"))
        self.assertIn(PURPLE, colors("ETYPE_0"))
        self.assertTrue({YELLOW, GREEN} <= colors("SPY_0"))
        self.assertTrue({PURPLE, PINK} <= colors("MINE"))
        self.assertTrue({DTEAL, BROWN} <= colors("ASTEROID_0"))
        self.assertEqual(g["ASTEROID_2"], own_grid_transform(g["ASTEROID_0"], "fliph"))
        for name in ("POD_V0", "POD_H5", "POD_V1", "POD_H3"):
            self.assertTrue({GREEN, DTEAL} <= colors(name), name)
        for name in ("CORE_V", "CORE_H"):
            self.assertTrue({ORANGE, YELLOW, GREEN} <= colors(name), name)
        for name in ("PODDEAD_V0", "PODDEAD_H0", "PODDEAD_V2", "PODDEAD_H4"):
            self.assertTrue({DRED, GRAY} <= colors(name), name)
            self.assertLess(len([p for row in g[name] for p in row if p is not None]),
                            len([p for row in g[name.replace("DEAD", "")] for p in row if p is not None]),
                            f"{name}: rubble is smaller than the pod")
        self.assertEqual(colors("SHOT_PLAYER"), {WHITE, PINK})
        self.assertEqual(colors("SHOT_PLAYER_H"), colors("SHOT_PLAYER"))
        self.assertEqual(g["SHOT_PLAYER_D2"], own_grid_transform(g["SHOT_PLAYER_D1"], "fliph"))
        self.assertIn(YELLOW, colors("SHOT_ENEMY"))
        self.assertEqual(colors("MISSILE_0"), {RED})
        self.assertLess(sum(p is not None for row in g["MISSILE_1"] for p in row),
                        sum(p is not None for row in g["MISSILE_0"] for p in row))
        for i in range(3):
            self.assertTrue(colors(f"EXPL_{i}"), f"EXPL_{i} is empty")
            self.assertTrue(colors(f"BIGEXPL_{i}"), f"BIGEXPL_{i} is empty")
        self.assertTrue({GREEN, ORANGE} <= colors("ICON_BASE"))
        self.assertEqual(colors("CAPTION_COND"), {GRAY})
        self.assertTrue(all(p is None for p in g["CAPTION_COND"][7]), "caption: last row blank")


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
        banks = list(self.blocks["_spr_bank"])
        self.assertEqual(len(banks), SPR_COUNT)
        self.assertTrue(set(banks) <= {0, 4, 6}, banks)
        for i, (name, _w, _h) in enumerate(DESIGN_SPRITES):
            if name in MAIN_ONLY:
                self.assertEqual(banks[i], 0, f"{name} must stay in main memory")
                self.assertIn(f"spr_{i:02d}_even", self.blocks)
            elif banks[i] == 0:
                self.assertIn(f"spr_{i:02d}_even", self.blocks, name)
                self.assertIn(f"spr_{i:02d}_odd", self.blocks, name)
            else:
                self.assertIn(f"spr_{i:02d}_even", self.consts, name)
                self.assertIn(f"spr_{i:02d}_odd", self.consts, name)
                self.assertNotIn(f"spr_{i:02d}_even", self.blocks, name)

    def test_card_regions_and_sprite_file(self):
        self.assertLessEqual(len(self.regions), len(DESIGN_REGIONS))
        used = {bank: bytearray() for _a, _l, bank in DESIGN_REGIONS}
        sizes = {bank: (addr, size) for addr, size, bank in DESIGN_REGIONS}
        for addr, bank, blob in self.regions:
            self.assertIn(bank, sizes)
            self.assertEqual(addr, sizes[bank][0])
            self.assertLessEqual(len(blob), sizes[bank][1])
            used[bank] = blob
        # every card sprite lies inside its region, variants back to back in
        # id order, and the regions hold nothing else
        expected = {bank: bytearray() for bank in used}
        for i, (name, _w, _h) in enumerate(DESIGN_SPRITES):
            bank = self.bank_of(i)
            if bank == 0:
                continue
            base = sizes[bank][0]
            self.assertEqual(self.consts[f"spr_{i:02d}_even"], base + len(expected[bank]), name)
            expected[bank] += self.variant(i, "even")
            self.assertEqual(self.consts[f"spr_{i:02d}_odd"], base + len(expected[bank]), name)
            expected[bank] += self.variant(i, "odd")
        for bank in used:
            self.assertEqual(bytes(used[bank]), bytes(expected[bank]), f"bank {bank}")
        self.assertGreater(sum(len(b) for b in used.values()), 8000, "most sprites are in the card")
        # gen_assets reads its own file the same way
        parsed = gen_assets.parse_spr_file(self.spr)
        self.assertEqual([(a, b, bytes(blob)) for a, b, blob in self.regions],
                         [(a, b, blob) for a, _l, b, blob in parsed])
        # the header totals name the same numbers
        m = re.search(r";\s*in BOSCO.SPR\s*:\s*(\d+)", self.asm_text)
        self.assertEqual(int(m.group(1)), sum(len(b) for _a, _b, b in self.regions))

    def test_exports_and_segment(self):
        for sym in ("_spr_even_lo", "_spr_even_hi", "_spr_odd_lo", "_spr_odd_hi",
                    "_spr_width", "_spr_height", "_spr_bank", "_font8", "_palette0"):
            self.assertRegex(self.asm_text, r"\.export[^\n]*\b" + sym + r"\b")
            self.assertIn(sym, self.order)
        self.assertIn('.segment "RODATA"', self.asm_text)
        self.assertIsNotNone(re.search(r"^;.*RODATA total\s*:\s*\d+", self.asm_text, re.M))

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
        self.assertEqual([(r, g, b) for _i, _n, r, g, b in gen_assets.PALETTE], DESIGN_PALETTE)

    def test_rodata_total(self):
        total = sum(len(v) for v in self.blocks.values()) + 4 * SPR_COUNT
        m = re.search(r";\s*RODATA total\s*:\s*(\d+)", self.asm_text)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), total)
        self.assertLess(total, 12 * 1024, "RODATA sprites must leave room for the code")


class TestHeader(GeneratorRun):

    def test_defines_match_bosco_h(self):
        bosco = (PROJECT / "bosco.h").read_text()
        for name, value in DESIGN_IDS.items():
            self.assertRegex(self.h_text, rf"#define {name} {value}\b", name)
            self.assertRegex(bosco, rf"#define {name} {value}\b", name)
        self.assertIn("#ifndef ASSETS_H", self.h_text)
        self.assertIn("extern const unsigned char spr_bank[SPR_COUNT];", self.h_text)

    @unittest.skipUnless(shutil.which("cc65"), "cc65 not installed")
    def test_both_headers_compile_together(self):
        src = self.tmp / "both.c"
        src.write_text('#include "bosco.h"\n#include "assets.h"\n'
                       "const unsigned char *p(void) { return spr_width + SPR_BIGEXPL_0; }\n"
                       "unsigned char n(void) { return SPR_COUNT + SPR_PODDEAD_V0; }\n")
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
        # rebuild the expected image: main-memory variants in id order, then
        # the tables (card sprites contribute their $D000+ addresses)
        expected = bytearray()
        addr = dict(self.consts)
        for i in range(SPR_COUNT):
            for v in ("even", "odd"):
                label = f"spr_{i:02d}_{v}"
                if label in self.blocks:
                    addr[label] = 0x4000 + len(expected)
                    expected += self.blocks[label]
        for label in ("_spr_even_lo", "_spr_even_hi", "_spr_odd_lo", "_spr_odd_hi"):
            kind, names = self.tables[label]
            for n in names:
                a = addr[n]
                expected.append(a & 0xFF if kind == "lobytes" else a >> 8)
        for label in ("_spr_width", "_spr_height", "_spr_bank", "_font8", "_palette0"):
            expected += self.blocks[label]
        self.assertEqual(len(data), len(expected))
        self.assertEqual(data, bytes(expected))


class TestErrors(unittest.TestCase):

    def test_wrong_size_and_missing_sprite_are_rejected(self):
        tmp = Path(tempfile.mkdtemp(prefix="bosco_bad_"))
        try:
            shutil.copy(ASSETS / "font8.txt", tmp / "font8.txt")
            text = (ASSETS / "sprites.txt").read_text()
            self.assertIn("sprite ASTEROID_0 16 16", text)
            (tmp / "sprites.txt").write_text(text.replace("sprite ASTEROID_0 16 16",
                                                          "sprite ASTEROID_0 16 15", 1))
            with self.assertRaises(gen_assets.AssetError):
                gen_assets.build_all(tmp)
            (tmp / "sprites.txt").write_text(text.replace("sprite ASTEROID_0 16 16",
                                                          "sprite ASTEROIDX 16 16", 1))
            with self.assertRaises(gen_assets.AssetError):
                gen_assets.build_all(tmp)
            # a helper that no listed sprite uses is fine; a pad that does not fit is not
            (tmp / "sprites.txt").write_text(text + "\nsprite _SPARE 2 2\n..\n..\n")
            gen_assets.build_all(tmp)
            (tmp / "sprites.txt").write_text(text + "\nderive MINE = pad BIGEXPL_0\n")
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

    def test_placement_first_fit_and_main_only(self):
        encoded = [dict(name="A", even=b"\1" * 10, odd=b"\1" * 10),
                   dict(name="ICON_SHIP", even=b"\2" * 4, odd=b"\2" * 4),
                   dict(name="B", even=b"\3" * 30, odd=b"\3" * 30),
                   dict(name="C", even=b"\4" * 10, odd=b"\4" * 10)]
        regions = (("R1", 4, 0xD000, 32), ("R2", 6, 0xD000, 100))
        blobs = gen_assets.place_sprites(encoded, regions)
        # A fits R1 (20 of 32), the icon stays in main memory, B (60) goes to
        # R2, C (20) no longer fits R1 and follows B in R2
        self.assertEqual([e["bank"] for e in encoded], [4, 0, 6, 6])
        self.assertEqual(encoded[0]["even_addr"], 0xD000)
        self.assertEqual(encoded[0]["odd_addr"], 0xD00A)
        self.assertIsNone(encoded[1]["even_addr"])
        self.assertEqual(encoded[3]["even_addr"], 0xD000 + 60)
        self.assertEqual(encoded[3]["odd_addr"], 0xD000 + 70)
        self.assertEqual(len(blobs[0]), 20)
        self.assertEqual(len(blobs[1]), 80)
        image = gen_assets.spr_file_bytes(blobs, regions)
        self.assertEqual(image[:5], b"BSPR\x02")
        parsed = gen_assets.parse_spr_file(image)
        self.assertEqual([(a, l, b) for a, l, b, _ in parsed], [(0xD000, 20, 4), (0xD000, 80, 6)])
        self.assertEqual(parsed[0][3], bytes(blobs[0]))
        self.assertEqual(parsed[1][3], bytes(blobs[1]))
        # an empty region is left out of the file
        blobs = gen_assets.place_sprites(encoded[:1], regions)
        image = gen_assets.spr_file_bytes(blobs, regions)
        self.assertEqual(image[4], 1)
        self.assertEqual(len(gen_assets.parse_spr_file(image)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
