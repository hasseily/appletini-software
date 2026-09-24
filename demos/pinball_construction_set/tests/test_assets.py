#!/usr/bin/env python3
"""Check tools/gen_assets.py against docs/DESIGN.md sections 3, 4, 6 and 7.

Run:  python3 tests/test_assets.py        (from the project directory)

The generator is run on the fixture in tests/assets_test/ (a deliberately
incomplete set of art files, a glyph override file and a parts.json subset)
into a temporary build directory. The generated assets.s, assets.inc and
PCS.SPR are parsed back with the test's own small parser, every variant is
decoded with an independent reader and compared with the art, and the ids,
tables, regions, font and palette are checked against the design. With
ca65/ld65 present, assets.s is assembled and linked with a raw config and
the binary compared byte for byte; with py65, tests/assets_test_driver.s
walks the directory in a 65C02 with the language card filled from PCS.SPR,
the way the loader and the renderer will. A last group runs the generator
on the real assets/ and build/parts.json when they exist.
"""

from __future__ import annotations

import json
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
TESTS = PROJECT / "tests"
FIXTURE = TESTS / "assets_test"
GEN = TOOLS / "gen_assets.py"
BASELINE_CDRAW = PROJECT / "build" / "baseline" / "CDRAW.s"
UPSTREAM_CDRAW = Path("/home/user/billbudge/pcs_appleii/source_disc1/CDRAW.S")
REAL_PARTS = PROJECT / "build" / "parts.json"
REAL_ASSETS = PROJECT / "assets"

sys.path.insert(0, str(TOOLS))
import gen_assets  # noqa: E402

try:
    from py65.devices.mpu65c02 import MPU
except ImportError:      # pragma: no cover
    MPU = None

# docs/DESIGN.md section 3, as (R, G, B) 4-bit values
DESIGN_PALETTE = [
    (0, 0, 0), (3, 3, 3), (7, 7, 7), (0xB, 0xB, 0xB), (0xF, 0xF, 0xF),
    (9, 0, 0), (0xF, 3, 3), (0xF, 8, 0), (0xF, 0xF, 3), (0, 6, 3),
    (3, 0xC, 3), (1, 2, 4), (3, 9, 0xF), (6, 0xE, 0xF), (9, 3, 0xE), (9, 6, 3),
]
# build/art_format.md pixel letters in index order 1..15
PIXEL_LETTERS = "dglWrROYeGnBCVb"
EMPTY = (0xFF, 0x00)
RUN_MORE = 0x80
SPLIT_GAP = 2
# docs/DESIGN.md sections 4 and 7: the auxiliary language card regions
DESIGN_REGIONS = [(0xD000, 0x2FF0, 4), (0xD000, 0x1000, 6), (0xA000, 0x2000, 8)]
PLACEHOLDER = {14, 4}

# the fixture's kinds (tests/assets_test/parts.json) in kit order
FIXTURE_KINDS = [("POLY", 0), ("LAUNCHER", 6), ("LEFTFLIPPER", 8), ("RIGHTFLIPPER", 8),
                 ("BALL", 1), ("KICK1", 3), ("TARG1", 2), ("POLY1", 0), ("CATCH2", 5)]
FIXTURE_BASES = {"LAUNCHER": "launcher", "LEFTFLIPPER": "lflip", "RIGHTFLIPPER": "rflip",
                 "BALL": "ball", "KICK1": "kick1", "TARG1": "targ1", "CATCH2": "catch2"}
FIXTURE_BOX = {"LAUNCHER": (7, 12, 0), "LEFTFLIPPER": (20, 16, 4), "RIGHTFLIPPER": (20, 16, 4),
               "BALL": (7, 5, 0), "KICK1": (7, 16, 0), "TARG1": (7, 3, 0), "CATCH2": (14, 9, 0)}
FIXTURE_DRAWN = {"launcher_0", "launcher_1", "lflip_0", "lflip_1", "lflip_2", "rflip_0",
                 "rflip_1", "rflip_2", "ball_0", "kick1_0", "kick1_1", "kick1_2", "targ1_0",
                 "targ1_1", "dropx_0", "dropy_0", "cur_hand", "tool_hand", "swatch_R",
                 "caret", "spare_rot", "spare_copy", "wide_thing"}
FIXTURE_EXTRA = ["spare_copy", "spare_rot", "wide_thing"]
UI_NAMES = [name for name, _up, _use in gen_assets.UI_SPRITES]
AUX_NAMES = [name for name, _w, _h, _n in gen_assets.AUX_SPRITES]

# the upstream 'A' (CDRAW.S FONT glyph 10: 0E 1B 1B 1F 1B 1B 1B) with bit 7 leftmost
UPSTREAM_A = [0x70, 0xD8, 0xD8, 0xF8, 0xD8, 0xD8, 0xD8]
UPSTREAM_ADV = ([6, 5, 6, 6, 6, 6, 6, 6, 6, 6]                       # 0-9
                + [6, 6, 6, 6, 6, 6, 6, 6, 5, 7, 7, 6, 8]            # A-M
                + [7, 6, 6, 6, 6, 6, 7, 6, 6, 8, 7, 7, 6]            # N-Z
                + [5])                                               # space

STEP_LIMIT = 100_000


# ---------------------------------------------------------------- helpers

def parse_asm(text: str):
    """Return (blocks, words, consts, order): label -> bytes for .byte
    blocks, label -> names for .word lists, symbol -> value for 'name = N'
    lines ($hex or decimal), labels in file order."""
    blocks: dict[str, bytearray] = {}
    words: dict[str, list[str]] = {}
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
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\$[0-9A-Fa-f]+|\d+)$", line.strip())
        if m:
            v = m.group(2)
            consts[m.group(1)] = int(v[1:], 16) if v.startswith("$") else int(v)
            continue
        s = line.strip()
        if s.startswith(".byte"):
            vals = [int(v.strip()[1:], 16) for v in s[5:].split(",")]
            blocks.setdefault(label, bytearray()).extend(vals)
        elif s.startswith(".word"):
            words.setdefault(label, []).extend(n.strip() for n in s[5:].split(","))
    return blocks, words, consts, order


def parse_inc(text: str) -> dict[str, int]:
    consts = {}
    for raw in text.split("\n"):
        line = raw.split(";", 1)[0].strip()
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\d+)$", line)
        if m:
            consts[m.group(1)] = int(m.group(2))
    return consts


def own_transform(grid, op):
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


def own_parse_art(paths):
    """Independent reading of the art files, in the given order."""
    letters = {".": None}
    for k, c in enumerate(PIXEL_LETTERS, start=1):
        letters[c] = k
    grids = {}
    for path in paths:
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
                assert all(len(r) == width for r in rows), name
                grids[name] = [[letters[c] for c in r] for r in rows]
            elif w[0] == "derive":
                grids[w[1]] = own_transform(grids[w[4]], w[3])
    return grids


def own_parse_font(path: Path):
    """code -> (rows, advance or None)."""
    glyphs = {}
    lines = path.read_text().split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        i += 1
        if s.startswith("glyph"):
            w = s.split()
            code = w[1]
            if code.lower() == "space":
                code = 36
            elif len(code) == 1 and code.isalpha():
                code = 10 + ord(code.upper()) - 65
            else:
                code = int(code)
            rows = lines[i:i + 7]
            i += 7
            glyphs[code] = ([int(r.ljust(8, ".").replace("#", "1").replace(".", "0"), 2)
                             for r in rows], int(w[3]) if len(w) == 4 else None)
    return glyphs


