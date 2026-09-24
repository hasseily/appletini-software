#!/usr/bin/env python3
"""Unit tests of the renderer (src/render.s, src/video.s, src/cdraw.s) in
the linked build, through tools/pcsdbg.py (docs/DESIGN.md section 4).

Run:  python3 tests/test_render.py        (from the project directory)

build/PCS.SYSTEM and build/PCS.lbl are used as they are (make is run when
they are missing). Each test class boots one py65 machine to the editor
(two frames) and then calls the routines directly with their inputs set in
zero page or BSS, the way the port's own code does:

  fill_span        odd and even span ends, clipping to the rectangle
  render_row       a synthetic row of span records (border, black, colours)
  blit_sprite      clipping on all four sides, negative x/y, odd x; the
                   arena is compared with the sprite decoded by
                   tools/gen_assets.py's decode_variant
  rd_mark          clamping to the table, even/odd rounding, the full list
  merge_rects      touching and overlapping rectangles join, others do not
  rd_mark_record   a bitmap record marks its own box less the hot y
  cur_show/hide    the save-under round trip restores the screen bytes
  panel_fill       whole-byte fills at odd edges, bands taller than the arena
  record_id / record_sprite_id   ids above 63, the first bad pointers
  vertex dots      points tools and black polygons finish a bounded redraw
  DOMENU           the item under the cursor is selected, none otherwise
  CHARTO/PRINT     glyph placement and advance, text only in the panel

The //e ROM comes from $APPLETINI_ROOT/docs/Apple2e_Enhanced.rom; the port
never reads it in the test machine, so a blank ROM stands in when the
file is missing.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "tools"
BUILD = PROJECT / "build"
sys.path.insert(0, str(TOOLS))

import gen_assets  # noqa: E402
import run_editor  # noqa: E402

try:
    import pcsdbg  # noqa: E402
except ImportError:      # pragma: no cover
    pcsdbg = None

# src/pcs.inc
ARENA = 0xBB00
ARENA_ROWS = 13
SHR_BASE = 0x2000
SHR_ROW = 160
TABLE_W, TABLE_H, PANEL_X = 154, 192, 154
SCREEN_W, SCREEN_H = 320, 200
COL_PANEL, COL_TEXT, COL_HILITE = 1, 3, 8
PARAM, YTEMP = 0x00, 0x09
CURSORY, CURSORX, CURSORXH = 0x82, 0x83, 0x84
NEWITEM, LASTITEM = 0x8D, 0x8F
MB_MOUSEX, MB_MOUSEY = 0x030C, 0x030E
RD_MAX = 32
SPR_COUNT = 135
SPR_CUR_HAND = 100
SPR_BALL_0, SPR_BMP1_0, SPR_LFLIP_0 = 22, 23, 6
SPR_BMP1_W, SPR_BMP1_H = 21, 14
FONT_SPACE = 36


def ensure_build() -> None:
    if not (BUILD / "PCS.SYSTEM").exists() or not (BUILD / "PCS.lbl").exists():
        subprocess.run(["make"], cwd=PROJECT, check=True, capture_output=True)


def rom_fallback() -> None:
    """A blank 16 KB ROM when the //e ROM is not where run_editor looks."""
    if not Path(run_editor.DEFAULT_ROM).exists():
        blank = Path(tempfile.gettempdir()) / "pcs_test_blank_rom.bin"
        if not blank.exists() or blank.stat().st_size != 0x4000:
            blank.write_bytes(bytes(0x4000))
        run_editor.DEFAULT_ROM = blank


def boot(frames: int = 2):
    ensure_build()
    rom_fallback()
    with contextlib.redirect_stdout(io.StringIO()):
        return pcsdbg.Dbg(frames=frames)


def nibbles(data: bytes) -> list[int]:
    return [n for b in data for n in (b >> 4, b & 15)]


def sprite_grid(d, sid: int, odd: bool):
    """The sprite's even or odd variant decoded from where the loader put it."""
    addr = d.w(d.L["spr_dir"] + 4 * sid + (2 if odd else 0))
    bank = d.mem[d.L["spr_bank"] + sid]
    if bank == gen_assets.BANK_RODATA:
        data = bytes(d.mem[addr:addr + 0x1000])
    else:
        altzp = bool(bank & gen_assets.BANK_AUX)
        if bank & gen_assets.BANK_1 and addr < 0xE000:
            data = bytes(d.m.lc_bank1[altzp][addr - 0xD000:])
        else:
            data = bytes(d.m.lc[altzp][addr - 0xC000:])
    grid, _used = gen_assets.decode_variant(data)
    return grid


def expected_blit(grid, x, y, cx0, cx1, cy0, cy1, fill):
    """The arena after drawing the grid at (x, y) over a `fill` nibble: a
    nibble 0 or a pixel outside every run leaves the arena alone."""
    out = [[fill] * (cx1 - cx0 + 1) for _ in range(cy1 - cy0 + 1)]
    base = x & ~1
    for r, row in enumerate(grid):
        sy = y + r
        if not cy0 <= sy <= cy1:
            continue
        for p, v in enumerate(row):
            sx = base + p
            if v and cx0 <= sx <= cx1:
                out[sy - cy0][sx - cx0] = v
    return out


