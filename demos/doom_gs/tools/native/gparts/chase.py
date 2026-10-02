#!/usr/bin/env python3
"""Part chase's checkpoint (milestone 10, wave 6; docs/GAME.md 2.4, 3.5;
docs/game-parts/chase.md), lean (the owner's rules of 2026-10-02: at most
40 calls a routine, chosen by branch, the $A5 machine only, the f121
profile): its image, its call logs, its captures, its routine-mode runs,
its synthetic cases, its planted bugs, build/native/game/chase/report.json.

Usage:  python3 tools/native/gparts/chase.py --build
        python3 tools/native/gparts/chase.py --log [--runs demo3,demo1,...]
        python3 tools/native/gparts/chase.py --capture [--jobs 2]
        python3 tools/native/gparts/chase.py --check [--jobs 2]
        python3 tools/native/gparts/chase.py --plants [--jobs 2]

Every routine of the part but the helpers is an ACTTAB action, entered by
p_tick65.s's callFn (JML [FN_P]), which ref816's --capture does not count
by itself: as part look does (tools/native/gparts/look.py), a call log
(log(): ref816 --call-log through a pipe, never stored) gives callFn's hits
that enter each action, their gametic, the routines each action call made
directly (its "signature": the branch it took, from the results of
lookForPlayers, checkMeleeRange, checkMissileRange, P_CheckSight, pMove,
faceTarget, and the calls of P_SetMobjState, newChaseDir, the attacks'
callees), and whether it entered callFn again before it returned (a
nesting hit: last in its capture run). The hits are captured at callFn
(gamecap.capture into build/native/game/chase/cases/) and checked to enter
the logged action at the logged tic (verify()).

A run (evaluate()): part mobjstate's Prepared and run_one (the case's
entry state through the game manifest into a machine poisoned with $A5,
the action's mobj in GA_MO; a2vm, f121; the state read back and compared
with the reference's in gcanon's routine mode, R1-R7; the stray writes by
mobjstate's shared rule: every built part's scratch block). A call that
stops at an unbuilt ACTTAB entry is a stop check with its variant (the
action removed on both sides), as part look does.

Synthetic cases (the reference's own callFn by ref816 --call on a case's
state with pokes):
  - A_CyberAttack and A_BruisAttack (no run calls them): captured
    A_TroopAttack calls (a melee one and a missile one) with FN_P the
    action's address;
  - the paging case of GAME.md 3.4 (review 1): a captured A_TroopAttack
    that shoots, with another shootable monster of the imp's block moved
    10 units in front of it, so that the troopshot's checkMissile ->
    P_TryMove -> checkThing -> P_DamageMobj runs, across the integrator's
    placement (A_TroopAttack, spawnMissile, P_SpawnMissile in slot 1,
    checkMissile, P_DamageMobj in slot 2, P_TryMove in slot 1);
  - A_BossDeath on E1M8 (the tour's last map: one of its A_Look calls,
    the tour run's first capture, so that its base is that machine): a
    baron dying with the other barons dead (the floors of tag 666), with
    another baron alive (nothing), with the player dead (nothing).
"""

import argparse
import json
import os
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

from native import gamecap as GC, gameroutine as GR, glayout as GL, \
    grun as G, render_check as RC  # noqa: E402
from ref816 import bounded, calls as CL  # noqa: E402
import mobjstate as MSP  # noqa: E402  (part mobjstate's harness, wave 1)
import look as LKP  # noqa: E402       (part look's, wave 3)

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'chase'
OUT = GL.GAME / PART
MYCASES = OUT / 'cases'
REPORT = OUT / 'report.json'
FILL = 0xA5
PROFILE = 'f121'
NAME = 'ptest'
BUDGET = 1800                   # GAME.md 2.4: upstream 1,400 x 1.3
UPSTREAM_BYTES = 1400
MODULES = ('chase',)
PER_ROUTINE = 40                # the lean rule
CALLFN = 'p_tick65.s:callFn'
FN_P = 'DC_ENTRY'               # callFn's JML [FN_P] operand (bank 0)
E = 'p_enemy65.s:'
CHASE, POS, SPOS, TROOP, SARG, CYBER, BRUIS, EXPLODE, BOSS = (E + n for n in (
    'A_Chase', 'A_PosAttack', 'A_SPosAttack', 'A_TroopAttack',
    'A_SargAttack', 'A_CyberAttack', 'A_BruisAttack', 'A_Explode',
    'A_BossDeath'))
