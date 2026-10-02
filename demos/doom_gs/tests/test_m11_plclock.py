"""Milestone 11, first half, part plclock (docs/SCREENS.md 2.2, 2.3, 4.4,
6.5, 7.3): the IRQ entry pl_vbl, the tic clock, pl_time, the PAL/NTSC
detection (src/native/pl_irq.s) with part fxplay's effect player in the
card (src/sound/fx.s's fx_step and fx_burst), the aux card's bridge
(pl_bridge.s), the host model (tools/native/plclock.py).

Without build/: the model (the fractions from the rates, the rates within
34.9-35.0, the step form equal to the closed form, the detection's cut)
and the two generated ld65 maps against s2layout.py's places.

With cc65, build/a2vm/a2vm, the math tables (python3 tools/native/
rtables.py), S2's objects (make -C src/sound) and the song files
(build/sound/D_*.native12.ay):

- SCREENS.md 6.5's clock row: 60 s of machine time on PAL (f121) and NTSC
  (f121+ntsc), the standard detected, the tics and the fraction equal to
  the model at every VBL, 34.9-35.0 tics a second on the machine's clock;
  an interrupt with no VBL pending (the mouse button's) counts nothing;
- the IRQ row with music alone: S2's driver and player with pl_vbl give
  S2's own build's AY log write for write, 20 s of each of the 13 songs
  in the Doom profile (f121+phasor+window32), under --irq-bounds
  00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF, the interrupt's stack at most
  24 B;
- the bridge: a synthetic machine whose aux card holds only the bridge,
  its main loop on the aux zero page and stack (ALTZP on): every
  interrupt counted by the main handler, the loop's registers and stack
  intact, nothing of the aux card or the aux zero page's $D8-$FF changed;
  a BRK with ALTZP on ends at pl_crash with ALTZP off;
- the sizes: pl_vbl, the clock and pl_time within 150 B, FXCODE within
  $F505-$F8FF, the bridge within $FF00-$FFF9;
- the planted bugs, each in a scratch copy of the sources: the PAL
  fraction 45,742; the NTSC fraction for PAL; a tic lost at the
  fraction's carry; the VBL cause not checked; the handler reading main
  $0300.

Run by name: python3 tools/testpar.py tests/test_m11_plclock.py
"""

import re
import shutil
import tempfile
import unittest
from pathlib import Path

import support

from native import plclock as P  # noqa: E402
from native import s2layout as S  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))


def ready() -> bool:
    from native import s2run
    return HAVE_CC65 and s2run.A2VM.exists() and \
        (s2run.TABLES / 'math' / 'squares.bin').exists() and \
        all((P.SOUND65 / (n + '.o')).exists()
            for n in ('player', 'driver', 'probe')) and \
        (P.SOUND65 / 'sound.lbl').exists() and len(P.song_paths()) == 13


READY = ready()
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), the math '
       'tables (python3 tools/native/rtables.py), S2\'s player (make -C '
       'src/sound) and the 13 song files (build/sound/D_*.native12.ay)')
needs_build = unittest.skipUnless(READY, WHY)

SECONDS = 60.0                  # SCREENS.md 6.5: 60 s of machine time
MUSIC_SECONDS = 20.0            # 7.3: 20 s of each song
SHORT = 200                     # VBLs: the planted bugs' clock runs


