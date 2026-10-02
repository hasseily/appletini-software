"""Milestone 11, first half, part s2pal (docs/SCREENS.md 1.3, 1.5.7,
1.5.8, 4.1, 6.3, 7.3; docs/m11-parts/s2pal.md): the palettes, tints,
gamma, SCBs, the finish and the wipe (src/native/s2_pal.s), the nibble
tables, gamma and a picture's palettes (s2_nib.s), the image PALW
(s2_palw.s), against the host model (tools/native/s2palmodel.py), which
is checked against ref816 first (tools/native/s2pal.py).

What runs here (the checkpoint, `python3 tools/native/s2pal.py --all`,
also runs demo3 and the tour and the timing):
  - the model against ref816 on every frame and event of palette.script
    and newgame (the state at I_FinishUpdate's entry, the SCBs and
    palettes after it, the wipe's black step PW, the TINTPALs of the
    levels, the gamma reloads), and on the nibble dumps of the four runs
    (each level load, new picture and menu close);
  - the native frames of palette.script and newgame from both poisoned
    machines, plain and with every SCB and palette byte the frame writes
    poisoned: the SCBs and palettes after s2_finish, the wipe's step, the
    palette state, st_palette and message_new, the strip's clear, the
    publish order of 1.3 on the write log, no stray write;
  - PALW and s2_picpal against the nibble dumps of palette.script (the
    level loads, the gamma changes, the title page);
  - ST_doPaletteStuff's paths the captures miss, the model against ref816
    --call and the native against the model;
  - the sizes: s2_pal 800 B, s2_nib 400 B, PALW's own 1,500 B;
  - the seven planted bugs, each in a scratch copy of the sources.

Needs cc65, build/a2vm/a2vm, the math tables, ref816 with the release
(make -C tools/ref816; python3 tools/ref816/title.py), the release image
and DOOM1.WAD (tools/fetch_upstream.py), part s2cap's cases
(python3 tools/native/s2cap.py --capture) and part s2draw's truth base
(python3 tools/native/s2drawcase.py); skips naming what is missing. The
first run captures the nibble dumps (about 10 s) and the --call truth
(about 5 s) into build/native/m11/s2pal/.

Run by name: python3 tools/testpar.py tests/test_m11_s2pal.py

By default (tests/README.md) the native frames run every second batch of
16 (each image still), the planted bugs the same; DOOM_GS_FULL=1 runs
every batch as before.
"""

import re
import shutil
import unittest
from unittest import mock

import support

ROOT = support.ROOT
BUILD = ROOT / 'build'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))


def missing() -> str:
    from native import s2cap, s2drawcase, s2run, umodel
    from ref816 import make_image, title
    need = []
    if not HAVE_CC65:
        need.append('cc65 on PATH')
    if not s2run.A2VM.exists():
        need.append('build/a2vm/a2vm (make -C tools/a2vm)')
    if not (s2run.TABLES / 'math' / 'squares.bin').exists():
        need.append('the math tables (python3 tools/native/rtables.py)')
    if not (title.MACHINE.exists() and title.MEMORY.exists() and
            title.DISK.exists()):
        need.append('ref816 and its memory image (make -C tools/ref816; '
                    'python3 tools/ref816/title.py)')
    if not (make_image.LINKMAP.exists() and umodel.RELEASE.exists()):
        need.append('the link map and the release image '
                    '(tools/fetch_upstream.py, tools/v816/imgmatch.py)')
    if not all((s2cap.CASES / r / 'index.json').exists()
               for r in ('demo3', 'newgame', 'tour', 'palette')):
        need.append('part s2cap\'s cases (python3 tools/native/s2cap.py '
                    '--capture)')
    if not s2drawcase.BASE.exists():
        need.append('part s2draw\'s base state (python3 tools/native/'
                    's2drawcase.py)')
    return ', '.join(need)


MISSING = missing()
needs_build = unittest.skipIf(MISSING, 'needs ' + MISSING)

RUNS = ('palette', 'newgame')
# by default every EVERY-th batch of 16 frames (tests/README.md); all of
# them with DOOM_GS_FULL=1
EVERY = 1 if support.FULL else 2


class Built:
    done = False


def ensure_built() -> None:
    from native import s2pal as P
    if not Built.done:
        P.make_part()
        Built.done = True


