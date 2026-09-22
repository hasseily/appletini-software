#!/usr/bin/env python3
"""py65 unit tests for sound.c + sound_io.s (Appletini Bosconian audio).

The test compiles sound.c, assembles sound_io.s and tests/sound_test_driver.s,
links them with tests/sound_test.cfg and none.lib, loads the image into a
65C02 emulator and calls the driver entry points.

Memory model: one flat 64 KB array with an observer on $C400-$C4FF that
records every read and write (with the entry point that was running). VIA
IFR and SSI-263 reads return scripted values so the D7 path (native), the
CA1 path (Mockingboard) and the timeout path
of the speech stream can be exercised. The VIA-A "ORA no handshake" read of
the chip probe returns `ora_value`: 0 (default) means the second AY behind
VIA-A answered, so the driver runs in Phasor native mode with four chips;
$AA means a Mockingboard with two chips. Everything else in $C4xx reads 0.

Checks: the exact AY write and chip-select sequences, the probe, no $C4xx
access outside sound_init / sound_update, per-frame access budget, shadows
suppressing repeated register writes, the speech stream terminating on
both paths, VIA-A restore and chip 0 resend after SSI writes in
Mockingboard mode (and no restore in native mode), and the mailbox globals.

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

VIA_A = 0xC410           # VIA-A answers at $C41x in both Phasor modes
VIA_B = 0xC480
SSI = 0xC440
R_ORB, R_ORA, R_DDRB, R_DDRA, R_PCR, R_IFR, R_IER, R_ORA_NH = 0, 1, 2, 3, 12, 13, 14, 15

MUSIC_NONE, MUSIC_TITLE, MUSIC_BLASTOFF, MUSIC_AMBIENT = 0, 1, 2, 3
MUSIC_ROUND_CLEAR, MUSIC_DEATH, MUSIC_GAME_OVER = 4, 5, 6
SFX_NONE, SFX_SHOT, SFX_HIT, SFX_EXPLODE, SFX_POD, SFX_BASE, SFX_MINE = 0, 1, 2, 3, 4, 5, 6
SFX_PLAYER_DIE, SFX_ALERT, SFX_SPY, SFX_EXTRA_LIFE, SFX_MISSILE = 7, 8, 9, 10, 11
SAY_NONE, SAY_BLAST_OFF, SAY_ALERT, SAY_SPY, SAY_RED, SAY_BATTLE, SAY_GAME_OVER = \
    0xFF, 0, 1, 2, 3, 4, 5

# phoneme length in bits 7-6 (sound.c L4/L3/L2), pause, end
def L4(c): return c
def L3(c): return c | 0x40
def L2(c): return c | 0x80
PA = 0x00
PHRASE_BLAST_OFF = [L2(0x24), L3(0x20), L4(0x0C), L3(0x30), L2(0x28), L2(PA),
                    L4(0x10), L3(0x34)]
PHRASE_ALERT_LEN = 9
PHRASE_GAME_OVER = [L3(0x29), L4(0x05), L4(0x05), L4(0x37), L3(PA), L4(0x11),
                    L4(0x11), L3(0x33), L4(0x1C), L4(0x1C)]
SSI_SETUP = [(SSI + 3, 0x80), (SSI + 0, 0xC0), (SSI + 1, 0x40),
             (SSI + 2, 0xA8), (SSI + 3, 0x5A), (SSI + 4, 0xE8)]

FRAME_BUDGET_MAX = 300   # four chips
FRAME_BUDGET_TYPICAL = 60
STEP_LIMIT = 500_000


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def build(tmpdir):
    objs = []
    c_obj = os.path.join(tmpdir, "sound.o")
    subprocess.check_call(["cl65", "-t", "none", "--cpu", "65c02", "--standard",
                           "c99", "-Oirs", "-c", "-o", c_obj,
                           os.path.join(ROOT, "sound.c")], cwd=ROOT)
    objs.append(c_obj)
    for src in ("sound_io.s", os.path.join("tests", "sound_test_driver.s")):
        obj = os.path.join(tmpdir, os.path.basename(src) + ".o")
        subprocess.check_call(["ca65", "--cpu", "65c02", "-I", ROOT, "-o", obj,
                               os.path.join(ROOT, src)], cwd=ROOT)
        objs.append(obj)
    binary = os.path.join(tmpdir, "test_sound.bin")
    labels = os.path.join(tmpdir, "test_sound.lbl")
    subprocess.check_call(["ld65", "-C", os.path.join(HERE, "sound_test.cfg"),
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
# memory with a $C4xx observer
# ---------------------------------------------------------------------------
class Access:
    __slots__ = ("phase", "frame", "kind", "addr", "value")

    def __init__(self, phase, frame, kind, addr, value):
        self.phase, self.frame, self.kind = phase, frame, kind
        self.addr, self.value = addr, value

    def __repr__(self):
        return "%s#%d %s %04X=%02X" % (self.phase, self.frame, self.kind,
                                       self.addr, self.value)


class SlotMemory:
    def __init__(self):
        self.ram = bytearray(0x10000)
        self.log = []
        self.phase = "none"
        self.frame = -1
        self.ifr_value = 0      # returned by VIA IFR reads
        self.ora_value = 0      # returned by the probe's VIA-A ORA_NH read
        self.ssi_value = 0      # returned by SSI-263 reads (D7 = phoneme done)

    def __getitem__(self, a):
        if isinstance(a, slice):
            return [self[i] for i in range(*a.indices(0x10000))]
        a &= 0xFFFF
        if 0xC400 <= a < 0xC500:
            v = 0
            if a in (VIA_A + R_IFR, VIA_B + R_IFR):
                v = self.ifr_value
            elif a == VIA_A + R_ORA_NH:
                v = self.ora_value
            elif SSI <= a < SSI + 8:
                v = self.ssi_value
            self.log.append(Access(self.phase, self.frame, "r", a, v))
            return v
        return self.ram[a]

    def __setitem__(self, a, v):
        if isinstance(a, slice):
            for i, x in zip(range(*a.indices(0x10000)), v):
                self[i] = x
            return
        a &= 0xFFFF
        v &= 0xFF
        if 0xC400 <= a < 0xC500:
            self.log.append(Access(self.phase, self.frame, "w", a, v))
            return
        if 0xC000 <= a < 0xD000:
            return
        self.ram[a] = v


# ---------------------------------------------------------------------------
# log interpretation: VIA sequences -> AY register model
# ---------------------------------------------------------------------------
class AyEvent:
    """One decoded event: ('ay', chip, reg, val) or ('reset', chip)."""
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
    Raises AssertionError on any access that is not one of:
      AY write  : ORA_NH=reg, ORB=latch, ORB=idle, ORA_NH=val, ORB=write,
                  ORB=idle, with the chip-select values of one chip
      reset     : DDRA=$FF, DDRB=$1F, ORB=0, ORB=$0C
      probe     : (VIA-A only) ORA_NH=0, ORB=$0F, ORB=$0C, DDRA=0, ORB=$0D,
                  read ORA_NH, ORB=$0C, DDRA=$FF
      setup     : IER / PCR / IFR writes, IFR reads
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
            assert reg == R_IFR, "unexpected read %r" % x
            i += 1
            continue
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
                for s_, (r, v) in zip(seq, exp)), "bad VIA restore at %r: %r" % (x, seq)
            events.append(AyEvent(x.frame, x.phase, "reset", via + "0"))
            i += 4
            continue
        raise AssertionError("unexpected access %r" % x)
    return events


def ssi_writes(log):
    return [x for x in log if SSI <= x.addr < SSI + 8 and x.kind == "w"]


def ssi_reads(log):
    return [x for x in log if SSI <= x.addr < SSI + 8 and x.kind == "r"]


def ifr_reads(log):
    return [x for x in log if x.addr in (VIA_A + R_IFR, VIA_B + R_IFR) and x.kind == "r"]


def check_addresses(log):
    for x in log:
        ok = (VIA_A <= x.addr < VIA_A + 16) or (VIA_B <= x.addr < VIA_B + 16) or \
             (SSI <= x.addr < SSI + 8)
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

    def call(self, entry, param=0, phase=None):
        s = self.syms
        self.mem.ram[s["param"]] = param & 0xFF
        self.mem.phase = phase or entry
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

    def update(self, n=1):
        for _ in range(n):
            self.mem.frame = self.frames
            self.call("t_update")
            self.frames += 1

    def music(self, t):
        self.call("t_music", t)

    def tempo(self, t):
        self.call("t_tempo", t)

    def sfx(self, i):
        self.call("t_sfx", i)

    def say(self, p):
        self.call("t_say", p)

    def busy(self):
        self.call("t_busy")
        return self.mem.ram[self.syms["result"]]

    def shutdown(self):
        self.call("t_shutdown")

    def g(self, name):
        return self.mem.ram[self.syms[name]]

    # --- log views ---
    def frame_counts(self):
        counts = {}
        for x in self.mem.log:
            if x.phase == "t_update":
                counts[x.frame] = counts.get(x.frame, 0) + 1
        return [counts.get(f, 0) for f in range(self.frames)]

    def events(self):
        return sorted(decode_via(self.mem.log, VIA_A, "A") +
                      decode_via(self.mem.log, VIA_B, "B"),
                      key=lambda e: (e.frame, 0))


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
class SoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="bosco_sound_")
        cls.image, cls.load, cls.syms = build(cls.tmp)

    def machine(self):
        m = Machine(self.image, self.load, self.syms)
        return m

    def scenario(self, frames=120, ifr=0, ora=0):
        """The reference scenario: init, blast-off music, a shot, speech."""
        m = self.machine()
        m.mem.ifr_value = ifr
        m.mem.ora_value = ora
        m.init()
        m.music(MUSIC_BLASTOFF)
        m.sfx(SFX_SHOT)
        m.say(SAY_BLAST_OFF)
        m.update(frames)
        return m

    # ---- init ----
    def test_init_sequence(self):
        m = self.machine()
        m.init()
        log = m.mem.log
        check_addresses(log)
        self.assertTrue(all(x.phase == "t_init" for x in log))
        # VIA prep: IER=$7F, PCR=0, IFR=$7F on both VIAs, before anything else
        prep = [(x.addr, x.value) for x in log[:6]]
        self.assertEqual(prep, [(VIA_A + R_IER, 0x7F), (VIA_A + R_PCR, 0),
                                (VIA_A + R_IFR, 0x7F), (VIA_B + R_IER, 0x7F),
                                (VIA_B + R_PCR, 0), (VIA_B + R_IFR, 0x7F)])
        # SSI setup in the given order, before the VIA-A DDRA write
        s = [(x.addr, x.value) for x in ssi_writes(log)]
        self.assertEqual(s, SSI_SETUP)
        first_ddra = next(i for i, x in enumerate(log) if x.addr == VIA_A + R_DDRA)
        last_ssi = max(i for i, x in enumerate(log) if SSI <= x.addr < SSI + 8)
        self.assertLess(last_ssi, first_ddra)
        # both VIAs reset, the probe on VIA-A, then every register of every
        # chip written: mixer $3F, volumes 0 (four chips: native mode)
        ev = m.events()
        a0 = [e.kind for e in ev if e.chip == "A0"]
        self.assertEqual(a0[0], "reset")
        self.assertIn("probe", a0)
        self.assertEqual([e.kind for e in ev if e.chip == "B0"][0], "reset")
        for chip in ("A0", "A1", "B0", "B1"):
            regs = {e.reg: e.val for e in ev if e.chip == chip and e.kind == "ay"}
            self.assertEqual(sorted(regs), list(range(11)), chip)
            self.assertEqual(regs[7], 0x3F)
            self.assertEqual((regs[8], regs[9], regs[10]), (0, 0, 0))
        self.assertEqual(m.g("_sound_chips"), 4)
        self.assertEqual(m.g("_sound_current_sfx"), SFX_NONE)
        self.assertEqual(m.g("_sound_current_track"), MUSIC_NONE)
        self.assertEqual(m.g("_speech_current"), SAY_NONE)

    # ---- I/O discipline ----
    def test_no_io_outside_init_and_update(self):
        m = self.scenario()
        phases = set(x.phase for x in m.mem.log)
        self.assertEqual(phases, {"t_init", "t_update"})
        check_addresses(m.mem.log)

    def test_write_sequence_shape(self):
        m = self.scenario()
        ev = m.events()
        self.assertTrue(any(e.chip == "A0" and e.kind == "ay" for e in ev))
        self.assertTrue(any(e.chip == "B0" and e.kind == "ay" for e in ev))
        # every SSI write in play is a DUR write with a phrase phoneme
        s = [x for x in ssi_writes(m.mem.log) if x.phase == "t_update"]
        self.assertTrue(all(x.addr == SSI for x in s))

    def test_frame_budget(self):
        m = self.scenario()
        counts = m.frame_counts()
        self.assertEqual(len(counts), 120)
        self.assertLessEqual(max(counts), FRAME_BUDGET_MAX,
                             "worst frame %d accesses" % max(counts))
        median = sorted(counts)[len(counts) // 2]
        self.assertLessEqual(median, FRAME_BUDGET_TYPICAL,
                             "median frame %d accesses" % median)

    def test_quiet_frames_cost_nothing(self):
        m = self.machine()
        m.init()
        m.music(MUSIC_NONE)
        m.update(10)
        self.assertEqual(sum(m.frame_counts()), 0)

    def test_full_resend_fits_budget(self):
        """Worst case: every register of both chips changes in one frame
        (a phoneme forces AY-A, a new tune with SFX on all channels)."""
        m = self.machine()
        m.init()
        m.music(MUSIC_TITLE)
        m.sfx(SFX_BASE)
        m.sfx(SFX_MINE)
        m.sfx(SFX_PLAYER_DIE)
        m.say(SAY_SPY)
        m.update(1)
        counts = m.frame_counts()
        self.assertLessEqual(counts[0], FRAME_BUDGET_MAX)

    # ---- chips ----
    def test_mockingboard_fallback(self):
        """A Mockingboard answers the probe with $AA: two chips, no second
        chip-select ever used, VIA-A restored after each phoneme."""
        m = self.scenario(ora=0xAA)
        self.assertEqual(m.g("_sound_chips"), 2)
        ev = m.events()
        self.assertFalse([e for e in ev if e.chip in ("A1", "B1") and e.phase == "t_update"])
        self.assertEqual([e for e in ev if e.chip == "A1"][0].reg, 0)   # the probe's write
        self.assertTrue([e for e in ev if e.kind == "reset" and e.phase == "t_update"])

    def test_native_uses_four_chips(self):
        m = self.machine()
        m.init()
        m.music(MUSIC_TITLE)
        for i in (SFX_BASE, SFX_MINE, SFX_PLAYER_DIE, SFX_ALERT, SFX_SPY, SFX_SHOT):
            m.sfx(i)
        m.say(SAY_SPY)
        m.update(30)
        self.assertEqual(m.g("_sound_chips"), 4)
        ev = [e for e in m.events() if e.phase == "t_update"]
        self.assertTrue([e for e in ev if e.chip == "B1" and e.kind == "ay"])
        self.assertTrue([e for e in ev if e.chip == "A1" and e.kind == "ay"])
        # native mode: the SSI write does not alias VIA-A, so no restore
        self.assertFalse([e for e in ev if e.kind == "reset"])
        # native mode doubles the PSG clock: the title's first lead note (A4,
        # period 145) is written as 290 = $0122 on chip B0 channel A
        lead = [(e.reg, e.val) for e in ev if e.chip == "B0" and e.kind == "ay" and e.reg in (0, 1)]
        self.assertIn((0, 0x22), lead)
        self.assertIn((1, 0x01), lead)

    # ---- shadows ----
    def test_shadows_suppress_repeats(self):
        m = self.scenario(frames=200, ora=0xAA)
        ev = [e for e in m.events() if e.phase == "t_update"]
        forced = set(e.frame for e in ev if e.kind == "reset")
        model = {"A0": {}, "A1": {}, "B0": {}, "B1": {}}
        repeats = []
        for e in ev:
            if e.kind == "reset":
                model[e.chip] = {}
                continue
            regs = model[e.chip]
            if e.frame not in forced and regs.get(e.reg) == e.val:
                repeats.append(e)
            regs[e.reg] = e.val
        self.assertEqual(repeats, [], "repeated writes: %r" % repeats[:8])
        self.assertTrue(forced, "no forced resend seen (speech did not run?)")

    def test_shadows_suppress_repeats_native(self):
        m = self.scenario(frames=200)
        ev = [e for e in m.events() if e.phase == "t_update"]
        model = {"A0": {}, "A1": {}, "B0": {}, "B1": {}}
        repeats = []
        for e in ev:
            if e.kind != "ay":
                continue
            if model[e.chip].get(e.reg) == e.val:
                repeats.append(e)
            model[e.chip][e.reg] = e.val
        self.assertEqual(repeats, [], "repeated writes: %r" % repeats[:8])
        self.assertFalse([e for e in ev if e.kind == "reset"])

    # ---- speech ----
    def phoneme_frames(self, m):
        return [(x.frame, x.value) for x in ssi_writes(m.mem.log) if x.phase == "t_update"]

    def timeout_path(self, mockingboard):
        m = self.machine()
        m.mem.ifr_value = 0
        m.mem.ssi_value = 0
        m.mem.ora_value = 0xAA if mockingboard else 0
        m.init()
        m.say(SAY_BLAST_OFF)
        self.assertEqual(m.g("_speech_current"), SAY_BLAST_OFF)
        self.assertEqual(m.busy(), 1)
        busy_frames = 0
        for _ in range(140):
            m.update(1)
            if m.busy():
                busy_frames += 1
            else:
                break
        self.assertEqual(m.busy(), 0, "speech never finished on the timeout path")
        self.assertEqual(m.g("_speech_current"), SAY_NONE)
        pf = self.phoneme_frames(m)
        # the phrase, then the pause that stops the last phoneme repeating
        self.assertEqual([v for _, v in pf], PHRASE_BLAST_OFF + [PA])
        gaps = [b - a for (a, _), (b, _) in zip(pf, pf[1:])]
        self.assertTrue(all(g == 13 for g in gaps), gaps)   # 1 send + 12 timeout
        self.assertGreaterEqual(busy_frames, 8 * 13)
        return m

    def test_speech_timeout_path_native(self):
        m = self.timeout_path(mockingboard=False)
        # native mode waits on D7 of the DUR register, never on the VIAs
        self.assertTrue(ssi_reads(m.mem.log))
        self.assertFalse([x for x in ifr_reads(m.mem.log) if x.phase == "t_update"])

    def test_speech_timeout_path_mockingboard(self):
        m = self.timeout_path(mockingboard=True)
        # Mockingboard mode waits on the VIA CA1 flags; $C44x is write-only
        self.assertFalse(ssi_reads(m.mem.log))
        self.assertTrue([x for x in ifr_reads(m.mem.log) if x.phase == "t_update"])

    def test_speech_d7_path(self):
        # Phasor native mode: the chip reports the end of a phoneme as D7
        m = self.machine()
        m.mem.ssi_value = 0x80
        m.mem.ifr_value = 0
        m.init()
        m.say(SAY_BLAST_OFF)
        m.update(12)
        self.assertEqual(m.busy(), 0)
        pf = self.phoneme_frames(m)
        self.assertEqual([v for _, v in pf], PHRASE_BLAST_OFF + [PA])
        gaps = [b - a for (a, _), (b, _) in zip(pf, pf[1:])]
        self.assertTrue(all(g == 1 for g in gaps), gaps)
        # one status read per waiting frame, all of the DUR register
        reads = [x for x in ssi_reads(m.mem.log) if x.phase == "t_update"]
        self.assertEqual(len(reads), len(PHRASE_BLAST_OFF))
        self.assertTrue(all(x.addr == SSI for x in reads))
        # no phoneme is sent before the chip has finished the last one
        for i in range(1, len(pf)):
            self.assertTrue(any(x.frame == pf[i][0] for x in reads), i)

    def test_speech_d7_waits(self):
        # D7 clear: the phoneme is not replaced until the timeout
        m = self.machine()
        m.mem.ssi_value = 0x7F
        m.init()
        m.say(SAY_BLAST_OFF)
        m.update(12)
        self.assertEqual(len(self.phoneme_frames(m)), 1)
        m.mem.ssi_value = 0x80
        m.update(1)
        self.assertEqual(len(self.phoneme_frames(m)), 2)

    def test_speech_ca1_path(self):
        # Mockingboard mode: the chip raises CA1 on a VIA
        m = self.machine()
        m.mem.ora_value = 0xAA
        m.mem.ifr_value = 0x02
        m.init()
        self.assertEqual(m.g("_sound_chips"), 2)
        m.say(SAY_BLAST_OFF)
        m.update(12)
        self.assertEqual(m.busy(), 0)
        pf = self.phoneme_frames(m)
        self.assertEqual([v for _, v in pf], PHRASE_BLAST_OFF + [PA])
        gaps = [b - a for (a, _), (b, _) in zip(pf, pf[1:])]
        self.assertTrue(all(g == 1 for g in gaps), gaps)
        # the flag is cleared (write of $02 to IFR) after each completion
        clears = [x for x in m.mem.log if x.kind == "w" and x.addr == VIA_B + R_IFR
                  and x.value == 0x02 and x.phase == "t_update"]
        self.assertGreaterEqual(len(clears), len(PHRASE_BLAST_OFF))
        self.assertFalse(ssi_reads(m.mem.log))

    def test_shutdown_silences_and_powers_speech_down(self):
        for ora in (0, 0xAA):
            m = self.machine()
            m.mem.ora_value = ora
            m.mem.ssi_value = 0x80
            m.init()
            m.music(MUSIC_TITLE)
            m.sfx(SFX_SHOT)
            m.say(SAY_BLAST_OFF)
            m.update(3)
            m.shutdown()
            log = [x for x in m.mem.log if x.phase == "t_shutdown"]
            check_addresses(log)
            # the last slot access powers the speech chip down (CTL bit 7)
            self.assertEqual((log[-1].kind, log[-1].addr, log[-1].value), ("w", SSI + 3, 0x80))
            # every chip the card has: mixer off, volumes 0 (replay of all
            # AY writes; the probe's write with the second-chip select codes
            # lands on the first chip of a two-chip card)
            regs = {}
            for e in m.events():
                if e.kind == "reset":
                    regs[e.chip] = {}
                elif e.kind == "ay":
                    regs.setdefault(e.chip, {})[e.reg] = e.val
            chips = ("A0", "A1", "B0", "B1") if m.g("_sound_chips") == 4 else ("A0", "B0")
            for chip in chips:
                r = regs[chip]
                self.assertEqual(r.get(7), 0x3F, chip)
                self.assertEqual((r.get(8), r.get(9), r.get(10)), (0, 0, 0), chip)

    def test_ssi_write_restores_via_a_and_resends_ay_a(self):
        m = self.scenario(frames=120, ora=0xAA)     # Mockingboard mode
        log = m.mem.log
        ev = m.events()
        for x in ssi_writes(log):
            if x.phase != "t_update":
                continue
            f = x.frame
            # VIA-A DDRA/DDRB restore in the same frame, after the SSI write
            later = [y for y in log if y.frame == f and y.phase == "t_update"
                     and log.index(y) > log.index(x)]
            self.assertTrue(any(y.addr == VIA_A + R_DDRA and y.value == 0xFF for y in later), f)
            self.assertTrue(any(y.addr == VIA_A + R_DDRB and y.value == 0x1F for y in later), f)
            # every register of chip 0 resent in this frame or the next one
            regs = set(e.reg for e in ev if e.chip == "A0" and e.kind == "ay"
                       and e.frame in (f, f + 1))
            self.assertEqual(regs, set(range(11)), "frame %d resent %r" % (f, sorted(regs)))

    def test_speech_queue(self):
        m = self.machine()
        m.mem.ssi_value = 0x80
        m.init()
        m.say(SAY_ALERT)
        m.say(SAY_GAME_OVER)
        self.assertEqual(m.busy(), 1)
        m.update(6)
        self.assertEqual(m.busy(), 1)
        m.update(30)
        self.assertEqual(m.busy(), 0)
        pf = [v for _, v in self.phoneme_frames(m)]
        self.assertEqual(len(pf), PHRASE_ALERT_LEN + 1 + len(PHRASE_GAME_OVER) + 1)
        self.assertEqual(pf[-len(PHRASE_GAME_OVER) - 1:], PHRASE_GAME_OVER + [PA])

    # ---- mailbox / sequencing ----
    def test_mailbox_globals(self):
        m = self.machine()
        m.init()
        m.music(MUSIC_BLASTOFF)
        self.assertEqual(m.g("_sound_current_track"), MUSIC_BLASTOFF)
        m.sfx(SFX_SHOT)
        self.assertEqual(m.g("_sound_current_sfx"), SFX_SHOT)
        m.update(5)
        self.assertEqual(m.g("_sound_current_sfx"), SFX_SHOT)
        m.update(1)
        self.assertEqual(m.g("_sound_current_sfx"), SFX_NONE)
        m.update(83)     # 89 frames total: still the fanfare
        self.assertEqual(m.g("_sound_current_track"), MUSIC_BLASTOFF)
        m.update(1)      # 90: the fanfare hands over to the ambient loop
        self.assertEqual(m.g("_sound_current_track"), MUSIC_AMBIENT)

    def test_music_endings(self):
        for track, length in ((MUSIC_ROUND_CLEAR, 120), (MUSIC_DEATH, 60),
                              (MUSIC_GAME_OVER, 180)):
            m = self.machine()
            m.init()
            m.music(track)
            m.update(length - 1)
            self.assertEqual(m.g("_sound_current_track"), track)
            m.update(1)
            self.assertEqual(m.g("_sound_current_track"), MUSIC_NONE)
            n = len(m.mem.log)
            m.update(5)
            # silence after the volume-off writes: no more traffic
            self.assertLessEqual(len(m.mem.log) - n, 18)
            ev = [e for e in m.events() if e.chip == "B0" and e.kind == "ay"]
            vols = {}
            for e in ev:
                if e.reg in (8, 9, 10):
                    vols[e.reg] = e.val
            self.assertEqual(vols, {8: 0, 9: 0, 10: 0})

    def test_title_loops(self):
        m = self.machine()
        m.init()
        m.music(MUSIC_TITLE)
        m.update(32 * 8 * 2 + 4)
        self.assertEqual(m.g("_sound_current_track"), MUSIC_TITLE)
        ev = [e for e in m.events() if e.chip == "B0" and e.kind == "ay"
              and e.phase == "t_update"]
        # lead, bass and arpeggio all sounded
        self.assertTrue(any(e.reg == 8 and e.val > 0 for e in ev))
        self.assertTrue(any(e.reg == 9 and e.val > 0 for e in ev))
        self.assertTrue(any(e.reg == 10 and e.val > 0 for e in ev))
        counts = m.frame_counts()
        self.assertLessEqual(max(counts), FRAME_BUDGET_MAX)
        self.assertLessEqual(sum(counts) / len(counts), FRAME_BUDGET_TYPICAL)

    def test_ambient_tempo(self):
        def pulse_changes(level):
            m = self.machine()
            m.init()
            m.music(MUSIC_AMBIENT)
            m.tempo(level)
            m.update(240)
            ev = [e for e in m.events() if e.chip == "B0" and e.kind == "ay"
                  and e.phase == "t_update" and e.reg == 0]
            self.assertLessEqual(max(m.frame_counts()), FRAME_BUDGET_MAX)
            return len(ev)
        slow, mid, fast = pulse_changes(0), pulse_changes(1), pulse_changes(2)
        self.assertLess(slow, mid)
        self.assertLess(mid, fast)

    # ---- SFX ----
    def test_sfx_priority_and_slots(self):
        m = self.machine()
        m.mem.ora_value = 0xAA      # Mockingboard mode: three slots
        m.init()
        m.music(MUSIC_NONE)
        m.sfx(SFX_SHOT)
        m.sfx(SFX_MISSILE)
        m.sfx(SFX_HIT)
        m.update(1)
        ev = [e for e in m.events() if e.chip == "A0" and e.kind == "ay"
              and e.phase == "t_update"]
        vols = {e.reg: e.val for e in ev if e.reg in (8, 9, 10)}
        self.assertEqual(sorted(vols), [8, 9, 10])
        self.assertTrue(all(v > 0 for v in vols.values()))
        # a fourth, more important effect steals the least important slot
        m.sfx(SFX_BASE)
        self.assertEqual(m.g("_sound_current_sfx"), SFX_BASE)
        # a low-priority effect is dropped while the three slots are busy
        m.update(1)
        m.sfx(SFX_SHOT)
        self.assertEqual(m.g("_sound_current_sfx"), SFX_BASE)
        m.update(60)
        self.assertEqual(m.g("_sound_current_sfx"), SFX_NONE)
        ev = [e for e in m.events() if e.chip == "A0" and e.kind == "ay"]
        vols = {}
        for e in ev:
            if e.reg in (8, 9, 10):
                vols[e.reg] = e.val
        self.assertEqual(vols, {8: 0, 9: 0, 10: 0})
        mixer = [e.val for e in ev if e.reg == 7][-1]
        self.assertEqual(mixer, 0x3F)

    def test_alert_loops_while_retriggered(self):
        m = self.machine()
        m.init()
        m.sfx(SFX_ALERT)
        m.update(30)
        m.sfx(SFX_ALERT)           # retrigger inside the loop
        m.update(35)               # past 60: still playing
        self.assertEqual(m.g("_sound_current_sfx"), SFX_ALERT)
        m.update(60)
        self.assertEqual(m.g("_sound_current_sfx"), SFX_NONE)

    def test_every_sfx_runs_to_the_end(self):
        lengths = {SFX_SHOT: 6, SFX_HIT: 10, SFX_EXPLODE: 18, SFX_POD: 12,
                   SFX_BASE: 40, SFX_MINE: 24, SFX_PLAYER_DIE: 50, SFX_ALERT: 60,
                   SFX_SPY: 30, SFX_EXTRA_LIFE: 20, SFX_MISSILE: 12}
        for sid, ln in lengths.items():
            m = self.machine()
            m.init()
            m.sfx(sid)
            m.update(ln - 1)
            self.assertEqual(m.g("_sound_current_sfx"), sid, sid)
            m.update(1)
            self.assertEqual(m.g("_sound_current_sfx"), SFX_NONE, sid)
            ev = [e for e in m.events() if e.chip == "A0" and e.kind == "ay"
                  and e.phase == "t_update"]
            # volumes stay in 0..15 and noise periods in 0..31 (u8 math sanity)
            for e in ev:
                if e.reg in (8, 9, 10):
                    self.assertLessEqual(e.val, 15, (sid, e))
                if e.reg == 6:
                    self.assertLessEqual(e.val, 31, (sid, e))
                if e.reg in (1, 3, 5):
                    self.assertLessEqual(e.val, 15, (sid, e))
            self.assertLessEqual(max(m.frame_counts()), FRAME_BUDGET_MAX, sid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
