#!/usr/bin/env python3
"""Part movers' checkpoint (milestone 10, docs/GAME.md 2.4 row movers, 3.5;
docs/game-parts/movers.md): routine mode on the door and plat thinkers and
partLight, their synthetic cases, mulExt's random check and the planted
bugs, in the lean form the owner asked for on 2026-10-02 (at most LEAN
calls a routine, chosen by path; one poisoned machine, $A5).

Usage:  python3 tools/native/gparts/movers.py --log
        python3 tools/native/gparts/movers.py --capture
        python3 tools/native/gparts/movers.py --synthetic
        python3 tools/native/gparts/movers.py --check [--jobs 2]
        python3 tools/native/gparts/movers.py --random [--count N]
        python3 tools/native/gparts/movers.py --plants
        python3 tools/native/gparts/movers.py --report

Everything it writes is under build/native/game/movers/ (the part's own
directory): the call logs' summaries (logs/RUN.json.z), the cases
(cases/RUN/ROUTINE/hNNNNNNNN.case.z and each run's base.ram.z, through
tools/native/gamecap.py with its case directory pointed here), the choice
(choice.json), the synthetic cases (synthetic.json.z), report.json. The
shared outputs (build/native/game/shared/) are read only.

--log: one ref816 call log a run (the survey's runs with door or plat
calls): callFn, the two thinkers (entered by JML [FN_P]: jumps=1),
partLight, and what they call: T_MovePlaneCeiling and T_MovePlaneFloor
(the direction at 4,s, the result in A), changeSector (a thing in the
moving sector), S_StartSound2 (the sound and its sector), P_RemoveThinker,
P_FindSectorFromLineTag and FixedApproxDiv (partLight's light work). Each
thinker call gets its path from what it called (a summary a call, no
memory kept), and its sound events, upstream's own.

--capture: the choice, LEAN calls an entry: first one call of each path
the logs show, then calls spread evenly over the rest; captured at callFn
(the thinkers: each case checked to enter its thinker at the logged tic)
and at partLight's JSR.

--synthetic: ref816 --call of chosen calls with pokes: a door closing on a
monster (a too-tall thing in its sector: crushed, up again with the open
sound), a plat waiting with a thing on it (its count ending and not), a
plat rising onto a too-tall thing, a raise plat reaching its top at the
stone sound's tic, partLight with a light tag on a tagged line at levels
below 0, between, and above FRACUNIT.

--check: the chosen and synthetic cases from the poisoned machine $A5
under f121 and fastpath, compared with ref816 in gcanon.py's routine mode
(R1-R6), the sector sound events (R6: upstream's from the call log for a
captured call, the model of expected_sounds for a synthetic one, the model
also checked against the log), no stray write. Writes report.json.

--random: mulExt (GAME.md 2.4 "Arithmetic") on 100,000 inputs: upstream's
on ref816 (tools/native/math's mathref batch) against the native (mv_bulk).

--plants: each planted bug built from a scratch copy of the part's sources
in a temporary directory (deleted), run on its named check, which must
fail.
"""

import argparse
import json
import random
import shutil
import struct
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
PART = 'movers'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
LOGS = OUT / 'logs'
CHOICE = OUT / 'choice.json'
SYN = OUT / 'synthetic.json.z'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
SOURCE = SRC / 'game' / PART / 'movers.s'
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory

DOOR = 'p_doors65.s:T_VerticalDoor'
LIGHT = 'p_doors65.s:partLight'
PLAT = 'p_plats65.s:T_PlatRaise'
ENTRIES = (DOOR, LIGHT, PLAT)
THINKERS = (DOOR, PLAT)
CALLFN = 'p_tick65.s:callFn'
FN_P = 'DC_ENTRY'               # callFn's JML [FN_P] operand (bank 0)
MPC = 'p_floor65.s:T_MovePlaneCeiling'
MPF = 'p_floor65.s:T_MovePlaneFloor'
CHANGE = 'p_floor65.s:changeSector'
SOUND2 = 'S_StartSound2'
REMOVE = 'P_RemoveThinker'
FINDTAG = 'P_FindSectorFromLineTag'
APPROX = 'FixedApproxDiv'
LEAN = 40                       # calls a routine (the owner's lean checks)
FILLS = (0xA5,)                 # one poisoned machine (lean)
PROFILES = SF.PROFILES
BATCH = 40
LOG_FORMAT = 'movers-log 1'
CHOICE_FORMAT = 'movers-choice 1'
SYN_FORMAT = 'movers-synthetic 1'
TALL = 0x7FFF0000               # a height no sector holds (fixed_t)


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def uconst() -> Dict[str, int]:
    return SF.uconst()


def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC,
          test: bool = True) -> Path:
    """The part's test image (make -f game.mk part P=movers MV_TEST=1);
    its directory."""
    variables = ['P=%s' % PART]
    if test:
        variables.append('MV_TEST=1')
    if game is not None:
        variables.append('GAME=%s' % game)
    G.make('part', variables, source)
    return (game or GL.GAME) / PART


