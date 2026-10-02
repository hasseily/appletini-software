#!/usr/bin/env python3
"""Part player's checkpoint (milestone 10, wave 5; docs/GAME.md 2.4, 3.5;
docs/game-parts/player.md), lean (the owner's rules of 2026-10-02): its
image, a sample of its routines' captured calls, its synthetic cases, the
random checks of its arithmetic helpers, its planted bugs, and
build/native/game/player/report.json.

Usage:  python3 tools/native/gparts/player.py --build
        python3 tools/native/gparts/player.py --capture [--jobs 2]
        python3 tools/native/gparts/player.py --check [--jobs 2] [--sample K]
        python3 tools/native/gparts/player.py --random [--count N]
        python3 tools/native/gparts/player.py --plants
        python3 tools/native/gparts/player.py --report

The image (build()): `make -f game.mk part P=player PL_TEST=1` from a
scratch copy of the build files and of the planted bugs' files, every
other source from the tree (game.mk's vpath), into
build/native/game/player/ (or a temporary directory).

The selection (at most LIMIT calls a routine, spread to reach as many
branches as the survey shows): P_PlayerThink by the class of its call (in
its tic: movePlayer or not, the death think's angleToAttacker,
specialSector, P_UseLines and PTR_NoWayTraverse, the ACTTAB actions and
LSTAB handlers it reached), only the classes whose dispatch targets are
built (no wfire action, no attack traverser), LIMIT spread over the
classes; specialSector, angleToAttacker and P_UseLines spread evenly over
every run's calls. movePlayer, calcHeight, fixedSquare and onGround run
inside every P_PlayerThink call; PTR_UseTraverse and PTR_NoWayTraverse
(TRVTAB's: upstream enters them by JML, which ref816's --capture does not
count) inside the P_UseLines calls. The captures (--capture):
tools/native/gamecap.py's, into the part's build/native/game/player/cases/;
with them P_PlayerThink calls of the tour spread over its maps, the bases
of the synthetic cases.

A run (run_one()): routine mode (the case's entry state through the game
manifest into a machine poisoned with $A5, the entry's inputs of
args.json, the call, the state read back and compared with the
reference's return state, gcanon's routine mode, exclusions R1-R7), on
a2vm under f121, with the write log: no CPU write outside the allowed
places (part mobjstate's shared rule and the part's scratch block), every
declared output equal (onground, angleToAttacker's angle), the
native-only globals consistent. One fill and one profile (the lean
rules); the other fill and fastpath are the final integration's.

The synthetic cases (SYNTHETIC), each a captured state with fields poked
and the reference's own call (ref816 --call):
  dead-left, dead-right  P_PlayerThink of a dead player with an attacker,
                the mobj's angle 90 degrees off the attacker's: a turn of
                ANG5 each way (the captured deaths mostly look at once)
  squat         P_PlayerThink on the ground, viewheight 22, delta -2: the
                height under VIEWHEIGHT / 2 after the delta (its order)
  nukage, nukage-16, nukage-suit, slime, slime-suit
                specialSector on the player's sector made special 5 (or
                16) under the player: leveltime & 31 = 0 (the damage) or 16
                (none; the mask), the radiation suit on (none, or 16's
                P_Random)
  e1m8-11, e1m8-11-god, e1m8-10, e1m8-10-god, e1m8-hurt
                E1M8's sector special 11 under the player on a tour state
                of E1M8: health 11 and 10, god mode on and off, leveltime &
                31 not 0 (no damage: only the health decides the exit); and
                health 30 with leveltime & 31 = 0 (20 damage, then the exit)
  locked-door   P_UseLines facing a locked door (specials 26-28, 32-34) of
                a tour map, 32 units in front of it, no keys

The random checks (--random): thrustMul, fixedSquare, times64 and hurt32
on N inputs each (0, +-1, the extremes, then random values) through
upstream's helpers (mathref batch on a captured P_PlayerThink call's
machine; for hurt32 upstream's P_DamageMobj is an RTL there, so that the
helper's own work is compared: whether it calls, and with what) and the
native's (pltest.s pl_bulk), compared.
"""

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

from bridge.port import PortReader, PortWriter, PortError  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, render_check as RC  # noqa: E402
from ref816 import bounded  # noqa: E402
import mobjstate as MS  # noqa: E402  (wave 1's harness: its generic parts)

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'player'
WAVE = 5
OUT = GL.GAME / PART
MYCASES = OUT / 'cases'
REPORT = OUT / 'report.json'
FILLS = (0xA5,)
PROFILES = ('f121',)
NAME = 'ptest'
UPSTREAM_BYTES = 2131
BUDGET = 2800                   # GAME.md 2.4: upstream 2,131 x 1.3
MODULES = ('puser', 'puse')
TEST_MODULES = ('pltest',)
LIMIT = 40
JOBS = 2

THINK = 'p_user65.s:P_PlayerThink'
SPEC = 'p_user65.s:specialSector'
ATK = 'p_user65.s:angleToAttacker'
USE = 'p_use65.s:P_UseLines'
MOVE = 'p_user65.s:movePlayer'
NOWAY = 'p_use65.s:PTR_NoWayTraverse'
ENTRIES = (THINK, SPEC, ATK, USE)
QUOTA = {THINK: LIMIT, SPEC: 20, ATK: 20, USE: LIMIT}
TOUR_BASES = 18                 # tour P_PlayerThink calls: the synthetic
                                #   cases' bases, spread over its maps


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def missing() -> Optional[str]:
    """None when the shared outputs, the survey, the level bases, ref816
    and a2vm are there; else what is missing and its command."""
    shared = GL.SHARED
    if not ((shared / 'gen' / 'ggame.inc').exists() and
            (shared / 'native-game-1.json').exists()):
        return ('the shared outputs (make -s -C src/native -f game.mk shared '
                'skel ROOT=$PWD)')
    if GC.survey_of('demo1') is None:
        return 'the survey (python3 tools/native/gamecap.py --survey)'
    if not GR.have_bases():
        return ('milestone 9\'s level bases (python3 tools/native/'
                'level_check.py --setup)')
    from ref816 import title
    if not (Path(G.A2VM).exists() and Path(title.MACHINE).exists()):
        return 'ref816 and a2vm (make -C tools/ref816; make -C tools/a2vm)'
    if not MATHREF.exists():
        return 'mathref (make -C tools/native)'
    return None


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