def own_decode(data: bytes):
    """Independent reading of a variant: (height, width_bytes, rows, used)
    with a row as a list of pixel values (None = outside every run)."""
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


def run_generator(assets: Path, parts: Path, build: Path, *extra: str):
    return subprocess.run([sys.executable, str(GEN), "--assets", str(assets), "--parts",
                           str(parts), "--build", str(build), "--quiet", *extra],
                          capture_output=True, text=True)


# ---------------------------------------------------------------- base

class GeneratorRun(unittest.TestCase):
    """Run the generator on the fixture once for the whole test module."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pcs_assets_"))
        cls.build = cls.tmp / "build"
        r = run_generator(FIXTURE, FIXTURE / "parts.json", cls.build)
        if r.returncode != 0:
            raise RuntimeError("gen_assets.py failed:\n" + r.stdout + r.stderr)
        cls.stderr = r.stderr
        cls.asm_text = (cls.build / "assets.s").read_text()
        cls.inc_text = (cls.build / "assets.inc").read_text()
        cls.spr = (cls.build / "PCS.SPR").read_bytes()
        cls.blocks, cls.words, cls.consts, cls.order = parse_asm(cls.asm_text)
        cls.inc = parse_inc(cls.inc_text)
        cls.grids = own_parse_art([FIXTURE / "sprites.txt", FIXTURE / "z_more.txt"])
        cls.font_override = own_parse_font(FIXTURE / "font.txt")
        cls.regions = cls.parse_spr(cls.spr)
        cls.count = cls.inc["SPR_COUNT"]
        # id -> name, from the directory's labels (spr_<name>_even)
        cls.names = [w[len("spr_"):-len("_even")] for w in cls.words["spr_dir"][0::2]]
        assert len(cls.names) == cls.count, (cls.names, cls.count)
        for i, name in enumerate(cls.names):
            assert cls.inc[f"SPR_{name.upper()}"] == i, name

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def parse_spr(data: bytes):
        """Own reading of PCS.SPR: [(address, bank, blob)]."""
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
        return self.blocks["spr_bank"][i]

    def variant(self, i, which):
        """Bytes of variant `which` of id i, from RODATA or from the card (an
        even-only sprite serves its even variant for both phases)."""
        if self.names[i] in gen_assets.EVEN_ONLY:
            which = "even"
        label = f"spr_{self.names[i]}_{which}"
        if label in self.blocks:
            return bytes(self.blocks[label])
        addr = self.consts[label]
        bank = self.bank_of(i)
        for base, rbank, blob in self.regions:
            if rbank == bank and base <= addr < base + len(blob):
                if self.names[i] in gen_assets.RAW_SPRITES:
                    used = self.blocks["spr_h"][i] * ((self.blocks["spr_w"][i] + 1) // 2)
                else:
                    _h, _wb, _rows, used = own_decode(blob[addr - base:])
                return bytes(blob[addr - base:addr - base + used])
        raise AssertionError(f"{label} at ${addr:04X} bank {bank} is in no region")

    def expected_grid(self, i):
        name = self.names[i]
        if name in self.grids:
            return self.grids[name]
        return None


# ---------------------------------------------------------------- parsing

class TestParsing(unittest.TestCase):

    def test_pixel_letters_follow_art_format(self):
        self.assertIsNone(gen_assets.PIXEL_CHARS["."])
        for k, c in enumerate(PIXEL_LETTERS, start=1):
            self.assertEqual(gen_assets.PIXEL_CHARS[c], k, c)
        self.assertEqual(len(gen_assets.PIXEL_CHARS), 16)

    def test_fixture_parses_like_the_independent_reader(self):
        grids, sources = gen_assets.load_art(FIXTURE)
        own = own_parse_art([FIXTURE / "sprites.txt", FIXTURE / "z_more.txt"])
        self.assertEqual(set(grids), set(own))
        for name in own:
            self.assertEqual(grids[name], own[name], name)
        self.assertEqual(sources["dropy_0"], "z_more.txt")
        self.assertEqual(sources["lflip_0"], "sprites.txt")
        # targ1_0 holds every letter once: indices 1..15 then transparent
        self.assertEqual(grids["targ1_0"][0], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(grids["targ1_0"][1], [8, 9, 10, 11, 12, 13, 14])
        self.assertEqual(grids["targ1_0"][2], [15] + [None] * 6)
        # font.txt is not an art file
        self.assertEqual([p.name for p in gen_assets.art_files(FIXTURE)],
                         ["sprites.txt", "z_more.txt"])

    def test_derive_operations(self):
        g = gen_assets.load_art(FIXTURE)[0]
        self.assertEqual(g["rflip_0"], own_transform(g["lflip_0"], "fliph"))
        self.assertEqual(g["lflip_2"], own_transform(g["lflip_0"], "flipv"))
        self.assertEqual(g["lflip_1"], g["lflip_0"])
        self.assertIsNot(g["lflip_1"], g["lflip_0"])
        self.assertEqual(g["dropy_0"], own_transform(g["dropx_0"], "flipv"))
        self.assertEqual(g["spare_rot"], own_transform(g["_helper"], "rot90"))
        # rot90 is clockwise: the top-left pixel moves to the top-right
        t = [[1, None], [None, None]]
        self.assertEqual(gen_assets.transform(t, "rot90"), [[None, 1], [None, None]])
        self.assertEqual(gen_assets.transform(t, "rot180"), [[None, None], [None, 1]])
        self.assertEqual(gen_assets.transform(t, "rot270"), [[None, None], [1, None]])
        self.assertEqual(gen_assets.transform([[1, 2, 3]], "fliph"), [[3, 2, 1]])
        self.assertEqual(gen_assets.transform([[1], [2]], "flipv"), [[2], [1]])
        with self.assertRaises(gen_assets.AssetError):
            gen_assets.transform([[1, 2, 3]], "rot90")
        with self.assertRaises(gen_assets.AssetError):
            gen_assets.transform([[1]], "pad")

    def test_bad_art_is_rejected_with_the_line_number(self):
        tmp = Path(tempfile.mkdtemp(prefix="pcs_bad_"))
        try:
            def check(text, message):
                p = tmp / "a.txt"
                p.write_text(text)
                with self.assertRaisesRegex(gen_assets.AssetError, message):
                    gen_assets.parse_art(p)

            check("sprite x 2 2\n..\n.x\n", r"a.txt:3: x row 1: bad pixel char")
            check("sprite x 2 2\n..\n...\n", r"a.txt:3: x row 1: 3 chars, expected 2")
            check("sprite x 2 2\n..", r"file ends inside rows")
            check("sprite x 2 2\n..\n..\nsprite x 1 1\n.\n", r"defined twice")
            check("sprite x 2 2\n..\n..\nderive y = fliph z\n", r"unknown source z")
            check("sprite x 2 2\n..\n..\nderive y = spin x\n", r"unknown operation")
            check("sprite x 2 2\n..\n..\nderive y = pad x 1 1\n", r"expected 'derive")
            check("sprite 2x 2 2\n..\n..\n", r"bad sprite name")
            check("sprite x-y 2 2\n..\n..\n", r"bad sprite name")
            check("sprite x 0 2\n", r"outside 1\.\.")
            # names may carry upper-case letters (swatch_W); the same name in
            # two cases would give one SPR_ constant, so build_all rejects it
            (tmp / "a.txt").unlink()
            p = tmp / "u.txt"
            p.write_text("sprite swatch_W 1 1\nW\nsprite Swatch_w 1 1\nd\n")
            self.assertEqual(sorted(gen_assets.parse_art(p)), ["Swatch_w", "swatch_W"])
            with self.assertRaisesRegex(gen_assets.AssetError, r"both be SPR_SWATCH_W"):
                gen_assets.build_all(tmp, FIXTURE / "parts.json")
            p.unlink()
            check("sprite x two 2\n", r"expected 'sprite NAME W H'")
            check("frobnicate\n", r"unknown directive")
            # a second file may not redefine a sprite of the first
            grids, sources = {}, {}
            (tmp / "a.txt").write_text("sprite x 1 1\nW\n")
            (tmp / "b.txt").write_text("sprite x 1 1\nd\n")
            gen_assets.parse_art(tmp / "a.txt", grids, sources)
            with self.assertRaisesRegex(gen_assets.AssetError, r"first in a.txt"):
                gen_assets.parse_art(tmp / "b.txt", grids, sources)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_parts_json_is_validated(self):
        tmp = Path(tempfile.mkdtemp(prefix="pcs_bad_"))
        try:
            with self.assertRaisesRegex(gen_assets.AssetError, r"run tools/parts.py"):
                gen_assets.load_parts(tmp / "none.json")
            (tmp / "p.json").write_text("{}")
            with self.assertRaisesRegex(gen_assets.AssetError, r"no 'parts' list"):
                gen_assets.load_parts(tmp / "p.json")
            (tmp / "p.json").write_text('{"parts": [{"name": "X", "kind": 0, "bitmap": "XB"}]}')
            with self.assertRaisesRegex(gen_assets.AssetError, r"X lacks 'box'"):
                gen_assets.load_parts(tmp / "p.json")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- encoding

class TestEncoding(GeneratorRun):

    def check_variant(self, name, grid, data, shift):
        """Decode the run records by hand and compare with the source art."""
        h, wb, rows, used = own_decode(data)
        self.assertEqual(used, len(data), f"{name}: trailing bytes")
        w = len(grid[0])
        self.assertEqual(h, len(grid), name)
        self.assertEqual(wb, (w + shift + 1) // 2, name)
        for y in range(h):
            row = grid[y]
            drawn = rows[y]
            for x in range(wb * 2):
                src = row[x - shift] if 0 <= x - shift < w else None
                if src is not None:
                    self.assertEqual(drawn[x], src, f"{name} row {y} x {x} shift {shift}")
                else:
                    self.assertIn(drawn[x], (None, 0), f"{name} row {y} x {x}: not transparent")
            # a run starts and ends on an opaque byte, and a gap of SPLIT_GAP
            # or more transparent bytes never lies inside a run
            covered = [k for k in range(wb) if drawn[2 * k] is not None]
            opaque = [k for k in range(wb) if any(
                (row[2 * k + j - shift] if 0 <= 2 * k + j - shift < w else None) is not None
                for j in (0, 1))]
            self.assertEqual(sorted(set(covered) & set(opaque)), opaque, f"{name} row {y}")
            gap = 0
            for k in covered:
                if k in opaque:
                    gap = 0
                else:
                    gap += 1
                    self.assertLess(gap, SPLIT_GAP, f"{name} row {y}: a long gap inside a run")
            if covered:
                self.assertIn(covered[0], opaque, f"{name} row {y}: run starts transparent")
                self.assertIn(covered[-1], opaque, f"{name} row {y}: run ends transparent")

    def test_every_variant_decodes_to_its_art_or_placeholder(self):
        for i in range(self.count):
            name = self.names[i]
            grid = self.expected_grid(i)
            even = self.variant(i, "even")
            odd = self.variant(i, "odd")
            if name in gen_assets.RAW_SPRITES:
                # raw rows: ceil(w/2) bytes per row, high nibble = left pixel
                w, h = self.blocks["spr_w"][i], self.blocks["spr_h"][i]
                self.assertEqual(len(even), h * ((w + 1) // 2), name)
                if grid is not None:
                    self.assertEqual(even, gen_assets.encode_raw(grid), name)
                self.assertEqual(odd, even, f"{name}: raw is even only")
                continue
            if grid is None:
                # a placeholder: the violet/white checker of the listed size
                h, wb, rows, _used = own_decode(even)
                colours = {p for r in rows for p in r if p not in (None, 0)}
                self.assertEqual(colours, PLACEHOLDER, name)
                grid = [[p for p in r[:self.blocks["spr_w"][i]]] for r in rows]
            self.check_variant(name, grid, even, 0)
            if name in gen_assets.EVEN_ONLY:
                self.assertEqual(odd, even, f"{name}: even only")
            else:
                self.check_variant(name, grid, odd, 1)
            # the generator's own decoder agrees with the independent one
            self.assertEqual(gen_assets.decode_variant(even)[0], own_decode(even)[2], name)
            self.assertEqual(gen_assets.decode_variant(odd)[0], own_decode(odd)[2], name)
        self.assertIn("logo", gen_assets.EVEN_ONLY)
        self.assertEqual(gen_assets.RAW_SPRITES, {"logo"})

    def test_run_splitting_and_headers(self):
        # kick1_0 row 8 "d.....d": bytes 0 and 3 opaque, gap of 2 -> two runs;
        # the transparent right nibble of each run byte is stored as 0
        i = self.names.index("kick1_0")
        _h, _wb, rows, _ = own_decode(self.variant(i, "even"))
        self.assertEqual(rows[8], [1, 0, None, None, None, None, 1, 0])
        # the same row shifted right lands on bytes 0 and 3 again (. d ... . d)
        _h, _wb, rows, _ = own_decode(self.variant(i, "odd"))
        self.assertEqual(rows[8], [0, 1, None, None, None, None, 0, 1])
        # wide_thing: 40 px, three runs, offsets beyond 15
        grid = self.grids["wide_thing"]
        even, holes = gen_assets.encode_variant(grid, 0)
        self.assertEqual(holes, 0)
        self.assertEqual(list(even[:2]), [2, 20])
        self.assertEqual(list(even[2:]),
                         [0 | RUN_MORE, 1, 0x44, 4 | RUN_MORE, 1, 0x44, 10, 1, 0x44] + list(EMPTY))
        # a gap of one byte is kept inside the run as nibble 0 (a hole)
        even, holes = gen_assets.encode_variant([[1, 1, None, None, 2, 2]], 0)
        self.assertEqual(holes, 2)
        self.assertEqual(list(even), [1, 3, 0, 3, 0x11, 0x00, 0x22])
        # the odd variant shifts the gap onto other byte boundaries
        odd, _ = gen_assets.encode_variant([[1] + [None] * 4 + [2]], 1)
        self.assertEqual(list(odd), [1, 4, 0 | RUN_MORE, 1, 0x01, 3, 1, 0x20])
        # an empty row costs the two EMPTY bytes and nothing else
        even, _ = gen_assets.encode_variant([[None, None], [3, None]], 0)
        self.assertEqual(list(even), [2, 1, 0xFF, 0x00, 0, 1, 0x30])

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
        self.assertEqual(list(odd[2:5]), [1, 1, 0x30])   # the 3 lands at x=2, high nibble

    def test_placeholder_is_a_visible_checker(self):
        g = gen_assets.placeholder_grid(8, 8)
        self.assertEqual(len(g), 8)
        self.assertEqual(g[0], [14, 14, 4, 4, 14, 14, 4, 4])
        self.assertEqual(g[2], [4, 4, 14, 14, 4, 4, 14, 14])
        self.assertEqual({p for r in g for p in r}, PLACEHOLDER)
        self.assertEqual(len(gen_assets.placeholder_grid(7, 3)[0]), 7)


# ---------------------------------------------------------------- ids and tables

class TestIds(GeneratorRun):

    def test_ids_are_parts_then_aux_then_ui_then_extras(self):
        expected = []
        for kind, frames in FIXTURE_KINDS:
            expected += [f"{FIXTURE_BASES[kind]}_{f}" for f in range(frames)]
        expected += AUX_NAMES + UI_NAMES + FIXTURE_EXTRA
        self.assertEqual(self.names, expected)
        self.assertEqual(self.count, len(expected))
        self.assertEqual(self.consts["SPR_COUNT"], self.count)
        self.assertEqual(self.inc["KIND_COUNT"], len(FIXTURE_KINDS))
        # a helper never gets an id
        self.assertNotIn("_helper", self.names)
        self.assertNotIn("SPR__HELPER", self.inc)

    def test_part_frames_have_consecutive_ids(self):
        for kind, frames in FIXTURE_KINDS:
            self.assertEqual(self.inc[f"SPR_{kind}_FRAMES"], frames, kind)
            if frames == 0:
                for suffix in ("FIRST", "W", "H", "HOTY"):
                    self.assertEqual(self.inc[f"SPR_{kind}_{suffix}"], 0, kind)
                continue
            first = self.inc[f"SPR_{kind}_FIRST"]
            base = FIXTURE_BASES[kind]
            for f in range(frames):
                self.assertEqual(self.inc[f"SPR_{base.upper()}_{f}"], first + f, f"{kind} frame {f}")
                self.assertEqual(self.names[first + f], f"{base}_{f}")
                # spr_dir + 4*id walks the frames: the runtime adds 4 per frame
                self.assertEqual(self.words["spr_dir"][2 * (first + f)], f"spr_{base}_{f}_even")
                self.assertEqual(self.words["spr_dir"][2 * (first + f) + 1], f"spr_{base}_{f}_odd")
        self.assertEqual(self.inc["SPR_LAUNCHER_FIRST"], 0)
        self.assertEqual(self.inc["SPR_LEFTFLIPPER_FIRST"], 6)
        self.assertEqual(self.inc["SPR_RIGHTFLIPPER_FIRST"], 14)
        self.assertEqual(self.inc["SPR_BALL_FIRST"], 22)
        self.assertEqual(self.inc["SPR_KICK1_FIRST"], 23)
        self.assertEqual(self.inc["SPR_CATCH2_FIRST"], 28)
        self.assertEqual(gen_assets.part_sprite_base("LFLIPPER2"), "lflip2")
        self.assertEqual(gen_assets.part_sprite_base("BMP3"), "bmp3")

    def test_even_only_names_have_fixed_even_positions(self):
        """An even-only sprite drawn at an odd x lands one pixel left, so the
        set is pinned to the names whose positions tools/layout.py and main.s
        fix at even x (see the comment on EVEN_ONLY). Parts, cursors, the
        caret and sprites no module places yet keep both variants."""
        fixed = {"logo", "poly_icon", "slide_scale", "slide_knob"}
        fixed |= {n for n in UI_NAMES if n.startswith(("tool_", "swatch_", "wire_"))}
        self.assertEqual(gen_assets.EVEN_ONLY, fixed)
        self.assertTrue(gen_assets.EVEN_ONLY <= set(UI_NAMES))
        for name in ("mag_grid", "logo_ball", "caret", "cur_hand", "ball_0"):
            self.assertNotIn(name, gen_assets.EVEN_ONLY)
        i = self.names.index("logo_ball")
        self.assertNotEqual(self.words["spr_dir"][2 * i], self.words["spr_dir"][2 * i + 1])

    def test_kind_sizes_come_from_the_art_or_the_box(self):
        for kind, (w, h, hoty) in FIXTURE_BOX.items():
            if kind == "BALL":
                w, h = 5, 5            # drawn smaller than the HGR byte box
            self.assertEqual((self.inc[f"SPR_{kind}_W"], self.inc[f"SPR_{kind}_H"],
                              self.inc[f"SPR_{kind}_HOTY"]), (w, h, hoty), kind)
        self.assertIn("ball_0 5x5 (parts.json box 7x5)", self.stderr)

    def test_tables_have_one_entry_per_id(self):
        for label in ("spr_w", "spr_h", "spr_hoty", "spr_bank"):
            self.assertEqual(len(self.blocks[label]), self.count, label)
        self.assertEqual(len(self.words["spr_dir"]), 2 * self.count)
        self.assertEqual(self.words["spr_dir"],
                         [f"spr_{n}_{'even' if n in gen_assets.EVEN_ONLY else v}"
                          for n in self.names for v in ("even", "odd")])
        self.assertEqual(self.words["spr_dir"][2 * self.names.index("logo") + 1], "spr_logo_even")
        for i, name in enumerate(self.names):
            grid = self.expected_grid(i)
            if grid is not None:
                w, h = len(grid[0]), len(grid)
            elif name.startswith(tuple(FIXTURE_BASES.values())):
                kind = next(k for k, b in FIXTURE_BASES.items() if name.startswith(b + "_"))
                w, h = FIXTURE_BOX[kind][:2]
            elif name in AUX_NAMES:
                w, h = [(aw, ah) for n, aw, ah, _ in gen_assets.AUX_SPRITES if n == name][0]
            else:
                w, h = 8, 8
            self.assertEqual(self.blocks["spr_w"][i], w, name)
            self.assertEqual(self.blocks["spr_h"][i], h, name)
            even = self.variant(i, "even")
            if name in gen_assets.RAW_SPRITES:
                self.assertEqual(len(even), h * ((w + 1) // 2), name)
                self.assertEqual(self.blocks["spr_bank"][i], 8, name)
            else:
                self.assertEqual((even[0], even[1]), (h, (w + 1) // 2), name)
            hoty = 4 if name.startswith(("lflip_", "rflip_")) else 0
            self.assertEqual(self.blocks["spr_hoty"][i], hoty, name)
        self.assertTrue(set(self.blocks["spr_bank"]) <= {0, 4, 6, 8})

    def test_missing_sprites_are_reported_and_marked(self):
        missing = [n for n in self.names if n not in FIXTURE_DRAWN]
        self.assertIn("launcher_2", missing)
        self.assertIn("catch2_4", missing)
        self.assertIn("logo", missing)
        m = re.search(r"placeholders used: (.*)", self.stderr)
        self.assertIsNotNone(m, self.stderr)
        self.assertEqual(m.group(1).split(", "), missing)
        self.assertIn("extra sprites in the art (ids appended): spare_copy, spare_rot, wide_thing",
                      self.stderr)
        for name in missing:
            self.assertRegex(self.inc_text, re.compile(rf"^SPR_{name.upper()} = \d+\s+; placeholder$", re.M))
            self.assertRegex(self.asm_text, re.compile(rf"^;\s+\d+\s+{name}\s.*PLACEHOLDER$", re.M))
        for name in FIXTURE_DRAWN:
            self.assertRegex(self.inc_text, re.compile(rf"^SPR_{name.upper()} = \d+$", re.M))

    def test_inc_is_guarded_and_assembles_twice(self):
        self.assertIn(".ifndef ASSETS_INC", self.inc_text)
        self.assertEqual(self.inc["SPR_BANK_AUX"], 4)
        self.assertEqual(self.inc["SPR_BANK_1"], 2)
        self.assertEqual(self.inc["FONT_GLYPHS"], 37)
        self.assertEqual(self.inc["FONT_SPACE"], 36)
        self.assertEqual(self.inc["FONT_A"], 10)
        if not shutil.which("ca65"):
            self.skipTest("ca65 not installed")
        src = self.tmp / "twice.s"
        src.write_text('SPR_BANK_AUX = 4\n.include "assets.inc"\n.include "assets.inc"\n'
                       ".byte SPR_COUNT, SPR_LFLIP_0, SPR_LEFTFLIPPER_FRAMES, FONT_SPACE\n")
        r = subprocess.run(["ca65", "--cpu", "65c02", "-I", str(self.build), "-o",
                            str(self.tmp / "twice.o"), str(src)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


# ---------------------------------------------------------------- PCS.SPR

class TestSprFile(GeneratorRun):

    def test_header_regions_and_addresses(self):
        self.assertEqual(self.spr[:4], b"BSPR")
        self.assertEqual(self.spr[4], len(self.regions))
        self.assertGreaterEqual(len(self.regions), 1)
        sizes = {bank: (addr, size) for addr, size, bank in DESIGN_REGIONS}
        for addr, bank, blob in self.regions:
            self.assertIn(bank, sizes)
            self.assertEqual(addr, sizes[bank][0])
            self.assertLessEqual(len(blob), sizes[bank][1])
        # every card sprite lies inside its region, variants back to back in
        # id order, and the regions hold nothing else
        expected = {bank: bytearray() for _a, bank, _b in self.regions}
        for i, name in enumerate(self.names):
            bank = self.bank_of(i)
            if bank == 0:
                self.assertIn(f"spr_{name}_even", self.blocks, name)
                self.assertIn(f"spr_{name}_odd", self.blocks, name)
                continue
            base = sizes[bank][0]
            self.assertEqual(self.consts[f"spr_{name}_even"], base + len(expected[bank]), name)
            expected[bank] += self.variant(i, "even")
            if name in gen_assets.EVEN_ONLY:
                self.assertNotIn(f"spr_{name}_odd", self.consts, name)
            else:
                self.assertEqual(self.consts[f"spr_{name}_odd"], base + len(expected[bank]), name)
                expected[bank] += self.variant(i, "odd")
            self.assertNotIn(f"spr_{name}_even", self.blocks, name)
        for _addr, bank, blob in self.regions:
            self.assertEqual(bytes(blob), bytes(expected[bank]), f"bank {bank}")
        # the fixture fits the first region (plus the raw logo in RamWorks);
        # gen_assets reads its own file the same way
        self.assertEqual([b for _a, b, _blob in self.regions], [4, 8])
        parsed = gen_assets.parse_spr_file(self.spr)
        self.assertEqual([(a, b, bytes(blob)) for a, b, blob in self.regions],
                         [(a, b, blob) for a, _l, b, blob in parsed])
        self.assertEqual(struct.unpack_from("<HHB", self.spr, 5), (0xD000, len(self.regions[0][2]), 4))
        m = re.search(r";\s*in PCS.SPR\s*:\s*(\d+)", self.asm_text)
        self.assertEqual(int(m.group(1)), sum(len(b) for _a, _b, b in self.regions))

    def test_placement_first_fit_and_overflow_to_rodata(self):
        encoded = [dict(name="a", even=b"\1" * 10, odd=b"\1" * 10),
                   dict(name="b", even=b"\3" * 30, odd=b"\3" * 30),
                   dict(name="c", even=b"\4" * 10, odd=b"\4" * 10),
                   dict(name="d", even=b"\5" * 60, odd=b"\5" * 60)]
        regions = (("R1", 4, 0xD000, 32), ("R2", 6, 0xD000, 100))
        blobs = gen_assets.place_sprites(encoded, regions)
        # a fits R1 (20 of 32), b (60) goes to R2, c (20) no longer fits R1 and
        # follows b in R2, d (120) fits nowhere and stays in RODATA
        self.assertEqual([e["bank"] for e in encoded], [4, 6, 6, 0])
        self.assertEqual(encoded[0]["even_addr"], 0xD000)
        self.assertEqual(encoded[0]["odd_addr"], 0xD00A)
        self.assertEqual(encoded[2]["even_addr"], 0xD000 + 60)
        self.assertEqual(encoded[2]["odd_addr"], 0xD000 + 70)
        self.assertIsNone(encoded[3]["even_addr"])
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
        with self.assertRaises(gen_assets.AssetError):
            gen_assets.parse_spr_file(image + b"\0")
        with self.assertRaises(gen_assets.AssetError):
            gen_assets.parse_spr_file(b"XSPR" + image[4:])

    def test_design_regions(self):
        self.assertEqual([(base, size, bank) for _n, bank, base, size in gen_assets.REGIONS],
                         DESIGN_REGIONS)

    def test_raw_sprite_must_fit_its_region(self):
        # a raw picture has no RODATA fallback: the blitter cannot draw raw
        # rows and DRAWLOGO fetches from RamWorks whatever spr_bank says
        regions = (("R1", 4, 0xD000, 0x2FF0), ("R2", 6, 0xD000, 0x1000), ("RW", 8, 0xA000, 16))
        with self.assertRaisesRegex(gen_assets.AssetError, r"logo: 32 raw bytes fit in no raw-row"):
            gen_assets.build_all(FIXTURE, FIXTURE / "parts.json", regions=regions)
        # without any raw region at all the same applies
        regions = (("R1", 4, 0xD000, 0x2FF0),)
        with self.assertRaisesRegex(gen_assets.AssetError, r"raw picture cannot live in RODATA"):
            gen_assets.build_all(FIXTURE, FIXTURE / "parts.json", regions=regions)


# ---------------------------------------------------------------- font and palette

class TestFontPalette(GeneratorRun):

    def test_upstream_font_extraction(self):
        fallback_glyphs, fallback_cwidth = gen_assets.fallback_font()
        self.assertEqual(len(fallback_glyphs), 36)
        self.assertEqual(len(fallback_cwidth), 37)
        found = False
        for path in (BASELINE_CDRAW, UPSTREAM_CDRAW):
            if not path.is_file():
                continue
            found = True
            glyphs, cwidth = gen_assets.extract_font(path)
            self.assertEqual(glyphs, fallback_glyphs, path)
            self.assertEqual(cwidth, fallback_cwidth, path)
            self.assertEqual(glyphs[10], [0x0E, 0x1B, 0x1B, 0x1F, 0x1B, 0x1B, 0x1B], "A")
        if not found:
            self.skipTest("no CDRAW source to extract from")

    def test_font_conversion(self):
        self.assertEqual(gen_assets.reverse7(0x01), 0x80)
        self.assertEqual(gen_assets.reverse7(0x40), 0x02)
        self.assertEqual(gen_assets.reverse7(0x0E), 0x70)
        font7, adv, origin = gen_assets.upstream_font(None)
        self.assertEqual(origin, "built-in copy")
        self.assertEqual(len(font7), 37)
        self.assertEqual(font7[10], UPSTREAM_A)
        self.assertEqual(font7[36], [0] * 7)
        self.assertEqual(adv, UPSTREAM_ADV)
        # 'L' (code 21) has its stem on the left: bit 7 set on every row
        self.assertTrue(all(b & 0x80 for b in font7[21]))
        # every glyph but the space has ink, and none uses column 7
        self.assertTrue(all(any(g) for g in font7[:36]))
        self.assertTrue(all(not (b & 1) for g in font7 for b in g))
        if BASELINE_CDRAW.is_file():
            font7b, advb, originb = gen_assets.upstream_font(BASELINE_CDRAW)
            self.assertEqual((font7b, advb), (font7, adv))
            self.assertEqual(originb, str(BASELINE_CDRAW))

    def test_font_tables_in_assets_s(self):
        font = bytes(self.blocks["font7"])
        adv = bytes(self.blocks["font_adv"])
        self.assertEqual(len(font), 37 * 7)
        self.assertEqual(len(adv), 37)
        for code in range(37):
            rows = list(font[code * 7:code * 7 + 7])
            if code in self.font_override:
                exp_rows, exp_adv = self.font_override[code]
                self.assertEqual(rows, exp_rows, f"overridden glyph {code}")
                self.assertEqual(adv[code], exp_adv if exp_adv else UPSTREAM_ADV[code], code)
            else:
                self.assertEqual(adv[code], UPSTREAM_ADV[code], code)
        # the fixture: '0' became a hollow box, 'A' kept its shape and got advance 7
        self.assertEqual(list(font[0:7]), [0xFE, 0x82, 0x82, 0x82, 0x82, 0x82, 0xFE])
        self.assertEqual(list(font[70:77]), UPSTREAM_A)
        self.assertEqual(adv[10], 7)
        self.assertEqual(adv[36], 5)
        self.assertEqual(font[36 * 7:37 * 7], bytes(7))
        self.assertIn("overridden glyphs: 0, A", self.asm_text)
        # glyph codes in the override file
        self.assertEqual(gen_assets.glyph_code("A"), 10)
        self.assertEqual(gen_assets.glyph_code("z"), 35)
        self.assertEqual(gen_assets.glyph_code("7"), 7)
        self.assertEqual(gen_assets.glyph_code("space"), 36)
        self.assertEqual(gen_assets.glyph_code("36"), 36)

    def test_bad_font_override_is_rejected(self):
        tmp = Path(tempfile.mkdtemp(prefix="pcs_font_"))
        try:
            def check(text, message):
                p = tmp / "font.txt"
                p.write_text(text)
                with self.assertRaisesRegex(gen_assets.AssetError, message):
                    gen_assets.parse_font_override(p)

            rows = "#######\n" * 7
            check("glyph 37 X\n" + rows, r"outside 0\.\.36")
            check("glyph 1 X\n" + rows + "glyph 1 Y\n" + rows, r"defined twice")
            check("glyph 1 X 9\n" + rows, r"advance 9")
            check("glyph 1 X\n" + "#######\n" * 6 + "##\n", r"bad row")
            check("glyph 1 X\n" + "#######\n" * 5 + "#######", r"file ends")
            check("gly 1 X\n", r"expected 'glyph")
            # 8-column rows are accepted for Bosconian's font8.txt habit, but the
            # 8th pixel would spill out of cdraw.s's 4-byte arena row at an odd x
            check("glyph 1 X\n" + ".......#\n" + "#######\n" * 6, r"column 8 must be")
            p = tmp / "font.txt"
            p.write_text("glyph 1 X\n" + "#######.\n" * 7)
            self.assertEqual(gen_assets.parse_font_override(p)[1], ([0xFE] * 7, None))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_palette(self):
        pal = bytes(self.blocks["palette0"])
        self.assertEqual(len(pal), 32)
        for i, (r, g, b) in enumerate(DESIGN_PALETTE):
            self.assertEqual(pal[2 * i], (g << 4) | b, f"palette {i} byte 0")
            self.assertEqual(pal[2 * i + 1], r, f"palette {i} byte 1")
        self.assertEqual([(r, g, b) for _i, _n, r, g, b in gen_assets.PALETTE], DESIGN_PALETTE)
        self.assertEqual(gen_assets.palette_bytes(), pal)
        self.assertEqual(pal[2 * 14:2 * 14 + 2], b"\x3E\x09")     # violet $93E

    def test_exports_segment_and_totals(self):
        for sym in ("spr_dir", "spr_w", "spr_h", "spr_hoty", "spr_bank", "palette0",
                    "font7", "font_adv", "SPR_COUNT"):
            self.assertRegex(self.asm_text, r"\.export[^\n]*\b" + sym + r"\b")
        self.assertEqual(self.order[-8:],
                         ["spr_dir", "spr_w", "spr_h", "spr_hoty", "spr_bank", "palette0",
                          "font7", "font_adv"])
        self.assertIn('.segment "RODATA"', self.asm_text)
        total = sum(len(v) for v in self.blocks.values()) + 4 * self.count
        m = re.search(r";\s*RODATA total\s*:\s*(\d+)", self.asm_text)
        self.assertEqual(int(m.group(1)), total)
        self.assertTrue(self.asm_text.startswith("; Pinball Construction Set for the Appletini"))


# ---------------------------------------------------------------- assembling

class TestAssemble(GeneratorRun):

    def expected_image(self, base: int) -> bytes:
        """The RODATA image: main-memory variants in id order, then the
        tables (card sprites contribute their $D000+ addresses)."""
        expected = bytearray()
        addr = dict(self.consts)
        for name in self.names:
            for v in ("even", "odd"):
                label = f"spr_{name}_{v}"
                if label in self.blocks and label not in addr:
                    addr[label] = base + len(expected)
                    expected += self.blocks[label]
        for n in self.words["spr_dir"]:
            expected += struct.pack("<H", addr[n])
        for label in ("spr_w", "spr_h", "spr_hoty", "spr_bank", "palette0", "font7", "font_adv"):
            expected += self.blocks[label]
        return bytes(expected)

    @unittest.skipUnless(shutil.which("ca65") and shutil.which("ld65"), "cc65 tools missing")
    def test_assemble_and_link_raw(self):
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
        self.assertEqual(binary.read_bytes(), self.expected_image(0x4000))

    @unittest.skipUnless(shutil.which("ca65") and shutil.which("ld65"), "cc65 tools missing")
    def test_rodata_sprites_assemble_too(self):
        """With tiny card regions most sprites land in RODATA; the labels
        and the directory must still link."""
        regions = (("R1", 4, 0xD000, 400), ("R2", 6, 0xD000, 300), ("RW", 8, 0xA000, 0x2000))
        result = gen_assets.build_all(FIXTURE, FIXTURE / "parts.json", regions=regions)
        banks = [e["bank"] for e in result["encoded"]]
        self.assertIn(0, banks)
        self.assertIn(4, banks)
        self.assertIn(6, banks)
        self.assertEqual(banks[result["encoded"].index(
            next(e for e in result["encoded"] if e["name"] == "logo"))], 8)
        build = self.tmp / "small"
        build.mkdir(exist_ok=True)
        totals = gen_assets.write_assets_s(build / "assets.s", result)
        self.assertGreater(totals["rodata_sprites"], 0)
        obj = build / "assets.o"
        r = subprocess.run(["ca65", "--cpu", "65c02", str(build / "assets.s"), "-o", str(obj)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = self.tmp / "raw.cfg"
        cfg.write_text("MEMORY { ROM: start = $4000, size = $8000, file = %O; }\n"
                       "SEGMENTS { RODATA: load = ROM, type = ro; }\n")
        r = subprocess.run(["ld65", "-C", str(cfg), "-o", str(build / "a.bin"), str(obj)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = (build / "a.bin").read_bytes()
        self.assertEqual(len(data), totals["rodata"])
        # the directory of a RODATA sprite points at its bytes in the image
        blocks, words, consts, _order = parse_asm((build / "assets.s").read_text())
        e = next(e for e in result["encoded"] if e["bank"] == 0)
        i = result["encoded"].index(e)
        dir_off = len(data) - (totals["tables"] + totals["font"] + totals["palette"])
        even_addr = struct.unpack_from("<H", data, dir_off + 4 * i)[0]
        self.assertEqual(data[even_addr - 0x4000:even_addr - 0x4000 + len(e["even"])], e["even"])
        odd_addr = struct.unpack_from("<H", data, dir_off + 4 * i + 2)[0]
        self.assertEqual(odd_addr, even_addr + len(e["even"]))


# ---------------------------------------------------------------- py65

class CardMemory:
    """Main memory plus the auxiliary set's language card, filled from
    PCS.SPR as src/loader.s would. $C009/$C008 select the set, a read of
    $C080/$C088 selects bank 2/1 with the card readable, $C082 puts the
    ROM back (the card is never written through the CPU here)."""

    def __init__(self):
        self.main = bytearray(0x10000)
        self.aux_zp = bytearray(0x200)
        self.lc_d = {(z, b): bytearray(0x1000) for z in (False, True) for b in (False, True)}
        self.lc_e = {False: bytearray(0x2000), True: bytearray(0x2000)}
        self.altzp = False
        self.lc_read = False
        self.lc_bank2 = True
        self.switches = []

    def load_spr(self, data: bytes):
        self.ramworks1 = bytearray(0x10000)
        for addr, length, bank, blob in gen_assets.parse_spr_file(data):
            if bank & 8:
                # RamWorks bank 1, main-range address: raw rows, never blitted
                assert bank == 8 and 0xA000 <= addr and addr + length <= 0xC000, "raw region"
                self.ramworks1[addr:addr + length] = blob
                continue
            assert bank & 4, "PCS.SPR regions are in the auxiliary card"
            for k, b in enumerate(blob):
                a = addr + k
                if a < 0xE000:
                    self.lc_d[(True, not bank & 2)][a - 0xD000] = b
                else:
                    self.lc_e[True][a - 0xE000] = b

    def card(self, a):
        if a < 0xE000:
            return self.lc_d[(self.altzp, self.lc_bank2)], a - 0xD000
        return self.lc_e[self.altzp], a - 0xE000

    def __getitem__(self, a):
        if isinstance(a, slice):
            return [self[i] for i in range(*a.indices(0x10000))]
        a &= 0xFFFF
        if 0xC080 <= a <= 0xC08F:
            self.switches.append(a)
            if a in (0xC080, 0xC083):
                self.lc_bank2, self.lc_read = True, True
            elif a in (0xC088, 0xC08B):
                self.lc_bank2, self.lc_read = False, True
            elif a in (0xC082, 0xC08A):
                self.lc_read = False
            return 0
        if 0xC000 <= a < 0xC100:
            return 0
        if a < 0x200 and self.altzp:
            return self.aux_zp[a]
        if a >= 0xD000 and self.lc_read:
            arr, off = self.card(a)
            return arr[off]
        return self.main[a]

    def __setitem__(self, a, v):
        if isinstance(a, slice):
            for i, x in zip(range(*a.indices(0x10000)), v):
                self[i] = x
            return
        a &= 0xFFFF
        v &= 0xFF
        if 0xC000 <= a < 0xC100:
            self.switches.append(a)
            if a == 0xC009:
                self.altzp = True
            elif a == 0xC008:
                self.altzp = False
            return
        if a < 0x200 and self.altzp:
            self.aux_zp[a] = v
            return
        if a >= 0xD000:
            raise AssertionError(f"write into the card at ${a:04X}")
        self.main[a] = v


@unittest.skipUnless(MPU and shutil.which("ca65") and shutil.which("ld65"),
                     "py65 or cc65 tools missing")
class TestDirectoryIn6502(GeneratorRun):
    """Assemble assets.s with the driver, load PCS.SPR into the card and
    walk every id and glyph in the emulator."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        objs = []
        for src in (cls.build / "assets.s", TESTS / "assets_test_driver.s"):
            obj = cls.tmp / (src.stem + ".o")
            subprocess.check_call(["ca65", "--cpu", "65c02", "-I", str(cls.build),
                                   "-o", str(obj), str(src)])
            objs.append(str(obj))
        binary = cls.tmp / "drv.bin"
        labels = cls.tmp / "drv.lbl"
        subprocess.check_call(["ld65", "-C", str(TESTS / "assets_test.cfg"), "-Ln", str(labels),
                               "-o", str(binary)] + objs)
        cls.syms = {}
        for line in labels.read_text().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "al":
                cls.syms[parts[2].lstrip(".")] = int(parts[1], 16)
        cls.image = binary.read_bytes()

    def machine(self):
        mem = CardMemory()
        mem.main[0x2000:0x2000 + len(self.image)] = self.image
        mem.load_spr(self.spr)
        mpu = MPU(memory=mem)
        return mem, mpu

    def call(self, mem, mpu, entry, p0, p1=0):
        mem.main[self.syms["param"]] = p0
        mem.main[self.syms["param"] + 1] = p1
        mem.switches.clear()
        mpu.pc = self.syms[entry]
        mpu.sp = 0xFF
        steps = 0
        while mpu.pc != self.syms["halt"]:
            mpu.step()
            steps += 1
            self.assertLess(steps, STEP_LIMIT, f"{entry} did not finish")
        r = self.syms["result"]
        return bytes(mem.main[r:r + 8])

    def test_every_id_resolves_to_its_variant(self):
        mem, mpu = self.machine()
        for i, name in enumerate(self.names):
            if name in gen_assets.RAW_SPRITES:
                continue            # not a run record: fetched by rows, not blitted
            for phase, which in ((0, "even"), (1, "odd")):
                res = self.call(mem, mpu, "t_lookup", i, phase)
                v = self.variant(i, which)
                self.assertEqual(res[0], v[0], f"{name} {which} height")
                self.assertEqual(res[1], v[1], f"{name} {which} width bytes")
                self.assertEqual(res[2], self.blocks["spr_w"][i], name)
                self.assertEqual(res[3], self.blocks["spr_h"][i], name)
                self.assertEqual(res[4], self.blocks["spr_hoty"][i], name)
                self.assertEqual(res[5], self.bank_of(i), name)
                if self.bank_of(i) & 4:
                    bank_read = 0xC088 if self.bank_of(i) & 2 else 0xC080
                    self.assertEqual(mem.switches, [0xC009, bank_read, 0xC082, 0xC008], name)
                else:
                    self.assertEqual(mem.switches, [0xC082, 0xC008], name)
                self.assertFalse(mem.altzp)
                self.assertFalse(mem.lc_read)

    def test_glyphs_and_palette(self):
        mem, mpu = self.machine()
        font = self.blocks["font7"]
        adv = self.blocks["font_adv"]
        for code in range(37):
            res = self.call(mem, mpu, "t_glyph", code)
            self.assertEqual(list(res[:7]), list(font[code * 7:code * 7 + 7]), code)
            self.assertEqual(res[7], adv[code], code)
        self.assertEqual(list(self.call(mem, mpu, "t_glyph", 10)[:7]), UPSTREAM_A)
        for i, (r, g, b) in enumerate(DESIGN_PALETTE):
            res = self.call(mem, mpu, "t_palette", i)
            self.assertEqual((res[0], res[1]), ((g << 4) | b, r), i)


