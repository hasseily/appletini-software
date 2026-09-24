#!/usr/bin/env python3
"""Tests of the platform: model, loader, kernel, GAME skeleton
(docs/DESIGN.md sections 2, 4 and 8).

Builds the stand-in configuration (make STANDIN=1: build/standin, the data
of tools/make_standin.py), then in the py65 machine of tools/a2sim.py:

  - boots DOOM.SYSTEM through the fake ProDOS to the frame loop: the
    loader's bank count, the data in its banks, the images installed;
  - SHR4 PAL256 is on (magic, paging byte, selector nibbles, $C029) and
    a screenshot shows the test pattern through PLAYPAL 0;
  - far_read / far_write / far_copy / far_elem across banks and chunk
    boundaries, from both spaces, into main memory, bank 1 and the zero
    page;
  - the space switch keeps A, X, Y, P and the stack; call_game passes
    the registers both ways and comes back in RENDER space;
  - blit_view writes exactly the doubled view into SHR rows 0-83;
  - the tic clock gives 35 tics per 60 frames (+-1), MAX_TICS caps;
  - the input mapping of DESIGN.md section 10;
  - the GAME skeleton counts the tics and reads the probe array;
  - the loader's errors (too little memory, a bad data file);
  - the model itself: TURBO frame length, bank aliasing, PAL256 image.

Run:  python3 tests/test_platform.py      (the measurements: -v)
"""

import os
import random
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))

import a2sim  # noqa: E402
import doomdbg  # noqa: E402
import make_standin  # noqa: E402
import run_doom  # noqa: E402

BUILD = ROOT / "build/standin"
ROM = run_doom.DEFAULT_ROM
VIEW_W, VIEW_H = 160, 84
MEASURE = {}


