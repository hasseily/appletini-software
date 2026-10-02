"""Milestone 10, wave 6: part chase's checkpoint (docs/GAME.md 2.4, 3.5;
docs/game-parts/chase.md; the harness is tools/native/gparts/chase.py),
lean (the owner's rules of 2026-10-02).

  Sources     no far access of the part's own (every record through the
              object API); args.json declares the part's entries, part.mk
              names them
  Build       the part's image builds with no warning; its bytes (less the
              stand-in of request 1) within its budget
  Checkpoint  routine mode on the part's image, the $A5 machine, f121: by
              default the first captured call of each entry (three of
              A_Chase), A_CyberAttack and A_BruisAttack from a captured
              A_TroopAttack, the paging case (a troopshot that hits a
              monster: P_DamageMobj under checkMissile, across the
              integrator's placement) and A_BossDeath on E1M8 with the last
              baron; with DOOM_GS_FULL=1 the whole lean checkpoint (at most
              40 calls a routine, chosen by branch, and every synthetic
              case): the canonical state equal to ref816's, no stray write
  Plants      each planted bug (movecount decremented after the move, the
              attack's P_Random order, A_BossDeath's floor type), made in a
              scratch copy of the part's sources, fails its check: by
              default on the cases above, with DOOM_GS_FULL=1 on every case
              of its entry

The full checkpoint and report.json: `python3 tools/native/gparts/chase.py
--check --plants`.

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (`make -s -C src/native -f game.mk
shared skel ROOT=$PWD`, the parallel runner's prebuild; never made here),
milestone 9's level bases (`python3 tools/native/level_check.py --setup`),
ref816 and a2vm (`make -C tools/ref816`, `make -C tools/a2vm`), the part's
call logs and captures (`python3 tools/native/gparts/chase.py --log
--capture`).
"""

import json
import os
import re
import shutil
import sys
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

ROOT = support.ROOT
BUILD = ROOT / 'build'
GAME = BUILD / 'native' / 'game'
SHARED = GAME / 'shared'
SRC = ROOT / 'src' / 'native' / 'game' / 'chase'
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

FULL = os.environ.get('DOOM_GS_FULL') == '1'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
PREBUILD = ('make -s -C src/native -f game.mk shared skel ROOT=$PWD (the '
            'parallel runner\'s prebuild)')


def shared_ok() -> bool:
    """The shared outputs, and newer than the layouts that make them."""
    inc = SHARED / 'gen' / 'ggame.inc'
    if not (HAVE_CC65 and inc.exists() and
            (SHARED / 'native-game-1.json').exists() and
            (SHARED / 'gen' / 'gplace.inc').exists() and
            (BUILD / 'native' / 'levels' / 'store' / 'store.json').exists()):
        return False
    t = inc.stat().st_mtime
    return all(t >= (ROOT / 'tools' / 'native' / f).stat().st_mtime
               for f in ('glayout.py', 'llayout.py'))


def machines_ok() -> bool:
    from native import grun as G
    from ref816 import title
    return Path(G.A2VM).exists() and Path(title.MACHINE).exists()


def bases_ok() -> bool:
    from native import gameroutine as GR
    return GR.have_bases()


def captures_ok() -> bool:
    import chase as C
    try:
        got = {k for k, _, _ in C.chosen()}
        return got >= {k for _, k, _ in C.WANT} | {C.LOOK}
    except Exception:                   # (no log: skipped by name below)
        return False


needs_shared = unittest.skipUnless(
    shared_ok(), 'needs the shared outputs, newer than tools/native/'
    'glayout.py and llayout.py: ' + PREBUILD + ', and milestone 9\'s store '
    '(python3 tools/native/wadconv.py --store)')
needs_all = unittest.skipUnless(
    shared_ok() and machines_ok() and bases_ok() and captures_ok(),
    'needs the shared outputs (' + PREBUILD + '), ref816 and a2vm (make -C '
    'tools/ref816; make -C tools/a2vm), milestone 9\'s level bases (python3 '
    'tools/native/level_check.py --setup) and the part\'s call logs and '
    'captures (python3 tools/native/gparts/chase.py --log --capture)')