class Model(unittest.TestCase):

    def test_fractions_and_rates(self):
        self.assertEqual(P.check_model(), [])
        self.assertEqual(P.TIC_FRAC, {P.STD_PAL: 45743, P.STD_NTSC: 38229})
        self.assertEqual(P.PAL_NTSC_CUT, 18655)
        self.assertAlmostEqual(P.tic_rate(P.STD_PAL), 34.9551, places=4)
        self.assertAlmostEqual(P.tic_rate(P.STD_NTSC), 34.9546, places=4)
        # the design's rejected rates: 7 tics per 10 VBLs on PAL (F2), and
        # the planted fractions, are outside or off the model
        self.assertGreater(P.vbl_hz(P.STD_PAL) * 7 / 10, P.RATE_RANGE[1])
        self.assertNotEqual(P.clock_at(2, P.STD_PAL),
                            ((2 * 45742) & 0xFFFF, (2 * 45742) >> 16))
        self.assertLess(P.tic_rate(P.STD_PAL, P.TIC_FRAC[P.STD_NTSC]),
                        P.RATE_RANGE[0])

    def test_clock_at(self):
        self.assertEqual(P.clock_at(0, P.STD_PAL), (0, 0))
        self.assertEqual(P.clock_at(1, P.STD_PAL), (45743, 0))
        self.assertEqual(P.clock_at(2, P.STD_PAL), ((2 * 45743) - 65536, 1))
        # 60 s of PAL VBLs: 3,004 VBLs give 2,096 tics
        self.assertEqual(P.clock_at(3004, P.STD_PAL)[1],
                         3004 * 45743 // 65536)

    def test_detect(self):
        self.assertEqual(P.detect(20280), P.STD_PAL)
        self.assertEqual(P.detect(20281), P.STD_PAL)     # the card's count
        self.assertEqual(P.detect(17030), P.STD_NTSC)
        self.assertEqual(P.detect(18655), P.STD_PAL)
        self.assertEqual(P.detect(18654), P.STD_NTSC)

    def test_cfgs(self):
        for kind in ('music', 'bridge'):
            text = P.cfg_text(kind)
            self.assertIn('FXCODE:', text)
            self.assertIn('start = $F505, size = $03FB', text)
            self.assertIn('start = $E900, size = $0C05', text)
            self.assertIn('SNDZP:  start = $00D8, size = $0028', text)
        self.assertIn('BRIDGE: start = $FF00, size = $00FA',
                      P.cfg_text('bridge'))
        self.assertIn('AUXVEC:', P.cfg_text('bridge'))
        self.assertNotIn('AUXVEC', P.cfg_text('music'))


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not READY:
            raise unittest.SkipTest(WHY)
        P.make()
        cls.tmp = Path(tempfile.mkdtemp(prefix='tmp-m11-plclock-test-',
                                        dir=str(BUILD)))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def work(self, name: str) -> Path:
        return self.tmp / (self.id().split('.')[-1] + '-' + name)


@needs_build
class Clock(Base):

    def check_clock(self, profile: str, std: int):
        n = int(SECONDS * P.vbl_hz(std))
        r = P.clock_run(self.work(profile), n, P.DETECT, profile)
        self.assertEqual(P.clock_problems(r, n, std), [])
        self.assertEqual(r.std, std)
        self.assertLessEqual(abs(r.count - P.VBL_CYCLES[std]), 2)
        rate, vhz = P.measured_rate(r, n, profile)
        self.assertGreaterEqual(rate, P.RATE_RANGE[0])
        self.assertLessEqual(rate, P.RATE_RANGE[1])
        self.assertAlmostEqual(vhz, P.vbl_hz(std), places=2)
        self.assertEqual(r.state.get('halt', ''), '')
        depth = P._depth(r.stack)
        self.assertIsNotNone(depth)
        self.assertLessEqual(depth, S.IRQ_STACK)
        return r

    def test_pal_60s(self):
        self.check_clock('f121', P.STD_PAL)

    def test_ntsc_60s(self):
        self.check_clock('f121+ntsc', P.STD_NTSC)

    def test_second_entry(self):
        n = 150
        plain = P.clock_run(self.work('plain'), n, P.STD_PAL, 'f121',
                            mode=P.MODE_VBL_BUTTON, idle=False)
        pressed = P.clock_run(self.work('pressed'), n, P.STD_PAL, 'f121',
                              mode=P.MODE_VBL_BUTTON, idle=False,
                              buttons=P.second_entry_buttons(n))
        self.assertEqual(P.clock_problems(plain, n, P.STD_PAL), [])
        self.assertEqual(P.clock_problems(pressed, n, P.STD_PAL), [])
        self.assertEqual(P.second_entry_problems(plain, pressed), [])
        self.assertGreaterEqual(len(pressed.irqs) - len(plain.irqs), 10)

    def test_sizes(self):
        z = P.sizes()
        self.assertEqual(P.size_problems(z), [])
        self.assertLessEqual(z['irq'], P.CARD_BUDGET)


@needs_build
class Music(Base):

    def test_songs_equal_s2(self):
        paths = P.song_paths()
        self.assertEqual(len(paths), 13)
        for path in paths:
            with self.subTest(song=path.name):
                data = path.read_bytes()
                name = path.name.split('.')[0]
                mine = P.music_run(self.work('m-' + name), data,
                                   MUSIC_SECONDS)
                ref = P.s2_music_run(self.work('s-' + name), data,
                                     MUSIC_SECONDS)
                self.assertEqual(P.music_problems(mine.run, ref), [])
                self.assertGreater(len(mine.run.bursts),
                                   MUSIC_SECONDS * 49)
                self.assertTrue(any(mine.run.bursts))
                depth = P._depth(mine.stack)
                self.assertIsNotNone(depth)
                self.assertLessEqual(depth, S.IRQ_STACK)
                st = P.irq_stats(mine.run.times, P.MUSIC_PROFILE)
                self.assertGreater(st['worst_us'], 0)

    def test_ntsc_song(self):
        data = P.song_paths()[0].read_bytes()
        mine = P.music_run(self.work('m'), data, 10.0, ntsc=True)
        ref = P.s2_music_run(self.work('s'), data, 10.0, ntsc=True)
        self.assertEqual(P.music_problems(mine.run, ref), [])

    def test_bounds_refuse_main(self):
        """The bounds are on: a run with a narrower contract (no card at
        $E000) halts in the interrupt."""
        data = P.song_paths()[0].read_bytes()
        with self.assertRaises(P.SR.RunError) as ctx:
            P.music_run(self.work('narrow'), data, 1.0,
                        irq_bounds='00D8-01FF,C0A0-C0AF,C400-C4FF,F000-FFFF')
        self.assertIn('irq-bounds', str(ctx.exception))


@needs_build
class Bridge(Base):

    def test_bridge(self):
        r = P.bridge_run(self.work('run'))
        self.assertEqual(P.bridge_problems(r), [])
        self.assertGreaterEqual(r.irqs, 99)

    def test_bridge_brk(self):
        r = P.bridge_run(self.work('brk'), frames=40, brkat=1)
        self.assertEqual(r.ended, 'pl_crash')
        self.assertEqual(r.state['switches']['altzp'], 0)

    def test_aux_card_only_bridge(self):
        r = P.bridge_run(self.work('card'), frames=5)
        card = bytearray(r.aux_card0)
        lo, hi = S.PLATFORM_CARD[1] - 0xC000, S.PLATFORM_CARD[2] - 0xC000
        self.assertTrue(any(card[lo:hi]))
        card[lo:hi] = bytes(hi - lo)
        card[0x3FFA:] = bytes(6)
        self.assertFalse(any(card))
        self.assertEqual(bytes(r.aux_card0[lo:hi]),
                         bytes(r.lc[lo:hi]))      # the same bytes in both


# ---------------------------------------------------------------------------
# Planted bugs
# ---------------------------------------------------------------------------

COPIED = ('m11.mk', 'm11/s2lay.mk', 'm11/plclock.mk', 'pl_irq.s',
          'pl_bridge.s', 'pl_ct.s', 'pl_bt.s')


@needs_build
class Planted(Base):

    def scratch(self, name: str, file: str, old: str, new: str) -> Path:
        """A copy of the part's sources with `old` replaced by `new` once in
        `file`, built into its own directory; returns its plclock build."""
        top = self.tmp / ('planted-' + name)
        src = top / 'src' / 'native'
        for f in COPIED:
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(SRC / f), str(src / f))
        text = (src / file).read_text()
        self.assertEqual(text.count(old), 1, 'the bug no longer applies')
        (src / file).write_text(text.replace(old, new))
        P.make(m11=top / 'm11', source=src)
        return top / 'm11' / 'plclock'

    def short_clock(self, part: Path, std: int = P.STD_PAL,
                    profile: str = 'f121'):
        return P.clock_run(self.tmp / ('run-' + part.parent.parent.name),
                           SHORT, P.DETECT, profile, part=part)

    def test_pal_fraction_45742(self):
        part = self.scratch('pal45742', 'pl_irq.s',
                            'TIC_FRAC_PAL = 45743', 'TIC_FRAC_PAL = 45742')
        r = self.short_clock(part)
        p = P.clock_problems(r, SHORT, P.STD_PAL)
        self.assertTrue(any(re.match(r'VBL 1: tics 0, fraction 45742', x)
                            for x in p), p)

    def test_ntsc_fraction_for_pal(self):
        part = self.scratch('ntscforpal', 'pl_irq.s',
                            'TIC_FRAC_PAL = 45743', 'TIC_FRAC_PAL = 38229')
        r = self.short_clock(part)
        p = P.clock_problems(r, SHORT, P.STD_PAL)
        self.assertTrue(any('VBL 1:' in x for x in p), p)
        rate, _ = P.measured_rate(r, SHORT, 'f121')
        self.assertLess(rate, P.RATE_RANGE[0])

    def test_tic_lost_at_carry(self):
        part = self.scratch('carry', 'pl_irq.s',
                            '        lda CLK_FRAC+1\n        adc CLK_STEP+1',
                            '        lda CLK_FRAC+1\n        clc\n'
                            '        adc CLK_STEP+1')
        r = self.short_clock(part)
        p = P.clock_problems(r, SHORT, P.STD_PAL)
        self.assertTrue(p)
        self.assertTrue(any(x.startswith('VBL 2:') for x in p), p)

    def test_vbl_cause_not_checked(self):
        part = self.scratch('cause', 'pl_irq.s',
                            '        beq @none               ; no VBL',
                            '        nop                     ; no VBL')
        n = 150
        plain = P.clock_run(self.tmp / 'cause-plain', n, P.STD_PAL, 'f121',
                            mode=P.MODE_VBL_BUTTON, idle=False, part=part)
        pressed = P.clock_run(self.tmp / 'cause-pressed', n, P.STD_PAL,
                              'f121', mode=P.MODE_VBL_BUTTON, idle=False,
                              part=part,
                              buttons=P.second_entry_buttons(n))
        p = P.second_entry_problems(plain, pressed)
        self.assertTrue(any('stopped' in x and 'early' in x for x in p), p)

    def test_handler_reads_main_0300(self):
        part = self.scratch('read0300', 'pl_irq.s',
                            'pl_vbody:\n',
                            'pl_vbody:\n        lda $0300\n')
        r = self.short_clock(part)
        self.assertIn('irq-bounds', r.ended)
        self.assertIn('$0300', r.ended)
        self.assertTrue(P.clock_problems(r, SHORT, P.STD_PAL))


if __name__ == '__main__':
    unittest.main()
