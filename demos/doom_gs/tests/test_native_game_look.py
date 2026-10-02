"""Milestone 10, wave 3: part look's checkpoint (docs/GAME.md 2.4, 3.5;
docs/game-parts/look.md; the harness is tools/native/gparts/look.py),
lean (the owner's rules of 2026-10-02).

  Build       the part's image builds with no warning; no far access of
              the part's own (every record through the object API); its
              bytes within its budget; args.json declares the part's
              entries
  Checkpoint  routine mode on the part's image, the $A5 machine, f121: by
              default one captured call of each entry and the synthetic
              cases that its planted bugs need (behindFast at an edge and
              one unit beyond, a shadow target, a thing on the radius
              attack's spot); with DOOM_GS_FULL=1 the whole lean
              checkpoint (at most 40 calls a routine, chosen by branch,
              and every synthetic case): the canonical state equal to
              ref816's, the declared outputs, no stray write; a call that
              reaches an unbuilt action is a stop check with its variant
              (the action removed on both sides) compared whole
  Plants      each planted bug (behindFast's 90 degree edge on the other
              side, the shadow's P_Random shift, the radius damage's
              distance not clamped at 0), made in a scratch copy of the
              part's sources, fails its check: by default on the cases
              above, with DOOM_GS_FULL=1 on every case of its entry

The full checkpoint and report.json: `python3 tools/native/gparts/look.py
--check --plants`.

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (`make -s -C src/native -f game.mk
shared skel ROOT=$PWD`, the parallel runner's prebuild; never made here),
milestone 9's level bases (`python3 tools/native/level_check.py --setup`),
ref816 and a2vm (`make -C tools/ref816`, `make -C tools/a2vm`), the part's
call logs and captures (`python3 tools/native/gparts/look.py --log
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
SRC = ROOT / 'src' / 'native' / 'game' / 'look'
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
    import look as L
    try:
        chosen = L.chosen_paths()
        return {e for e, _ in chosen} >= {k for _, k, _ in L.DIRECT} | \
            {k for _, k, _ in L.VIA_CALLFN}
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
    'captures (python3 tools/native/gparts/look.py --log --capture)')


def setUpModule() -> None:
    try:
        import look as L
        L.use_cases()
    except Exception:                   # (the classes skip by name)
        pass


class Sources(unittest.TestCase):
    """What needs no build/: the part's own sources."""

    def test_no_far_access(self):
        for p in sorted(SRC.glob('*.s')):
            for n, line in enumerate(p.read_text().splitlines(), 1):
                code = line.split(';', 1)[0]
                self.assertIsNone(
                    re.search(r'\b(far_get|far_put|g_get|g_put)\b', code),
                    '%s:%d: a far access outside the object API' % (p.name,
                                                                    n))

    def test_args(self):
        d = json.loads((SRC / 'args.json').read_text())
        self.assertEqual(d['format'], 'game-args 1')
        sys.path.insert(0, str(ROOT / 'tools'))
        from native import glayout as GL
        part = next(x for x in GL.PARTS if x['name'] == 'look')
        for key in d['entries']:
            self.assertIn(key, part['routines'])
        mk = (SRC / 'part.mk').read_text()
        for key in part['routines']:
            self.assertIn(GL.native_names()[key], mk, key)


@needs_shared
class Build(unittest.TestCase):

    def test_build_and_sizes(self):
        import look as L
        b = L.load(L.build())           # (raises on a warning)
        sz = L.sizes(b)
        # request 2 applied in wave 3's integration: distanceAT jumps to
        # the core's aproxdist (math-g.o), no stand-in
        self.assertEqual(sz['standin_bytes'], 0)
        self.assertLessEqual(sz['own_bytes'], L.BUDGET * 1.1,
                             'more than 10%% over the budget: %r' % (sz,))


def default_jobs():
    """One captured call of each entry, the edge pair of behindFast at a
    diagonal, a shadow target, the radius attack with a thing on its
    spot."""
    import look as L
    js = L.plan(True)
    out, seen = [], set()
    for j in js:
        e = L.job_entry(j)
        if j[0] == 'case' and e not in seen:
            seen.add(e)
            out.append(j)
    out += [j for j in js if j[0] == 'bf' and j[2] == 1]
    out += [j for j in js if j[0] == 'shadow'][:1]
    out += [j for j in js if j[0] == 'radius' and j[3]][:1]
    return out


@needs_all
class Checkpoint(unittest.TestCase):

    def test_routine_mode(self):
        import look as L
        L.build()
        js = L.plan(True) if FULL else default_jobs()
        res = L.run_jobs(js, L.OUT, 2)
        bad = [r for r in res if not r.get('ok')]
        self.assertFalse(bad, json.dumps(bad[:3], default=str)[:3000])
        entries = {r.get('entry') for r in res}
        import look as L2
        self.assertTrue({L2.BF, L2.LFP, L2.LOOK, L2.FACE, L2.RADIUS,
                         L2.MELEE, L2.MISSILE} <= entries, entries)
        self.assertEqual(sum(r.get('strays') or 0 for r in res), 0)


@needs_all
class Plants(unittest.TestCase):
    """Each planted bug fails its check (GAME.md 2.4 row look; lean: the
    three most likely mistakes)."""

    def plant(self, name: str, kind: str):
        import look as L
        import tempfile
        bugs, entries = L.PLANTS[name]
        js = [j for j in (L.plan(True, entries) if FULL else
                          default_jobs()) if j[0] in (kind, 'case') and
              L.job_entry(j) in entries]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-look-test-',
                                    dir=str(BUILD)))
        try:
            obj = L.build(tmp / 'game', bugs)
            res = L.run_jobs(js, obj, 2)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        self.assertTrue(res)
        self.assertTrue([r for r in res if not r.get('ok')],
                        '%s: not caught on %d runs' % (name, len(res)))

    def test_bf_edge(self):
        self.plant('bf-edge', 'bf')

    def test_shadow_shift(self):
        self.plant('shadow-shift', 'shadow')

    def test_no_clamp(self):
        self.plant('no-clamp', 'radius')


if __name__ == '__main__':
    unittest.main()