LOOK = E + 'A_Look'
ACTIONS = (CHASE, POS, SPOS, TROOP, SARG, CYBER, BRUIS, EXPLODE, BOSS)
# the routines an action calls directly, logged with their return and its
# A (R), with their return (C: so that their own calls are not the
# action's) or their entry only (N); short names in the signatures
CHILDREN = [(E + 'lookForPlayers', 'R'), (E + 'checkMeleeRange', 'R'),
            (E + 'checkMissileRange', 'R'), (E + 'pMove', 'R'),
            (E + 'faceTarget', 'R'), ('p_sight65.s:P_CheckSight', 'R'),
            (E + 'newChaseDir', 'C'), ('p_tick65.s:P_SetMobjState', 'C'),
            ('p_attack65.s:P_AimLineAttack', 'N'),
            ('p_attack65.s:P_LineAttack', 'N'),
            ('p_inter65.s:P_DamageMobj', 'N'),
            ('p_spawn65.s:P_SpawnMissile', 'N'),
            ('p_attack65.s:P_RadiusAttack', 'N')]
# (run, action, at most how many) of the captured calls; a routine's runs
# share its PER_ROUTINE
WANT = [('demo3', CHASE, 30), ('demo1', CHASE, PER_ROUTINE),
        ('demo3', POS, PER_ROUTINE), ('demo1', POS, PER_ROUTINE),
        ('demo3', SPOS, PER_ROUTINE), ('demo1', SPOS, PER_ROUTINE),
        ('demo3', TROOP, PER_ROUTINE), ('demo1', TROOP, PER_ROUTINE),
        ('demo3', SARG, PER_ROUTINE), ('demo1', SARG, PER_ROUTINE),
        ('demo2', EXPLODE, PER_ROUTINE), ('demo1', EXPLODE, PER_ROUTINE)]
LOG_RUNS = ('demo3', 'demo1', 'demo2', 'tour')
E1M8_FROM = 1299                # the tour's E1M8: its load is at tic 1298
BOSS_RUN = 'tour'


class PartError(Exception):
    pass


def check_disk() -> None:
    st = os.statvfs(str(BUILD))
    if st.f_bavail * st.f_frsize < 20 * 10 ** 9:
        raise PartError('below 20 GB free: stopped')


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

