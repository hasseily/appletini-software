"""Part teleport of milestone 10 (docs/GAME.md 2.4 row teleport, wave 4;
docs/game-parts/teleport.md): the teleporters (EV_Teleport, P_TeleportMove,
stompThing = PIT_StompThing, LSTAB's lnTele, ITTAB's stompThing), natively
(src/native/game/teleport/).

What it checks (tools/native/gparts/teleport.py does the work), in the lean
form the owner asked for on 2026-10-02 (under 60 s in the default suite):

  * the part builds within its budget, every routine of its args.json is a
    label of the image with a group, LSTAB's lnTele and ITTAB's stompThing
    are this part's, and it makes no far access of a cached kind's bank
    (gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5) on a sample: the synthetic
    sequences of the first teleport line of E1M5 (a monster moved, a
    second one past a thing that is not shootable, the player's telefrag,
    a monster blocked by the player, the back side), EV_Teleport alone (a
    missile, a tag with no destination, the player) and P_TeleportMove with
    boss set followed by the player's telefrag of a dropper (request R4:
    the core's gp_secnodes leaves tmx, tmy), from the poisoned machine $A5 under f121, equal to
    ref816's with the exclusions R1-R7 only, the declared outputs and the
    teleport's sound events equal, no stray write;
  * times20 on 10,000 inputs (100,000 with DOOM_GS_FULL=1) against
    upstream's on ref816's machine (mathref) and against 20 v mod 2^32;
  * the three planted bugs, each built from a scratch copy of the part's
    sources in a temporary directory and failing its named check;
  * with DOOM_GS_FULL=1: every synthetic call under f121 and fastpath
    (`teleport.py --check`).

It skips with the reason when build/ lacks upstream's sources, ref816,
a2vm, the shared outputs (`make -s -C src/native -f game.mk shared
ROOT=$PWD`; the survey: `python3 tools/native/gamecap.py --survey`), the
level bases (`python3 tools/native/level_check.py --setup`), the math
reference (`make -C tools/native`) or the part's own bases and calls
(`python3 tools/native/gparts/teleport.py --capture`, then `--synthetic`).
It never rebuilds a shared output.
"""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

import teleport as T  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'


def setUpModule():
    """The part's own case directory: gamecap's CASES is one global, which
    the harness sets when imported and another part's harness may change
    in the same process (unittest discover runs every module in one)."""
    T.GC.CASES = T.CASES


def why_skip():
    why = T.missing()
    if why:
        return why
    import sight
    if not sight.MATHREF.exists():
        return 'no mathref (make -C tools/native)'
    if not T.full_bases():
        return ('no bases (python3 tools/native/gparts/teleport.py '
                '--capture)')
    if not T.synthetic_names():
        return ('no synthetic calls (python3 tools/native/gparts/'
                'teleport.py --synthetic)')
    return None


SKIP = why_skip()
_BUILT = []


def built():
    if not _BUILT:
        _BUILT.append(T.build())
    return _BUILT[0]


def sample(rec):
    """The default suite's sample: E1M5's first line, EV_Teleport alone,
    one P_TeleportMove sequence and the player's crossing after it."""
    if 'E1M5 line 787' not in rec['note']:
        return False
    if rec['key'] == T.MOVE or 'onto monsters' in rec['note']:
        return '+30, +0' in rec['note']
    return True


def run_checked(test, recs, profiles=(T.PROFILES[0],)):
    res = T.run_jobs(T.check_jobs(recs, profiles=profiles), workers=2)
    test.assertTrue(res)
    bad = [r for r in res if not r.get('ok')]
    test.assertEqual(bad, [], json.dumps(bad[:3])[:3000])
    test.assertEqual(sum(r.get('stray') or 0 for r in res), 0)
    return res


@unittest.skipIf(SKIP, SKIP or '')
class Build(unittest.TestCase):

    def test_builds_within_budget(self):
        built()
        sz = T.sizes()
        self.assertLessEqual(sz['bytes'], sz['budget'])
        for name in T.LABELS:
            self.assertIn(name, sz['routines'])

    def test_no_far_access_of_a_cached_kind(self):
        problems = T.GR.grep_check(T.SRC, ['game/teleport/teleport.s'])
        self.assertEqual(problems, [])

    def test_args(self):
        built()
        nat = T.SF.Native(T.OUT)
        spec = T.args()
        self.assertEqual(set(spec), set(T.KEYS))
        for key, e in spec.items():
            self.assertIn(e['native'], nat.b.labels, key)
            nat.group(e['native'])

    def test_dispatch_entries(self):
        """LSTAB's lnTele and ITTAB's stompThing are this part's."""
        built()
        text = (T.OUT / 'gen' / 'gdisp.inc').read_text()
        for name in ('p_switch65.s:lnTele', 'p_map65.s:stompThing'):
            row = [x for x in text.splitlines()
                   if x.rstrip().endswith(name)]
            self.assertEqual(len(row), 1, name)
            self.assertIn('<%s' % name.split(':')[1], row[0])


@unittest.skipIf(SKIP, SKIP or '')
class Checkpoint(unittest.TestCase):

    def test_sample(self):
        built()
        recs = T.records(select=sample)
        keys = {r['key'] for r in recs}
        self.assertEqual(keys, set(T.KEYS))
        res = run_checked(self, recs)
        paths = {r['path'] for r in res}
        for p in ('monster teleported', 'monster blocked',
                  'player back side', 'monster missile',
                  'player no destination'):
            self.assertIn(p, paths)
        self.assertTrue(any('telefrag' in p and 'drop' in p for p in paths))

    @unittest.skipUnless(FULL, 'DOOM_GS_FULL=1: every synthetic call, both '
                         'profiles')
    def test_all(self):
        built()
        recs = T.records()
        self.assertGreaterEqual(len(recs), 60)
        run_checked(self, recs, T.PROFILES)


@unittest.skipIf(SKIP, SKIP or '')
class Arithmetic(unittest.TestCase):

    def test_times20(self):
        built()
        r = T.random_check(100_000 if FULL else 10_000)
        self.assertEqual(r['different'], 0, r['first'])
        self.assertEqual(r['compared'], r['inputs'])
        self.assertEqual(r['upstream_is_20v'], r['inputs'])


@unittest.skipIf(SKIP, SKIP or '')
class Plants(unittest.TestCase):

    def test_planted_bugs_are_caught(self):
        built()
        got = T.plants()
        self.assertEqual(set(got), set(T.PLANTS))
        for name, r in got.items():
            self.assertTrue(r['runs'], name)
            self.assertTrue(r['caught'], name)


if __name__ == '__main__':
    unittest.main()