def build(game: Path = GL.GAME, bugs: Sequence[Tuple[str, str, str]] = ()
          ) -> Path:
    """The part's image (GAME/player/ptest.*) from a scratch copy of the
    build files and of the bugs' files (relative to src/native) with each
    bug (file, old, new) applied once; the copy is deleted."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-player-build-', dir=str(BUILD)))
    try:
        src = tmp / 'src'
        copy_files = set(G.PLANT_COPY) | {'game/%s/part.mk' % PART}
        copy_files |= {name for name, _, _ in bugs}
        for f in copy_files:
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(SRC / f), str(src / f))
        for name, old, new in bugs:
            text = (src / name).read_text()
            if text.count(old) != 1:
                raise PartError('%s: the edit no longer applies: %r' % (
                    name, old[:60]))
            (src / name).write_text(text.replace(old, new))
        objs = game / PART / 'game' / PART
        if objs.exists():               # (player.inc is no prerequisite)
            for p in objs.glob('*.o'):
                p.unlink()
        cmd = ['make', '-s', '-C', str(src), '-f', 'game.mk', 'part',
               'P=%s' % PART, 'ROOT=%s' % ROOT, 'GAME=%s' % game,
               'PL_TEST=1']         # (pltest.s: part.mk)
        r = bounded.run(cmd, timeout=600, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, universal_newlines=True)
        if r.returncode:
            raise PartError('the build failed:\n' + r.stdout[-3000:])
        if 'arning' in r.stdout:
            raise PartError('the build warns:\n' + r.stdout[-3000:])
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return game / PART


def load(obj: Path = OUT) -> RC.Build:
    return G.load_build(obj, NAME)


def sizes(b: RC.Build) -> Dict[str, Any]:
    """The part's bytes against its budget, and the segments they are in."""
    ms = MS.module_ranges(b)
    by = {m: sum(hi + 1 - lo for _, lo, hi in ms.get(m, ()))
          for m in MODULES + TEST_MODULES}
    code = sum(by[m] for m in MODULES)
    return {'modules': by, 'part_bytes': code, 'budget': BUDGET,
            'upstream_bytes': UPSTREAM_BYTES,
            'over_budget_pct': round(100.0 * (code - BUDGET) / BUDGET, 1),
            'segments': {m: sorted({seg for seg, _, _ in ms.get(m, ())})
                         for m in MODULES}}


def inc_value(b: RC.Build, name: str) -> int:
    """A symbol of the image's generated ggame.inc."""
    for line in (b.obj / 'gen' / 'ggame.inc').read_text().splitlines():
        f = line.split()
        if len(f) >= 3 and f[0] == name and f[1] == '=':
            return int(f[2].lstrip('$'), 16)
    raise PartError('%s is not in ggame.inc' % name)


SB_NAMES = {'PY_THING': 1, 'PY_LINE': 3, 'PY_T': 25}


def place(b: RC.Build, name: str) -> int:
    return inc_value(b, 'SB_PLAYER') + SB_NAMES[name]


def main_place(name: str) -> int:
    """A main: place: the tic phase's own globals (glayout.TGM:
    G_ONGROUND, request R1 as integrated) or llayout's."""
    from native import llayout as LL
    return GL.TGM[name] if name in GL.TGM else LL.G[name]


# ---------------------------------------------------------------------------
# The selection and the captures
# ---------------------------------------------------------------------------

_SV: Dict[str, Any] = {}


def survey(run: str) -> Optional[Dict[str, Any]]:
    if run not in _SV:
        _SV[run] = GC.survey_of(run)
    return _SV[run]