def build(game: Path = GL.GAME, bugs: Sequence[Tuple[str, str, str]] = ()
          ) -> Path:
    """The part's image (game/chase/ptest.*) from a scratch copy of the
    build files and the bugs (file under src/native, old, new) applied to
    copies; every other source from the tree (game.mk's vpath). The copy
    is deleted."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-chase-build-', dir=str(BUILD)))
    try:
        src = tmp / 'src'
        files = set(G.PLANT_COPY) | {'game/%s/part.mk' % PART}
        files |= {name for name, _, _ in bugs}
        for f in files:
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(SRC / f), str(src / f))
        for name, old, new in list(bugs):
            text = (src / name).read_text()
            if text.count(old) != 1:
                raise PartError('%s: the edit no longer applies: %r' % (
                    name, old[:60]))
            (src / name).write_text(text.replace(old, new))
        objs = game / PART / 'game' / PART
        if objs.exists():
            for p in objs.glob('*.o'):
                p.unlink()
        cmd = ['make', '-s', '-C', str(src), '-f', 'game.mk', 'part',
               'P=%s' % PART, 'ROOT=%s' % ROOT, 'GAME=%s' % game]
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
    """The part's bytes by module (the image's map), its stand-in's
    (bd_floors .. its end, request 1), against the budget."""
    ms = MSP.module_ranges(b)
    by = {m: sum(hi + 1 - lo for _, lo, hi in ms.get(m, ()))
          for m in MODULES}
    part = sum(by.values())
    p = next(x for x in GL.PARTS if x['name'] == PART)
    mine = set(p['routines'] + p['helpers'])
    try:
        rs = {k: v for k, v in G.routine_sizes(b)[0].items() if k in mine}
    except Exception as error:          # (a report only)
        rs = {'error': str(error)}
    lab = b.labels
    standin = lab['bd_floors_end'] - lab['bd_floors'] \
        if 'bd_floors' in lab and 'bd_floors_end' in lab else 0
    return {'routines': rs, 'modules': by, 'part_bytes': part,
            'standin_bytes': standin, 'own_bytes': part - standin,
            'budget': BUDGET, 'upstream_bytes': UPSTREAM_BYTES,
            'over_budget_pct': round(100.0 * (part - standin - BUDGET) /
                                     BUDGET, 1),
            'groups': sorted({seg for m in MODULES for seg, _, _ in
                              ms.get(m, ())})}


# ---------------------------------------------------------------------------
# The call logs
# ---------------------------------------------------------------------------

def short(key: str) -> str:
    return key.split(':', 1)[1]


def log_path(run: str) -> Path:
    return OUT / ('callfn-%s.json' % run)


def log(run: str, say=print) -> Dict[str, Any]:
    """One call log of run (ref816 --call-log through a pipe): callFn's
    hits by the action they enter, each [hit, tic, signature, nesting];
    the tour logs A_Look's hits only (the A_BossDeath bases)."""
    table = CL.Linkmap()
    tracked = (LOOK,) if run == BOSS_RUN else ACTIONS
    want = {table.address(k) & 0xFFFFFF: k for k in tracked}
    fn_p = table.address(FN_P)
    hits: Dict[str, List[List[Any]]] = {k: [] for k in tracked}
    box: Dict[str, Any] = {}
    kinds = dict(CHILDREN)

    def reader(handle) -> None:
        first = json.loads(handle.readline())
        names = [r['name'] for r in first['routines']]
        tic = -1
        n = 0
        opened: Dict[int, List[Any]] = {}     # the action's call -> row
        kids: Dict[int, List[Tuple[int, str]]] = {}
        for raw in handle:
            line = json.loads(raw)
            if line.get('end'):
                box['end'] = line
                break
            name = names[line['routine']]
            if name == GC.TIC_NAME:
                tic = int.from_bytes(bytes.fromhex(line['in']['mem'][0]),
                                     'little')
            elif name == 'callFn':
                n += 1
                for row in opened.values():
                    row[3] = 1              # entered again: nesting
                target = int.from_bytes(bytes.fromhex(
                    line['in']['mem'][0]), 'little') & 0xFFFFFF
                key = want.get(target)
                if key:
                    row = [line['hit'], tic, None, 0]  # (None: no return)
                    hits[key].append(row)
                    opened[line['call'] + 1] = row
            elif name in tracked:
                c = line['call']
                row = opened.pop(c, None)
                got = sorted(kids.pop(c, []))
                if row is not None:
                    row[2] = ' '.join(s for _, s in got)
            elif name in kinds:
                p = line.get('parent')
                if p in opened:
                    s = short(name)
                    if kinds[name] == 'R':
                        o = line.get('out') or {}
                        s += '=%d' % (o.get('a', 0) & 0xFF)
                    kids.setdefault(p, []).append((line['call'], s))
        box['calls'] = n

    routines = ['%s,name=%s,in=_g_gametic:4,entry=1' % (GC.TICKER,
                                                       GC.TIC_NAME),
                '%s,name=callFn,in=%06X:3,entry=1' % (CALLFN, fn_p)]
    routines += ['%s,name=%s,jumps=1' % (k, k) for k in tracked]
    if run != BOSS_RUN:
        routines += ['%s,name=%s%s' % (k, k, ',entry=1' if m == 'N' else '')
                     for k, m in CHILDREN]
    check_disk()
    work = Path(tempfile.mkdtemp(prefix='tmp-chase-log-', dir=str(BUILD)))
    try:
        fifo = work / 'calls.fifo'
        os.mkfifo(str(fifo))
        opts = CL.options(routines, fifo) + ['--call-log-limit',
                                             str(GC.CALL_LOG_LIMIT)]
        start = time.time()
        r = GC.machine(run, work, opts, reader=reader, fifo=fifo)
        if r['problems']:
            raise PartError('%s: %s' % (run, '; '.join(r['problems'])))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    out = {'format': 'chase-callfn 1', 'run': run, 'calls': box.get('calls'),
           'hits': hits, 'seconds': round(time.time() - start)}
    OUT.mkdir(parents=True, exist_ok=True)
    log_path(run).write_text(json.dumps(out) + '\n')
    say('%s: %d callFn calls; %s' % (run, out['calls'], ', '.join(
        '%s %d (%d nesting)' % (short(k), len(v), sum(r[3] for r in v))
        for k, v in hits.items() if v)))
    return out


def load_log(run: str) -> Dict[str, Any]:
    p = log_path(run)
    if not p.exists():
        raise PartError('no %s (python3 tools/native/gparts/chase.py --log)'
                        % p)
    return json.loads(p.read_text())


# ---------------------------------------------------------------------------
# The selection and the captures
# ---------------------------------------------------------------------------

def use_cases() -> None:
    MSP.use_cases(MYCASES)


