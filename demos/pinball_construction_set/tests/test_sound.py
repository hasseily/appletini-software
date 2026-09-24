#!/usr/bin/env python3
"""py65 unit tests for src/sound.s (the Phasor driver of the PCS port).

The test assembles src/sound.s and tests/sound_test_driver.s with
ca65 --cpu 65c02, links them with tests/sound_test.cfg, loads the image
into a 65C02 emulator and calls the driver entry points.

Memory model: one flat 64 KB array with an observer on every I/O access
($C000-$CFFF). Slot 4 accesses ($C400-$C4FF and the $C0Cx mode switches)
are logged with the entry point that was running; any other I/O access is
an error. The VIA-A "ORA no handshake" read of the chip probe returns
`ora_value`: 0 (default) means the second AY behind VIA-A answered (Phasor
native mode, four chips), $AA means a Mockingboard (two chips). Reads of
the SSI-263 return `ssi_value` (D7 = phoneme done). Everything else reads
0.

Checks: the mode switch, VIA setup and probe in snd_init and the chip
count in MB_SOUND; no slot access outside snd_init / snd_frame /
snd_shutdown; a quiet frame costs nothing; every effect writes the AY
over several frames, follows the original's pitch contour, is silent
within 40 frames and never repeats a register value (shadows); the SND /
SOUND hook's SERIES/SLICE semantics, STGL gate and X/Y preservation;
mute, by snd_mute and by STGL (cleared by snd_init, honoured by
snd_frame); the speech queue on the D7 and timeout paths; shutdown.

Run:  python3 tests/test_sound.py
"""

import os
import subprocess
import sys
import tempfile
import unittest

from py65.devices.mpu65c02 import MPU

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")

VIA_A = 0xC410
VIA_B = 0xC480
SSI = 0xC440
PHASOR_MB, PHASOR_NATIVE = 0xC0C8, 0xC0C5
R_ORB, R_ORA, R_DDRB, R_DDRA, R_PCR, R_IFR, R_IER, R_ORA_NH = 0, 1, 2, 3, 12, 13, 14, 15

STGL, SERIES, SLICE = 0x3E, 0xC8, 0xC9
MB_SOUND = 0x0313

CODES = (0, 4, 12, 20, 36, 56, 76)              # EFFECTS offsets of noise 1..7
SLICES = {0: 3, 4: 7, 12: 7, 20: 15, 36: 19, 56: 19, 76: 19}
EFFECTS = bytes.fromhex(
    "540C5400" "0C1824303C485400" "54483C3024180C00"
    "540C540C540C540C0C243C54543C2400"
    "0C1824303C4854483C303C483C303C483C303C00"
    "0C1824303C485454483C3024180C1824303C4800"
    "0C1824300C1824300C1824300C1824300C182400")
ROW_PERIOD = [50, 65, 80, 95, 110, 125, 140]    # row_a of sound.s

# phoneme length in bits 7-6 (sound.s L4/L3/L2), pause, end
def L4(c): return c
def L3(c): return c | 0x40
def L2(c): return c | 0x80
PA = 0x00
PLAYER = [L2(0x27), L3(0x20), L4(0x05), L3(0x1C), L2(PA)]
PHRASES = {
    0: PLAYER + [L3(0x23), L4(0x18), L3(0x38)],
    1: PLAYER + [L2(0x28), L4(0x16), L4(0x16)],
    2: PLAYER + [L3(0x36), L3(0x1D), L4(0x01), L4(0x01)],
    3: PLAYER + [L3(0x34), L4(0x11), L4(0x1D)],
    4: [L2(0x26), L4(0x05), L4(0x05), L3(0x37), L3(PA), L4(0x11), L4(0x11),
        L3(0x33), L4(0x1C), L4(0x1C)],
    5: [L3(0x37), L4(0x18), L3(0x20), L2(0x28), L3(0x07), L2(PA), L2(0x24),
        L4(0x10), L3(0x20)],
    6: [L2(0x24), L4(0x11), L3(0x38), L3(0x18), L3(0x30)],
}
SSI_SETUP = [(SSI + 3, 0x80), (SSI + 0, 0xC0), (SSI + 1, 0x40),
             (SSI + 2, 0xA8), (SSI + 3, 0x5A), (SSI + 4, 0xE8)]
SPEECH_TIMEOUT = 12

FRAME_BUDGET_MAX = 64
STEP_LIMIT = 200_000


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def assemble(src, obj):
    # -g: every label reaches the VICE label file, not only the exports
    subprocess.check_call(["ca65", "--cpu", "65c02", "-g", "-I", SRC, "-o", obj, src],
                          cwd=ROOT)


