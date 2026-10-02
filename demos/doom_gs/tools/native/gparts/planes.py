#!/usr/bin/env python3
"""Part planes' checkpoint (milestone 10, docs/GAME.md 2.4 row planes, 3.5;
docs/game-parts/planes.md): routine mode on the part's entries, its
synthetic cases and its planted bugs, in the lean form the owner asked for
on 2026-10-02 (at most LEAN calls a routine, one poisoned machine, $A5).

Usage:  python3 tools/native/gparts/planes.py --log
        python3 tools/native/gparts/planes.py --capture
        python3 tools/native/gparts/planes.py --synthetic
        python3 tools/native/gparts/planes.py --check [--jobs 2]
        python3 tools/native/gparts/planes.py --plants
        python3 tools/native/gparts/planes.py --report

Everything it writes is under build/native/game/planes/ (the part's own
directory): the thinker log (logs/RUN.json.z: callFn's hits that enter
T_MoveFloor), the cases (cases/RUN/ROUTINE/hNNNNNNNN.case.z and each run's
base.ram.z, through tools/native/gamecap.py with its case directory pointed
here), the pool's paths and the choice (choice.json), the synthetic cases
(synthetic.json.z), report.json. The shared outputs
(build/native/game/shared/) are read only.

The run machinery is part secfind's (tools/native/gparts/secfind.py: Ref,
Prep, Native, ref_call, sounds) with part mobjstate's stray rule and
thinker-list checks, as wave 1's integration asked; this tool adds the
part's choice, paths, the scratch-block inputs and outputs ("sb:NAME" in
args.json), the sound events and the plants.

--log: callFn's hits that are T_MoveFloor's calls (a call log of demo3, the
only run with floor thinkers), as part secfind's thinker logs.

--capture: a pool of each entry's calls (every call when POOL or fewer,
else POOL spread evenly over the survey's runs; T_MoveFloor's at callFn,
each case checked to enter T_MoveFloor at the logged tic), then the choice:
first one call of each path the pool takes, then calls spread evenly over
the rest, LEAN in all (choice.json).

--synthetic: ref816 --call of captured calls with a thing made too tall to
fit (its height poked): a ceiling closing on a monster (T_MovePlaneCeiling,
crushed and the move undone), the same on a corpse (gibs) and on a dropped
item (removed), and changeSector on each kind of thing.

--check: the chosen and synthetic cases from the poisoned machine $A5 under
f121 and fastpath, compared with ref816 in gcanon.py's routine mode
(R1-R6), the declared outputs of src/native/game/planes/args.json, the
sector sound events (R6), no stray write. Writes report.json.

--plants: each planted bug built from a scratch copy of the part's sources
in a temporary directory (deleted), run on its named check, which must
fail.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

import secfind as SF  # noqa: E402  (wave 1's machinery)
import mobjstate as MS  # noqa: E402  (the shared stray rule)
from bridge.port import PortReader  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL  # noqa: E402
from ref816 import calls as CL  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'planes'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
LOGS = OUT / 'logs'
CHOICE = OUT / 'choice.json'
SYN = OUT / 'synthetic.json.z'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
SOURCE = SRC / 'game' / PART / 'planes.s'
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory

MPF = 'p_floor65.s:T_MovePlaneFloor'
MPC = 'p_floor65.s:T_MovePlaneCeiling'
CHECK = 'p_floor65.s:checkSector'
CHANGE = 'p_floor65.s:changeSector'
CLIP = 'p_floor65.s:heightClip'
MOVEFLOOR = 'p_floor65.s:T_MoveFloor'
ENTRIES = (MPF, MPC, CHECK, CHANGE, CLIP, MOVEFLOOR)
CALLFN = 'p_tick65.s:callFn'
FN_P = 'DC_ENTRY'               # callFn's JML [FN_P] operand (bank 0)
LEAN = 40                       # calls a routine (the owner's lean checks)
POOL = 120                      # calls captured a routine to choose from
FILLS = (0xA5,)                 # one poisoned machine (lean)
PROFILES = SF.PROFILES
BATCH = 40
SYN_FORMAT = 'planes-synthetic 1'
CHOICE_FORMAT = 'planes-choice 1'
TALL = 0x7FFF0000               # a height no sector holds (fixed_t)
# floormove_t's fields (p_floor65.s:38-44, upstream's own .equ's)
FM_TYPE, FM_TEXTURE, FM_DEST = 16, 19, 21


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def uconst() -> Dict[str, int]:
    return SF.uconst()


def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC) -> Path:
    """The part's test image (make -f game.mk part P=planes); its
    directory."""
    variables = ['P=%s' % PART]
    if game is not None:
        variables.append('GAME=%s' % game)
    G.make('part', variables, source)
    return (game or GL.GAME) / PART


def args() -> Dict[str, Dict[str, Any]]:
    d = json.loads(ARGS.read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise PartError('%s is not %s' % (ARGS, GR.ARGS_FORMAT))
    return dict(d['entries'])


def scratch_offsets(source: Path = SOURCE) -> Dict[str, int]:
    """planes.s's `SB_NAME = SB_PLANES + n` (and `= SB_PLANES`): name ->
    n."""
    out = {}
    for m in re.finditer(r'^(SB_\w+)\s*=\s*SB_PLANES(?:\s*\+\s*(\d+))?\s*(?:;|$)',
                         source.read_text(), re.M):
        out[m.group(1)] = int(m.group(2) or 0)
    return out


def sb_address(name: str) -> int:
    offs = scratch_offsets()
    if name not in offs:
        raise PartError('no scratch byte %s in planes.s' % name)
    return GL.scratch_blocks()[PART][0] + offs[name]


# ---------------------------------------------------------------------------
# The thinker log (--log): callFn's hits that enter T_MoveFloor
# ---------------------------------------------------------------------------

def thinker_log(run: str) -> Dict[str, Any]:
    table = CL.Linkmap()
    found: List[List[int]] = []
    state = {'tic': -1, 'calls': 0}

    def reader(handle) -> None:
        first = json.loads(handle.readline())
        if first.get('format') != CL.FORMAT:
            raise PartError('not a call log')
        rnames = [r['name'] for r in first['routines']]
        by_call: Dict[int, str] = {}
        for raw in handle:
            line = json.loads(raw)
            if line.get('end'):
                break
            name = rnames[line['routine']]
            if name == GC.TIC_NAME:
                state['tic'] = int.from_bytes(
                    bytes.fromhex(line['in']['mem'][0]), 'little')
            elif name == MOVEFLOOR:
                by_call[line['parent']] = name
            elif name == CALLFN:
                state['calls'] += 1
                if by_call.pop(line['call'], None) is not None:
                    found.append([line['hit'], state['tic']])
    routines = ['%s,name=%s,in=_g_gametic:4,entry=1' % (GC.TICKER,
                                                        GC.TIC_NAME),
                '%s,name=%s' % (CALLFN, CALLFN),
                '%s,name=%s,entry=1,jumps=1' % (MOVEFLOOR, MOVEFLOOR)]
    GC.check_disk()
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-planes-log-',
                                 dir=str(BUILD)))
    try:
        fifo = work / 'calls.fifo'
        os.mkfifo(str(fifo))
        opts = CL.options(routines, fifo, table) + ['--call-log-limit',
                                                    str(SF.LOG_LIMIT)]
        r = GC.machine(run, work, opts, reader=reader, fifo=fifo)
        if r['problems']:
            raise PartError('%s: %s' % (run, '; '.join(r['problems'])))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    want = survey_count(run, MOVEFLOOR)
    if want != len(found):
        raise PartError('%s: %d T_MoveFloor calls logged, the survey has %d'
                        % (run, len(found), want))
    out = {'format': 'planes-thinkers 1', 'run': run,
           'callfn_calls': state['calls'], 'calls': found}
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / (run + '.json.z')).write_bytes(zlib.compress(
        json.dumps(out, separators=(',', ':')).encode(), 6))
    return out


def load_log(run: str) -> Optional[Dict[str, Any]]:
    p = LOGS / (run + '.json.z')
    if not p.exists():
        return None
    return json.loads(zlib.decompress(p.read_bytes()))


def survey_count(run: str, key: str) -> int:
    sv = GC.survey_of(run)
    r = sv['routines'].get(key) if sv else None
    return r['calls'] if r else 0


# ---------------------------------------------------------------------------
# The calls, the pool and the choice
# ---------------------------------------------------------------------------

def calls_of(key: str) -> List[Tuple[str, int, int]]:
    """Every call of an entry over the survey's runs: (run, hit, tic);
    T_MoveFloor's hits are callFn's. The part's calls reach no dispatch
    target in the survey (checked: every call is eligible)."""
    out: List[Tuple[str, int, int]] = []
    for run in GC.RUNS:
        sv = GC.survey_of(run)
        r = sv['routines'].get(key) if sv else None
        if not r or not r['calls']:
            continue
        if any(r['reached'].values()):
            raise PartError('%s %s: a call reaches a dispatch target'
                            % (run, key))
        if key == MOVEFLOOR:
            lg = load_log(run)
            if lg is None:
                raise PartError('no thinker log of %s (--log)' % run)
            out += [(run, h, t) for h, t in lg['calls']]
        else:
            out += [(run, i + 1, t) for i, t in enumerate(r['tic'])]
    return out


def pool(key: str) -> List[Tuple[str, int, int]]:
    calls = calls_of(key)
    if len(calls) <= POOL:
        return calls
    return [calls[(i * len(calls)) // POOL] for i in range(POOL)]


def case_key(key: str) -> str:
    return CALLFN if key == MOVEFLOOR else key


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, case_key(key)) / ('h%08d.case.z' % hit)


def capture(keys: Sequence[str] = ENTRIES) -> int:
    made = 0
    for key in keys:
        by: Dict[str, Dict[int, int]] = {}
        for run, hit, tic in pool(key):
            by.setdefault(run, {})[hit] = tic
        for run, hits in sorted(by.items()):
            todo = sorted(h for h in hits
                          if not case_path(run, key, h).exists())
            if not todo:
                continue
            top = max(todo)
            tics = [hits.get(h, -1) for h in range(1, top + 1)]
            start = time.time()
            got = GC.capture(run, case_key(key), todo, tics, batch=BATCH,
                             say=say)
            made += len(got)
            say('%s %s: %d cases (%.0f s)' % (run, key, len(got),
                                              time.time() - start))
    bad = verify()
    if bad:
        raise PartError('%d callFn cases do not enter T_MoveFloor at their '
                        'tic: %s' % (len(bad), bad[:3]))
    return made


def verify() -> List[str]:
    """The callFn cases whose FN_P is not T_MoveFloor or whose gametic is
    not the logged one (ref816's --capture does not count a nested call:
    README "capturing at a dispatch stub")."""
    table = CL.Linkmap()
    fn_p = table.address(FN_P)
    want = table.address(MOVEFLOOR) & 0xFFFFFF
    gt = table.address('g_game65.s:_g_gametic')
    bad = []
    for run, hit, tic in pool(MOVEFLOOR):
        p = case_path(run, MOVEFLOOR, hit)
        if not p.exists():
            continue
        c = GC.load_case(p)
        got = int.from_bytes(c.entry.read(fn_p, 3), 'little')
        if got != want or int.from_bytes(c.entry.read(gt, 4),
                                         'little') != tic:
            bad.append(str(p))
    return bad


def _ptr(ref: 'SF.Ref', text: str, when: str = 'in') -> int:
    return int.from_bytes(ref.source(text, when), 'little') & 0xFFFFFF


def objects(s: Dict[str, Any], kind: str) -> Dict[int, Dict[str, Any]]:
    return s['objects'].get(kind, {})


def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def path_of(key: str, ref: 'SF.Ref') -> str:
    """The branches a call takes, from the reference's states."""
    s, o = ref.s_in, ref.s_out
    if key in (MPF, MPC):
        d = ref.source('s:4:2')[0]
        sec = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('sector',))
        res = ref.source('a', 'out')[0]
        n = len(objects(s, 'sector')[sec.id]['touching_thinglist'])
        return 'dir%s-res%d-%s' % ({0xFF: '-1', 1: '1'}.get(d, '0'), res,
                                   'things' if n else 'empty')
    if key == CHECK:
        sec = ref.ref(_ptr(ref, 'abs:p_floor65.s:MP_SEC:4'), ('sector',))
        nodes = objects(s, 'sector')[sec.id]['touching_thinglist']
        nofit = ref.source('a', 'out')[0]
        nbm = any(objects(s, 'mobj').get(n_['m_thing'].id, {}).get(
            'flags', 0) & uconst()['UC_MF_NOBLOCKMAP']
            for n_ in (objects(s, 'secnode')[x.id] for x in nodes)
            if n_['m_thing'] is not None and n_['m_thing'].kind == 'mobj')
        return 'n%s-nofit%d%s' % (min(len(nodes), 3) if len(nodes) < 3
                                  else '3+', nofit, '-noblockmap' if nbm
                                  else '')
    if key in (CHANGE, CLIP):
        th = ref.ref(_ptr(ref, 'dp:_Dp:4'), SF.kinds_of('mobj'))
        before = objects(s, th.kind)[th.id]
        after = objects(o, th.kind).get(th.id)
        if key == CLIP:
            onf = before['z'] == before['floorz']
            fits = ref.source('a', 'out')[0]
            moved = after is not None and after['z'] != before['z']
            return '%s-%s%s' % ('onfloor' if onf else 'air',
                                'fits' if fits else 'nofit',
                                '-zmoved' if moved else '')
        if after is None or after.get('free') or \
                after['function'] != before['function']:
            return 'removed'
        fits = s32(after['ceilingz'] - after['floorz']) >= s32(
            after['height']) or after['height'] == 0 and \
            after['state'] != before['state']
        if after['state'] != before['state']:
            return 'gibs'
        n0 = ref.source('abs:p_floor65.s:NOFIT:2')[0]
        n1 = ref.source('abs:p_floor65.s:NOFIT:2', 'out')[0]
        if not fits:
            return 'nofit-shootable' if n1 and not n0 else (
                'nofit-%s' % ('again' if n0 else 'not-shootable'))
        return 'fits'
    if key == MOVEFLOOR:
        fl = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('floor',))
        f = objects(s, 'floor')[fl.id]
        sec = f['sector'].id
        done = objects(o, 'sector')[sec]['floordata'] is None
        lt = int.from_bytes(ref.source('abs:_g_leveltime:2'), 'little')
        return 'dir%d%s%s' % (f['direction'], '-pastdest' if done else '',
                              '-stone' if lt & 7 == 0 else '')
    return 'call'