def selection() -> List[Tuple[str, str, List[Tuple[int, int, str, int]]]]:
    """(run, action, [(hit, tic, signature, nesting)]) of every chosen
    call: by signature (every branch the log tells apart, the smallest
    classes first), a routine's PER_ROUTINE shared by its runs in WANT's
    order; a call that the run ended inside is left out; then the tour's
    E1M8 base for A_BossDeath."""
    out = []
    left = {k: PER_ROUTINE for _, k, _ in WANT}
    for run, key, n in WANT:
        n = min(n, left[key])
        if n <= 0:
            continue
        calls = [c for c in load_log(run)['hits'][key] if c[2] is not None]
        chosen = LKP.by_class(calls, lambda c: c[2], n)
        left[key] -= len(chosen)
        if chosen:
            out.append((run, key, [tuple(c) for c in chosen]))
    out.append((BOSS_RUN, LOOK, [tuple(boss_base_hit())]))
    return out


def boss_base_hit() -> List[Any]:
    """A_Look's call on E1M8 that the A_BossDeath cases start from: the
    first of the tour's E1M8 tics that does not nest."""
    for row in load_log(BOSS_RUN)['hits'][LOOK]:
        if row[1] >= E1M8_FROM + 5 and not row[3] and row[2] is not None:
            return row
    raise PartError('no A_Look call on E1M8 in the tour')


def case_path(run: str, hit: int) -> Path:
    use_cases()
    return GC.case_dir(run, CALLFN) / ('h%08d.case.z' % hit)


def _capture_job(job) -> str:
    run, hits = job
    use_cases()
    top = max(h for h, _ in hits)
    tics = [-1] * top
    for h, t in hits:
        tics[h - 1] = t
    made = GC.capture(run, CALLFN, [h for h, _ in hits], tics,
                      say=lambda *a: None)
    return '%s: %d made' % (run, len(made))


def capture(jobs: int = 2, say=print) -> None:
    """Every chosen call the case directory lacks, by run, at most
    GC.BATCH a ref816 run, a nesting hit last in its run; the first batch
    of a run alone (it writes the run's base: the tour's is its E1M8
    call). Then every case is checked to enter the logged action at the
    logged tic (verify())."""
    use_cases()
    by: Dict[str, Dict[int, Tuple[int, int]]] = {}
    for run, key, hits in selection():
        d = by.setdefault(run, {})
        for h, t, _, nest in hits:
            if not case_path(run, h).exists():
                d[h] = (t, nest)
    todo = []
    for run, d in sorted(by.items()):
        batch: List[Tuple[int, int]] = []
        for h, (t, nest) in sorted(d.items()):
            batch.append((h, t))
            if nest or len(batch) == GC.BATCH:
                todo.append((run, batch))
                batch = []
        if batch:
            todo.append((run, batch))
    first = []
    for run in sorted({t[0] for t in todo}):
        if not GC.base_path(run).exists():
            j = next(t for t in todo if t[0] == run)
            first.append(j)
            todo.remove(j)
    for group in (first, todo):
        if not group:
            continue
        check_disk()
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for got in pool.map(_capture_job, group):
                say(got)
    bad = verify()
    for p in bad:
        say('removed %s: not the logged action' % p)
        p.unlink()
    if bad:
        raise PartError('%d cases entered another action' % len(bad))


def verify() -> List[Path]:
    """The cases whose FN_P at the entry is not the logged action, or
    whose gametic is not the logged one."""
    use_cases()
    table = CL.Linkmap()
    fn_p = table.address(FN_P)
    gt = table.address('g_game65.s:_g_gametic')
    bad = []
    for run, key, hits in selection():
        want = table.address(key) & 0xFFFFFF
        for h, tic, _, _ in hits:
            p = case_path(run, h)
            if not p.exists():
                continue
            c = GC.load_case(p)
            got = int.from_bytes(c.entry.read(fn_p, 3), 'little')
            gametic = int.from_bytes(c.entry.read(gt, 4), 'little')
            if got != want or gametic != tic:
                bad.append(p)
    return bad


def chosen() -> List[Tuple[str, str, str]]:
    """(action, case path, signature) of every chosen call captured."""
    out = []
    for run, key, hits in selection():
        for h, _, sig, _ in hits:
            p = case_path(run, h)
            if p.exists():
                out.append((key, str(p), sig))
    return out


# ---------------------------------------------------------------------------
# Synthetic cases
# ---------------------------------------------------------------------------

def uconst(name: str) -> int:
    return MSP.uconst(name)


def ptr(mem, a: int) -> int:
    return int.from_bytes(mem.read(a, 4), 'little') & 0xFFFFFF


def actor_of(case: GC.Case) -> int:
    return ptr(case.entry, MSP.dp_address(case, '_Dp', 0))


