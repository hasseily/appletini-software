"""Part sight of milestone 10 (wave 1; docs/GAME.md 2.4 row sight, 3.5;
docs/game-parts/sight.md): P_CheckSight, zSetup, sightSlope,
interceptFrac and opening in routine mode against ref816, the synthetic
cases, the random checks of the arithmetic helpers (and the decision on
the side test's log fast path), and the planted bugs.

The checkpoint here runs a sample of the captured cases (every
SAMPLE_SIGHT-th call of P_CheckSight, every SAMPLE_OTHER-th of the other
entries) and every synthetic case; `python3 tools/native/gparts/sight.py
--check` runs them all (build/native/game/sight/report.json). Each test
skips, naming the command, when build/ lacks what it needs: a2vm, ref816,
the shared outputs, the level bases, the part's path logs and cases. It
writes only under build/native/game/sight/ and in temporary directories
it deletes.
"""

import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / 'tools' / 'native' / 'gparts' / 'sight.py'
SAMPLE_SIGHT = 20
SAMPLE_OTHER = 15
RANDOM_N = 100_000


def tool():
    """tools/native/gparts/sight.py as the module `sight` (its name in the
    worker processes it starts, which import it again)."""
    for p in (ROOT / 'tools', TOOL.parent):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    return importlib.import_module('sight')


def need(t) -> None:
    """Skip unless build/ has the machines, the shared outputs, the path
    logs and the cases."""
    why = t.missing()
    if why:
        raise unittest.SkipTest(why)
    if any(t.load_paths(r) is None for r in t.GC.RUNS):
        raise unittest.SkipTest('no path logs (python3 '
                                'tools/native/gparts/sight.py --paths)')
    if len(t.case_files(t.CHECKSIGHT)) < t.SIGHT_N:
        raise unittest.SkipTest('the cases are missing (python3 '
                                'tools/native/gparts/sight.py --capture)')
    if not t.synthetic_files():
        raise unittest.SkipTest('no synthetic cases (python3 '
                                'tools/native/gparts/sight.py --synthetic)')


T = None


def setUpModule():
    global T
    T = tool()
    need(T)
    T.build()


class Selection(unittest.TestCase):
    """GAME.md 2.4's minimums: 2,000 calls of P_CheckSight by path, 300
    (or all) of each other entry with every path taken."""

    def test_sight_paths(self):
        sel = T.selection(T.CHECKSIGHT)
        self.assertEqual(len(sel), T.SIGHT_N)
        for c in ('pair', 'reject', 'samess', 'one', 'two', 'seen'):
            self.assertTrue(any(x[3] == c for x in sel), c)
        self.assertEqual(len(T.case_files(T.CHECKSIGHT)), T.SIGHT_N)

    def test_hint_hits_captured(self):
        cls = [T.class_of_case(T.GC.load_case(p))
               for p in T.case_files(T.CHECKSIGHT, 10)]
        self.assertIn('hint', cls)

    def test_other_entries(self):
        for key in T.ENTRIES[1:]:
            calls = T.calls_of(key)
            sel = T.selection(key)
            self.assertGreaterEqual(len(sel), min(len(calls), T.MINIMUM))
            self.assertEqual({c[3] for c in sel}, {c[3] for c in calls})
            self.assertEqual(len(T.case_files(key)), len(sel), key)


class Checkpoint(unittest.TestCase):
    """The sample from both fills ($A5 under f121, $5A under fastpath):
    canonical state, declared outputs, the hit log, GT_HINT, no stray
    write; each P_CheckSight case again with no hint, the same answer."""

    @classmethod
    def setUpClass(cls):
        work = []
        for key in T.ENTRIES:
            n = SAMPLE_SIGHT if key == T.CHECKSIGHT else SAMPLE_OTHER
            work += [(str(p), key, str(T.OUT), False)
                     for p in T.case_files(key, n)]
        work += [(str(p), T.synthetic_key(p), str(T.OUT), True)
                 for p in T.synthetic_files()]
        cls.results = T.run_cases(work, T.JOBS)
        cls.summary = T.summarize(cls.results)

    def test_every_entry_equal(self):
        for key in T.ENTRIES:
            s = self.summary[key]
            self.assertGreater(s['runs'], 0, key)
            self.assertEqual(s['failed'], 0, (key, s['first_failures']))
            self.assertEqual(s['stray_writes'], 0, key)

    def test_hint_free_answers(self):
        s = self.summary[T.CHECKSIGHT]
        self.assertGreater(s['hintless_runs'], 0)
        self.assertEqual(s['hintless_failed'], 0, s['first_failures'])

    def test_paths_and_synthetic(self):
        s = self.summary[T.CHECKSIGHT]
        for c in T.SIGHT_PATHS:
            self.assertIn(c, s['paths'], c)
        notes = {r.get('note') for r in self.results}
        for n in ('on-node (synthetic)', 'stale1 (synthetic)',
                  'stale2 (synthetic)', 'wrap (synthetic)',
                  'frac den0 (synthetic)', 'frac big (synthetic)'):
            self.assertIn(n, notes)

    def test_timing_and_stack(self):
        for key in T.ENTRIES:
            s = self.summary[key]
            for prof in ('f121', 'fastpath'):
                self.assertGreater(s[prof]['cycles_median'], 0, (key, prof))
            self.assertIsNotNone(s['lowest_s'])


