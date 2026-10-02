"""Part chasemove of milestone 10 (docs/GAME.md 2.4 row chasemove, wave 5;
docs/game-parts/chasemove.md): the monsters' walk (pMove: P_Move with its
speed steps, the try and the blocked doors; tryWalk, P_TryWalk), the new
chase direction (newChaseDir, doNewChaseDir: the directions with P_Random,
the turnaround; P_NewChaseDir) and the drop-off avoidance (avoidDropoff,
ITTAB's PIT_AvoidDropoff), natively (src/native/game/chasemove/).

What it checks (tools/native/gparts/chasemove.py does the work), within the
lean checks the owner asked for on 2026-10-02:

  * the part builds without a warning, within its budget (2,900 B), makes
    no far access (no g_get, g_put, far_get or far_put:
    gameroutine.grep_check), and no routine jumps to another routine's
    local code (each routine's local code is in its own segment, which can
    be another group of the same slot);
  * the checkpoint (routine mode, GAME.md 3.5): every SAMPLE-th of the
    chosen captured calls of pMove and newChaseDir inside A_Chase (40
    each: a cover of the candidates' paths), from the $A5 machine under
    f121, equal to ref816's with the routine exclusions only, every
    declared output equal, no stray write;
  * the random checks of umul16x, mulSpeed and times32 against upstream's
    on ref816 (2,000 inputs each; 100,000 with DOOM_GS_FULL=1);
  * with DOOM_GS_FULL=1: every chosen call under f121 and fastpath, the
    paths they take, and the planted bugs, each built from a scratch copy
    of the part's sources in a temporary directory and failing the
    checkpoint: P_Random taken before the direct test, the turnaround
    table, the diagonal tried after the straight ones.

It skips with the reason when build/ lacks ref816, a2vm, the shared
outputs (`make -s -C src/native -f game.mk shared ROOT=$PWD`; the survey:
`python3 tools/native/gamecap.py --survey`), the level bases (`python3
tools/native/level_check.py --setup`), mathref (milestone 6) or the part's
own survey and captures (`python3 tools/native/gparts/chasemove.py
--survey`, then `--capture`). It never rebuilds a shared output.
"""

import json
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

import chasemove as T  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'
SAMPLE = 4


def setUpModule():
    """The part's own case directory (gamecap's CASES is one global, which
    another part's harness may change in the same process)."""
    T.GC.CASES = T.CASES


def why_skip():
    why = T.missing()
    if why:
        return why
    for run in T.SURVEY_RUNS:
        if T.own_survey(run) is None:
            return ('no survey of newChaseDir in %s (python3 tools/native/'
                    'gparts/chasemove.py --survey)' % run)
    known = json.loads(T.PATHS_FILE.read_text()) \
        if T.PATHS_FILE.exists() else {}
    for key in T.ENTRIES:
        got = T.captured(key)
        if not got:
            return ('no captures of %s (python3 tools/native/gparts/'
                    'chasemove.py --capture)' % key)
        if any(str(p) not in known.get(key, {}) for _, _, p in got):
            return ('the paths of %s are not decoded (python3 tools/native/'
                    'gparts/chasemove.py --capture)' % key)
    return None


WHY = why_skip()


def segments_of(text):
    """label -> the ROUTINE it is under (its segment), and the jsr/jmp
    targets under each ROUTINE: (routine, target, line)."""
    owner, calls = {}, []
    routine = None
    for n, line in enumerate(text.splitlines(), 1):
        code = line.split(';', 1)[0]
        m = re.match(r'\s+ROUTINE\s+(\w+)', code)
        if m:
            routine = m.group(1)
            continue
        m = re.match(r'([A-Za-z_]\w*):', code)
        if m and routine:
            owner[m.group(1)] = routine
        m = re.search(r'\b(jsr|jmp)\s+([A-Za-z_]\w*)\b', code)
        if m and routine:
            calls.append((routine, m.group(2), n))
    return owner, calls


