"""Part planes of milestone 10 (docs/GAME.md 2.4 row planes, wave 4;
docs/game-parts/planes.md): the plane movers (T_MovePlaneFloor,
T_MovePlaneCeiling), the check of the things in a moving sector
(checkSector, changeSector, heightClip) and the floor thinker T_MoveFloor
(THTAB's), natively (src/native/game/planes/).

What it checks (tools/native/gparts/planes.py does the work), in the lean
form the owner asked for on 2026-10-02 (under 60 s in the default suite):

  * the part builds within its budget, every entry of its args.json is a
    label of the image with a group, THTAB's floor entry is T_MoveFloor,
    and it makes no far access of a cached kind's bank
    (gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5) on a sample: the first
    chosen call of each entry and every SYN_SAMPLE-th synthetic call, from
    the poisoned machine $A5 under f121, equal to ref816's with the
    exclusions R1-R6 only, the declared outputs and the sector sound
    events equal, no stray write;
  * the three planted bugs, each built from a scratch copy of the part's
    sources in a temporary directory and failing its named check on a
    sample of that check's cases (`planes.py --plants` runs them all);
  * with DOOM_GS_FULL=1: every chosen captured call and every synthetic
    call under f121 and fastpath (`planes.py --check`).

It skips with the reason when build/ lacks upstream's sources, ref816,
a2vm, the shared outputs (`make -s -C src/native -f game.mk shared
ROOT=$PWD`; the survey: `python3 tools/native/gamecap.py --survey`), the
level bases (`python3 tools/native/level_check.py --setup`) or the part's
own captures (`python3 tools/native/gparts/planes.py --log`, `--capture`,
then `--synthetic`). It never rebuilds a shared output.
"""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

import planes as P  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'
SYN_SAMPLE = 3
PLANT_SAMPLE = 4


def setUpModule():
    """The part's own case directory: gamecap's CASES is one global, which
    the harness sets when imported and another part's harness may change
    in the same process (unittest discover runs every module in one)."""
    P.GC.CASES = P.CASES


def why_skip():
    why = P.missing()
    if why:
        return why
    if not P.CHOICE.exists():
        return ('no captures (python3 tools/native/gparts/planes.py --log, '
                'then --capture)')
    ch = P.load_choice()
    for key in P.ENTRIES:
        names = ch['chosen'].get(key) or []
        if not names or not all((P.OUT / n).exists() for n in names):
            return ('no captures of %s (python3 tools/native/gparts/'
                    'planes.py --capture)' % key)
    if not P.SYN.exists():
        return ('no synthetic cases (python3 tools/native/gparts/planes.py '
                '--synthetic)')
    return None


SKIP = why_skip()
_BUILT = []


def built():
    if not _BUILT:
        _BUILT.append(P.build())
    return _BUILT[0]


@unittest.skipIf(SKIP, SKIP or '')
class Build(unittest.TestCase):

    def test_builds_within_budget(self):
        built()
        sz = P.sizes()
        self.assertLessEqual(sz['bytes'], sz['budget'])
        for name in P.LABELS:
            self.assertIn(name, sz['routines'])

    def test_no_far_access_of_a_cached_kind(self):
        problems = P.GR.grep_check(P.SRC, ['game/planes/planes.s'])
        self.assertEqual(problems, [])

    def test_args(self):
        built()
        nat = P.SF.Native(P.OUT)
        spec = P.args()
        self.assertEqual(set(spec), set(P.ENTRIES))
        for key, e in spec.items():
            self.assertIn(e['native'], nat.b.labels, key)
            nat.group(e['native'])
            for item in e['in'] + e['out']:
                for place in (item.get('to', ''), item.get('native', '')):
                    if place.startswith('sb:'):
                        P.sb_address(place[3:])

    def test_thtab_entry(self):
        """THTAB's floor entry is this part's T_MoveFloor."""
        built()
        text = (P.OUT / 'gen' / 'gdisp.inc').read_text()
        row = [x for x in text.splitlines()
               if x.rstrip().endswith('p_floor65.s:T_MoveFloor')]
        self.assertEqual(len(row), 1)
        self.assertIn('<T_MoveFloor', row[0])


def run_checked(test, jobs):
    res = P.run_jobs(jobs, workers=2, progress=False)
    test.assertTrue(res)
    bad = [r for r in res if not r.get('ok')]
    test.assertEqual(bad, [], json.dumps(bad[:3])[:3000])
    test.assertEqual(sum(r.get('stray') or 0 for r in res), 0)
    return res


@unittest.skipIf(SKIP, SKIP or '')
class Checkpoint(unittest.TestCase):

    def test_sample(self):
        """The first chosen call of each entry and every SYN_SAMPLE-th
        synthetic call, $A5 under f121."""
        built()
        one = dict(fills=(0xA5,), profiles=('f121',))
        ch = P.load_choice()
        items = [('case', key, ch['chosen'][key][0]) for key in P.ENTRIES]
        jobs = [(items, str(P.OUT), (0xA5,), ('f121',))]
        jobs += P.check_jobs(captured=False, sample=SYN_SAMPLE, **one)
        res = run_checked(self, jobs)
        self.assertEqual({r['entry'] for r in res}, set(P.ENTRIES))

    @unittest.skipUnless(FULL, 'the whole checkpoint: DOOM_GS_FULL=1')
    def test_all(self):
        """Every chosen captured call and every synthetic call, $A5 under
        f121 and fastpath (`planes.py --check`)."""
        built()
        res = run_checked(self, P.check_jobs())
        paths = {r['path'] for r in res}
        for want in ('dir-1-res0-things', 'dir1-res2', 'dir-1-res1',
                     'onfloor-fits', 'n0-nofit0', 'removed', 'gibs',
                     'nofit-shootable', 'dir1-pastdest'):
            self.assertTrue(any(want in p for p in paths), want)


@unittest.skipIf(SKIP, SKIP or '')
class Planted(unittest.TestCase):
    """Each planted bug fails its named check (GAME.md 2.4) on a sample of
    its cases."""

    def plant(self, name):
        built()
        r = P.plants([name], sample=PLANT_SAMPLE)[name]
        self.assertTrue(r['caught'], r)
        self.assertGreater(r['runs'], 0)

    def test_sector_list(self):
        self.plant('sector-list')

    def test_not_undone(self):
        self.plant('not-undone')

    def test_visited_kept(self):
        self.plant('visited-kept')


if __name__ == '__main__':
    unittest.main()
