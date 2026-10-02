"""Part lines of milestone 10 (docs/GAME.md 2.4 row lines, wave 2;
docs/game-parts/lines.md): the special lines a thing uses or crosses, the
LSTAB dispatch of their handlers and the exits, the switch textures and the
buttons, natively (src/native/game/lines/).

What it checks (tools/native/gparts/lines.py does the work):

  * the part builds without a warning, within its budget; its tables
    (usetab, crosstab) equal p_switch65.s's in the release's memory entry
    by entry (special, handler, argument, mode), ggame.inc's LSTAB numbers
    (LSTAB_<label>) equal the dispatch table's order, its GT_SWIDX and
    GT_SWLIST equal llayout's places, and it makes no far access of a
    cached kind's bank (gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5) on a sample of the chosen
    captured calls: every eligible call of P_CrossSpecialLine and
    P_ChangeSwitchTexture, every SAMPLE-th of P_UseSpecialLine's and
    findSpecial's choice, from both poisoned machines under f121 and
    fastpath, equal to ref816's with the exclusions R1-R6 only, every
    declared output equal (findSpecial's carry, argument and index), the
    sound events equal, no stray write; the synthetic calls on the nine
    maps: P_ChangeSwitchTexture on every SYN_SAMPLE-th switch line once
    and again and the button list's cases (pressed, a slot taken, full:
    I_Error), the exits by the player alive and dead and by a monster,
    lnExit alone, a light line crossed (walk once) and the shots on 97
    (the whole of it: `lines.py --check`, report.json);
  * the planted bugs of GAME.md 2.4, each built from a scratch copy of the
    part's sources in a temporary directory, each failing its named check.

It skips with the reason when build/ lacks upstream's sources, ref816,
a2vm, the shared outputs (`make -s -C src/native -f game.mk shared
ROOT=$PWD`; the survey: `python3 tools/native/gamecap.py --survey`), the
level bases (`python3 tools/native/level_check.py --setup`) or the part's
own captures (`python3 tools/native/gparts/lines.py --capture`, then
`--synthetic`). It never rebuilds a shared output.
"""

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

import lines as L  # noqa: E402


def setUpModule():
    """The part's own case directory: gamecap's CASES is one global, which
    the harness sets when imported and another part's harness may change
    in the same process (unittest discover runs every module in one)."""
    L.GC.CASES = L.CASES


SAMPLE = 10         # P_UseSpecialLine's and findSpecial's choice
SYN_SAMPLE = 4      # P_ChangeSwitchTexture's synthetic lines


def why_skip():
    why = L.missing()
    if why:
        return why
    for key in L.ENTRIES:
        if L.eligible_calls(key)[0] and not L.captured(key):
            return ('no captures of %s (python3 tools/native/gparts/'
                    'lines.py --capture)' % key)
    for name in L.synthetic_names():
        if not (L.SYN / (name + '.json.z')).exists():
            return ('no synthetic calls %s (python3 tools/native/gparts/'
                    'lines.py --synthetic)' % name)
    # the captured calls' paths (the choice's), decoded once
    known = json.loads(L.PATHS_FILE.read_text()) if L.PATHS_FILE.exists() \
        else {}
    for key in L.ENTRIES:
        if any(L.rel(p) not in known.get(key, {})
               for _, _, _, p in L.captured(key)):
            return ('the paths of %s are not decoded (python3 tools/native/'
                    'gparts/lines.py --paths)' % key)
    return None


SKIP = why_skip()
_BUILT = []


def built():
    if not _BUILT:
        _BUILT.append(L.build())
    return _BUILT[0]


