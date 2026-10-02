"""Part tracel of milestone 10 (docs/GAME.md 1.9, 2.4 row tracel, 2.5,
3.5): the intercepts of the lines a trace crosses, checked against ref816
in routine mode (tools/native/gparts/tracel.py).

The checkpoint: the captured calls of every entry and the synthetic cases
(two intercepts of equal frac, the full list), and PIT_AddLineIntercepts
through P_BlockLinesIterator on the captured block steps of
P_PathTraverse, from both poisoned machines under f121 and fastpath;
every logged call of interceptVector3 and divlineSide in the four runs;
interceptVector3 and divlineSide on 1,000,000 random inputs, ivProd and
smul on 100,000, ivTest (FixedDiv and its guards) on 300,000, ivAxis,
ivSetup, vsC on 100,000 and gOf on all 65,536, against upstream's
routines (mathref); and the planted bugs, each made in a scratch copy of
the part's sources and caught by its named check.

Skips with the command to run when build/ lacks what it needs: the shared
outputs, the survey, a2vm, ref816, mathref, the level bases, or the
part's own cases and logs (python3 tools/native/gparts/tracel.py --select
--capture --synth --logs). Writes only under build/native/game/tracel/
and temporary build/tmp-tracel-* directories, deleted after each run.

TRACEL_JOBS (default 2) sets the processes; TRACEL_SAMPLE (default 5)
takes every n-th captured case (and every synthetic one), so that the
module stays within the runner's time limit: `tracel.py --run` runs every
case from both fills under both profiles for report.json (11,300 runs,
about 70 minutes at 2 processes; docs/game-parts/tracel.md section 3), and
TRACEL_SAMPLE=1 runs them all here.
"""

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
    import tracel as M
    IMPORT_ERROR = None
except Exception as error:          # (an import that needs build/)
    M = None
    IMPORT_ERROR = error

JOBS = int(os.environ.get('TRACEL_JOBS', '2'))
SAMPLE = int(os.environ.get('TRACEL_SAMPLE', '5'))
# every case from both poisoned machines, one under each cost profile (the
# tool's --run makes the four runs a case for report.json)
COMBOS = [(0xA5, 'f121'), (0x5A, 'fastpath')]
CASES_CMD = ('python3 tools/native/gparts/tracel.py --select --capture '
             '--synth --logs')


def ready():
    if M is None:
        return 'tracel.py does not import: %s' % IMPORT_ERROR
    missing = M.need()
    if missing:
        return missing
    if not (M.OUT / 'select.json').exists() or not any(
            M.CASES.glob('*/*/h*.case.z')):
        return 'the part\'s cases are missing (%s)' % CASES_CMD
    if not any(M.SYNTH.glob('*/s*.case.z')):
        return 'the synthetic cases are missing (%s)' % CASES_CMD
    for run in M.LOG_RUNS:
        if not (M.LOGS / ('%s.json.z' % run)).exists():
            return 'the call logs are missing (%s)' % CASES_CMD
    try:
        M.ram()
    except Exception as error:
        return '%s (python3 tools/native/setupcap.py)' % error
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
    def test_size_within_budget(self):
        s = M.sizes()
        self.assertGreater(s['native_bytes'], 0)
        self.assertLessEqual(s['native_bytes'], s['budget'], s)

    def test_routines_exported(self):
        """Every routine and helper of the part has its label, but the
        long-call wrappers inlined (glayout.INLINED, request R3: their
        callers FCALL the routine itself), which have none."""
        from native import glayout as GL
        b = M.load_build()
        for key in M.ENTRIES + M.HELPERS:
            name = M.native_name(key)
            if GL.inlined(key):
                self.assertNotIn(name, b.labels, name)
            else:
                self.assertIn(name, b.labels, name)

    def test_no_far_access(self):
        text = (M.SRC / 'game' / 'tracel' / 'tracel.s').read_text()
        code = '\n'.join(line.split(';')[0] for line in text.splitlines())
        for call in ('far_get', 'far_put', 'g_get', 'g_put'):
            self.assertNotIn(call, code)


class TestCheckpoint(Base):
    def test_cases(self):
        res = M.check_cases(obj=M.OUT, jobs=JOBS, sample=SAMPLE,
                            combos=COMBOS, say=lambda *a, **k: None)
        for key in M.ENTRIES + [M.ITER]:
            self.assertIn(key, res, key)
        for key, rs in res.items():
            bad = [r for r in rs if M.failed(r)]
            self.assertEqual(bad, [], key)
            self.assertEqual(sum(r.get('stray_n', 0) for r in rs), 0, key)
            self.assertTrue(any(r['class'] == 'equal' for r in rs), key)

    def test_every_logged_call(self):
        r = M.check_logs(M.OUT, JOBS, say=lambda *a, **k: None)
        self.assertEqual(r['failures'], 0, r)
        self.assertGreater(r['kinds']['interceptVector3']['calls'], 10000)

    def test_random(self):
        r = M.rand_all(M.OUT, None, JOBS, say=lambda *a, **k: None)
        self.assertEqual(r['failures'], 0, r)
        for kind, k in r['kinds'].items():
            self.assertEqual(k['inputs'], M.RAND_N[kind], kind)
        self.assertEqual(r['kinds']['ivTest']['no_return_confirmed'],
                         M.RAND_HANG)


class TestPlants(Base):
    """Each planted bug in a scratch copy fails its named check."""

    def plant(self, name):
        bugs, check = M.PLANTS[name]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-tracel-plant-',
                                    dir=str(M.BUILD)))
        try:
            obj = M.planted(tmp, bugs)
            kind, _, what = check.partition(':')
            if kind == 'rand':
                r = M.rand_kind(what, M.RAND_N[what], obj, JOBS,
                                hang_checks=0, say=lambda *a, **k: None)
                return M.rand_failures(r)
            res = M.check_cases(['p_trace65.s:addIntercept',
                                 'p_trace65.s:icInsert'], obj, JOBS,
                                sample=10 ** 9, combos=COMBOS[:1],
                                say=lambda *a, **k: None)
            return sum(1 for rs in res.values() for r in rs
                       if r.get('synthetic') and M.failed(r))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_fixeddiv_guard(self):
        self.assertGreater(self.plant('fixeddiv-guard'), 0)

    def test_fast_product(self):
        self.assertGreater(self.plant('fast-product'), 0)

    def test_equal_before(self):
        self.assertGreater(self.plant('equal-before'), 0)


if __name__ == '__main__':
    unittest.main()