def as_action(base: GC.Case, key: str, pokes=(), note: str = '',
              variant: str = '') -> GC.Case:
    """base (a case captured at callFn) with FN_P = key's address and the
    pokes: the reference's callFn again by --call."""
    t = CL.Linkmap()
    fp = (t.address(key) & 0xFFFFFF).to_bytes(3, 'little')
    entry = base.entry.copy()
    entry.header = base.entry.header
    entry.write(t.address(FN_P), fp)
    for a, d in pokes:
        entry.write(a, d)
    after, call = MSP.ref_call(entry, CALLFN, (), LKP.ref_regs(base))
    hdr = dict(base.header, routine=CALLFN, note=note or variant, call=call,
               variant=variant)
    return GC.Case(hdr, entry, after, None)


def mobjs(case: GC.Case) -> List[int]:
    """The addresses of the case's mobjs (pool and zone), from the
    bridge's reader of its entry."""
    from bridge.fields import R as Ref
    up = GR.Upstream(case)
    out = []
    for kind in ('mobj', 'zmobj'):
        for i in sorted(up.s_in['objects'].get(kind, {})):
            out.append(up.r_in.ref_address(Ref(kind, i, None)))
    return out


def word(mem, a: int, n: int = 2, signed: bool = True) -> int:
    return int.from_bytes(mem.read(a, n), 'little', signed=signed)


def nearest_monster(base: GC.Case) -> Optional[Tuple[int, int]]:
    """(distance in whole units, address) of the shootable live mobj
    nearest the case's actor (not it, not its target, no missile)."""
    mem = base.entry
    ap = actor_of(base)
    tgt = ptr(mem, ap + uconst('UO_MO_TARGET'))
    ox, oy = uconst('UO_MO_X'), uconst('UO_MO_Y')
    ax, ay = word(mem, ap + ox, 4), word(mem, ap + oy, 4)
    best = None
    for a in mobjs(base):
        if a in (ap, tgt):
            continue
        fl = word(mem, a + uconst('UO_MO_FLAGS'), 4, False)
        if not fl & 4 or fl & (1 << 16) or \
                word(mem, a + uconst('UO_MO_HEALTH')) <= 0:
            continue                    # MF_SHOOTABLE, no MF_MISSILE, alive
        d = max(abs(word(mem, a + ox, 4) - ax),
                abs(word(mem, a + oy, 4) - ay)) >> 16
        if best is None or d < best[0]:
            best = (d, a)
    return best


PAGING_NEAR = 48                # whole units: the monster's own block is
                                # among those the troopshot's check walks


def paging_base(paths: Sequence[str]) -> Optional[str]:
    """Of the captured A_TroopAttack calls that shoot, the one with a
    monster nearest the imp (within PAGING_NEAR), remembered in
    OUT/paging.json."""
    memo = OUT / 'paging.json'
    key = sorted(paths)
    if memo.exists():
        got = json.loads(memo.read_text())
        if got.get('paths') == key:
            return got.get('base')
    best = None
    for p in key:
        got = nearest_monster(GC.load_case(Path(p)))
        if got and got[0] <= PAGING_NEAR and (best is None or
                                              got[0] < best[0]):
            best = (got[0], p)
    out = best[1] if best else None
    memo.write_text(json.dumps({'paths': key, 'base': out,
                                'distance': best[0] if best else None}))
    return out


def paging_case(base: GC.Case) -> GC.Case:
    """A captured A_TroopAttack that shoots, with the nearest shootable
    monster moved 10 units in front of the imp (towards its target, its z
    the imp's): the troopshot hits it in checkMissile (P_DamageMobj under
    P_TryMove's checkThing)."""
    import math
    mem = base.entry
    ap = actor_of(base)
    tgt = ptr(mem, ap + uconst('UO_MO_TARGET'))
    ox, oy, oz = uconst('UO_MO_X'), uconst('UO_MO_Y'), uconst('UO_MO_Z')
    ax, ay = word(mem, ap + ox, 4), word(mem, ap + oy, 4)
    got = nearest_monster(base)
    if got is None:
        raise PartError('no monster near the imp')
    a = got[1]
    tx, ty = word(mem, tgt + ox, 4), word(mem, tgt + oy, 4)
    th = math.atan2(ty - ay, tx - ax)
    nx = ax + int(round(10 * 65536 * math.cos(th)))
    ny = ay + int(round(10 * 65536 * math.sin(th)))
    pokes = [(a + ox, (nx & 0xFFFFFFFF).to_bytes(4, 'little')),
             (a + oy, (ny & 0xFFFFFFFF).to_bytes(4, 'little')),
             (a + oz, mem.read(ap + oz, 4))]
    return as_action(base, TROOP, pokes, '%s: a monster in front' % (
        base.path.name if base.path else '?'), 'paging: a monster in front')