@unittest.skipIf(SKIP, SKIP or '')
class Build(unittest.TestCase):

    def test_builds_within_budget(self):
        built()
        sz = L.sizes()
        self.assertLessEqual(sz['bytes'], sz['budget'])
        for name in L.LABELS:
            self.assertIn(name, sz['routines'])

    def source(self):
        return (L.PART_SRC / 'lines.s').read_text()

    def const(self, name):
        for line in self.source().splitlines():
            f = line.split(';')[0].split()
            if len(f) >= 3 and f[0] == name and f[1] == '=':
                return ' '.join(f[2:])
        self.fail('no %s in lines.s' % name)

    def test_tables(self):
        """usetab and crosstab equal p_switch65.s's in the release (a
        case's memory), with the handlers by LSTAB's numbers and the
        arguments by their upstream constants."""
        built()
        key = next(k for k in L.ENTRIES if L.captured(k))
        mem = L.GC.load_case(L.captured(key)[0][3]).entry
        up = L.upstream_spectab(mem)
        names = L.lstab_names()
        # each handler by ggame.inc's LSTAB_<label> (request 2, wave 2 as
        # integrated): its number in LSTAB's order
        text = (L.OUT / 'gen' / 'ggame.inc').read_text()
        nums = {}
        for line in text.splitlines():
            m = re.match(r'^(LSTAB_\w+)\s*=\s*\$([0-9A-F]+)', line)
            if m:
                nums[m.group(1)] = int(m.group(2), 16)
        for i, k in enumerate(names, 1):
            self.assertEqual(nums['LSTAB_' + k.split(':')[1]], i, k)
        uc = L.uconst()
        rows = {'usetab': [], 'crosstab': []}
        table = None
        for line in self.source().splitlines():
            code = line.split(';')[0]
            if code.startswith('usetab:'):
                table = 'usetab'
            elif code.startswith('crosstab:'):
                table = 'crosstab'
            elif code.startswith('crosstab_end:'):
                table = None
            m = re.search(r'\bSPEC\s+(.*)$', code)
            if table and m:
                f = [x.strip() for x in m.group(1).split(',')]
                arg = uc[f[2]] if f[2].startswith('UC_') else int(f[2])
                rows[table].append((int(f[0]), names[nums[f[1]] - 1], arg,
                                    int(f[3])))
        self.assertEqual(rows, up)
        # the image's tables are those rows, inside findSpecial's own
        # bytes (its group: its only reader)
        b = L.G.load_build(L.OUT, L.IMAGE)
        self.assertEqual(b.labels['usetab_end'] - b.labels['usetab'],
                         4 * len(up['usetab']))
        self.assertEqual(b.labels['crosstab_end'] - b.labels['crosstab'],
                         4 * len(up['crosstab']))
        fs = L.sizes()['routines']['findSpecial']
        lo = b.labels['findSpecial']
        self.assertTrue(lo < b.labels['spectab'] and
                        b.labels['crosstab_end'] <= lo + fs['bytes'])
        data = bytearray(L.OUT.joinpath('%s.g%d' % (L.IMAGE, fs['group']))
                         .read_bytes()) if fs['group'] else None
        if data is not None:
            seg = b.segments[fs['segment']][0]
            at = b.labels['usetab'] - seg
            got = [tuple(data[at + 4 * i:at + 4 * i + 4])
                   for i in range(len(up['usetab']) + len(up['crosstab']))]
            want = [(sp, names.index(h) + 1, arg, mode) for sp, h, arg, mode
                    in up['usetab'] + up['crosstab']]
            self.assertEqual(got, want)

    def test_constants(self):
        """ggame.inc's GT_SWIDX and GT_SWLIST (request 1) are GTAB's SW_IDX
        and switchlist, and the button's time is TICRATE
        (p_switch65.s:21)."""
        built()
        from native import llayout as LL
        text = (L.OUT / 'gen' / 'ggame.inc').read_text()

        def inc(name):
            for line in text.splitlines():
                f = line.split(';')[0].split()
                if len(f) == 3 and f[0] == name and f[1] == '=':
                    return int(f[2].replace('$', '0x'), 0)
            self.fail('no %s' % name)
        self.assertEqual(inc('GT_SWIDX'), LL.GT['SW_IDX'][0])
        self.assertEqual(inc('GT_SWLIST'), LL.GT['SWITCHLIST'][0])
        self.assertEqual(LL.NUMSW2, 38)
        self.assertEqual(LL.GT['SW_IDX'][1], 256)
        self.assertEqual(self.const('BUTTONTIME'), 'UC_TICRATE')
        self.assertEqual(L.uconst()['UC_TICRATE'], 35)

    def test_no_far_access_of_a_cached_kind(self):
        problems = L.GR.grep_check(L.SRC, ['game/lines/lines.s'])
        self.assertEqual(problems, [])

    def test_args(self):
        built()
        nat = L.SF.Native(L.OUT)
        spec = L.args()
        self.assertEqual(set(spec), set(L.ALL_KEYS))
        for key, e in spec.items():
            self.assertIn(e['native'], nat.b.labels, key)
            nat.group(e['native'])


