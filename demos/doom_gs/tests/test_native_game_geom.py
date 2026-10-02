"""Part geom of milestone 10 (docs/GAME.md 2.4 row geom, 2.5, 3.5): the
side tests, the openings, the point's sector, the block range and the
block iterators, checked against ref816 in routine mode
(tools/native/gparts/geom_check.py).

The checkpoint (each captured call of every entry and every synthetic
case, from both poisoned machines under f121 and fastpath; the iterators
with the recording callback on every captured call's block; 100,000
random point-line and box-line pairs a map and 100,000 posMul inputs
against upstream's routines) and the planted bugs, each made in a scratch
copy of the part's sources and caught by its named check. Skips with the
command to run when build/ lacks what it needs: the shared outputs, the
survey, a2vm, ref816, mathref, the level bases, or the part's own cases
(python3 tools/native/gparts/geom_check.py --select --capture --synth).
Writes only under build/native/game/geom/ and temporary build/tmp-geom-*
directories, deleted after each run.

GEOM_JOBS (default 2) sets the processes the runs use.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))
sys.path.insert(0, str(ROOT / 'tools'))

try:
    import geom_check as M
    IMPORT_ERROR = None
except Exception as error:          # (an import that needs build/)
    M = None
    IMPORT_ERROR = error

JOBS = int(os.environ.get('GEOM_JOBS', '2'))
# every case from both poisoned machines, one under each cost profile (the
# tool's --run makes the four runs a case for report.json)
COMBOS = [(0xA5, 'f121'), (0x5A, 'fastpath')]
CAPTURE_CMD = ('python3 tools/native/gparts/geom_check.py --select '
               '--capture --synth')

# The planted bugs (docs/GAME.md 2.4 row geom), each (file, old, new) in
# src/native/: the scratch copy is built with it and the named check must
# fail
PLANTS = {
    # an on-the-line point given the other side: dx 0, x exactly
    # v1.x << 16 counted as above the axis (dy < 0: side 1)
    'on-line-side-1': [('game/geom/geom.s', """        lda GA_X                        ; the same whole part: <= when the
        ora GA_X+1                      ;   fraction is 0
        bne @dyneg""", """        lda GA_X                        ; (planted: on the line is above)
        ora GA_X+1
        bra @dyneg""")],
    # P_BoxOnLineSide's horizontal case on the wrong edge: the top tested
    # where the bottom is
    'horizontal-wrong-edge': [('game/geom/geom.s', """        ldx #GEO_BOTTOM - GA_0          ; bottom above v1.y << 16?""",
                               """        ldx #GEO_TOP - GA_0             ; (planted: the top)""")],
    # a block list read from its first entry (the list's 0: line 0)
    'list-first-entry': [('game/geom/giter.s', """        lda BL_BUF                      ;   the list's 0
        adc #1""", """        lda BL_BUF                      ;   (planted: the 0 itself)
        adc #0""")],
    # P_LineOpening's lowfloor as the higher floor: the lower floor taken
    # as openbottom
    'lowfloor-higher': [('game/geom/geom.s', """:       bpl @ceil""",
                         """:       bmi @ceil                       ; (planted)""")],
}


def ready():
    if M is None:
        return 'geom_check.py does not import: %s' % IMPORT_ERROR
    missing = M.need()
    if missing:
        return missing
    if not (M.OUT / 'select.json').exists() or not any(
            M.CASES.glob('*/*/h*.case.z')):
        return 'the part\'s cases are missing (%s)' % CAPTURE_CMD
    if not any(M.SYNTH.glob('*/s*.case.z')):
        return 'the synthetic cases are missing (%s)' % CAPTURE_CMD
    for gamemap in range(1, 10):
        try:
            p = M.setup_of_map(gamemap) / 'r.ram.z'
        except M.CheckError as error:
            return '%s (python3 tools/native/setupcap.py)' % error
        if not p.exists():
            return '%s is missing (python3 tools/native/setupcap.py)' % p
    return None


class Base(unittest.TestCase):
    built = None

    @classmethod
    def setUpClass(cls):
        why = ready()
        if why:
            raise unittest.SkipTest(why)
        if Base.built is None:
            Base.built = M.build()


class TestBuild(Base):
    def test_sizes_within_budget(self):
        s = M.sizes()
        self.assertGreater(s['native_bytes'], 0)
        self.assertLessEqual(s['native_bytes'], s['budget'], s)

    def test_entries_exported(self):
        b = M.load_build()
        for key in M.ENTRIES:
            name = M.GL.native_names()[key]
            self.assertIn(name, b.labels, name)

    def test_paths_declared(self):
        for key in M.ENTRIES:
            self.assertIn(key, M.PATHS, key)


