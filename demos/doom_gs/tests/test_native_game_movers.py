"""Part movers of milestone 10 (docs/GAME.md 2.4 row movers, wave 6;
docs/game-parts/movers.md): the door thinker T_VerticalDoor with partLight
and the plat thinker T_PlatRaise (THTAB's), natively
(src/native/game/movers/).

What it checks (tools/native/gparts/movers.py does the work), in the lean
form the owner asked for on 2026-10-02 (under 60 s in the default suite):

  * the part builds within its budget, every entry of its args.json is a
    label of the image with a group, THTAB's door and plat entries are its
    thinkers, and it makes no far access of a cached kind's bank
    (gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5) on a sample: one chosen
    call of each path of each entry and every synthetic call, from the
    poisoned machine $A5 under f121, equal to ref816's with the exclusions
    R1-R6 only, the sector sound events equal (upstream's own, from the
    call log), no stray write;
  * mulExt's random check (GAME.md 2.4 "Arithmetic") on RANDOM inputs,
    the edges included (`movers.py --random` runs 100,000);
  * the three planted bugs, each built from a scratch copy of the part's
    sources in a temporary directory and failing its named check
    (`movers.py --plants`);
  * with DOOM_GS_FULL=1: every chosen captured call and every synthetic
    call under f121 and fastpath (`movers.py --check`) and mulExt on
    100,000 inputs.

It skips with the reason when build/ lacks upstream's sources, ref816,
a2vm, mathref, the shared outputs (`make -s -C src/native -f game.mk shared
ROOT=$PWD`; the survey: `python3 tools/native/gamecap.py --survey`), the
level bases (`python3 tools/native/level_check.py --setup`) or the part's
own captures (`python3 tools/native/gparts/movers.py --log`, `--capture`,
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

import movers as P  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'
RANDOM = 100_000 if FULL else 10_000


def setUpModule():
    """The part's own case directory: gamecap's CASES is one global, which
    the harness sets when imported and another part's harness may change
    in the same process (unittest discover runs every module in one)."""
    P.GC.CASES = P.CASES


def why_skip():
    why = P.missing()
    if why:
        return why
    if not (P.BUILD / 'native' / 'math' / 'mathref').exists():
        return 'no mathref (make -C tools/native/math, milestone 6)'
    if not P.CHOICE.exists():
        return ('no captures (python3 tools/native/gparts/movers.py --log, '
                'then --capture)')
    ch = P.load_choice()
    for key in P.ENTRIES:
        recs = ch['chosen'].get(key) or []
        if not recs or not all((P.OUT / r['case']).exists() for r in recs):
            return ('no captures of %s (python3 tools/native/gparts/'
                    'movers.py --capture)' % key)
    if not P.SYN.exists():
        return ('no synthetic cases (python3 tools/native/gparts/movers.py '
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
        problems = P.GR.grep_check(P.SRC, ['game/movers/movers.s'])
        self.assertEqual(problems, [])

    def test_args(self):
        built()
        nat = P.SF.Native(P.OUT)
        spec = P.args()
        self.assertEqual(set(spec), set(P.ENTRIES))
        for key, e in spec.items():
            self.assertIn(e['native'], nat.b.labels, key)
            nat.group(e['native'])

    def test_thtab_entries(self):
        """THTAB's door and plat entries are this part's thinkers."""
        built()
        text = (P.OUT / 'gen' / 'gdisp.inc').read_text()
        for key, label in ((P.DOOR, 'T_VerticalDoor'),
                           (P.PLAT, 'T_PlatRaise')):
            row = [x for x in text.splitlines()
                   if x.rstrip().endswith(key)]
            self.assertEqual(len(row), 1, key)
            self.assertIn('<%s' % label, row[0])


def run_checked(test, jobs):
    res = P.run_jobs(jobs, workers=2, progress=False)
    test.assertTrue(res)
    bad = [r for r in res if not r.get('ok')]
    test.assertEqual(bad, [], json.dumps(bad[:3])[:3000])
    test.assertEqual(sum(r.get('stray') or 0 for r in res), 0)
    test.assertFalse([r['case'] for r in res
                      if r.get('model_agrees') is False])
    return res


@unittest.skipIf(SKIP, SKIP or '')
class Checkpoint(unittest.TestCase):

    def test_sample(self):
        """One chosen call of each path of each entry and every synthetic
        call, $A5 under f121."""
        built()
        one = dict(fills=(0xA5,), profiles=('f121',))
        ch = P.load_choice()
        items = []
        for key in P.ENTRIES:
            seen = set()
            for r in ch['chosen'][key]:
                if r['path'] not in seen:
                    seen.add(r['path'])
                    items.append(('case', key, r))
        jobs = [(items[i:i + 8], str(P.OUT), (0xA5,), ('f121',))
                for i in range(0, len(items), 8)]
        jobs += P.check_jobs(captured=False, **one)
        res = run_checked(self, jobs)
        self.assertEqual({r['entry'] for r in res}, set(P.ENTRIES))
        paths = {r['path'] for r in res}
        for want in ('wait-end-dorcls', 'down-res1-things-doropn',
                     'up-res2', 'down-res2-removed', 'wait-end-pstart',
                     'up-res2-pstop-removed', 'down-res2-pstop',
                     'up-res0-stnmov', 'door-dir-1-to1-type0',
                     'door-dir0-to1-type1', 'plat-status0-to1-type0',
                     'light-tag1'):
            self.assertTrue(any(p.startswith(want) for p in paths), want)

    @unittest.skipUnless(FULL, 'the whole checkpoint: DOOM_GS_FULL=1')
    def test_all(self):
        """Every chosen captured call and every synthetic call, $A5 under
        f121 and fastpath (`movers.py --check`)."""
        built()
        run_checked(self, P.check_jobs())


@unittest.skipIf(SKIP, SKIP or '')
class Arithmetic(unittest.TestCase):

    def test_mulext_random(self):
        """mulExt against upstream's on ref816, the edges included."""
        built()
        r = P.random_check(RANDOM)
        self.assertEqual(r['compared'], RANDOM)
        self.assertEqual(r['different'], 0, r['first'])


@unittest.skipIf(SKIP, SKIP or '')
class Planted(unittest.TestCase):
    """Each planted bug fails its named check (GAME.md 2.4)."""

    def plant(self, name):
        built()
        r = P.plants([name])[name]
        self.assertTrue(r['caught'], r)
        self.assertGreater(r['runs'], 0)

    def test_door_wait(self):
        self.plant('door-wait')

    def test_status_before_the_sound(self):
        self.plant('status-first')

    def test_reversal_without_its_sound(self):
        self.plant('reversal-silent')


if __name__ == '__main__':
    unittest.main()
