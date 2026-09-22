#!/usr/bin/env python3
"""py65 unit tests for video.s (Appletini Bosconian SHR driver).

The test assembles video.s together with tests/video_test_driver.s (which
stands in for build/assets.s) using tests/video_test.cfg, loads the image
into a 65C02 emulator and calls the driver entry points.

Memory model: main and AUX are two separate 64 KB arrays. A write to $C005
turns RAMWRT on, $C004 turns it off. While RAMWRT is on every write at or
above $0200 lands in AUX; the test records any such write that falls
outside the SHR framebuffer ($2000-$9FFF) as a violation of the RAMWRT
rule (it would have been a lost main-memory write on real hardware).
Writes to main $2000-$9FFF with RAMWRT off are also flagged (code lives
there). Reads come from main (RAMRD off); $C019 reads are served from a
scripted sequence so VBL waits can be tested. ALTZP ($C008/$C009) switches
$0000-$01FF and the language card between the main and the auxiliary set,
and reads of $C080/$C088 select bank 2/1 of $D000-$DFFF with the card
readable, so sprites kept in the auxiliary card (docs/DESIGN.md section 2)
can be tested: they are placed there directly, as loader.s would.

Run:  python3 tests/test_video.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from py65.devices.mpu65c02 import MPU

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SHR_BASE = 0x2000
SHR_END = 0xA000
ROW = 160
PANEL = 128
RAMWRTOFF = 0xC004
RAMWRTON = 0xC005
RDVBLBAR = 0xC019
NEWVIDEO = 0xC029
STORE80OFF = 0xC000
TEXTON = 0xC051
DL_MAX = 96
STAR_MAX = 48

STEP_LIMIT = 3_000_000


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def build(tmpdir):
    """Assemble and link; return (binary bytes, load address, labels)."""
    objs = []
    for src in ("video.s", os.path.join("tests", "video_test_driver.s")):
        obj = os.path.join(tmpdir, os.path.basename(src) + ".o")
        subprocess.check_call(["ca65", "--cpu", "65c02", "-I", ROOT,
                               "-o", obj, os.path.join(ROOT, src)], cwd=ROOT)
        objs.append(obj)
    binary = os.path.join(tmpdir, "test_video.bin")
    labels = os.path.join(tmpdir, "test_video.lbl")
    subprocess.check_call(["ld65", "-C", os.path.join(HERE, "video_test.cfg"),
                           "-Ln", labels, "-o", binary] + objs + ["none.lib"],
                          cwd=ROOT)
    with open(binary, "rb") as f:
        data = f.read()
    syms = {}
    with open(labels) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "al":
                syms[parts[2].lstrip(".")] = int(parts[1], 16)
    return data, 0x6000, syms


# ---------------------------------------------------------------------------
# memory with a separate AUX bank
# ---------------------------------------------------------------------------
ALTZPOFF = 0xC008
ALTZPON = 0xC009
LCBANK2RD = 0xC080
LCBANK1RD = 0xC088
BANK_1 = 2                 # _spr_bank bits (tools/gen_assets.py)
BANK_AUX = 4


class BankedMemory:
    def __init__(self):
        self.main = bytearray(0x10000)
        self.aux = bytearray(0x10000)
        # language cards: (altzp, bank2) -> $D000-$DFFF, altzp -> $E000-$FFFF
        self.lc_d = {(z, b): bytearray(0x1000) for z in (False, True) for b in (False, True)}
        self.lc_e = {False: bytearray(0x2000), True: bytearray(0x2000)}
        self.altzp = False
        self.lc_read = False
        self.lc_bank2 = True
        self.ramwrt = False
        self.vbl_seq = []          # values returned by $C019 reads
        self.vbl_reads = 0
        self.io_writes = []        # (addr, value) for $C000-$C0FF stores
        self.bad_aux_writes = []   # RAMWRT on, address outside the framebuffer
        self.bad_main_writes = []  # RAMWRT off, write into main $2000-$9FFF
        self.aux_write_count = 0

    def lc_slot(self, a):
        if a < 0xE000:
            return self.lc_d[(self.altzp, self.lc_bank2)], a - 0xD000
        return self.lc_e[self.altzp], a - 0xE000

    def __getitem__(self, a):
        if isinstance(a, slice):
            return [self[i] for i in range(*a.indices(0x10000))]
        a &= 0xFFFF
        if a == RDVBLBAR:
            self.vbl_reads += 1
            if self.vbl_seq:
                return self.vbl_seq.pop(0)
            return 0x00
        if a in (LCBANK2RD, LCBANK1RD, 0xC083, 0xC08B):
            self.lc_bank2 = a in (LCBANK2RD, 0xC083)
            self.lc_read = True
            return 0
        if 0xC000 <= a < 0xC100:
            return 0
        if a < 0x200:
            return (self.aux if self.altzp else self.main)[a]
        if a >= 0xD000 and self.lc_read:
            arr, off = self.lc_slot(a)
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
            self.io_writes.append((a, v))
            if a == RAMWRTON:
                self.ramwrt = True
            elif a == RAMWRTOFF:
                self.ramwrt = False
            elif a == ALTZPON:
                self.altzp = True
            elif a == ALTZPOFF:
                self.altzp = False
            return
        if a < 0x200:
            (self.aux if self.altzp else self.main)[a] = v
            return
        if a >= 0xD000:
            arr, off = self.lc_slot(a)       # the card is always writable here
            arr[off] = v
            return
        if self.ramwrt and a >= 0x200:
            self.aux[a] = v
            self.aux_write_count += 1
            if not (SHR_BASE <= a < SHR_END):
                self.bad_aux_writes.append(a)
        else:
            self.main[a] = v
            if SHR_BASE <= a < SHR_END:
                self.bad_main_writes.append(a)


# ---------------------------------------------------------------------------
# sprite encoder (docs/DESIGN.md section 4)
# ---------------------------------------------------------------------------
RUN_MORE = 0x80            # run_off flag: another run of the same row follows
SPLIT_GAP = 2              # transparent bytes between opaque bytes that start a new run


def encode_variant(pixels, shift):
    """pixels: list of rows, each a list of color indexes (0 = transparent).
    shift = 0 for the even variant, 1 for the odd variant (image moved one
    pixel to the right). Returns the variant bytes: a row is one run record
    per group of opaque bytes that are less than SPLIT_GAP bytes apart, bit
    7 of run_off set on every record but the row's last."""
    h = len(pixels)
    w = len(pixels[0])
    wbytes = (w + shift + 1) // 2
    out = bytearray([h, wbytes])
    for row in pixels:
        px = [0] * shift + list(row)
        px += [0] * (wbytes * 2 - len(px))
        bts = [(px[2 * i] << 4) | px[2 * i + 1] for i in range(wbytes)]
        opaque = [i for i, b in enumerate(bts) if b]
        if not opaque:
            out += bytes([0xFF, 0])
            continue
        runs = []
        first = prev = opaque[0]
        for i in opaque[1:]:
            if i - prev - 1 >= SPLIT_GAP:
                runs.append((first, prev))
                first = i
            prev = i
        runs.append((first, prev))
        for n, (first, last) in enumerate(runs):
            flag = RUN_MORE if n + 1 < len(runs) else 0
            out += bytes([first | flag, last - first + 1]) + bytes(bts[first:last + 1])
    return bytes(out)