def spread(items: Sequence[Any], n: int) -> List[Any]:
    if len(items) <= n:
        return list(items)
    return [items[(i * len(items)) // n] for i in range(n)]


def reached(run: str, key: str, hit: int) -> List[str]:
    sv = survey(run)
    r = sv['routines'].get(key, {})
    return [sv['targets'][i] for i in r.get('reached', {}).get(str(hit), [])]


def eligible(run: str, key: str, hit: int) -> List[str]:
    """The dispatch targets the call reached that are not built in the
    part's image: empty when the call is eligible."""
    built = set(GL.built_set(extra=[PART]))
    return [t for t in reached(run, key, hit)
            if (GL.owner_of(t) or 'core') not in built | {'core'}]


def tics_of(run: str, key: str) -> set:
    return set(survey(run)['routines'].get(key, {}).get('tic', []))


def think_class(run: str, hit: int, flags: Dict[str, set]) -> str:
    """The class of a P_PlayerThink call: its tic's other calls (no
    movePlayer: dead or a reaction time; angleToAttacker; specialSector;
    P_UseLines) and the dispatch targets it reached."""
    tic = survey(run)['routines'][THINK]['tic'][hit - 1]
    parts = [name for name, tics in sorted(flags.items()) if tic in tics]
    acts = sorted(t.split(':')[1] for t in reached(run, THINK, hit))
    return '+'.join(parts + acts) or 'plain'


def calls_of(key: str) -> List[Tuple[str, int, str]]:
    """(run, hit, class) of every eligible call of key in the runs."""
    out = []
    for run in GC.RUNS:
        sv = survey(run)
        if not sv:
            continue
        n = sv['routines'].get(key, {}).get('calls', 0)
        flags = {}
        if key == THINK:
            moved = tics_of(run, MOVE)
            flags = {'still': set(sv['routines'][THINK]['tic']) - moved,
                     'atk': tics_of(run, ATK), 'special': tics_of(run, SPEC),
                     'use': tics_of(run, USE), 'noway': tics_of(run, NOWAY)}
        for h in range(1, n + 1):
            if eligible(run, key, h):
                continue
            cls = think_class(run, h, flags) if key == THINK else \
                key.split(':')[1]
            out.append((run, h, cls))
    return out


def selection(key: str) -> List[Tuple[str, int, str]]:
    """At most QUOTA[key] calls: P_PlayerThink's spread over its classes
    (each class its share, every class at least one while the quota
    lasts), the others spread over every run's calls."""
    calls = calls_of(key)
    quota = QUOTA[key]
    if key != THINK:
        return spread(calls, quota)
    by: Dict[str, List[Tuple[str, int, str]]] = {}
    for c in calls:
        by.setdefault(c[2], []).append(c)
    share = max(1, quota // max(1, len(by)))
    chosen: List[Tuple[str, int, str]] = []
    # the rare classes first, so that every class is in when there are
    # more classes than the quota
    for cls in sorted(by, key=lambda k: (len(by[k]), k)):
        chosen += spread(by[cls], share)
    chosen = chosen[:quota]
    rest = [c for c in calls if c not in set(chosen)]
    chosen += spread(rest, max(0, quota - len(chosen)))
    return sorted(chosen[:quota], key=lambda c: (GC.RUNS.index(c[0]), c[1]))


def _capture_job(job) -> str:
    run, key, hits = job
    MS.use_cases(MYCASES)
    tics = GC.survey_of(run)['routines'][key]['tic']
    made = GC.capture(run, key, hits, tics, say=lambda *a: None)
    return '%s %s: %d made of %d' % (run, key, len(made), len(hits))


def tour_hits() -> List[int]:
    n = survey('tour')['routines'][THINK]['calls']
    return spread(list(range(1, n + 1)), TOUR_BASES)


def capture_plan() -> List[Tuple[str, str, List[int]]]:
    """(run, key, hits) of the cases the part's directory lacks: the
    selection, and the tour's P_PlayerThink bases of the synthetic
    cases."""
    MS.use_cases(MYCASES)
    want: Dict[Tuple[str, str], List[int]] = {}
    for key in ENTRIES:
        for run, h, _ in selection(key):
            want.setdefault((run, key), []).append(h)
    want.setdefault(('tour', THINK), []).extend(tour_hits())
    todo = []
    for (run, key), hits in sorted(want.items()):
        d = GC.case_dir(run, key)
        miss = sorted({h for h in hits
                       if not (d / ('h%08d.case.z' % h)).exists()})
        for i in range(0, len(miss), GC.BATCH):
            todo.append((run, key, miss[i:i + GC.BATCH]))
    return todo


def capture(jobs: int = JOBS) -> None:
    MS.use_cases(MYCASES)
    todo = capture_plan()
    first = []
    for run in sorted({t[0] for t in todo}):
        if not GC.base_path(run).exists():
            j = next(t for t in todo if t[0] == run)
            first.append(j)
            todo.remove(j)
    for batch in (first, todo):
        if batch:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                for got in pool.map(_capture_job, batch):
                    say(got)


def case_paths(key: str) -> List[Tuple[str, Path, str]]:
    MS.use_cases(MYCASES)
    out = []
    for run, hit, cls in selection(key):
        p = GC.case_dir(run, key) / ('h%08d.case.z' % hit)
        if p.exists():
            out.append((run, p, cls))
    return out


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def uconst(name: str) -> int:
    return MS.uconst(name)


def sym(name: str) -> int:
    return GC.CL.Linkmap().address(name)


def exported(name: str) -> int:
    """A symbol of the release's link map (its exported table)."""
    if not hasattr(exported, 'd'):
        exported.d = json.loads((BUILD / 'linkmap.json').read_text())[
            'game']['exported']
    return exported.d[name]


def ptr(mem, at: int) -> int:
    return int.from_bytes(mem.read(at, 4), 'little') & 0xFFFFFF


def sector_number(case: GC.Case, p: int) -> int:
    base = ptr(case.entry, exported('_g_sectors'))
    k, r = divmod((p & 0xFFFFFF) - base, uconst('US_SEC'))
    n = case.entry.u16(exported('_g_numsectors'))
    if r or not 0 <= k < n:
        raise GR.HarnessError('$%06X is no sector' % p)
    return k


def intercept_number(p: int) -> int:
    k, r = divmod((p & 0xFFFFFF) - sym('p_path65.s:intercepts'),
                  uconst('US_IC'))
    if r or not 0 <= k < 64:
        raise GR.HarnessError('$%06X is no intercept' % p)
    return k


class Prep:
    """A case's reference side and its native inputs (mobjstate.Prepared's,
    with the part's destination sb: and conversions sectorptr and
    intercept)."""

    def __init__(self, case: GC.Case, spec: Dict[str, Any], b: RC.Build):
        self.case = case
        self.spec = spec
        self.up = up = GR.Upstream(case)
        self.problems: List[str] = []
        self.accepted: List[str] = []
        for r in (up.r_in, up.r_out):
            acc, others = MS.stale_link_problems(r)
            self.accepted += acc
            self.problems += others
        if self.problems:
            return
        self.mf, self.header, self.banks = GR.manifest(up.gamemap)
        self.skip = gcanon.skips('routine', up.s_in)
        pm = G.tracked_memory()
        PortWriter(self.mf).write(gcanon.strip(up.s_in, self.skip), pm)
        self.recs = G.port_records(pm) + GR.derived(pm, self.header)
        regs = [0, 0, 0, 0x34]
        self.zp: List[Tuple[int, bytes]] = []
        for item in spec.get('in', []):
            data = up.source(item['from'])
            kind = item.get('as')
            v = int.from_bytes(data, 'little')
            if kind == 'sectorptr':
                data = bytes([sector_number(case, v)])
            elif kind == 'intercept':
                data = bytes([intercept_number(v)])
            elif kind:
                data = MS._convert(up, self.mf, data, kind)
            to = item['to']
            n = item.get('bytes', len(data))
            if to in ('a', 'x', 'y'):
                regs['axy'.index(to)] = data[0]
            elif to.startswith('zp:'):
                self.zp.append((GR.zp_address(to[3:]),
                                data[:n].ljust(n, b'\0')))
            elif to.startswith('sb:'):
                self.zp.append((place(b, to[3:]), data[:n].ljust(n, b'\0')))
            elif to.startswith('main:'):
                self.zp.append((main_place(to[5:]),
                                data[:n].ljust(n, b'\0')))
            else:
                raise GR.HarnessError('an input destination %r' % to)
        self.regs = regs


def allowed_extra(b: RC.Build) -> List[Tuple[int, int]]:
    """The main places beyond mobjstate's shared rule: the part's scratch
    block, and the sound flood's work stack (part pspr's ps_stack, in its
    group's slot: a shot's noise alert inside P_MovePsprites; pspr.py
    allows it the same way)."""
    sb = inc_value(b, 'SB_PLAYER')
    out = [(sb, sb + inc_value(b, 'SB_PLAYER_SIZE'))]
    if 'ps_stack' in b.labels:
        st = b.labels['ps_stack']
        out.append((st, st + 512 * 2))
    return out


def allowed_aux_extra() -> List[Tuple[int, int, int]]:
    """The aux places beyond mobjstate's rule: the sides (P_UseLines ->
    P_UseSpecialLine -> P_ChangeSwitchTexture writes a switch's side back
    with sd_put; evworld.py allows them the same way)."""
    from native import rlayout as RL
    sides = RL.SIDES
    return [(RL.LVMAP, sides.base, sides.base + sides.stride *
             sides.capacity)]


def stray(writes, b: RC.Build, header: Dict[str, Any]) -> List[str]:
    extra = allowed_extra(b)
    aux = allowed_aux_extra()
    rest = [w for w in writes if not (
        (w.storage == 'main' and any(lo <= w.offset < hi
                                     for lo, hi in extra)) or
        (w.storage == 'aux' and any(w.bank == k and lo <= w.offset < hi
                                    for k, lo, hi in aux)))]
    return MS.stray(rest, b, header)


def run_one(prep: Prep, b: RC.Build, fill: int, profile: Optional[str]
            ) -> Dict[str, Any]:
    case, up, spec = prep.case, prep.up, prep.spec
    res: Dict[str, Any] = {'case': case.path.name if case.path else
                           case.header.get('note') or 'synthetic',
                           'routine': case.key, 'hit': case.header['hit'],
                           'fill': '%02x' % fill, 'profile': profile,
                           'ok': False}
    if prep.problems:
        res['error'] = 'bridge: ' + '; '.join(prep.problems[:3])
        return res
    if prep.accepted:
        res['stale_links'] = len(prep.accepted)
    img = G.Image(b, fill, store=True)
    img.recs += GR.base_records(up.gamemap)
    img.recs += prep.recs
    for a, d in prep.zp:
        img.main(a, d)
    name = spec['native']
    img.poke_word('dg_entry', b.labels[name])
    img.poke_label('dg_grp', bytes([G.entry_group(b, name)]))
    work = Path(tempfile.mkdtemp(prefix='tmp-player-run-', dir=str(BUILD)))
    try:
        start = time.time()
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), banks=prep.banks, profile=profile,
                  write_log=MS.LOG_RANGES)
        res['seconds'] = round(time.time() - start, 2)
        res['lowest_s'] = r.state.get('lowest_s')
        writes = MS.read_log(work / 'writes.log') \
            if (work / 'writes.log').exists() else []
        res['clock'], res['cpu_cycles'] = MS.call_clock(writes, b)
        st = stray([w for _, w in writes], b, prep.header)
        res['strays'] = len(st)
        if st:
            res['stray_first'] = st[:4]
        ended = r.ended()
        res['ended'] = ended
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                res['stop'] = G.stop_codes(G.load_snapshot(p))
            return res
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    from native import setupcheck as SC
    try:
        nat = PortReader(prep.mf).read(SC.port_memory(m))
    except PortError as error:
        res['diff'] = ['the port reader: %s' % error]
        return res
    diff = gcanon.compare(up.s_out, nat, 'routine')
    diff += MS.native_checks(m)
    res['fc_loads'] = m.main[GL.RT['FC_LOADS']] | \
        m.main[GL.RT['FC_LOADS'] + 1] << 8
    diff += outputs(prep, b, m)
    res['diff'] = diff[:12]
    res['ok'] = not diff and not res['strays']
    return res


M_R = 0xB0 + 0x18               # math.inc: MZ + $18


def outputs(prep: Prep, b: RC.Build, m) -> List[str]:
    lab = b.labels
    regs = {'a': G.card_byte(m, lab['dg_ra']),
            'x': G.card_byte(m, lab['dg_rx']),
            'y': G.card_byte(m, lab['dg_ry'])}
    out = []
    for item in prep.spec.get('out', []):
        nv, n = item['native'], item.get('bytes', 2)
        if nv in regs:
            value = regs[nv]
        elif nv == 'm_r':
            value = int.from_bytes(bytes(m.main[M_R:M_R + 4]), 'little')
        elif nv.startswith('sb:') or nv.startswith('main:'):
            at = place(b, nv[3:]) if nv.startswith('sb:') else \
                main_place(nv[5:])
            value = int.from_bytes(bytes(m.main[at:at + n]), 'little')
        else:
            raise GR.HarnessError('a native output %r' % nv)
        uv = int.from_bytes(prep.up.source(item['upstream'], 'out'),
                            'little')
        mask = (1 << (8 * n)) - 1
        if value & mask != uv & mask:
            out.append('output %s: %X != %X' % (item['upstream'],
                                                value & mask, uv & mask))
    return out


# ---------------------------------------------------------------------------
# The synthetic cases: a captured state poked, the reference's own call
# ---------------------------------------------------------------------------

FRAC = 0x10000
ANG5 = 0x038E38E3


def u16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, 'little')


