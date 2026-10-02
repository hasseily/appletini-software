"""Part evworld of milestone 10 (docs/GAME.md 2.4 row evworld, wave 3;
docs/game-parts/evworld.md): the doors and the plats a line starts
(EV_DoDoor, newDoor, EV_VerticalDoor, EV_DoPlat and LSTAB's lnDoor, lnPlat,
lnVDoor), natively (src/native/game/evworld/).

What it checks (tools/native/gparts/evworld.py does the work), in the lean
form the owner asked for on 2026-10-02 (under 60 s in the default suite):

  * the part builds within its budget, every entry of its args.json is a
    label of the image with a group, and it makes no far access of a cached
    kind's bank (gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5) on a sample: the first
    captured call of each entry and every SAMPLE-th synthetic call, from
    the poisoned machine $A5 under f121, equal to ref816's with the
    exclusions R1-R6 only, the declared outputs and the sound events equal,
    no stray write;
  * the three planted bugs, each built from a scratch copy of the part's
    sources in a temporary directory and failing its named check
    (`evworld.py --plants`);
  * with DOOM_GS_FULL=1: every chosen captured call and every synthetic
    call under f121 and fastpath (`evworld.py --check`).

It skips with the reason when build/ lacks upstream's sources, ref816,
a2vm, the shared outputs (`make -s -C src/native -f game.mk shared
ROOT=$PWD`; the survey: `python3 tools/native/gamecap.py --survey`), the
level bases (`python3 tools/native/level_check.py --setup`) or the part's
own captures (`python3 tools/native/gparts/evworld.py --capture`, then
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

import evworld as E  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'
SYN_SAMPLE = 8


def setUpModule():
    """The part's own case directory: gamecap's CASES is one global, which
    the harness sets when imported and another part's harness may change
    in the same process (unittest discover runs every module in one)."""
    E.GC.CASES = E.CASES


def why_skip():
    why = E.missing()
    if why:
        return why
    for key in E.ENTRIES:
        if not E.captured(key):
            return ('no captures of %s (python3 tools/native/gparts/'
                    'evworld.py --capture)' % key)
    for name in E.synthetic_names():
        if not (E.SYN / (name + '.json.z')).exists():
            return ('no synthetic calls %s (python3 tools/native/gparts/'
                    'evworld.py --synthetic)' % name)
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
        problems = E.GR.grep_check(E.SRC, ['game/evworld/evworld.s'])
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
        """LSTAB's door and plat entries are this part's handlers."""
        built()
        text = (E.OUT / 'gen' / 'gdisp.inc').read_text()
        for name in ('lnDoor', 'lnPlat', 'lnVDoor'):
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

    def test_sample(self):
        """The first captured call of each entry and every SYN_SAMPLE-th
        synthetic call, $A5 under f121."""
        built()
        one = dict(fills=(0xA5,), profiles=('f121',))
        jobs = []
        for key in E.ENTRIES:
            jobs.append(('case', [(key, str(E.captured(key)[0]))],
                         str(E.OUT), (0xA5,), ('f121',)))
        jobs += E.check_jobs(captured_=False, sample=SYN_SAMPLE, **one)
        res = run_checked(self, jobs)
        self.assertEqual({r['entry'] for r in res} & set(E.ENTRIES),
                         set(E.ENTRIES))

    @unittest.skipUnless(FULL, 'the whole checkpoint: DOOM_GS_FULL=1')
    def test_all(self):
        """Every chosen captured call and every synthetic call, $A5 under
        f121 and fastpath (`evworld.py --check`)."""
        built()
        res = run_checked(self, E.check_jobs())
        paths = {r['path'] for r in res}
        for want in ('new-1', 'turn-', 'locked-nokey', 'one-sided-player',
                     'one-sided-monster', 'plat-type0-1-made',
                     'plat-type1-1-made', ':0-made'):
            self.assertTrue(any(want in p for p in paths), want)


@unittest.skipIf(SKIP, SKIP or '')
class Planted(unittest.TestCase):
    """Each planted bug fails its named check (GAME.md 2.4)."""

    def plant(self, name):
        built()
        r = E.plants([name])[name]
        self.assertTrue(r['caught'], r)
        self.assertGreater(r['runs'], 0)

    def test_top_without_4(self):
        self.plant('top-without-4')

    def test_low_other_finder(self):
        self.plant('low-other-finder')

    def test_plat_busy_ignored(self):
        self.plant('plat-busy-ignored')


if __name__ == '__main__':
    unittest.main()