class TestModel(unittest.TestCase):
    """The model's rules on hand-made values (no build needed)."""

    def test_gamma(self):
        from native import s2palmodel as M
        self.assertEqual(M.gamma_color(0x0ABC, 0), 0x0ABC)
        self.assertEqual(M.gamma_color(0xF123, 0), 0x0123)   # bits 12-15
        # row 4: 1 -> 3, 2 -> 5, 3 -> 6 [R i_viigs65.s:182]
        self.assertEqual(M.gamma_color(0x0123, 4), 0x0356)

    def test_nibtab(self):
        from native import s2palmodel as M
        t = M.build_nibtab(bytes(range(256)))
        self.assertEqual(len(t), 1024)
        self.assertEqual((t[0x5A], t[0x15A], t[0x25A], t[0x35A]),
                         (0x50, 0xA0, 0x0A, 0x05))

    def test_st_palette_rules(self):
        from native import s2palmodel as M
        st = M.PalState(bytes(200), bytes(512), 100, 0, 0, 0, 0, 0xFFFF, 0,
                        0)
        m = M.Model(st, bytes(768), bytes(M.TINTPAL_SIZE), 0)
        # damage 40: red (40 + 7) >> 3 = 5, + 1
        self.assertEqual(m.st_do_palette_stuff(40, 0, 0, 0, 0, 0), 6)
        self.assertEqual(m.newpal, 6)
        # in the menu: half (5 >> 1 = 2), + 1
        self.assertEqual(m.st_do_palette_stuff(40, 0, 0, 0, 1, 6), 3)
        # the suit's blink: bit 3 of powers[pw_ironfeet] at 128 or less
        self.assertEqual(m.st_do_palette_stuff(0, 0, 0, 8, 0, 0),
                         M.RADIATIONPAL)
        self.assertEqual(m.st_do_palette_stuff(0, 0, 0, 7, 0, 13), 0)
        # unchanged: no I_SetPalette
        m.newpal = 100
        self.assertEqual(m.st_do_palette_stuff(0, 0, 0, 0, 0, 0), 0)
        self.assertEqual(m.newpal, 100)

    def test_finish_order(self):
        from native import s2palmodel as M
        st = M.PalState(bytes(range(200)), bytes([7]) * 512, 2, 0, 0, 256,
                        1, 5, 0, 0)
        m = M.Model(st, bytes(768), bytes(range(256)) * 21, 0)
        mid = m.finish_update()
        # the black 512, then the SCBs, then the picture's 512
        self.assertEqual([v for _, v in m.stores[:512]], [0] * 512)
        self.assertEqual(mid, 512 + 200)
        self.assertEqual(m.palettecount, 0)
        self.assertEqual(m.curtint, 2)
        self.assertEqual(m.levelcopy, 0)        # a picture: no TINTPAL row

    def test_palst_round_trip(self):
        from native import s2pal as P, s2palmodel as M
        st = M.PalState(bytes(range(200)), bytes(range(256)) * 2, 100, 13,
                        1, 256, 1, 0xFFFF, 11, 10)
        data = P.palst_native(st, 0, 1)
        back, begun, txt = P.palst_decode(data)
        self.assertEqual(back, st)
        self.assertEqual((begun, txt), (0, 1))
        with self.assertRaises(P.PalError):
            P.palst_native(st._replace(palettecount=100))

    def test_include(self):
        # S2PAL's places, PS_TXTINV and the zero page are s2.inc's
        # (requests S2PAL-1 to -3, applied); s2pal.inc defines none of
        # s2.inc's names (ca65 would refuse the second definition)
        from native import s2layout as S, s2pal as P
        values = dict(S.constants('test'))
        values.update(S.zeropage())
        own = dict(P.inc_values())
        self.assertEqual(set(own) & set(values), set())
        self.assertEqual(values['PS_TXTINV'],
                         S.palst_places()['PS_BEGUN'] + 1)
        self.assertEqual(values['S2P_NIB'] & 0xFF, 0)       # page aligned
        for name, at, size in P.S2PAL_PLACES:   # a RAMRD window's reach
            self.assertTrue(0x0200 <= at and at + size <= 0xC000, name)
            self.assertEqual((values[name], values[name + '_SIZE']),
                             (at, size))
        ends = sorted((a, a + z) for _, a, z in P.S2PAL_PLACES)
        for (a0, e0), (a1, _) in zip(ends, ends[1:]):
            self.assertLessEqual(e0, a1)
        self.assertEqual(values['S2P_A'], 0x78)

    def test_layout_check(self):
        """s2layout's check (the phase stores of these sources among
        them) passes."""
        from native import s2layout as S
        S.check()


