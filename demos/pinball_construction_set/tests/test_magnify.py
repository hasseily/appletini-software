#!/usr/bin/env python3
"""py65 tests of src/magnify.s (the magnifier: the pixel editor of the
overlay layer) in the whole port.

The port is booted in tools/a2sim.py's machine through tools/pcsdbg.py
(build/PCS.SYSTEM and build/PCS.SPR, built by `make`; the test runs
`make` when they are missing). Routines are called with their inputs set
and the editor is driven with the mouse and the keyboard.

Checks: the ov_tiles bit set by paint_pixel is the one render.s's
overlay_row reads (the pixel shows on the screen, and vanishes when that
bit is cleared); a painted pixel sets its own nibble of the bank-1 row
and nothing else, erasing (colour 0) clears it; recentre clamps the
window to the table with an even x and the window shows the table at 4x;
overlay_clear at start-up zeroes whatever RamWorks bank 1 held; entering
by the tool box sets MB_ST_MAG and the brush, leaving by Esc or QUIT
restores the editor (state, hand cursor, kit); painting with the mouse
reaches the table, survives a full re-render, the window box shows the
colour and, after an erase, what was beneath; the keys.

Run:  python3 tests/test_magnify.py
"""

import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pcsdbg  # noqa: E402

# pcs.inc
CURSORY, CURSORX, CURSORXH = 0x82, 0x83, 0x84
MB_STATE = 0x0304
MB_ST_EDIT, MB_ST_MAG = 1, 3
COL_PANEL, COL_GREY, COL_WHITE, COL_RED, COL_HILITE, COL_GREEN, COL_CYAN = 1, 2, 4, 6, 8, 10, 13
TABLE_W, TABLE_H, SHR_ROW = 154, 192, 160
# magnify.s
MAG_W, MAG_H, SCALE = 32, 24, 4
WIN_X, WIN_Y = 174, 66
PAL_X0, PAL_TY = 156, 167
TOOL_CLICK = (277, 60)          # inside MAGNB (x 264..291, y 51..68)
QUIT_CLICK = (185, 185)
GRID_CLICK = (289, 185)


def sprite_ids():
    ids = {}
    with open(os.path.join(ROOT, "build", "assets.inc")) as f:
        for line in f:
            m = re.match(r"(SPR_\w+)\s*=\s*(\d+)", line)
            if m:
                ids[m.group(1)] = int(m.group(2))
    return ids


def ensure_built():
    for name in ("PCS.SYSTEM", "PCS.SPR", "PCS.lbl", "assets.inc"):
        if not os.path.exists(os.path.join(ROOT, "build", name)):
            subprocess.check_call(["make"], cwd=ROOT)
            break