def setUpModule():
    subprocess.run(["make", "-s", "STANDIN=1"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)


def tearDownModule():
    if MEASURE and ("-v" in sys.argv or os.environ.get("DOOM_MEASURE")):
        print("\nmeasurements (cycles, TURBO model, $Cxxx = 73 cycles):")
        for key, value in MEASURE.items():
            print(f"  {key:40s} {value}")


def expected_pattern(tics: int, col: int) -> bytes:
    """src/render/stub.s: x + y + 2*tics, column `col` in colour 4."""
    out = bytearray()
    for x in range(VIEW_W):
        if x == col:
            out += bytes([4]) * VIEW_H
        else:
            out += bytes((x + y + 2 * tics) & 0xFF for y in range(VIEW_H))
    return bytes(out)


# ---------------------------------------------------------------------------
class BootTest(unittest.TestCase):
    """The real path: DOOM.SYSTEM under the fake ProDOS."""

    @classmethod
    def setUpClass(cls):
        cls.doom = run_doom.Doom(BUILD, fast=False)
        cls.boot = cls.doom.boot()
        cls.doom.start_cycle = cls.doom.mpu.processorCycles
        MEASURE["loader: boot cycles (stand-in data)"] = cls.boot
        cls.machine = cls.doom.machine
        cls.machine.run(12 * cls.machine.frame_cycles, stop_pc=cls.doom.label("kernel_crash_stop"))

    def test_bank_count(self):
        self.assertEqual(self.doom.byte("kbanks"), 128)

    def test_data_in_banks(self):
        m = self.machine
        for name, contents in self.doom.data_files.items():
            for bank, address, blob in make_standin.parse_data_file(contents):
                self.assertEqual(bytes(m.bank_memory(bank)[address:address + len(blob)]), blob,
                                 f"{name} segment {bank}:{address:04X}")

    def test_images_installed(self):
        m, files = self.machine, self.doom.files
        game = files["GAME.BIN"]
        self.assertEqual(bytes(m.bank_memory(1)[0x0200:0x0200 + len(game)]), game)
        lc = files["LC.BIN"]
        # bank 2 $D000 (the blit), $E000 up to the kernel's BSS, bank 1
        bss = self.doom.label("__KBSS_RUN__")
        self.assertEqual(bytes(m.lc[False][0x1000:0x2000]), lc[:0x1000])
        self.assertEqual(bytes(m.lc[False][0x2000:bss - 0xC000]), lc[0x1000:bss - 0xD000])
        self.assertEqual(bytes(m.lc[False][0x3FFA:0x4000]), lc[0x2FFA:0x3000])
        self.assertEqual(bytes(m.lc_bank1[False]), lc[0x3000:])
        render = files["RENDER.BIN"]
        code = self.doom.label("render_frame")        # code, not overwritten by BSS
        self.assertEqual(m.main[code:code + 32], render[code - 0x0200:code - 0x0200 + 32])

    def test_pal256_on(self):
        m = self.machine
        aux = m.aux_banks[0]
        self.assertEqual(bytes(aux[0x9DFC:0x9E00]), b"\xD3\xC8\xD2\xB4")
        self.assertEqual(aux[0x9DF8], 0)
        self.assertEqual(m.newvideo, 0xC1)
        self.assertTrue(all(aux[a] >> 4 == 2 for a in range(0x9E01, 0xA000, 2)))
        self.assertTrue(m.pal256_active())
        dir1 = make_standin.parse_data_file(self.doom.data_files["DIR.1"])[0][2]
        self.assertEqual(bytes(aux[0x9E00:0xA000]), dir1[:512])

    def test_frame_loop_running(self):
        d = self.doom
        self.assertGreater(d.word("kframes"), 3)
        self.assertEqual(d.byte("kcrash"), 0)
        self.assertGreater(self.machine.irqs, 10)

    def test_screenshot_shows_pattern(self):
        d, m = self.doom, self.machine
        # stop right after a blit, then the screen is the view buffer, doubled
        self.assertTrue(d.run_to("present_done"))
        view = d.view_buffer()
        tics = d.word("ktics")
        self.assertEqual(view, expected_pattern(tics, d.byte("stub_col")))
        image = m.shr_image()
        self.assertEqual(image.size, (640, 400))
        palette = m.pal256_palette()
        for x, y in ((0, 0), (37, 11), (159, 83), (80, 40)):
            index = view[84 * x + y]
            # game pixel (x, y) is 4x4 output pixels at (4x, 4y)
            self.assertEqual(image.getpixel((4 * x + 3, 4 * y + 2)), palette[index])
        image.save(ROOT / "build/standin/test_pattern.png")


# ---------------------------------------------------------------------------
class KernelTest(unittest.TestCase):
    """Routines called one by one in a booted (fast) machine."""

    @classmethod
    def setUpClass(cls):
        cls.d = doomdbg.Dbg(frames=3, build=BUILD)
        cls.m = cls.d.m

    def far_args(self, src=None, dst=None, ptr=None, length=0):
        d = self.d
        if src is not None:
            d.zp("far_src", [src[1] & 255, src[1] >> 8, src[0]])
        if dst is not None:
            d.zp("far_dst", [dst[1] & 255, dst[1] >> 8, dst[0]])
        if ptr is not None:
            d.zp("far_ptr", [ptr & 255, ptr >> 8])
        d.zp("far_len", [length & 255, length >> 8])

    def test_far_elem_chunks(self):
        d = self.d
        desc = 0x4F00                     # a descriptor in main memory
        d.m.main[desc:desc + 6] = bytes((make_standin.PROBE_BANK, 0x00, 0x02,
                                         make_standin.PROBE_SIZE, 0, make_standin.PROBE_LOG2))
        count = make_standin.PROBE_COUNT
        for index in (0, 1, 4095, 4096, 4097, 8191, 8192, 12287, 12288, count - 1):
            d.zp("far_idx", [index & 255, index >> 8])
            cycles = d.call("far_elem", a=desc & 255, x=desc >> 8)
            got = d.m.main[d.L["far_src"]:d.L["far_src"] + 3]
            bank, address = make_standin.probe_location(index)
            self.assertEqual((got[2], got[0] | (got[1] << 8)), (bank, address), index)
            MEASURE.setdefault("far_elem (size 4, log2 12), worst", 0)
            MEASURE["far_elem (size 4, log2 12), worst"] = max(
                MEASURE["far_elem (size 4, log2 12), worst"], cycles)

    def test_far_elem_general(self):
        d = self.d
        desc = 0x4F10
        for bank, base, size, log2, index in ((5, 0x0300, 12, 10, 3000), (9, 0x1234, 1, 0, 7),
                                              (2, 0x0200, 300, 7, 129), (7, 0x0200, 2, 15, 40000)):
            d.m.main[desc:desc + 6] = bytes((bank, base & 255, base >> 8, size & 255, size >> 8, log2))
            d.zp("far_idx", [index & 255, index >> 8])
            d.call("far_elem", a=desc & 255, x=desc >> 8)
            got = d.m.main[d.L["far_src"]:d.L["far_src"] + 3]
            mask = (1 << log2) - 1
            want = (bank + (index >> log2), (base + (index & mask) * size) & 0xFFFF)
            self.assertEqual((got[2], got[0] | (got[1] << 8)), want)

    def test_far_read_both_spaces(self):
        d, m = self.d, self.m
        rng = random.Random(1)
        for bank, address, length in ((8, 0x0200 + 4095 * 4, 4), (9, 0x0200, 4), (10, 0x1000, 300),
                                      (40, 0xBF00, 256), (127, 0x2345, 1), (64, 0x0200, 0x1000)):
            data = bytes(rng.randrange(256) for _ in range(length))
            d.put_far(bank, address, data)
            # RENDER space into main memory
            self.far_args(src=(bank, address), ptr=0x5000, length=length)
            c1 = d.call("far_read")
            self.assertEqual(bytes(m.main[0x5000:0x5000 + length]), data)
            # GAME space into bank 1
            self.far_args(src=(bank, address), ptr=0x7000, length=length)
            c2 = d.call("far_read", space="game")
            self.assertEqual(d.far(1, 0x7000, length), data)
            self.assertEqual(m.bank, 1)                       # back in bank 1
            if length == 4:
                MEASURE["far_read 4 bytes RENDER / GAME"] = f"{c1} / {c2}"
            if length == 256:
                MEASURE["far_read 256 bytes RENDER / GAME"] = f"{c1} / {c2}"
            if length == 0x1000:
                MEASURE["far_read 4 KB RENDER / GAME"] = f"{c1} / {c2}"
        # into the zero page, from GAME space
        d.put_far(5, 0x0400, b"\x11\x22\x33\x44")
        self.far_args(src=(5, 0x0400), ptr=0x00C0, length=4)
        d.call("far_read", space="game")
        self.assertEqual(bytes(m.main[0xC0:0xC4]), b"\x11\x22\x33\x44")
        # the probe array's chunk boundary, element by element
        for index in (4095, 4096):
            bank, address = make_standin.probe_location(index)
            self.far_args(src=(bank, address), ptr=0x5100, length=4)
            d.call("far_read")
            self.assertEqual(bytes(m.main[0x5100:0x5104]), make_standin.probe_element(index))

    def test_far_write_both_spaces(self):
        d, m = self.d, self.m
        data = bytes(range(256)) + bytes(range(44))
        m.main[0x5200:0x5200 + 300] = data
        main_before = bytes(m.main[0x0280:0x0280 + 300])
        self.far_args(dst=(100, 0x0280), ptr=0x5200, length=300)
        d.call("far_write")
        self.assertEqual(d.far(100, 0x0280, 300), data)
        self.assertEqual(bytes(m.main[0x0280:0x0280 + 300]), main_before)
        before = d.far(1, 0x0280, 300)
        m.bank_memory(1)[0x6000:0x6000 + 300] = data[::-1]
        self.far_args(dst=(101, 0xBE00), ptr=0x6000, length=300)
        d.call("far_write", space="game")
        self.assertEqual(d.far(101, 0xBE00, 300), data[::-1])
        self.assertEqual(d.far(1, 0x0280, 300), before)   # bank 1 not written
        self.assertEqual(m.bank, 1)

    def test_far_copy_both_spaces(self):
        d, m = self.d, self.m
        data = bytes((i * 37) & 255 for i in range(700))
        d.put_far(3, 0x9000, data)
        self.far_args(src=(3, 0x9000), dst=(110, 0x0333), length=700)
        c = d.call("far_copy")
        self.assertEqual(d.far(110, 0x0333, 700), data)
        self.assertFalse(m.sw["ramrd"] or m.sw["ramwrt"])
        self.far_args(src=(110, 0x0333), dst=(111, 0x0200), length=700)
        d.call("far_copy", space="game")
        self.assertEqual(d.far(111, 0x0200, 700), data)
        MEASURE["far_copy 700 bytes (bounced)"] = c

    def test_space_switch_keeps_registers(self):
        d, m, mpu = self.d, self.m, self.m.mpu
        for label, ramrd, bank in (("space_game", True, 1), ("space_render", False, None)):
            mpu.p = (mpu.p & ~0xC3) | 0x81       # N and C set
            sp = mpu.sp
            d.call(label, a=0x5A, x=0xA5, y=0x3C)
            a, x, y, p = d.regs
            self.assertEqual((a, x, y), (0x5A, 0xA5, 0x3C), label)
            self.assertEqual(m.sw["ramrd"], ramrd)
            self.assertEqual(m.sw["ramwrt"], ramrd)
            if bank is not None:
                self.assertEqual(m.bank, bank)
            self.assertEqual(mpu.sp, sp)
        d.call("space_render")
        MEASURE["space_game / space_render (JSR..RTS)"] = \
            f"{d.call('space_game')} / {d.call('space_render')}"

    def test_call_game_passes_registers(self):
        d, m = self.d, self.m
        # a GAME routine in bank 1: X+1, Y+1, A unchanged, carry set
        m.bank_memory(1)[0xB000:0xB004] = bytes((0xE8, 0xC8, 0x38, 0x60))   # inx iny sec rts
        m.main[0xB000] = 0x00                                                # BRK in main
        d.zp("kcall", [0x00, 0xB0])
        cycles = d.call("call_game", a=0x42, x=0x10, y=0x20)
        a, x, y, p = d.regs
        self.assertEqual((a, x, y), (0x42, 0x11, 0x21))
        self.assertTrue(p & 1)
        self.assertEqual(m.main[d.L["kspace"]], 0)
        self.assertFalse(m.sw["ramrd"] or m.sw["ramwrt"])
        MEASURE["call_game round trip (empty routine)"] = cycles

    def test_blit(self):
        d, m = self.d, self.m
        rng = random.Random(7)
        view = bytes(rng.randrange(256) for _ in range(VIEW_W * VIEW_H))
        v = d.L["VIEWBUF"]
        m.main[v:v + len(view)] = view
        aux = m.aux_banks[0]
        aux[0x2000 + 320 * 84:0x2000 + 320 * 100] = b"\x77" * (320 * 16)   # status bar rows
        shr = m.shr_writes
        io = m.io_accesses
        cycles = d.call("blit_view")
        self.assertEqual(m.shr_writes - shr, 2 * VIEW_W * VIEW_H)
        for y in range(VIEW_H):
            row = bytes(aux[0x2000 + 320 * y:0x2000 + 320 * (y + 1)])
            want = bytes(view[84 * (x // 2) + y] for x in range(320))
            self.assertEqual(row, want, f"row {y}")
        self.assertEqual(bytes(aux[0x2000 + 320 * 84:0x2000 + 320 * 100]), b"\x77" * (320 * 16))
        self.assertFalse(m.sw["ramwrt"])
        MEASURE["blit_view (160x84 -> 320x84)"] = cycles
        MEASURE["blit_view $Cxxx accesses"] = m.io_accesses - io

    def test_clock_tics(self):
        d, m = self.d, self.m
        vbl, last, acc = d.L["vbl_count"], d.L["clk_last"], d.L["clk_acc"]
        tics = []
        m.main[acc] = 0
        for i in range(60):
            m.main[last] = i & 255
            m.main[vbl] = (i + 1) & 255
            d.call("clock_tics")
            tics.append(d.regs[0])
        self.assertEqual(sum(tics), 35)
        self.assertEqual(tics[:12], [0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1])   # 7 in 12
        # a long render: 12 VBLs at once are 7 tics, capped to 4, 3 dropped
        dropped = d.get("kdropped", 2)
        m.main[acc], m.main[last], m.main[vbl] = 0, 10, 22
        d.call("clock_tics")
        self.assertEqual(d.regs[0], 4)
        self.assertEqual(d.get("kdropped", 2) - dropped, 3)

    def test_input_mapping(self):
        d, m = self.d, self.m
        kin = d.L["kin"]

        def frame():
            d.call("input_frame")
            return bytes(d.d.lc_byte(kin + i) for i in range(8))

        d.call("input_consume")
        for key, bits in (("\x0b", 1), ("w", 1), ("\x0a", 2), ("S", 2), ("\x08", 4),
                          ("\x15", 8), ("a", 0x10), (",", 0x10), ("d", 0x20), (".", 0x20),
                          ("x", 0)):
            m.hold(key)
            k = frame()
            self.assertEqual(k[3], bits, repr(key))
            self.assertEqual(k[4], ord(key.upper()), repr(key))
            m.release()
        k = frame()                                  # released: no key held
        self.assertEqual((k[3], k[4]), (0, 0))
        # Open Apple fires, Closed Apple uses, with a movement key held
        m.hold("w")
        m.buttons[0] = 0x80
        k = frame()
        self.assertEqual((k[2] & 3, k[3]), (1, 1))
        m.buttons[0], m.buttons[1] = 0, 0x80
        d.call("input_consume")
        k = frame()
        self.assertEqual(k[2] & 3, 2)
        m.buttons[1] = 0
        m.release()
        d.call("input_consume")
        # a click between tics is latched until consumed
        m.mouse_buttons(True, False)
        frame()
        m.mouse_buttons(False, False)
        k = frame()
        self.assertEqual(k[2] & 1, 1)
        d.call("input_consume")
        self.assertEqual(frame()[2] & 1, 0)
        # mouse X: relative motion, accumulated until consumed
        m.mouse_delta(25, 0)
        frame()
        m.mouse_delta(-5, 0)
        k = frame()
        self.assertEqual(int.from_bytes(k[0:2], "little", signed=True), 20)
        d.call("input_consume")
        m.mouse_delta(-300, 0)
        k = frame()
        self.assertEqual(int.from_bytes(k[0:2], "little", signed=True), -300)
        # far from the centre: re-centred, the motion still counts
        d.call("input_consume")
        m.mouse_delta(0x7000, 0)
        k = frame()
        self.assertEqual(int.from_bytes(k[0:2], "little", signed=True), 0x7000)
        self.assertEqual(m.mouse.x, 0x8000)
        m.mouse_delta(3, 0)
        self.assertEqual(int.from_bytes(frame()[0:2], "little", signed=True), 0x7003)
        d.call("input_consume")
        # digits, Esc, Tab
        m.press("5", at_cycle=0)
        k = frame()
        self.assertEqual((k[5], k[6]), (ord("5"), 5))
        m.release()
        m.press("\x1b", at_cycle=0)
        self.assertEqual(frame()[7] & 1, 1)
        m.press("\t", at_cycle=0)
        self.assertEqual(frame()[2] & 0x80, 0x80)
        m.press("\t", at_cycle=0)
        self.assertEqual(frame()[2] & 0x80, 0)
        d.call("input_consume")
        k = frame()
        self.assertEqual((k[0], k[1], k[5], k[6], k[7]), (0, 0, 0, 0, 0))
        io = m.io_accesses
        MEASURE["input_frame"] = d.call("input_frame")
        MEASURE["input_frame $Cxxx accesses"] = m.io_accesses - io


# ---------------------------------------------------------------------------
class FrameLoopTest(unittest.TestCase):
    """The frame loop over many frames (fast boot)."""

    def test_35_tics_per_60_frames(self):
        d = doomdbg.Dbg(frames=5, build=BUILD)
        for frames in (60, 120):
            t0 = d.get("ktics", 2)
            d.run_frames(frames)
            tics = d.get("ktics", 2) - t0
            self.assertLessEqual(abs(tics - frames * 35 // 60), 1, f"{tics} in {frames}")
        # the game counts the same tics
        self.assertEqual(d.d.byte("_game_tics", "game") | (d.d.byte("_game_tics", "game", 1) << 8),
                         d.get("ktics", 2))
        self.assertEqual(d.d.byte("_game_inits", "game"), 1)

    def test_game_probe_reads_data(self):
        d = doomdbg.Dbg(frames=40, build=BUILD)
        index = d.d.word("_probe_index", "game")
        value = d.far(1, d.L["_probe_value"], 4)
        self.assertEqual(value, make_standin.probe_element(index))
        self.assertEqual(index, (d.d.word("_game_tics", "game") * 1021) % make_standin.PROBE_COUNT)

    def test_game_sees_input(self):
        d = doomdbg.Dbg(frames=3, build=BUILD)
        d.m.hold("w")
        d.m.mouse_delta(40, 0)
        d.run_frames(6)
        game_input = d.far(1, d.L["_game_input"], 8)
        self.assertEqual(game_input[3], 1)                    # KM_FORWARD
        self.assertEqual(game_input[4], ord("W"))
        turn = int.from_bytes(d.far(1, d.L["_game_turn"], 2), "little", signed=True)
        self.assertEqual(turn, 40)                            # taken by one tic only

    def test_run_doom_frames(self):
        """run_doom's per-frame numbers: no torn frame, the budget, costs."""
        class Args:
            build = BUILD
            data = None
            rom = ROM
            speed = "turbo"
            banks = 128
            fast = True
            frames = 90
            out = str(ROOT / "build/standin/run")
            do = ["20:mouse 30", "40:hold w", "60:release"]
            shot = [50]
            quiet = True
            trace = []
            trace_limit = 0
            stats = str(ROOT / "build/standin/run/stats.json")
        runner = run_doom.Runner(Args)
        runner.run()
        s = runner.summary()
        self.assertEqual(s["torn"], 0)
        self.assertEqual(s["over_budget"], 0)
        self.assertLessEqual(abs(s["tics"] - 90 * 35 // 60), 2)
        rows = runner.rows[2:]
        idle = runner.machine.idle_cycles
        MEASURE["frame (tic + stub render + blit), median"] = s["work"]["median"]
        MEASURE["blits that waited for line 0"] = f"{s['waited']} of {s['frames']}"
        MEASURE["idle cycles skipped in 90 frames"] = idle
        self.assertTrue(rows)


# ---------------------------------------------------------------------------
class LoaderErrorTest(unittest.TestCase):
    def boot_error(self, banks=128, data=None):
        doom = run_doom.Doom(BUILD, data=data, banks=banks, fast=False)
        m = doom.machine
        m.load(0x2000, doom.files["DOOM.SYSTEM"])
        m.mpu.pc = 0x2000
        m.mpu.sp = 0xFF
        start = doom.label("kernel_start")
        m.run(60_000_000, stop_pc={start, doom.label("fail_wait")})
        return m.mpu.pc == start, m.text_screen()

    def test_too_little_memory(self):
        started, screen = self.boot_error(banks=32)
        self.assertFalse(started)
        self.assertIn("CANNOT LOAD, ERROR $F2", screen)

    def test_data_beyond_the_banks(self):
        # 64 banks pass the minimum; a segment in bank 70 does not fit
        tmp = ROOT / "build/standin/tmpdata"
        tmp.mkdir(exist_ok=True)
        (tmp / "HIGH.1").write_bytes(make_standin.data_file([(70, 0x0200, b"x" * 10)]))
        started, screen = self.boot_error(banks=64, data=tmp)
        self.assertFalse(started)
        self.assertIn("ERROR $F2", screen)

    def test_bad_segment(self):
        tmp = ROOT / "build/standin/tmpdata2"
        tmp.mkdir(exist_ok=True)
        bad = bytearray(make_standin.data_file([(9, 0x0200, b"y" * 10)]))
        bad[9:11] = (0xBFFC).to_bytes(2, "little")          # address + 10 > $C000
        (tmp / "BAD.1").write_bytes(bytes(bad))
        started, screen = self.boot_error(data=tmp)
        self.assertFalse(started)
        self.assertIn("ERROR $F3", screen)
        self.assertIn("BAD.1", screen)


# ---------------------------------------------------------------------------
class ModelTest(unittest.TestCase):
    def test_turbo_frame(self):
        m = a2sim.Machine(ROM, speed="turbo")
        self.assertEqual(m.frame_cycles, 1_250_000)
        self.assertEqual(m.io_cycles, 73)
        self.assertEqual(m.vbl_start, 192 * 1_250_000 // 262)
        m33 = a2sim.Machine(ROM, speed=33)
        self.assertEqual((m33.frame_cycles, m33.io_cycles), (17030 * 33, 0))

    def test_bank_aliasing(self):
        m = a2sim.Machine(ROM, ramworks_banks=64)
        m.select_bank(70)
        self.assertEqual(m.bank, 6)
        m = a2sim.Machine(ROM)
        m.select_bank(0xFF)
        self.assertEqual(m.bank, 127)

    def test_pal256_image(self):
        m = a2sim.Machine(ROM)
        aux = m.aux_banks[0]
        aux[0x9DFC:0x9E00] = b"\xD3\xC8\xD2\xB4"
        for i in range(256):
            aux[0x9E00 + 2 * i] = (i & 15) << 4 | (i >> 4)     # G = i & 15, B = i >> 4
            aux[0x9E01 + 2 * i] = 0x20 | 7
        for y in range(100):
            aux[0x2000 + 320 * y:0x2000 + 320 * (y + 1)] = bytes((x + y) & 255 for x in range(320))
        self.assertTrue(m.pal256_active())
        image = m.shr_image()
        for x, y in ((0, 0), (319, 99), (100, 50)):
            i = (x + y) & 255
            want = (7 * 16, (i & 15) * 16, (i >> 4) * 16)
            for dx in (0, 1):
                for dy in range(4):
                    self.assertEqual(image.getpixel((2 * x + dx, 4 * y + dy)), want)
        # without a selector-2 entry it is standard SHR
        for i in range(256):
            aux[0x9E01 + 2 * i] = 7
        self.assertFalse(m.pal256_active())

    def test_vbl_interrupt_and_idle_skip(self):
        m = a2sim.Machine(ROM, speed="turbo")
        # IRQ handler at $0300: inc $10, ack the card, rti; main: cli, spin
        m.main[0x0300:0x0308] = bytes((0xE6, 0x10, 0xA9, 0x03, 0x8D, 0xAF, 0xC0, 0x40))
        m.lc_read = True
        m.lc[False][0x3FFE:0x4000] = b"\x00\x03"
        m.main[0x2000:0x2004] = bytes((0x58, 0x4C, 0x01, 0x20))       # cli; jmp *
        m.mouse.write(14, 0x08)                                        # VBL interrupts
        m.idle_pcs[0x2001] = "vbl"
        m.mpu.pc = 0x2000
        m.run(10 * m.frame_cycles)
        self.assertIn(m.main[0x10], (9, 10))
        self.assertGreater(m.idle_cycles, 9 * m.frame_cycles)


if __name__ == "__main__":
    unittest.main()