def pool_paths() -> Dict[str, Dict[str, str]]:
    """Each pooled case's path, by entry and case file (cached in
    choice.json with the choice)."""
    out: Dict[str, Dict[str, str]] = {}
    for key in ENTRIES:
        d = out.setdefault(key, {})
        for run, hit, _ in pool(key):
            p = case_path(run, key, hit)
            if not p.exists():
                continue
            ref = SF.Ref(GC.load_case(p))
            if ref.problems:
                d[str(p.relative_to(OUT))] = 'undecodable'
                continue
            d[str(p.relative_to(OUT))] = path_of(key, ref)
    return out


def choose(paths: Dict[str, Dict[str, str]]) -> Dict[str, List[str]]:
    """LEAN cases an entry: one of each path the pool takes (its first),
    then cases spread evenly over the rest."""
    out: Dict[str, List[str]] = {}
    for key, d in paths.items():
        names = [n for n in d if d[n] != 'undecodable']
        first: List[str] = []
        seen = set()
        for n in names:
            if d[n] not in seen:
                seen.add(d[n])
                first.append(n)
        first = first[:LEAN]
        rest = [n for n in names if n not in first]
        k = min(LEAN - len(first), len(rest))
        pick = first + [rest[(i * len(rest)) // k] for i in range(k)]
        out[key] = [n for n in names if n in set(pick)]
    return out


def write_choice() -> Dict[str, Any]:
    paths = pool_paths()
    d = {'format': CHOICE_FORMAT, 'lean': LEAN, 'pool': POOL,
         'paths': paths, 'chosen': choose(paths)}
    CHOICE.write_text(json.dumps(d, indent=1) + '\n')
    return d


def load_choice() -> Dict[str, Any]:
    if not CHOICE.exists():
        raise PartError('no %s (--capture)' % CHOICE)
    d = json.loads(CHOICE.read_text())
    if d.get('format') != CHOICE_FORMAT:
        raise PartError('%s is not %s' % (CHOICE, CHOICE_FORMAT))
    return d


# ---------------------------------------------------------------------------
# The synthetic cases: a thing too tall to fit (ref816 --call)
# ---------------------------------------------------------------------------

def _mobj_address(ref: 'SF.Ref', ident) -> int:
    """The upstream address of a mobj of the entry state."""
    return ref.r_in.ref_address(ident)


def synthetic_plan() -> List[Dict[str, Any]]:
    """From the chosen cases: changeSector on a thing made too tall (its
    height TALL) as it is (shootable or not), as a corpse (health 0) and as
    a dropped item (MF_DROPPED); T_MovePlaneCeiling closing (direction -1,
    a step) on a sector whose first touching thing is made too tall:
    crushed, the move undone; T_MovePlaneFloor raising (direction 1, a
    step) the same way; the corpse and the dropped item under a closing
    ceiling and a rising floor; a monster under a mover reaching its
    destination (pastdest, the move undone) and under a floor going down
    and a ceiling going up (a step: no restore whatever the check finds);
    heightClip in the air; T_MoveFloor reaching its destination, plain and
    as a donut's pool."""
    c = uconst()
    ch = load_choice()
    plan: List[Dict[str, Any]] = []
    o_h = c['UO_MO_HEIGHT']
    o_hp = c['UO_MO_HEALTH']
    o_fl = c['UO_MO_FLAGS']

    def thing_pokes(m, a: int, how: str) -> List[Tuple[int, bytes]]:
        out = [(a + o_h, TALL.to_bytes(4, 'little'))]
        if how == 'corpse':
            out.append((a + o_hp, (0).to_bytes(2, 'little')))
        elif how == 'dropped':
            hp = m.u16(a + o_hp)
            if hp == 0 or hp & 0x8000:
                out.append((a + o_hp, (1).to_bytes(2, 'little')))
            f = m.u32(a + o_fl) | c['UC_MF_DROPPED_HI'] << 16
            out.append((a + o_fl, f.to_bytes(4, 'little')))
        elif how == 'monster':
            hp = m.u16(a + o_hp)
            if hp == 0 or hp & 0x8000:
                out.append((a + o_hp, (1).to_bytes(2, 'little')))
            f = (m.u32(a + o_fl) | c['UC_MF_SHOOTABLE']) & \
                ~(c['UC_MF_DROPPED_HI'] << 16)
            out.append((a + o_fl, f.to_bytes(4, 'little')))
        return out
    # changeSector: the first chosen case of a live thing, in each form
    for name in ch['chosen'][CHANGE][:1]:
        case = GC.load_case(OUT / name)
        ref = SF.Ref(case)
        a = _ptr(ref, 'dp:_Dp:4')
        for how in ('monster', 'corpse', 'dropped'):
            plan.append({'key': CHANGE, 'base': name, 'note':
                         'changeSector on a too tall %s' % how,
                         'pokes': thing_pokes(case.entry, a, how)})
    # the movers: a chosen step with things in the sector
    for key, d, hows in (
            (MPC, 'dir-1-res0-things', ('monster', 'corpse', 'dropped')),
            (MPF, 'dir1-res0-things', ('monster', 'corpse', 'dropped')),
            (MPC, 'dir1-res2-things', ('monster',)),
            (MPF, 'dir-1-res2-things', ('monster',)),
            (MPC, 'dir1-res0-things', ('monster',)),
            (MPF, 'dir-1-res0-things', ('monster',))):
        names = [n for n in ch['chosen'][key] if ch['paths'][key][n] == d]
        for name in names[:1]:
            case = GC.load_case(OUT / name)
            ref = SF.Ref(case)
            sec = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('sector',))
            nodes = objects(ref.s_in, 'sector')[sec.id]['touching_thinglist']
            things = [objects(ref.s_in, 'secnode')[n.id]['m_thing']
                      for n in nodes]
            things = [t for t in things if t is not None and t.kind == 'mobj'
                      and not objects(ref.s_in, 'mobj')[t.id]['flags'] &
                      c['UC_MF_NOBLOCKMAP']]
            if not things:
                continue
            a = _mobj_address(ref, things[0])
            for how in hows:
                plan.append({'key': key, 'base': name, 'note':
                             '%s %s on a too tall %s' % (
                                 key.split(':')[1], d, how),
                             'pokes': thing_pokes(case.entry, a, how)})
    # the movers' destination beyond the other plane: a floor rising to a
    # dest above its ceiling (destheight = the ceiling) and a ceiling
    # closing to a dest below its floor (destheight = the floor), each with
    # the other plane half a unit away (pastdest at it), no thing
    table = CL.Linkmap()
    for key, d, dest, plane, other in (
            (MPF, 'dir1-res0-empty', 0x7FFF0000, 'ceilingheight',
             'floorheight'),
            (MPC, 'dir-1-res0-empty', 0x80010000, 'floorheight',
             'ceilingheight')):
        names = [n for n in ch['chosen'][key] if ch['paths'][key][n] == d]
        for name in names[:1]:
            case = GC.load_case(OUT / name)
            ref = SF.Ref(case)
            sec = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('sector',))
            sa = ref.r_in.ref_address(sec)
            near = objects(ref.s_in, 'sector')[sec.id][other] + (
                0x8000 if plane == 'ceilingheight' else -0x8000)
            dp = (case.regs_in['d'] + table.address('_Dp') -
                  table.direct_page + 4) & 0xFFFF
            off = c['UO_SEC_CEILINGHEIGHT'] if plane == 'ceilingheight' \
                else c['UO_SEC_FLOORHEIGHT']
            plan.append({'key': key, 'base': name, 'note':
                         '%s %s, dest beyond the %s' % (
                             key.split(':')[1], d, plane),
                         'pokes': [(dp, dest.to_bytes(4, 'little')),
                                   (sa + off, (near & 0xFFFFFFFF).to_bytes(
                                       4, 'little'))]})
    # heightClip on a thing in the air: a unit above its floor, and with its
    # top above its ceiling (z = ceilingz - height + 8 units: clamped, the
    # ceiling of a door's sector moving up 2 units a tic)
    for name in ch['chosen'][CLIP][:1]:
        case = GC.load_case(OUT / name)
        ref = SF.Ref(case)
        a = _ptr(ref, 'dp:_Dp:4')
        m = case.entry
        fz = s32(m.u32(a + c['UO_MO_FLOORZ']))
        cz = s32(m.u32(a + c['UO_MO_CEILINGZ']))
        h = s32(m.u32(a + o_h))
        for note, z in (('a unit above its floor', fz + 0x10000),
                        ('its top 8 units above its ceiling',
                         cz - h + 0x80000)):
            plan.append({'key': CLIP, 'base': name, 'note':
                         'heightClip on a thing %s' % note,
                         'pokes': [(a + c['UO_MO_Z'], (z & 0xFFFFFFFF)
                                    .to_bytes(4, 'little'))]})
    # T_MoveFloor reaching its destination (dest a unit past the floor):
    # rising, and rising as a donut's pool (DONUTRAISE, texture 5)
    names = [n for n in ch['chosen'][MOVEFLOOR]
             if ch['paths'][MOVEFLOOR][n].startswith('dir1')]
    for name in names[:1]:
        case = GC.load_case(OUT / name)
        ref = SF.Ref(case)
        fl = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('floor',))
        fa = ref.r_in.ref_address(fl)
        sec = objects(ref.s_in, 'floor')[fl.id]['sector']
        floor = objects(ref.s_in, 'sector')[sec.id]['floorheight']
        dest = [(fa + FM_DEST, ((floor + 0x8000) & 0xFFFFFFFF)
                 .to_bytes(4, 'little'))]
        plan.append({'key': MOVEFLOOR, 'base': name, 'note':
                     'T_MoveFloor rising to its destination', 'pokes': dest})
        plan.append({'key': MOVEFLOOR, 'base': name, 'note':
                     'T_MoveFloor rising to its destination, a donut',
                     'pokes': dest + [
                         (fa + FM_TYPE, c['UC_DONUTRAISE'].to_bytes(
                             2, 'little')),
                         (fa + FM_TEXTURE, (5).to_bytes(2, 'little'))]})
    return plan