def boss_cases(base: GC.Case) -> List[Tuple[str, GC.Case]]:
    """A_BossDeath on E1M8 (the tour's A_Look call there): a baron dying
    as the last one (every baron's health 0), with another baron alive,
    with the player dead too; and the A_Look's own actor (not a baron)."""
    mem = base.entry
    bruiser = uconst('UC_MT_BRUISER')
    ot, oh = uconst('UO_MO_TYPE'), uconst('UO_MO_HEALTH')
    barons = [a for a in mobjs(base) if word(mem, a + ot, 2, False) ==
              bruiser]
    if len(barons) < 2:
        raise PartError('E1M8 has %d barons in the tour\'s state' %
                        len(barons))
    t = CL.Linkmap()
    dp0 = MSP.dp_address(base, '_Dp', 0)
    zero = bytes(2)
    ph = t.address('g_game65.s:_g_player') + uconst('UO_PL_HEALTH')
    me = [(dp0, barons[0].to_bytes(4, 'little'))]
    dead = [(a + oh, zero) for a in barons]
    out = [('last baron', as_action(base, BOSS, me + dead, variant='E1M8: '
                                    'the last baron dies')),
           ('another alive', as_action(base, BOSS, me + dead[:1],
                                       variant='E1M8: another baron '
                                       'alive')),
           ('player dead', as_action(base, BOSS, me + dead + [(ph, zero)],
                                     variant='E1M8: the player dead')),
           ('not a baron', as_action(base, BOSS, variant='E1M8: not a '
                                     'baron'))]
    return out


# ---------------------------------------------------------------------------
# The runs
# ---------------------------------------------------------------------------

def spec_of(key: str) -> Dict[str, Any]:
    return GR.all_args()[key]


def evaluate(case: GC.Case, entry: str, b: RC.Build, kind: str, path: str,
             extra: Sequence = (), depth: int = 0) -> List[Dict[str, Any]]:
    """A case's run on image b ($A5, f121), or its stop check and the
    variant with the stopped action removed."""
    spec = spec_of(entry)
    prep = MSP.Prepared(case, spec)
    r = MSP.run_one(case, spec, b, FILL, PROFILE, extra, keep_crash=True,
                    prep=prep)
    if r.get('lowest_s') is not None and isinstance(r['lowest_s'], dict):
        r['lowest_s'] = r['lowest_s'].get('s')
    cm = r.pop('_crash', None)
    stop = r.get('stop')
    r.update(kind=kind, entry=entry, path=path)
    if not (stop and stop[0] == GL.GS['UNBUILTD'] and
            stop[1] >> 8 == LKP.ACTTAB_TABLE):
        return [r]
    number = stop[1] & 0xFF
    states = LKP.stopped_states(cm, case, number)
    keys = LKP.acttab_keys()
    action = keys[number - 1] if 0 < number <= len(keys) else '?'
    diff = []
    if not states:
        diff.append('no state of the snapshot has ACTTAB %d (%s)' % (
            number, action))
    if r.get('strays'):
        diff.append('%d stray writes' % r['strays'])
    r.update(kind='stop', ok=not diff, diff=diff, waiting=action,
             states=states)
    out = [r]
    if states and depth < 3:
        try:
            v, vextra = LKP.action_removed(case, states, extra)
        except Exception as error:      # reported, never hidden
            out.append({'ok': False, 'kind': 'action removed',
                        'entry': entry, 'path': path, 'error': '%s: %s' % (
                            type(error).__name__, error)})
            return out
        out += evaluate(v, entry, b, 'action removed', path, vextra,
                        depth + 1)
    return out


def plan(synthetic: bool = True, entries=None) -> List[Tuple]:
    """The jobs: ('case', path, action, signature) of each chosen call,
    and the synthetic ones ('as', path, action, which), ('paging', path),
    ('boss', path, variant)."""
    js: List[Tuple] = []
    troops: Dict[str, str] = {}
    shooting: List[str] = []
    boss = None
    for key, path, sig in chosen():
        if key == LOOK:
            boss = path
            continue
        js.append(('case', path, key, sig))
        if key == TROOP:
            cls = 'melee' if 'checkMeleeRange=1' in sig else \
                'missile' if 'P_SpawnMissile' in sig else ''
            if cls and cls not in troops:
                troops[cls] = path
            if cls == 'missile':
                shooting.append(path)
    if synthetic:
        for cls, path in sorted(troops.items()):
            js.append(('as', path, CYBER, cls))
            js.append(('as', path, BRUIS, cls))
        if shooting:
            js.append(('paging', tuple(shooting)))
        if boss:
            for v in ('last baron', 'another alive', 'player dead',
                      'not a baron'):
                js.append(('boss', boss, v))
    if entries:
        js = [j for j in js if job_entry(j) in entries]
    return js