def args() -> Dict[str, Dict[str, Any]]:
    d = json.loads(ARGS.read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise PartError('%s is not %s' % (ARGS, GR.ARGS_FORMAT))
    return dict(d['entries'])


def survey_count(run: str, key: str) -> int:
    sv = GC.survey_of(run)
    r = sv['routines'].get(key) if sv else None
    return r['calls'] if r else 0


def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


# ---------------------------------------------------------------------------
# The call logs (--log): each thinker call's path and sounds, from what it
# called
# ---------------------------------------------------------------------------

def _hexint(text: str) -> int:
    return int.from_bytes(bytes.fromhex(text), 'little')


def thinker_log(run: str) -> Dict[str, Any]:
    """The run's door, plat and partLight calls: [hit, tic, summary]; a
    thinker's hit is callFn's."""
    table = CL.Linkmap()
    c = uconst()
    soundorg = c['UO_SEC_SOUNDORG']
    sec_size = c['US_SEC']
    out: Dict[str, List[List[Any]]] = {DOOR: [], PLAT: [], LIGHT: []}
    kids: Dict[int, List[Dict[str, Any]]] = {}
    state = {'tic': -1, 'callfn': 0}

    def reader(handle) -> None:
        first = json.loads(handle.readline())
        if first.get('format') != CL.FORMAT:
            raise PartError('not a call log')
        names = [r['name'] for r in first['routines']]
        for raw in handle:
            line = json.loads(raw)
            if line.get('end'):
                break
            name = names[line['routine']]
            if name == GC.TIC_NAME:
                state['tic'] = _hexint(line['in']['mem'][0])
                continue
            mine = kids.pop(line['call'], [])
            node: Dict[str, Any] = {'r': name}
            if name in (MPC, MPF):
                node['dir'] = _hexint(line['in']['mem'][0]) & 0xFF
                node['res'] = line['out']['a'] & 0xFFFF if line.get('out') \
                    else None
                node['things'] = sum(1 for k in mine if k['r'] == CHANGE)
            elif name == SOUND2:
                ptr = _hexint(line['in']['mem'][0]) & 0xFFFFFF
                base = _hexint(line['in']['mem'][1]) & 0xFFFFFF
                off = ptr - soundorg - base
                node['sfx'] = line['in']['a'] & 0xFFFF
                node['sec'] = off // sec_size if off >= 0 and \
                    off % sec_size == 0 else None
            elif name == APPROX:
                o = line.get('out') or {}
                node['level'] = s32((o.get('a', 0) & 0xFFFF) |
                                    (o.get('x', 0) & 0xFFFF) << 16)
            elif name == LIGHT:
                node['tags'] = sum(1 for k in mine if k['r'] == FINDTAG)
                lv = [k['level'] for k in mine if k['r'] == APPROX]
                node['level'] = lv[0] if lv else None
                node['hit'] = line['hit']
                out[LIGHT].append([line['hit'], state['tic'],
                                   light_summary(node)])
            elif name in THINKERS:
                node['kids'] = mine
                node['callfn'] = line['parent']
            elif name == CALLFN:
                state['callfn'] += 1
                for k in mine:
                    if k['r'] in THINKERS:
                        out[k['r']].append([line['hit'], state['tic'],
                                            thinker_summary(k)])
                continue
            if line['parent']:
                kids.setdefault(line['parent'], []).append(node)
    routines = ['%s,name=%s,in=_g_gametic:4,entry=1' % (GC.TICKER,
                                                        GC.TIC_NAME),
                '%s,name=%s' % (CALLFN, CALLFN),
                '%s,name=%s,jumps=1' % (DOOR, DOOR),
                '%s,name=%s,jumps=1' % (PLAT, PLAT),
                '%s,name=%s' % (LIGHT, LIGHT),
                '%s,name=%s,in=s+4:2' % (MPC, MPC),
                '%s,name=%s,in=s+4:2' % (MPF, MPF),
                '%s,name=%s,entry=1' % (CHANGE, CHANGE),
                '%s,name=%s,in=dp:_Dp:4+_g_sectors:4,entry=1' % (SOUND2,
                                                                  SOUND2),
                '%s,name=%s,entry=1,jumps=1' % (REMOVE, REMOVE),
                '%s,name=%s,entry=1' % (FINDTAG, FINDTAG),
                '%s,name=%s' % (APPROX, APPROX)]
    GC.check_disk()
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-movers-log-',
                                 dir=str(BUILD)))
    try:
        fifo = work / 'calls.fifo'
        import os
        os.mkfifo(str(fifo))
        opts = CL.options(routines, fifo, table) + ['--call-log-limit',
                                                    str(SF.LOG_LIMIT)]
        r = GC.machine(run, work, opts, reader=reader, fifo=fifo)
        if r['problems']:
            raise PartError('%s: %s' % (run, '; '.join(r['problems'])))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    for key in ENTRIES:
        want = survey_count(run, key)
        if want != len(out[key]):
            raise PartError('%s: %d %s calls logged, the survey has %d'
                            % (run, len(out[key]), key, want))
    d = {'format': LOG_FORMAT, 'run': run, 'callfn_calls': state['callfn'],
         'calls': out}
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / (run + '.json.z')).write_bytes(zlib.compress(
        json.dumps(d, separators=(',', ':')).encode(), 6))
    return d


SFX = {}


def sfx_name(v: int) -> str:
    if not SFX:
        for k, x in uconst().items():
            if k.startswith('UC_SFX_'):
                SFX.setdefault(x, k[7:].lower())
    return SFX.get(v, 'sfx%d' % v)