@unittest.skipIf(SKIP, SKIP or '')
class Checkpoint(unittest.TestCase):

    def run_jobs(self, jobs):
        res = L.run_jobs(jobs, workers=2, progress=False)
        self.assertTrue(res)
        bad = [r for r in res if not r.get('ok')]
        self.assertEqual(bad, [], json.dumps(bad[:3])[:3000])
        self.assertEqual(sum(r.get('stray') or 0 for r in res), 0)
        return res

    def test_captured(self):
        """Every chosen call of P_CrossSpecialLine and P_ChangeSwitchTexture,
        every SAMPLE-th of the others, both fills, both profiles."""
        built()
        jobs = L.check_jobs(keys=(L.CROSS, L.CHANGE), synthetic=False)
        jobs += L.check_jobs(keys=(L.USE, L.FIND), synthetic=False,
                             sample=SAMPLE)
        res = self.run_jobs(jobs)
        self.assertEqual({r['entry'] for r in res}, set(L.ENTRIES))
        per: dict = {}
        for r in res:
            per[(r['entry'], r['case'])] = per.get((r['entry'], r['case']),
                                                   0) + 1
        self.assertEqual(set(per.values()), {4})     # 2 fills x 2 profiles
        paths = {r['path'] for r in res}
        self.assertTrue(any(p.startswith('monster-') for p in paths))
        self.assertTrue(any(p.startswith('usetab-found') for p in paths))
        self.assertTrue(any(p.startswith('crosstab-') for p in paths))

    def test_switches_and_buttons(self):
        """P_ChangeSwitchTexture on every SYN_SAMPLE-th switch line of the
        nine maps, once and again, and the button list's cases."""
        built()
        jobs = L.check_jobs(keys=(L.CHANGE,), captured_=False,
                            sample=SYN_SAMPLE)
        jobs += L.check_jobs(keys=(L.CHANGE,), captured_=False,
                             select=lambda r: 'buttons' in r['note'])
        res = self.run_jobs(jobs)
        self.assertEqual(len({r['case'].split(':')[0] for r in res}), 9)
        paths = {r['path'] for r in res}
        for want in ('once-', 'again-', '-pressed', '-slot1', '-full',
                     'once-none'):
            self.assertTrue(any(want in p for p in paths), want)
        self.assertTrue(any(r.get('expect') == 'GS_ERROR' for r in res))

    def test_exits_and_crossings(self):
        """The exits (P_UseSpecialLine and lnExit) by the player alive and
        dead and by a monster, the other use and cross cases, findSpecial
        on each map."""
        built()
        jobs = L.check_jobs(keys=(L.USE, L.EXIT, L.CROSS, L.FIND),
                            captured_=False)
        res = self.run_jobs(jobs)
        paths = {r['path'] for r in res}
        for want in ('player-lnExit-mode0', 'player-lnExit-dead-mode0',
                     'monster-not-a-door', 'exit-player-normal',
                     'exit-player-dead-normal', 'player-lnLight-mode1',
                     'missile', 'monster-not-97-88'):
            self.assertIn(want, paths)


@unittest.skipIf(SKIP, SKIP or '')
class Planted(unittest.TestCase):
    """Each planted bug fails its named check (GAME.md 2.4)."""

    def plant(self, name):
        built()
        r = L.plants([name])[name]
        self.assertTrue(r['caught'], r)
        self.assertGreater(r['runs'], 0)

    def test_walk_once_not_cleared(self):
        self.plant('walk-once-not-cleared')

    def test_monster_allowed(self):
        self.plant('monster-allowed')

    def test_button_timer_short(self):
        self.plant('button-timer-short')


if __name__ == '__main__':
    unittest.main()