def decode_runs(variant):
    """Return (wbytes, rows) of a variant; a row is a list of (run_off, data
    bytes) runs, empty for an empty row."""
    h, wbytes = variant[0], variant[1]
    rows = []
    p = 2
    for _ in range(h):
        runs = []
        while True:
            off, ln = variant[p], variant[p + 1]
            p += 2 + ln
            if off == 0xFF:
                break
            runs.append((off & ~RUN_MORE, variant[p - ln:p]))
            if not off & RUN_MORE:
                break
        rows.append(runs)
    return wbytes, rows


def model_draw(fb, sprites, sid, x, y, erase=False):
    """Reference drawing into a bytearray framebuffer (offset 0 = $2000).
    Returns the number of bytes written."""
    even, odd = sprites[sid]
    variant = odd if (x & 1) else even
    _, rows = decode_runs(variant)
    bc = x >> 1  # floor division, matches the arithmetic shift in asm
    n = 0
    for r, runs in enumerate(rows):
        sy = y + r
        if not (0 <= sy < 200):
            continue
        for off, data in runs:
            for k, b in enumerate(data):
                col = bc + off + k
                if 0 <= col < PANEL:
                    fb[sy * ROW + col] = 0 if erase else b
                    n += 1
    return n


def rect(w, h, color=1):
    return [[color] * w for _ in range(h)]