def thinker_summary(node: Dict[str, Any]) -> Dict[str, Any]:
    """A thinker call's path (from its callees, in their order) and its
    sounds, upstream's."""
    kids = node['kids']
    mover = [k for k in kids if k['r'] in (MPC, MPF)]
    sounds = [[k['sfx'], k['sec']] for k in kids if k['r'] == SOUND2]
    removed = any(k['r'] == REMOVE for k in kids)
    light = [k for k in kids if k['r'] == LIGHT]
    parts: List[str] = []
    if not mover:
        parts.append('wait')
        if sounds:
            parts.append('end')
    else:
        m = mover[0]
        parts.append({1: 'up', 0xFF: 'down'}.get(m['dir'], 'dir%d' %
                                                 m['dir']))
        parts.append('res%s' % m['res'])
        if m['things']:
            parts.append('things')
    parts += [sfx_name(s) for s, _ in sounds]
    if removed:
        parts.append('removed')
    if light and light[0]['tags']:
        parts.append('light')
    return {'path': '-'.join(parts), 'sounds': sounds}


def light_summary(node: Dict[str, Any]) -> Dict[str, Any]:
    lv = node['level']
    if lv is None:
        path = 'none'
    else:
        path = 'level-%s-tags%d' % ('neg' if lv < 0 else 'above' if
                                    lv > 0x10000 else 'frac',
                                    min(node['tags'], 3))
    return {'path': path, 'sounds': []}


def load_log(run: str) -> Optional[Dict[str, Any]]:
    p = LOGS / (run + '.json.z')
    if not p.exists():
        return None
    d = json.loads(zlib.decompress(p.read_bytes()))
    return d if d.get('format') == LOG_FORMAT else None


def log_runs() -> List[str]:
    return [run for run in GC.RUNS
            if any(survey_count(run, k) for k in ENTRIES)]


# ---------------------------------------------------------------------------
# The choice and the captures
# ---------------------------------------------------------------------------

def calls_of(key: str) -> List[Tuple[str, int, int, Dict[str, Any]]]:
    out = []
    for run in log_runs():
        lg = load_log(run)
        if lg is None:
            raise PartError('no call log of %s (--log)' % run)
        out += [(run, h, t, s) for h, t, s in lg['calls'][key]]
    return out


