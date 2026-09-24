#!/usr/bin/env python3
"""py65 unit tests for src/input.s (mouse, keyboard and paddles of the PCS
port).

The test assembles src/input.s and tests/input_test_driver.s with
ca65 --cpu 65c02, links them with tests/input_test.cfg, loads the image
into tools/a2sim.py's Apple //e (the vTW at 33x, a mouse card in slot 2
unless the test leaves it out, paddles at the 558 timer's centre unless
the test moves or unplugs them) and calls the driver entry points.

The machine's ROM is the enhanced //e ROM at $ROM or, by default,
appletini-one/docs/Apple2e_Enhanced.rom next to this tree; the internal
ROM matters only for the "no card" probe, so a blank ROM stands in when
it is missing. Every $C0xx access is counted (io_accesses) and every one
is logged with its address, so the per-frame bus budget and the register
sequences can be checked.

Checks: card detection with and without the card (and with INTCXROM on),
the set-up register sequence and that an empty slot is never written; the
card's clamps; the cursor following the mouse (absolute and delta
commits); the arrow keys with and without a mouse (tap, hold, the
4-pixel steps after 15 frames, the screen edges, the card following the
keys); the button and flipper sources; the plunger state machine's
timing; input_getkey's once-only report and register discipline;
input_set_cursor; the paddles as a rate controller, their calibration
and the switch-off of a dead axis; the $C0xx budget per frame.

Run:  python3 tests/test_input.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, os.path.join(ROOT, "tools"))

import a2sim  # noqa: E402

ROM_DEFAULT = os.path.join(ROOT, "..", "..", "..", "appletini-one", "docs",
                           "Apple2e_Enhanced.rom")

# mailbox (src/pcs.inc)
MB_MOUSEX, MB_MOUSEY, MB_INPUT, MB_HAVEMOUSE = 0x030C, 0x030E, 0x030F, 0x0311

# mouse card registers (index in $C0Ax)
R_STATUS, R_XLO, R_XHI, R_YLO, R_YHI, R_BTN = 0, 1, 2, 3, 4, 5
R_CLAMPSEL, R_MINLO, R_MINHI, R_MAXLO, R_MAXHI, R_CMD, R_MODE, R_ACK = 7, 8, 9, 10, 11, 12, 14, 15
MOUSE_IO = 0xC0A0

KEY_LEFT, KEY_RIGHT, KEY_UP, KEY_DOWN = 0x08, 0x15, 0x0B, 0x0A
ESC, CTRL_S = 0x1B, 0x13

SPEED = 33
STEP_LIMIT = 400_000
NO_PADDLE = 10 ** 9              # a 558 timer that never expires
JOY_CAP = 400


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def assemble(src, obj):
    subprocess.check_call(["ca65", "--cpu", "65c02", "-g", "-I", SRC, "-o", obj, src],
                          cwd=ROOT)


def build(tmpdir):
    objs = []
    for src in (os.path.join(SRC, "input.s"),
                os.path.join(HERE, "input_test_driver.s")):
        obj = os.path.join(tmpdir, os.path.basename(src) + ".o")
        assemble(src, obj)
        objs.append(obj)
    binary = os.path.join(tmpdir, "test_input.bin")
    labels = os.path.join(tmpdir, "test_input.lbl")
    subprocess.check_call(["ld65", "-C", os.path.join(HERE, "input_test.cfg"),
                           "-Ln", labels, "-o", binary] + objs, cwd=ROOT)
    with open(binary, "rb") as f:
        data = f.read()
    syms = {}
    with open(labels) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "al":
                syms[parts[2].lstrip(".")] = int(parts[1], 16)
    return data, 0x6000, syms


def rom_path(tmpdir):
    path = os.environ.get("ROM") or ROM_DEFAULT
    if os.path.exists(path):
        return path
    blank = os.path.join(tmpdir, "blank.rom")
    with open(blank, "wb") as f:
        f.write(bytes(0x4000))
    return blank


# ---------------------------------------------------------------------------
# the machine, with an I/O log
# ---------------------------------------------------------------------------
class LoggedMachine(a2sim.Machine):
    """a2sim.Machine plus a log of every $C0xx access: (kind, addr, value)."""

    def __init__(self, *args, **kwargs):
        self.io_log = []
        super().__init__(*args, **kwargs)

    def _io_read(self, address):
        value = super()._io_read(address)
        self.io_log.append(("r", address, value))
        return value

    def _io_write(self, address, value):
        super()._io_write(address, value)
        self.io_log.append(("w", address, value & 0xFF))


class Rig:
    def __init__(self, image, load, syms, rom, mouse=True, paddles=None):
        self.m = LoggedMachine(rom, speed=SPEED, mouse=mouse)
        if paddles is not None:
            self.m.paddles = list(paddles)
        self.m.load(load, image)
        self.syms = syms
        self.frames = 0
        self.last_accesses = 0
        self.last_log = []

    # --- running ---
    def call(self, entry, params=()):
        mpu = self.m.mpu
        for i, v in enumerate(params):
            self.m.main[self.syms["param"] + i] = v & 0xFF
        mpu.pc = self.syms[entry]
        mpu.sp = 0xFF
        halt = self.syms["halt"]
        before = self.m.io_accesses
        mark = len(self.m.io_log)
        n = 0
        while mpu.pc != halt:
            mpu.step()
            n += 1
            if n > STEP_LIMIT:
                raise AssertionError("%s did not finish (pc=%04X)" % (entry, mpu.pc))
        self.last_accesses = self.m.io_accesses - before
        self.last_log = self.m.io_log[mark:]
        return n

    def init(self):
        self.call("t_init")

    def frame(self, n=1):
        """Run n input_frames; return the $C0xx accesses of the last one."""
        for _ in range(n):
            self.call("t_frame")
            self.frames += 1
        return self.last_accesses

    def getkey(self):
        """(A, X, Y) after input_getkey."""
        self.call("t_getkey")
        r = self.syms["result"]
        return tuple(self.m.main[r:r + 3])

    def set_cursor(self, x, y):
        self.call("t_set_cursor", (x & 0xFF, x >> 8, y))

    # --- state ---
    def var(self, name):
        return self.m.main[self.syms[name]]

    def var16(self, name):
        a = self.syms[name]
        return self.m.main[a] | (self.m.main[a + 1] << 8)

    @property
    def cursor(self):
        return self.var16("in_mx"), self.var("in_my")

    @property
    def card(self):
        return self.m.mouse

    def mailbox(self, a):
        return self.m.main[a]

    # --- input ---
    def hold(self, key):
        self.m.hold(key)

    def release(self):
        self.m.release()

    def tap(self, key):
        self.m.press(chr(key) if isinstance(key, int) else key)

    def apple(self, open_=False, closed=False):
        self.m.buttons[0] = 0x80 if open_ else 0
        self.m.buttons[1] = 0x80 if closed else 0

    def mouse_accesses(self, log=None):
        return [x for x in (self.last_log if log is None else log)
                if MOUSE_IO <= x[1] < MOUSE_IO + 16]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
class InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pcs_input_")
        cls.image, cls.load, cls.syms = build(cls.tmp)
        cls.rom = rom_path(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def rig(self, mouse=True, paddles=None, init=True):
        r = Rig(self.image, self.load, self.syms, self.rom, mouse=mouse, paddles=paddles)
        if init:
            r.init()
        return r

    def no_mouse(self, paddles=(NO_PADDLE,) * 4):
        """A machine without a card and, by default, without paddles."""
        return self.rig(mouse=False, paddles=paddles)

    # ---- detection and set-up ----
    def test_detects_card_and_sets_it_up(self):
        r = self.rig()
        self.assertEqual(r.mailbox(MB_HAVEMOUSE), 1)
        self.assertEqual(r.var("have_mouse"), 1)
        card = r.card
        self.assertTrue(card.enabled)
        self.assertEqual(card.clamp, [[0, 319], [0, 199]])
        self.assertEqual((card.x, card.y), (160, 100))
        self.assertEqual(r.cursor, (160, 100))
        # the exact register sequence: mode, ACK (a mode write leaves a
        # stale IRQ latch alone), X window + commit, Y window + commit,
        # then the centre through the position registers
        self.assertEqual(card.writes(), [
            (R_MODE, 1), (R_ACK, 3),
            (R_CLAMPSEL, 0), (R_MINLO, 0), (R_MINHI, 0), (R_MAXLO, 319 & 0xFF),
            (R_MAXHI, 319 >> 8), (R_CMD, 2),
            (R_CLAMPSEL, 1), (R_MINLO, 0), (R_MINHI, 0), (R_MAXLO, 199),
            (R_MAXHI, 0), (R_CMD, 2),
            (R_XLO, 160), (R_XHI, 0), (R_YLO, 100), (R_YHI, 0)])
        self.assertFalse([x for x in card.log if x[0] == "r"], "init reads no register")
        self.assertFalse(r.m.sw["intcxrom"])
        self.assertFalse(card.irq or card.moved)

    def test_init_releases_a_stale_irq(self):
        # a previous program armed interrupts and quit without SERVEMOUSE
        r = self.rig(init=False)
        r.card.write(R_MODE, 0x0F)
        r.m.mouse_move(5, 5)
        r.m.mouse_buttons(True, False)
        r.card.vblank()
        self.assertTrue(r.card.irq)
        r.init()
        self.assertFalse(r.card.irq)
        self.assertEqual(r.card.status() & 0x2E, 0)      # no cause bit left
        self.assertEqual(r.card.mode, 1)

    def test_no_card(self):
        r = self.no_mouse()
        self.assertEqual(r.mailbox(MB_HAVEMOUSE), 0)
        self.assertEqual(r.var("have_mouse"), 0)
        self.assertEqual(r.cursor, (160, 100))
        # an empty slot is never written or read
        self.assertEqual(r.mouse_accesses(r.m.io_log), [])
        r.frame(3)
        self.assertEqual(r.mouse_accesses(r.m.io_log), [])

    def test_card_found_with_intcxrom_on(self):
        # the internal ROM hides the slot ROMs: the driver switches it off
        r = self.rig(init=False)
        r.m.sw["intcxrom"] = True
        r.init()
        self.assertEqual(r.mailbox(MB_HAVEMOUSE), 1)
        self.assertEqual([(k, a) for k, a, _ in r.last_log[:1]], [("w", 0xC006)])
        self.assertFalse(r.m.sw["intcxrom"])

    def test_internal_rom_never_passes_the_probe(self):
        # the //e's internal ROM has three of the four ID bytes on its slot 3
        # page (the 80-column firmware); the probe wants all four
        r = self.no_mouse()
        self.assertEqual(r.mailbox(MB_HAVEMOUSE), 0)
        r = self.rig(init=False)
        r.m.mouse.rom = bytes(r.m.rom[0x300:0x400])      # a card with slot 3's page
        r.init()
        self.assertEqual(r.mailbox(MB_HAVEMOUSE), 0)

    # ---- clamps ----
    def test_card_clamps_the_position(self):
        r = self.rig()
        r.m.mouse_move(1000, 500)
        self.assertEqual((r.card.x, r.card.y), (319, 199))
        r.frame()
        self.assertEqual(r.cursor, (319, 199))
        r.m.mouse_move(0, 0)
        r.m.mouse_delta(-10, -10)
        self.assertEqual((r.card.x, r.card.y), (0, 0))
        r.frame()
        self.assertEqual(r.cursor, (0, 0))
        r.m.mouse_delta(5, 7)
        r.frame()
        self.assertEqual(r.cursor, (5, 7))
        # the PS saturates what it publishes to 16 bits, it never wraps
        r.m.mouse_move(-1, -1)
        r.frame()
        self.assertEqual(r.cursor, (0, 0))
        r.m.mouse_move(70000, 70000)
        r.frame()
        self.assertEqual(r.cursor, (319, 199))

    def test_position_does_not_move_while_disabled(self):
        r = self.rig()
        r.card.write(R_MODE, 0)
        r.m.mouse_move(10, 10)
        self.assertEqual((r.card.x, r.card.y), (160, 100))
        r.card.write(R_MODE, 1)
        r.m.mouse_move(10, 10)
        self.assertEqual((r.card.x, r.card.y), (10, 10))

    def test_status_moved_and_ack(self):
        r = self.rig()
        self.assertFalse(r.card.status() & 0x20)
        r.m.mouse_move(10, 10)
        self.assertTrue(r.card.status() & 0x20)
        r.m.mouse_buttons(True, False)
        self.assertEqual(r.card.status() & 0x90, 0x80)
        r.card.write(R_ACK, 1)
        self.assertEqual(r.card.status() & 0x20, 0)
        self.assertEqual(r.card.status() & 0x40, 0x40)     # previous button 0

    # ---- the cursor follows the mouse ----
    def test_cursor_follows_mouse(self):
        r = self.rig()
        r.frame()
        self.assertEqual(r.cursor, (160, 100))
        self.assertEqual(r.mailbox(MB_MOUSEX) | (r.mailbox(MB_MOUSEX + 1) << 8), 160)
        self.assertEqual(r.mailbox(MB_MOUSEY), 100)
        r.m.mouse_move(50, 60)
        r.frame()
        self.assertEqual(r.cursor, (50, 60))
        self.assertEqual(r.mailbox(MB_MOUSEX), 50)
        self.assertEqual(r.mailbox(MB_MOUSEY), 60)
        r.m.mouse_delta(3, -4)
        r.frame()
        self.assertEqual(r.cursor, (53, 56))
        r.m.mouse_move(300, 5)
        r.frame()
        self.assertEqual(r.cursor, (300, 5))
        self.assertEqual(r.mailbox(MB_MOUSEX) | (r.mailbox(MB_MOUSEX + 1) << 8), 300)

    def test_frame_reads_x_y_and_buttons_only(self):
        r = self.rig()
        r.m.mouse_move(20, 30)
        r.frame()
        self.assertEqual([(k, a - MOUSE_IO) for k, a, _ in r.mouse_accesses()],
                         [("r", R_XLO), ("r", R_XHI), ("r", R_YLO), ("r", R_BTN)])

    # ---- arrows ----
    def test_arrow_tap_moves_one_pixel(self):
        r = self.no_mouse()
        r.tap(KEY_RIGHT)
        r.frame()
        self.assertEqual(r.cursor, (161, 100))
        r.frame()
        self.assertEqual(r.cursor, (161, 100))
        r.tap(KEY_UP)
        r.frame()
        self.assertEqual(r.cursor, (161, 99))
        r.tap(KEY_LEFT)
        r.frame()
        r.tap(KEY_DOWN)
        r.frame()
        self.assertEqual(r.cursor, (160, 100))
        self.assertEqual(r.mailbox(MB_INPUT) & 0x0F, 0x02)   # down was applied

    def test_arrow_hold_accelerates_after_15_frames(self):
        r = self.no_mouse()
        r.hold(KEY_RIGHT)
        xs = []
        for _ in range(17):
            r.frame()
            xs.append(r.cursor[0])
        self.assertEqual(xs, [160 + i for i in range(1, 16)] + [179, 183])
        r.release()
        r.frame()
        self.assertEqual(r.cursor, (183, 100))
        # a new hold starts slowly again
        r.hold(KEY_LEFT)
        r.frame(3)
        self.assertEqual(r.cursor, (180, 100))

    def test_arrows_stop_at_the_screen_edges(self):
        r = self.no_mouse()
        r.hold(KEY_LEFT)
        r.frame(80)
        self.assertEqual(r.cursor, (0, 100))
        r.hold(KEY_UP)
        r.frame(60)
        self.assertEqual(r.cursor, (0, 0))
        r.hold(KEY_RIGHT)
        r.frame(120)
        self.assertEqual(r.cursor, (319, 0))
        r.hold(KEY_DOWN)
        r.frame(80)
        self.assertEqual(r.cursor, (319, 199))

    def test_arrows_move_the_card_when_a_mouse_is_present(self):
        r = self.rig()
        r.hold(KEY_RIGHT)
        r.frame()
        self.assertEqual(r.cursor, (161, 100))
        self.assertEqual((r.card.x, r.card.y), (161, 100))
        # the keys own the cursor: the buttons are read, the position is
        # written, and the frame stays at 8 accesses
        self.assertEqual([(k, a - MOUSE_IO, v) for k, a, v in r.mouse_accesses()],
                         [("r", R_BTN, 0), ("w", R_XLO, 161), ("w", R_XHI, 0),
                          ("w", R_YLO, 100)])
        self.assertEqual(r.last_accesses, 8)
        r.frame()
        self.assertEqual(r.cursor, (162, 100))
        # a mouse motion while the key is held is overridden by the keys
        r.m.mouse_delta(10, 0)
        self.assertEqual(r.card.x, 172)
        r.frame()
        self.assertEqual(r.cursor, (163, 100))
        self.assertEqual(r.card.x, 163)
        r.release()
        r.frame()
        self.assertEqual(r.cursor, (163, 100))
        self.assertEqual(len([x for x in r.mouse_accesses() if x[0] == "w"]), 0)
        # afterwards the PS's delta builds on what the keys wrote
        r.m.mouse_delta(10, 0)
        r.frame()
        self.assertEqual(r.cursor, (173, 100))
        # the mouse button is still seen while an arrow key is held
        r.hold(KEY_LEFT)
        r.m.mouse_buttons(True, False)
        r.frame()
        self.assertEqual(r.cursor, (172, 100))
        self.assertEqual(r.var("in_btn"), 0x80)

    # ---- the button ----
    def test_button_sources(self):
        r = self.rig()
        r.frame()
        self.assertEqual(r.var("in_btn"), 0)
        r.m.mouse_buttons(True, False)
        r.frame(2)
        self.assertEqual(r.var("in_btn"), 0x80)      # held, not an edge
        self.assertEqual(r.mailbox(MB_INPUT) & 0x80, 0x80)
        r.m.mouse_buttons(False, True)
        r.frame()
        self.assertEqual(r.var("in_btn"), 0)         # the right button is not the button
        r.m.mouse_buttons(False, False)
        r.apple(open_=True)
        r.frame()
        self.assertEqual(r.var("in_btn"), 0x80)
        r.apple(closed=True)
        r.frame()
        self.assertEqual(r.var("in_btn"), 0x80)
        r.apple()
        r.frame()
        self.assertEqual(r.var("in_btn"), 0)
        r.hold(" ")
        r.frame(3)
        self.assertEqual(r.var("in_btn"), 0x80)
        r.release()
        r.frame()
        self.assertEqual(r.var("in_btn"), 0)
        r.hold("z")
        r.frame()
        self.assertEqual(r.var("in_btn"), 0)         # a flipper key is not the button

    def test_space_is_the_button_without_a_mouse(self):
        r = self.no_mouse()
        r.hold(" ")
        r.frame()
        self.assertEqual(r.var("in_btn"), 0x80)
        r.release()
        r.frame()
        self.assertEqual(r.var("in_btn"), 0)

    # ---- flippers ----
    def test_flipper_bits(self):
        r = self.rig()
        cases = [
            (lambda: r.m.mouse_buttons(True, False), 0x80),
            (lambda: r.m.mouse_buttons(False, True), 0x40),
            (lambda: r.m.mouse_buttons(True, True), 0xC0),
            (lambda: r.m.mouse_buttons(False, False), 0x00),
            (lambda: r.apple(open_=True), 0x80),
            (lambda: r.apple(closed=True), 0x40),
            (lambda: r.apple(open_=True, closed=True), 0xC0),
            (lambda: r.apple(), 0x00),
            (lambda: r.hold("z"), 0x80),
            (lambda: r.hold("Z"), 0x80),
            (lambda: r.hold("/"), 0x40),
            (lambda: r.release(), 0x00),
        ]
        for action, expected in cases:
            action()
            r.frame()
            self.assertEqual(r.var("in_flip"), expected)
            self.assertEqual(r.mailbox(MB_INPUT) & 0x60, expected >> 1)
        # sources combine, and the held state lasts
        r.apple(open_=True)
        r.hold("/")
        r.frame(4)
        self.assertEqual(r.var("in_flip"), 0xC0)

    # ---- the plunger ----
    def test_plunger_state_machine(self):
        r = self.no_mouse()
        r.hold(" ")
        for i in range(1, 11):
            r.frame()
            self.assertEqual((r.var("in_plunger"), r.var("in_launch")), (4 * i, 0), i)
        r.release()
        # 12 frames of launch with the charge held
        for i in range(12):
            r.frame()
            self.assertEqual((r.var("in_plunger"), r.var("in_launch")), (40, 0x80), i)
            self.assertEqual(r.mailbox(MB_INPUT) & 0x10, 0x10)
        # then the charge falls by 32 per frame
        r.frame()
        self.assertEqual((r.var("in_plunger"), r.var("in_launch")), (8, 0))
        r.frame()
        self.assertEqual((r.var("in_plunger"), r.var("in_launch")), (0, 0))
        r.frame(3)
        self.assertEqual((r.var("in_plunger"), r.var("in_launch")), (0, 0))
        self.assertEqual(r.mailbox(MB_INPUT) & 0x10, 0)

    def test_plunger_saturates(self):
        r = self.no_mouse()
        r.hold(" ")
        r.frame(63)
        self.assertEqual(r.var("in_plunger"), 252)
        r.frame()
        self.assertEqual(r.var("in_plunger"), 255)
        r.frame(10)
        self.assertEqual(r.var("in_plunger"), 255)
        r.release()
        r.frame(12)
        self.assertEqual((r.var("in_plunger"), r.var("in_launch")), (255, 0x80))
        r.frame(8)
        self.assertEqual((r.var("in_plunger"), r.var("in_launch")), (0, 0))

    def test_down_arrow_pulls_the_plunger(self):
        r = self.no_mouse()
        r.hold(KEY_DOWN)
        r.frame(5)
        self.assertEqual(r.var("in_plunger"), 20)
        self.assertEqual(r.cursor, (160, 105))
        r.release()
        r.frame()
        self.assertEqual(r.var("in_launch"), 0x80)

    def test_pull_during_launch_restarts(self):
        r = self.no_mouse()
        r.hold(" ")
        r.frame(5)
        r.release()
        r.frame(3)
        self.assertEqual((r.var("in_plunger"), r.var("in_launch")), (20, 0x80))
        r.hold(" ")
        r.frame()
        self.assertEqual((r.var("in_plunger"), r.var("in_launch")), (24, 0))
        r.release()
        r.frame()
        self.assertEqual((r.var("in_plunger"), r.var("in_launch")), (24, 0x80))

    def test_plunger_with_a_mouse(self):
        r = self.rig()
        r.hold(" ")
        r.frame(2)
        self.assertEqual((r.var("in_plunger"), r.var("in_btn")), (8, 0x80))

    # ---- keys ----
    def test_getkey_reports_once_and_keeps_x_y(self):
        r = self.no_mouse()
        self.assertEqual(r.getkey(), (0, 0x5A, 0xA5))
        r.tap(ESC)
        r.frame()
        self.assertEqual(r.var("in_key"), 0x9B)
        self.assertEqual(r.getkey(), (0x9B, 0x5A, 0xA5))
        self.assertEqual(r.getkey(), (0, 0x5A, 0xA5))
        r.tap(CTRL_S)
        r.frame()
        self.assertEqual(r.getkey()[0], 0x93)
        # a key nobody takes is gone with the next frame: the editor never
        # polls keys, and the play loop must not start on a stale Esc
        r.tap("q")
        r.frame()
        self.assertEqual(r.var("in_key"), 0xF1)
        r.frame()
        self.assertEqual(r.var("in_key"), 0)
        self.assertEqual(r.getkey()[0], 0)
        r.tap("2")
        r.frame()
        self.assertEqual(r.getkey()[0], 0xB2)
        self.assertEqual(r.getkey()[0], 0)

    def test_a_key_is_reported_once_per_press(self):
        r = self.no_mouse()
        r.hold("z")
        r.frame()
        self.assertEqual(r.getkey()[0], 0xFA)
        self.assertEqual(r.getkey()[0], 0)
        r.frame(5)                                  # still held: no new report
        self.assertEqual(r.getkey()[0], 0)
        self.assertEqual(r.var("in_flip"), 0x80)    # but still held
        r.release()
        r.hold("z")
        r.frame()
        self.assertEqual(r.getkey()[0], 0xFA)

    def test_held_key_stops_when_released(self):
        r = self.no_mouse()
        r.hold("z")
        r.frame(3)
        self.assertEqual(r.var("in_flip"), 0x80)
        r.release()
        r.frame()
        self.assertEqual(r.var("in_flip"), 0)
        # a tap of another key while holding replaces the held key (the
        # //e cannot tell which keys are down)
        r.hold(KEY_RIGHT)
        r.frame()
        r.hold("/")
        r.frame()
        self.assertEqual(r.var("in_flip"), 0x40)
        self.assertEqual(r.cursor, (161, 100))

    # ---- input_set_cursor ----
    def test_set_cursor_moves_cursor_and_card(self):
        r = self.rig()
        r.set_cursor(300, 150)
        self.assertEqual(r.cursor, (300, 150))
        self.assertEqual((r.card.x, r.card.y), (300, 150))
        self.assertEqual([(k, a - MOUSE_IO, v) for k, a, v in r.mouse_accesses()],
                         [("w", R_XLO, 300 & 0xFF), ("w", R_XHI, 1), ("w", R_YLO, 150)])
        r.m.mouse_delta(5, 5)
        r.frame()
        self.assertEqual(r.cursor, (305, 155))
        r.set_cursor(7, 9)
        r.frame()
        self.assertEqual(r.cursor, (7, 9))

    def test_set_cursor_without_a_mouse(self):
        r = self.no_mouse()
        r.set_cursor(10, 20)
        self.assertEqual(r.cursor, (10, 20))
        self.assertEqual(r.last_accesses, 0)
        r.frame()
        self.assertEqual(r.cursor, (10, 20))

    # ---- paddles ----
    def test_paddles_steer_the_cursor(self):
        r = self.no_mouse(paddles=[1400, 1400, 1400, 1400])
        self.assertEqual((r.var("joy_ok"), r.m.main[self.syms["joy_ok"] + 1]), (1, 1))
        centre = r.var16("joy_center")
        self.assertTrue(100 <= centre <= 150, centre)     # about 1400 us / 11 us
        self.assertLess(r.var16("joy_lo"), centre)
        self.assertGreater(r.var16("joy_hi"), centre)
        r.frame(6)
        self.assertEqual(r.cursor, (160, 100))            # centred: no drift
        # One axis is read per frame (X on odd frames here, Y on even ones)
        # and the other axis's direction is remembered, so a deflection
        # moves the cursor every frame and a change shows one frame late.
        r.m.paddles[0] = 2400                             # stick right
        r.frame(2)
        self.assertEqual(r.cursor, (162, 100))
        r.m.paddles[0] = 400                              # stick left
        r.frame(2)
        self.assertEqual(r.cursor, (160, 100))
        r.m.paddles[0] = 1400
        r.m.paddles[1] = 2400                             # stick down
        r.frame(2)                                        # X centred, then Y: down
        self.assertEqual(r.cursor, (160, 101))
        r.m.paddles[1] = 400                              # stick up
        r.frame(4)                                        # 102 (stale), 101, 100, 99
        self.assertEqual(r.cursor, (160, 99))
        # diagonal: both axes' bits are kept between reads
        r.m.paddles[0] = 2400
        r.frame(4)
        self.assertEqual(r.cursor, (164, 95))
        # a held deflection accelerates like a held key: the direction has
        # been on for 9 frames; 6 more at 1 pixel, then 14 at 4 pixels
        r.m.paddles[1] = 1400
        r.frame(20)
        self.assertEqual(r.cursor, (226, 94))

    def test_paddle_polls_are_capped(self):
        r = self.no_mouse(paddles=[1400, 1400, 1400, 1400])
        r.frame()
        polls = [x for x in r.last_log if 0xC064 <= x[1] <= 0xC067]
        self.assertTrue(100 <= len(polls) <= 150, len(polls))
        self.assertEqual(len([x for x in r.last_log if x[1] == 0xC070]), 1)
        r.m.paddles = [NO_PADDLE] * 4                     # unplugged after calibration
        r.frame()
        self.assertEqual(len([x for x in r.last_log if 0xC064 <= x[1] <= 0xC067]), JOY_CAP)

    def test_missing_paddles_are_switched_off(self):
        r = self.no_mouse()
        self.assertEqual((r.var("joy_ok"), r.m.main[self.syms["joy_ok"] + 1]), (0, 0))
        init_polls = [x for x in r.m.io_log if 0xC064 <= x[1] <= 0xC067]
        self.assertEqual(len(init_polls), 2 * JOY_CAP)
        r.frame(4)
        self.assertEqual(r.cursor, (160, 100))
        self.assertEqual([x for x in r.last_log if 0xC064 <= x[1] <= 0xC070], [])

    def test_one_dead_axis(self):
        r = self.no_mouse(paddles=[1400, NO_PADDLE, 1400, 1400])
        self.assertEqual((r.var("joy_ok"), r.m.main[self.syms["joy_ok"] + 1]), (1, 0))
        r.m.paddles[0] = 2400
        r.frame(4)                                        # X read on 2 of 4, remembered on the others
        self.assertEqual(r.cursor, (164, 100))
        # the dead axis costs nothing
        r.frame()
        odd = [x for x in r.last_log if 0xC064 <= x[1] <= 0xC070]
        r.frame()
        even = [x for x in r.last_log if 0xC064 <= x[1] <= 0xC070]
        self.assertEqual(sorted((len(odd) == 0, len(even) == 0)), [False, True])

    def test_paddles_are_ignored_with_a_mouse(self):
        r = self.rig(paddles=[2400, 2400, 2400, 2400])
        r.frame(4)
        self.assertEqual(r.cursor, (160, 100))
        self.assertEqual([x for x in r.m.io_log if 0xC064 <= x[1] <= 0xC070], [])

    # ---- the bus budget ----
    def test_frame_budget_with_a_mouse(self):
        r = self.rig()
        counts = set()
        for i in range(60):
            r.m.mouse_delta(3 - (i % 7), (i % 5) - 2)
            r.m.mouse_buttons(i % 3 == 0, i % 4 == 0)
            if i % 6 == 0:
                r.tap("z")
            if i % 11 == 0:
                r.hold(KEY_RIGHT)                       # held arrows: card written
            if i % 11 == 5:
                r.tap(KEY_UP)
            if i % 11 == 7:
                r.release()
            if i % 5 == 0:
                r.apple(open_=True)
            else:
                r.apple()
            counts.add(r.frame())
        self.assertEqual(counts, {8})                   # 2 keyboard + 2 buttons + 4 card

    def test_frame_budget_without_mouse_or_paddles(self):
        r = self.no_mouse()
        worst = 0
        for i in range(30):
            if i % 4 == 0:
                r.tap(KEY_RIGHT)
            if i % 7 == 0:
                r.hold(" ")
            if i % 7 == 3:
                r.release()
            worst = max(worst, r.frame())
        self.assertLessEqual(worst, 5)
        self.assertEqual(worst, 4)

    def test_frame_accesses_are_the_documented_set(self):
        r = self.no_mouse()
        r.tap("z")
        r.frame()
        self.assertEqual([(k, a) for k, a, _ in r.last_log],
                         [("r", 0xC000), ("w", 0xC010), ("r", 0xC061), ("r", 0xC062)])
        r.frame()
        self.assertEqual([(k, a) for k, a, _ in r.last_log],
                         [("r", 0xC000), ("r", 0xC010), ("r", 0xC061), ("r", 0xC062)])
        r = self.rig()
        r.frame()
        self.assertEqual([(k, a) for k, a, _ in r.last_log],
                         [("r", 0xC000), ("r", 0xC010), ("r", 0xC061), ("r", 0xC062),
                          ("r", 0xC0A1), ("r", 0xC0A2), ("r", 0xC0A3), ("r", 0xC0A5)])

    def test_slot_4_is_never_touched(self):
        for r in (self.rig(), self.no_mouse(paddles=[1400] * 4)):
            r.hold(KEY_DOWN)
            r.frame(3)
            r.set_cursor(1, 2)
            self.assertEqual([x for x in r.m.io_log if 0xC0C0 <= x[1] <= 0xC0CF], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
