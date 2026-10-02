"""Part path of milestone 10 (docs/GAME.md 0.3 fact 4, 1.9, 2.2 TRVTAB,
2.4 row path, 2.5, 3.5, 5.2 acceptance 6): P_PathTraverse, its walk through
the block map, the early traversal and P_TraverseIntercepts, checked
against ref816 in routine mode (tools/native/gparts/path.py).

The lean checkpoint (the owner's request of 2026-10-02): at most 40
captured calls of P_PathTraverse, from the $A5 machine under f121: those
whose traverser never runs as captured; every one again with the recording
traverser and with traversers that stop at the k-th intercept, on both
sides (the reference's P_PathTraverse by ref816 --call on the captured
machine); the start on a block line (synthetic); acceptance 6's traces of
more than 64 intercepts with stops at 1, 8, 32, 64 and 65; a1Shr7 on
100,000 inputs against upstream's; the planted bugs, each made in a
scratch copy of the part's sources.

By default (under 60 s): the build's checks, 4 of the chosen calls with
their variants, the plain and synthetic cases, one acceptance trace, the
random check, and two planted bugs (the start not moved off a block line;
more than 64 intercepts handled as the C does). DOOM_GS_FULL=1: every
case and the three planted bugs (the early limit one block late too).

Skips with the command to run when build/ lacks what it needs: the shared
outputs, the survey, the placement, a2vm, ref816, mathref, the level
bases, or the part's own cases (python3 tools/native/gparts/path.py
--select --capture --variants --acceptance). Writes only under
build/native/game/path/ and temporary build/tmp-path-* directories,
deleted after each run.
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
    import path as M
    IMPORT_ERROR = None
except Exception as error:          # (an import that needs build/)
    M = None
    IMPORT_ERROR = error

FULL = os.environ.get('DOOM_GS_FULL') == '1'
JOBS = int(os.environ.get('PATH_JOBS', '2'))
LIMIT = None if FULL else 4
CASES_CMD = 'python3 tools/native/gparts/path.py --select --capture ' \
    '--variants --acceptance'


def ready():
    if M is None:
        return 'path.py does not import: %s' % IMPORT_ERROR
    missing = M.need()
    if missing:
        return missing
    if not (M.OUT / 'select.json').exists() or not any(
            M.CASES.glob('*/P_PathTraverse/h*.case.z')):
        return 'the part\'s cases are missing (%s)' % CASES_CMD
    if not any(M.VAR.glob('*-k0.case.z')) or not any(
            M.VAR.glob('synth-*.case.z')):
        return 'the reference\'s variants are missing (%s)' % CASES_CMD
    if not any(M.ACC.glob('*-k0.case.z')):
        return 'acceptance 6\'s traces are missing (%s)' % CASES_CMD
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
        """Every routine and helper with code has its label; callTrav has
        none (traverseTo's DCALL: request R3)."""
        b = M.G.load_build(M.OUT, M.IMAGE)
        for key in M.ROUTINES + M.HELPERS:
            name = M.native_name(key)
            if key in M.NO_CODE:
                self.assertNotIn(name, b.labels, name)
            else:
                self.assertIn(name, b.labels, name)

    def test_no_far_access(self):
        text = (M.SRC / 'game' / 'path' / 'path.s').read_text()
        text += (M.SRC / 'game' / 'path' / 'path.inc').read_text()
        code = '\n'.join(line.split(';')[0] for line in text.splitlines())
        for call in ('far_get', 'far_put', 'g_get', 'g_put'):
            self.assertNotIn(call, code)

    def test_recording_traverser(self):
        """The reference's recording traverser: 10 bytes an intercept, its
        loop's branch back to the loop's start."""
        code = M.rec_code(0xEB)
        i = code.index(bytes([0xD0]))
        self.assertEqual((i + 2 + (code[i + 1] - 256)), 16)
        self.assertEqual(code[-1], 0x6B)


class TestCheckpoint(Base):
    def test_cases(self):
        res = M.check_cases(M.OUT, JOBS, limit=LIMIT, say=quiet)
        kinds = {r['kind'] for r in res}
        self.assertEqual(kinds, {'plain', 'record', 'synth', 'acc6'})
        bad = [r for r in res if M.failed(r)]
        self.assertEqual(bad, [])
        self.assertTrue(all(r['class'] == 'equal' for r in res),
                        [r for r in res if r['class'] != 'equal'][:2])
        self.assertEqual(sum(r.get('stray_n', 0) for r in res), 0)
        # the stops: every recorded variant ran its k-stops
        stops = {r.get('stop') for r in res if r['kind'] == 'record'}
        self.assertTrue({0, 1} <= stops, stops)
        acc = [r for r in res if r['kind'] == 'acc6']
        self.assertEqual({r['stop'] for r in acc}, set(M.ACC_STOPS))
        # acceptance 6: the never-stopping runs return false (more than
        # 64 intercepts) on both sides
        over = [r for r in acc if r['acceptance'].get('over_64')]
        self.assertTrue(over)
        self.assertTrue(all(r.get('result') == 0 for r in over
                            if r['stop'] == 0))
        # the start on a block line: offLine moved it in each
        synth = [r for r in res if r['kind'] == 'synth']
        self.assertTrue(synth and all((r.get('marks') or {}).get('off-line')
                                      for r in synth))

    def test_random_a1shr7(self):
        r = M.random_check(100_000)
        self.assertEqual(r['compared'], 100_000)
        self.assertEqual(r['different'], 0, r['first'])


class TestPlants(Base):
    """Each planted bug in a scratch copy fails its check."""

    def plant(self, name):
        r = M.plant_check(name, JOBS, limit=LIMIT, say=quiet)
        return r['caught']

    def test_no_offline(self):
        self.assertGreater(self.plant('no-offline'), 0)

    def test_c_overflow(self):
        self.assertGreater(self.plant('c-overflow'), 0)

    @unittest.skipUnless(FULL, 'DOOM_GS_FULL=1')
    def test_early_late(self):
        self.assertGreater(self.plant('early-late'), 0)


if __name__ == '__main__':
    unittest.main()