def numbered(w, h):
    """Sprite whose pixels are 1..15 in sequence (never 0)."""
    rows = []
    v = 1
    for _ in range(h):
        row = []
        for _ in range(w):
            row.append(v)
            v = v % 15 + 1
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# emulator wrapper
# ---------------------------------------------------------------------------
class Machine:
    def __init__(self, image, load, syms):
        self.mem = BankedMemory()
        self.mem.main[load:load + len(image)] = image
        self.syms = syms
        self.mpu = MPU(memory=self.mem)
        self.sprites = {}

    # --- helpers ---
    def poke(self, addr, data):
        if isinstance(data, int):
            data = bytes([data & 0xFF])
        self.mem.main[addr:addr + len(data)] = bytes(data)

    def peek16(self, addr):
        return self.mem.main[addr] | (self.mem.main[addr + 1] << 8)

    def fb(self):
        return bytes(self.mem.aux[SHR_BASE:SHR_END])

    def rows(self):
        """The 200 pixel rows (without the SCB/palette area)."""
        return bytes(self.mem.aux[SHR_BASE:SHR_BASE + 200 * ROW])

    def fb_byte(self, col, row):
        return self.mem.aux[SHR_BASE + row * ROW + col]

    def call(self, entry, params=(), steps=STEP_LIMIT):
        s = self.syms
        p = bytearray(8)
        for i, v in enumerate(params):
            p[i] = v & 0xFF
        self.poke(s["param"], bytes(p))
        self.mpu.pc = s[entry]
        self.mpu.sp = 0xFF
        self.mem.aux_write_count = 0
        halt = s["halt"]
        n = 0
        while self.mpu.pc != halt:
            self.mpu.step()
            n += 1
            if n > steps:
                raise AssertionError("%s did not finish within %d steps (pc=%04X)"
                                     % (entry, steps, self.mpu.pc))
        assert not self.mem.ramwrt, "%s left RAMWRT on" % entry
        assert not self.mem.altzp, "%s left ALTZP on" % entry
        assert not self.mem.bad_aux_writes, \
            "%s wrote outside AUX $2000-$9FFF with RAMWRT on: %s" % (
                entry, ["%04X" % a for a in self.mem.bad_aux_writes[:8]])
        assert not self.mem.bad_main_writes, \
            "%s wrote main $2000-$9FFF with RAMWRT off: %s" % (
                entry, ["%04X" % a for a in self.mem.bad_main_writes[:8]])
        return n

    def poke_lc(self, addr, data, bank):
        """Write into the language card that a _spr_bank code names."""
        altzp = bool(bank & BANK_AUX)
        bank2 = not bank & BANK_1
        for i, v in enumerate(data):
            a = addr + i
            if a < 0xE000:
                self.mem.lc_d[(altzp, bank2)][a - 0xD000] = v
            else:
                self.mem.lc_e[altzp][a - 0xE000] = v

    def load_sprites(self, defs, banks=None):
        """defs: {id: pixel rows}. Encodes both variants into sprite_buf (or,
        for ids that banks maps to a _spr_bank code, into that language card
        from $D000 on) and fills the lookup tables."""
        s = self.syms
        buf = s["sprite_buf"]
        p = buf
        lc_next = {}
        banks = banks or {}
        self.sprites = {}
        for sid, pixels in defs.items():
            even = encode_variant(pixels, 0)
            odd = encode_variant(pixels, 1)
            bank = banks.get(sid, 0)
            if bank:
                q = lc_next.get(bank, 0xD000)
                self.poke_lc(q, even, bank)
                ea = q
                q += len(even)
                self.poke_lc(q, odd, bank)
                oa = q
                q += len(odd)
                lc_next[bank] = q
            else:
                self.poke(p, even)
                ea = p
                p += len(even)
                self.poke(p, odd)
                oa = p
                p += len(odd)
                assert p < buf + 1024, "sprite_buf overflow"
            self.poke(s["_spr_even_lo"] + sid, ea & 0xFF)
            self.poke(s["_spr_even_hi"] + sid, ea >> 8)
            self.poke(s["_spr_odd_lo"] + sid, oa & 0xFF)
            self.poke(s["_spr_odd_hi"] + sid, oa >> 8)
            self.poke(s["_spr_width"] + sid, len(pixels[0]))
            self.poke(s["_spr_height"] + sid, len(pixels))
            self.poke(s["_spr_bank"] + sid, bank)
            self.sprites[sid] = (even, odd)

    def set_dl(self, items):
        """items: list of (id, x, y)."""
        s = self.syms
        data = bytearray()
        for sid, x, y in items:
            data += bytes([sid & 0xFF, x & 0xFF, (x >> 8) & 0xFF,
                           y & 0xFF, (y >> 8) & 0xFF, 0])
        self.poke(s["_dl_items"], bytes(data))
        self.poke(s["_dl_count"], len(items))

    def set_stars(self, stars):
        """stars: list of (x, y, color)."""
        s = self.syms
        for i, (x, y, c) in enumerate(stars):
            self.poke(s["_star_x"] + i, x)
            self.poke(s["_star_y"] + i, y)
            self.poke(s["_star_color"] + i, c)
        self.poke(s["_star_count"], len(stars))

    def frame_writes(self):
        return self.peek16(self.syms["_video_frame_writes"])

    def set_font_glyph(self, ch, rows):
        g = ord(ch) - 32
        self.poke(self.syms["_font8"] + g * 8, bytes(rows))

    def put_string(self, text):
        addr = self.syms["sprite_buf"] + 900
        self.poke(addr, text.encode("ascii") + b"\0")
        return addr


# test font: 'A' = a diagonal, 'B' = solid, '0' = alternating columns
GLYPH_A = [0b10000000, 0b01000000, 0b00100000, 0b00010000,
           0b00001000, 0b00000100, 0b00000010, 0b00000001]
GLYPH_B = [0xFF] * 8
GLYPH_0 = [0b10101010] * 8


def glyph_row_bytes(bits, color):
    out = []
    for i in range(4):
        hi = color if bits & (0x80 >> (2 * i)) else 0
        lo = color if bits & (0x40 >> (2 * i)) else 0
        out.append((hi << 4) | lo)
    return out


def glyph_row_bytes_big(bits, color):
    return [(color * 0x11) if bits & (0x80 >> i) else 0 for i in range(8)]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