def write_synthetic() -> int:
    recs = []
    for rec in synthetic_plan():
        base = GC.load_case(OUT / rec['base'])
        case = GC.call_case(base, rec['pokes'], note=rec['note'])
        recs.append(dict(rec, pokes=[[a, d.hex()] for a, d in rec['pokes']],
                         call=case.header['call'],
                         writes=[[a, case.after.read(a, n).hex()]
                                 for a, n in case.header['writes']]))
    SYN.write_bytes(zlib.compress(json.dumps(
        {'format': SYN_FORMAT, 'records': recs},
        separators=(',', ':')).encode(), 6))
    return len(recs)


def load_synthetic() -> List[Dict[str, Any]]:
    if not SYN.exists():
        raise PartError('no synthetic cases %s (--synthetic)' % SYN)
    d = json.loads(zlib.decompress(SYN.read_bytes()))
    if d.get('format') != SYN_FORMAT:
        raise PartError('%s is not %s' % (SYN, SYN_FORMAT))
    return d['records']


def synthetic_case(rec: Dict[str, Any]) -> GC.Case:
    b = GC.load_case(OUT / rec['base'])
    entry = b.entry.copy()
    entry.header = b.entry.header
    for a, d in rec['pokes']:
        entry.write(a, bytes.fromhex(d))
    after = entry.copy()
    for a, d in rec['writes']:
        after.write(a, bytes.fromhex(d))
    header = dict(b.header, note=rec['note'], call=rec['call'], hit=0,
                  writes=[[a, len(d) // 2] for a, d in rec['writes']])
    return GC.Case(header, entry, after, None)


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

class Prep(SF.Prep):
    """secfind's Prep with the part's own input form: "sb:NAME", a byte of
    the scratch block."""

    def inputs(self):
        spec = self.spec
        own = [i for i in spec.get('in', []) if i['to'].startswith('sb:')]
        self.spec = dict(spec, **{'in': [i for i in spec.get('in', [])
                                         if i not in own]})
        try:
            regs, pokes = super().inputs()
        finally:
            self.spec = spec
        for item in own:
            data = self.ref.source(item['from'])
            n = item.get('bytes', len(data))
            pokes.append((sb_address(item['to'][3:]),
                          data[:n].ljust(n, b'\0')))
        return regs, pokes


def outputs(prep: 'SF.Prep', nat: 'SF.Native', m) -> List[str]:
    """The declared outputs against upstream's: a, x, y, ax, zp:NAME and
    sb:NAME (the scratch block's byte)."""
    lab = nat.b.labels
    regs = {'a': G.card_byte(m, lab['dg_ra']),
            'x': G.card_byte(m, lab['dg_rx']),
            'y': G.card_byte(m, lab['dg_ry'])}
    out = []
    for item in prep.spec.get('out', []):
        nv = item['native']
        n = item.get('bytes', 2)
        if nv == 'ax':
            value = regs['a'] | regs['x'] << 8
        elif nv in regs:
            value = regs[nv]
        elif nv.startswith('zp:') or nv.startswith('sb:'):
            a = GR.zp_address(nv[3:]) if nv.startswith('zp:') else \
                sb_address(nv[3:])
            value = int.from_bytes(bytes(m.main[a:a + n]), 'little')
        else:
            raise PartError('a native output %r' % nv)
        want = int.from_bytes(prep.ref.source(item['upstream'], 'out'),
                              'little')
        mask = (1 << (8 * n)) - 1
        if value & mask != want & mask:
            out.append('output %s (%s): %X, upstream %X' % (
                nv, item['upstream'], value & mask, want & mask))
    return out


def expected_sector_sounds(prep: 'SF.Prep') -> List[Tuple[int, int, int,
                                                           int]]:
    """The sector sounds (S_StartSound2, kind 1) upstream's call makes:
    T_MoveFloor's stone sound when (leveltime & 7) == 0, then its stop
    sound when the floor reached its destination (its sector's floordata
    none after the call); the other entries make none."""
    if prep.key != MOVEFLOOR:
        return []
    ref = prep.ref
    s = ref.s_in
    c = uconst()
    tic = s['globals']['g_game65.s:_g_gametic'] & 0xFFFF
    fl = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('floor',))
    sec = objects(s, 'floor')[fl.id]['sector'].id
    lt = int.from_bytes(ref.source('abs:_g_leveltime:2'), 'little')
    out = []
    if lt & 7 == 0:
        out.append((tic, 1, c['UC_SFX_STNMOV'], 0x8000 | sec))
    if objects(ref.s_out, 'sector')[sec]['floordata'] is None:
        out.append((tic, 1, c['UC_SFX_PSTOP'], 0x8000 | sec))
    return out


def allowed_main(b) -> List[Tuple[int, int]]:
    """mobjstate's places (the shared stray rule of wave 2's integration)
    and the parts' scratch blocks (W $9A00-$9DFF: R1)."""
    lo, hi = GL.WR['SCRATCH']
    return MS.allowed_main(b) + [(lo, hi)]


def stray(writes, b, header: Dict[str, Any]) -> List[str]:
    """CPU writes outside the allowed places (mobjstate.stray's rule with
    the scratch blocks)."""
    allowed = allowed_main(b)
    desc = b.segments['DESC']
    drv = b.segments['DRIVER']
    loader = b.segments['RLOAD']
    far = b.segments['RFAR']
    aux = MS.allowed_aux(header)
    mfar = b.segments.get('MATHFAR')
    patched = MS.mt_far_operands(b)
    out = []
    for w in writes:
        if w.storage == 'main':
            if w.offset < 0x0200 or any(lo <= w.offset < hi
                                         for lo, hi in allowed):
                continue
            if loader[0] <= w.pc <= loader[1] and 0x6000 <= w.offset:
                continue
            if far[0] <= w.pc <= far[1] and \
                    GL.WR['SLOT1'][0] <= w.offset < GL.WR['SLOT2'][1]:
                continue
        elif w.storage == 'lc' and drv[0] <= w.pc <= drv[1] and (
                desc[0] <= w.offset <= desc[1] or w.offset >= 0xFFFE or
                any(lo <= w.offset < hi for lo, hi in allowed)):
            continue
        elif w.storage == 'lc1' and mfar and \
                mfar[0] <= w.pc <= mfar[1] and w.offset in patched:
            continue
        elif w.storage == 'aux' and any(
                lo <= w.offset < hi for lo, hi in aux.get(w.bank, ())):
            continue
        out.append('pc $%04X wrote %s %d $%04X' % (w.pc, w.storage, w.bank,
                                                     w.offset))
    return out


def run_one(prep: 'SF.Prep', nat: 'SF.Native', fill: int, profile: str
            ) -> Dict[str, Any]:
    """One run of a case: the canonical state after the call against the
    reference's (routine mode), the declared outputs, the sector sound
    events, the native thinker list's checks (mobjstate's), the stray
    writes; the cycles from the routine's entry to its return, the lowest
    S."""
    spec = prep.spec
    res: Dict[str, Any] = {'entry': prep.key, 'fill': '%02x' % fill,
                           'profile': profile, 'ok': False}
    if prep.ref.problems:
        res['error'] = 'bridge: ' + '; '.join(prep.ref.problems[:3])
        return res
    img = prep.image(nat, fill)
    prep.pre_state(img, fill)
    entry = nat.b.labels[spec['native']]
    img.poke_word('dg_entry', entry)
    img.poke_label('dg_grp', bytes([nat.group(spec['native'])]))
    events = ['pc %X@1 snapshot start' % entry,
              'pc %X@1 snapshot ret' % nat.ret]
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-planes-', dir=str(BUILD)))
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), events=events,
                  banks=list(prep.banks) + [LL.GTEST],
                  profile=profile, write_log=MS.LOG_RANGES,
                  cycles=SF.RUN_CYCLES)
        ended = r.ended()
        res['ended'] = ended
        res['lowest_s'] = r.state.get('lowest_s')
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                res['stop'] = G.stop_codes(G.load_snapshot(p))
            return res
        c0, c1 = SF.snapshot_cycles(work, 'start'), \
            SF.snapshot_cycles(work, 'ret')
        res['cycles'] = c1 - c0 if c0 is not None and c1 is not None \
            else None
        if c0 is None:
            raise PartError('no snapshot at the routine\'s entry')
        writes = MS.read_log(work / 'writes.log')
        st = stray([w for _, w in writes], nat.b, prep.header)
        res['stray'] = len(st)
        res['stray_first'] = st[:4]
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    from native import setupcheck as SC
    nat_state = PortReader(prep.mf).read(SC.port_memory(m))
    diff = gcanon.compare(prep.ref.s_out, nat_state, 'routine')
    diff += outputs(prep, nat, m)
    diff += MS.native_checks(m)
    got = SF.sounds(m)
    res['sounds'] = len(got)
    res['mobj_sounds'] = sum(1 for e in got if e[1] != 1)
    want = expected_sector_sounds(prep)
    mine = [e for e in got if e[1] == 1]
    if mine != want:
        diff.append('sector sound events %s, expected %s' % (mine[:4],
                                                             want[:4]))
    if st:
        diff.append('%d stray writes: %s' % (len(st), st[:4]))
    res['diff'] = diff[:12]
    res['ok'] = not diff
    return res