class Sizes(unittest.TestCase):
    def test_budget(self):
        s = T.sizes()
        self.assertLessEqual(s['release'], T.BUDGET)


class RandomChecks(unittest.TestCase):
    """smul48 and the side test on 100,000 inputs each (the edges
    included), the magnitude on every 16-bit value, upstream's helper on
    ref816 (mathref batch) against the native one (sg_bulk on a2vm)."""

    @classmethod
    def setUpClass(cls):
        cls.rep = T.random_checks(RANDOM_N)

    def test_half(self):
        r = self.rep['half']
        self.assertEqual(r['inputs'], 65535)
        self.assertEqual(r['different'], 0, r['first'])

    def test_smul48(self):
        r = self.rep['smul48']
        self.assertGreaterEqual(r['inputs'], RANDOM_N)
        self.assertEqual(r['different'], 0, r['first'])
        self.assertEqual(r['upstream_is_the_product'], r['inputs'])

    def test_side_exact(self):
        """The native side test is the exact signed product compare, and
        it gives upstream's answer (its log fast path, then the products)
        on every input, those with an operand of -32768 included (LOGTAB's
        entry 0 is log 32768): the decision on LOGTAB,
        docs/game-parts/sight.md."""
        r = self.rep['side']
        self.assertGreaterEqual(r['inputs'], RANDOM_N)
        self.assertGreater(r['with_32768'], 0)
        self.assertEqual(r['native_not_exact'], 0)
        self.assertEqual(r['different'], 0, r['first'])