def s32(v: int) -> bytes:
    return (v & 0xFFFFFFFF).to_bytes(4, 'little')


def player() -> int:
    return exported('_g_player')


def pl(field: str) -> int:
    return player() + uconst('UO_PL_' + field)


def i32(mem, at: int) -> int:
    v = int.from_bytes(mem.read(at, 4), 'little')
    return v - (1 << 32) if v & 0x80000000 else v


def i16(mem, at: int) -> int:
    v = mem.u16(at)
    return v - 0x10000 if v & 0x8000 else v


def mo_of(mem) -> int:
    return ptr(mem, pl('MO'))


def sector_of(mem) -> int:
    """The player's sector's address: mo->subsector->sector."""
    ss = ptr(mem, mo_of(mem) + uconst('UO_MO_SUBSECTOR'))
    return ptr(mem, ss + uconst('UO_SUB_SECTOR'))


def gamemap(case: GC.Case) -> int:
    return GR.Upstream(case).gamemap


_TOUR: List[GC.Case] = []


def tour_cases() -> List[GC.Case]:
    """The tour's captured P_PlayerThink calls (the synthetic cases'
    bases), in hit order."""
    if not _TOUR:
        MS.use_cases(MYCASES)
        d = GC.case_dir('tour', THINK)
        for h in tour_hits():
            p = d / ('h%08d.case.z' % h)
            if p.exists():
                _TOUR.append(GC.load_case(p))
    if not _TOUR:
        raise PartError('no tour P_PlayerThink case (python3 tools/native/'
                        'gparts/player.py --capture)')
    return _TOUR


def alive_base(gmap: Optional[int] = None) -> GC.Case:
    """A tour P_PlayerThink call (on gmap) with the player alive, on the
    ground, no reaction time."""
    for c in tour_cases():
        mem = c.entry
        mo = mo_of(mem)
        if gmap is not None and gamemap(c) != gmap:
            continue
        if mem.u16(pl('PLAYERSTATE')) != 0 or \
                mem.u16(mo + uconst('UO_MO_REACTIONTIME')):
            continue
        if i32(mem, mo + uconst('UO_MO_Z')) != \
                i32(mem, mo + uconst('UO_MO_FLOORZ')):
            continue
        return c
    raise PartError('no tour P_PlayerThink case alive on the ground%s' % (
        '' if gmap is None else ' on E1M%d' % gmap))


def dead_base() -> Tuple[GC.Case, int]:
    """A captured P_PlayerThink call of a dead player with an attacker that
    is not the player's mobj, and the attacker's address."""
    MS.use_cases(MYCASES)
    for run, p, cls in case_paths(THINK):
        if 'atk' not in cls.split('+'):
            continue
        c = GC.load_case(p)
        mem = c.entry
        a = ptr(mem, pl('ATTACKER'))
        if mem.u16(pl('PLAYERSTATE')) == 1 and a and a != mo_of(mem):
            return c, a
    raise PartError('no captured P_PlayerThink call of a dead player with an '
                    'attacker (its class "atk")')


def ref_case(base: GC.Case, key: str, pokes: Sequence[Tuple[int, bytes]],
             note: str) -> GC.Case:
    """The reference's own call of key on base's entry memory with pokes."""
    entry = base.entry.copy()
    entry.header = base.entry.header
    for a, d in pokes:
        entry.write(a, d)
    after, call = MS.ref_call(entry, key, ())
    hdr = dict(base.header, routine=key, note=note, call=call)
    return GC.Case(hdr, entry, after, None)


def bam(dx: float, dy: float) -> int:
    return int(round(math.atan2(dy, dx) / (2 * math.pi) * (1 << 32))) & \
        0xFFFFFFFF


