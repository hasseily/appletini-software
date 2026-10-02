"""Milestone 11, first half, part plinput (docs/SCREENS.md 1.5.3, 2.1, 2.4,
4.2, 6.5, 7.3): the //e's input, the shared object pl_poll
(src/native/pl_input.s), the key table's routines (pl_keys.s), the key
table and names (tools/native/plkeys.py), the host model and its
sequences (tools/native/plmodel.py), the a2vm runs (tools/native/
plinput.py).

Without build/: the key table's rules, pl_keys.s's defaults equal to
plkeys.DEFAULTS, the generated include, the model's rules on hand-written
cases (the design's, not the model's own arithmetic), the sequences' count
and coverage.

With cc65, build/a2vm/a2vm, the math tables (python3 tools/native/
rtables.py) and S2's player (make -C src/sound):

- the build with no warning; pl_input.o within 600 B (SCREENS.md 4.1);
- SCREENS.md 6.5's input row: every sequence (at least 40: taps, holds,
  the //e's auto-repeat, two keys overlapping, a tap between polls, the
  Apple keys, the mouse moving, re-centring, both buttons, the menu's
  arrow repeat, a rebinding, lower-case keys, a nearly full queue
  deferring a key) polled at 6, 10 and 35 a second (f121, --cost-timed)
  and at 35 on fastpath: after every poll the input block $03B3-$03ED and
  the key table equal plmodel.py's, the poll at its tic; pl_action's
  answers; the write log: the poll writes only the input block, its zero
  page and the mouse's X; the interrupt bounds;
- the planted bugs, each in a scratch copy of the sources: the
  auto-repeat posting a key down; the held key not going up when another
  comes; the tap's up in the same poll; the mouse's sequence byte not
  re-read; the counts not shared by two keys of one Doom key; a
  lower-case code not folded (typing p fires mouse 2); a full queue
  dropping a key instead of deferring it; and a byte written below the
  block (the write log's check).

Run by name: python3 tools/testpar.py tests/test_m11_plinput.py
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import support

from native import plinput as P  # noqa: E402
from native import plkeys as K  # noqa: E402
from native import plmodel as M  # noqa: E402
from native import s2layout as S  # noqa: E402

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
READY = HAVE_CC65 and P.have_prerequisites()
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), the math '
       'tables (python3 tools/native/rtables.py) and S2\'s player (make -C '
       'src/sound)')
needs_build = unittest.skipUnless(READY, WHY)

UP, FIRE, USE, STRAFE = K.KEY['UP'], K.KEY['FIRE'], K.KEY['USE'], \
    K.KEY['STRAFE']
DOWN_, UP_ = M.EV_KEYDOWN, M.EV_KEYUP


def model_events(polls, rate=35):
    """The events each poll queued (the consumer drains every poll)."""
    seq = M.sq('case', *polls)
    return M.run(seq, rate).events[1:]


class KeyTable(unittest.TestCase):

    def test_rules(self):
        self.assertEqual(K.problems(), [])
        self.assertEqual(len(K.table()), 128)
        self.assertEqual(len(K.names()), 128)
        self.assertTrue(all(len(n) <= 7 for n in K.names()))

    def test_design_defaults(self):
        # SCREENS.md 2.4's list
        keys = K.doom_keys()
        for code, k in ((K.UP, 'UP'), (K.DOWN, 'DOWN'), (K.LEFT, 'LEFT'),
                        (K.RIGHT, 'RIGHT'), (ord('W'), 'UP'),
                        (ord('S'), 'DOWN'), (ord('A'), 'STRAFELEFT'),
                        (ord('D'), 'STRAFERIGHT'), (ord(','), 'STRAFELEFT'),
                        (ord('.'), 'STRAFERIGHT'), (ord('E'), 'USE'),
                        (K.SPACE, 'USE'), (K.RETURN, 'USE'),
                        (K.ESC, 'ESCAPE'), (K.TAB, 'MAP'),
                        (ord('-'), 'ZOOMOUT'), (ord('='), 'ZOOMIN'),
                        (K.OAPPLE, 'FIRE'), (K.SAPPLE, 'USE'),
                        (K.MOUSE1, 'FIRE'), (K.MOUSE2, 'STRAFE')):
            self.assertEqual(keys[code], K.KEY[k], '$%02X' % code)
        for i in range(7):
            self.assertEqual(keys[ord('1') + i], K.KEY['WEAPON1'] + i)
        self.assertEqual(sum(k != K.NOKEY for k in keys), 28)

    def test_characters_as_upstream(self):
        # letters lower case, digits, the menu keys; nothing else
        tb = K.table()
        self.assertEqual(tb[ord('Y')][1], ord('y'))
        self.assertEqual(tb[ord('7')][1], ord('7'))
        self.assertEqual([tb[c][1] for c in (K.UP, K.DOWN, K.LEFT, K.RIGHT,
                                             K.RETURN, K.DELETE)],
                         [0x80, 0x81, 0x82, 0x83, 0x84, 0x85])
        self.assertEqual(tb[K.ESC][1], 0)
        self.assertEqual(tb[K.SPACE][1], 0)
        self.assertEqual(K.fold(ord('p')), ord('P'))

    def test_s2state_pokes_this_table(self):
        # s2state.apple2e_keys(), what the reference's key setup is poked
        # with (6.2), is this table since request PLINPUT-6 (wave 5)
        from native import s2state
        names, table = s2state.apple2e_keys()
        self.assertEqual(names, K.names())
        self.assertEqual(table, K.table())
        self.assertEqual([k for k, _ in table], K.doom_keys())

    def test_defaults_in_the_source(self):
        self.assertEqual(P.model_problems(), [])

    def test_include(self):
        text = K.inc_text()
        self.assertIn('.macro plk_names', text)
        self.assertEqual(text.count('   ; $'), 128)
        self.assertIn('PLK_MOUSE2 ', text)


class Model(unittest.TestCase):
    """The design's rules (SCREENS.md 2.4) on hand-written cases."""

    def test_tap(self):
        ev = model_events(M.steps([M.key('W')], []))
        self.assertEqual(ev, [[(DOWN_, UP), (DOWN_, ord('w'))],
                              [(UP_, UP)]])

    def test_auto_repeat_ignored(self):
        ev = model_events(M.steps([M.hold('W')], [M.hold('W')],
                                  [M.hold('W')], [M.REL]))
        self.assertEqual(ev, [[(DOWN_, UP), (DOWN_, ord('w'))], [], [],
                              [(UP_, UP)]])

    def test_held_key_goes_up_when_another_comes(self):
        ev = model_events(M.steps([M.hold('W')], [M.hold('E')]))
        self.assertEqual(ev[1], [(DOWN_, UP), (UP_, UP), (DOWN_, USE),
                                 (DOWN_, ord('e'))][1:])

    def test_counts_shared(self):
        ev = model_events(M.steps([('oa', 1)], [('buttons', 1, 0)],
                                  [('oa', 0)], [('buttons', 0, 0)]))
        self.assertEqual(ev, [[(DOWN_, FIRE)], [], [], [(UP_, FIRE)]])

    def test_p_is_not_mouse_2(self):
        ev = model_events(M.steps([M.key('p')], []))
        self.assertEqual(ev, [[(DOWN_, ord('p'))], []])
        self.assertNotIn((DOWN_, STRAFE), ev[0])

    def test_menu_repeat(self):
        ev = model_events(M.steps([M.hold(K.DOWN)], menu=1) +
                          M.quiet(20, menu=1), rate=35)
        reps = [k for k, e in enumerate(ev) if (DOWN_, 0x81) in e]
        # the press at poll 0, then 11 tics later, then every 4
        self.assertEqual(reps, [0, 11, 15, 19])

    def test_deferral_keeps_the_key(self):
        # W: 2 events, D: 3, A: 3 (24 bytes queued: fewer than 7 free), so
        # the polls of S and the next defer; the drain after the second,
        # then S comes
        polls = M.steps([M.key('W')], [M.key('D')], [M.key('A')],
                        [M.key('S')], flags=0) + [M.Poll(), M.Poll()]
        r = M.run(M.sq('defer', *polls), 35)
        st = M.Input()
        st.mem = bytearray(r.blocks[-2])
        self.assertEqual(st.get('PL_DEFER'), 2)
        self.assertEqual(st.get('PL_HELD'), ord('A'))
        self.assertEqual(len(r.events[-2]), 8)
        # (the Doom keys from 22 down to 0, recount's order)
        self.assertEqual(r.events[-1], [(DOWN_, K.KEY['DOWN']),
                                        (UP_, K.KEY['STRAFELEFT']),
                                        (DOWN_, ord('s'))])

    def test_sequences(self):
        seqs = M.sequences()
        self.assertGreaterEqual(len(seqs), 40)
        names = ' '.join(s.name for s in seqs)
        for what in ('tap', 'auto-repeat', 'overlapping', 'between polls',
                     'Open Apple', 'mouse moving', 're-centring',
                     'both buttons', 'arrow repeat', 'rebinding',
                     'lower-case', 'nearly full queue defers'):
            self.assertIn(what, names)
        self.assertEqual(S.INPUT_END - S.INPUT_LO, M.SIZE)


