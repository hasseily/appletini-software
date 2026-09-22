#!/usr/bin/env python3
"""Checks on the round layout table in rounds.c (docs/DESIGN.md section 10).

Parses the C table (no compiler needed) and compares it with an independent
copy of the arcade's tables (read from the sub CPU ROM with MAME: 14
layouts of radar tiles plus orientation, and the round -> layout list), then
checks the geometry: every base inside the 1024x1792 world, no two bases
overlapping, the ship's start position clear of every core and cannon.

Run:  python3 tests/test_rounds.py        (from the project directory)
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

WORLD_W, WORLD_H = 1024, 1792
START = (512, 1668)
BASE_MAX = 8
# a base's bounding box: vertical 64x72, horizontal 72x64
BASE_SIZE = {"V": (64, 72), "H": (72, 64)}
# hit boxes (game.c): the core and the six 16x16 cannons, offsets from the centre
CORE_BOX = {"V": (32, 40), "H": (40, 32)}
CANNONS = {"V": [(0, -28), (-24, -12), (24, -12), (-24, 12), (24, 12), (0, 28)],
           "H": [(-28, 0), (-12, -24), (12, -24), (-12, 24), (12, 24), (28, 0)]}

# The arcade tables: radar tile (a = y/32, c = x/32) and orientation per
# base, turned into centres the way the arcade's main CPU does it:
# horizontal (c*32+36, a*32+32), vertical (c*32+32, a*32+36).
ROM_LAYOUTS = [
    [(484, 1504, "H"), (612, 1440, "H"), (356, 1184, "H")],
    [(164, 672, "H"), (164, 864, "H"), (736, 804, "V"), (928, 804, "V")],
    [(228, 416, "H"), (352, 228, "V"), (544, 228, "V"), (740, 416, "H"),
     (676, 672, "H"), (544, 868, "V"), (484, 1056, "H"), (484, 1312, "H")],
    [(32, 100, "V"), (612, 224, "H"), (864, 292, "V"), (864, 612, "V"),
     (676, 736, "H"), (548, 1056, "H"), (416, 1316, "V"), (548, 1632, "H")],
    [(164, 544, "H"), (804, 544, "H"), (352, 740, "V"), (608, 740, "V"),
     (356, 1056, "H"), (612, 1056, "H"), (160, 1252, "V"), (800, 1252, "V")],
    [(736, 996, "V"), (804, 992, "H"), (804, 1056, "H"), (484, 1120, "H"),
     (484, 1184, "H"), (672, 1380, "V"), (608, 1380, "V"), (228, 1504, "H")],
    [(544, 164, "V"), (416, 548, "V"), (672, 676, "V"), (480, 740, "V"),
     (288, 868, "V"), (608, 932, "V"), (36, 1248, "H"), (800, 1636, "V")],
    [(484, 800, "H"), (356, 864, "H"), (612, 864, "H"), (288, 932, "V"),
     (672, 932, "V"), (356, 1056, "H"), (484, 1056, "H"), (612, 1056, "H")],
    [(164, 288, "H"), (740, 480, "H"), (608, 996, "V"), (480, 1060, "V"),
     (352, 1124, "V"), (484, 1376, "H"), (868, 1504, "H"), (228, 1632, "H")],
    [(160, 548, "V"), (480, 548, "V"), (800, 548, "V"), (612, 736, "H"),
     (356, 1056, "H"), (160, 1252, "V"), (480, 1252, "V"), (800, 1252, "V")],
    [(32, 996, "V"), (160, 996, "V"), (288, 996, "V"), (416, 996, "V"),
     (544, 996, "V"), (672, 996, "V"), (800, 996, "V"), (932, 992, "H")],
    [(228, 800, "H"), (740, 800, "H"), (352, 996, "V"), (608, 996, "V"),
     (484, 1120, "H"), (480, 1252, "V"), (480, 1380, "V"), (480, 1508, "V")],
    [(356, 800, "H"), (484, 800, "H"), (612, 800, "H"), (416, 868, "V"),
     (580, 864, "H"), (356, 992, "H"), (484, 992, "H"), (608, 996, "V")],
    [(480, 548, "V"), (800, 676, "V"), (224, 612, "V"), (480, 1316, "V"),
     (100, 864, "H"), (868, 928, "H"), (164, 1120, "H"), (740, 1184, "H")],
]
# layout of rounds 1..17; later rounds play 12..17 again
ROM_ROUND_SEQ = [0, 1, 7, 8, 13, 3, 10, 12, 4, 11, 9, 7, 8, 5, 6, 13, 2]


def parse_layouts(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    body = text[text.index("round_layouts[ROUND_LAYOUTS] = {"):]
    body = body[:body.index("};")]
    layouts = []
    for m in re.finditer(r"\{\s*(\d+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*,"
                         r"\s*\{([^}]*)\}\s*,\s*\{([^}]*)\}\s*\}", body):
        count = int(m.group(1))
        hz = int(m.group(2), 0)
        xs = [int(v) for v in m.group(3).split(",") if v.strip()]
        ys = [int(v) for v in m.group(4).split(",") if v.strip()]
        layouts.append((count, hz, xs, ys))
    return layouts


def parse_round_seq(text):
    m = re.search(r"round_seq\[17\]\s*=\s*\{([^}]*)\}", text)
    return [int(v) for v in m.group(1).split(",")]


def layout_of_round(seq, round_no):
    """round_layout() of rounds.c: rounds 18 and up play 12..17 again."""
    while round_no > 17:
        round_no -= 6
    return seq[round_no - 1]


def wrap_delta(a, b, size):
    d = (a - b) % size
    return d - size if d >= size // 2 else d


class RoundTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "rounds.c")) as f:
            cls.text = f.read()
        with open(os.path.join(ROOT, "game.h")) as f:
            cls.header = f.read()
        cls.layouts = parse_layouts(cls.text)
        cls.seq = parse_round_seq(cls.text)

    def test_table_size_matches_header(self):
        n = int(re.search(r"#define ROUND_LAYOUTS (\d+)", self.header).group(1))
        self.assertEqual(len(self.layouts), n)
        self.assertEqual(n, len(ROM_LAYOUTS))
        self.assertIn("#define WORLD_W 1024", self.header)
        self.assertIn("#define WORLD_H 1792", self.header)
        self.assertIn("#define START_X 512", self.header)
        self.assertIn("#define START_Y 1668", self.header)

    def test_table_matches_the_arcade_rom(self):
        for i, (count, hz, xs, ys) in enumerate(self.layouts):
            rom = ROM_LAYOUTS[i]
            self.assertEqual(count, len(rom), f"layout {i}: count")
            self.assertEqual(len(xs), BASE_MAX, f"layout {i}: {len(xs)} x values")
            self.assertEqual(len(ys), BASE_MAX, f"layout {i}: {len(ys)} y values")
            for b, (x, y, o) in enumerate(rom):
                self.assertEqual((xs[b], ys[b]), (x, y), f"layout {i} base {b}")
                self.assertEqual((hz >> b) & 1, 1 if o == "H" else 0,
                                 f"layout {i} base {b}: orientation")
            for b in range(count, BASE_MAX):
                self.assertEqual((xs[b], ys[b]), (0, 0), f"layout {i}: unused slot {b}")
            self.assertLess(hz, 1 << count)

    def test_round_sequence_matches_the_arcade_rom(self):
        self.assertEqual(self.seq, ROM_ROUND_SEQ)
        self.assertEqual(layout_of_round(self.seq, 1), 0)
        self.assertEqual(layout_of_round(self.seq, 2), 1)
        for r in range(18, 60):
            self.assertEqual(layout_of_round(self.seq, r), layout_of_round(self.seq, r - 6))
        self.assertEqual(layout_of_round(self.seq, 18), layout_of_round(self.seq, 12))
        # the code does the same: subtract 6 until the round is 17 or less
        self.assertIn("while (round_no > 17) round_no -= 6;", self.text)

    def test_arcade_counts(self):
        self.assertEqual(self.layouts[layout_of_round(self.seq, 1)][0], 3, "round 1 has three bases")
        self.assertEqual(self.layouts[layout_of_round(self.seq, 2)][0], 4, "round 2 has four bases")
        for r in range(3, 18):
            self.assertEqual(self.layouts[layout_of_round(self.seq, r)][0], 8, f"round {r} has eight")

    def test_bases_inside_the_world(self):
        for i, rom in enumerate(ROM_LAYOUTS):
            for b, (x, y, _o) in enumerate(rom):
                self.assertTrue(0 <= x < WORLD_W, f"layout {i} base {b} x")
                self.assertTrue(0 <= y < WORLD_H, f"layout {i} base {b} y")

    def test_bases_do_not_overlap(self):
        for i, rom in enumerate(ROM_LAYOUTS):
            for b, (x, y, o) in enumerate(rom):
                w, h = BASE_SIZE[o]
                for c in range(b + 1, len(rom)):
                    x2, y2, o2 = rom[c]
                    w2, h2 = BASE_SIZE[o2]
                    dx = abs(wrap_delta(x, x2, WORLD_W))
                    dy = abs(wrap_delta(y, y2, WORLD_H))
                    self.assertTrue(dx >= (w + w2) // 2 or dy >= (h + h2) // 2,
                                    f"layout {i}: bases {b} and {c} overlap")

    def test_start_is_clear_of_every_core_and_cannon(self):
        for i, rom in enumerate(ROM_LAYOUTS):
            for b, (x, y, o) in enumerate(rom):
                dx = wrap_delta(START[0], x, WORLD_W)
                dy = wrap_delta(START[1], y, WORLD_H)
                cw, ch = CORE_BOX[o]
                self.assertFalse(abs(dx) < (16 + cw) // 2 and abs(dy) < (16 + ch) // 2,
                                 f"layout {i}: the ship starts inside base {b}'s core")
                for k, (ox, oy) in enumerate(CANNONS[o]):
                    self.assertFalse(abs(dx - ox) < 16 and abs(dy - oy) < 16,
                                     f"layout {i}: the ship starts on base {b} cannon {k}")

    def test_round_1_bases_are_ahead_of_the_start(self):
        rom = ROM_LAYOUTS[layout_of_round(self.seq, 1)]
        for x, y, _o in rom:
            self.assertLess(y, START[1], "round-1 bases lie above the start (the ship flies up)")
            self.assertLess(abs(wrap_delta(x, START[0], WORLD_W)), 200)
            self.assertLess(START[1] - y, 500)

    def test_game_uses_the_table(self):
        with open(os.path.join(ROOT, "game.c")) as f:
            game = f.read()
        self.assertIn("round_layout(round_no)", game)
        self.assertIn("base_x[b] = rd->x[b];", game)
        self.assertIn("base_hz[b] = (rd->hz >> b) & 1;", game)
        self.assertNotIn("base_cell_cx", game, "the old random 3x3 placement is gone")


if __name__ == "__main__":
    unittest.main()
