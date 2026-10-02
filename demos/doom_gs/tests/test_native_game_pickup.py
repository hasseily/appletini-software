"""Milestone 10, wave 2: part pickup's checkpoint (docs/GAME.md 2.4, 3.5,
3.7; docs/game-parts/pickup.md; the harness is
tools/native/gparts/pickup.py).

  Build       the part's image builds with no warning; no far access of
              the part's own; ggame.inc's symbol numbers are the game
              manifest's, and the player's message is the bridge's "ref"
              of a symbol (tag 1), as the sources write it
  Checkpoint  routine mode on the part's image, both fills ($A5, $5A),
              both profiles (f121, fastpath), every SAMPLE-th case of each
              group: the captured P_TouchSpecialThing calls (demo3, demo1,
              demo2, the tour), the captured C_Responder calls that
              complete a cheat (the tour, newgame; the others checked to
              change no canonical state), the synthetic touches (each E1
              item type at each skill, three player states), every cheat
              on captured states, P_GivePower of each power, random player
              states and reaches: the canonical state equal to ref816's,
              every declared output equal, no stray write, the native-only
              globals consistent, the renderer's shadow flag
  Plants      each planted bug of the part's row, made in a scratch copy of
              its sources, fails its named check (the synthetic touches of
              its items)

The full checkpoint (every case) is `python3 tools/native/gparts/
pickup.py --check --plants` (report.json).

By default (tests/README.md) the module runs fewer cases, every group,
entry and planted bug still reached: every SAMPLE_DEF-th case of the
captured touches, the synthetic touches and the random states; every
CHEAT_DEF-th captured C_Responder call (every one that completes a cheat);
each cheat once on a captured state (the states and bases in turn);
P_GivePower of each power once (the player states in turn); each plant on
every PLANT_DEF-th touch of its check. DOOM_GS_FULL=1 runs all of what it
ran before: every SAMPLE-th case of each group (every captured C_Responder
call and P_GivePower case), each plant on every touch of its check.

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (`make -s -C src/native -f game.mk
shared skel ROOT=$PWD`, the parallel runner's prebuild; never made here),
the survey (`python3 tools/native/gamecap.py --survey`), milestone 9's
level bases (`python3 tools/native/level_check.py --setup`), the release
and the WAD (`python3 tools/fetch_upstream.py`), ref816 and a2vm (`make -C
tools/ref816`, `make -C tools/a2vm`), the part's captures (`python3
tools/native/gparts/pickup.py --capture`).
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

ROOT = support.ROOT
BUILD = ROOT / 'build'
GAME = BUILD / 'native' / 'game'
SHARED = GAME / 'shared'
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
PREBUILD = ('make -s -C src/native -f game.mk shared skel ROOT=$PWD (the '
            'parallel runner\'s prebuild)')
FULL = os.environ.get('DOOM_GS_FULL') == '1'
SAMPLE = 6
SAMPLE_DEF = 60     # by default: the captured and synthetic touches, random
CHEAT_DEF = 6       # by default: the captured C_Responder calls
PLANT_DEF = 10      # by default: a plant's touches


def shared_ok() -> bool:
    """The shared outputs, newer than the layouts that make them, the
    release and the WAD (lgame.inc's tables read them)."""
    inc = SHARED / 'gen' / 'ggame.inc'
    if not (HAVE_CC65 and inc.exists() and
            (SHARED / 'native-game-1.json').exists() and
            (SHARED / 'gen' / 'gplace.inc').exists() and
            (BUILD / 'native' / 'levels' / 'store' / 'store.json').exists()
            and support.RELEASE_IMAGE.exists() and
            (BUILD / 'linkmap.json').exists()):
        return False
    t = inc.stat().st_mtime
    return all(t >= (ROOT / 'tools' / 'native' / f).stat().st_mtime
               for f in ('glayout.py', 'llayout.py'))


def machines_ok() -> bool:
    from native import grun as G
    from ref816 import title
    return Path(G.A2VM).exists() and Path(title.MACHINE).exists()


def survey_ok() -> bool:
    return all((SHARED / 'survey' / (r + '.json.z')).exists()
               for r in ('demo3', 'demo1', 'demo2', 'tour', 'newgame'))


def bases_ok() -> bool:
    from native import gameroutine as GR
    return GR.have_bases()


def captures_ok() -> bool:
    import pickup as P
    return P.have_captures()


def wad_ok() -> bool:
    from ref816 import lumps
    return lumps.WAD.exists()


needs_shared = unittest.skipUnless(
    shared_ok(), 'needs the shared outputs, newer than tools/native/'
    'glayout.py and llayout.py: ' + PREBUILD + ', milestone 9\'s store '
    '(python3 tools/native/wadconv.py --store), the release and the link '
    'map (python3 tools/fetch_upstream.py; python3 tools/v816/imgmatch.py)')
needs_all = unittest.skipUnless(
    shared_ok() and machines_ok() and survey_ok() and bases_ok() and
    wad_ok() and captures_ok(),
    'needs the shared outputs (' + PREBUILD + '), ref816 and a2vm (make -C '
    'tools/ref816; make -C tools/a2vm), the survey (python3 tools/native/'
    'gamecap.py --survey), milestone 9\'s level bases (python3 tools/native/'
    'level_check.py --setup), DOOM1.WAD (python3 tools/fetch_upstream.py) '
    'and the part\'s captures (python3 tools/native/gparts/pickup.py '
    '--capture)')


@needs_shared
class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pickup as P
        cls.tmp = Path(tempfile.mkdtemp(prefix='tmp-pickup-test-',
                                        dir=str(BUILD)))
        cls.obj = P.build(cls.tmp / 'game')
        cls.b = P.load(cls.obj)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_the_image_builds(self):
        import pickup as P
        sz = P.sizes(self.b)
        for m in P.MODULES:
            self.assertGreater(sz['modules'][m], 0, m)
        for name in ('P_TouchSpecialThing', 'P_GivePower', 'C_Responder',
                     'power', 'm_cheat_giveAmmo', 'p_inter_giveAmmo',
                     'giveWeapon', 'givePower', 'giveBody', 'pkBackpack'):
            self.assertIn(name, self.b.labels)
        # GAME.md 4.7: more than 10% over the budget is a request
        self.assertLessEqual(sz['part_bytes'], P.BUDGET * 1.1)

    def test_no_far_access(self):
        """The part's sources call no g_get, g_put, far_get or far_put:
        every mobj through the object API."""
        from native import gameroutine as GR
        src = GR.SRC / 'game' / 'pickup'
        for p in sorted(src.glob('*.s')):
            words = [GR._code(x) for x in p.read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and w[0] in ('jsr', 'jmp')
                   and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], p.name)

    def test_the_messages_symbols(self):
        """ggame.inc's SYM_* (request P1, wave 2 as integrated) are the
        game manifest's symbol numbers, the messages' among them, and the
        manifest holds the player's message as a reference to a symbol
        with tag 1 (what P_TouchSpecialThing and ch_msg write)."""
        from native import glayout as GL, llayout as LL
        syms = LL.symbol_list()
        text = (self.obj / 'gen' / 'ggame.inc').read_text()
        got = {}
        for line in text.splitlines():
            f = line.split(';')[0].split()
            if len(f) == 3 and f[0].startswith('SYM_') and f[1] == '=':
                got[f[0]] = int(f[2].replace('$', '0x'), 0)
        self.assertEqual(len(got), len(syms))
        for i, key in enumerate(syms):
            self.assertEqual(got[GL.symbol_name(key)], i, key)
        msgs = [k for k in syms if k.split(':')[0] in ('p_inter65.s',
                                                       'm_cheat65.s')
                and k.split(':')[1].startswith('msg')]
        self.assertEqual(len(msgs), 36)
        layout = dict((p, e) for p, e, _ in LL.player_layout())
        self.assertEqual(layout[('message',)]['codes'], [['symbol', None]])
        self.assertTrue(layout[('message',)]['offset'])
        self.assertIn('p_inter65.s:msgArmor', syms)