def dead_case(sign: int, note: str) -> GC.Case:
    base, a = dead_base()
    mem = base.entry
    mo = mo_of(mem)
    dx = i32(mem, a + uconst('UO_MO_X')) - i32(mem, mo + uconst('UO_MO_X'))
    dy = i32(mem, a + uconst('UO_MO_Y')) - i32(mem, mo + uconst('UO_MO_Y'))
    angle = (bam(dx, dy) + sign * 0x40000000) & 0xFFFFFFFF
    return ref_case(base, THINK, [(mo + uconst('UO_MO_ANGLE'), s32(angle))],
                    note)


def squat_case() -> GC.Case:
    base = alive_base()
    return ref_case(base, THINK, [(pl('VIEWHEIGHT'), s32(22 * FRAC)),
                                  (pl('DELTAVIEWHEIGHT'), s32(-2 * FRAC))],
                    'squat')


def floor_pokes(base: GC.Case, special: int, leveltime: int, suit: int
                ) -> List[Tuple[int, bytes]]:
    """specialSector's input: _Dp the player's sector, made special under
    the player (its floor at the mobj's z), the leveltime, the suit."""
    mem = base.entry
    sec = sector_of(mem)
    mo = mo_of(mem)
    return [(MS.dp_address(base, '_Dp', 0), s32(sec)),
            (sec + uconst('UO_SEC_SPECIAL'), u16(special)),
            (sec + uconst('UO_SEC_FLOORHEIGHT'),
             mem.read(mo + uconst('UO_MO_Z'), 4)),
            (exported('_g_leveltime'), s32(leveltime)),
            (pl('POWERS') + 2 * uconst('UC_PW_IRONFEET'), u16(suit))]


def special_case(base: GC.Case, special: int, leveltime: int, suit: int,
                 note: str, extra: Sequence[Tuple[int, bytes]] = ()
                 ) -> GC.Case:
    pokes = floor_pokes(base, special, leveltime, suit) + list(extra)
    return ref_case(base, SPEC, pokes, note)


def e1m8_case(health: int, god: bool, leveltime: int, note: str
              ) -> GC.Case:
    base = alive_base(8)
    cheats = base.entry.u16(pl('CHEATS'))
    god_bit = uconst('UC_CF_GODMODE')
    cheats = (cheats | god_bit) if god else (cheats & ~god_bit)
    mo = mo_of(base.entry)
    return special_case(base, 11, leveltime, 0, note, [
        (pl('HEALTH'), u16(health)), (pl('CHEATS'), u16(cheats)),
        (mo + uconst('UO_MO_HEALTH'), u16(health))])


LOCKED = (26, 27, 28, 32, 33, 34)


def locked_door_case() -> GC.Case:
    """P_UseLines 32 units in front of a locked door's middle, facing it,
    with no keys, on the first tour map that has one."""
    for base in tour_cases():
        mem = base.entry
        lines = ptr(mem, exported('_g_lines'))
        n = mem.u16(exported('_g_numlines'))
        size = uconst('US_LINE')
        for i in range(n):
            at = lines + i * size
            if mem.u16(at + uconst('UO_LINE_SPECIAL')) not in LOCKED:
                continue
            # (the release's line keeps its vertices in place: x, y of
            # each in map units, int16)
            x1, y1, x2, y2 = (i16(mem, at + uconst(f) + k) * FRAC
                              for f in ('UO_LINE_V1', 'UO_LINE_V2')
                              for k in (0, 2))
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 32 * FRAC:
                continue
            nx, ny = dy / length, -dx / length      # the front side
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
            x = int(mx + 32 * FRAC * nx)
            y = int(my + 32 * FRAC * ny)
            mo = mo_of(mem)
            pokes = [(mo + uconst('UO_MO_X'), s32(x)),
                     (mo + uconst('UO_MO_Y'), s32(y)),
                     (mo + uconst('UO_MO_ANGLE'), s32(bam(-nx, -ny))),
                     (MS.dp_address(base, '_Dp', 0), s32(player()))]
            pokes += [(pl('CARDS') + 2 * k, u16(0)) for k in range(6)]
            c = ref_case(base, USE, pokes, 'locked-door')
            c.header['locked_line'] = i
            return c
    raise PartError('no locked door on the tour\'s maps')


def synthetic_case(name: str) -> GC.Case:
    if name == 'dead-left':
        return dead_case(1, name)
    if name == 'dead-right':
        return dead_case(-1, name)
    if name == 'squat':
        return squat_case()
    if name.startswith('nukage') or name.startswith('slime'):
        special = 5 if name.startswith('nukage') else 16
        lt = 32 * 41 + (16 if name.endswith('-16') else 0)
        suit = 100 if name.endswith('-suit') else 0
        return special_case(alive_base(), special, lt, suit, name)
    if name == 'e1m8-hurt':
        return e1m8_case(30, True, 32 * 41, name)
    if name.startswith('e1m8-'):
        f = name.split('-')
        return e1m8_case(int(f[1]), f[-1] == 'god', 32 * 41 + 1, name)
    if name == 'locked-door':
        return locked_door_case()
    raise PartError('no synthetic case %s' % name)


def synthetic_took(name: str, case: GC.Case) -> List[str]:
    """What the reference's own call must show for the case to be the one
    it is named for."""
    a, b_ = case.entry, case.after
    out = []
    health = pl('HEALTH')
    action = exported('_g_gameaction')
    if name.startswith('dead-'):
        mo = mo_of(a)
        at = mo + uconst('UO_MO_ANGLE')
        d = (int.from_bytes(b_.read(at, 4), 'little') -
             int.from_bytes(a.read(at, 4), 'little')) & 0xFFFFFFFF
        want = (-ANG5) & 0xFFFFFFFF if name == 'dead-left' else ANG5
        if d != want:
            out.append('the angle moved by $%08X' % d)
    elif name == 'squat':
        if i32(b_, pl('VIEWHEIGHT')) != 20 * FRAC + 0x8000:
            out.append('viewheight %X' % i32(b_, pl('VIEWHEIGHT')))
    elif name in ('nukage', 'slime', 'e1m8-hurt'):
        if b_.u16(health) >= a.u16(health):
            out.append('no damage')
    elif name in ('nukage-16', 'nukage-suit'):
        if b_.u16(health) != a.u16(health):
            out.append('a damage')
    elif name == 'slime-suit':
        if b_.u16(sym('m_random65.s:prndindex')) == a.u16(sym('m_random65.s:prndindex')):
            out.append('no P_Random')
    if name.startswith('e1m8-'):
        exits = b_.u16(action) == uconst('UGA_COMPLETED')
        if exits != (name in ('e1m8-10', 'e1m8-10-god', 'e1m8-hurt')):
            out.append('the exit %s' % exits)
        if b_.u16(pl('CHEATS')) & uconst('UC_CF_GODMODE'):
            out.append('god mode kept')
    if name == 'locked-door':
        if b_.read(pl('MESSAGE'), 4) == a.read(pl('MESSAGE'), 4):
            out.append('no message')
    return ['synthetic %s: %s' % (name, x) for x in out]