def setUpModule() -> None:
    try:
        import chase as C
        C.use_cases()
    except Exception:                   # (the classes skip by name)
        pass


class Sources(unittest.TestCase):
    """What needs no build/: the part's own sources."""

    def test_no_far_access(self):
        for p in sorted(SRC.glob('*.s')) + sorted(SRC.glob('*.inc')):
            for n, line in enumerate(p.read_text().splitlines(), 1):
                code = line.split(';', 1)[0]
                self.assertIsNone(
                    re.search(r'\b(far_get|far_put|g_get|g_put)\b', code),
                    '%s:%d: a far access outside the object API' % (p.name,
                                                                    n))

    def test_args(self):
        d = json.loads((SRC / 'args.json').read_text())
        self.assertEqual(d['format'], 'game-args 1')
        from native import glayout as GL
        part = next(x for x in GL.PARTS if x['name'] == 'chase')
        self.assertEqual(set(d['entries']), set(part['routines']))
        mk = (SRC / 'part.mk').read_text()
        for key in part['routines'] + part['helpers']:
            self.assertIn(GL.native_names()[key], mk, key)


@needs_shared
class Build(unittest.TestCase):

    def test_build_and_sizes(self):
        import chase as C
        b = C.load(C.build())           # (raises on a warning)
        sz = C.sizes(b)
        self.assertGreater(sz['standin_bytes'], 0)
        self.assertLessEqual(sz['own_bytes'], C.BUDGET * 1.1,
                             'more than 10%% over the budget: %r' % (sz,))


def default_jobs():
    """The first captured call of each entry (A_Chase's first three), the
    two attacks made from an A_TroopAttack, the paging case, A_BossDeath
    with the last baron."""
    import chase as C
    js = C.plan(True)
    out, seen = [], {}
    for j in js:
        if j[0] != 'case':
            continue
        n = seen.get(j[2], 0)
        if n < (3 if j[2] == C.CHASE else 1):
            seen[j[2]] = n + 1
            out.append(j)
    done = set()
    for j in js:
        if j[0] == 'as' and j[2] not in done:
            done.add(j[2])
            out.append(j)
    out += [j for j in js if j[0] == 'paging']
    out += [j for j in js if j[0] == 'boss' and j[2] == 'last baron']
    return out


@needs_all
class Checkpoint(unittest.TestCase):

    def test_routine_mode(self):
        import chase as C
        C.build()
        js = C.plan(True) if FULL else default_jobs()
        res = C.run_jobs(js, C.OUT, 2)
        bad = [r for r in res if not r.get('ok')]
        self.assertFalse(bad, json.dumps(bad[:3], default=str)[:3000])
        entries = {r.get('entry') for r in res}
        self.assertTrue(set(C.ACTIONS) <= entries, entries)
        self.assertEqual(sum(r.get('strays') or 0 for r in res), 0)
        paging = [r for r in res if r.get('path') == 'paging']
        self.assertTrue(paging and all(r.get('fc_loads') for r in paging))


@needs_all
class Plants(unittest.TestCase):
    """Each planted bug fails its check (GAME.md 2.4 row chase)."""

    def plant(self, name: str):
        import chase as C
        import tempfile
        bugs, entries = C.PLANTS[name]
        js = [j for j in (C.plan(True, entries) if FULL else
                          default_jobs()) if C.job_entry(j) in entries]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-chase-test-',
                                    dir=str(BUILD)))
        try:
            obj = C.build(tmp / 'game', bugs)
            res = C.run_jobs(js, obj, 2)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        self.assertTrue(res)
        self.assertTrue([r for r in res if not r.get('ok')],
                        '%s: not caught on %d runs' % (name, len(res)))

    def test_movecount_after(self):
        self.plant('movecount-after')

    def test_random_order(self):
        self.plant('random-order')

    def test_boss_floor_type(self):
        self.plant('boss-floor-type')


if __name__ == '__main__':
    unittest.main()