@needs_all
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pickup as P
        if FULL:
            cls.rep = P.check(jobs=2, sample=SAMPLE, rebuild=True,
                              say=lambda *a: None)
            return
        # pickup.check() on the default sample
        P.build()
        js, _ = P.plan(P.OUT, P.FILLS, P.PROFILES, SAMPLE_DEF)
        js = [j for j in js if j[0] not in ('cheats', 'synth-cheats',
                                            'givepower')]
        # every captured call that completes a cheat (pickup.cheat_of),
        # every CHEAT_DEF-th of the others
        cheats = P.plan(P.OUT, P.FILLS, P.PROFILES, 1, ('cheats',))[0]
        js += support.every(cheats, CHEAT_DEF, keep=lambda j: P.cheat_of(
            P.GC.load_case(Path(j[1]))) is not None)
        o, rb = str(P.OUT), P.responder_bases()
        states = [state for state, _ in P.SYNTH_CHEAT_STATES]
        for number in range(len(P.CHEATS)):
            js.append(('synth-cheats', (str(rb[number % len(rb)]), number,
                                        states[number % len(states)]), o,
                       P.FILLS, P.PROFILES))
        bases = P.touch_bases()
        variants = ('captured', 'needy', 'stocked')
        for power in range(6):
            js.append(('givepower', (str(bases[power % len(bases)]), power,
                                     variants[power % 3]), o, P.FILLS,
                       P.PROFILES))
        res = P.run_jobs(js, 2)
        cls.rep = {'entries': P.summarize(res),
                   'strays': sum(r.get('strays') or 0 for r in res)}

    def test_no_failure_and_no_stray_write(self):
        bad = {k: e['first_failures'] for k, e in self.rep['entries'].items()
               if e['failures']}
        self.assertEqual(bad, {})
        self.assertEqual(self.rep['strays'], 0)

    def test_every_entry_and_group_ran(self):
        e = self.rep['entries']
        for key in ('p_inter65.s:P_TouchSpecialThing',
                    'p_inter65.s:P_GivePower', 'm_cheat65.s:C_Responder'):
            with self.subTest(key):
                self.assertGreater(e[key]['runs'], 0)
        groups = {g for x in e.values() for g in x['groups']}
        for g in ('captured', 'cheats', 'touch', 'synth-cheats',
                  'givepower', 'random'):
            self.assertIn(g, groups)

    def test_both_fills_and_profiles(self):
        e = self.rep['entries']['p_inter65.s:P_TouchSpecialThing']
        for prof in ('f121', 'fastpath'):
            self.assertIsNotNone(e['clock'][prof]['median'])
        self.assertEqual(e['runs'] % 4, 0)

    def test_the_paths(self):
        """The captured touches and the synthetic ones take the pickups'
        cases: taken and not taken, and out of reach."""
        paths = self.rep['entries']['p_inter65.s:P_TouchSpecialThing'][
            'paths']
        self.assertTrue(any(p.endswith(' taken') for p in paths))
        self.assertTrue(any('not taken' in p for p in paths))
        cheats = self.rep['entries']['m_cheat65.s:C_Responder']['paths']
        for c in ('cheatGod', 'cheatClev'):
            self.assertIn(c, cheats)


def run_plant(name):
    """pickup.run_plant on every PLANT_DEF-th touch of its check (all of
    them with DOOM_GS_FULL=1)."""
    import pickup as P
    if FULL:
        return P.run_plant(name)
    p = P.PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-pickup-plant-', dir=str(BUILD)))
    try:
        obj = P.build(tmp / 'game', p['bugs'])
        res = P.run_jobs(P.plant_jobs(p['check'], obj)[::PLANT_DEF], 2)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        P._BUILDS.clear()
    return {'check': p['check'], 'runs': len(res),
            'caught': any(not r.get('ok') for r in res)}


@needs_all
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        import pickup as P
        for name in P.PLANTS:
            with self.subTest(name):
                r = run_plant(name)
                self.assertGreater(r['runs'], 0)
                self.assertTrue(r['caught'], '%s was not caught by %s' % (
                    name, r['check']))


if __name__ == '__main__':
    unittest.main()