SYNTHETIC = ('dead-left', 'dead-right', 'squat', 'nukage', 'nukage-16',
             'nukage-suit', 'slime', 'slime-suit', 'e1m8-11', 'e1m8-11-god',
             'e1m8-10', 'e1m8-10-god', 'e1m8-hurt', 'locked-door')


def synthetic_key(name: str) -> str:
    if name.startswith(('nukage', 'slime', 'e1m8')):
        return SPEC
    if name == 'locked-door':
        return USE
    return THINK


# ---------------------------------------------------------------------------
# The jobs
# ---------------------------------------------------------------------------

_BUILDS: Dict[str, RC.Build] = {}


def _build(obj: str) -> RC.Build:
    if obj not in _BUILDS:
        _BUILDS[obj] = load(Path(obj))
    return _BUILDS[obj]


def _job(job) -> List[Dict[str, Any]]:
    """kind ('case' or 'synthetic'), the case file or the synthetic name,
    the entry, its class, the image, fills, profiles."""
    kind, what, key, path, obj, fills, profiles = job
    MS.use_cases(MYCASES)
    b = _build(obj)
    label = ('%s/%s' % (Path(what).parent.parent.name, Path(what).name)
             if kind == 'case' else what)
    try:
        case = GC.load_case(Path(what)) if kind == 'case' else \
            synthetic_case(what)
        spec = GR.all_args()[key]
        prep = Prep(case, spec, b)
    except Exception as error:              # reported, never hidden
        return [{'ok': False, 'kind': kind, 'entry': key, 'path': path,
                 'case': label,
                 'error': '%s: %s' % (type(error).__name__, error)}]
    took = synthetic_took(what, case) if kind == 'synthetic' else []
    out = []
    for fill in fills:
        for prof in profiles:
            try:
                r = run_one(prep, b, fill, prof)
                if took:
                    r['ok'] = False
                    r['diff'] = took + r.get('diff', [])
            except Exception as error:      # reported per run
                r = {'ok': False, 'fill': '%02x' % fill, 'profile': prof,
                     'error': '%s: %s' % (type(error).__name__, error)}
            r.update(kind=kind, entry=key, path=path, case=label)
            out.append(r)
    return out


def plan(obj: Path = OUT, fills=FILLS, profiles=PROFILES, sample: int = 1,
         entries: Optional[Sequence[str]] = None,
         synthetic_names: Sequence[str] = SYNTHETIC
         ) -> Tuple[List[Tuple], Dict[str, Any]]:
    o = str(obj)
    jobs: List[Tuple] = []
    elig: Dict[str, Any] = {}
    for key in ENTRIES:
        if entries and key not in entries:
            continue
        cases = case_paths(key)
        e = elig.setdefault(key, {'selected': len(selection(key)),
                                  'captured': len(cases),
                                  'eligible': len(calls_of(key))})
        e['calls'] = {run: survey(run)['routines'].get(key, {}).get(
            'calls', 0) for run in GC.RUNS}
        for run, p, cls in cases[::sample]:
            jobs.append(('case', str(p), key, cls, o, tuple(fills),
                         tuple(profiles)))
    for name in synthetic_names:
        key = synthetic_key(name)
        if entries and key not in entries:
            continue
        jobs.append(('synthetic', name, key, 'synthetic: ' + name, o,
                     tuple(fills), tuple(profiles)))
    return jobs, elig


