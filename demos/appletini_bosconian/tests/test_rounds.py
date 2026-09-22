#!/usr/bin/env python3
"""Checks on the round layout table in rounds.c (docs/DESIGN.md section 10).

Parses the C table (no compiler needed) and checks that every layout keeps
its bases apart from each other and from the ship's start position, that
the documented arcade counts hold (three bases in round 1, four in round 2,
never more than BASE_MAX), that coordinates stay inside the 1536x1536 world
and that the repeat sequence only names existing layouts.

Run:  python3 tests/test_rounds.py        (from the project directory)
"""

import math
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

WORLD_UNITS = 1536 // 8          # coordinates are world pixels / 8
START = (768 // 8, 768 // 8)
BASE_MAX = 8
MIN_BASE_GAP = 16                # 128 px: two 64x72 px bases never overlap
MIN_START_GAP = 24               # 192 px: the ship never starts inside a base


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


def parse_repeat_seq(text):
    m = re.search(r"repeat_seq\[6\]\s*=\s*\{([^}]*)\}", text)
    return [int(v) for v in m.group(1).split(",")]


class RoundTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "rounds.c")) as f:
            cls.text = f.read()
        with open(os.path.join(ROOT, "game.h")) as f:
            cls.header = f.read()
        cls.layouts = parse_layouts(cls.text)
        cls.seq = parse_repeat_seq(cls.text)

    def test_table_size_matches_header(self):
        n = int(re.search(r"#define ROUND_LAYOUTS (\d+)", self.header).group(1))
        self.assertEqual(len(self.layouts), n)
        self.assertGreaterEqual(n, 11, "rounds 1..11 have their own layouts")

    def test_arcade_counts(self):
        self.assertEqual(self.layouts[0][0], 3, "round 1 has three bases")
        self.assertEqual(self.layouts[1][0], 4, "round 2 has four bases")
        for i, (count, hz, xs, ys) in enumerate(self.layouts):
            self.assertTrue(3 <= count <= BASE_MAX, f"layout {i + 1}: count {count}")
            self.assertEqual(len(xs), BASE_MAX, f"layout {i + 1}: {len(xs)} x values")
            self.assertEqual(len(ys), BASE_MAX, f"layout {i + 1}: {len(ys)} y values")
            self.assertLess(hz, 1 << BASE_MAX)
            for b in range(count, BASE_MAX):
                self.assertEqual((xs[b], ys[b]), (0, 0), f"layout {i + 1}: unused slot {b}")

    def test_counts_never_decrease_in_the_first_rounds(self):
        counts = [lay[0] for lay in self.layouts[:5]]
        self.assertEqual(counts, sorted(counts), f"rounds 1-5 counts {counts}")

    def test_bases_inside_the_world(self):
        for i, (count, _hz, xs, ys) in enumerate(self.layouts):
            for b in range(count):
                self.assertTrue(0 <= xs[b] < WORLD_UNITS, f"layout {i + 1} base {b} x")
                self.assertTrue(0 <= ys[b] < WORLD_UNITS, f"layout {i + 1} base {b} y")

    def test_bases_apart_from_each_other_and_from_the_start(self):
        def wrap_dist(a, b):
            dx = abs(a[0] - b[0])
            dy = abs(a[1] - b[1])
            dx = min(dx, WORLD_UNITS - dx)
            dy = min(dy, WORLD_UNITS - dy)
            return math.hypot(dx, dy)

        for i, (count, _hz, xs, ys) in enumerate(self.layouts):
            pts = [(xs[b], ys[b]) for b in range(count)]
            for b, p in enumerate(pts):
                self.assertGreaterEqual(
                    wrap_dist(p, START), MIN_START_GAP,
                    f"layout {i + 1} base {b} at {p} is on top of the start")
                for c in range(b + 1, count):
                    self.assertGreaterEqual(
                        wrap_dist(p, pts[c]), MIN_BASE_GAP,
                        f"layout {i + 1} bases {b} and {c} overlap: {p} {pts[c]}")

    def test_round_1_is_a_close_triangle_around_the_start(self):
        count, _hz, xs, ys = self.layouts[0]
        pts = [(xs[b], ys[b]) for b in range(count)]
        # every base within 3 screens (768 px = 96 units) of the start
        for p in pts:
            self.assertLessEqual(math.hypot(p[0] - START[0], p[1] - START[1]), 96)
        # the start lies inside the triangle
        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        signs = [cross(pts[k], pts[(k + 1) % 3], START) for k in range(3)]
        self.assertTrue(all(s > 0 for s in signs) or all(s < 0 for s in signs),
                        f"start {START} is outside the round-1 triangle {pts}")

    def test_repeat_sequence_names_existing_layouts(self):
        self.assertEqual(len(self.seq), 6)
        for idx in self.seq:
            self.assertTrue(0 <= idx < len(self.layouts), f"repeat index {idx}")
        # rounds 12.. never repeat rounds 1 and 2 (the easy layouts)
        self.assertNotIn(0, self.seq)
        self.assertNotIn(1, self.seq)

    def test_game_uses_the_table(self):
        with open(os.path.join(ROOT, "game.c")) as f:
            game = f.read()
        self.assertIn("round_layout(round_no)", game)
        self.assertNotIn("base_cell_cx", game, "the old random 3x3 placement is gone")
        self.assertIn("base_hz[b]", game, "pods follow the base orientation")


if __name__ == "__main__":
    unittest.main()