def build(tmpdir):
    objs = []
    for src in (os.path.join(SRC, "sound.s"),
                os.path.join(HERE, "sound_test_driver.s")):
        obj = os.path.join(tmpdir, os.path.basename(src) + ".o")
        assemble(src, obj)
        objs.append(obj)
    binary = os.path.join(tmpdir, "test_sound.bin")
    labels = os.path.join(tmpdir, "test_sound.lbl")
    subprocess.check_call(["ld65", "-C", os.path.join(HERE, "sound_test.cfg"),
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


# ---------------------------------------------------------------------------
# memory with an I/O observer
# ---------------------------------------------------------------------------
class Access:
    __slots__ = ("phase", "frame", "kind", "addr", "value")

    def __init__(self, phase, frame, kind, addr, value):
        self.phase, self.frame, self.kind = phase, frame, kind
        self.addr, self.value = addr, value

    def __repr__(self):
        return "%s#%d %s %04X=%02X" % (self.phase, self.frame, self.kind,
                                       self.addr, self.value)


def is_slot4(a):
    return 0xC400 <= a < 0xC500 or 0xC0C0 <= a < 0xC0D0


class SlotMemory:
    def __init__(self):
        self.ram = bytearray(0x10000)
        self.log = []           # slot 4 accesses
        self.other_io = []      # any other I/O access: always an error
        self.phase = "none"
        self.frame = -1
        self.ora_value = 0      # the probe's VIA-A ORA_NH read
        self.ssi_value = 0      # SSI-263 reads (D7 = phoneme done)

    def __getitem__(self, a):
        if isinstance(a, slice):
            return [self[i] for i in range(*a.indices(0x10000))]
        a &= 0xFFFF
        if 0xC000 <= a < 0xD000:
            v = 0
            if a == VIA_A + R_ORA_NH:
                v = self.ora_value
            elif SSI <= a < SSI + 8:
                v = self.ssi_value
            acc = Access(self.phase, self.frame, "r", a, v)
            (self.log if is_slot4(a) else self.other_io).append(acc)
            return v
        return self.ram[a]

    def __setitem__(self, a, v):
        if isinstance(a, slice):
            for i, x in zip(range(*a.indices(0x10000)), v):
                self[i] = x
            return
        a &= 0xFFFF
        v &= 0xFF
        if 0xC000 <= a < 0xD000:
            acc = Access(self.phase, self.frame, "w", a, v)
            (self.log if is_slot4(a) else self.other_io).append(acc)
            return
        self.ram[a] = v


# ---------------------------------------------------------------------------
# log interpretation: VIA sequences -> AY register events
# ---------------------------------------------------------------------------
class AyEvent:
    """('ay', chip, reg, val), ('reset', chip) or ('probe', chip)."""
    __slots__ = ("frame", "phase", "kind", "chip", "reg", "val")

    def __init__(self, frame, phase, kind, chip, reg=None, val=None):
        self.frame, self.phase, self.kind = frame, phase, kind
        self.chip, self.reg, self.val = chip, reg, val

    def __repr__(self):
        return "%s#%d %s%s r%s=%s" % (self.phase, self.frame, self.kind,
                                      self.chip, self.reg, self.val)


SEL_LATCH, SEL_WRITE, SEL_IDLE = (0x0F, 0x17), (0x0E, 0x16), (0x0C, 0x14)
SEL_READ = 0x0D


def decode_via(log, base, via):
    """Check the shape of every access to one VIA and return the AY events.
    Every access must be one of:
      AY write  : ORA_NH=reg, ORB=latch, ORB=idle, ORA_NH=val, ORB=write,
                  ORB=idle, with the chip-select values of one chip
      reset     : DDRA=$FF, DDRB=$1F, ORB=0, ORB=$0C
      probe     : (VIA-A) ORA_NH=0, ORB=$0F, ORB=$0C, DDRA=0, ORB=$0D,
                  read ORA_NH, ORB=$0C, DDRA=$FF
      setup     : IER / PCR / IFR writes
    Chip names are via + select: A0, A1, B0, B1.
    """
    acc = [x for x in log if base <= x.addr < base + 16]
    events = []
    i = 0
    n = len(acc)
    while i < n:
        x = acc[i]
        reg = x.addr - base
        if x.kind == "r":
            raise AssertionError("unexpected read %r" % x)
        if reg in (R_IER, R_PCR, R_IFR):
            i += 1
            continue
        if reg == R_ORA_NH:
            seq = acc[i:i + 8]
            probe = [(R_ORA_NH, 0, "w"), (R_ORB, 0x0F, "w"), (R_ORB, 0x0C, "w"),
                     (R_DDRA, 0x00, "w"), (R_ORB, SEL_READ, "w"), (R_ORA_NH, None, "r"),
                     (R_ORB, 0x0C, "w"), (R_DDRA, 0xFF, "w")]
            if via == "A" and len(seq) == 8 and all(
                    s_.kind == k and s_.addr - base == r and (v is None or s_.value == v)
                    for s_, (r, v, k) in zip(seq, probe)):
                events.append(AyEvent(x.frame, x.phase, "probe", via + "0"))
                i += 8
                continue
            seq = acc[i:i + 6]
            assert len(seq) == 6, "truncated AY write at %r" % x
            sel = None
            for k in (0, 1):
                exp = [(R_ORA_NH, None), (R_ORB, SEL_LATCH[k]), (R_ORB, SEL_IDLE[k]),
                       (R_ORA_NH, None), (R_ORB, SEL_WRITE[k]), (R_ORB, SEL_IDLE[k])]
                if all(s_.kind == "w" and s_.addr - base == r and (v is None or s_.value == v)
                       for s_, (r, v) in zip(seq, exp)):
                    sel = k
            assert sel is not None, "bad AY write sequence at %r: %r" % (x, seq)
            assert seq[0].value <= 13, "AY register out of range: %r" % seq
            events.append(AyEvent(x.frame, x.phase, "ay", via + str(sel),
                                  seq[0].value, seq[3].value))
            i += 6
            continue
        if reg == R_DDRA:
            seq = acc[i:i + 4]
            exp = [(R_DDRA, 0xFF), (R_DDRB, 0x1F), (R_ORB, 0), (R_ORB, 0x0C)]
            assert len(seq) == 4 and all(
                s_.kind == "w" and s_.addr - base == r and s_.value == v
                for s_, (r, v) in zip(seq, exp)), "bad VIA reset at %r: %r" % (x, seq)
            events.append(AyEvent(x.frame, x.phase, "reset", via + "0"))
            i += 4
            continue
        raise AssertionError("unexpected access %r" % x)
    return events


def ssi_writes(log):
    return [x for x in log if SSI <= x.addr < SSI + 8 and x.kind == "w"]


def ssi_reads(log):
    return [x for x in log if SSI <= x.addr < SSI + 8 and x.kind == "r"]


def check_addresses(log):
    for x in log:
        ok = (VIA_A <= x.addr < VIA_A + 16) or (VIA_B <= x.addr < VIA_B + 16) or \
             (SSI <= x.addr < SSI + 8) or \
             (x.addr in (PHASOR_MB, PHASOR_NATIVE) and x.phase == "t_init")
        assert ok, "access outside the VIA/SSI windows: %r" % x


# ---------------------------------------------------------------------------
# emulator wrapper
# ---------------------------------------------------------------------------
class Machine:
    def __init__(self, image, load, syms):
        self.mem = SlotMemory()
        self.mem.ram[load:load + len(image)] = image
        self.syms = syms
        self.mpu = MPU(memory=self.mem)
        self.frames = 0

    def call(self, entry, param=0):
        s = self.syms
        self.mem.ram[s["param"]] = param & 0xFF
        self.mem.phase = entry
        self.mpu.pc = s[entry]
        self.mpu.sp = 0xFF
        halt = s["halt"]
        n = 0
        while self.mpu.pc != halt:
            self.mpu.step()
            n += 1
            if n > STEP_LIMIT:
                raise AssertionError("%s did not finish (pc=%04X)" % (entry, self.mpu.pc))
        return n

    def init(self):
        self.mem.frame = -1
        self.call("t_init")

    def frame(self, n=1):
        for _ in range(n):
            self.mem.frame = self.frames
            self.call("t_frame")
            self.frames += 1

    def effect(self, code):
        self.call("t_effect", code)

    def mute(self, v):
        self.call("t_mute", v)

    def speak(self, p):
        self.call("t_speak", p)

    def shutdown(self):
        self.call("t_shutdown")

    def snd(self, entry="t_snd"):
        """Call the SND hook; return (X, Y) as the hook left them."""
        self.call(entry)
        r = self.syms["result"]
        return self.mem.ram[r], self.mem.ram[r + 1]

    def zp(self, a, v=None):
        if v is not None:
            self.mem.ram[a] = v
        return self.mem.ram[a]

    # --- log views ---
    def frame_counts(self):
        counts = {}
        for x in self.mem.log:
            if x.phase == "t_frame":
                counts[x.frame] = counts.get(x.frame, 0) + 1
        return [counts.get(f, 0) for f in range(self.frames)]

    def events(self):
        return sorted(decode_via(self.mem.log, VIA_A, "A") +
                      decode_via(self.mem.log, VIA_B, "B"),
                      key=lambda e: (e.frame, 0))

    def chip0_frames(self, first=0):
        """Per frame from `first`: the chip 0 register file after that
        frame's writes (a dict reg -> value), starting from silence."""
        regs = {r: 0 for r in range(11)}
        regs[7] = 0x1C
        per = {}
        for e in self.events():
            if e.phase == "t_frame" and e.chip == "A0" and e.kind == "ay":
                per.setdefault(e.frame, []).append((e.reg, e.val))
        out = []
        for f in range(first, self.frames):
            for reg, val in per.get(f, []):
                regs[reg] = val
            out.append(dict(regs))
        return out


def sound_frames(states):
    """Indices of the frames where any volume is on."""
    return [i for i, s in enumerate(states) if s[8] or s[9] or s[10]]


def periods(states, reg=0):
    """The distinct successive tone periods (lo + hi) of a voice."""
    out = []
    for s in states:
        p = s[reg] | (s[reg + 1] << 8)
        if not out or out[-1] != p:
            out.append(p)
    return out


def contour_rows(code):
    rows = []
    i = code
    while EFFECTS[i]:
        rows.append(EFFECTS[i] // 12 - 1)
        i += 1
    return rows


def expected_contour(code, native):
    """The voice A periods of a series as periods() sees them: a note
    repeated in the original ($0C $0C, $54 $54) keeps its period."""
    out = []
    for k in contour_rows(code):
        p = ROW_PERIOD[k] << native
        if not out or out[-1] != p:
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
class SoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pcs_sound_")
        cls.image, cls.load, cls.syms = build(cls.tmp)

    def machine(self, ora=0, ssi=0x80):
        m = Machine(self.image, self.load, self.syms)
        m.mem.ora_value = ora
        m.mem.ssi_value = ssi
        return m

    def played(self, code, ora=0, frames=60):
        m = self.machine(ora=ora)
        m.init()
        m.effect(code)
        m.frame(frames)
        return m

    # ---- assembly ----
    def test_assembles_with_65c02(self):
        obj = os.path.join(self.tmp, "standalone.o")
        assemble(os.path.join(SRC, "sound.s"), obj)
        self.assertTrue(os.path.getsize(obj) > 0)
        self.assertLessEqual(self.syms["snd_t1"] - self.syms["snd_t0"] + 1, 8)
        self.assertTrue(0x40 <= self.syms["snd_t0"] < 0x80)

    def test_hooks_are_aliases(self):
        s = self.syms
        self.assertEqual(s["SND"], s["SOUND"])
        self.assertEqual(s["INITSND"], s["INITSOUND"])

    # ---- init ----
    def test_init_native(self):
        m = self.machine()
        m.init()
        log = m.mem.log
        check_addresses(log)
        self.assertFalse(m.mem.other_io)
        self.assertTrue(all(x.phase == "t_init" for x in log))
        # the mode switch first: Mockingboard mode, then native
        self.assertEqual([(x.kind, x.addr) for x in log[:2]],
                         [("r", PHASOR_MB), ("r", PHASOR_NATIVE)])
        # VIA prep: IER=$7F, PCR=0, IFR=$7F on both VIAs
        prep = [(x.addr, x.value) for x in log[2:8]]
        self.assertEqual(prep, [(VIA_A + R_IER, 0x7F), (VIA_A + R_PCR, 0),
                                (VIA_A + R_IFR, 0x7F), (VIA_B + R_IER, 0x7F),
                                (VIA_B + R_PCR, 0), (VIA_B + R_IFR, 0x7F)])
        ev = m.events()
        a0 = [e.kind for e in ev if e.chip == "A0"]
        self.assertEqual(a0[0], "reset")
        self.assertIn("probe", a0)
        self.assertEqual([e.kind for e in ev if e.chip == "B0"][0], "reset")
        # the probe: $55 on chip 0, $AA on chip 1, before the read-back
        probe_at = next(i for i, e in enumerate(ev) if e.kind == "probe")
        before = [(e.chip, e.reg, e.val) for e in ev[:probe_at] if e.kind == "ay"]
        self.assertEqual(before, [("A0", 0, 0x55), ("A1", 0, 0xAA)])
        # four chips: every register of every chip written, mixer off,
        # then chip 0 gets the effect mixer (tones A, B; noise C)
        for chip in ("A0", "A1", "B0", "B1"):
            regs = {}
            for e in ev:
                if e.chip == chip and e.kind == "ay":
                    regs[e.reg] = e.val
            self.assertEqual(sorted(regs), list(range(11)), chip)
            self.assertEqual((regs[8], regs[9], regs[10]), (0, 0, 0))
            self.assertEqual(regs[7], 0x1C if chip == "A0" else 0x3F, chip)
        # the SSI-263 set up, in order, after the probe
        s = [(x.addr, x.value) for x in ssi_writes(log)]
        self.assertEqual(s, SSI_SETUP)
        self.assertEqual(m.mem.ram[MB_SOUND], 4)

    def test_init_mockingboard(self):
        m = self.machine(ora=0xAA)
        m.init()
        check_addresses(m.mem.log)
        self.assertEqual(m.mem.ram[MB_SOUND], 2)
        ev = m.events()
        # the second-chip selects are used once, by the probe, never again
        a1 = [e for e in ev if e.chip == "A1"]
        self.assertEqual([(e.reg, e.val) for e in a1], [(0, 0xAA)])
        self.assertFalse([e for e in ev if e.chip == "B1"])
        for chip in ("A0", "B0"):
            regs = {e.reg: e.val for e in ev if e.chip == chip and e.kind == "ay"}
            self.assertEqual(sorted(regs), list(range(11)), chip)
        # no speech chip there: $C44x would be VIA-A
        self.assertFalse(ssi_writes(m.mem.log))
        self.assertFalse(ssi_reads(m.mem.log))

    # ---- I/O discipline ----
    def test_no_io_outside_init_frame_shutdown(self):
        m = self.machine()
        m.init()
        m.zp(STGL, 0)
        for code in CODES:
            m.effect(code)
            m.speak(code % 7)
            m.zp(SERIES, code)
            m.zp(SLICE, 0)
            for _ in range(SLICES[code]):
                m.snd()
            m.frame(5)
        m.mute(0x80)
        m.frame(2)
        m.mute(0)
        m.call("t_initsnd")
        m.call("t_initsound")
        m.snd("t_sound")
        m.frame(50)
        m.shutdown()
        phases = set(x.phase for x in m.mem.log)
        self.assertEqual(phases, {"t_init", "t_frame", "t_shutdown"})
        check_addresses(m.mem.log)
        self.assertFalse(m.mem.other_io)

    def test_quiet_frames_cost_nothing(self):
        m = self.machine()
        m.init()
        m.frame(10)
        self.assertEqual(sum(m.frame_counts()), 0)
        # and after an effect has ended
        m.effect(4)
        m.frame(45)
        n = len(m.mem.log)
        m.frame(20)
        self.assertEqual(len(m.mem.log), n)

    def test_frame_budget(self):
        for code in CODES:
            m = self.machine()
            m.init()
            m.effect(code)
            m.speak(4)
            m.frame(60)
            counts = m.frame_counts()
            self.assertLessEqual(max(counts), FRAME_BUDGET_MAX,
                                 "code %d: worst frame %d accesses" % (code, max(counts)))

    # ---- effects ----
    def test_every_effect_plays_and_ends(self):
        for code in CODES:
            m = self.played(code)
            states = m.chip0_frames()
            on = sound_frames(states)
            self.assertTrue(on, code)
            self.assertEqual(on[0], 0, "code %d starts late" % code)
            length = on[-1] + 1
            self.assertTrue(10 <= length <= 40, "code %d: %d frames" % (code, length))
            self.assertEqual(on, list(range(length)), "code %d has a gap" % code)
            # silent afterwards, with no more traffic
            self.assertEqual((states[-1][8], states[-1][9], states[-1][10]), (0, 0, 0))
            counts = m.frame_counts()
            self.assertEqual(sum(counts[length + 1:]), 0, code)
            # register writes spread over several frames
            frames_with_writes = [f for f, c in enumerate(counts) if c]
            self.assertGreaterEqual(len(frames_with_writes), 4, code)
            # sane values: volumes 0..15, coarse periods 0..15, noise 0..31
            for e in m.events():
                if e.kind != "ay" or e.phase != "t_frame":
                    continue
                self.assertEqual(e.chip, "A0", (code, e))
                if e.reg in (8, 9, 10):
                    self.assertLessEqual(e.val, 15, (code, e))
                if e.reg in (1, 3, 5):
                    self.assertLessEqual(e.val, 15, (code, e))
                if e.reg == 6:
                    self.assertLessEqual(e.val, 31, (code, e))
                self.assertNotEqual(e.reg, 7, "the mixer never changes")

    def test_effects_follow_the_original_contours(self):
        for native in (1, 0):
            for code in CODES:
                m = self.played(code, ora=0 if native else 0xAA)
                states = m.chip0_frames()
                on = sound_frames(states)
                voice_a = periods([states[i] for i in on])
                self.assertEqual(voice_a, expected_contour(code, native), (code, native))
        # the specific shapes the design names
        m = self.played(4)
        p = periods([s for s in m.chip0_frames() if s[8]])
        self.assertEqual(p, sorted(p))                    # falling sweep
        self.assertEqual(len(set(p)), 7)
        m = self.played(12)
        p = periods([s for s in m.chip0_frames() if s[8]])
        self.assertEqual(p, sorted(p, reverse=True))      # rising sweep
        m = self.played(0)
        p = periods([s for s in m.chip0_frames() if s[8]])
        self.assertEqual(len(p), 3)
        self.assertTrue(p[0] == p[2] and p[1] < p[0])     # low, high, low
        m = self.played(76)
        p = periods([s for s in m.chip0_frames() if s[8]])
        self.assertEqual(p[:4] * 4 + p[:3], p)             # four repeated runs

    def test_note_timing_and_retrigger(self):
        """Every note of a series starts at its frame (rate frames apart);
        a chime effect restarts its envelope at the peak on each note, so a
        note the original repeats ($0C $0C in code 20) is heard twice."""
        rate = {0: 4, 4: 3, 12: 3, 20: 2, 36: 2, 56: 2, 76: 2}
        peak = {0: 15, 12: 13, 20: 15, 56: 14, 76: 15}      # retriggered effects
        for code in CODES:
            m = self.played(code)
            states = m.chip0_frames()
            rows = contour_rows(code)
            for i, k in enumerate(rows):
                s = states[i * rate[code]]
                self.assertEqual(s[0] | (s[1] << 8), ROW_PERIOD[k] << 1, (code, i))
                if code in peak:
                    self.assertEqual(s[8], peak[code], (code, i))
                    if i * rate[code] + 1 < len(rows) * rate[code]:
                        nxt = states[i * rate[code] + 1]
                        self.assertLess(nxt[8], peak[code], (code, i))   # decays
            # the continuous effects never jump back up
            if code not in peak:
                va = [s[8] for s in states]
                self.assertEqual(va, sorted(va, reverse=True), code)

    def test_effects_are_distinct(self):
        runs = {}
        for code in CODES:
            m = self.played(code)
            states = m.chip0_frames()
            runs[code] = [tuple(sorted(s.items())) for s in states[:41]]
        for a in CODES:
            for b in CODES:
                if a < b:
                    self.assertNotEqual(runs[a], runs[b], (a, b))
        # two voices with envelopes: voice A and B sound with decaying
        # volumes; the bumper thump (code 4) has a noise burst
        for code in CODES:
            m = self.played(code)
            states = m.chip0_frames()
            va = [s[8] for s in states]
            vb = [s[9] for s in states]
            self.assertGreater(max(va), 8, code)
            self.assertGreater(max(vb), 0, code)
            self.assertTrue(any(va[i] > va[i + 1] > 0 for i in range(len(va) - 1)), code)
            noise = max(s[10] for s in states)
            if code == 4:
                self.assertEqual(noise, 15)
                self.assertGreater(states[0][6], 0)       # noise period set
            elif code != 0:
                self.assertEqual(noise, 0, code)
        # the two-voice partial differs between chime and thump effects
        m = self.played(4)
        s = m.chip0_frames()[0]
        self.assertGreater(s[2] | (s[3] << 8), s[0] | (s[1] << 8))   # an octave below
        m = self.played(12)
        s = m.chip0_frames()[0]
        self.assertLess(s[2] | (s[3] << 8), s[0] | (s[1] << 8))      # above

    def test_unknown_code_is_ignored(self):
        m = self.machine()
        m.init()
        for code in (1, 5, 8, 21, 77, 96, 0xFF):
            m.effect(code)
        m.frame(10)
        self.assertEqual(sum(m.frame_counts()), 0)

    def test_effect_restarts_from_the_beginning(self):
        m = self.machine()
        m.init()
        m.effect(76)
        m.frame(9)
        first = m.chip0_frames()[0]
        m.effect(76)                        # again, mid-way
        m.frame(1)
        again = m.chip0_frames()[9]
        self.assertEqual((again[0], again[1], again[8]), (first[0], first[1], first[8]))
        m.frame(50)
        states = m.chip0_frames()
        on = sound_frames(states)
        self.assertEqual(on, list(range(on[-1] + 1)))
        self.assertLessEqual(on[-1] + 1, 9 + 40)
        # a different effect replaces the playing one at once
        m.effect(4)
        m.frame(1)
        s = m.chip0_frames()[-1]
        self.assertEqual(s[0] | (s[1] << 8), expected_contour(4, 1)[0])
        self.assertEqual(s[10], 15)

    def test_shadows_suppress_repeats(self):
        m = self.machine()
        m.init()
        for code in CODES:
            m.effect(code)
            m.frame(45)
        ev = [e for e in m.events() if e.phase == "t_frame"]
        self.assertTrue(ev)
        model = {}
        for e in m.events():
            if e.kind == "reset":
                model[e.chip] = {}
            elif e.kind == "ay":
                model.setdefault(e.chip, {})
                if e.phase == "t_frame":
                    self.assertNotEqual(model[e.chip].get(e.reg), e.val,
                                        "repeated write %r" % e)
                model[e.chip][e.reg] = e.val

    # ---- the upstream hooks ----
    def test_hook_runs_a_series(self):
        for code in CODES:
            m = self.machine()
            m.init()
            m.zp(STGL, 0)
            m.zp(SERIES, code)
            m.zp(SLICE, 0)
            n = len(m.mem.log)
            for i in range(1, SLICES[code]):
                x, y = m.snd()
                self.assertEqual((x, y), (0x5A, 0xA5))
                self.assertEqual(m.zp(SERIES), code, (code, i))
                self.assertEqual(m.zp(SLICE), i, (code, i))
            m.snd()
            self.assertEqual(m.zp(SERIES), 0xFF, code)
            self.assertEqual(m.zp(SLICE), 0, code)
            self.assertEqual(len(m.mem.log), n, "the hook touched the card")
            # slice 0 started the effect: the next frame plays its first note
            m.frame(1)
            s = m.chip0_frames()[0]
            self.assertEqual(s[0] | (s[1] << 8), expected_contour(code, 1)[0])
            self.assertGreater(s[8], 0)

    def test_hook_idle_and_gated(self):
        m = self.machine()
        m.init()
        # SERIES negative: nothing happens
        m.zp(STGL, 0)
        m.zp(SERIES, 0xFF)
        m.zp(SLICE, 0)
        m.snd()
        self.assertEqual((m.zp(SERIES), m.zp(SLICE)), (0xFF, 0))
        # STGL bit 7: nothing happens, the series stays as it is
        m.zp(STGL, 0x80)
        m.zp(SERIES, 4)
        m.zp(SLICE, 2)
        x, y = m.snd()
        self.assertEqual((x, y), (0x5A, 0xA5))
        self.assertEqual((m.zp(SERIES), m.zp(SLICE)), (4, 2))
        m.frame(3)
        self.assertEqual(sum(m.frame_counts()), 0)
        # STGL clear again: SLICE 2 only counts, the effect is not restarted
        m.zp(STGL, 0)
        m.snd("t_sound")
        self.assertEqual((m.zp(SERIES), m.zp(SLICE)), (4, 3))
        m.frame(3)
        self.assertEqual(sum(m.frame_counts()), 0)
        # SOUND is the same hook: it finishes the series
        for _ in range(4):
            m.snd("t_sound")
        self.assertEqual((m.zp(SERIES), m.zp(SLICE)), (0xFF, 0))

    def test_initsnd(self):
        m = self.machine()
        m.init()
        for entry in ("t_initsnd", "t_initsound"):
            m.zp(SERIES, 20)
            m.zp(SLICE, 9)
            n = len(m.mem.log)
            m.call(entry)
            self.assertEqual((m.zp(SERIES), m.zp(SLICE)), (0xFF, 0))
            self.assertEqual(len(m.mem.log), n)

    # ---- mute ----
    def test_mute_silences_and_ignores(self):
        m = self.machine()
        m.init()
        m.effect(36)
        m.speak(4)
        m.frame(5)
        self.assertTrue(m.chip0_frames()[-1][8] > 0)
        n = len(m.mem.log)
        m.mute(0x80)
        self.assertEqual(len(m.mem.log), n, "snd_mute touched the card")
        m.frame(1)
        s = m.chip0_frames()[-1]
        self.assertEqual((s[8], s[9], s[10]), (0, 0, 0))
        # the speech chip is left a pause, then nothing
        pa = [x for x in ssi_writes(m.mem.log) if x.frame == 5]
        self.assertEqual([x.value for x in pa], [PA])
        n = len(m.mem.log)
        m.effect(4)
        m.speak(0)
        m.frame(10)
        self.assertEqual(len(m.mem.log), n, "muted: effects and speech must be ignored")
        # sound on again: effects work
        m.mute(0)
        m.effect(4)
        m.frame(1)
        self.assertGreater(m.chip0_frames()[-1][8], 0)

    def test_init_clears_stgl(self):
        """Nothing else initialises the upstream's toggle: sound is on at boot."""
        m = self.machine()
        m.zp(STGL, 0x93)
        m.init()
        self.assertEqual(m.zp(STGL), 0)

    def test_stgl_mutes_everything(self):
        """RUN.S Ctrl-S flips STGL ($93 in, bit 7 set) and nothing calls
        snd_mute: the driver itself must stop what is sounding."""
        m = self.machine()
        m.init()
        m.effect(36)
        m.speak(4)
        m.frame(5)
        self.assertTrue(m.chip0_frames()[-1][8] > 0)
        m.zp(STGL, 0x93)
        m.frame(1)
        s = m.chip0_frames()[-1]
        self.assertEqual((s[8], s[9], s[10]), (0, 0, 0))
        pa = [x for x in ssi_writes(m.mem.log) if x.frame == 5]
        self.assertEqual([x.value for x in pa], [PA])
        # while it is set: effects and speech are refused, no traffic at all
        n = len(m.mem.log)
        m.effect(4)
        m.speak(0)
        m.frame(10)
        self.assertEqual(len(m.mem.log), n, "STGL set: effects and speech must be ignored")
        # cleared again (a second Ctrl-S): effects and speech work
        m.zp(STGL, 0)
        m.effect(4)
        m.speak(6)
        m.frame(1)
        self.assertGreater(m.chip0_frames()[-1][8], 0)
        last = self.phonemes(m)[-1]
        self.assertEqual(last, (16, PHRASES[6][0]))

    def test_noise_period_only_for_bursts(self):
        """A chime has no noise: after a thump it leaves the noise period
        alone rather than paying six accesses for a register nobody hears."""
        m = self.machine()
        m.init()
        m.effect(4)
        m.frame(30)
        m.effect(12)
        m.frame(1)
        regs = [e.reg for e in m.events() if e.phase == "t_frame" and e.frame == 30]
        self.assertNotIn(6, regs)
        self.assertIn(8, regs)

    # ---- speech ----
    def phonemes(self, m):
        return [(x.frame, x.value) for x in ssi_writes(m.mem.log) if x.phase == "t_frame"]

    def test_speech_d7_path(self):
        for phrase in range(7):
            m = self.machine(ssi=0x80)
            m.init()
            m.speak(phrase)
            m.frame(20)
            pf = self.phonemes(m)
            self.assertEqual([v for _, v in pf], PHRASES[phrase] + [PA], phrase)
            self.assertTrue(all(x.addr == SSI for x in ssi_writes(m.mem.log)
                                if x.phase == "t_frame"))
            gaps = [b - a for (a, _), (b, _) in zip(pf, pf[1:])]
            self.assertTrue(all(g == 1 for g in gaps), gaps)
            # one status read per phoneme after the first, of the DUR register
            reads = [x for x in ssi_reads(m.mem.log) if x.phase == "t_frame"]
            self.assertEqual(len(reads), len(PHRASES[phrase]))
            self.assertTrue(all(x.addr == SSI for x in reads))
            # then quiet
            n = len(m.mem.log)
            m.frame(10)
            self.assertEqual(len(m.mem.log), n)

    def test_speech_waits_for_d7(self):
        m = self.machine(ssi=0x00)
        m.init()
        m.speak(6)
        m.frame(SPEECH_TIMEOUT)
        self.assertEqual(len(self.phonemes(m)), 1)
        m.mem.ssi_value = 0x80
        m.frame(1)
        self.assertEqual(len(self.phonemes(m)), 2)

    def test_speech_timeout_path(self):
        m = self.machine(ssi=0x00)
        m.init()
        m.speak(6)
        m.frame(120)
        pf = self.phonemes(m)
        self.assertEqual([v for _, v in pf], PHRASES[6] + [PA])
        gaps = [b - a for (a, _), (b, _) in zip(pf, pf[1:])]
        self.assertTrue(all(g == SPEECH_TIMEOUT + 1 for g in gaps), gaps)

    def test_speech_queue(self):
        m = self.machine(ssi=0x80)
        m.init()
        m.speak(4)
        m.speak(5)
        m.speak(6)
        m.speak(0)                  # a fourth: dropped
        m.speak(7)                  # not a phrase
        m.frame(60)
        pf = [v for _, v in self.phonemes(m)]
        self.assertEqual(pf, PHRASES[4] + [PA] + PHRASES[5] + [PA] + PHRASES[6] + [PA])

    def test_speech_off_on_mockingboard(self):
        m = self.machine(ora=0xAA, ssi=0x80)
        m.init()
        m.speak(0)
        m.frame(30)
        self.assertFalse(ssi_writes(m.mem.log))
        self.assertFalse(ssi_reads(m.mem.log))
        self.assertEqual(sum(m.frame_counts()), 0)

    # ---- shutdown ----
    def test_shutdown_silences_and_powers_speech_down(self):
        for ora in (0, 0xAA):
            m = self.machine(ora=ora)
            m.init()
            m.effect(56)
            m.speak(4)
            m.frame(3)
            m.shutdown()
            log = [x for x in m.mem.log if x.phase == "t_shutdown"]
            check_addresses(log)
            self.assertEqual((log[-1].kind, log[-1].addr, log[-1].value), ("w", SSI + 3, 0x80))
            regs = {}
            for e in m.events():
                if e.kind == "reset":
                    regs[e.chip] = {}
                elif e.kind == "ay":
                    regs.setdefault(e.chip, {})[e.reg] = e.val
            chips = ("A0", "A1", "B0", "B1") if ora == 0 else ("A0", "B0")
            for chip in chips:
                r = regs[chip]
                self.assertEqual(r.get(7), 0x3F, chip)
                self.assertEqual((r.get(8), r.get(9), r.get(10)), (0, 0, 0), chip)
            # nothing pending afterwards
            n = len(m.mem.log)
            m.frame(5)
            self.assertEqual(len(m.mem.log), n)


if __name__ == "__main__":
    unittest.main(verbosity=2)