class TestCheckpoint(Base):
    def test_every_case(self):
        """Every chosen case and every synthetic one, from both fills (one
        under f121, one under fastpath): the canonical state, the outputs,
        no stray write; every declared path taken."""
        res = M.check_cases(jobs=JOBS, combos=COMBOS,
                            say=lambda *a, **k: None)
        bad = [r for rs in res.values() for r in rs if M.failed(r)]
        self.assertEqual(bad, [], json.dumps(bad[:3])[:3000])
        sel = M.load_select()
        for key in M.ENTRIES:
            rs = res.get(key, [])
            self.assertTrue(rs, '%s: no case ran' % key)
            chosen = sum(1 for calls in sel['entries'][key]['chosen']
                         .values() for _, _, role in calls if role == 'check')
            runs = {(r['run'], r['case']) for r in rs
                    if not r.get('synthetic')}
            self.assertEqual(len(runs), chosen, key)
            # (an undecodable case never reaches the native run)
            self.assertTrue(all(r.get('stray_n', 0) == 0 for r in rs), key)
            self.assertTrue(all(r.get('stray_n') == 0 for r in rs
                                if r.get('class') == 'equal'), key)
            taken = {p for r in rs for p in r.get('paths', [])}
            missing = [p for p in M.PATHS[key] if p not in taken and
                       key not in M.ITERATORS]
            self.assertEqual(missing, [], '%s: paths not taken' % key)

    def test_iterators_recording(self):
        """The two iterators with the recording callback on every captured
        call's block (stopped at its first and second callback too)."""
        res = M.iter_cases(jobs=JOBS, combos=COMBOS,
                           say=lambda *a, **k: None)
        bad = [r for r in res if not r.get('ok')]
        self.assertEqual(bad, [], json.dumps(bad[:3])[:3000])
        # each combination records every callback of the 434 cases
        # (375 lines and 32 mobjs on 2026-10-01's captures)
        first = [r for r in res if (int(r['fill'], 16), r['profile']) ==
                 COMBOS[0]]
        self.assertGreater(sum(r.get('recorded', 0) for r in first), 300)
        self.assertTrue(any(r.get('stop') for r in res))
        self.assertEqual({r['routine'] for r in res}, set(M.ITERATORS))


class TestRandom(Base):
    def test_pairs_every_map(self):
        """100,000 point-line and 100,000 box-line pairs on each map."""
        res = M.rand_all(n=100_000, jobs=JOBS, say=lambda *a, **k: None)
        for m, r in res['maps'].items():
            self.assertEqual(r['points']['failed'], 0, (m, r['points']))
            self.assertEqual(r['boxes']['failed'], 0, (m, r['boxes']))
            for p in ('dx0-eq', 'dy0-eq', 'gen-eq', 'gen-0', 'gen-1'):
                self.assertIn(p, r['points']['paths'], m)
        self.assertEqual(res['posMul']['failed'], 0, res['posMul'])


class TestPlanted(Base):
    """Each planted bug, built from a scratch copy, fails its named
    check."""

    def plant(self, name):
        tmp = Path(tempfile.mkdtemp(prefix='tmp-geom-plant-',
                                    dir=str(M.BUILD)))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        return M.planted(tmp, PLANTS[name])

    def test_on_line_side_1(self):
        obj = self.plant('on-line-side-1')
        b = M.load_build(obj)
        r = M.rand_map(b, 1, 20_000, M.entry_cases(), 0xA5,
                       say=lambda *a, **k: None)
        self.assertGreater(r['points']['failed'], 0)

    def test_horizontal_wrong_edge(self):
        obj = self.plant('horizontal-wrong-edge')
        b = M.load_build(obj)
        r = M.rand_map(b, 1, 20_000, M.entry_cases(), 0xA5,
                       say=lambda *a, **k: None)
        self.assertGreater(r['boxes']['failed'], 0)

    def test_list_first_entry(self):
        obj = self.plant('list-first-entry')
        res = M.iter_cases(obj, JOBS, sample=20, combos=[(0xA5, 'f121')],
                           say=lambda *a, **k: None)
        self.assertTrue(res)
        self.assertGreater(sum(1 for r in res if not r.get('ok')), 0)

    def test_lowfloor_higher(self):
        obj = self.plant('lowfloor-higher')
        res = M.check_cases(['p_map65.s:P_LineOpening'], obj, JOBS,
                            sample=5, combos=[(0xA5, 'f121')],
                            say=lambda *a, **k: None)
        rs = res.get('p_map65.s:P_LineOpening', [])
        self.assertTrue(rs)
        bad = [r for r in rs if not r.get('ok')]
        self.assertGreater(len(bad), 0)
        self.assertTrue(any('_g_openbottom' in ' '.join(r.get('diff', []))
                            for r in bad), bad[:2])


if __name__ == '__main__':
    unittest.main()
