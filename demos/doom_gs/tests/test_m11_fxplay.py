"""Milestone 11, first half, part fxplay (docs/SCREENS.md 2.3, 3, 4.4,
7.3; tools/sound/README.md "Effects (S4)"): the effect player
src/sound/fx.s, its model tools/sound/fxplay.py, its a2vm runs
tools/sound/fxrun65.py (docs/m11-parts/fxplay.md).

Without build/: the model on a hand-made bank (the script's steps, the
end and the last set, the underrun's hold, the stereo rule (A left, B
right, C centre: each band, the fallbacks, and every separation with
every set of busy voices against the nearest voice in pan), the
mailboxes' rules, fx_isplaying with a
pending start, the loudest voice's noise, FX_HOLD and FX_INVAL, no write
without a voice, FX_ON 0) and the test machine's ld65 map.

With cc65, build/a2vm/a2vm, the math tables, S2's player (make -C
src/sound), the 13 song files (build/sound), SFX.1 (part fxconv) and
demo3's captured sound calls (part s2cap, build/native/m11/cases):

- the checkpoint (fxrun65.checkpoint): every effect alone, PAL and NTSC,
  three volumes, each voice: the AY log equal to the model at every
  interrupt; each of the 13 songs (20 s) with the 52 effects at demo3's
  measured times: chips 0-2 equal S2's own build's log of the song alone,
  chip 3 the model's; no effect: the whole AY log equal to S2's own
  build's; the underrun; the stereo rule and the mailboxes; a tone effect
  before any song written whole; --phasor-mb-only with no AY write past
  the probe's; three effects over D_E1M1 and D_INTRO (the stack at most
  24 B); song starts swept over a frame so that VBLs land with FX_HOLD
  set: no chip-3 write in them, all of R0-R10 at the next; every run
  under --irq-bounds 00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF and the
  write log's publish order;
- the sizes: the card part within 748 B, FXCODE within $F505-$F8FF with
  pl_vbl, fx_service within 400 B;
- the planted bugs, each in a scratch copy built apart (fxrun65.PLANTED).

Run by name: python3 tools/testpar.py tests/test_m11_fxplay.py
"""

import shutil
import unittest

import support

from sound import fxplay as F  # noqa: E402
from sound import fxrun65 as R  # noqa: E402
from sound import tables  # noqa: E402

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))


def ready() -> bool:
    from native import s2run
    return HAVE_CC65 and R.A2VM.exists() and R.SFX1.exists() and \
        (s2run.TABLES / 'math' / 'squares.bin').exists() and \
        all((R.SOUND65 / n).exists()
            for n in ('player.o', 'probe.o', 'tables.inc', 'sound.lbl')) \
        and len(R.song_files()) == 13 and \
        (R.CASES / 'demo3' / 'calls.z').exists()


READY = ready()
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), the math '
       'tables (python3 tools/native/rtables.py), S2\'s player (make -C '
       'src/sound), the 13 song files (build/sound), SFX.1 (make -f '
       'src/native/m11/fxconv.mk) and demo3\'s cases (python3 '
       'tools/native/s2cap.py --capture)')
needs_build = unittest.skipUnless(READY, WHY)


# ---------------------------------------------------------------------------
# a hand-made bank: SFX.1's layout (fxconv.py) with scripts of our own
# ---------------------------------------------------------------------------

def script(steps, flags=0):
    return bytes([1, flags, len(steps) & 0xFF, len(steps) >> 8]) + \
        bytes(steps)


def bank(scripts):
    """SFX.1's bytes: the directory at $0200 (52 entries), VATT at $02D0,
    the scripts from $0350; sound k + 1 is scripts[k], the rest a lone
    end."""
    data = bytearray(0x150)
    for v in range(128):
        data[0xD0 + v] = tables.ATTENUATION_OF_VALUE[v]
    at = 0x0350
    body = bytearray()
    for k in range(52):
        s = scripts[k] if k < len(scripts) else script([0xFF])
        data[4 * k:4 * k + 4] = bytes([at & 0xFF, at >> 8, len(s) & 0xFF,
                                       len(s) >> 8])
        body += s
        at += len(s)
    return bytes(data + body)


