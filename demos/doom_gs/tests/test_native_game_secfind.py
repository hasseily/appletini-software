"""Part secfind of milestone 10 (docs/GAME.md 2.4 row secfind, wave 1;
docs/game-parts/secfind.md): the sector finders, the tag search, the
animated textures and flats, the switch timers, the scrolling walls and
the light thinkers, natively (src/native/game/secfind/).

What it checks (tools/native/gparts/secfind.py does the work):

  * the part builds without a warning, within its budget; the constants
    it takes from ggame.inc equal what they name (llayout's GTAB place of
    animated_texture_basepic, p_lights65.s's GLOWSPEED and STROBEBRIGHT),
    and its notags table equals p_spec65.s's in the release's memory;
  * the checkpoint (routine mode, GAME.md 3.5) on a sample: every captured
    call of the small entries and every 10th of the others, from both
    poisoned machines under f121 and fastpath, equal to ref816's with the
    exclusions R1-R6 only, every declared output equal, no stray write;
    the synthetic calls: leveltime from 32,768 up, the switch timers ending
    on each place of a texture, the thinkers at their limits, and every
    20th of the finders', tags' and lights' calls on the nine maps (the
    whole of it: `secfind.py --check`, report.json);
  * mod3 on every 16-bit input against upstream's (and the 100,000 seeded
    random inputs with the edges among them);
  * the planted bugs of GAME.md 2.4, each built from a scratch copy of the
    part's sources in a temporary directory, each failing its named check.

It skips with the reason when build/ lacks upstream's sources, ref816,
a2vm, the shared outputs (`make -s -C src/native -f game.mk shared
ROOT=$PWD`; the survey: `python3 tools/native/gamecap.py --survey`), the
level bases (`python3 tools/native/level_check.py --setup`) or the part's
own captures (`python3 tools/native/gparts/secfind.py --log`, then
`--capture`, then `--synthetic`). It never rebuilds a shared output.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

import secfind as S  # noqa: E402


def setUpModule():
    """The part's own case directory: gamecap's CASES is one global, which
    the harness sets when imported and another part's harness may change
    in the same process (unittest discover runs every module in one)."""
    S.GC.CASES = S.CASES


SMALL = 40          # an entry with at most this many cases runs them all
SAMPLE = 10         # else every SAMPLE-th
SYN_SAMPLE = 20     # the synthetic finders', tags' and lights' calls


def why_skip():
    why = S.missing()
    if why:
        return why
    for key in S.ENTRIES:
        if key in ('p_switch65.s:lnLight', 'p_lights65.s:EV_LightTurnOn'):
            continue
        try:
            have = S.cases_of(key)
        except S.PartError as error:
            return '%s (python3 tools/native/gparts/secfind.py --log)' % error
        if not have:
            return ('no captures of %s (python3 tools/native/gparts/'
                    'secfind.py --log, then --capture)' % key)
    for name in S.synthetic_names():
        if not (S.SYN / (name + '.json.z')).exists():
            return ('no synthetic calls %s (python3 tools/native/gparts/'
                    'secfind.py --synthetic)' % name)
    return None


SKIP = why_skip()
_BUILT = []


def built():
    if not _BUILT:
        _BUILT.append(S.build())
    return _BUILT[0]


@unittest.skipIf(SKIP, SKIP or '')
class Build(unittest.TestCase):

    def test_builds_within_budget(self):
        built()
        sz = S.sizes()
        self.assertLessEqual(sz['bytes'], sz['budget'])
        self.assertEqual(sz['test_only'] > 0, True)
        for name in ('getNextSector', 'T_Glow', 'P_UpdateSpecials',
                     'EV_LightTurnOn', 'lnLight', 'around', 'mod3'):
            self.assertIn(name, sz['routines'])

    def test_constants(self):
        """The constants the part takes from ggame.inc (requests 3 and 5,
        applied at wave 1's integration: its stand-ins are gone) equal
        what they name: GTAB's animated_texture_basepic, p_lights65.s's
        GLOWSPEED and STROBEBRIGHT."""
        built()
        from native import llayout as LL
        from ref816 import calls as CL
        text = (S.OUT / 'gen' / 'ggame.inc').read_text()
        self.assertNotIn('SF_GT_BASEPIC',
                         (S.PART_SRC / 'secfind.s').read_text())

        def const(name):
            for line in text.splitlines():
                f = line.split(';')[0].split()
                if len(f) == 3 and f[0] == name and f[1] == '=':
                    return int(f[2].replace('$', '0x'), 0)
            self.fail('no %s' % name)
        self.assertEqual(const('GT_BASEPIC'), LL.GT['BASEPIC'][0])
        t = CL.Linkmap()
        self.assertEqual(const('UGLOWSPEED'),
                         t.address('p_lights65.s:GLOWSPEED'))
        self.assertEqual(const('USTROBEBRIGHT'),
                         t.address('p_lights65.s:STROBEBRIGHT'))
        text = (S.PART_SRC / 'secfind.s').read_text()
        # notags: the release's table (a case's memory)
        case = S.GC.load_case(S.cases_of('p_spec65.s:P_CheckTag')[0])
        at = t.address('p_spec65.s:notags')
        end = t.address('p_spec65.s:notags_end')
        words = [case.entry.u16(a) for a in range(at, end, 2)]
        self.assertEqual(tuple(words), S.NOTAGS)
        line = next(x for x in text.splitlines() if x.startswith('notags:'))
        native = tuple(int(v) for v in line.split('.byte')[1].split(','))
        self.assertEqual(native, S.NOTAGS)

    def test_args(self):
        built()
        nat = S.Native(S.OUT)
        spec = S.args()
        self.assertEqual(set(spec), set(S.ENTRIES))
        for key, e in spec.items():
            self.assertIn(e['native'], nat.b.labels, key)
            nat.group(e['native'])


@unittest.skipIf(SKIP, SKIP or '')
class Checkpoint(unittest.TestCase):

    def run_jobs(self, jobs):
        res = S.run_jobs(jobs, workers=2, progress=False)
        self.assertTrue(res)
        bad = [r for r in res if not r.get('ok')]
        self.assertEqual(bad, [], json.dumps(bad[:3])[:3000])
        self.assertEqual(sum(r.get('stray') or 0 for r in res), 0)
        return res

    def test_captured(self):
        """Every case of the small entries, every SAMPLE-th of the others,
        both fills, both profiles."""
        built()
        jobs = []
        for key in S.ENTRIES:
            if key == 'p_switch65.s:lnLight':
                continue
            n = len(S.cases_of(key))
            if n == 0:
                continue
            jobs += S.check_jobs(keys=(key,), sample=1 if n <= SMALL
                                 else SAMPLE, synthetic=False)
        res = self.run_jobs(jobs)
        runs = {r['entry'] for r in res}
        self.assertGreaterEqual(len(runs), 12)
        per: dict = {}
        for r in res:
            per[(r['entry'], r['case'])] = per.get((r['entry'], r['case']),
                                                   0) + 1
        self.assertEqual(set(per.values()), {4})     # 2 fills x 2 profiles

    def test_leveltime_and_buttons(self):
        """P_UpdateSpecials with leveltime 32,767 and up (NUKAGE's unsigned
        shift, the slime's arithmetic one) and the switch timers ending on
        each place of a texture, on E1M1 and E1M3."""
        built()
        jobs = S.check_jobs(keys=('p_spec65.s:P_UpdateSpecials',),
                            captured=False, names=('e1m1', 'e1m3'))
        res = self.run_jobs(jobs)
        notes = {r['case'].split(': ')[1] for r in res}
        self.assertIn('leveltime 32768', notes)
        self.assertTrue(any(n.startswith('buttons') for n in notes))
        paths = {r['path'] for r in res}
        self.assertIn('button-end', ' '.join(paths))
        self.assertIn('leveltime-bit15', ' '.join(paths))

    def test_thinkers_at_their_limits(self):
        built()
        res = self.run_jobs(S.check_jobs(keys=tuple(S.THINKERS),
                                         captured=False,
                                         names=('thinkers',)))
        paths = {r['path'] for r in res}
        self.assertIn('down-turn-at', paths)
        self.assertIn('up-turn-at', paths)

    def test_nine_maps(self):
        """Every SYN_SAMPLE-th synthetic call of the finders, the tags and
        the lights on each of the nine maps."""
        built()
        keys = S.FINDERS + ('p_spec65.s:P_FindSectorFromLineTag',
                            'p_spec65.s:P_CheckTag',
                            'p_lights65.s:EV_LightTurnOn',
                            'p_switch65.s:lnLight')
        jobs = S.check_jobs(keys=keys, captured=False, sample=SYN_SAMPLE,
                            names=['e1m%d' % m for m in range(1, 10)])
        res = self.run_jobs(jobs)
        self.assertEqual(len({r['case'].split(':')[0] for r in res}), 9)
        self.assertEqual({r['entry'] for r in res}, set(keys))


@unittest.skipIf(SKIP, SKIP or '')
class Mod3(unittest.TestCase):

    def test_every_input(self):
        built()
        r = S.mod3_check()
        self.assertTrue(r['upstream_is_mod3'])
        self.assertEqual(r['different'], 0, r['first'])
        self.assertEqual(r['random_different'], 0)
        self.assertGreaterEqual(r['random_draws'], 100_000)


@unittest.skipIf(SKIP, SKIP or '')
class Planted(unittest.TestCase):
    """Each planted bug fails its named check (GAME.md 2.4)."""

    def plant(self, name):
        built()
        r = S.plants([name])[name]
        self.assertTrue(r['caught'], r)
        self.assertGreater(r['runs'], 0)

    def test_tag_search_from_0(self):
        self.plant('tag-search-from-0')

    def test_glow_turn_late(self):
        self.plant('glow-turn-late')

    def test_nukage_signed_shift(self):
        self.plant('nukage-signed-shift')

    def test_button_other_texture(self):
        self.plant('button-other-texture')

    def test_mod3_off(self):
        self.plant('mod3-off')


if __name__ == '__main__':
    unittest.main()
