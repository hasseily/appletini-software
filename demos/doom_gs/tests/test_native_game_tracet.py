"""Part tracet of milestone 10 (docs/GAME.md 1.9, 2.4 row tracet, 2.5,
3.5): the block steps of a long trace with the fast vertex sides
(traceLines, traceThings with thFast and thSide) and their setup
(sideSetup, longTrace), checked against ref816 in routine mode
(tools/native/gparts/tracet.py).

The lean checkpoint (the owner's request of 2026-10-02): a sample of at
most 40 captured calls an entry and the synthetic cases (a trace through a
vertex, one along a line, the slow sides of things, the full list, the
setup's edges), from the $A5 machine under f121; the evidence that no
captured call writes the dead guard's state (GAME.md 3.5 R4); the planted
bugs, each made in a scratch copy of the part's sources and caught by the
sampled cases of its entry.

By default (under 60 s): the build's checks, 4 sampled calls an entry
with every synthetic case, the guard's evidence and one planted bug
(the stamp written after the side test). DOOM_GS_FULL=1: every sampled
call and the three planted bugs.

Skips with the command to run when build/ lacks what it needs: the shared
outputs, the survey, a2vm, ref816, the level bases, or the part's own
cases (python3 tools/native/gparts/tracet.py --select --capture --synth).
Writes only under build/native/game/tracet/ and temporary
build/tmp-tracet-* directories, deleted after each run.
"""

import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))
sys.path.insert(0, str(ROOT / 'tools'))

try:
    import tracet as M
    IMPORT_ERROR = None
except Exception as error:          # (an import that needs build/)
    M = None
    IMPORT_ERROR = error

FULL = os.environ.get('DOOM_GS_FULL') == '1'
JOBS = int(os.environ.get('TRACET_JOBS', '2'))
LIMIT = None if FULL else 4
CASES_CMD = 'python3 tools/native/gparts/tracet.py --select --capture ' \
    '--synth'


def ready():
    if M is None:
        return 'tracet.py does not import: %s' % IMPORT_ERROR
    missing = M.need()
    if missing:
        return missing
    if not (M.OUT / 'select.json').exists() or not any(
            M.CASES.glob('*/*/h*.case.z')):
        return 'the part\'s cases are missing (%s)' % CASES_CMD
    if not any(M.SYNTH.glob('*/s*.case.z')):
        return 'the synthetic cases are missing (%s)' % CASES_CMD
    return None


def quiet(*a, **k):
    pass


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
        """Every routine and helper with code has its label; upstream's
        patched templates, their patchers and thFastL have none (data:
        request R1)."""
        b = M.load_build()
        for key in M.ROUTINES + M.HELPERS:
            name = M.native_name(key)
            if key in M.NO_CODE:
                self.assertNotIn(name, b.labels, name)
            else:
                self.assertIn(name, b.labels, name)

    def test_no_far_access(self):
        text = (M.SRC / 'game' / 'tracet' / 'tracet.s').read_text()
        text += (M.SRC / 'game' / 'tracet' / 'tracet.inc').read_text()
        code = '\n'.join(line.split(';')[0] for line in text.splitlines())
        for call in ('far_get', 'far_put', 'g_get', 'g_put'):
            self.assertNotIn(call, code)


class TestCheckpoint(Base):
    def test_cases(self):
        res = M.check_cases(obj=M.OUT, jobs=JOBS, limit=LIMIT, say=quiet)
        for key in M.ENTRIES:
            self.assertIn(key, res, key)
        for key, rs in res.items():
            bad = [r for r in rs if M.failed(r)]
            self.assertEqual(bad, [], key)
            self.assertEqual(sum(r.get('stray_n', 0) for r in rs), 0, key)
            self.assertTrue(all(r['class'] == 'equal' for r in rs), key)
        synth = {r['routine'] for rs in res.values() for r in rs
                 if r.get('synthetic')}
        self.assertEqual(synth, set(M.ENTRIES))

    def test_dead_guard(self):
        """No captured call writes the dead guard's state, and G_IDT is 0
        at every captured call of traceLines (GAME.md 3.5 R4)."""
        g = M.guard_evidence(say=quiet)
        self.assertTrue(g['ok'], g)
        self.assertGreater(g['traceLines_cases'], 0)


class TestPlants(Base):
    """Each planted bug in a scratch copy fails the sampled cases of its
    entry."""

    def plant(self, name):
        r = M.plant_check(name, JOBS, limit=LIMIT, say=quiet)
        return r['caught']

    def test_stamp_after(self):
        self.assertGreater(self.plant('stamp-after'), 0)

    @unittest.skipUnless(FULL, 'DOOM_GS_FULL=1')
    def test_quadrant(self):
        self.assertGreater(self.plant('quadrant'), 0)

    @unittest.skipUnless(FULL, 'DOOM_GS_FULL=1')
    def test_met_twice(self):
        self.assertGreater(self.plant('met-twice'), 0)


if __name__ == '__main__':
    unittest.main()