# sound 1: tone 300 at 10, noise 5, 3 ticks; then attenuation 20, 2 ticks
# by a last set
S1 = script([0x47, 0x2C, 0x01, 10, 5, 0x02, 0x4A, 20, 0x01])
# sound 2: a tone 500 at 0 for 64 ticks, again and again (a long one)
S2 = script([0x43, 0xF4, 0x01, 0] + [0x3F] * 300 + [0xFF])
# sound 3: noise 9 at 0 for 40 ticks
S3 = script([0x46, 0, 9, 0x27, 0xFF], 2)
# sound 4: noise 17 at 0 for 40 ticks
S4 = script([0x46, 0, 17, 0x27, 0xFF], 2)
BANK = bank([S1, S2, S3, S4])


def run_until_idle(fx, limit=2000):
    out = []
    for _ in range(limit):
        out.append(fx.interrupt())
        fx.service()
        if not any(v.flags for v in fx.voices):
            break
    return out


class Model(unittest.TestCase):

    def test_steps_and_last_set(self):
        fx = F.FxPlayer(BANK)
        fx.mail_start(0, 1, 127, 64)
        fx.service()
        v = fx.voices[0]
        self.assertEqual((v.flags, v.chan, v.sound, v.rpos, v.wpos),
                         (F.ACTIVE, 0, 1, 4, len(S1)))
        first = fx.interrupt()          # 2 or 3 ticks of the first state
        self.assertEqual(first, [(3, r, x) for r, x in enumerate(
            [0x2C, 1, 0, 0, 0, 0, 5, 0x3F & ~1 & ~8,
             tables.LEVEL[10], 0, 0])])  # the shadow invalid: all
        writes = run_until_idle(fx)
        # 3 ticks at 10, 2 at 20, then the voice ends: level 0 once
        self.assertIn((3, 8, tables.LEVEL[20]), [w for b in writes
                                                 for w in b])
        self.assertEqual(writes[-1][-2:], [(3, 7, 0x3F), (3, 8, 0)])
        self.assertEqual(fx.voices[0].flags, 0)
        self.assertEqual(fx.interrupt(), [])        # no voice, no write

    def test_ticks_per_interrupt(self):
        # 2 + 52,135/65,536 ticks a PAL interrupt, 2 + 22,043 NTSC
        for ntsc, frac in ((False, 52135), (True, 22043)):
            fx = F.FxPlayer(BANK, ntsc=ntsc)
            fx.mail_start(0, 2, 127, 64)
            fx.service()
            ticks = 0
            for k in range(1, 41):
                fx.interrupt()
                fx.service()
                ticks += 2 + ((k * frac) >> 16) - (((k - 1) * frac) >> 16)
            self.assertEqual(fx.frac, (40 * frac) & 0xFFFF)
            # tick j of a 64-tick wait leaves 64 - j to run
            self.assertEqual(fx.voices[0].run, 64 - (ticks - 1) % 64)

    def test_underrun_holds(self):
        fx = F.FxPlayer(BANK)
        fx.mail_start(0, 2, 127, 64)
        fx.service()
        v = fx.voices[0]
        fx.interrupt()                  # its set read, a wait running
        v.wpos = v.rpos                 # the ring empty: nothing to read
        v.run = 1
        w = fx.interrupt()
        self.assertTrue(v.flags & F.STARVED)
        self.assertIn((3, 8, 0), w)     # silent
        rpos = v.rpos
        for _ in range(5):
            fx.interrupt()
        self.assertEqual(v.rpos, rpos)  # held
        fx.refill(v)                    # the bytes come
        w = fx.interrupt()
        self.assertFalse(v.flags & F.STARVED)
        self.assertIn((3, 8, tables.LEVEL[0]), w)

    def test_stereo_rule(self):
        def voice_of(sep, busy=()):
            fx = F.FxPlayer(BANK)
            for c, s in busy:
                fx.mail_start(c, 2, 127, s)
                fx.service()
            fx.mail_start(2, 2, 127, sep)
            fx.service()
            return fx.voices.index(fx.chan_voice(2))
        a, b, c = 0, 1, 2                           # left, right, centre
        for sep, v in ((0, a), (1, a), (64, a), (95, a), (96, c), (127, c),
                       (128, c), (129, c), (160, c), (161, b), (200, b),
                       (255, b)):
            self.assertEqual(voice_of(sep), v, sep)
        # the fallbacks: the centre busy, then the centre and a side
        self.assertEqual(voice_of(128, [(0, 128)]), a)   # 128: the left
        self.assertEqual(voice_of(96, [(0, 128)]), a)
        self.assertEqual(voice_of(100, [(0, 128), (1, 128)]), b)
        self.assertEqual(voice_of(129, [(0, 128)]), b)
        self.assertEqual(voice_of(160, [(0, 128), (1, 200)]), a)
        # a side busy: the centre, then the other side
        self.assertEqual(voice_of(95, [(0, 64)]), c)
        self.assertEqual(voice_of(1, [(0, 64), (1, 128)]), b)
        self.assertEqual(voice_of(161, [(0, 200)]), c)
        self.assertEqual(voice_of(255, [(0, 200), (1, 128)]), a)
        # every voice busy: no voice
        fx = F.FxPlayer(BANK)
        for k, s in enumerate((64, 128, 200)):
            fx.mail_start(k, 2, 127, s)
        fx.service()
        self.assertIsNone(fx.choose(128))

    def test_stereo_rule_is_the_nearest_voice_in_pan(self):
        """fxplay's choice against a second statement of the rule: the
        voices sit at separations 64 (A), 128 (C) and 192 (B); a start
        takes the free voice nearest its separation, a tie to C, then A
        (96 and 160 are the centre's, 128 leans left). Every separation,
        every set of busy voices."""
        where = {0: 64, 2: 128, 1: 192}
        tie = {2: 0, 0: 1, 1: 2}
        for busy in range(8):
            for sep in range(256):
                fx = F.FxPlayer(BANK)
                for k in range(3):
                    if busy >> k & 1:
                        fx.voices[k].flags = F.ACTIVE
                free = [k for k in range(3) if not busy >> k & 1]
                want = min(free, key=lambda k: (abs(sep - where[k]),
                                                tie[k])) if free else None
                got = fx.choose(sep)
                self.assertEqual(None if got is None else
                                 fx.voices.index(got), want, (busy, sep))

    def test_chip3_voices_table(self):
        self.assertEqual([(v.name, v.side, v.pan) for v in tables.FX_VOICES],
                         [('A', 'left', 5), ('B', 'right', 11),
                          ('C', 'centre', 8)])
        self.assertEqual(len(tables.FX_VOICES), F.VOICES)

    def test_mailboxes(self):
        fx = F.FxPlayer(BANK)
        fx.mail_start(0, 2, 127, 64)        # a start then a stop: nothing
        fx.mail_stop(0)
        self.assertFalse(fx.isplaying(0))
        fx.service()
        self.assertEqual([v.flags for v in fx.voices], [0, 0, 0])
        fx.mail_start(0, 2, 127, 64)
        fx.service()
        fx.mail_stop(0)                     # a stop then a start: the new
        fx.mail_start(0, 1, 127, 200)
        fx.service()
        self.assertEqual(fx.voices[0].flags, F.ENDING)
        self.assertEqual((fx.voices[1].flags, fx.voices[1].sound),
                         (F.ACTIVE, 1))
        fx.mail_start(1, 2, 127, 64)        # a start then a volume: the
        fx.mail_volume(1, 20)               # new volume
        fx.service()
        self.assertEqual(fx.chan_voice(1).vatt,
                         tables.ATTENUATION_OF_VALUE[20])

    def test_isplaying(self):
        fx = F.FxPlayer(BANK)
        fx.mail_start(2, 1, 127, 64)
        self.assertTrue(fx.isplaying(2))    # pending: not yet a voice
        self.assertFalse(fx.isplaying(0))
        fx.service()
        self.assertTrue(fx.isplaying(2))
        run_until_idle(fx)
        self.assertFalse(fx.isplaying(2))

    def test_loudest_noise(self):
        fx = F.FxPlayer(BANK)
        fx.mail_start(0, 3, 127, 64)        # A: noise 9, loud
        fx.mail_start(1, 4, 20, 200)        # B: noise 17, quiet
        fx.service()
        fx.interrupt()
        self.assertEqual(fx.want[6], 9)
        fx.mail_volume(0, 10)
        fx.mail_volume(1, 127)
        fx.service()
        fx.interrupt()
        self.assertEqual(fx.want[6], 17)

    def test_hold_and_invalid_shadow(self):
        fx = F.FxPlayer(BANK)
        fx.mail_start(0, 2, 127, 64)
        fx.service()
        self.assertEqual(len(fx.interrupt()), F.NREGS)
        fx.interrupt()
        fx.song_begin()
        self.assertEqual(fx.interrupt(), [])        # FX_HOLD: nothing
        fx.song_end()
        self.assertEqual([r for _, r, _ in fx.interrupt()],
                         list(range(F.NREGS)))      # FX_INVAL: all
        self.assertEqual(fx.interrupt(), [])        # then the shadow

    def test_no_effects_without_native_mode(self):
        fx = F.FxPlayer(BANK)
        fx.init(F.SND_NO_MUSIC)
        fx.mail_start(0, 1, 127, 64)
        fx.service()
        self.assertEqual([m.flags for m in fx.mail], [0, 0, 0])
        self.assertEqual([v.flags for v in fx.voices], [0, 0, 0])
        self.assertEqual(fx.interrupt(), [])

    def test_stopall(self):
        fx = F.FxPlayer(BANK)
        fx.mail_start(0, 2, 127, 64)
        fx.mail_start(1, 2, 127, 200)
        fx.service()
        fx.mail_start(2, 1, 127, 64)
        fx.stopall()
        self.assertEqual([v.flags for v in fx.voices],
                         [F.ENDING, F.ENDING, 0])
        self.assertFalse(fx.isplaying(2))

    def test_cfg(self):
        text = R.cfg_text()
        self.assertIn('FXC:    start = $F505, size = $03FB', text)
        self.assertIn('SNDZP:  start = $00D8, size = $001F', text)
        self.assertIn('S2CODE:', text)


@needs_build
class Machine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        R.make()

    def test_checkpoint(self):
        lines = []
        # by default the tool's quick sample (three of the 18 alone
        # combinations, three songs: tests/README.md); DOOM_GS_FULL=1 all
        problems = R.checkpoint(jobs=2, quick=not support.FULL,
                                out=lines.append)
        self.assertEqual(problems, [], '\n'.join(lines))
        self.assertTrue(any('FX_HOLD set (interrupts' in x for x in lines))

    def test_sizes(self):
        z = R.sizes()
        self.assertLessEqual(z['fx-card:FXCODE'], 620 + 128)
        self.assertLessEqual(z['FXCODE'], z['FXC_ROOM'])
        self.assertLessEqual(z['fx:S2CODE'], 400)

    def test_noise_case_tells(self):
        setup, _ = R.stereo_setup(R.bank_bytes())
        self.assertGreater(R.noise_telling(R.bank_bytes(), setup), 0)

    def test_planted(self):
        lines = []
        self.assertEqual(R.planted(jobs=2, out=lines.append), [],
                         '\n'.join(lines))


if __name__ == '__main__':
    unittest.main()