@needs_build
class TestReference(unittest.TestCase):
    """The model against ref816's captures."""

    def test_frames_and_events(self):
        from native import s2pal as P
        for run in RUNS:
            o = P.model_run(run)
            self.assertEqual(o['problems'], [], run)
            self.assertGreater(o['finishes'], 100, run)
            self.assertGreaterEqual(o['wipes'], 3, run)
            self.assertLessEqual(o['title'], 1, run)    # X3: one at most
        o = P.model_run('palette')
        self.assertEqual(o['reloads'], 8)               # gamma 1-4, 0
        self.assertGreaterEqual(o['tintpals'], 5)

    def test_nibble_dumps(self):
        from native import s2pal as P
        for run in P.RUNS:
            if not (P.NIB_DIR / (run + '.z')).exists():
                P.nib_capture(run)
        total = {'levels': 0, 'pictures': 0, 'closes': 0}
        for run in P.RUNS:
            o = P.nib_model(run)
            self.assertEqual(o['problems'], [], run)
            for k in total:
                total[k] += o[k]
        self.assertGreaterEqual(total['levels'], 16)
        self.assertGreaterEqual(total['pictures'], 12)
        self.assertGreaterEqual(total['closes'], 9)


@needs_build
class TestNative(unittest.TestCase):

    def test_sizes(self):
        ensure_built()
        from native import s2pal as P
        seen = {}
        for name in ('s2pp', 's2pf', 'palw'):
            text = (P.WORK / (name + '.sizes')).read_text()
            for line in text.splitlines():
                m = re.match(r'^(\w+)\s+(\S+)\s+(\d+) of\s+(\d+) B', line)
                if m:
                    seen[(m.group(1), m.group(2))] = (int(m.group(3)),
                                                      int(m.group(4)))
        self.assertLessEqual(seen[('P2DW', 's2_pal')][0], 800)
        self.assertLessEqual(seen[('WIW', 's2_nib')][0], 400)
        self.assertLessEqual(seen[('PALW', 'own')][0], 1500)
        self.assertEqual(seen[('P2DW', 's2_pal')][1], 800)
        self.assertEqual(seen[('PALW', 's2_nib')][1], 400)

    def test_frames(self):
        """Every batch of the runs' frames from both fills, plain and
        poisoned (by default every EVERY-th batch: tests/README.md)."""
        ensure_built()
        from native import s2pal as P
        o = P.native_all(RUNS, jobs=2, every=EVERY)
        self.assertEqual(o['problems'], [])
        self.assertEqual(o['stray'], 0)
        self.assertGreater(o['writes'], 0)
        self.assertGreater(o['by_image'].get('s2pf', 0), 0)  # a picture
        n = sum(c['finishes'] for c in o['counts'].values())
        batches, _ = P.native_cases(RUNS)
        self.assertEqual(sum(len(b) for _, b in batches), n)
        self.assertEqual(o['cases'], 4 * sum(
            len(b) for k, (_, b) in enumerate(batches) if k % EVERY == 0))
        self.assertLessEqual(o['stack'], 64)

    def test_palw(self):
        ensure_built()
        from native import s2pal as P
        o = P.palw_all(['palette'], jobs=2)
        self.assertEqual(o['problems'], [])
        self.assertEqual(set(o['kinds']), {'level', 'gamma', 'picture'})

    def test_st_palette_paths(self):
        ensure_built()
        from native import s2pal as P
        o = P.synth_native(jobs=2)
        self.assertEqual(o['problems'], [])
        for path in ('red', 'red, menu', 'red, capped', 'berserk', 'gold',
                     'gold, capped', 'suit', 'suit, blink on',
                     'suit, blink off', 'none'):
            self.assertGreater(o['paths'].get(path, 0), 0, path)


@needs_build
class TestPlanted(unittest.TestCase):
    """Each planted bug, in a scratch copy of the sources, is caught."""

    def test_planted(self):
        ensure_built()
        from native import s2pal as P
        native_all = P.native_all
        for pl in P.PLANTS:
            with self.subTest(pl.name), mock.patch.object(
                    P, 'native_all', lambda *a, **k: native_all(
                        *a, every=EVERY, **k)):
                o = P.plant_run(pl, jobs=2)
                self.assertTrue(o['caught'], pl.name)
                if pl.name == 'the black palettes after the first band':
                    # both snapshots pass: the order alone catches it
                    self.assertTrue(o['only_order'], o['first'])


if __name__ == '__main__':
    unittest.main()