# ---------------------------------------------------------------------------
# The checkpoint (--check)
# ---------------------------------------------------------------------------

def _check_job(job) -> List[Dict[str, Any]]:
    items, obj, fills, profiles = job
    nat = SF.Native(Path(obj))
    spec_all = args()
    out: List[Dict[str, Any]] = []
    for kind, key, item in items:
        try:
            if kind == 'case':
                name = item
                case = GC.load_case(OUT / item)
            else:
                name = 'synthetic: %s' % item['note']
                case = synthetic_case(item)
            prep = Prep(case, key, spec_all[key])
            path = path_of(key, prep.ref)
        except Exception as error:      # reported per case, never hidden
            out.append({'case': name, 'entry': key, 'ok': False,
                        'synthetic': kind != 'case',
                        'error': '%s: %s' % (type(error).__name__, error)})
            continue
        for fill in fills:
            for profile in profiles:
                try:
                    r = run_one(prep, nat, fill, profile)
                except Exception as error:
                    r = {'entry': key, 'fill': '%02x' % fill,
                         'profile': profile, 'ok': False,
                         'error': '%s: %s' % (type(error).__name__, error)}
                r.update(case=name, path=path, synthetic=kind != 'case')
                out.append(r)
    return out


def check_jobs(keys: Sequence[str] = ENTRIES, synthetic: bool = True,
               captured: bool = True, obj: Path = OUT,
               fills: Sequence[int] = FILLS,
               profiles: Sequence[str] = PROFILES, select=None,
               sample: int = 1, chunk: int = 8) -> List[Tuple]:
    items: List[Tuple[str, str, Any]] = []
    if captured:
        ch = load_choice()
        for key in keys:
            names = [n for n in ch['chosen'].get(key, [])
                     if select is None or select(key, ch['paths'][key][n])]
            items += [('case', key, n) for n in names[::sample]]
    if synthetic:
        recs = [r for r in load_synthetic() if r['key'] in keys and
                (select is None or select(r['key'], r['note']))]
        items += [('synthetic', r['key'], r) for r in recs[::sample]]
    return [(items[i:i + chunk], str(obj), tuple(fills), tuple(profiles))
            for i in range(0, len(items), chunk)]


