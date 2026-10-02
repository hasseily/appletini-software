"""Milestone 11, first half, part fxdisk (docs/SCREENS.md 3, 7.3;
tools/sound/README.md "Effects (S4)", "The test disk SOUNDS.hdv";
docs/m11-parts/fxdisk.md): the effects' test disk SOUNDS.hdv, its
program src/sound/sounds.s and its checks tools/sound/fxdisk.py.

Without build/: the names' include, the screen's checksum, the screen's
rows, the key model's steps (the four play keys, C's two channels, T on
a tuned and an automatic effect, the repeat's timing, V and M with and
without native mode, the quit), the step marker's parser, the model's
bank switch.

With cc65, make, build/a2vm/a2vm, the WAD, appletini-one's ProDOS, S2's
player (make -C src/sound) and SFX.1 (part fxconv):

- the disk built (into a temporary directory) with no warning; the
  program's places against s2layout.py's;
- the checkpoint (fxdisk.check_all): every effect by key on the centre
  and left voices and on the right one, at the three distances, the voice
  the screen names after the first plays (RETURN: C CENTRE); the ten
  tuned effects
  tuned and automatic, the screen's effect line and list after each T;
  every effect over D_E1M1, V and M; NTSC with a volume change, the
  repeat, S and ESC; q; --phasor-mb-only with no AY write past the
  probe's and snd_init's: every interrupt's AY writes equal to the models'
  (S2's music, fxplay.py's effects) under the IRQ bounds, the steps of the
  program equal to the key model's, each in its visit, the publish order,
  the quit as MUSIC.SYSTEM's;
- the planted bugs, each in a scratch copy of sounds.s built apart.

Run by name: python3 tools/testpar.py tests/test_m11_fxdisk.py
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (sys.path)

from sound import fxconv  # noqa: E402
from sound import fxdisk as D  # noqa: E402
from sound import fxplay  # noqa: E402


def ready() -> bool:
    return D.have_tools() and D.A2VM.exists() and \
        (D.FXCONV_OUT / 'SFX.1').exists() and \
        (D.FXCONV_OUT / 'SFXAUTO.1').exists()


READY = ready()
WHY = ('needs cc65 and make on PATH, build/a2vm/a2vm (make -C tools/a2vm), '
       'the WAD (tools/fetch_upstream.py), appletini-one\'s ProDOS_2_4_3.po, '
       'S2\'s player (make -C src/sound) and SFX.1 (make -f '
       'src/native/m11/fxconv.mk)')
needs_build = unittest.skipUnless(READY, WHY)


class Pure(unittest.TestCase):

    def test_names(self):
        text = D.names_inc()
        rows = [ln for ln in text.splitlines() if ln.strip().startswith('.byte')]
        self.assertEqual(len(rows), 52)
        for row, name in zip(rows, fxconv.NAMES):
            self.assertEqual(row.split('"')[1], name.ljust(6))

    def test_sum(self):
        self.assertEqual(D.script_sum(b''), 0)
        self.assertEqual(D.script_sum(bytes([1, 2])), 4)        # 1, 2 + 2
        self.assertEqual(D.script_sum(bytes([0x80] + [0] * 8)), 0x8000)
        self.assertEqual(D.script_sum(bytes([0x80] + [0] * 9)), 0x0001)
        self.assertEqual(D.script_sum(bytes([0xFF, 0xFF])), 0x02FD)

    def test_rows(self):
        tuned = [n in fxconv.TUNED for n in fxconv.NAMES]
        ver = [0 if t else 1 for t in tuned]
        rows = D.list_rows(0, tuned, ver)
        self.assertEqual(len(rows), 18)
        self.assertEqual(rows[0][:23], '> PISTOL T     PLPAIN T')
        self.assertTrue(all(len(r) <= 40 for r in rows))
        ver[1] = 1
        self.assertEqual(D.list_rows(1, tuned, ver)[1][:10], '> SHOTGN A')
        self.assertEqual(D.effect_row(1, 'AUTO', 0x3A7C, 2, 'B RIGHT'),
                         'SHOTGN AUTO  SUM 3A7C FAR  B RIGHT')
        self.assertEqual(D.machine_row(True, True, True, True),
                         'NTSC //E PHASOR NATIVE  CHIP 3 MUSIC REP')
        self.assertEqual(D.machine_row(False, False, True, True),
                         'PAL //E  NO EFFECTS: NO NATIVE MODE')
        for r in D.KEY_ROWS + [D.TITLE]:
            self.assertLessEqual(len(r), 40)

    def model(self, events, visits=400, native=True, ntsc=False):
        tuned = [n in fxconv.TUNED for n in fxconv.NAMES]
        return D.model_steps(events, visits, tuned, native, ntsc)

    def test_play_keys(self):
        ui = self.model([(3, 'return'), (5, 'down'), (6, '3'), (7, 'B'),
                         (9, 'C'), (11, '2')])
        S = D.Step
        self.assertEqual(ui.steps, [
            S(3, D.STOPALL), S(3, D.START, (0, 1, 127, 128)),
            S(6, D.VOLUME_, (0, 6)),
            S(7, D.STOPALL), S(7, D.START, (0, 2, 6, 200)),
            S(9, D.STOPALL), S(9, D.START, (0, 2, 6, 64)),
            S(9, D.START, (1, 2, 6, 64)), S(9, D.SERVICE), S(9, D.STOP, (0,)),
            S(9, D.SERVICE),
            S(11, D.VOLUME_, (1, 63))])

    def test_tuned_and_columns(self):
        ui = self.model([(3, 'T'), (4, 'right'), (5, 'T'), (6, 'left'),
                         (7, 'left'), (8, 'up'), (9, 'T')])
        # PISTOL and PLPAIN (a column to the right) tuned; up from
        # PISTOL wraps to GETPOW, not tuned: no step
        self.assertEqual(ui.steps, [D.Step(3, D.TOGGLE, (1, 1)),
                                    D.Step(5, D.TOGGLE, (19, 1))])
        self.assertEqual(ui.cur, 51)

    def test_repeat(self):
        ui = self.model([(3, 'A'), (4, 'R'), (200, 'S')], visits=260)
        plays = [v for v, _, _ in ui.plays]
        self.assertEqual(plays, [3, 54, 104, 154])
        self.assertEqual(ui.steps[-1], D.Step(200, D.STOPALL))
        ui = self.model([(3, 'A'), (4, 'R')], visits=200, ntsc=True)
        self.assertEqual([v for v, _, _ in ui.plays], [3, 64, 124, 184])

    def test_music_and_video(self):
        ui = self.model([(3, 'M'), (5, 'V'), (7, 'M'), (9, 'V'), (11, 'q'),
                         (13, 'A')])
        self.assertEqual([(s.visit, s.kind, s.args) for s in ui.steps], [
            (3, D.SONG, (False,)), (5, D.STD, (True,)), (5, D.SONG, (True,)),
            (7, D.SONGSTOP, ()), (9, D.STD, (False,)), (11, D.QUIT, ())])
        ui = self.model([(3, 'M'), (5, 'V')], native=False)
        self.assertEqual([s.kind for s in ui.steps], [D.STD])

    def test_marks(self):
        W = D.Write

        class R:
            labels = {'sds_mark': 0x30}
            writes = [W(10, 0, 0x30, 0, 7), W(12, 0, 0x30, 7, 3),
                      W(15, 0, 0x30, 3, 0), W(20, 0, 0x31, 0, 5),
                      W(30, 0, 0x30, 0, 0x80), W(35, 0, 0x30, 0x80, 0x81),
                      W(40, 0, 0x30, 0x81, 0), W(50, 0, 0x30, 0, 0xFF)]
        self.assertEqual(D.mark_events(R()), [
            D.Event(7, 10, 12), D.Event(3, 12, 15), D.Event(0x80, 30, 35),
            D.Event(0x81, 35, 40), D.Event(0xFF, 50, 1 << 62)])

    def test_bank_switch(self):
        sfx = bytearray(0x200)
        auto = bytearray(0x300)
        for s in range(1, 53):
            sfx[4 * (s - 1):4 * s] = (0x0350).to_bytes(2, 'little') + \
                (4).to_bytes(2, 'little')
            auto[4 * (s - 1):4 * s] = (0x0400).to_bytes(2, 'little') + \
                (8).to_bytes(2, 'little')
        b = D.MutBank(bytes(sfx), bytes(auto))
        self.assertEqual(b.entry(3), (0x0350, 4))
        b.switch(3, 1)
        self.assertEqual(b.entry(3), (0x0400 + D.AUTO_OFF, 8))
        self.assertEqual(b.entry(4), (0x0350, 4))
        b.switch(3, 0)
        self.assertEqual(b.entry(3), (0x0350, 4))
        self.assertIsInstance(b, fxplay.Bank)


@needs_build
class Disk(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='tmp-fxdisk-test-',
                                        dir=str(D.BUILD)))
        cls.disk = D.build(cls.tmp / 'SOUNDS.hdv')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_places_and_sizes(self):
        self.assertEqual(D.place_problems(self.disk.program), [])
        z = D.sizes(self.disk.program)
        self.assertLessEqual(z['main_end'], 0x4000)
        self.assertLessEqual(z['FXCODE'], 0xF900 - 0xF505)
        names = [f[0] for f in self.disk.files]
        self.assertEqual(names, ['SOUNDS.SYSTEM', 'PRODOS', 'SFX.1',
                                 'SFXAUTO.1', 'E1M1.AY', 'PROFILE.TXT'])

    def test_checkpoint(self):
        lines = []
        problems = D.check_all(self.disk, 2, out=lines.append)
        self.assertEqual(problems, [], '\n'.join(lines))
        self.assertEqual(len(lines), 1 + len(D.CHECKS))

    def test_planted(self):
        lines = []
        missed = D.planted(self.disk, 2, out=lines.append)
        self.assertEqual(missed, [], '\n'.join(lines))
        self.assertEqual(len(lines), sum(len(b[3]) for b in D.PLANTED),
                         '\n'.join(lines))


if __name__ == '__main__':
    unittest.main()