# ---------------------------------------------------------------- errors and options

class TestOptions(unittest.TestCase):

    def test_strict_fails_on_missing_sprites(self):
        tmp = Path(tempfile.mkdtemp(prefix="pcs_strict_"))
        try:
            r = run_generator(FIXTURE, FIXTURE / "parts.json", tmp / "b", "--strict")
            self.assertEqual(r.returncode, 1)
            self.assertIn("missing sprites (--strict): launcher_2", r.stderr)
            self.assertFalse((tmp / "b" / "assets.s").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_art_at_all_still_builds(self):
        tmp = Path(tempfile.mkdtemp(prefix="pcs_empty_"))
        try:
            r = run_generator(tmp / "no_such_dir", FIXTURE / "parts.json", tmp / "b")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("placeholders used: launcher_0", r.stderr)
            inc = parse_inc((tmp / "b" / "assets.inc").read_text())
            expected = sum(f for _k, f in FIXTURE_KINDS) + len(AUX_NAMES) + len(UI_NAMES)
            self.assertEqual(inc["SPR_COUNT"], expected)
            blocks, _w, _c, _o = parse_asm((tmp / "b" / "assets.s").read_text())
            # placeholder sizes: the box for parts, the upstream size for the
            # drop singles, 8x8 for the UI
            self.assertEqual(blocks["spr_w"][inc["SPR_LFLIP_3"]], 20)
            self.assertEqual(blocks["spr_h"][inc["SPR_LFLIP_3"]], 16)
            self.assertEqual(blocks["spr_hoty"][inc["SPR_LFLIP_3"]], 4)
            self.assertEqual(blocks["spr_w"][inc["SPR_BALL_0"]], 7)
            self.assertEqual((blocks["spr_w"][inc["SPR_DROPY_0"]], blocks["spr_h"][inc["SPR_DROPY_0"]]), (7, 7))
            self.assertEqual((blocks["spr_w"][inc["SPR_LOGO"]], blocks["spr_h"][inc["SPR_LOGO"]]), (8, 8))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_raw_sprite_must_fit_the_logo_band(self):
        tmp = Path(tempfile.mkdtemp(prefix="pcs_logo_"))
        try:
            (tmp / "a.txt").write_text("sprite logo 161 1\n" + "W" * 161 + "\n")
            with self.assertRaisesRegex(gen_assets.AssetError, r"logo: 161x1 does not fit"):
                gen_assets.build_all(tmp, FIXTURE / "parts.json")
            (tmp / "a.txt").write_text("sprite logo 2 65\n" + "WW\n" * 65)
            with self.assertRaisesRegex(gen_assets.AssetError, r"logo: 2x65 does not fit"):
                gen_assets.build_all(tmp, FIXTURE / "parts.json")
            (tmp / "a.txt").write_text("sprite logo 160 64\n" + ("W" * 160 + "\n") * 64)
            result = gen_assets.build_all(tmp, FIXTURE / "parts.json")
            logo = next(e for e in result["encoded"] if e["name"] == "logo")
            self.assertEqual((logo["bank"], logo["even_addr"], len(logo["even"])),
                             (8, 0xA000, 80 * 64))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_frames_of_a_kind_must_share_one_size(self):
        tmp = Path(tempfile.mkdtemp(prefix="pcs_sizes_"))
        try:
            (tmp / "a.txt").write_text("sprite kick1_0 7 16\n" + ".......\n" * 16
                                       + "sprite kick1_1 7 15\n" + ".......\n" * 15)
            with self.assertRaisesRegex(gen_assets.AssetError, r"KICK1: its frames differ"):
                gen_assets.build_all(tmp, FIXTURE / "parts.json")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_bad_art_file_fails_the_run(self):
        tmp = Path(tempfile.mkdtemp(prefix="pcs_badrun_"))
        try:
            (tmp / "a.txt").write_text("sprite ball_0 2 2\n..\n.x\n")
            r = run_generator(tmp, FIXTURE / "parts.json", tmp / "b")
            self.assertEqual(r.returncode, 1)
            self.assertIn("a.txt:3: ball_0 row 1: bad pixel char", r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_preview_is_written_when_pillow_imports(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        tmp = Path(tempfile.mkdtemp(prefix="pcs_prev_"))
        try:
            r = run_generator(FIXTURE, FIXTURE / "parts.json", tmp / "b")
            self.assertEqual(r.returncode, 0, r.stderr)
            png = tmp / "b" / "assets_preview.png"
            self.assertTrue(png.is_file())
            self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the real art

@unittest.skipUnless(REAL_PARTS.is_file(), "build/parts.json not generated (make build/parts.json)")
class TestRealAssets(unittest.TestCase):
    """Whatever the artists have drawn so far must build, assemble and keep
    the frame ids consecutive; the card must hold all the part sprites."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pcs_real_"))
        cls.build = cls.tmp / "build"
        r = run_generator(REAL_ASSETS, REAL_PARTS, cls.build)
        if r.returncode != 0:
            raise RuntimeError("gen_assets.py failed on assets/:\n" + r.stdout + r.stderr)
        cls.stderr = r.stderr
        cls.parts = json.loads(REAL_PARTS.read_text())["parts"]
        cls.inc = parse_inc((cls.build / "assets.inc").read_text())
        cls.blocks, cls.words, cls.consts, _o = parse_asm((cls.build / "assets.s").read_text())
        cls.spr = (cls.build / "PCS.SPR").read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_kind_has_consecutive_frames(self):
        self.assertEqual(self.inc["KIND_COUNT"], 43)
        self.assertEqual(len(self.parts), 43)
        for p in self.parts:
            n = p["name"]
            self.assertEqual(self.inc[f"SPR_{n}_FRAMES"], p.get("frames", 0), n)
            if "bitmap" not in p:
                continue
            base = gen_assets.part_sprite_base(n)
            first = self.inc[f"SPR_{n}_FIRST"]
            for f in range(p["frames"]):
                self.assertEqual(self.inc[f"SPR_{base.upper()}_{f}"], first + f, f"{n} frame {f}")
                self.assertEqual(self.words["spr_dir"][2 * (first + f)], f"spr_{base}_{f}_even")
            self.assertEqual(self.inc[f"SPR_{n}_HOTY"], p["hoty"], n)
            self.assertEqual(self.blocks["spr_hoty"][first], p["hoty"], n)
        self.assertEqual(self.inc["SPR_LAUNCHER_FIRST"], 0)
        self.assertEqual(self.inc["SPR_LFLIP_0"], self.inc["SPR_LEFTFLIPPER_FIRST"])
        self.assertEqual(self.inc["SPR_RFLIP2_7"], self.inc["SPR_RFLIPPER2_FIRST"] + 7)
        self.assertEqual(self.inc["SPR_BALL_0"], self.inc["SPR_BALL_FIRST"])

    def test_regions_and_totals(self):
        regions = GeneratorRun.parse_spr(self.spr)
        sizes = {bank: size for _a, size, bank in DESIGN_REGIONS}
        for _addr, bank, blob in regions:
            self.assertLessEqual(len(blob), sizes[bank])
        # the part sprites (ids before the drop singles) all live in the card
        for i in range(self.inc["SPR_DROPX_0"]):
            self.assertIn(self.blocks["spr_bank"][i], (4, 6), i)
        m = re.search(r";\s*RODATA total\s*:\s*(\d+)", (self.build / "assets.s").read_text())
        self.assertLess(int(m.group(1)), 12 * 1024, "RODATA must leave room for the code")

    @unittest.skipUnless(shutil.which("ca65") and shutil.which("ld65"), "cc65 tools missing")
    def test_assembles(self):
        obj = self.tmp / "assets.o"
        r = subprocess.run(["ca65", "--cpu", "65c02", str(self.build / "assets.s"), "-o", str(obj)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = self.tmp / "raw.cfg"
        cfg.write_text("MEMORY { ROM: start = $4000, size = $8000, file = %O; }\n"
                       "SEGMENTS { RODATA: load = ROM, type = ro; }\n")
        r = subprocess.run(["ld65", "-C", str(cfg), "-o", str(self.tmp / "a.bin"), str(obj)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