def run_jobs(jobs: List[Tuple], workers: int = 2,
             progress: bool = True) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    start = time.time()
    if workers <= 1:
        for j in jobs:
            out += _check_job(j)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool_:
        for i, got in enumerate(pool_.map(_check_job, jobs)):
            out += got
            if progress and (i + 1) % 5 == 0:
                say('  %d of %d jobs, %d runs, %d failed (%.0f s)' % (
                    i + 1, len(jobs), len(out),
                    sum(1 for r in out if not r.get('ok')),
                    time.time() - start))
    return out


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ch = load_choice() if CHOICE.exists() else {'paths': {}}
    entries: Dict[str, Any] = {}
    for key in ENTRIES:
        rs = [r for r in results if r.get('entry') == key]
        cases = {(r.get('case'), bool(r.get('synthetic'))) for r in rs}
        pool_paths_ = sorted(set(ch['paths'].get(key, {}).values()))
        run_paths = sorted({r['path'] for r in rs if 'path' in r and
                            not r.get('synthetic')})
        e: Dict[str, Any] = {
            'calls_in_survey': sum(survey_count(run, key)
                                   for run in GC.RUNS),
            'cases_eligible': sum(survey_count(run, key)
                                  for run in GC.RUNS),
            'cases_pooled': len(ch['paths'].get(key, {})),
            'cases_captured': sum(1 for _, s in cases if not s),
            'cases_synthetic': sum(1 for _, s in cases if s),
            'runs': len(rs),
            'failures': sum(1 for r in rs if not r.get('ok')),
            'stray_writes': sum(r.get('stray') or 0 for r in rs),
            'mobj_sound_events': sum(r.get('mobj_sounds') or 0 for r in rs),
            'paths_in_pool': pool_paths_, 'paths_run': run_paths,
            'paths_synthetic': sorted({r['case'] for r in rs
                                       if r.get('synthetic')}),
            'cycles': {}}
        for profile in PROFILES:
            cyc = sorted(r['cycles'] for r in rs if r.get('profile') ==
                         profile and r.get('cycles') is not None)
            if cyc:
                mhz = SF.fabric_mhz(profile)
                e['cycles'][profile] = {
                    'median': cyc[len(cyc) // 2], 'worst': cyc[-1],
                    'median_us': round(cyc[len(cyc) // 2] / mhz, 1),
                    'worst_us': round(cyc[-1] / mhz, 1),
                    'unit': 'fabric clocks (%g MHz), from the routine\'s '
                            'entry to its return' % mhz}
        ls = [r['lowest_s']['s'] for r in rs if isinstance(
            r.get('lowest_s'), dict)]
        e['lowest_s'] = min(ls) if ls else None
        e['first_failures'] = [r for r in rs if not r.get('ok')][:3]
        entries[key] = e
    return entries


# ---------------------------------------------------------------------------
# The planted bugs (--plants): the three most likely mistakes (lean)
# ---------------------------------------------------------------------------

PLANTS = {
    # the things visited by the sector's thing list (snext), not by its
    # touching-thing (node) list
    'sector-list': ('things', [(
        '''@again: jsr cs_head             ; do: the first unvisited node''',
        '''@again: jmp @plant              ; (planted)'''), (
        '''@done:  lda SB_NOFIT
        rts''',
        '''@done:  lda SB_NOFIT
        rts
@plant: SECTOR                  ; (planted: the sector's thing
        ldy #SEC_THINGS         ;   list, snext, each thing once)
        lda (GC_SP),y
        sta SB_TH
        iny
        lda (GC_SP),y
        sta SB_TH+1
@walk:  lda SB_TH+1
        cmp #$FF
        beq @done
        lda SB_TH
        ldx SB_TH+1
        jsr mo_get
        ldy #TH_SNEXT
        lda (GC_MP),y
        sta SB_NODE
        iny
        lda (GC_MP),y
        sta SB_NODE+1
        ldy #ML_B + MB_FLAGS
        lda (GC_MP),y
        and #<UC_MF_NOBLOCKMAP_LO
        bne @nx
        lda SB_TH
        ldx SB_TH+1
        FCALL changeSector
@nx:    lda SB_NODE
        sta SB_TH
        lda SB_NODE+1
        sta SB_TH+1
        bra @walk''')]),
    # the move not undone when a thing does not fit (crushStep, toDest)
    'not-undone': ('crush', [(
        '''        jsr mp_set
        beq mp_okay
        jsr mp_restore''',
        '''        jsr mp_set
        beq mp_okay
        nop                     ; (planted: no restore)
        nop
        nop''')]),
    # visited not reset before the walk
    'visited-kept': ('things', [(
        '''        stz API_W               ; visited = 0 on every node''',
        '''        bra @again              ; (planted: visited kept)''')]),
}


def plant_build(name: str, tmp: Path) -> Path:
    _, edits = PLANTS[name]
    src = tmp / 'src'
    files = list(G.PLANT_COPY) + ['game/%s/%s' % (PART, f) for f in
                                  ('part.mk', 'planes.s')]
    for f in files:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    target = src / 'game' / PART / 'planes.s'
    text = target.read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise PartError('the planted bug %s no longer applies: %r' % (
                name, old[:60]))
        text = text.replace(old, new)
    target.write_text(text)
    return build(game=tmp / 'game', source=src)


def plant_jobs(check: str, obj: Path, sample: int = 1) -> List[Tuple]:
    one = dict(fills=(FILLS[0],), profiles=(PROFILES[0],), sample=sample)
    if check == 'things':       # checkSector's cases with things
        return check_jobs(keys=(CHECK,), synthetic=False, obj=obj,
                          select=lambda k, p: not p.startswith('n0'), **one)
    if check == 'crush':        # the movers' synthetic crushes
        return check_jobs(keys=(MPF, MPC), captured=False, obj=obj, **one)
    raise PartError('no check %s' % check)


def plants(names: Optional[Sequence[str]] = None,
           sample: int = 1) -> Dict[str, Any]:
    out = {}
    for name in (names or list(PLANTS)):
        check = PLANTS[name][0]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-planes-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            res = run_jobs(plant_jobs(check, obj, sample), workers=2,
                           progress=False)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        bad = [r for r in res if not r.get('ok')]
        r = {'check': check, 'runs': len(res), 'failed': len(bad),
             'caught': bool(bad),
             'first': (bad[0].get('diff') or [bad[0].get('error') or
                                              bad[0].get('ended')])[:2]
             if bad else None}
        out[name] = r
        say('%-14s %-7s %s' % (name, check, 'caught: %d of %d runs fail, %s'
                               % (r['failed'], r['runs'], r['first'])
                               if r['caught'] else 'NOT CAUGHT (%d runs)' %
                               r['runs']))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)
LABELS = ('T_MovePlaneFloor', 'T_MovePlaneCeiling', 'checkSector',
          'changeSector', 'heightClip', 'T_MoveFloor')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (planes.o) against its budget; each routine's
    bytes and group."""
    b = G.load_build(obj, IMAGE)
    text = (obj / (IMAGE + '.map')).read_text()
    mods = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    chunks: List[Tuple[str, int, int]] = []
    module = None
    for line in mods.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module == PART and f and f[0] in b.segments:
            off = next(int(x[5:], 16) for x in f if x.startswith('Offs='))
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            lo = b.segments[f[0]][0] + off
            chunks.append((f[0], lo, lo + size))
    nat = SF.Native(obj)
    routines = {}
    for seg, lo, hi in chunks:
        g = int(seg[4:]) if seg.startswith('GGRP') else 0
        inside = sorted((b.labels[n], n) for n in LABELS
                        if lo <= b.labels[n] < hi and nat.group(n) == g)
        for k, (a, n) in enumerate(inside):
            end = inside[k + 1][0] if k + 1 < len(inside) else hi
            routines[n] = {'bytes': end - a, 'group': nat.group(n),
                           'segment': seg}
    total = sum(hi - lo for _, lo, hi in chunks)
    return {'bytes': total, 'budget': BUDGET, 'upstream': UPSTREAM_BYTES,
            'over_10_percent': total > BUDGET * 1.1, 'routines': routines}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def du_kb(path: Path) -> int:
    r = subprocess.run(['du', '-sk', str(path)], stdout=subprocess.PIPE,
                       universal_newlines=True)
    return int(r.stdout.split()[0]) if r.returncode == 0 else -1


def write_report(results: Optional[Sequence[Dict[str, Any]]] = None,
                 **parts) -> Dict[str, Any]:
    rep: Dict[str, Any] = {}
    if REPORT.exists():
        rep = json.loads(REPORT.read_text())
    rep.update(format='game-part-report 1', part=PART,
               wave=next(p['wave'] for p in GL.PARTS if p['name'] == PART),
               lean='at most %d calls a routine (chosen by path from a pool '
                    'of %d), fill $A5 only (the owner\'s lean checks of '
                    '2026-10-02)' % (LEAN, POOL),
               fills=['%02x' % f for f in FILLS], profiles=list(PROFILES),
               exclusions=[n for n, _, _ in gcanon.ROUTINE_EXCLUSIONS])
    if results is not None:
        rep['entries'] = summarize(results)
        rep['runs'] = len(results)
        rep['failures'] = sum(1 for r in results if not r.get('ok'))
        rep['stray_writes'] = sum(r.get('stray') or 0 for r in results)
        ls = [r['lowest_s']['s'] for r in results
              if isinstance(r.get('lowest_s'), dict)]
        rep['lowest_s'] = min(ls) if ls else None
    rep.update(parts)
    rep['build_kb'] = du_kb(OUT)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=1, default=str) + '\n')
    return rep


def print_report(rep: Dict[str, Any]) -> None:
    for key, e in rep.get('entries', {}).items():
        cyc = '; '.join('%s %s/%s us' % (p, c['median_us'], c['worst_us'])
                        for p, c in e['cycles'].items())
        say('%-30s %3d+%-2d cases %4d runs %d failed %d stray, S %s; %s' % (
            key, e['cases_captured'], e['cases_synthetic'], e['runs'],
            e['failures'], e['stray_writes'], e['lowest_s'], cyc))
    if 'sizes' in rep:
        sz = rep['sizes']
        say('bytes %d of %d (upstream %d)' % (sz['bytes'], sz['budget'],
                                             sz['upstream']))
    for name, r in rep.get('plants', {}).items():
        say('planted %-14s %s' % (name, 'caught' if r['caught'] else
                                  'NOT CAUGHT'))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--log', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--keys', default=None)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--json', type=Path)
    a = parser.parse_args(argv)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if a.log:
        for run in GC.RUNS:
            if survey_count(run, MOVEFLOOR):
                lg = thinker_log(run)
                say('%s: %d T_MoveFloor calls of %d callFn calls' % (
                    run, len(lg['calls']), lg['callfn_calls']))
        return 0
    if a.capture:
        keys = a.keys.split(',') if a.keys else list(ENTRIES)
        say('%d cases made' % capture(keys))
        d = write_choice()
        for key in ENTRIES:
            ps: Dict[str, int] = {}
            for p in d['paths'][key].values():
                ps[p] = ps.get(p, 0) + 1
            say('%s: %d pooled, %d chosen; %s' % (
                key, len(d['paths'][key]), len(d['chosen'][key]), ps))
        return 0
    if a.synthetic:
        say('%d synthetic cases' % write_synthetic())
        return 0
    if a.check:
        keys = a.keys.split(',') if a.keys else list(ENTRIES)
        start = time.time()
        build()
        jobs = check_jobs(keys)
        say('%d jobs' % len(jobs))
        res = run_jobs(jobs, a.jobs)
        rep = write_report(res, sizes=sizes(), check_seconds=round(
            time.time() - start))
        if a.json:
            a.json.write_text(json.dumps(res, indent=1) + '\n')
        print_report(rep)
        return 1 if rep['failures'] else 0
    if a.plants:
        build()
        r = plants(a.keys.split(',') if a.keys else None)
        write_report(plants=r)
        return 0 if all(x['caught'] for x in r.values()) else 1
    if a.report:
        print_report(json.loads(REPORT.read_text()))
        return 0
    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