@needs_build
class Native(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        P.make()

    def test_sizes(self):
        z = P.sizes()
        self.assertLessEqual(z['pl_input'], P.BUDGET_POLL)
        self.assertGreater(z['pl_input'], 0)
        self.assertGreater(z['pl_keys'], 0)

    def test_layout_check(self):
        # (the phase scan reads pl_input.s, pl_keys.s and pl_it.s: only
        # the platform's sources may write phase 31)
        self.assertEqual(S.problems_of(), [])

    def test_checkpoint(self):
        res = P.check_all(jobs=2)
        self.assertEqual(res['problems'], [])
        self.assertGreaterEqual(res['sequences'], 40)
        self.assertEqual(res['runs'], 4 * res['sequences'])
        self.assertEqual(res['polls'], 4 * sum(len(s.polls)
                                               for s in M.sequences()))
        for prof in P.PROFILES:
            self.assertGreater(res['timing_ms'][prof]['n'], 0)
        self.assertLessEqual(res['stack'], S.STACK_2D)


@needs_build
class Planted(unittest.TestCase):

    def test_each_caught(self):
        res = P.planted(jobs=2)
        self.assertEqual(len(res), len(P.PLANTED))
        for r in res:
            self.assertGreater(r['problems'], 0, r['bug'])

    def test_scratch_copy_only(self):
        d = Path(tempfile.mkdtemp(prefix='tmp-m11-plinput-t-',
                                  dir=str(support.BUILD)))
        try:
            what, file, old, new = P.PLANTED[0]
            src = P.plant(d / 'p', file, old, new)
            self.assertNotEqual((src / file).read_text(),
                                (P.SOURCE / file).read_text())
            self.assertIn(old, (P.SOURCE / file).read_text())
        finally:
            shutil.rmtree(str(d), ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