class VideoTest(unittest.TestCase):
    image = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="bosco_video_")
        cls.image, cls.load, cls.syms = build(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def machine(self, init=True, banks=None):
        m = Machine(self.image, self.load, self.syms)
        m.load_sprites({
            0: numbered(4, 2),      # 4x2, every pixel a different color
            1: numbered(4, 4),      # 4x4
            2: rect(16, 16, 7),     # 16x16 solid
            3: [[0, 0, 0, 0], [0, 5, 5, 0], [0, 0, 0, 0]],  # empty rows
            4: rect(62, 3, 9),      # 62 px: 31 bytes even, 32 bytes odd (the widest run)
            5: rect(8, 8, 8),       # icon
            6: [[3] * 4 + [0] * 8 + [5] * 4] * 2,           # two runs per row (8 px gap)
            7: [[3, 3, 0, 0, 5, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]],  # a 2 px gap: one run
        }, banks)
        m.set_font_glyph("A", GLYPH_A)
        m.set_font_glyph("B", GLYPH_B)
        m.set_font_glyph("0", GLYPH_0)
        if init:
            m.call("t_init")
        return m

    # --- init / shutdown ---
    def test_init_clears_aux_and_sets_palette(self):
        m = self.machine(init=False)
        # dirty AUX first
        for a in range(SHR_BASE, SHR_END, 97):
            m.mem.aux[a] = 0xAB
        m.call("t_init")
        pal = m.mem.main[self.syms["_palette0"]:self.syms["_palette0"] + 32]
        self.assertEqual(bytes(m.mem.aux[0x9E00:0x9E20]), bytes(pal))
        rest = bytearray(m.mem.aux[SHR_BASE:SHR_END])
        rest[0x9E00 - SHR_BASE:0x9E20 - SHR_BASE] = bytes(32)
        self.assertEqual(rest.count(0), len(rest))
        # $C000 (80STORE off) written before RAMWRT on, $C029 = $C1 after RAMWRT off
        addrs = [a for a, _ in m.mem.io_writes]
        self.assertIn(STORE80OFF, addrs)
        self.assertLess(addrs.index(STORE80OFF), addrs.index(RAMWRTON))
        self.assertIn((NEWVIDEO, 0xC1), m.mem.io_writes)
        self.assertLess(addrs.index(RAMWRTOFF), addrs.index(NEWVIDEO))
        self.assertEqual(m.frame_writes(), 0)

    def test_shutdown(self):
        m = self.machine()
        m.mem.io_writes = []
        m.call("t_shutdown")
        self.assertIn((NEWVIDEO, 0x01), m.mem.io_writes)
        self.assertIn(TEXTON, [a for a, _ in m.mem.io_writes])

    # --- sprites ---
    def test_sprite_even_x(self):
        m = self.machine()
        m.set_dl([(0, 10, 5)])
        m.call("t_render")
        # 4x2 sprite at (10,5): byte column 5, rows 5 and 6
        self.assertEqual(m.fb_byte(5, 5), 0x12)
        self.assertEqual(m.fb_byte(6, 5), 0x34)
        self.assertEqual(m.fb_byte(5, 6), 0x56)
        self.assertEqual(m.fb_byte(6, 6), 0x78)
        self.assertEqual(m.fb_byte(4, 5), 0)
        self.assertEqual(m.fb_byte(7, 5), 0)
        self.assertEqual(m.frame_writes(), 4)
        self.assertEqual(m.mem.aux_write_count, 4)
        fb = bytearray(200 * ROW)
        model_draw(fb, m.sprites, 0, 10, 5)
        self.assertEqual(m.rows(), bytes(fb))

    def test_sprite_odd_x_uses_odd_variant(self):
        m = self.machine()
        m.set_dl([(0, 11, 5)])
        m.call("t_render")
        self.assertEqual(m.fb_byte(5, 5), 0x01)
        self.assertEqual(m.fb_byte(6, 5), 0x23)
        self.assertEqual(m.fb_byte(7, 5), 0x40)
        self.assertEqual(m.fb_byte(5, 6), 0x05)
        self.assertEqual(m.fb_byte(6, 6), 0x67)
        self.assertEqual(m.fb_byte(7, 6), 0x80)
        self.assertEqual(m.frame_writes(), 6)

    def test_empty_rows_are_skipped(self):
        m = self.machine()
        m.set_dl([(3, 20, 20)])
        m.call("t_render")
        self.assertEqual(m.fb_byte(10, 21), 0x05)
        self.assertEqual(m.fb_byte(11, 21), 0x50)
        self.assertEqual(m.frame_writes(), 2)
        fb = bytearray(200 * ROW)
        model_draw(fb, m.sprites, 3, 20, 20)
        self.assertEqual(m.rows(), bytes(fb))

    def check_clip(self, sid, x, y, banks=None):
        m = self.machine(banks=banks)
        m.set_dl([(sid, x, y)])
        m.call("t_render")
        fb = bytearray(200 * ROW)
        n = model_draw(fb, m.sprites, sid, x, y)
        self.assertEqual(m.rows(), bytes(fb), "sprite %d at (%d,%d)" % (sid, x, y))
        self.assertEqual(m.frame_writes(), n, "writes for (%d,%d)" % (x, y))
        return m

    def test_clip_left_even(self):
        m = self.check_clip(0, -2, 5)
        self.assertEqual(m.fb_byte(0, 5), 0x34)
        self.assertEqual(m.frame_writes(), 2)

    def test_clip_left_odd(self):
        m = self.check_clip(0, -3, 5)
        # odd variant of a 4-wide sprite at x=-3: pixel 0 of the screen is
        # the sprite's 4th pixel (shifted image: _123 4___ -> byte 1 = 0x40)
        self.assertEqual(m.fb_byte(0, 5), 0x40)
        self.assertEqual(m.frame_writes(), 2)

    def test_clip_left_far(self):
        m = self.check_clip(2, -16, 5)   # 16 wide, fully off
        self.assertEqual(m.frame_writes(), 0)
        m = self.check_clip(2, -15, 5)   # one pixel column visible
        self.assertEqual(m.frame_writes(), 16)
        self.assertEqual(m.fb_byte(0, 5), 0x70)

    def test_clip_right(self):
        m = self.check_clip(0, 254, 5)
        self.assertEqual(m.fb_byte(127, 5), 0x12)
        self.assertEqual(m.fb_byte(128, 5), 0)   # panel untouched
        self.assertEqual(m.frame_writes(), 2)
        m = self.check_clip(0, 255, 5)          # odd: only the first pixel
        self.assertEqual(m.fb_byte(127, 5), 0x01)
        self.assertEqual(m.frame_writes(), 2)
        m = self.check_clip(2, 256, 5)
        self.assertEqual(m.frame_writes(), 0)
        m = self.check_clip(2, 700, 5)
        self.assertEqual(m.frame_writes(), 0)
        m = self.check_clip(2, -700, 5)
        self.assertEqual(m.frame_writes(), 0)

    def test_clip_top(self):
        m = self.check_clip(0, 10, -1)
        self.assertEqual(m.fb_byte(5, 0), 0x56)  # second sprite row on screen row 0
        self.assertEqual(m.frame_writes(), 2)
        m = self.check_clip(1, 10, -3)
        self.assertEqual(m.frame_writes(), 2)
        m = self.check_clip(1, 10, -4)
        self.assertEqual(m.frame_writes(), 0)
        m = self.check_clip(2, 10, -300)
        self.assertEqual(m.frame_writes(), 0)

    def test_clip_bottom(self):
        m = self.check_clip(1, 10, 198)
        self.assertEqual(m.frame_writes(), 4)
        self.assertEqual(m.fb_byte(5, 199), 0x56)  # row 1 of the 4x4 sprite
        m = self.check_clip(1, 10, 199)
        self.assertEqual(m.frame_writes(), 2)
        m = self.check_clip(1, 10, 200)
        self.assertEqual(m.frame_writes(), 0)
        m = self.check_clip(2, 10, 300)
        self.assertEqual(m.frame_writes(), 0)

    def test_clip_corner(self):
        self.check_clip(2, -5, -5)
        self.check_clip(2, 250, 195)
        self.check_clip(4, -60, 100)     # 32-byte run clipped left
        self.check_clip(4, 200, 100)     # 32-byte run clipped right
        m = self.check_clip(4, 63, 100)  # full 32-byte run (odd variant)
        self.assertEqual(m.frame_writes(), 96)
        m = self.check_clip(4, 64, 100)  # 31-byte run
        self.assertEqual(m.frame_writes(), 93)

    # --- rows with more than one run ---
    def test_wide_gap_makes_two_runs(self):
        m = self.machine()
        even, _odd = m.sprites[6]
        self.assertEqual(even[2] & RUN_MORE, RUN_MORE, "first record flags a second run")
        m.set_dl([(6, 20, 10)])
        m.call("t_render")
        row = m.rows()[10 * ROW:11 * ROW]
        self.assertEqual(row[10:12], bytes([0x33, 0x33]))
        self.assertEqual(row[12:16], bytes(4), "the gap is not written")
        self.assertEqual(row[16:18], bytes([0x55, 0x55]))
        self.assertEqual(m.frame_writes(), 8)
        fb = bytearray(200 * ROW)
        model_draw(fb, m.sprites, 6, 20, 10)
        self.assertEqual(m.rows(), bytes(fb))
        # the odd variant too, and both runs are erased again
        m.set_dl([(6, 21, 10)])
        m.call("t_render")
        fb = bytearray(200 * ROW)
        model_draw(fb, m.sprites, 6, 21, 10)
        self.assertEqual(m.rows(), bytes(fb))
        m.set_dl([])
        m.call("t_render")
        self.assertEqual(m.rows().count(0), 200 * ROW)

    def test_two_run_rows_clip_and_skip_like_others(self):
        for x, y in ((-6, 10), (250, 10), (20, -1), (20, 199), (-14, 5), (244, 5)):
            self.check_clip(6, x, y)

    def test_small_gap_is_drawn_black(self):
        m = self.machine()
        m.set_dl([(7, 0, 0)])
        m.call("t_render")
        self.assertEqual(m.rows()[:4], bytes([0x33, 0x00, 0x55, 0x00]))
        self.assertEqual(m.frame_writes(), 3)

    # --- sprites in the auxiliary language card ---
    def test_aux_card_sprites_draw_and_erase(self):
        for bank in (BANK_AUX, BANK_AUX | BANK_1):
            m = self.machine(banks={0: bank, 2: bank, 6: bank})
            m.set_dl([(2, 100, 50), (0, 11, 5), (6, 30, 90), (1, 50, 50)])
            m.call("t_render")
            fb = bytearray(200 * ROW)
            n = 0
            for sid, x, y in ((2, 100, 50), (0, 11, 5), (6, 30, 90), (1, 50, 50)):
                n += model_draw(fb, m.sprites, sid, x, y)
            self.assertEqual(m.rows(), bytes(fb), f"bank {bank}")
            self.assertEqual(m.frame_writes(), n)
            addrs = [a for a, _ in m.mem.io_writes]
            self.assertIn(ALTZPON, addrs)
            self.assertIn(ALTZPOFF, addrs)
            self.assertFalse(m.mem.altzp)
            self.assertEqual(m.mem.lc_bank2, bank == BANK_AUX)
            # erasing reads the same card again
            m.set_dl([])
            m.call("t_render")
            self.assertEqual(m.rows().count(0), 200 * ROW)
            self.assertEqual(m.frame_writes(), n)

    def test_aux_card_sprites_clip(self):
        for x, y in ((-6, 10), (250, 195), (60, -3), (20, 190)):
            self.check_clip(2, x, y, banks={2: BANK_AUX})
            self.check_clip(6, x, y, banks={6: BANK_AUX | BANK_1})

    def test_main_memory_sprites_never_switch(self):
        m = self.machine()
        m.set_dl([(0, 10, 5), (2, 50, 50)])
        m.call("t_render")
        addrs = [a for a, _ in m.mem.io_writes]
        self.assertNotIn(ALTZPON, addrs)

    # --- erase ---
    def test_erase_on_next_render(self):
        m = self.machine()
        m.set_dl([(2, 100, 50)])
        m.call("t_render")
        self.assertEqual(m.frame_writes(), 128)
        m.set_dl([])
        m.call("t_render")
        self.assertEqual(m.fb()[:200 * ROW].count(0), 200 * ROW)
        self.assertEqual(m.frame_writes(), 128)
        # nothing left to erase
        m.call("t_render")
        self.assertEqual(m.frame_writes(), 0)

    def test_move_erases_old_position(self):
        m = self.machine()
        m.set_dl([(0, 10, 5)])
        m.call("t_render")
        m.set_dl([(0, 40, 60)])
        m.call("t_render")
        fb = bytearray(200 * ROW)
        model_draw(fb, m.sprites, 0, 40, 60)
        self.assertEqual(m.rows(), bytes(fb))
        self.assertEqual(m.frame_writes(), 8)

    def test_disappearing_items_are_erased(self):
        m = self.machine()
        m.set_dl([(0, 10, 5), (1, 50, 50), (2, 100, 100)])
        m.call("t_render")
        self.assertEqual(m.frame_writes(), 4 + 8 + 128)
        m.set_dl([(0, 10, 5)])
        m.call("t_render")
        fb = bytearray(200 * ROW)
        model_draw(fb, m.sprites, 0, 10, 5)
        self.assertEqual(m.rows(), bytes(fb))
        self.assertEqual(m.frame_writes(), 4 + 4 + 8 + 128)
        # more items than before: the new ones are only drawn
        m.set_dl([(0, 10, 5), (1, 50, 50)])
        m.call("t_render")
        self.assertEqual(m.frame_writes(), 4 + 4 + 8)

    def test_overlapping_items_do_not_punch_holes(self):
        m = self.machine()
        m.set_dl([(2, 100, 100), (0, 120, 110)])
        m.call("t_render")
        # item 1 moves onto where item 0 used to be; item 0 moves a bit
        m.set_dl([(2, 102, 100), (0, 104, 104)])
        m.call("t_render")
        fb = bytearray(200 * ROW)
        model_draw(fb, m.sprites, 2, 102, 100)
        model_draw(fb, m.sprites, 0, 104, 104)
        self.assertEqual(m.rows(), bytes(fb))

    def test_full_display_list(self):
        m = self.machine()
        items = [(i % 6, (i * 37) % 300 - 20, (i * 53) % 230 - 15) for i in range(DL_MAX)]
        m.set_dl(items)
        m.call("t_render")
        fb = bytearray(200 * ROW)
        n = 0
        for sid, x, y in items:
            n += model_draw(fb, m.sprites, sid, x, y)
        self.assertEqual(m.rows(), bytes(fb))
        self.assertEqual(m.frame_writes(), n)
        m.set_dl([])
        m.call("t_render")
        self.assertEqual(m.fb()[:200 * ROW].count(0), 200 * ROW)

    # --- stars ---
    def test_stars(self):
        m = self.machine()
        m.set_stars([(20, 3, 7), (21, 3, 9), (0, 0, 1), (255, 199, 15)])
        m.call("t_render")
        self.assertEqual(m.fb_byte(10, 3), 0x09)   # second star overwrote the first byte
        self.assertEqual(m.fb_byte(0, 0), 0x10)
        self.assertEqual(m.fb_byte(127, 199), 0x0F)
        self.assertEqual(m.frame_writes(), 4)
        m.set_stars([(22, 3, 7)])
        m.call("t_render")
        self.assertEqual(m.fb_byte(10, 3), 0)
        self.assertEqual(m.fb_byte(0, 0), 0)
        self.assertEqual(m.fb_byte(127, 199), 0)
        self.assertEqual(m.fb_byte(11, 3), 0x70)
        self.assertEqual(m.frame_writes(), 4 + 1)

    def test_stars_under_sprites(self):
        m = self.machine()
        m.set_stars([(100, 50, 1)])
        m.set_dl([(2, 100, 50)])
        m.call("t_render")
        self.assertEqual(m.fb_byte(50, 50), 0x77)   # sprite on top of the star
        self.assertEqual(m.frame_writes(), 129)
        m.set_dl([])
        m.call("t_render")
        self.assertEqual(m.fb_byte(50, 50), 0x10)   # star redrawn after the erase

    # --- clears ---
    def test_clear_playfield_keeps_panel_and_forgets(self):
        m = self.machine()
        m.set_dl([(2, 100, 100)])
        m.set_stars([(4, 4, 1)])
        m.call("t_render")
        m.call("t_panel_fill", (0, 0, 32, 200, 10))
        m.call("t_clear_playfield")
        fb = m.fb()
        for y in range(200):
            row = fb[y * ROW:(y + 1) * ROW]
            self.assertEqual(row[:PANEL], bytes(PANEL), "row %d" % y)
            self.assertEqual(row[PANEL:], bytes([0xAA] * 32), "row %d" % y)
        # previous positions are forgotten: nothing is erased
        m.call("t_render")
        self.assertEqual(m.frame_writes(), 129)

    def test_clear_all(self):
        m = self.machine()
        m.call("t_panel_fill", (0, 0, 32, 200, 10))
        s = m.put_string("BB")
        m.call("t_field_text", (0, 0, 1, s & 0xFF, s >> 8))
        m.set_dl([(2, 100, 100)])
        m.call("t_render")
        m.call("t_clear_all")
        fb = m.fb()
        self.assertEqual(fb[:200 * ROW].count(0), 200 * ROW)
        self.assertEqual(bytes(m.mem.aux[0x9E00:0x9E20]),
                         bytes(m.mem.main[self.syms["_palette0"]:self.syms["_palette0"] + 32]))
        m.call("t_render")
        self.assertEqual(m.frame_writes(), 128)

    # --- panel ---
    def test_panel_text(self):
        m = self.machine()
        s = m.put_string("aB")
        m.call("t_panel_text", (2, 10, 6, s & 0xFF, s >> 8))
        for r in range(8):
            row = m.fb()[(10 + r) * ROW:(11 + r) * ROW]
            self.assertEqual(list(row[PANEL + 2:PANEL + 6]), glyph_row_bytes(GLYPH_A[r], 6), "row %d" % r)
            self.assertEqual(list(row[PANEL + 6:PANEL + 10]), [0x66] * 4, "row %d" % r)
            self.assertEqual(row[PANEL + 1], 0)
            self.assertEqual(row[PANEL + 10], 0)
        self.assertEqual(m.fb()[9 * ROW + PANEL:9 * ROW + PANEL + 10], bytes(10))
        self.assertEqual(m.fb()[18 * ROW + PANEL:18 * ROW + PANEL + 10], bytes(10))
        # background is black: a second string overwrites the first
        s = m.put_string("  ")
        m.call("t_panel_text", (2, 10, 6, s & 0xFF, s >> 8))
        self.assertEqual(m.fb()[10 * ROW:18 * ROW].count(0), 8 * ROW)

    def test_panel_text_small(self):
        m = self.machine()
        s = m.put_string("A")
        m.call("t_panel_text_small", (0, 20, 1, s & 0xFF, s >> 8))
        for r in range(4):
            row = m.fb()[(20 + r) * ROW:(21 + r) * ROW]
            self.assertEqual(list(row[PANEL:PANEL + 4]), glyph_row_bytes(GLYPH_A[2 * r], 1), "row %d" % r)
        self.assertEqual(m.fb()[24 * ROW:25 * ROW].count(0), ROW)

    def test_panel_color_default(self):
        m = self.machine()
        m.call("t_set_panel_color", (4,))
        s = m.put_string("B")
        m.call("t_panel_text", (0, 0, 0xFF, s & 0xFF, s >> 8))
        self.assertEqual(m.fb_byte(PANEL, 0), 0x44)
        m.call("t_panel_dot", (10, 100, 0xFF))
        self.assertEqual(m.fb_byte(PANEL + 10, 100), 0x44)

    def test_text_past_the_bottom_never_wraps_to_the_top(self):
        # the one-byte row counter must not run past 255 into row 0
        m = self.machine()
        s = m.put_string("B")
        m.call("t_panel_text", (0, 250, 1, s & 0xFF, s >> 8))
        self.assertEqual(m.rows().count(0), 200 * ROW)
        m.call("t_field_text_big", (0, 241, 1, s & 0xFF, s >> 8))
        self.assertEqual(m.rows().count(0), 200 * ROW)
        m.call("t_panel_text", (0, 196, 1, s & 0xFF, s >> 8))
        for y in range(196, 200):
            self.assertEqual(list(m.fb()[y * ROW + PANEL:y * ROW + PANEL + 4]), [0x11] * 4)
        self.assertEqual(m.rows().count(0), 200 * ROW - 16)

    def test_panel_text_stops_at_edge(self):
        m = self.machine()
        s = m.put_string("BBBB")
        m.call("t_panel_text", (26, 0, 1, s & 0xFF, s >> 8))
        row0 = m.fb()[:ROW]
        self.assertEqual(list(row0[PANEL + 26:]), [0x11] * 4 + [0, 0])   # second glyph would pass byte 31
        self.assertEqual(m.fb()[ROW:2 * ROW][:PANEL].count(0), PANEL)   # nothing wrapped into row 1

    def test_panel_fill_and_dot(self):
        m = self.machine()
        m.call("t_panel_fill", (4, 44, 28, 10, 7))
        fb = m.fb()
        for y in range(44, 54):
            self.assertEqual(fb[y * ROW + PANEL + 4:y * ROW + PANEL + 32], bytes([0x77] * 28))
            self.assertEqual(fb[y * ROW + PANEL + 3], 0)
        self.assertEqual(fb[43 * ROW:44 * ROW].count(0), ROW)
        self.assertEqual(fb[54 * ROW:55 * ROW].count(0), ROW)
        m.call("t_panel_dot", (8, 60, 4))
        self.assertEqual(m.fb_byte(PANEL + 8, 60), 0x44)
        self.assertEqual(m.fb_byte(PANEL + 8, 61), 0x44)
        self.assertEqual(m.fb_byte(PANEL + 8, 62), 0)
        self.assertEqual(m.fb_byte(PANEL + 9, 60), 0)
        # zero size does nothing
        m.call("t_panel_fill", (0, 0, 0, 5, 1))
        m.call("t_panel_fill", (0, 0, 5, 0, 1))
        self.assertEqual(m.fb()[:ROW].count(0), ROW)

    def test_panel_sprite(self):
        m = self.machine()
        m.call("t_panel_sprite", (2, 128, 5))
        fb = m.fb()
        for y in range(128, 136):
            self.assertEqual(fb[y * ROW + PANEL + 2:y * ROW + PANEL + 6], bytes([0x88] * 4))
            self.assertEqual(fb[y * ROW + PANEL + 1], 0)
            self.assertEqual(fb[y * ROW + PANEL + 6], 0)
        self.assertEqual(fb[136 * ROW:137 * ROW].count(0), ROW)
        m.call("t_panel_sprite", (0, 0, 3))   # sprite with empty rows
        self.assertEqual(m.fb()[:ROW].count(0), ROW)
        self.assertEqual(m.fb_byte(PANEL, 1), 0x05)
        self.assertEqual(m.fb_byte(PANEL + 1, 1), 0x50)

    # --- field text ---
    def test_field_text(self):
        m = self.machine()
        s = m.put_string("0A")
        m.call("t_field_text", (20, 100, 8, s & 0xFF, s >> 8))
        fb = m.fb()
        for r in range(8):
            row = fb[(100 + r) * ROW:(101 + r) * ROW]
            self.assertEqual(list(row[10:14]), glyph_row_bytes(GLYPH_0[r], 8))
            self.assertEqual(list(row[14:18]), glyph_row_bytes(GLYPH_A[r], 8))

    def test_field_text_big(self):
        m = self.machine()
        s = m.put_string("A0")
        m.call("t_field_text_big", (20, 100, 2, s & 0xFF, s >> 8))
        fb = m.fb()
        for r in range(8):
            for sub in (0, 1):
                y = 100 + 2 * r + sub
                row = fb[y * ROW:(y + 1) * ROW]
                self.assertEqual(list(row[10:18]), glyph_row_bytes_big(GLYPH_A[r], 2), "row %d" % y)
                self.assertEqual(list(row[18:26]), glyph_row_bytes_big(GLYPH_0[r], 2), "row %d" % y)
        self.assertEqual(fb[99 * ROW:100 * ROW].count(0), ROW)
        self.assertEqual(fb[116 * ROW:117 * ROW].count(0), ROW)
        # bottom clipping: rows past 199 are dropped, nothing wraps
        s = m.put_string("B")
        m.call("t_field_text_big", (0, 190, 1, s & 0xFF, s >> 8))
        for y in range(190, 200):
            self.assertEqual(list(m.fb()[y * ROW:y * ROW + 8]), [0x11] * 8)

    # --- VBL ---
    def test_wait_vbl_returns_at_blank_to_display_edge(self):
        m = self.machine()
        # already in blank on entry: returns at the next line 0
        m.mem.vbl_seq = [0x00, 0x00, 0x80, 0x80, 0x80]
        m.mem.vbl_reads = 0
        m.call("t_wait_vbl")
        self.assertEqual(m.mem.vbl_reads, 3)
        # in display on entry: waits for the blank, then for line 0
        m.mem.vbl_seq = [0x80, 0x80, 0x00, 0x00, 0x80, 0x80]
        m.mem.vbl_reads = 0
        m.call("t_wait_vbl")
        self.assertEqual(m.mem.vbl_reads, 5)

    def test_speed_probe_counts_between_line_zeros(self):
        m = self.machine()
        k, n = 7, 11
        m.mem.vbl_seq = [0x00, 0x80] + [0x80] * k + [0x00] * n + [0x80]
        m.mem.vbl_reads = 0
        m.call("t_speed_probe")
        self.assertEqual(m.mem.vbl_reads, 2 + k + 1 + n)
        self.assertEqual(m.peek16(self.syms["result"]), k + 1 + n)

    def test_speed_probe_saturates(self):
        m = self.machine()
        m.mem.vbl_seq = [0x00, 0x80, 0x00]   # then blank forever
        m.call("t_speed_probe", steps=2_000_000)
        self.assertEqual(m.peek16(self.syms["result"]), 0xFFFF)


if __name__ == "__main__":
    unittest.main(verbosity=2)