@unittest.skipUnless(pcsdbg, "py65 not installed")
class RenderCase(unittest.TestCase):
    d = None

    @classmethod
    def setUpClass(cls):
        cls.d = boot()

    # -- arena --------------------------------------------------------
    def arena_fill(self, stride, rows, byte=0xEE):
        self.d.mem[ARENA:ARENA + stride * rows] = bytes([byte]) * (stride * rows)

    def arena(self, stride, rows):
        return [nibbles(self.d.mem[ARENA + stride * r:ARENA + stride * (r + 1)]) for r in range(rows)]

    # -- screen -------------------------------------------------------
    def pixel(self, x, y):
        b = self.d.aux[SHR_BASE + SHR_ROW * y + x // 2]
        return b >> 4 if x % 2 == 0 else b & 15

    def row_bytes(self, y, c0, c1):
        return bytes(self.d.aux[SHR_BASE + SHR_ROW * y + c0:SHR_BASE + SHR_ROW * y + c1 + 1])


class TestVertexDots(RenderCase):
    def test_points_tools_and_black_polygon_redraw(self):
        d = self.d
        # Pointer, Scissor and Hammer all enable RD_POINTS. Before the fix,
        # the first visible vertex sent dot's row counter through a loop.
        limit = 800_000
        self.assertNotEqual(self.pixel(3, 30), 4)
        d.set("rd_flags", d.get("rd_flags") | 0x40)
        d.set("dr_all", 0x80)
        steps = d.call("rd_frame", limit=limit)
        self.assertLess(steps, limit, "points-mode redraw did not finish")
        self.assertEqual(self.pixel(3, 30), 4)

        # A black polygon draws its vertices even with the Hand tool.
        pbd = d.L["PBDATA"]
        wall = pbd + 1 + d.mem[pbd]
        d.mem[wall + 1] = 0
        d.set("rd_flags", 0)
        d.set("dr_all", 0x80)
        steps = d.call("rd_frame", limit=limit)
        self.assertLess(steps, limit, "black-polygon redraw did not finish")
        self.assertEqual(self.pixel(3, 30), 4)


class TestFillSpan(RenderCase):
    """fill_span: pixels R_A..R_B of the arena row in R_C, clipped to R_X0..R_X1."""

    def fill(self, x0, x1, a, b, c, fill=0xEE):
        d = self.d
        stride = (x1 - x0) // 2 + 1
        self.arena_fill(stride, 1, fill)
        d.set("R_X0", x0)
        d.set("R_X1", x1)
        d.set("R_A", a)
        d.set("R_B", b)
        d.set("R_C", c)
        d.set("R_DST", ARENA, 2)
        d.call("fill_span")
        return self.arena(stride, 1)[0]

    @staticmethod
    def model(x0, x1, a, b, c, fill=0xE):
        row = [fill] * (x1 - x0 + 1)
        for x in range(max(a, x0), min(b, x1) + 1):
            row[x - x0] = c
        return row

    def check(self, x0, x1, a, b, c):
        self.assertEqual(self.fill(x0, x1, a, b, c), self.model(x0, x1, a, b, c),
                         f"span {a}..{b} colour {c} in {x0}..{x1}")

    def test_even_ends(self):
        self.check(0, 153, 10, 20, 6)

    def test_odd_start_even_end(self):
        self.check(0, 153, 11, 20, 6)

    def test_even_start_odd_end(self):
        self.check(0, 153, 10, 21, 6)

    def test_odd_both_ends(self):
        self.check(0, 153, 11, 21, 6)

    def test_single_pixel_even_and_odd(self):
        self.check(0, 153, 40, 40, 4)
        self.check(0, 153, 41, 41, 4)
        self.check(20, 41, 41, 41, 4)      # the last pixel of the rectangle

    def test_two_pixels_in_one_byte_and_across_bytes(self):
        self.check(0, 153, 40, 41, 12)
        self.check(0, 153, 41, 42, 12)

    def test_clipped_on_the_left(self):
        self.check(50, 99, 30, 60, 7)
        self.check(50, 99, 30, 61, 7)

    def test_clipped_on_the_right(self):
        self.check(50, 99, 90, 140, 7)
        self.check(50, 99, 91, 200, 7)
        self.check(50, 99, 91, 255, 7)

    def test_spanning_the_rectangle(self):
        self.check(50, 99, 0, 255, 10)
        self.check(0, 153, 0, 153, 10)

    def test_outside_leaves_the_row_alone(self):
        self.check(50, 99, 0, 49, 10)
        self.check(50, 99, 100, 200, 10)
        self.check(50, 99, 60, 55, 10)     # B < A: nothing

    def test_colours_fill_both_nibbles(self):
        row = self.fill(0, 7, 0, 7, 15, fill=0)
        self.assertEqual(row, [15] * 8)
        row = self.fill(0, 7, 2, 5, 9, fill=0x11)
        self.assertEqual(row, [1, 1, 9, 9, 9, 9, 1, 1])

    def test_scratch_row_beyond_the_span_is_untouched(self):
        d = self.d
        self.arena_fill(80, 2, 0x33)
        d.set("R_X0", 0)
        d.set("R_X1", 153)
        d.set("R_A", 150)
        d.set("R_B", 153)
        d.set("R_C", 5)
        d.set("R_DST", ARENA, 2)
        d.call("fill_span")
        rows = self.arena(80, 2)
        self.assertEqual(rows[0][150:154], [5] * 4)
        self.assertEqual(rows[0][154:160], [3] * 6)   # bytes past the row's 77
        self.assertEqual(rows[1], [3] * 160)


class TestRenderRow(RenderCase):
    """render_row on a synthetic row: border colour outside object 0's spans,
    black inside, then every record in order; inviso paints nothing."""

    def test_synthetic_row(self):
        d = self.d
        L = d.L
        y = 100
        pbdx = L["PBDX"] + y
        saved = (d.mem[pbdx], bytes(d.mem[L["objcolor"]:L["objcolor"] + 4]),
                 d.mem[L["rd_flags"]], d.mem[L["ov_enabled"]])
        records = [(10, 0, 140, 0), (20, 1, 30, 0), (50, 2, 60, 0), (100, 3, 200, 0)]
        buf = L["P1STATE"]
        for i, rec in enumerate(records):
            d.mem[buf + 4 * i:buf + 4 * i + 4] = bytes(rec)
        try:
            d.mem[pbdx] = 4 * len(records)
            d.mem[L["objcolor"]:L["objcolor"] + 4] = bytes([11, 6, 0x10, 4])
            d.mem[L["rd_flags"]] = 0
            d.mem[L["ov_enabled"]] = 0
            d.set("R_Y", y)
            d.set("R_ROW", buf, 2)
            d.set("R_X0", 0)
            d.set("R_X1", 153)
            d.set("R_DST", ARENA, 2)
            d.set("arena_stride", 77)       # render_rect's job
            self.arena_fill(77, 1, 0xEE)
            d.call("render_row")
        finally:
            d.mem[pbdx] = saved[0]
            d.mem[L["objcolor"]:L["objcolor"] + 4] = saved[1]
            d.mem[L["rd_flags"]] = saved[2]
            d.mem[L["ov_enabled"]] = saved[3]
        row = self.arena(77, 1)[0]
        expected = [11] * 154
        for x in range(10, 141):
            expected[x] = 0                 # inside the border: black
        for x in range(20, 31):
            expected[x] = 6
        for x in range(100, 154):
            expected[x] = 4                 # clipped at the table edge
        self.assertEqual(row, expected)

    def test_hidden_polygons_paint_nothing(self):
        d = self.d
        L = d.L
        saved = d.mem[L["rd_flags"]], d.mem[L["ov_enabled"]]
        try:
            d.mem[L["rd_flags"]] = 0x80         # RD_HIDEPOLYS
            d.mem[L["ov_enabled"]] = 0
            d.set("R_Y", 100)
            d.set("R_ROW", L["P1STATE"], 2)
            d.set("R_X0", 0)
            d.set("R_X1", 153)
            d.set("R_DST", ARENA, 2)
            d.set("arena_stride", 77)
            self.arena_fill(77, 1, 0xEE)
            d.call("render_row")
        finally:
            d.mem[L["rd_flags"]], d.mem[L["ov_enabled"]] = saved
        self.assertEqual(self.arena(77, 1)[0], [0] * 154)


class TestBlitSprite(RenderCase):
    """blit_sprite into an arena rectangle, compared with the decoded variant."""

    def blit(self, sid, x, y, cx0, cx1, cy0, cy1, fill=0xEE):
        d = self.d
        stride = (cx1 - cx0) // 2 + 1
        rows = cy1 - cy0 + 1
        self.arena_fill(stride, rows, fill)
        d.set("bl_id", sid)
        d.set("bl_x", x & 0xFFFF, 2)
        d.set("bl_y", y & 0xFFFF, 2)
        d.set("bl_cx0", cx0, 2)
        d.set("bl_cx1", cx1, 2)
        d.set("bl_cy0", cy0)
        d.set("bl_cy1", cy1)
        d.set("arena_stride", stride)
        d.call("sprite_bank", a=sid)
        d.call("blit_sprite", altzp=True)
        return self.arena(stride, rows)

    def check(self, sid, x, y, cx0, cx1, cy0, cy1):
        grid = sprite_grid(self.d, sid, bool(x & 1))
        self.assertEqual(self.blit(sid, x, y, cx0, cx1, cy0, cy1),
                         expected_blit(grid, x, y, cx0, cx1, cy0, cy1, 0xE),
                         f"sprite {sid} at ({x},{y}) in {cx0}..{cx1} x {cy0}..{cy1}")

    def test_sprites_have_the_expected_shape(self):
        d = self.d
        self.assertEqual((d.mem[d.L["spr_w"] + SPR_BMP1_0], d.mem[d.L["spr_h"] + SPR_BMP1_0]),
                         (SPR_BMP1_W, SPR_BMP1_H))
        even = sprite_grid(d, SPR_BMP1_0, False)
        odd = sprite_grid(d, SPR_BMP1_0, True)
        self.assertEqual(len(even), SPR_BMP1_H)
        # the odd variant is the even one shifted right by one pixel
        for r in range(SPR_BMP1_H):
            self.assertEqual([v or None for v in [None] + even[r]][:len(odd[r])],
                             [v or None for v in odd[r]], f"row {r}")
        self.assertTrue(any(v for row in even for v in row), "BMP1 has no pixels")

    def test_unclipped_even_and_odd_x(self):
        self.check(SPR_BMP1_0, 20, 3, 0, 153, 0, 12)
        self.check(SPR_BMP1_0, 21, 3, 0, 153, 0, 12)
        self.check(SPR_BALL_0, 7, 1, 0, 153, 0, 12)

    def test_clipped_left(self):
        self.check(SPR_BMP1_0, 40, 2, 50, 99, 0, 12)     # 21 wide: columns 40..60
        self.check(SPR_BMP1_0, 41, 2, 50, 99, 0, 12)
        self.check(SPR_BMP1_0, 49, 2, 50, 99, 0, 12)

    def test_clipped_right(self):
        self.check(SPR_BMP1_0, 90, 2, 50, 99, 0, 12)
        self.check(SPR_BMP1_0, 97, 2, 50, 99, 0, 12)
        self.check(SPR_BMP1_0, 140, 2, 0, 153, 0, 12)    # the table edge

    def test_clipped_top(self):
        self.check(SPR_BMP1_0, 60, 30, 50, 99, 36, 48)   # rows 30..43: the first six cut
        self.check(SPR_BMP1_0, 60, 43, 50, 99, 44, 56)   # ends one row above the band

    def test_clipped_bottom(self):
        self.check(SPR_BMP1_0, 60, 40, 50, 99, 36, 48)   # rows 40..53: the last five cut
        self.check(SPR_BMP1_0, 60, 48, 50, 99, 36, 48)   # one row inside

    def test_negative_x_and_y(self):
        self.check(SPR_BMP1_0, -3, 4, 0, 153, 0, 12)
        self.check(SPR_BMP1_0, -20, 4, 0, 153, 0, 12)
        self.check(SPR_BMP1_0, 10, -5, 0, 153, 0, 12)
        self.check(SPR_LFLIP_0, -1, -1, 0, 153, 0, 12)

    def test_entirely_outside_leaves_the_arena(self):
        for x, y in ((-30, 2), (100, 2), (20, 20), (20, -20), (300, 2)):
            self.assertEqual(self.blit(SPR_BMP1_0, x, y, 50, 99, 0, 12), [[0xE] * 50] * 13,
                             f"sprite at ({x},{y}) should be clipped away")

    def test_transparent_pixels_keep_the_arena(self):
        grid = sprite_grid(self.d, SPR_BMP1_0, False)
        holes = [(r, p) for r, row in enumerate(grid) for p, v in enumerate(row) if not v]
        self.assertTrue(holes, "BMP1 has no transparent pixel to test")
        out = self.blit(SPR_BMP1_0, 20, 0, 0, 153, 0, 13, 0x77)
        for r, p in holes:
            self.assertEqual(out[r][20 + p], 7, f"hole at row {r} pixel {p} was painted")


class TestDirtyRects(RenderCase):
    """rd_mark clamping and rounding, merge_rects, rd_mark_record."""

    def setUp(self):
        self.d.set("dr_n", 0)
        self.d.set("dr_all", 0)

    def tearDown(self):
        self.d.set("dr_n", 0)
        self.d.set("dr_all", 0)

    def mark(self, x0, y0, x1, y1):
        d = self.d
        d.set("rd_ax0", x0)
        d.set("rd_ay0", y0)
        d.set("rd_ax1", x1)
        d.set("rd_ay1", y1)
        d.call("rd_mark")

    def rects(self):
        d = self.d
        n = d.get("dr_n")
        L = d.L
        return [(d.mem[L["dr_x0"] + i], d.mem[L["dr_y0"] + i], d.mem[L["dr_x1"] + i], d.mem[L["dr_y1"] + i])
                for i in range(n)]

    def put(self, rects):
        d = self.d
        L = d.L
        for i, (x0, y0, x1, y1) in enumerate(rects):
            d.mem[L["dr_x0"] + i] = x0
            d.mem[L["dr_y0"] + i] = y0
            d.mem[L["dr_x1"] + i] = x1
            d.mem[L["dr_y1"] + i] = y1
        d.set("dr_n", len(rects))

    def test_rounding_to_byte_columns(self):
        self.mark(5, 10, 6, 20)
        self.assertEqual(self.rects(), [(4, 10, 7, 20)])

    def test_clamping_to_the_table(self):
        self.mark(151, 100, 200, 250)
        self.assertEqual(self.rects(), [(150, 100, 153, 191)])

    def test_registers_are_preserved(self):
        d = self.d
        d.set("rd_ax0", 0)
        d.set("rd_ay0", 0)
        d.set("rd_ax1", 3)
        d.set("rd_ay1", 3)
        d.call("rd_mark", a=0x12, x=0x34, y=0x56)
        self.assertEqual((d.mpu.x, d.mpu.y), (0x34, 0x56))

    def test_one_row_is_a_rectangle(self):
        self.mark(0, 50, 153, 50)
        self.assertEqual(self.rects(), [(0, 50, 153, 50)])

    def test_empty_and_off_table_are_dropped(self):
        self.mark(154, 0, 200, 10)          # in the panel
        self.mark(10, 60, 20, 50)           # y1 < y0
        self.mark(20, 0, 10, 10)            # x1 < x0 (after rounding: 20 > 11)
        self.assertEqual(self.rects(), [])

    def test_full_list_marks_the_whole_table(self):
        for i in range(RD_MAX):
            self.mark(0, i, 1, i)
        self.assertEqual(self.d.get("dr_n"), RD_MAX)
        self.assertEqual(self.d.get("dr_all"), 0)
        self.mark(0, 100, 1, 100)
        self.assertEqual(self.d.get("dr_n"), RD_MAX)
        self.assertEqual(self.d.get("dr_all"), 0x80)

    def test_rd_mark_all(self):
        self.d.call("rd_mark_all")
        self.assertEqual(self.d.get("dr_all"), 0x80)

    def test_merge_touching(self):
        self.put([(0, 0, 7, 7), (8, 0, 15, 7)])
        self.d.call("merge_rects")
        self.assertEqual(self.rects(), [(0, 0, 15, 7)])
        self.put([(0, 0, 7, 7), (0, 8, 7, 15)])
        self.d.call("merge_rects")
        self.assertEqual(self.rects(), [(0, 0, 7, 15)])

    def test_merge_overlapping(self):
        self.put([(10, 10, 31, 30), (20, 20, 51, 40)])
        self.d.call("merge_rects")
        self.assertEqual(self.rects(), [(10, 10, 51, 40)])

    def test_apart_stay_apart(self):
        self.put([(0, 0, 7, 7), (10, 0, 17, 7), (0, 9, 7, 17)])
        self.d.call("merge_rects")
        self.assertEqual(sorted(self.rects()), [(0, 0, 7, 7), (0, 9, 7, 17), (10, 0, 17, 7)])

    def test_chain_merges_through_a_bridge(self):
        # the first and the third touch only through the second
        self.put([(0, 0, 7, 7), (40, 0, 47, 7), (8, 0, 39, 7)])
        self.d.call("merge_rects")
        self.assertEqual(self.rects(), [(0, 0, 47, 7)])

    def test_merge_keeps_the_others(self):
        self.put([(0, 0, 7, 7), (100, 100, 111, 111), (8, 0, 15, 7), (60, 60, 61, 61)])
        self.d.call("merge_rects")
        self.assertEqual(sorted(self.rects()), [(0, 0, 15, 7), (60, 60, 61, 61), (100, 100, 111, 111)])

    def test_mark_record(self):
        d = self.d
        buf = d.L["P1STATE"]
        ptr = d.L["spr_dir"] + 4 * SPR_BMP1_0
        d.mem[buf:buf + 7] = bytes([ptr & 255, ptr >> 8, 30, 20, 0, SPR_BMP1_H, SPR_BMP1_W])
        d.call("rd_mark_record", a=buf & 255, x=buf >> 8)
        self.assertEqual(self.rects(), [(20, 30, 41, 43)])
        # a flipper's box starts hot-y rows above its record y
        hoty = d.mem[d.L["spr_hoty"] + SPR_LFLIP_0]
        self.assertGreater(hoty, 0)
        ptr = d.L["spr_dir"] + 4 * SPR_LFLIP_0
        w, h = d.mem[d.L["spr_w"] + SPR_LFLIP_0], d.mem[d.L["spr_h"] + SPR_LFLIP_0]
        d.mem[buf:buf + 7] = bytes([ptr & 255, ptr >> 8, 100, 50, 0, h, w])
        self.d.set("dr_n", 0)
        d.call("rd_mark_record", a=buf & 255, x=buf >> 8)
        self.assertEqual(self.rects(), [(50, 100 - hoty, (50 + w - 1) | 1, 100 - hoty + h - 1)])

    def test_mark_record_ignores_the_panel(self):
        d = self.d
        buf = d.L["P1STATE"]
        ptr = d.L["spr_dir"] + 4 * SPR_BMP1_0
        d.mem[buf:buf + 7] = bytes([ptr & 255, ptr >> 8, 30, 200, 0, SPR_BMP1_H, SPR_BMP1_W])
        d.call("rd_mark_record", a=buf & 255, x=buf >> 8)
        d.mem[buf:buf + 7] = bytes([ptr & 255, ptr >> 8, 30, 44, 1, SPR_BMP1_H, SPR_BMP1_W])
        d.call("rd_mark_record", a=buf & 255, x=buf >> 8)
        self.assertEqual(self.rects(), [])


class TestCursor(RenderCase):
    """cur_show saves the bytes under the cursor and draws it; cur_hide puts
    them back."""

    def region(self, x, y, w, h):
        c0 = max(0, (x & ~1) // 2 - 1)
        c1 = min(SHR_ROW - 1, (x & ~1) // 2 + (w + 2) // 2)
        rows = range(max(0, y - 1), min(SCREEN_H, y + h + 1))
        return [(r, self.row_bytes(r, c0, c1)) for r in rows]

    def round_trip(self, x, y, sid=SPR_CUR_HAND, min_drawn=10):
        d = self.d
        d.call("cur_hide")
        self.assertEqual(d.get("cur_vis"), 0)
        w, h = d.mem[d.L["spr_w"] + sid], d.mem[d.L["spr_h"] + sid]
        # a pattern of non-zero nibbles under and around the cursor
        for r in range(max(0, y - 1), min(SCREEN_H, y + h + 1)):
            for c in range(max(0, (x & ~1) // 2 - 1), min(SHR_ROW, (x & ~1) // 2 + (w + 2) // 2 + 1)):
                d.aux[SHR_BASE + SHR_ROW * r + c] = 0x11 * ((r + c) % 15 + 1)
        before = self.region(x, y, w, h)
        d.set("cur_id", sid)
        d.set("cur_x", x, 2)
        d.set("cur_y", y)
        d.call("cur_show")
        self.assertEqual(d.get("cur_vis"), 0x80)
        grid = sprite_grid(d, sid, bool(x & 1))
        drawn = 0
        for r, row in enumerate(grid):
            sy = y + r
            if sy >= SCREEN_H:
                continue
            for p, v in enumerate(row):
                sx = (x & ~1) + p
                if sx >= SCREEN_W:
                    continue
                pixel_before = (0x11 * ((sy + sx // 2) % 15 + 1)) & 15
                if v:
                    drawn += 1
                    self.assertEqual(self.pixel(sx, sy), v, f"cursor pixel ({sx},{sy})")
                else:
                    self.assertEqual(self.pixel(sx, sy), pixel_before, f"kept pixel ({sx},{sy})")
        self.assertGreaterEqual(drawn, min_drawn)
        if drawn:
            self.assertNotEqual(self.region(x, y, w, h), before)
        d.call("cur_hide")
        self.assertEqual(d.get("cur_vis"), 0)
        self.assertEqual(self.region(x, y, w, h), before, "cur_hide did not restore the screen")
        d.call("cur_hide")                  # a second hide is a no-op
        self.assertEqual(self.region(x, y, w, h), before)

    def test_round_trip_even_x(self):
        self.round_trip(200, 50)

    def test_round_trip_odd_x(self):
        self.round_trip(201, 51)

    def test_round_trip_in_the_table(self):
        self.round_trip(3, 5)

    def test_round_trip_clipped_right_and_bottom(self):
        self.round_trip(310, 190)
        self.round_trip(319, 199, min_drawn=1)     # one pixel left on the screen

    def test_show_twice_saves_once(self):
        d = self.d
        d.call("cur_hide")
        d.set("cur_id", SPR_CUR_HAND)
        d.set("cur_x", 220, 2)
        d.set("cur_y", 60)
        d.call("cur_show")
        saved = bytes(d.mem[d.L["cur_save"]:d.L["cur_save"] + 32])
        d.call("cur_show")                  # already visible: nothing saved again
        self.assertEqual(bytes(d.mem[d.L["cur_save"]:d.L["cur_save"] + 32]), saved)
        d.call("cur_hide")


class TestPanelFill(RenderCase):
    """panel_fill works on whole bytes: x0 rounded down, x1 rounded up."""

    def fill(self, x0, x1, y0, y1, colour):
        d = self.d
        d.set("pf_x0", x0, 2)
        d.set("pf_x1", x1, 2)
        d.set("pf_y0", y0)
        d.set("pf_y1", y1)
        d.set("pf_color", colour)
        d.call("panel_fill")

    def test_odd_edges_round_to_bytes(self):
        for y in (100, 101):
            for c in range(130, 138):
                self.d.aux[SHR_BASE + SHR_ROW * y + c] = 0x22
        self.fill(267, 270, 100, 100, 8)
        self.assertEqual(self.row_bytes(100, 130, 137), bytes([0x22, 0x22, 0x22, 0x88, 0x88, 0x88, 0x22, 0x22]))
        self.assertEqual(self.row_bytes(101, 130, 137), bytes([0x22] * 8))

    def test_one_pixel_wide_fills_its_byte(self):
        for c in range(130, 138):
            self.d.aux[SHR_BASE + SHR_ROW * 110 + c] = 0x22
        self.fill(267, 267, 110, 110, 6)
        self.assertEqual(self.row_bytes(110, 132, 135), bytes([0x22, 0x66, 0x22, 0x22]))
        self.fill(268, 268, 110, 110, 6)
        self.assertEqual(self.row_bytes(110, 132, 135), bytes([0x22, 0x66, 0x66, 0x22]))

    def test_colour_uses_its_low_nibble(self):
        self.fill(280, 281, 120, 120, 0x1C)
        self.assertEqual(self.row_bytes(120, 140, 140), bytes([0xCC]))

    def test_taller_than_the_arena_fills_every_row(self):
        for y in range(19, 52):
            for c in range(120, 124):
                self.d.aux[SHR_BASE + SHR_ROW * y + c] = 0x22
        self.fill(242, 245, 20, 50, 4)      # 31 rows: three bands
        for y in range(20, 51):
            self.assertEqual(self.row_bytes(y, 120, 123), bytes([0x22, 0x44, 0x44, 0x22]), f"row {y}")
        self.assertEqual(self.row_bytes(19, 120, 123), bytes([0x22] * 4))
        self.assertEqual(self.row_bytes(51, 120, 123), bytes([0x22] * 4))

    def test_hides_the_cursor_first(self):
        d = self.d
        d.call("cur_hide")
        d.set("cur_id", SPR_CUR_HAND)
        d.set("cur_x", 250, 2)
        d.set("cur_y", 140)
        d.call("cur_show")
        self.fill(250, 259, 140, 145, 0)
        self.assertEqual(d.get("cur_vis"), 0)
        self.assertEqual(self.row_bytes(142, 125, 129), bytes(5))


class TestRecordIds(RenderCase):
    """record_sprite_id (render.s, R_TMP) and record_id (cdraw.s, C_PTR)."""

    def ids(self, routine, pointer_var, pointer):
        d = self.d
        buf = d.L["P1STATE"] + 64
        d.mem[buf] = pointer & 255
        d.mem[buf + 1] = (pointer >> 8) & 255
        d.set(pointer_var, buf, 2)
        d.call(routine)
        return d.mpu.x

    def check(self, routine, var):
        spr_dir = self.d.L["spr_dir"]
        for sid in (0, 1, 63, 64, 65, 100, 127, 128, SPR_COUNT - 1):
            self.assertEqual(self.ids(routine, var, spr_dir + 4 * sid), sid, f"{routine}: id {sid}")
        for pointer in (spr_dir + 4 * SPR_COUNT, spr_dir + 4 * 300, spr_dir - 4, 0, 0xFFFF):
            self.assertEqual(self.ids(routine, var, pointer), 0xFF, f"{routine}: pointer ${pointer:04X}")

    def test_record_sprite_id(self):
        self.check("record_sprite_id", "R_TMP")

    def test_record_id(self):
        self.check("record_id", "C_PTR")


class TestMenu(RenderCase):
    """DOMENU: the item under the cursor when the button is released."""

    def build_menu(self):
        """Three items in P1STATE; handler i is `lda #i+1 / sta marker / rts`."""
        d = self.d
        base = d.L["P1STATE"] + 128
        self.marker = base + 200                   # which handler ran
        rects = [(100, 200, 10, 20), (100, 230, 10, 20), (120, 200, 10, 50)]   # top, x, height, width
        items = []
        for i, (top, x, h, w) in enumerate(rects):
            addr = base + 6 * i
            d.mem[addr:addr + 6] = bytes([top, x & 255, x >> 8, h - 1, w & 255, w >> 8])
            handler = base + 64 + 8 * i
            d.mem[handler:handler + 6] = bytes([0xA9, i + 1, 0x8D, self.marker & 255, self.marker >> 8, 0x60])
            items += [addr & 255, addr >> 8, handler & 255, handler >> 8]
        items += [0, 0]
        menu = base + 96
        d.mem[menu:menu + len(items)] = bytes(items)
        d.mem[self.marker] = 0
        return menu

    def cursor_to(self, x, y, button):
        """Publish a mouse position and button, then step two frames with
        frame_step (not run_frames: the CPU is parked in the call driver)."""
        d = self.d
        d.m.mouse_move(x, y)
        d.m.mouse_buttons(button, False)
        d.call("frame_step")
        d.call("frame_step")
        self.assertEqual((d.w(MB_MOUSEX), d.mem[MB_MOUSEY]), (x, y))
        self.assertEqual(d.get("in_btn"), 0x80 if button else 0)
        self.assertEqual((d.mem[CURSORX] | (d.mem[CURSORXH] << 8), d.mem[CURSORY]), (x, y))

    def test_selects_the_item_under_the_cursor(self):
        d = self.d
        menu = self.build_menu()
        for x, y, item in ((240, 105, 2), (210, 105, 1), (240, 125, 3)):
            self.cursor_to(x, y, True)
            d.m.mouse_buttons(False, False)     # released before the menu's first frame
            d.mem[LASTITEM + 1] = 0
            d.mem[self.marker] = 0
            d.call("DOMENU", a=menu & 255, x=menu >> 8)
            self.assertEqual(d.mem[self.marker], item, f"handler for the item at ({x},{y})")
            self.assertEqual(d.mem[YTEMP], 4 * (item - 1), "YTEMP = the item's offset")
            self.assertEqual(d.mem[LASTITEM + 1], 0, "the highlight was not removed")
            self.assertEqual(d.get("hl_n"), 0)

    def test_nothing_under_the_cursor_returns_zero(self):
        d = self.d
        menu = self.build_menu()
        self.cursor_to(300, 150, False)
        d.mem[LASTITEM + 1] = 0
        d.call("DOMENU", a=menu & 255, x=menu >> 8)
        self.assertEqual(d.mpu.x, 0)
        self.assertEqual(d.mem[self.marker], 0, "a handler ran")
        self.assertEqual(d.get("hl_n"), 0)

    def test_highlight_is_drawn_while_held(self):
        """hl_toggle frames the item in the highlight colour and removes it."""
        d = self.d
        menu = self.build_menu()
        rect = d.w(menu)                       # the first item's record
        d.call("hl_toggle", a=rect & 255, x=rect >> 8)
        self.assertEqual(d.get("hl_n"), 1)
        self.assertEqual(self.pixel(200, 100), COL_HILITE)
        self.assertEqual(self.pixel(220, 109), COL_HILITE)
        d.call("hl_toggle", a=rect & 255, x=rect >> 8)
        self.assertEqual(d.get("hl_n"), 0)
        self.assertEqual(self.pixel(200, 100), COL_PANEL)


class TestText(RenderCase):
    """CHARTO/PRINT: glyphs of the 7-row font at column*7 + offset."""

    def font(self, code):
        return [self.d.mem[self.d.L["font7"] + code * 7 + r] for r in range(7)]

    def adv(self, code):
        return self.d.mem[self.d.L["font_adv"] + code]

    def print_at(self, column, offset, row, codes):
        d = self.d
        buf = d.L["P1STATE"] + 256
        data = bytes(codes[:-1]) + bytes([codes[-1] | 0x80])
        d.mem[buf:buf + len(data)] = data
        d.call("CHARTO", a=offset, x=column, y=row)
        self.assertEqual(list(d.mem[d.L["CHARBITS"] + 2:d.L["CHARBITS"] + 5]), [row, column, offset])
        d.call("PRINT", a=buf & 255, x=buf >> 8)

    def check_text(self, column, offset, row, codes):
        d = self.d
        colour = d.get("text_color")
        x = column * 7 + offset
        expected = {}
        for code in codes:
            if code < FONT_SPACE and x >= PANEL_X:
                for r, byte in enumerate(self.font(code)):
                    self.assertEqual(byte & 1, 0, "font bit 0 must be clear (7-pixel glyphs)")
                    for k in range(7):
                        expected[(x + k, row + r)] = COL_PANEL
                    for k in range(7):
                        if byte >> (7 - k) & 1:
                            expected[(x + k, row + r)] = colour
            x += self.adv(code)
        self.print_at(column, offset, row, codes)
        for (sx, sy), v in sorted(expected.items()):
            self.assertEqual(self.pixel(sx, sy), v, f"pixel ({sx},{sy})")
        self.assertTrue(any(v == colour for v in expected.values()), "no glyph pixel expected")
        # the text position advanced by the glyph widths
        cb = d.L["CHARBITS"]
        self.assertEqual(d.mem[cb + 3] * 7 + d.mem[cb + 4], x)
        self.assertLess(d.mem[cb + 4], 7)

    def test_glyph_at_even_x(self):
        self.check_text(26, 2, 178, [10])              # 'A' at x 184

    def test_glyph_at_odd_x(self):
        self.check_text(26, 3, 178, [10])              # 'A' at x 185

    def test_string_with_spaces_and_digits(self):
        # "QUIT", then a space, then "10" at the world screen's text position
        self.check_text(26, 3, 170, [26, 30, 18, 29, FONT_SPACE, 1, 0])

    def test_columns_beyond_255(self):
        self.check_text(40, 5, 150, [11, 12])          # x 285: 16-bit text x

    def test_score_digits_keep_their_first_columns(self):
        """Score digits are drawn right-to-left in seven-pixel cells."""
        d = self.d
        row = 120
        starts = (273, 266, 259, 252)
        cb = d.L["CHARBITS"]
        for y in range(row, row + 7):
            first = SHR_BASE + SHR_ROW * y + 252 // 2
            d.aux[first:first + 14] = bytes([COL_PANEL * 0x11]) * 14
        d.call("CHARTO", a=0, x=39, y=row)
        for _ in starts:
            d.call("PRCHAR", a=0)
            d.mem[cb + 3] -= 1          # RUN/RUN2 PRSCORE2 resets each digit's column
            d.mem[cb + 4] = 0
        glyph = self.font(0)
        for x in range(252, 280):
            for r, bits in enumerate(glyph):
                ink = any(x0 <= x < x0 + 7 and bits & (0x80 >> (x - x0))
                          for x0 in starts)
                expected = COL_TEXT if ink else COL_PANEL
                self.assertEqual(self.pixel(x, row + r), expected,
                                 f"score pixel ({x},{row + r})")

    def test_table_region_prints_nothing(self):
        d = self.d
        row = 100
        before = self.row_bytes(row, 0, 76)
        self.print_at(10, 0, row, [10, 11])            # x 70..: inside the table
        self.assertEqual(self.row_bytes(row, 0, 76), before)
        cb = d.L["CHARBITS"]
        self.assertEqual(d.mem[cb + 3] * 7 + d.mem[cb + 4], 70 + self.adv(10) + self.adv(11))

    def test_text_colour(self):
        d = self.d
        d.call("set_text_color", a=6)
        try:
            self.check_text(30, 0, 160, [10])
        finally:
            d.call("set_text_color", a=COL_TEXT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