def choose(key: str) -> List[Tuple[str, int, int, Dict[str, Any]]]:
    """LEAN calls: the first of each path, then calls spread evenly over
    the rest."""
    calls = calls_of(key)
    first, seen = [], set()
    for c in calls:
        if c[3]['path'] not in seen:
            seen.add(c[3]['path'])
            first.append(c)
    first = first[:LEAN]
    taken = {(c[0], c[1]) for c in first}
    rest = [c for c in calls if (c[0], c[1]) not in taken]
    k = min(LEAN - len(first), len(rest))
    pick = first + [rest[(i * len(rest)) // k] for i in range(k)]
    order = {(c[0], c[1]): i for i, c in enumerate(calls)}
    return sorted(pick, key=lambda c: order[(c[0], c[1])])


def case_key(key: str) -> str:
    return CALLFN if key in THINKERS else key


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, case_key(key)) / ('h%08d.case.z' % hit)


def capture() -> Dict[str, Any]:
    chosen = {key: choose(key) for key in ENTRIES}
    by: Dict[Tuple[str, str], Dict[int, int]] = {}
    for key, cs in chosen.items():
        for run, hit, tic, _ in cs:
            by.setdefault((run, case_key(key)), {})[hit] = tic
    for (run, ckey), hits in sorted(by.items()):
        todo = sorted(h for h in hits if not (GC.case_dir(run, ckey) / (
            'h%08d.case.z' % h)).exists())
        if not todo:
            continue
        tics = [hits.get(h, -1) for h in range(1, max(todo) + 1)]
        start = time.time()
        got = GC.capture(run, ckey, todo, tics, batch=BATCH, say=say)
        say('%s %s: %d cases (%.0f s)' % (run, ckey, len(got),
                                          time.time() - start))
    d = {'format': CHOICE_FORMAT, 'lean': LEAN, 'chosen': {}}
    for key, cs in chosen.items():
        d['chosen'][key] = [
            {'case': str(case_path(run, key, hit).relative_to(OUT)),
             'run': run, 'hit': hit, 'tic': tic, 'path': s['path'],
             'sounds': s['sounds']} for run, hit, tic, s in cs]
        d.setdefault('paths', {})[key] = sorted(
            {c[3]['path'] for c in calls_of(key)})
    bad = verify(d)
    if bad:
        raise PartError('%d callFn cases do not enter their thinker at '
                        'their tic: %s' % (len(bad), bad[:3]))
    CHOICE.write_text(json.dumps(d, indent=1) + '\n')
    return d


def verify(d: Dict[str, Any]) -> List[str]:
    """The callFn cases whose FN_P is not their thinker or whose gametic is
    not the logged one (README "capturing at a dispatch stub")."""
    table = CL.Linkmap()
    fn_p = table.address(FN_P)
    gt = table.address('g_game65.s:_g_gametic')
    bad = []
    for key in THINKERS:
        want = table.address(key) & 0xFFFFFF
        for rec in d['chosen'][key]:
            c = GC.load_case(OUT / rec['case'])
            got = int.from_bytes(c.entry.read(fn_p, 3), 'little')
            if got != want or int.from_bytes(c.entry.read(gt, 4),
                                             'little') != rec['tic']:
                bad.append(rec['case'])
    return bad


def load_choice() -> Dict[str, Any]:
    if not CHOICE.exists():
        raise PartError('no %s (--capture)' % CHOICE)
    d = json.loads(CHOICE.read_text())
    if d.get('format') != CHOICE_FORMAT:
        raise PartError('%s is not %s' % (CHOICE, CHOICE_FORMAT))
    return d


# ---------------------------------------------------------------------------
# The reference's objects
# ---------------------------------------------------------------------------

def _ptr(ref: 'SF.Ref', text: str, when: str = 'in') -> int:
    return int.from_bytes(ref.source(text, when), 'little') & 0xFFFFFF


def objects(s: Dict[str, Any], kind: str) -> Dict[int, Dict[str, Any]]:
    return s['objects'].get(kind, {})


def thinker_of(key: str, ref: 'SF.Ref'):
    if key == LIGHT:
        return ref.ref(_ptr(ref, 'abs:p_doors65.s:DR_DOOR:4'), ('door',))
    return ref.ref(_ptr(ref, 'dp:_Dp:4'), ('door' if key == DOOR
                                             else 'plat',))


def expected_sounds(key: str, ref: 'SF.Ref') -> List[Tuple[int, int]]:
    """The model of upstream's sounds (sfx, sector) from the states before
    and after the call: a door's close or open sound when its direction
    changes from waiting, its open sound when it turns from down to up; a
    plat's start sound when it leaves waiting or turns from up to down,
    the stone sound of a raise plat going up when leveltime & 7 is 0
    (before the rest), its stop sound when it starts waiting."""
    if key == LIGHT:
        return []
    c = uconst()
    th = thinker_of(key, ref)
    kind = 'door' if key == DOOR else 'plat'
    a = objects(ref.s_in, kind)[th.id]
    b = objects(ref.s_out, kind).get(th.id) or a
    sec = a['sector'].id
    out: List[Tuple[int, int]] = []
    if key == DOOR:
        d0, d1 = a['direction'] & 0xFF, b['direction'] & 0xFF
        if d0 == 0 and d1 == 0xFF:
            out.append((c['UC_SFX_DORCLS'], sec))
        elif d0 in (0, 0xFF) and d1 == 1:
            out.append((c['UC_SFX_DOROPN'], sec))
        return out
    s0, s1 = a['status'], b['status']
    if objects(ref.s_out, 'sector')[sec]['floordata'] is None:
        s1 = c['UC_WAITING']    # removed at its destination, after stopWait
    lt =int.from_bytes(ref.source('abs:_g_leveltime:2'), 'little')
    if s0 == c['UC_UP'] and a['type'] == c['UC_RAISETONEARESTANDCHANGE'] \
            and lt & 7 == 0:
        out.append((c['UC_SFX_STNMOV'], sec))
    if s0 == c['UC_WAITING'] and s1 != s0 or \
            s0 == c['UC_UP'] and s1 == c['UC_DOWN']:
        out.append((c['UC_SFX_PSTART'], sec))
    elif s0 != c['UC_WAITING'] and s1 == c['UC_WAITING']:
        out.append((c['UC_SFX_PSTOP'], sec))
    return out


# ---------------------------------------------------------------------------
# The synthetic cases (ref816 --call of chosen calls with pokes)
# ---------------------------------------------------------------------------

def _mobj_pokes(m, a: int) -> List[Tuple[int, bytes]]:
    """A thing made a too-tall live shootable monster."""
    c = uconst()
    out = [(a + c['UO_MO_HEIGHT'], TALL.to_bytes(4, 'little'))]
    hp = m.u16(a + c['UO_MO_HEALTH'])
    if hp == 0 or hp & 0x8000:
        out.append((a + c['UO_MO_HEALTH'], (1).to_bytes(2, 'little')))
    f = (m.u32(a + c['UO_MO_FLAGS']) | c['UC_MF_SHOOTABLE']) & \
        ~(c['UC_MF_DROPPED_HI'] << 16)
    out.append((a + c['UO_MO_FLAGS'], f.to_bytes(4, 'little')))
    return out


def _first_thing(ref: 'SF.Ref', sec_id: int):
    c = uconst()
    nodes = objects(ref.s_in, 'sector')[sec_id]['touching_thinglist']
    for n in nodes:
        t = objects(ref.s_in, 'secnode')[n.id]['m_thing']
        if t is None or t.kind != 'mobj':
            continue
        if objects(ref.s_in, 'mobj')[t.id]['flags'] & c['UC_MF_NOBLOCKMAP']:
            continue
        return t
    return None


def _recs(ch: Dict[str, Any], key: str, want) -> List[Dict[str, Any]]:
    return [r for r in ch['chosen'][key] if want(r['path'])]


def synthetic_plan() -> List[Dict[str, Any]]:
    c = uconst()
    ch = load_choice()
    plan: List[Dict[str, Any]] = []

    def thinker_addr(ref, key):
        return ref.r_in.ref_address(thinker_of(key, ref))

    # a door closing on a monster: a door going down with a thing in its
    # sector, the thing made too tall (crushed: up again, the open sound)
    for rec in _recs(ch, DOOR, lambda p: p.startswith('down-res0')):
        case = GC.load_case(OUT / rec['case'])
        ref = SF.Ref(case)
        th = thinker_of(DOOR, ref)
        sec = objects(ref.s_in, 'door')[th.id]['sector'].id
        t = _first_thing(ref, sec)
        if t is None:
            continue
        plan.append({'key': DOOR, 'base': rec['case'], 'note':
                     'a door closing on a monster',
                     'pokes': _mobj_pokes(case.entry,
                                          ref.r_in.ref_address(t))})
        break
    # close30ThenOpen (no E1 line makes one): its wait ending (up, the open
    # sound) and its bottom (a wait of 30 s)
    c30 = c['UC_CLOSE30THENOPEN'].to_bytes(2, 'little')
    for want, note, extra in (
            (lambda p: p == 'wait', 'its wait ending',
             lambda da: [(da + c['UO_DOOR_TOPCOUNTDOWN'],
                          (1).to_bytes(2, 'little'))]),
            (lambda p: p.startswith('down-res2'), 'at its bottom',
             lambda da: [])):
        for rec in _recs(ch, DOOR, want)[:1]:
            case = GC.load_case(OUT / rec['case'])
            ref = SF.Ref(case)
            da = thinker_addr(ref, DOOR)
            plan.append({'key': DOOR, 'base': rec['case'], 'note':
                         'a close30ThenOpen door %s' % note,
                         'pokes': [(da + c['UO_DOOR_TYPE'], c30)] +
                         extra(da)})
    # plats with a thing on them: waiting with the count ending (status
    # from floorheight == low), still waiting; rising onto a too-tall
    # thing (crushed: down, the start sound)
    for rec in _recs(ch, PLAT, lambda p: '-things' in p):
        case = GC.load_case(OUT / rec['case'])
        ref = SF.Ref(case)
        pa = thinker_addr(ref, PLAT)
        th = thinker_of(PLAT, ref)
        sec = objects(ref.s_in, 'plat')[th.id]['sector'].id
        if _first_thing(ref, sec) is None:
            continue
        st = (c['UC_WAITING']).to_bytes(2, 'little')
        for count, note in ((1, 'its count ending'),
                            (5, 'its count going on')):
            plan.append({'key': PLAT, 'base': rec['case'], 'note':
                         'a plat waiting with a thing on it, %s' % note,
                         'pokes': [(pa + c['UO_PLAT_STATUS'], st),
                                   (pa + c['UO_PLAT_COUNT'],
                                    count.to_bytes(2, 'little'))]})
        # the same at the bottom: low = its floor (up when it ends)
        floor = objects(ref.s_in, 'sector')[sec]['floorheight']
        plan.append({'key': PLAT, 'base': rec['case'], 'note':
                     'a plat waiting at its bottom with a thing on it',
                     'pokes': [(pa + c['UO_PLAT_STATUS'], st),
                               (pa + c['UO_PLAT_COUNT'],
                                (1).to_bytes(2, 'little')),
                               (pa + c['UO_PLAT_LOW'],
                                (floor & 0xFFFFFFFF).to_bytes(4,
                                                              'little'))]})
        break
    for rec in _recs(ch, PLAT, lambda p: p.startswith('up-res0-things')):
        case = GC.load_case(OUT / rec['case'])
        ref = SF.Ref(case)
        th = thinker_of(PLAT, ref)
        sec = objects(ref.s_in, 'plat')[th.id]['sector'].id
        t = _first_thing(ref, sec)
        if t is None:
            continue
        plan.append({'key': PLAT, 'base': rec['case'], 'note':
                     'a plat rising onto a too-tall thing',
                     'pokes': _mobj_pokes(case.entry,
                                          ref.r_in.ref_address(t))})
        break
    # a raise plat reaching its top on the stone sound's tic (the stone
    # sound before the stop sound), and one tic later (no stone sound);
    # a plat going down to its bottom
    lt_at = CL.Linkmap().address('_g_leveltime')
    for rec in _recs(ch, PLAT, lambda p: p.startswith('up-res0')):
        case = GC.load_case(OUT / rec['case'])
        ref = SF.Ref(case)
        pa = thinker_addr(ref, PLAT)
        th = thinker_of(PLAT, ref)
        sec = objects(ref.s_in, 'plat')[th.id]['sector'].id
        floor = objects(ref.s_in, 'sector')[sec]['floorheight']
        lt = case.entry.u16(lt_at)
        top = [(pa + c['UO_PLAT_TYPE'], c['UC_RAISETONEARESTANDCHANGE']
                .to_bytes(2, 'little')),
               (pa + c['UO_PLAT_HIGH'], ((floor + 0x8000) & 0xFFFFFFFF)
                .to_bytes(4, 'little'))]
        for v, note in ((lt & ~7, 'on the stone sound\'s tic'),
                        ((lt & ~7) | 1, 'off it')):
            plan.append({'key': PLAT, 'base': rec['case'], 'note':
                         'a raise plat reaching its top %s' % note,
                         'pokes': top + [(lt_at, (v & 0xFFFF).to_bytes(
                             2, 'little'))]})
        plan.append({'key': PLAT, 'base': rec['case'], 'note':
                     'a raise plat crushed on the stone sound\'s tic',
                     'pokes': [top[0], (lt_at, ((lt & ~7) & 0xFFFF)
                                        .to_bytes(2, 'little'))] +
                     (_mobj_pokes(case.entry, ref.r_in.ref_address(
                         _first_thing(ref, sec)))
                      if _first_thing(ref, sec) is not None else [])})
        break
    # partLight with a light tag on a line with a sector's tag, at levels
    # below 0 (the ceiling under the floor), between 0 and FRACUNIT and
    # above it (the ceiling over the top)
    for rec in ch['chosen'][LIGHT][:1]:
        case = GC.load_case(OUT / rec['case'])
        ref = SF.Ref(case)
        th = thinker_of(LIGHT, ref)
        door = objects(ref.s_in, 'door')[th.id]
        da = ref.r_in.ref_address(th)
        sec = door['sector'].id
        sa = ref.r_in.ref_address(door['sector'])
        tags = sorted({s['tag'] for s in objects(ref.s_in,
                                                 'sector').values()
                       if s['tag']})
        if not tags or door['line'] is None:
            break
        la = ref.r_in.ref_address(door['line'])
        floor = objects(ref.s_in, 'sector')[sec]['floorheight']
        top = door['topheight']
        base = [(da + c['UO_DOOR_LIGHTTAG'], (1).to_bytes(2, 'little')),
                (la + c['UO_LINE_TAG'], tags[0].to_bytes(2, 'little'))]
        for ceil, note in ((floor - 0x10000, 'below 0'),
                           ((floor + top) // 2, 'between'),
                           (top + 0x80000, 'above FRACUNIT')):
            pk = base + [(sa + c['UO_SEC_CEILINGHEIGHT'],
                          (ceil & 0xFFFFFFFF).to_bytes(4, 'little'))]
            if top == floor:
                pk.append((da + c['UO_DOOR_TOPHEIGHT'], ((floor + 0x400000)
                                                         & 0xFFFFFFFF)
                           .to_bytes(4, 'little')))
            plan.append({'key': LIGHT, 'base': rec['case'], 'note':
                         'partLight with a light tag, the level %s' % note,
                         'pokes': pk})
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
        say('%s: %s' % (rec['key'], rec['note']))
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


def path_of(key: str, ref: 'SF.Ref') -> str:
    """A call's path from the reference's states (the synthetic cases')."""
    c = uconst()
    th = thinker_of(key, ref)
    kind = 'door' if key in (DOOR, LIGHT) else 'plat'
    a = objects(ref.s_in, kind)[th.id]
    b = objects(ref.s_out, kind).get(th.id) or a
    if key == LIGHT:
        return 'light-tag%d' % (1 if a['lighttag'] else 0)
    if key == DOOR:
        return 'door-dir%d-to%d-type%d' % (a['direction'], b['direction'],
                                            a['type'])
    sec = a['sector'].id
    done = objects(ref.s_out, 'sector')[sec]['floordata'] is None
    return 'plat-status%d-to%d-type%d%s' % (a['status'], b['status'],
                                             a['type'],
                                             '-removed' if done else '')


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def allowed_main(b) -> List[Tuple[int, int]]:
    """mobjstate's places (the shared stray rule of wave 2's integration)
    and the parts' scratch blocks (W $9A00-$9DFF: R1)."""
    lo, hi = GL.WR['SCRATCH']
    return MS.allowed_main(b) + [(lo, hi)]


def stray(writes, b, header: Dict[str, Any]) -> List[str]:
    """CPU writes outside the allowed places (mobjstate.stray's rule with
    the scratch blocks, as part planes)."""
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


def run_one(prep: 'SF.Prep', nat: 'SF.Native', fill: int, profile: str,
            want_sounds: List[Tuple[int, int]]) -> Dict[str, Any]:
    """One run of a case: the canonical state after the call against the
    reference's (routine mode), the sector sound events, the native thinker
    list's checks (mobjstate's), the stray writes; the cycles from the
    routine's entry to its return, the lowest S."""
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
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-movers-', dir=str(BUILD)))
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
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    from native import setupcheck as SC
    nat_state = PortReader(prep.mf).read(SC.port_memory(m))
    diff = gcanon.compare(prep.ref.s_out, nat_state, 'routine')
    diff += MS.native_checks(m)
    got = SF.sounds(m)
    res['sounds'] = len(got)
    tic = prep.ref.s_in['globals']['g_game65.s:_g_gametic'] & 0xFFFF
    want = [(tic, 1, sfx, 0x8000 | sec) for sfx, sec in want_sounds]
    mine = [e for e in got if e[1] == 1]
    res['mobj_sounds'] = len(got) - len(mine)
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
                name = item['case']
                case = GC.load_case(OUT / name)
                path = item['path']
            else:
                name = 'synthetic: %s' % item['note']
                case = synthetic_case(item)
            prep = SF.Prep(case, key, spec_all[key])
            model = expected_sounds(key, prep.ref)
            if kind == 'case':
                want = [tuple(x) for x in item['sounds']]
            else:
                want = model
                path = path_of(key, prep.ref)
        except Exception as error:      # reported per case, never hidden
            out.append({'case': name, 'entry': key, 'ok': False,
                        'synthetic': kind != 'case',
                        'error': '%s: %s' % (type(error).__name__, error)})
            continue
        for fill in fills:
            for profile in profiles:
                try:
                    r = run_one(prep, nat, fill, profile, want)
                except Exception as error:
                    r = {'entry': key, 'fill': '%02x' % fill,
                         'profile': profile, 'ok': False,
                         'error': '%s: %s' % (type(error).__name__, error)}
                r.update(case=name, path=path, synthetic=kind != 'case',
                         model_agrees=model == want)
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
            recs = [r for r in ch['chosen'].get(key, [])
                    if select is None or select(key, r['path'])]
            items += [('case', key, r) for r in recs[::sample]]
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
        calls = sum(survey_count(run, key) for run in GC.RUNS)
        run_paths = sorted({r['path'] for r in rs if 'path' in r and
                            not r.get('synthetic')})
        e: Dict[str, Any] = {
            'calls_in_survey': calls, 'cases_eligible': calls,
            'cases_captured': sum(1 for _, s in cases if not s),
            'cases_synthetic': sum(1 for _, s in cases if s),
            'runs': len(rs),
            'failures': sum(1 for r in rs if not r.get('ok')),
            'stray_writes': sum(r.get('stray') or 0 for r in rs),
            'mobj_sound_events': sum(r.get('mobj_sounds') or 0 for r in rs),
            'sound_model_disagrees': sorted({r['case'] for r in rs if
                                             r.get('model_agrees') is False}),
            'paths_in_logs': ch['paths'].get(key, []),
            'paths_run': run_paths,
            'paths_not_run': sorted(set(ch['paths'].get(key, [])) -
                                    set(run_paths)),
            'paths_synthetic': sorted({'%s (%s)' % (r['case'], r['path'])
                                       for r in rs if r.get('synthetic')}),
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
# mulExt's random check (GAME.md 2.4 "Arithmetic")
# ---------------------------------------------------------------------------

BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
EDGES32 = (0, 1, -1, 2, -2, 0x7FFFFFFF, -0x80000000, -0x7FFFFFFF, 0xFFFF,
           0x10000, -0x10000, 0x8000, -0x8000, 0x7FFF, 0xFFFFFF, 0x1234567)
EDGES16 = (0, 1, -1, 2, -2, 0x7FFF, -0x8000, -0x7FFF, 0xFF, 0x100, 0x80,
           255, -255)


def mulext_inputs(n: int, seed: int = 1) -> List[Tuple[int, int]]:
    """(a 32-bit value, a word): every pair of the edges, then random
    (uniform; a light level and a level 0..FRACUNIT, as partLight's)."""
    rnd = random.Random(seed)
    out = [(a, b) for a in EDGES32 for b in EDGES16]
    while len(out) < n:
        k = len(out) % 3
        if k == 0:
            out.append((rnd.randint(-0x80000000, 0x7FFFFFFF),
                        rnd.randint(-0x8000, 0x7FFF)))
        elif k == 1:
            out.append((rnd.randint(0, 0x10000), rnd.randint(0, 255)))
        else:
            out.append((rnd.choice((1, -1)) * (1 << rnd.randint(0, 30)) +
                        rnd.randint(-2, 2), rnd.choice((1, -1)) *
                        (1 << rnd.randint(0, 14)) + rnd.randint(-1, 1)))
    return [(s32(a), ((b + 0x8000) & 0xFFFF) - 0x8000) for a, b in out[:n]]


def native_bulk(b, pairs: Sequence[Tuple[int, int]]) -> List[int]:
    per = BULK_ROOM // 6
    out: List[int] = []
    for start in range(0, len(pairs), per):
        chunk = pairs[start:start + per]
        img = G.Image(b, 0xA5, store=False)
        img.aux(BULK_IN, 0x0200, b''.join(struct.pack('<ih', a, w)
                                          for a, w in chunk))
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-movers-bulk-',
                                     dir=str(BUILD)))
        try:
            k = len(chunk)
            r = G.run(img, work, GL.MODES['ROUTINE'], 'mv_bulk',
                      regs=(0, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise PartError('mv_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + 4 * len(chunk)])
        out += [struct.unpack('<i', data[i:i + 4])[0]
                for i in range(0, len(data), 4)]
    return out


def random_check(n: int = 100_000, seed: int = 1,
                 obj: Path = OUT) -> Dict[str, Any]:
    """mulExt on n inputs: upstream's (mathref batch on a captured case's
    machine: C the word, _Dp[0-3] the value in; X:C out) against the
    native (mv_bulk) and against the product's low 32 bits."""
    import sight as SG
    ch = load_choice()
    case = GC.load_case(OUT / ch['chosen'][DOOR][0]['case'])
    t = CL.Linkmap()
    pairs = mulext_inputs(n, seed)
    dp = (case.regs_in['d'] + t.address('_Dp') - t.direct_page) & 0xFFFF
    recs = b''.join(struct.pack('<hi', w, a) for a, w in pairs)
    pc = t.address('p_doors65.s:mulExt')
    ups = SG.mathref(case, 'mulExt', pc, ['a', '%06X 4' % dp], ['a', 'x'],
                     recs, 4)
    upv = [struct.unpack('<i', u)[0] for u in ups]
    b = G.load_build(obj, IMAGE)
    nat = native_bulk(b, pairs)
    bad = [(a, w, u, m_) for (a, w), u, m_ in zip(pairs, upv, nat)
           if u != m_]
    model = sum(1 for (a, w), u in zip(pairs, upv) if u == s32(a * w))
    return {'inputs': len(pairs), 'compared': min(len(upv), len(nat)),
            'different': len(bad) + abs(len(upv) - len(nat)),
            'first': bad[:5], 'edges': len(EDGES32) * len(EDGES16),
            'upstream_is_the_low_product': model, 'seed': seed}


# ---------------------------------------------------------------------------
# The planted bugs (--plants): the three most likely mistakes (lean)
# ---------------------------------------------------------------------------

PLANTS: Dict[str, Tuple[str, List[Tuple[str, str]]]] = {
    # the door's wait at its top not VDOORWAIT (the plat's 3 s, 105)
    'door-wait': ('door-top', [(
        '''VDOORWAIT = 150                 ; p_doors65.s:23''',
        '''VDOORWAIT = 105                 ; (planted: PLATWAIT * 35)''')]),
    # the plat's status changed (with its sound) before the stone sound
    'status-first': ('stone', [(
        '''        THINKER
        TYPE16 SPPL_TYPE
        cmp #UC_RAISETONEARESTANDCHANGE
        bne :+
        lda G_LEVELTIME
        and #7
        bne :+
        SECSOUND UC_SFX_STNMOV
:       lda SB_RES
        cmp #UC_CRUSHED
        bne :+
        lda #UC_DOWN            ; (waitStatus)
        jsr pl_wait
        SECSOUND UC_SFX_PSTART
        rts
:       cmp #UC_PASTDEST        ; at the top: both types are done
        bne @rts
        jsr pl_stop''',
        '''        lda SB_RES              ; (planted: the status first)
        cmp #UC_CRUSHED
        bne :+
        lda #UC_DOWN
        jsr pl_wait
        SECSOUND UC_SFX_PSTART
        jmp pl_stone
:       cmp #UC_PASTDEST
        beq :+
        jmp pl_stone
:       jsr pl_stop
        jsr pl_stone''')]),
    # the reversal on a thing without its open sound
    'reversal-silent': ('door-crush', [(
        '''        lda #1
        jsr dr_setdir
        SECSOUND UC_SFX_DOROPN
        rts

        ; up to the top''',
        '''        lda #1
        jsr dr_setdir
        rts                     ; (planted: no sound)

        ; up to the top''')]),
}
PLANT_EXTRA = {
    'status-first': '''
pl_stone:                       ; (planted)
        THINKER
        TYPE16 SPPL_TYPE
        cmp #UC_RAISETONEARESTANDCHANGE
        bne :+
        lda G_LEVELTIME
        and #7
        bne :+
        SECSOUND UC_SFX_STNMOV
:       rts
'''}


def plant_build(name: str, tmp: Path) -> Path:
    _, edits = PLANTS[name]
    src = tmp / 'src'
    files = list(G.PLANT_COPY) + ['game/%s/%s' % (PART, f) for f in
                                  ('part.mk', 'movers.s', 'mvtest.s')]
    for f in files:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    target = src / 'game' / PART / 'movers.s'
    text = target.read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise PartError('the planted bug %s no longer applies: %r' % (
                name, old[:60]))
        text = text.replace(old, new)
    text += PLANT_EXTRA.get(name, '')
    target.write_text(text)
    return build(game=tmp / 'game', source=src)


def plant_jobs(check: str, obj: Path, sample: int = 1) -> List[Tuple]:
    one = dict(fills=(FILLS[0],), profiles=(PROFILES[0],), sample=sample)
    if check == 'door-top':     # a normal door reaching its top
        return check_jobs(keys=(DOOR,), synthetic=False, obj=obj,
                          select=lambda k, p: p.startswith('up-res2') and
                          'removed' not in p, **one)
    if check == 'stone':        # the raise plats on the stone tic
        return check_jobs(keys=(PLAT,), captured=False, obj=obj,
                          select=lambda k, n: 'stone' in n, **one)
    if check == 'door-crush':   # a door closing on a thing: demo1's and
        return check_jobs(      # the synthetic monster
            keys=(DOOR,), obj=obj, select=lambda k, n: 'closing on' in n or
            n.startswith('down-res1'), **one)
    raise PartError('no check %s' % check)


def plants(names: Optional[Sequence[str]] = None,
           sample: int = 1) -> Dict[str, Any]:
    out = {}
    for name in (names or list(PLANTS)):
        check = PLANTS[name][0]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-movers-plant-',
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
        say('%-16s %-10s %s' % (name, check, 'caught: %d of %d runs fail, %s'
                                % (r['failed'], r['runs'], r['first'])
                                if r['caught'] else 'NOT CAUGHT (%d runs)' %
                                r['runs']))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)
LABELS = ('T_VerticalDoor', 'partLight', 'T_PlatRaise', 'mulExt')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (movers.o) against its budget; each routine's
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
               lean='at most %d calls a routine (by path, from the call '
                    'logs of every call), fill $A5 only (the owner\'s lean '
                    'checks of 2026-10-02)' % LEAN,
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
        say('%-28s %3d+%-2d cases %4d runs %d failed %d stray, S %s; %s' % (
            key, e['cases_captured'], e['cases_synthetic'], e['runs'],
            e['failures'], e['stray_writes'], e['lowest_s'], cyc))
        if e.get('paths_not_run'):
            say('  paths not run: %s' % e['paths_not_run'])
    if 'sizes' in rep:
        sz = rep['sizes']
        say('bytes %d of %d (upstream %d)' % (sz['bytes'], sz['budget'],
                                             sz['upstream']))
    if 'random' in rep:
        say('mulExt: %s' % rep['random'])
    for name, r in rep.get('plants', {}).items():
        say('planted %-16s %s' % (name, 'caught' if r['caught'] else
                                  'NOT CAUGHT'))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--log', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--count', type=int, default=100_000)
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--keys', default=None)
    parser.add_argument('--runs', default=None)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--json', type=Path)
    a = parser.parse_args(argv)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if a.log:
        for run in (a.runs.split(',') if a.runs else log_runs()):
            start = time.time()
            lg = thinker_log(run)
            say('%s: %s of %d callFn calls (%.0f s)' % (
                run, {k.split(':')[1]: len(v) for k, v in
                      lg['calls'].items()}, lg['callfn_calls'],
                time.time() - start))
        return 0
    if a.capture:
        d = capture()
        for key in ENTRIES:
            ps: Dict[str, int] = {}
            for r in d['chosen'][key]:
                ps[r['path']] = ps.get(r['path'], 0) + 1
            say('%s: %d paths in the logs, %d chosen; %s' % (
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
    if a.random:
        build()
        start = time.time()
        r = random_check(a.count)
        r['seconds'] = round(time.time() - start)
        write_report(random=r)
        say('mulExt: %s' % r)
        return 1 if r['different'] else 0
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
