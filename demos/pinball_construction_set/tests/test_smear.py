#!/usr/bin/env python3
"""Incremental play rendering must match a complete redraw of the same table.

The original run loop moves a ball by issuing XOFFDRAW for the old and new
bitmap boxes. If either box is interpreted incorrectly, the ball's previous
pixels remain on screen until something else redraws that area.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))

import pcsdbg  # noqa: E402
from test_files import HAVE_BUILD, LOAD_ITEM, PLAY_ITEM, ST_PLAY, Sim  # noqa: E402

BUILD = ROOT / "build"
SHR_BASE, SHR_ROW, TABLE_BYTES, TABLE_H = 0x2000, 160, 77, 192


class _Subroutine:
    """Use pcsdbg's BRK-return driver with a disk-menu Sim."""

    call = pcsdbg.Dbg.call

    def __init__(self, sim):
        self.mem = sim.mem
        self.m = sim.m
        self.mpu = sim.mpu
        self.L = sim.L


def table_screen(sim):
    """The table's packed 154-pixel image, excluding the immediate-mode panel."""
    screen = sim.m.aux_banks[0]
    return b"".join(screen[SHR_BASE + y * SHR_ROW:
                           SHR_BASE + y * SHR_ROW + TABLE_BYTES]
                    for y in range(TABLE_H))


def finish_frame_render(sim):
    """Run from Runner's line-zero breakpoint through this frame's rd_frame.

    Sim.frames() stops when video_wait_vbl is entered, just before the
    renderer. Comparing there would mistake a legitimately queued dirty
    rectangle for a smear.
    """
    frame_step = sim.L["frame_step"]
    rd_frame = sim.L["rd_frame"]
    call = frame_step + 9             # fourth JSR: video, input, cursor, render
    assert bytes(sim.mem[call:call + 3]) == bytes((0x20, rd_frame & 255, rd_frame >> 8))
    end = call + 3
    for _ in range(2_000_000):
        if sim.mpu.pc == end:
            return
        sim.mpu.step()
    raise AssertionError("frame renderer did not return")


@unittest.skipUnless(HAVE_BUILD, "needs build/PCS.SYSTEM, tables and ROM")
class TestPlayRedraw(unittest.TestCase):
    def test_ball_and_animated_parts_leave_no_old_pixels(self):
        # DEMO5 has converted HGR artwork. THESAW adds a different crowded
        # object layout; TABLE1 covers a table without a converted overlay.
        for name in ("DEMO5.PCS", "THESAW.PCS", "TABLE1.PCS"):
            with self.subTest(table=name):
                data = (BUILD / "tables" / name).read_bytes()
                sim = Sim({name: data})
                sim.boot_to_editor()
                sim.open_menu()
                sim.click(*sim.entry_pos(0))
                sim.click(*LOAD_ITEM, settle=8)
                sim.open_menu()
                sim.click(*PLAY_ITEM, settle=2)
                sim.frames(66)
                sim.key(ord("1"), settle=6)
                self.assertEqual(sim.state(), ST_PLAY)

                driver = _Subroutine(sim)
                finish_frame_render(sim)
                # Establish the complete game image, then verify that each
                # following incremental update is equivalent to drawing its
                # current state from scratch.
                sim.mem[sim.L["dr_all"]] = 0x80
                driver.call("rd_frame", limit=10_000_000)
                ball_addr, ball = sim.l_record(4)
                old_pos = tuple(ball[17:19])
                moved = False
                for frame in range(24):
                    # Exercise a moving flipper as well as the ball.
                    if frame == 6:
                        sim.m.hold("Z")
                    if frame == 14:
                        sim.m.release()
                    if frame == 16:
                        sim.m.hold("X")
                    if frame == 22:
                        sim.m.release()
                    self.assertTrue(sim.frames(1), name)
                    finish_frame_render(sim)
                    actual = table_screen(sim)
                    sim.mem[sim.L["dr_all"]] = 0x80
                    driver.call("rd_frame", limit=10_000_000)
                    expected = table_screen(sim)
                    if actual != expected:
                        mismatch = next(i for i, pair in enumerate(zip(actual, expected))
                                        if pair[0] != pair[1])
                        x, y = (mismatch % TABLE_BYTES) * 2, mismatch // TABLE_BYTES
                        self.fail(f"{name} leaves old pixels at ({x},{y}) on frame {frame}")
                    ball = sim.mem[ball_addr + 17:ball_addr + 19]
                    # RUN's transient sweep records must use the port's
                    # pixel-x/zero-high convention. The DIV7/MOD7 tables
                    # in src/tables.s already provide this translation.
                    for symbol in ("HBALL", "VBALL"):
                        record = sim.L[symbol]
                        self.assertEqual(tuple(sim.mem[record + 3:record + 5]),
                                         (ball[0], 0), f"{name} {symbol} x header")
                    moved |= tuple(ball) != old_pos
                    old_pos = tuple(ball)
                self.assertTrue(moved, f"{name} did not move its ball during the test")


if __name__ == "__main__":
    unittest.main()