def run_jobs(jobs: Sequence[Tuple], workers: int = JOBS
             ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if workers <= 1:
        for j in jobs:
            out += _job(j)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(_job, jobs, chunksize=1):
            out += got
    return out


def check(jobs: int = JOBS, sample: int = 1, entries=None,
          synthetic_names: Sequence[str] = SYNTHETIC, rebuild: bool = True
          ) -> Dict[str, Any]:
    if rebuild:
        build()
    b = load()
    js, elig = plan(OUT, FILLS, PROFILES, sample, entries, synthetic_names)
    start = time.time()
    res = run_jobs(js, jobs)
    rep = {'entries': MS.summarize(res), 'selection': elig,
           'runs': len(res),
           'failures': sum(1 for r in res if not r.get('ok')),
           'strays': sum(r.get('strays') or 0 for r in res),
           'seconds': round(time.time() - start),
           'fills': ['%02x' % f for f in FILLS], 'profiles': list(PROFILES),
           'sizes': sizes(b), 'sample': sample}
    rep['paths_taken'] = {k: sorted(e['paths']) for k, e in
                          rep['entries'].items()}
    return rep


# ---------------------------------------------------------------------------
# The random checks: thrustMul, fixedSquare, times64, hurt32 (GAME.md 2.4
# "Arithmetic")
# ---------------------------------------------------------------------------

MATHREF = BUILD / 'native' / 'math' / 'mathref'
BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
EDGES32 = (0, 1, -1, 2, -2, 0x7FFFFFFF, -0x80000000, -0x7FFFFFFF, 0x10000,
           -0x10000, 0xFFFF, 0x8000, -0x8000, 0x7FFF0000, 0x00010001,
           0xFFFF8000, 0x80000000 - 0x10000, 0x00100000, 0x00008001)
EDGES16 = (0, 1, -1, 2, 5, 10, 20, 0x7FFF, -0x8000, 0x8000, 0x00FF, 0x0100)
LEVELTIMES = (0, 1, 15, 16, 31, 32, 33, 0xFFE0, 0xFFFF, 0x10000, 0x1001F,
              0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0xFFFFFFE0)
MODES = {'thrustMul': 0, 'fixedSquare': 1, 'times64': 2, 'hurt32': 3}
IN_SIZE = {0: 8, 1: 4, 2: 4, 3: 6}
OUT_SIZE = {0: 4, 1: 4, 2: 4, 3: 9}
MO_HANDLE = 0x0123              # the player's mobj in the bulk's machine


def inputs32(n: int, rnd: random.Random) -> List[int]:
    out = [v & 0xFFFFFFFF for v in EDGES32]
    while len(out) < n:
        out.append(rnd.randrange(1 << 32))
    return out[:n]


def native_bulk(b: RC.Build, mode: int, records: bytes) -> List[bytes]:
    """The native helper (pl_bulk mode) on each input record, as many runs
    as the banks take."""
    isz, osz = IN_SIZE[mode], OUT_SIZE[mode]
    per = min(BULK_ROOM // isz, BULK_ROOM // osz)
    n = len(records) // isz
    out: List[bytes] = []
    for start in range(0, n, per):
        k = min(per, n - start)
        img = G.Image(b, 0xA5, store=False)
        img.aux(BULK_IN, 0x0200, records[start * isz:(start + k) * isz])
        img.main(player_mo_address(b), u16(MO_HANDLE))
        work = Path(tempfile.mkdtemp(prefix='tmp-player-bulk-',
                                     dir=str(BUILD)))
        try:
            r = G.run(img, work, GL.MODES['ROUTINE'], 'pl_bulk',
                      regs=(mode, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise PartError('pl_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + k * osz])
        out += [data[i:i + osz] for i in range(0, len(data), osz)]
    return out


def player_mo_address(b: RC.Build) -> int:
    """G_PLAYER + PL_MO of the image's lgame.inc."""
    vals = {}
    for line in (b.obj / 'gen' / 'lgame.inc').read_text().splitlines():
        f = line.split()
        if len(f) >= 3 and f[1] == '=' and f[0] in ('G_PLAYER', 'PL_MO'):
            vals[f[0]] = int(f[2].lstrip('$'), 16)
    return vals['G_PLAYER'] + vals['PL_MO']


def think_ref() -> GC.Case:
    """A captured P_PlayerThink call: upstream's machine for the helpers
    (its D, DBR at the call)."""
    MS.use_cases(MYCASES)
    for run, p, _ in case_paths(THINK):
        return GC.load_case(p)
    raise PartError('no P_PlayerThink case (python3 tools/native/gparts/'
                    'player.py --capture)')


def mathref(case: GC.Case, name: str, items_in: Sequence[str],
            items_out: Sequence[str], records: bytes, out_size: int,
            pokes: Sequence[Tuple[int, bytes]] = ()) -> List[bytes]:
    """Upstream's helper name (p_user65.s or p_use65.s) on each input
    record (mathref batch, JSR's return), the RAM poked: the outputs."""
    import sight as SG
    unit = 'p_use65.s' if name == 'times64' else 'p_user65.s'
    pc = sym('%s:%s' % (unit, name))
    ram = bytearray(SG.ram_of(case))
    for a, d in pokes:
        ram[a:a + len(d)] = d
    work = Path(tempfile.mkdtemp(prefix='tmp-player-ref-', dir=str(BUILD)))
    try:
        (work / 'base.ram').write_bytes(bytes(ram))
        (work / 'entry').write_text(SG.entry_text(case, pc))
        spec = ['routine %s %06X' % (name, pc)] + \
            ['in %s' % x for x in items_in] + \
            ['out %s' % x for x in items_out]
        (work / 'spec').write_text('\n'.join(spec) + '\n')
        (work / 'cases').write_bytes(records)
        r = bounded.run([str(MATHREF), 'batch', str(work / 'base.ram'),
                         str(work / 'entry'), str(work / 'spec'), name,
                         str(work / 'cases'), str(work / 'out')],
                        timeout=1200, max_bytes=1 << 28,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        universal_newlines=True)
        if r.returncode:
            raise PartError('mathref: %s' % r.stdout[-1000:])
        data = (work / 'out').read_bytes()
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    step = out_size + 4
    return [data[i:i + out_size] for i in range(0, len(data), step)]


def random_check(n: int = 100_000, seed: int = 1,
                 b: Optional[RC.Build] = None,
                 names: Sequence[str] = tuple(MODES)) -> Dict[str, Any]:
    """Each helper on n inputs: upstream's (mathref) against the native's
    (pl_bulk), compared."""
    case = think_ref()
    b = b or load()
    rnd = random.Random(seed)
    out: Dict[str, Any] = {'inputs': n, 'seed': seed}
    mom = '%06X 4' % pl('MOMX')
    put = '%06X 4' % sym('p_user65.s:PU_T')
    lt = '%06X 4' % exported('_g_leveltime')
    dp = MS.dp_address(case, '_Dp', 0)
    for name in names:
        mode = MODES[name]
        if name in ('thrustMul', 'times64'):
            a = inputs32(n, rnd)
            m = inputs32(n, rnd) if name == 'thrustMul' else [0] * n
            recs = b''.join(s32(x) + (s32(y) if name == 'thrustMul' else
                                      b'') for x, y in zip(a, m))
            ups = mathref(case, name, ['a', 'x'] + (
                [put] if name == 'thrustMul' else []), ['a', 'x'], recs, 4)
            nat = native_bulk(b, mode, recs)
            bad = [(r.hex(), u.hex(), v.hex()) for r, u, v in zip(
                [recs[i * IN_SIZE[mode]:(i + 1) * IN_SIZE[mode]]
                 for i in range(n)], ups, nat) if u != v]
        elif name == 'fixedSquare':
            a = inputs32(n, rnd)
            ups = mathref(case, name, ['x', mom], ['a', 'x'],
                          b''.join(u16(0) + s32(x) for x in a), 4)
            nat = native_bulk(b, mode, b''.join(s32(x) for x in a))
            bad = [('%08X' % x, u.hex(), v.hex())
                   for x, u, v in zip(a, ups, nat) if u != v]
        else:                           # hurt32
            dmg = [v & 0xFFFF for v in EDGES16]
            while len(dmg) < n:
                dmg.append(rnd.randrange(1 << 16))
            lts = [v & 0xFFFFFFFF for v in LEVELTIMES]
            while len(lts) < n:
                lts.append(rnd.randrange(1 << 32))
            dmg, lts = dmg[:n], lts[:n]
            marker = b'\xA5' * 8
            stub = [(exported('P_DamageMobj'), b'\x6B')]     # RTL
            ups = mathref(case, name, ['a', lt, '%06X 8' % dp],
                          ['a', '%06X 8' % dp],
                          b''.join(u16(d) + s32(t) + marker
                                   for d, t in zip(dmg, lts)), 10,
                          pokes=stub)
            nat = native_bulk(b, mode, b''.join(u16(d) + s32(t)
                                                for d, t in zip(dmg, lts)))
            mo = s32(mo_of(case.entry))
            bad = []
            for d, t, u, v in zip(dmg, lts, ups, nat):
                called = u[2:10] != marker
                if called and not (u[2:6] == mo and u[6:10] == b'\0' * 4 and
                                   u[0:2] == u16(d)):
                    bad.append(('%04X %08X' % (d, t), 'upstream', u.hex()))
                    continue
                if bool(v[8] & 1) != called:
                    bad.append(('%04X %08X' % (d, t), u.hex(), v.hex()))
                elif called and v[0:8] != u16(MO_HANDLE) + b'\xFF' * 4 + \
                        u16(d):
                    bad.append(('%04X %08X' % (d, t), u.hex(), v.hex()))
            out.setdefault('hurt32_calls', sum(
                1 for u in ups if u[2:10] != marker))
        out[name] = {'compared': min(len(ups), len(nat)),
                     'different': len(bad) + abs(len(ups) - len(nat)),
                     'first': bad[:5]}
    return out


# ---------------------------------------------------------------------------
# The planted bugs (lean: three, the mistakes most likely to happen), each
# in a scratch copy of the part's sources, its image in a temporary
# directory, run on its check
# ---------------------------------------------------------------------------

PY = 'game/%s/' % PART
ADD_DELTA = """        clc                             ; viewheight += deltaviewheight
        ldx #0
:       lda PLR + PL_VIEWHEIGHT,x
        adc PLR + PL_DELTAVIEWHEIGHT,x
        sta PLR + PL_VIEWHEIGHT,x
        inx
        txa
        eor #4
        bne :-
"""
STEP = """@step:  lda PLR + PL_DELTAVIEWHEIGHT    ; delta: += FRACUNIT / 4, but not"""
PLANTS: Dict[str, Dict[str, Any]] = {
    # the view height clamped before adding the delta (GAME.md 2.4's
    # row): the squat under VIEWHEIGHT / 2
    'clamp-first': {'check': 'squat', 'bugs': [
        (PY + 'puser.s', ADD_DELTA, ''),
        (PY + 'puser.s', STEP, ADD_DELTA + STEP)]},
    # special 11 exiting at health 11 (the task's row): E1M8 at health 11
    'exit-at-11': {'check': 'e1m8-11', 'bugs': [
        (PY + 'puser.s', """        lda PLR + PL_HEALTH
        sbc #11""", """        lda PLR + PL_HEALTH
        sbc #12                         ; (planted: health <= 11)""")]},
    # the bob's square overflowing differently (GAME.md 2.4's row): the
    # carry of (alw * alw) >> 16 not taken into the high word: fixedSquare's
    # random check
    'square-carry': {'check': 'random:fixedSquare', 'bugs': [
        (PY + 'puser.s', """        bcc :+
        inc M_R + 2
        bne :+
        inc M_R + 3
:       rts""", """        bra :+                  ; (planted: no carry)
        inc M_R + 2
        bne :+
        inc M_R + 3
:       rts""")]},
}


def plant_jobs(plant: Dict[str, Any], obj: Path, limit: int = 40
               ) -> List[Tuple]:
    check_ = plant['check']
    if check_ in SYNTHETIC:
        js, _ = plan(obj, (0xA5,), (None,), entries=[synthetic_key(check_)],
                     synthetic_names=[check_])
        return [j for j in js if j[0] == 'synthetic']
    js, _ = plan(obj, (0xA5,), (None,), entries=[check_], synthetic_names=())
    return spread(js, limit)


def run_plant(name: str, count: int = 20_000) -> Dict[str, Any]:
    p = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-player-plant-', dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', p['bugs'])
        if p['check'].startswith('random:'):
            helper = p['check'].split(':')[1]
            r = random_check(count, b=load(obj), names=[helper])
            _BUILDS.clear()
            caught = r[helper]['different'] > 0
            return {'check': p['check'], 'runs': r[helper]['compared'],
                    'failed': r[helper]['different'], 'caught': caught,
                    'first': r[helper]['first'][:2]}
        res = run_jobs(plant_jobs(p, obj), JOBS)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        _BUILDS.clear()
    bad = [r for r in res if not r.get('ok')]
    return {'check': p['check'], 'runs': len(res), 'failed': len(bad),
            'caught': bool(bad),
            'first': [{k: r.get(k) for k in ('case', 'path', 'diff', 'error',
                                             'ended', 'stop') if r.get(k)}
                      for r in bad[:2]]}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def write_report(rep: Dict[str, Any], plants: Optional[Dict[str, Any]] = None,
                 rnd: Optional[Dict[str, Any]] = None) -> Path:
    out = {}
    if REPORT.exists():
        out = json.loads(REPORT.read_text())
    out.update(rep)
    out['format'] = 'game-part-report 1'
    out['part'] = PART
    out['wave'] = WAVE
    if plants is not None:
        out['plants'] = plants
    if rnd is not None:
        out['random'] = rnd
    out['build_kb'] = MS.du_kb(OUT)
    out['notes'] = [
        'lean checkpoint (the owner\'s rules of 2026-10-02): at most %d '
        'captured calls a routine, one fill ($A5), f121 only; the other '
        'fill and fastpath are the final integration\'s' % LIMIT,
        'clock: the call\'s time under f121 (fabric clocks); cpu_cycles: '
        'the W65C02S\'s cycles; every slot empty at the call (an upper '
        'bound)',
        'paths: P_PlayerThink by its tic\'s other calls (still: no '
        'movePlayer; atk: angleToAttacker; special: specialSector; use: '
        'P_UseLines; noway: PTR_NoWayTraverse) and the dispatch targets it '
        'reached; synthetic cases by name',
        'movePlayer, calcHeight, fixedSquare, onGround and thrustMul run '
        'inside every P_PlayerThink call, PTR_UseTraverse and '
        'PTR_NoWayTraverse inside the P_UseLines calls',
        'sizes: puser.s and puse.s; pltest.s is test-only (the driver\'s '
        'area)']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1, default=str) + '\n')
    return REPORT


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--jobs', type=int, default=JOBS)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--count', type=int, default=100_000)
    parser.add_argument('--entries', default='')
    parser.add_argument('--synthetic', default=None,
                        help='only these synthetic cases (comma list)')
    args = parser.parse_args(argv)
    status = 0
    if args.build:
        print(json.dumps(sizes(load(build())), indent=1))
    if args.capture:
        capture(args.jobs)
    if args.check:
        names = SYNTHETIC if args.synthetic is None else tuple(
            x for x in args.synthetic.split(',') if x)
        rep = check(args.jobs, args.sample,
                    [e for e in args.entries.split(',') if e] or None, names)
        write_report(rep)
        for k, e in sorted(rep['entries'].items()):
            print('%-34s %4d cases %4d runs %3d failed  cycles %s  S %s' % (
                k, len(e['cases']) if isinstance(e['cases'], (list, set))
                else e['cases'], e['runs'], e['failures'],
                e['cpu_cycles'].get('f121'), e['lowest_s']))
            for f in e['first_failures'][:3]:
                print('   ', json.dumps(f, default=str)[:900])
        print('runs %d, failures %d, stray writes %d, %d s' % (
            rep['runs'], rep['failures'], rep['strays'], rep['seconds']))
        status |= 1 if rep['failures'] or rep['strays'] else 0
    if args.random:
        r = random_check(args.count)
        print(json.dumps(r, indent=1))
        write_report({}, rnd=r)
        status |= 1 if any(r[k]['different'] for k in MODES) else 0
    if args.plants:
        pl_ = {}
        for n in PLANTS:
            pl_[n] = run_plant(n)
            print('%-20s %s' % (n, ('caught: %d of %d runs fail: %s' % (
                pl_[n]['failed'], pl_[n]['runs'], str(pl_[n]['first'])[:300]))
                if pl_[n]['caught'] else 'NOT CAUGHT (%d runs)' %
                pl_[n]['runs']))
        write_report({}, plants=pl_)
        status |= 0 if all(p['caught'] for p in pl_.values()) else 1
    if args.report:
        print(REPORT.read_text() if REPORT.exists() else 'no report yet')
    return status


if __name__ == '__main__':
    sys.exit(main())