def tile_bit(tx, ty):
    """(byte, bit) of ov_tiles for table pixel (tx, ty), as overlay_row reads it."""
    tile = tx // 8
    return (ty // 8) * 3 + tile // 8, 1 << (tile & 7)


class MagnifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_built()
        cls.spr = sprite_ids()

    # -- helpers ------------------------------------------------------------
    def boot(self, frames=12, do=()):
        return pcsdbg.Dbg(frames=frames, do=list(do))

    def pixel(self, d, x, y):
        b = d.aux[0x2000 + SHR_ROW * y + x // 2]
        return b >> 4 if x % 2 == 0 else b & 15

    def bank1(self, d, tx, ty):
        return d.m.aux_banks[1][0x2000 + SHR_ROW * ty + tx // 2]

    def paint(self, d, tx, ty, colour):
        d.set("mag_tx", tx)
        d.set("mag_ty", ty)
        d.set("mag_color", colour)
        d.call("paint_pixel")

    def recentre(self, d, x, y):
        d.mem[CURSORX] = x & 255
        d.mem[CURSORXH] = x >> 8
        d.mem[CURSORY] = y
        d.call("recentre")

    def enter(self, frames_after=10):
        """The editor with the magnifier entered through its tool box."""
        d = self.boot(frames=10 + 4 + frames_after, do=["10:click %d %d" % TOOL_CLICK])
        self.assertEqual(d.mem[MB_STATE], MB_ST_MAG)
        return d

    def click(self, d, x, y, frames=6):
        d.m.mouse_move(x, y)
        d.m.mouse_buttons(True, False)
        d.run_frames(3)
        d.m.mouse_buttons(False, False)
        d.run_frames(frames)

    def key(self, d, code, frames=3):
        d.m.press(chr(code), at_cycle=d.mpu.processorCycles)
        d.run_frames(frames)

    # -- the layer ----------------------------------------------------------
    def test_tile_bits_match_overlay_row(self):
        d = self.boot()
        tiles = d.L["ov_tiles"]
        for tx, ty in ((0, 0), (7, 7), (8, 8), (63, 0), (64, 191), (153, 191), (101, 50)):
            d.mem[tiles:tiles + 72] = bytes(72)
            self.paint(d, tx, ty, COL_CYAN)
            byte, bit = tile_bit(tx, ty)
            expect = bytearray(72)
            expect[byte] = bit
            self.assertEqual(bytes(d.mem[tiles:tiles + 72]), bytes(expect), (tx, ty))
            self.assertEqual(d.get("ov_enabled"), 1)
            # the renderer shows it through that bit...
            d.run_frames(2)
            self.assertEqual(self.pixel(d, tx, ty), COL_CYAN, (tx, ty))
            # ...and not without it
            d.mem[tiles + byte] = 0
            d.call("rd_mark_all")
            d.run_frames(2)
            self.assertNotEqual(self.pixel(d, tx, ty), COL_CYAN, (tx, ty))
            self.paint(d, tx, ty, 0)

    def test_paint_sets_nibble_erase_clears_it(self):
        d = self.boot()
        row = 0x2000 + SHR_ROW * 20
        before = bytes(d.m.aux_banks[1][row:row + 77])
        self.assertEqual(before, bytes(77))
        self.paint(d, 10, 20, COL_CYAN)
        self.assertEqual(self.bank1(d, 10, 20), 0xD0)
        self.paint(d, 11, 20, 7)
        self.assertEqual(self.bank1(d, 11, 20), 0xD7)
        # nothing else in the row, nothing in the neighbours
        others = bytearray(d.m.aux_banks[1][row:row + 77])
        others[5] = 0
        self.assertEqual(bytes(others), bytes(77))
        for y in (19, 21):
            self.assertEqual(bytes(d.m.aux_banks[1][0x2000 + SHR_ROW * y:][:77]), bytes(77))
        # the dirty pixel and the pending box
        self.assertEqual((d.get("rd_ax0"), d.get("rd_ax1"), d.get("rd_ay0"), d.get("rd_ay1")),
                         (10, 11, 20, 20))
        self.assertEqual(d.get("mag_pend"), 0x80)
        # erase
        self.paint(d, 10, 20, 0)
        self.assertEqual(self.bank1(d, 10, 20), 0x07)
        self.paint(d, 11, 20, 0)
        self.assertEqual(self.bank1(d, 11, 20), 0x00)
        # the same colour again changes nothing and marks nothing
        d.set("mag_pend", 0)
        self.paint(d, 11, 20, 0)
        self.assertEqual(d.get("mag_pend"), 0)

    def test_overlay_clear_at_startup(self):
        d = pcsdbg.Dbg(frames=0)
        bank1 = d.m.aux_banks[1]
        for y in range(TABLE_H):
            bank1[0x2000 + SHR_ROW * y:0x2000 + SHR_ROW * y + 77] = bytes([0xAA]) * 77
        d.run_frames(6)
        for y in range(TABLE_H):
            self.assertEqual(bytes(bank1[0x2000 + SHR_ROW * y:][:77]), bytes(77), y)
        self.assertEqual(bytes(d.mem[d.L["ov_tiles"]:][:72]), bytes(72))
        self.assertEqual(d.get("ov_enabled"), 0)
        # and on demand, after an edit
        self.paint(d, 40, 40, COL_RED)
        d.run_frames(2)
        self.assertEqual(self.pixel(d, 40, 40), COL_RED)
        d.call("overlay_clear")
        self.assertEqual(self.bank1(d, 40, 40), 0)
        self.assertEqual(d.get("ov_enabled"), 0)
        d.run_frames(2)
        self.assertNotEqual(self.pixel(d, 40, 40), COL_RED)

    # -- the window ---------------------------------------------------------
    def test_recentre_clamps_to_the_table(self):
        d = self.enter()
        cases = [((0, 0), (0, 0)), ((153, 191), (122, 168)), ((80, 100), (64, 88)),
                 ((81, 101), (64, 89)), ((16, 12), (0, 0)), ((17, 13), (0, 1)),
                 ((300, 50), (122, 38)), ((138, 180), (122, 168)), ((137, 179), (120, 167))]
        for (x, y), (wx, wy) in cases:
            self.recentre(d, x, y)
            self.assertEqual((d.get("mag_wx"), d.get("mag_wy")), (wx, wy), (x, y))
            self.assertEqual(d.get("mag_wx") % 2, 0)

    def test_window_shows_the_table_magnified(self):
        d = self.enter()
        for (x, y) in ((75, 95), (0, 0), (153, 191)):
            self.recentre(d, x, y)
            wx, wy = d.get("mag_wx"), d.get("mag_wy")
            d.run_frames(2)
            d.call("cur_hide")
            for j in range(MAG_H):
                for i in range(MAG_W):
                    want = self.pixel(d, wx + i, wy + j)
                    for dy in range(SCALE):
                        for dx in range(SCALE):
                            self.assertEqual(self.pixel(d, WIN_X + SCALE * i + dx, WIN_Y + SCALE * j + dy),
                                             want, (x, y, i, j, dx, dy))

    def test_grid(self):
        d = self.enter()
        self.recentre(d, 75, 95)
        self.key(d, ord("G"))
        self.assertEqual(d.get("mag_grid"), 0x80)
        wx, wy = d.get("mag_wx"), d.get("mag_wy")
        d.call("cur_hide")
        for j in range(MAG_H):
            for i in range(MAG_W):
                want = self.pixel(d, wx + i, wy + j)
                for dy in range(SCALE):
                    for dx in range(SCALE):
                        grid = dx == SCALE - 1 or dy == SCALE - 1
                        self.assertEqual(self.pixel(d, WIN_X + SCALE * i + dx, WIN_Y + SCALE * j + dy),
                                         COL_PANEL if grid else want, (i, j, dx, dy))
        # the grid box is framed while the grid is on
        self.assertEqual(self.pixel(d, 290, 180), COL_HILITE)
        self.key(d, ord("g"))
        self.assertEqual(d.get("mag_grid"), 0)
        self.assertEqual(self.pixel(d, 290, 180), COL_PANEL)

    # -- the editor round trip ----------------------------------------------
    def test_enter_and_leave_by_esc(self):
        d = self.enter()
        self.assertEqual(d.get("cur_id"), self.spr["SPR_CUR_BRUSH"])
        # the panel: the frame, a white swatch, the QUIT text, the grid icon
        self.assertEqual(self.pixel(d, 172, 100), COL_GREY)
        self.assertEqual(self.pixel(d, PAL_X0 + 2 + 10 * COL_WHITE, PAL_TY + 1), COL_WHITE)
        self.assertEqual(self.pixel(d, PAL_X0 + 1, PAL_TY), COL_HILITE)     # colour 0 is current
        self.assertTrue(any(self.pixel(d, x, 185) != COL_PANEL for x in range(174, 198)))
        self.assertTrue(any(self.pixel(d, x, 185) != COL_PANEL for x in range(283, 297)))
        self.key(d, 27, frames=12)
        self.assertEqual(d.mem[MB_STATE], MB_ST_EDIT)
        self.assertEqual(d.get("cur_id"), self.spr["SPR_CUR_HAND"])
        self.assertEqual(d.get("mag_held"), 0)
        # the kit is back: the tool box holds an icon, the magnifier's panel is gone
        self.assertTrue(any(self.pixel(d, x, 60) != COL_PANEL for x in range(264, 292)))
        self.assertEqual(self.pixel(d, 172, 100), COL_PANEL)
        self.assertEqual(self.pixel(d, PAL_X0 + 2 + 10 * COL_WHITE, PAL_TY + 1), COL_PANEL)

    def test_leave_by_quit_box(self):
        d = self.enter()
        self.click(d, *QUIT_CLICK, frames=12)
        self.assertEqual(d.mem[MB_STATE], MB_ST_EDIT)
        self.assertEqual(d.get("cur_id"), self.spr["SPR_CUR_HAND"])
        self.assertTrue(any(self.pixel(d, x, 60) != COL_PANEL for x in range(264, 292)))

    def test_paint_with_the_mouse(self):
        d = self.enter()
        # recentre on the table's top-left corner (the border colour there,
        # no part: parts are drawn over the edits)
        self.click(d, 16, 12)
        wx, wy = d.get("mag_wx"), d.get("mag_wy")
        self.assertEqual((wx, wy), (0, 0))
        # pick red
        self.click(d, PAL_X0 + 6 + 10 * COL_RED, PAL_TY + 4)
        self.assertEqual(d.get("mag_color"), COL_RED)
        self.assertEqual(self.pixel(d, PAL_X0 + 1 + 10 * COL_RED, PAL_TY), COL_HILITE)
        self.assertEqual(self.pixel(d, PAL_X0 + 1, PAL_TY), 0)
        # a box on the border: cell (14, 8) = table (14, 8)
        tx, ty = wx + 14, wy + 8
        under = self.pixel(d, tx, ty)
        self.assertNotEqual(under, 0, "expected the border colour under the box")
        self.click(d, WIN_X + SCALE * 14 + 1, WIN_Y + SCALE * 8 + 1)
        self.assertEqual(self.bank1(d, tx, ty) >> 4, COL_RED)
        self.assertEqual(self.pixel(d, tx, ty), COL_RED)
        d.call("cur_hide")              # the brush sits on the box
        box = {self.pixel(d, WIN_X + SCALE * 14 + dx, WIN_Y + SCALE * 8 + dy)
               for dx in range(SCALE) for dy in range(SCALE)}
        self.assertEqual(box, {COL_RED})
        # a full re-render keeps it
        d.call("rd_mark_all")
        d.run_frames(3)
        self.assertEqual(self.pixel(d, tx, ty), COL_RED)
        # erase: the table and the box show what was beneath
        self.click(d, PAL_X0 + 6, PAL_TY + 4)
        self.assertEqual(d.get("mag_color"), 0)
        self.click(d, WIN_X + SCALE * 14 + 1, WIN_Y + SCALE * 8 + 1)
        self.assertEqual(self.bank1(d, tx, ty) >> 4, 0)
        self.assertEqual(self.pixel(d, tx, ty), under)
        d.call("cur_hide")              # the brush sits on the box
        box = {self.pixel(d, WIN_X + SCALE * 14 + dx, WIN_Y + SCALE * 8 + dy)
               for dx in range(SCALE) for dy in range(SCALE)}
        self.assertEqual(box, {under})

    def test_drag_paints_and_pans(self):
        d = self.enter()
        # a press on the table pans while held, even over the panel
        d.m.mouse_move(20, 30)
        d.m.mouse_buttons(True, False)
        d.run_frames(3)
        self.assertEqual((d.get("mag_wx"), d.get("mag_wy")), (4, 18))
        d.m.mouse_move(200, 100)
        d.run_frames(3)
        self.assertEqual((d.get("mag_wx"), d.get("mag_wy")), (122, 88))
        d.m.mouse_move(16, 12)
        d.run_frames(3)
        d.m.mouse_buttons(False, False)
        d.run_frames(2)
        self.assertEqual((d.get("mag_wx"), d.get("mag_wy")), (0, 0))
        # a drag inside the window paints a pixel per frame
        self.key(d, ord("A"))           # colour 10, green
        self.assertEqual(d.get("mag_color"), COL_GREEN)
        d.m.mouse_move(WIN_X + 2, WIN_Y + 2)
        d.m.mouse_buttons(True, False)
        for step in range(1, 6):
            d.run_frames(2)
            d.m.mouse_move(WIN_X + 2 + SCALE * step, WIN_Y + 2 + SCALE * step)
        d.run_frames(2)
        d.m.mouse_buttons(False, False)
        d.run_frames(3)
        for step in range(6):
            self.assertEqual(self.pixel(d, step, step), COL_GREEN, step)
            self.assertEqual(self.bank1(d, step, step) >> (4 if step % 2 == 0 else 0) & 15, COL_GREEN)
        # the keys: digits and letters pick colours, the rest is ignored
        for code, colour in ((ord("5"), 5), (ord("c"), 12), (ord("F"), 15), (ord("0"), 0), (ord("Z"), 0)):
            self.key(d, code)
            self.assertEqual(d.get("mag_color"), colour, chr(code))
        self.assertEqual(d.mem[MB_STATE], MB_ST_MAG)


if __name__ == "__main__":
    unittest.main()