def job_entry(j: Tuple) -> str:
    return {'paging': TROOP, 'boss': BOSS}.get(j[0]) or j[2]


def _job(job: Tuple) -> List[Dict[str, Any]]:
    obj, j = job
    use_cases()
    b = G.load_build(Path(obj), NAME)
    try:
        if j[0] == 'case':
            _, path, key, sig = j
            return evaluate(GC.load_case(Path(path)), key, b, 'captured',
                            sig or '(no call)')
        if j[0] == 'as':
            _, path, key, cls = j
            base = GC.load_case(Path(path))
            case = as_action(base, key, (), variant='from a %s '
                             'A_TroopAttack' % cls)
            return evaluate(case, key, b, 'synthetic',
                            'from a %s A_TroopAttack' % cls)
        if j[0] == 'paging':
            path = paging_base(j[1])
            if path is None:
                return [{'ok': False, 'kind': 'synthetic', 'entry': TROOP,
                         'case': 'paging', 'error': 'no captured shot with '
                         'a monster within %d units' % PAGING_NEAR}]
            base = GC.load_case(Path(path))
            case = paging_case(base)
            a = nearest_monster(base)[1]
            oh = uconst('UO_MO_HEALTH')
            hit = word(case.after, a + oh) < word(case.entry, a + oh)
            rs = evaluate(case, TROOP, b, 'synthetic', 'paging')
            for r in rs:                # (the reference must take the path)
                if not hit:
                    r['ok'] = False
                    r['diff'] = ['the reference\'s troopshot hit nothing']
            for r in rs:
                if r.get('ok') and not r.get('fc_loads'):
                    r['ok'] = False
                    r['diff'] = ['no group load: the paging not taken']
            return rs
        if j[0] == 'boss':
            got = dict(boss_cases(GC.load_case(Path(j[1]))))
            case = got[j[2]]
            up = GR.Upstream(case)
            made = len(up.s_out['objects'].get('floor', {})) - \
                len(up.s_in['objects'].get('floor', {}))
            rs = evaluate(case, BOSS, b, 'synthetic', '%s (%d floors)' % (
                j[2], made))
            if (made > 0) != (j[2] == 'last baron'):
                for r in rs:            # (the reference must take the path)
                    r['ok'] = False
                    r['diff'] = ['the reference made %d floors' % made]
            return rs
    except Exception as error:          # reported per job, never hidden
        return [{'ok': False, 'kind': j[0], 'entry': job_entry(j),
                 'case': str(j[1]), 'error': '%s: %s' % (
                     type(error).__name__, error)}]
    raise PartError('a job %r' % (j,))


