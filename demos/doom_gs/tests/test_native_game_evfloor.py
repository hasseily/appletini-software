"""Part evfloor of milestone 10 (docs/GAME.md 2.4 row evfloor, wave 4;
docs/game-parts/evfloor.md): the floors, the stairs and the donut a line
starts (EV_DoFloor, EV_BuildStairs, EV_DoDonut, newFloor and LSTAB's
lnFloor, lnStairs, lnDonut), natively (src/native/game/evfloor/).

What it checks (tools/native/gparts/evfloor.py does the work), in the lean
form the owner asked for on 2026-10-02 (under 60 s in the default suite):

  * the part builds within its budget, every entry of its args.json is a
    label of the image with a group, LSTAB's three floor entries are the
    part's handlers, and it makes no far access of a cached kind's bank
    (gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5): every captured call and
    every synthetic call, from the poisoned machine $A5 under f121, equal
    to ref816's with the exclusions R1-R6 only, the declared outputs and
    the sound events equal, no stray write;
  * the three planted bugs, each built from a scratch copy of the part's
    sources in a temporary directory and failing its named check
    (`evfloor.py --plants`);
  * with DOOM_GS_FULL=1: the same calls under fastpath too
    (`evfloor.py --check`).

It skips with the reason when build/ lacks upstream's sources, ref816,
a2vm, the shared outputs (`make -s -C src/native -f game.mk shared
ROOT=$PWD`; the survey: `python3 tools/native/gamecap.py --survey`), the
level bases (`python3 tools/native/level_check.py --setup`) or the part's
own captures (`python3 tools/native/gparts/evfloor.py --capture`, then
`--synthetic`). It never rebuilds a shared output.
"""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

import evfloor as E  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'


def setUpModule():
    """The part's own case directory: gamecap's CASES is one global, which
    the harness sets when imported and another part's harness may change
    in the same process (unittest discover runs every module in one)."""
    E.GC.CASES = E.CASES


def why_skip():
    why = E.missing()
    if why:
        return why
    E.GC.CASES = E.CASES
    why = E.captures_complete()
    if why:
        return '%s (python3 tools/native/gparts/evfloor.py --capture)' % why
    for name in E.synthetic_names():
        if not (E.SYN / (name + '.json.z')).exists():
            return ('no synthetic calls %s (python3 tools/native/gparts/'
                    'evfloor.py --synthetic)' % name)
    return None


SKIP = why_skip()
_BUILT = []


def built():
    if not _BUILT:
        _BUILT.append(E.build())
    return _BUILT[0]


@unittest.skipIf(SKIP, SKIP or '')
class Build(unittest.TestCase):

    def test_builds_within_budget(self):
        built()
        sz = E.sizes()
        self.assertLessEqual(sz['bytes'], sz['budget'])
        for name in E.LABELS:
            self.assertIn(name, sz['routines'])

    def test_no_far_access_of_a_cached_kind(self):
        problems = E.GR.grep_check(E.SRC, ['game/evfloor/evfloor.s'])
        self.assertEqual(problems, [])

    def test_args(self):
        built()
        nat = E.SF.Native(E.OUT)
        spec = E.args()
        self.assertEqual(set(spec), set(E.ALL_KEYS))
        for key, e in spec.items():
            self.assertIn(e['native'], nat.b.labels, key)
            nat.group(e['native'])

    def test_lstab_entries(self):
        """LSTAB's floor, stairs and donut entries are this part's
        handlers."""
        built()
        text = (E.OUT / 'gen' / 'gdisp.inc').read_text()
        for name in ('lnFloor', 'lnStairs', 'lnDonut'):
            row = [x for x in text.splitlines() if x.rstrip().endswith(
                'p_switch65.s:' + name)]
            self.assertEqual(len(row), 1, name)
            self.assertIn('<%s' % name, row[0])


def run_checked(test, jobs):
    res = E.run_jobs(jobs, workers=2, progress=False)
    test.assertTrue(res)
    bad = [r for r in res if not r.get('ok')]
    test.assertEqual(bad, [], json.dumps(bad[:3])[:3000])
    test.assertEqual(sum(r.get('stray') or 0 for r in res), 0)
    return res


@unittest.skipIf(SKIP, SKIP or '')
class Checkpoint(unittest.TestCase):

    def check(self, profiles):
        built()
        res = run_checked(self, E.check_jobs(fills=(0xA5,),
                                             profiles=profiles))
        paths = {r['path'] for r in res}
        # the branches the lean checkpoint reaches (docs/game-parts/
        # evfloor.md 3): every floor type, the stairs, the donut, busy
        for want in ('type0x1-arg0', 'type7x1-arg7', 'type1x1', 'type2x',
                     'type3x', 'type4x1', 'lnStairs-mode1:type6x',
                     'lnDonut-mode1:type0x1,type5x1', 'none-busy',
                     'new-type'):
            self.assertTrue(any(want in p for p in paths), want)
        self.assertEqual({r['entry'] for r in res},
                         {E.DOFLOOR, E.NEWFLOOR, E.USE, E.CROSS})

    def test_f121(self):
        """Every captured and synthetic call, $A5 under f121."""
        self.check(('f121',))

    @unittest.skipUnless(FULL, 'fastpath too: DOOM_GS_FULL=1')
    def test_fastpath(self):
        self.check(('fastpath',))


@unittest.skipIf(SKIP, SKIP or '')
class Planted(unittest.TestCase):
    """Each planted bug fails its named check (GAME.md 2.4)."""

    def plant(self, name):
        built()
        r = E.plants([name])[name]
        self.assertTrue(r['caught'], r)
        self.assertGreater(r['runs'], 0)

    def test_stairs_other_side(self):
        self.plant('stairs-other-side')

    def test_donut_outer_floor(self):
        self.plant('donut-outer-floor')

    def test_turbo_speed(self):
        self.plant('turbo-speed')


if __name__ == '__main__':
    unittest.main()