class Sources(unittest.TestCase):
    def test_local_code_in_its_routines_segment(self):
        """A jsr or jmp to local code goes to code under the same ROUTINE
        (its group): doNewChaseDir once called newChaseDir's cm_get in
        another group of slot 2 (found by the checkpoint)."""
        for f in T.GAME_SOURCES:
            owner, calls = segments_of((T.PART_SRC / f).read_text())
            bad = [(r, t, n) for r, t, n in calls
                   if t in owner and owner[t] != r]
            self.assertEqual(bad, [], f)

    def test_no_far_access(self):
        """No g_get, g_put, far_get or far_put: every record through the
        object API."""
        from native import gameroutine as GR
        for f in T.GAME_SOURCES:
            words = [GR._code(x) for x in
                     (T.PART_SRC / f).read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and
                   w[0] in ('jsr', 'jmp') and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], f)
        self.assertEqual(GR.grep_check(T.PART_SRC, T.GAME_SOURCES), [])

    def test_args_declare_the_entries(self):
        spec = T.args()
        for key in T.ENTRIES:
            self.assertIn(key, spec)
        self.assertEqual(spec[T.PMOVE]['out'][0]['native'], 'a')


@unittest.skipIf(T.missing(), str(T.missing()))
class Build(unittest.TestCase):
    def test_builds_within_its_budget(self):
        T.build()
        sz = T.sizes()
        self.assertGreater(sz['bytes'], 0)
        self.assertLessEqual(sz['bytes'], sz['budget'], sz)
        for name in T.LABELS:
            self.assertIn(name, sz['routines'], name)


@unittest.skipIf(WHY, str(WHY))
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T.build()
        cls.res = T.run_jobs(T.check_jobs(sample=1 if FULL else SAMPLE,
                                          profiles=T.PROFILES if FULL else
                                          T.PROFILES[:1]), 2)

    def test_every_run_equal(self):
        run = [r for r in self.res if not r.get('waiting')]
        bad = [(r['case'], r.get('profile'), r.get('diff') or
                r.get('error') or r.get('ended')) for r in run
               if not r.get('ok')]
        self.assertEqual(bad, [])
        self.assertEqual(sum(r.get('stray') or 0 for r in run), 0)

    def test_both_entries_ran(self):
        for key in T.ENTRIES:
            with self.subTest(key):
                self.assertTrue([r for r in self.res if r['entry'] == key
                                 and r.get('ok')])

    @unittest.skipUnless(FULL, 'the paths of every chosen call: '
                         'DOOM_GS_FULL=1')
    def test_the_paths_taken(self):
        """The chosen calls walk an axis and a diagonal, move, are blocked
        with and without special lines (a door opened and none), and find
        their new direction by the diagonal, a straight one, the old one
        and the search, away from a drop-off (PIT_AvoidDropoff)."""
        paths = set()
        for r in self.res:
            if r.get('ok'):
                paths.update(r.get('path', []))
        for what in ('axis', 'diagonal', 'moved', 'blocked',
                     'blocked-specials', 'opened', 'none-opened', 'nodir',
                     'took-diagonal', 'took-straight', 'took-olddir',
                     'took-search', 'stuck', 'dropoff-away',
                     'reached-PIT_AvoidDropoff', 'diag-is-turnaround'):
            self.assertIn(what, paths)


@unittest.skipIf(WHY, str(WHY))
class Random(unittest.TestCase):
    def test_helpers_equal_upstream(self):
        why = T.random_missing()
        if why:
            self.skipTest(why)
        T.build()
        r = T.random_check(100_000 if FULL else 2_000)
        for helper in T.HELPERS:
            with self.subTest(helper):
                self.assertEqual(r[helper]['different'], 0, r[helper])
                self.assertEqual(r[helper]['compared'], r[helper]['inputs'])


@unittest.skipIf(WHY, str(WHY))
@unittest.skipUnless(FULL, 'the planted bugs: DOOM_GS_FULL=1')
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        r = T.plants()
        for name in T.PLANT_NAMES:
            with self.subTest(name):
                self.assertGreater(r[name]['runs'], 0)
                self.assertTrue(r[name]['caught'], name)


if __name__ == '__main__':
    unittest.main()