# The planted bugs (GAME.md 2.4 row sight), each in a scratch copy of the
# part's sources, each caught by its named check.
PLANTS = {
    # CS_PREV not kept: the pair stays the old one (the canonical
    # CS_PREV1/2; the next call of the pair would walk and raise
    # validcount)
    'cs-prev-not-kept': ('walk', [('sight.s', """\
@new:   ldx #3                  ; the pair is kept (p_sight65.s:148-153)
:       lda SG_T1,x
        sta CS_PREV1,x
        dex
        bpl :-""", """\
@new:   ldx #3                  ; (planted: the pair is not kept)
:       lda SG_T1,x
        nop
        nop
        nop
        dex
        bpl :-""")]),
    # $FFFE matching a slot: a stale CS_PREV1 taken for any t1 (the hit
    # log: a hit where upstream walks)
    'stale-matches': ('stale', [('sight.s', """\
@pair:  lda SG_T1,x
        cmp CS_PREV1,x
        bne @new
        dex
        bpl @pair""", """\
@pair:  lda SG_T1,x
        cmp CS_PREV1,x
        beq @peq
        lda CS_PREV1+1          ; (planted: a stale handle matches)
        cmp #>STALE
        bne @new
@peq:   dex
        bpl @pair""")]),
    # the far child walked first (the lines' stamps of a blocked walk)
    'far-child-first': ('blocked', [('sight.s', """\
        lda SG_S1               ; crossed: the other child waits
        eor #1
        jsr child
        phx
        pha
@same:  lda SG_S1               ; the start's child
        jsr child
        bra node_loop""", """\
        lda SG_S1               ; (planted: the start's child waits)
        jsr child
        phx
        pha
        lda SG_S1
        eor #1
        jsr child
        bra node_loop
@same:  lda SG_S1
        jsr child
        bra node_loop""")]),
    # the side test on the 32-bit differences' sign, not the 16-bit whole
    # parts with their wrap (the synthetic far points)
    'side-no-wrap': ('wrap', [('sight.s', """\
        lda SG+7,x
        sbc (GT_0),y
        sta SG_QA+1""", """\
        lda SG+7,x
        sbc (GT_0),y
        bvc :+                  ; (planted: no 16-bit wrap)
        eor #$80
:       sta SG_QA+1"""), ('sight.s', """\
        lda SG+3,x
        sbc (GT_0),y
        sta SG_QC+1""", """\
        lda SG+3,x
        sbc (GT_0),y
        bvc :+                  ; (planted: no 16-bit wrap)
        eor #$80
:       sta SG_QC+1""")]),
    # sightSlope with the 32-bit distance where upstream takes its whole
    # part (the sightSlope cases' result)
    'slope-32-bit': ('slope', [('sfrac.s', """\
@go:    sec                     ; (height - sightzstart) >> 16
        lda GA_0
        sbc SG_ZS
        lda GA_1
        sbc SG_ZS+1
        lda GA_2
        sbc SG_ZS+2
        sta SG_SLW
        lda GA_3
        sbc SG_ZS+3
        sta SG_SLW+1
        lda SG_FRAC             ; FixedReciprocalSmall(frac)
        sta M_A
        lda SG_FRAC+1
        sta M_A+1
        jsr recipsmall
        ldx #3
:       lda M_R,x
        sta M_B,x
        dex
        bpl :-
        lda SG_SLW              ; the whole part, sign extended, times it
        sta M_A
        lda SG_SLW+1
        sta M_A+1
        and #$80
        beq :+
        lda #$FF
:       sta M_A+2
        sta M_A+3
        jmp mul32""", """\
@go:    sec                     ; (planted: the 32-bit distance)
        lda GA_0
        sbc SG_ZS
        sta SG_SLW
        lda GA_1
        sbc SG_ZS+1
        sta SG_SLW+1
        lda GA_2
        sbc SG_ZS+2
        sta SG_SLW+2
        lda GA_3
        sbc SG_ZS+3
        sta SG_SLW+3
        lda SG_FRAC
        sta M_A
        lda SG_FRAC+1
        sta M_A+1
        jsr recipsmall
        ldx #3
:       lda M_R,x
        sta M_B,x
        lda SG_SLW,x
        sta M_A,x
        dex
        bpl :-
        jmp mul32""")]),
    # REJECT's bit order reversed (the REJECT cases)
    'reject-bit-order': ('reject', [('sight.s',
                                     'bitTab: .byte 1, 2, 4, 8, 16, 32, 64, '
                                     '128',
                                     'bitTab: .byte 128, 64, 32, 16, 8, 4, '
                                     '2, 1')]),
}
PLANT_CASES = 10


def plant_cases(kind: str):
    """(path, entry, synthetic) of PLANT_CASES cases of the plant's kind,
    each one the tree's image passes (the checkpoint's sample)."""
    if kind == 'slope':
        return [(str(p), 'p_sight65.s:sightSlope', False)
                for p in T.case_files('p_sight65.s:sightSlope', 30)]
    if kind in ('stale', 'wrap'):
        names = {'stale': 'stale', 'wrap': 'wrap'}[kind]
        return [(str(p), T.CHECKSIGHT, True) for p in T.synthetic_files()
                if p.name.startswith(names)]
    want = {'walk': ('seen', 'one', 'two', 'hint'),
            'blocked': ('one', 'two'), 'reject': ('reject',)}[kind]
    out = []
    for p in T.case_files(T.CHECKSIGHT, 1 if kind == 'blocked' else 7):
        if T.class_of_case(T.GC.load_case(p)) in want:
            out.append((str(p), T.CHECKSIGHT, False))
        if len(out) >= PLANT_CASES:
            break
    return out


class PlantedBugs(unittest.TestCase):
    def check(self, name):
        kind, bugs = PLANTS[name]
        cases = plant_cases(kind)
        self.assertGreater(len(cases), 0)
        good = T.run_cases([(p, k, str(T.OUT), s, True)
                            for p, k, s in cases], T.JOBS)
        self.assertTrue(all(r.get('ok') for r in good),
                        [r.get('diff') for r in good if not r.get('ok')])
        r = T.plant_run(bugs, cases)
        self.assertGreater(r['failed'], 0, '%s not caught' % name)

    def test_cs_prev_not_kept(self):
        self.check('cs-prev-not-kept')

    def test_stale_matches(self):
        self.check('stale-matches')

    def test_far_child_first(self):
        self.check('far-child-first')

    def test_side_no_wrap(self):
        self.check('side-no-wrap')

    def test_slope_32_bit(self):
        self.check('slope-32-bit')

    def test_reject_bit_order(self):
        self.check('reject-bit-order')


if __name__ == '__main__':
    unittest.main()