def run_jobs(js: Sequence[Tuple], obj: Path = OUT, workers: int = 2,
             say=None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    work = [(str(obj), j) for j in js]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(_job, work):
            out += got
            if say:
                for r in got:
                    if not r.get('ok'):
                        say('FAIL %s %s %s %s' % (
                            r.get('entry'), r.get('case'), r.get('path'),
                            r.get('diff') or r.get('error') or
                            r.get('stop') or r.get('stray_first')))
    return out


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return LKP.summarize(results)


def check(jobs: int = 2, entries=None, say=print) -> Dict[str, Any]:
    build()
    b = load()
    js = plan(True, entries)
    say('%d jobs' % len(js))
    start = time.time()
    res = run_jobs(js, OUT, jobs, say)
    return {'entries': summarize(res), 'runs': len(res),
            'failures': sum(1 for r in res if not r.get('ok')),
            'strays': sum(r.get('strays') or 0 for r in res),
            'seconds': round(time.time() - start), 'fill': '%02x' % FILL,
            'profile': PROFILE, 'sizes': sizes(b)}


# ---------------------------------------------------------------------------
# The planted bugs (at most 3, the lean rule): each in a scratch copy of
# the sources, built into a temporary directory, must fail its check
# ---------------------------------------------------------------------------

CS = 'game/%s/chase.s' % PART
PLANTS = {
    # movecount decremented after the move (pMove first, then --movecount
    # and its test)
    'movecount-after': ([(CS, """@chase: GETMO CH_AP             ; if (--movecount < 0 || !P_Move(actor))
        ldy #LN_C + MC_MOVEC""", """@chase: ARG01 CH_AP
        FCALL pMove
        pha
        GETMO CH_AP
        ldy #LN_C + MC_MOVEC"""), (CS, """        plp
        bmi @newdir
        ARG01 CH_AP
        FCALL pMove
        cmp #0
        bne @sound""", """        plp
        bpl :+
        pla
        bra @newdir
:       pla
        cmp #0
        bne @sound""")], [CHASE]),
    # the attack's P_Random order: A_PosAttack's damage before the spread
    'random-order': ([(CS, """        FCALL spreadAngle
        lda #5                  ; damage = (P_Random() % 5 + 1) * 3
        FCALL p_enemy_randMod
        inc a
        TIMES3
        FCALL lineAttack
        rts

        ROUTINE A_SPosAttack""", """        lda #5                  ; damage = (P_Random() % 5 + 1) * 3
        FCALL p_enemy_randMod
        inc a
        TIMES3
        pha
        FCALL spreadAngle
        pla
        FCALL lineAttack
        rts

        ROUTINE A_SPosAttack""")], [POS]),
    # A_BossDeath's floor type: lowerFloor (to the highest floor next to
    # it) instead of lowerFloorToLowest
    'boss-floor-type': ([(CS, """        ldy #UC_LOWERFLOORTOLOWEST
        FCALL newFloor""", """        ldy #UC_LOWERFLOOR
        FCALL newFloor""")], [BOSS]),
}


def run_plant(name: str, jobs: int = 2, say=None, js=None
              ) -> Dict[str, Any]:
    bugs, entries = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-chase-plant-', dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', bugs)
        res = run_jobs(js if js is not None else plan(True, entries), obj,
                       jobs)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    failed = [r for r in res if not r.get('ok')]
    out = {'entries': entries, 'runs': len(res), 'failed': len(failed),
           'caught': bool(failed),
           'first': [{x: r.get(x) for x in ('case', 'path', 'diff',
                                             'error') if r.get(x)}
                     for r in failed[:2]]}
    if say:
        say('%s: %d of %d runs fail: %s' % (name, len(failed), len(res),
                                            'caught' if failed else
                                            'NOT CAUGHT'))
    return out


def write_report(rep: Dict[str, Any], **parts: Any) -> Path:
    old = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    out = dict(old)
    out.update(rep)
    out.update({k: v for k, v in parts.items() if v is not None})
    out['format'] = 'game-part-report 1'
    out['part'] = PART
    out['wave'] = 6
    out['build_kb'] = MSP.du_kb(OUT)
    out['notes'] = [
        'lean checkpoint (the owner, 2026-10-02): at most 40 calls a '
        'routine, chosen by branch (the signature: the direct calls and '
        'their results), the $A5 machine only, the f121 profile only',
        'cpu_cycles: the W65C02S cycles from call_entry to the return '
        '(routine mode, the slots empty at the call); clock: fabric clocks',
        'synthetic: A_CyberAttack and A_BruisAttack from captured '
        'A_TroopAttack calls (FN_P poked), the paging case (a monster in '
        'front of a shooting imp), A_BossDeath on the tour\'s E1M8',
        'A_BossDeath\'s floors: the stand-in bd_floors (request 1)']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1, default=str) + '\n')
    return REPORT


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--log', action='store_true')
    parser.add_argument('--runs', default=','.join(LOG_RUNS))
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--entries', default='')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args(argv)
    status = 0
    if args.build:
        b = load(build())
        print(json.dumps(sizes(b), indent=1))
    if args.log:
        runs = [r for r in args.runs.split(',') if r]
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for _ in pool.map(log, runs):
                pass
    if args.capture:
        capture(args.jobs)
    if args.check:
        rep = check(args.jobs, [e for e in args.entries.split(',') if e]
                    or None)
        if not args.entries:
            write_report(rep)
        for k, e in sorted(rep['entries'].items()):
            print('%-28s %4d runs %3d failed  cycles %s  S %s' % (
                k, e['runs'], e['failures'], e['cpu_cycles'],
                e['lowest_s']))
            for p, n in sorted(e['paths'].items()):
                print('      %3d  %s' % (n, p))
        print('runs %d, failures %d, stray writes %d, %d s' % (
            rep['runs'], rep['failures'], rep['strays'], rep['seconds']))
        status |= 1 if rep['failures'] or rep['strays'] else 0
    if args.plants:
        pl = {n: run_plant(n, args.jobs, print) for n in PLANTS}
        write_report({}, plants=pl)
        status |= 0 if all(p['caught'] for p in pl.values()) else 1
    return status


if __name__ == '__main__':
    sys.exit(main())
