#!/usr/bin/env python3
"""Part damage's checkpoint (milestone 10, wave 2; docs/GAME.md 2.4, 3.5;
docs/game-parts/damage.md): its image, its captures, its routine-mode runs
on both fills and both profiles, its synthetic cases, the random check of
the thrust, its planted bugs, and build/native/game/damage/report.json.

Usage:  python3 tools/native/gparts/damage.py --build
        python3 tools/native/gparts/damage.py --capture [--jobs 2]
        python3 tools/native/gparts/damage.py --check [--jobs 2] [--sample K]
        python3 tools/native/gparts/damage.py --synthetic
        python3 tools/native/gparts/damage.py --random [--n 100000]
        python3 tools/native/gparts/damage.py --plants

The image (build()): `make -f game.mk part P=damage DM_TEST=1` from a
scratch copy of the build files, into build/native/game/damage/; DM_TEST=1
adds the part's test routine (game/damage/dtest.s: the thrust's bulk
driver, in the card's driver area).

The captures (capture()): tools/native/gamecap.py's, into the part's own
build/native/game/damage/cases/: every call of P_DamageMobj, P_DropWeapon,
lowerWeapon and wInfoOf of the three demos (and the newgame's and the
tour's wInfoOf), and 100 calls of wInfo in each demo spread evenly (wInfo
has 5,934 calls) with every call of the newgame and the tour.

A run (run_one()): the routine harness of part mobjstate
(tools/native/gparts/mobjstate.py: the case's entry state through the game
manifest into a machine poisoned with $A5 or $5A, the entry's inputs, the
call, the state read back and compared with the reference's return state,
gcanon's routine mode, exclusions R1-R6 and R7 only, every declared
output), on a2vm under a cost profile (f121, fastpath), with the write log:
no CPU write outside the places this part's routines and their callees
may write (stray()).

Eligible cases (GAME.md 3.5 step 6): every dispatch target the call
reaches is built. P_DamageMobj reaches ACTTAB through P_SetMobjState (the
pain, see, death and extreme death states' actions) and through
P_DropWeapon's setPsprite (the weapon's down state's A_Lower, part pspr):
reaches() reads them from the reference's memory at the call. A call that
reaches an unbuilt action is a "stop check": the native stops at that
action's DCALL with the action's number. Its variant with that state's
action removed from the states table on both sides (a synthetic poke of
upstream's table and of the native GTAB copy) runs the whole call and is
compared like any case ("action removed").
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
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

from bridge.port import PortReader, PortError  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL, \
    render_check as RC  # noqa: E402
from ref816 import bounded  # noqa: E402
import mobjstate as MSP  # noqa: E402  (part mobjstate's harness, wave 1)

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'damage'
OUT = GL.GAME / PART
MYCASES = OUT / 'cases'
REPORT = OUT / 'report.json'
FILLS = (0xA5, 0x5A)
PROFILES = ('f121', 'fastpath')
NAME = 'ptest'
BUDGET = 1800                   # GAME.md 2.4: upstream 1,363 x 1.3
MODULES = ('dinter', 'dweap')
TEST_MODULES = ('dtest',)
DAMAGE = 'p_inter65.s:P_DamageMobj'
KILL = 'p_inter65.s:killMobj'
DROP = 'p_pspr65.s:P_DropWeapon'
LOWER = 'p_pspr65.s:lowerWeapon'
WINFO = 'p_pspr65.s:wInfo'
WINFOOF = 'p_pspr65.s:wInfoOf'


class PartError(Exception):
    pass


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

def build(game: Path = GL.GAME, bugs: Sequence[Tuple[str, str, str]] = (),
          test: bool = True) -> Path:
    """The part's image (game/damage/ptest.*) from a scratch copy of the
    build files (game.mk, math.inc, integrated.txt, the parts' fragments)
    and the bugs (file under src/native, old, new) applied to copies; every
    other source from the tree (game.mk's vpath). The copy is deleted."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-damage-build-', dir=str(BUILD)))
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
        if objs.exists():               # (damage.inc is no prerequisite)
            for p in objs.glob('*.o'):
                p.unlink()
        cmd = ['make', '-s', '-C', str(src), '-f', 'game.mk', 'part',
               'P=%s' % PART, 'ROOT=%s' % ROOT, 'GAME=%s' % game]
        if test:
            cmd.append('DM_TEST=1')
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
    """The part's bytes by module (the image's map), the math stand-in's
    (request R1: dinter.s's dm_pta3, dm_finesine, dm_finecosine, which go
    when the tic images link math.s's) and the weapon table (in the core)
    apart."""
    ms = MSP.module_ranges(b)
    by = {m: sum(hi + 1 - lo for _, lo, hi in ms.get(m, ()))
          for m in MODULES + TEST_MODULES}
    part = sum(by[m] for m in MODULES)
    lab = b.labels
    standin = lab['dm_math_end'] - lab['dm_math'] \
        if 'dm_math' in lab and 'dm_math_end' in lab else 0
    table = 12 * 9
    own = part - standin
    mine = set(next(x for x in GL.PARTS if x['name'] == PART)['routines'] +
               next(x for x in GL.PARTS if x['name'] == PART)['helpers'])
    try:
        rs = {k: v for k, v in G.routine_sizes(b)[0].items() if k in mine}
    except Exception as error:          # (a report only)
        rs = {'error': str(error)}
    return {'routines': rs,
            'modules': by, 'part_bytes': part, 'standin_bytes': standin,
            'weaponinfo_bytes': table, 'own_bytes': own, 'budget': BUDGET,
            'over_budget_pct': round(100.0 * (own - BUDGET) / BUDGET, 1),
            'groups': sorted({seg for m in MODULES for seg, _, _ in
                              ms.get(m, ())})}


# ---------------------------------------------------------------------------
# The cases
# ---------------------------------------------------------------------------

def use_cases(where: Path = MYCASES) -> None:
    MSP.use_cases(where)


# (run, file:label, how many: None every call, N evenly spread)
CAPTURES = [
    ('demo3', DAMAGE, None), ('demo1', DAMAGE, None), ('demo2', DAMAGE, None),
    ('demo3', DROP, None), ('demo1', DROP, None), ('demo2', DROP, None),
    ('demo3', LOWER, None), ('demo1', LOWER, None), ('demo2', LOWER, None),
    ('demo3', WINFOOF, None), ('demo1', WINFOOF, None),
    ('demo2', WINFOOF, None), ('newgame', WINFOOF, None),
    ('tour', WINFOOF, None),
    ('demo3', WINFO, 100), ('demo1', WINFO, 100), ('demo2', WINFO, 100),
    ('newgame', WINFO, None), ('tour', WINFO, None),
]


def _capture_job(job) -> str:
    run, key, hits = job
    use_cases(MYCASES)
    sv = GC.survey_of(run)
    tics = sv['routines'][key]['tic']
    made = GC.capture(run, key, hits, tics, say=lambda *a: None)
    return '%s %s: %d made, %d asked' % (run, key, len(made), len(hits))


def capture(jobs: int = 2, say=print) -> None:
    """Every capture of CAPTURES the part's case directory lacks: the
    first batch of each run alone (it writes the run's base), the rest
    jobs at a time."""
    use_cases(MYCASES)
    todo = []
    for run, key, n in CAPTURES:
        hits = MSP.hits_of(run, key, n)
        d = GC.case_dir(run, key)
        missing = [h for h in hits if not (d / ('h%08d.case.z' % h)).exists()]
        for i in range(0, len(missing), GC.BATCH):
            todo.append((run, key, missing[i:i + GC.BATCH]))
    first = []
    for run in sorted({t[0] for t in todo}):
        if not GC.base_path(run).exists():
            j = next(t for t in todo if t[0] == run)
            first.append(j)
            todo.remove(j)
    if first:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for got in pool.map(_capture_job, first):
                say(got)
    if not todo:
        return
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_capture_job, todo):
            say(got)


def case_paths(run: str, key: str, where: Path = MYCASES) -> List[Path]:
    use_cases(where)
    return sorted(GC.case_dir(run, key).glob('h*.case.z'))




def spec_of(key: str) -> Dict[str, Any]:
    return GR.all_args()[key]


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

LOG_RANGES = MSP.LOG_RANGES
ACTTAB_TABLE = list(GL.DISPATCH).index('ACTTAB') + 1


def allowed_main(b: RC.Build) -> List[Tuple[int, int]]:
    """Part mobjstate's places (P_SetMobjState runs in this part's calls)
    and this part's scratch block."""
    lo, n = GL.scratch_blocks()[PART]
    return MSP.allowed_main(b) + [(lo, lo + n)]


def stray(writes, b: RC.Build, header: Dict[str, Any]) -> List[str]:
    """CPU writes outside the allowed places (part mobjstate's rule, with
    this part's scratch block, and math.s's mt_far patching its own two
    operands in the card's bank 1: the tables bank's reads of the
    stand-in's R_PointToAngle3 and sines, requests R1 and R6)."""
    allowed = allowed_main(b)
    desc = b.segments['DESC']
    drv = b.segments['DRIVER']
    loader = b.segments['RLOAD']
    far = b.segments['RFAR']
    mfar = b.segments.get('MATHFAR')
    lab = b.labels
    patched = {lab['mt_far_count'] + 1, lab['mt_far_stride'] + 1}
    aux = MSP.allowed_aux(header)
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


_WI: Dict[str, int] = {}


def weaponinfo_near() -> int:
    """upstream's weaponinfo's near address (wInfo's X less it is the
    record's offset)."""
    if not _WI:
        _WI['a'] = GC.CL.Linkmap().address('p_pspr65.s:weaponinfo') & 0xFFFF
    return _WI['a']


def run_one(case, spec: Dict[str, Any], b: RC.Build, fill: int,
            profile: Optional[str], extra: Sequence = (),
            prep: Optional[MSP.Prepared] = None, keep_crash: bool = False
            ) -> Dict[str, Any]:
    """The case on image b at fill under profile: the comparison (gcanon's
    routine mode), wInfo's and wInfoOf's X and A, the stray writes, the
    native checks, the call's clock and cycles, the lowest S. extra:
    image records after the state (a synthetic poke of GTAB); keep_crash:
    a stop's snapshot in _crash."""
    if prep is None:
        prep = MSP.Prepared(case, spec)
    case, up = prep.case, prep.up
    res: Dict[str, Any] = {'case': '%s/%s' % (case.path.parent.parent.name,
                                              case.path.name) if case.path
                           else case.header.get('note') or 'synthetic',
                           'routine': case.key, 'hit': case.header['hit'],
                           'fill': '%02x' % fill, 'profile': profile,
                           'ok': False}
    if prep.problems:
        res['error'] = 'bridge: ' + '; '.join(prep.problems[:3])
        return res
    if prep.accepted:
        res['stale_links'] = len(prep.accepted)
    mf, header, banks = prep.mf, prep.header, prep.banks
    img = G.Image(b, fill, store=True)
    img.recs += GR.base_records(up.gamemap)
    img.recs += prep.recs
    img.recs += list(extra)
    for a, d in prep.zp:
        img.main(a, d)
    name = spec['native']
    img.poke_word('dg_entry', b.labels[name])
    img.poke_label('dg_grp', bytes([MSP.entry_group(b, name)]))
    work = Path(tempfile.mkdtemp(prefix='tmp-damage-run-', dir=str(BUILD)))
    try:
        start = time.time()
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), banks=banks, profile=profile,
                  write_log=LOG_RANGES)
        res['seconds'] = round(time.time() - start, 2)
        ls = r.state.get('lowest_s')
        res['lowest_s'] = ls.get('s') if isinstance(ls, dict) else ls
        writes = MSP.read_log(work / 'writes.log') \
            if (work / 'writes.log').exists() else []
        res['clock'], res['cpu_cycles'] = MSP.call_clock(writes, b)
        st = stray([w for _, w in writes], b, header)
        res['strays'] = len(st)
        if st:
            res['stray_first'] = st[:4]
        ended = r.ended()
        res['ended'] = ended
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                cm = G.load_snapshot(p)
                res['stop'] = list(G.stop_codes(cm))
                if keep_crash:
                    res['_crash'] = cm
            return res
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    from native import setupcheck as SC
    try:
        nat = PortReader(mf).read(SC.port_memory(m))
    except PortError as error:
        res['diff'] = ['the port reader: %s' % error]
        return res
    diff = gcanon.compare(up.s_out, nat, 'routine')
    diff += MSP.native_checks(m)
    res['fc_loads'] = m.main[GL.RT['FC_LOADS']] | \
        m.main[GL.RT['FC_LOADS'] + 1] << 8
    lab = b.labels
    if name in ('wInfo', 'wInfoOf'):
        # X (and A): the record's offset; upstream's X less the table's
        # near address
        nx = G.card_byte(m, lab['dg_rx'])
        na = G.card_byte(m, lab['dg_ra'])
        ux = (case.regs_out['x'] - weaponinfo_near()) & 0xFFFF
        ua = (case.regs_out['a'] - weaponinfo_near()) & 0xFFFF
        res['weapon_offset'] = ux
        if (nx, na) != (ux, ua):
            diff.append('X, A: %02X, %02X; upstream\'s offsets %04X, %04X'
                        % (nx, na, ux, ua))
    res['diff'] = diff[:12]
    res['ok'] = not diff and not res['strays']
    return res


# ---------------------------------------------------------------------------
# The stops at an unbuilt action, and the variants with the action removed
# ---------------------------------------------------------------------------

STATES = MSP.STATES
_GC: Dict[str, int] = {}


def gconst(name: str) -> int:
    if not _GC:
        _GC.update(dict(LL.game_constants()))
    return _GC[name]


def stopped_states(cm, prep: MSP.Prepared, number: int) -> List[int]:
    """The states whose action is ACTTAB entry `number` among those the
    stop's snapshot holds: the target's (its cache line; P_SetMobjState
    sets the state before the action) and the two psprites' (setPsprite
    the same)."""
    up, case = prep.up, prep.case
    cands = []
    try:
        t = up.ref(int.from_bytes(up.source('dp:_Dp:4'), 'little'))
        got = MSP.mobj_at_stop(cm, GR.handle_of(prep.mf, t))
        if got:
            cands.append(got['state'])
    except Exception:                   # (an entry with no mobj in _Dp)
        pass
    pl = LL.G['G_PLAYER']
    for k in ('PL_PSPRITES_0_STATE', 'PL_PSPRITES_1_STATE'):
        a = pl + gconst(k)
        cands.append(cm.main[a] | cm.main[a + 1] << 8)
    nums = MSP.act_numbers()
    out = []
    for s in cands:
        if s == 0xFFFF or s in out:
            continue
        act = MSP.state_record(case.entry, s)['action']
        if act and nums.get(act) == number:
            out.append(s)
    return out


def action_removed(case: GC.Case, states: Sequence[int], extra: Sequence
                   ) -> Tuple[GC.Case, List]:
    """The case with the states' actions removed (their action pointer 0
    in upstream's table, and the native GTAB's copy from the same bytes),
    run again on ref816 (--call): the variant and its GTAB records."""
    t = GC.CL.Linkmap()
    mem = case.entry.copy()
    mem.header = case.entry.header
    for s in states:
        mem.write(t.address(STATES) + 16 * s + 6, bytes(4))
    regs = {'a': case.regs_in['a'] & 0xFFFF, 'x': case.regs_in['x'] & 0xFFFF,
            'y': case.regs_in['y'] & 0xFFFF}
    after, call = MSP.ref_call(mem, case.key, (), regs)
    note = '%s, state %s\'s action removed' % (
        '%s/%s' % (case.path.parent.parent.name, case.path.name)
        if case.path else case.header.get('note') or '',
        '/'.join(str(s) for s in states))
    hdr = dict(case.header, note=note, call=call)
    v = GC.Case(hdr, mem, after, None)
    return v, list(extra) + MSP.gtab_state_records(mem, states)


def evaluate(case: GC.Case, spec: Dict[str, Any], b: RC.Build, fills,
             profiles, kind: str, entry: str, path: str = '',
             extra: Sequence = (), depth: int = 0) -> List[Dict[str, Any]]:
    """A case's runs (each fill and profile). A call that stops at an
    unbuilt action's DCALL is a stop check (every run stops there, the
    stop's action is the action of a state the snapshot holds) and its
    variant with that state's action removed is evaluated in turn."""
    prep = MSP.Prepared(case, spec)
    if not path and not prep.problems:
        path = path_of(case.key, prep.up, case)
    runs = [(f, p) for f in fills for p in profiles]
    out: List[Dict[str, Any]] = []
    first = run_one(case, spec, b, runs[0][0], runs[0][1], extra, prep,
                    keep_crash=True)
    cm = first.pop('_crash', None)
    stop = first.get('stop')
    if not (stop and stop[0] == GL.GS['UNBUILTD'] and
            stop[1] >> 8 == ACTTAB_TABLE):
        rs = [first] + [run_one(case, spec, b, f, p, extra, prep)
                        for f, p in runs[1:]]
        for r in rs:
            r.pop('_crash', None)
            r.update(kind=kind, entry=entry, path=path)
        return rs
    number = stop[1] & 0xFF
    states = stopped_states(cm, prep, number)
    keys = GL.dispatch_entries(_graph())['ACTTAB']
    action = keys[number - 1] if 0 < number <= len(keys) else '?'
    rs = [first] + [run_one(case, spec, b, f, p, extra, prep)
                    for f, p in runs[1:]]
    for r in rs:
        diff = []
        if list(r.get('stop') or [])[:2] != list(stop[:2]):
            diff.append('stop %s, not %s' % (r.get('stop'), stop[:2]))
        if not states:
            diff.append('no state of the snapshot has ACTTAB %d (%s)' % (
                number, action))
        if r.get('strays'):
            diff.append('%d stray writes' % r['strays'])
        r.pop('_crash', None)
        r.update(kind='stop', entry=entry, path=path, ok=not diff,
                 diff=diff, waiting=action, states=states)
        out.append(r)
    if states and depth < 3:
        try:
            v, vextra = action_removed(case, states, extra)
        except Exception as error:      # reported, never hidden
            out.append({'ok': False, 'kind': 'action removed',
                        'entry': entry, 'path': path, 'error': '%s: %s' % (
                            type(error).__name__, error)})
            return out
        out += evaluate(v, spec, b, fills, profiles, 'action removed',
                        entry, path + ' (%s removed)' % action.split(':')[-1],
                        vextra, depth + 1)
    return out


_GRAPH: List[Any] = []


def _graph():
    if not _GRAPH:
        from native import gcallgraph as CG
        _GRAPH.append(CG.load(write=False))
    return _GRAPH[0]


# ---------------------------------------------------------------------------
# The paths (the coverage report, GAME.md 3.5 step 2)
# ---------------------------------------------------------------------------

def uconst(name: str) -> int:
    return MSP.uconst(name)


_ADDR: Dict[str, int] = {}


def uaddr(sym: str) -> int:
    if sym not in _ADDR:
        _ADDR[sym] = GC.CL.Linkmap().address(sym)
    return _ADDR[sym]


def ptr_at(mem, a: int) -> int:
    return int.from_bytes(mem.read(a & 0xFFFFFF, 4), 'little') & 0xFFFFFF


def info_word(mem, mtype: int, field: str) -> int:
    return int.from_bytes(mem.read(uaddr('info65.s:mobjinfo') + 64 * mtype +
                                   uconst(field), 2), 'little')


def path_of(key: str, up: GR.Upstream, case: GC.Case) -> str:
    """P_DamageMobj's path from the reference's states; the weapon for
    wInfo, wInfoOf; '' for the others."""
    try:
        if key == WINFO:
            pl = up.s_in['objects']['player'][0]
            return 'weapon %d' % pl['readyweapon']
        if key == WINFOOF:
            return 'weapon %d' % (case.regs_in['a'] & 0xFFFF)
        if key != DAMAGE:
            return ''
        s_in, s_out = up.s_in, up.s_out
        t = up.ref(int.from_bytes(up.source('dp:_Dp:4'), 'little'))
        o_in = s_in['objects'][t.kind][t.id]
        o_out = s_out['objects'][t.kind].get(t.id) or {}
        pl_in = s_in['objects']['player'][0]
        pl_out = s_out['objects']['player'][0]
        bits = ['player' if pl_in['mo'] == t else 'monster']
        if not int.from_bytes(up.source('dp:_Dp+4:4'), 'little') & 0xFFFFFF:
            bits.append('no inflictor')
        if not o_in['flags'] & uconst('UC_MF_SHOOTABLE'):
            return ', '.join(bits + ['not shootable'])
        if o_in['health'] <= 0:
            return ', '.join(bits + ['dead'])
        if (o_out.get('momx'), o_out.get('momy')) != (o_in['momx'],
                                                       o_in['momy']):
            bits.append('thrust')
        if o_out.get('health') == o_in['health']:
            bits.append('no damage')
        elif o_out.get('health', 1) <= 0:
            bits.append('dies')
            st = o_out.get('state')
            if st is not None and st.id == info_word(
                    case.entry, o_in['type'], 'UO_MI_XDEATHSTATE'):
                bits.append('extreme')
            dropped = uconst('UC_MF_DROPPED_HI') << 16

            def drops(s):
                return sum(1 for k in ('mobj', 'zmobj')
                           for o in s['objects'].get(k, {}).values()
                           if not o.get('free') and o['flags'] & dropped)
            if drops(s_out) > drops(s_in):
                bits.append('drop')
        else:
            jh = 0x40
            if o_out.get('flags', 0) & jh and not o_in['flags'] & jh:
                bits.append('pain')
            if o_out.get('target') != o_in.get('target'):
                bits.append('new target')
            if o_out.get('state') != o_in.get('state') and \
                    'pain' not in bits:
                bits.append('state')
        if pl_out['armorpoints'] != pl_in['armorpoints']:
            bits.append('armour %d' % pl_in['armortype'])
        n = (s_out['globals']['m_random65.s:prndindex'] -
             s_in['globals']['m_random65.s:prndindex']) & 0xFF
        bits.append('P_Random x%d' % n)
        return ', '.join(bits)
    except Exception as error:          # (a path is a report only)
        return 'unknown: %s' % type(error).__name__


# ---------------------------------------------------------------------------
# Synthetic cases (GAME.md 2.4's row: a kill with a drop, the player's
# death, each armour type, god mode, a hit at 0 health; and the paths no
# capture takes), made from captured P_DamageMobj calls by pokes of the
# reference's memory and run on ref816 (--call)
# ---------------------------------------------------------------------------

_BASES: Dict[str, Any] = {}


def _scan_bases() -> Dict[str, Any]:
    """The captured calls the synthetic cases start from: a monster hit
    by an inflictor, a hit of the player, a zombieman (MT_POSSESSED) and
    a shotgun guy; each by its first case of the three demos (raw memory
    reads, no reader)."""
    if _BASES:
        return _BASES
    pl = uaddr('g_game65.s:_g_player')
    for run in ('demo3', 'demo1', 'demo2'):
        for p in case_paths(run, DAMAGE):
            c = GC.load_case(p)
            t = ptr_at(c.entry, MSP.dp_address(c, '_Dp'))
            i = ptr_at(c.entry, MSP.dp_address(c, '_Dp', 4))
            mo = ptr_at(c.entry, pl + uconst('UO_PL_MO'))
            mtype = c.entry.u16(t + uconst('UO_MO_TYPE'))
            health = int.from_bytes(c.entry.read(t + uconst('UO_MO_HEALTH'),
                                                 2), 'little', signed=True)
            if health <= 0:
                continue
            if t == mo:
                _BASES.setdefault('player', c)
                if i:
                    _BASES.setdefault('player-inflictor', c)
            elif i and i != t:
                _BASES.setdefault('monster', c)
                if mtype == uconst('UC_MT_POSSESSED'):
                    _BASES.setdefault('possessed', c)
                if mtype == uconst('UC_MT_SHOTGUY'):
                    _BASES.setdefault('shotguy', c)
            if len(_BASES) == 5:
                return _BASES
    return _BASES


def _w16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, 'little')


def _w32(v: int) -> bytes:
    return (v & 0xFFFFFFFF).to_bytes(4, 'little')


class Poker:
    """Pokes of a base case's reference memory (upstream's addresses)."""

    def __init__(self, base: GC.Case):
        self.base = base
        self.mem = base.entry
        self.t = ptr_at(base.entry, MSP.dp_address(base, '_Dp'))
        self.i = ptr_at(base.entry, MSP.dp_address(base, '_Dp', 4))
        self.pl = uaddr('g_game65.s:_g_player')
        self.pokes: List[Tuple[int, bytes]] = []

    def mo(self, field: str, data: bytes, ptr: Optional[int] = None) -> None:
        self.pokes.append(((self.t if ptr is None else ptr) +
                           uconst(field), data))

    def player(self, field: str, data: bytes) -> None:
        self.pokes.append((self.pl + uconst(field), data))

    def sym(self, name: str, data: bytes) -> None:
        self.pokes.append((uaddr(name), data))

    def u16(self, a: int) -> int:
        return int.from_bytes(self.mem.read(a, 2), 'little', signed=True)

    def health(self) -> int:
        for a, d in self.pokes:
            if a == self.t + uconst('UO_MO_HEALTH'):
                return int.from_bytes(d, 'little', signed=True)
        return self.u16(self.t + uconst('UO_MO_HEALTH'))

    def mtype(self) -> int:
        for a, d in self.pokes:
            if a == self.t + uconst('UO_MO_TYPE'):
                return int.from_bytes(d, 'little')
        return self.u16(self.t + uconst('UO_MO_TYPE'))

    def case(self, note: str, damage: int) -> GC.Case:
        return MSP.ref_case(self.base, DAMAGE, self.pokes,
                            note + ' (synthetic)', {'a': damage & 0xFFFF})


def _player_ok(pk: Poker) -> None:
    """The player alive and hurtable: no god mode, no invulnerability, no
    armour (each case sets what it tests)."""
    cheats = pk.u16(pk.pl + uconst('UO_PL_CHEATS'))
    pk.player('UO_PL_CHEATS', _w16(cheats & ~uconst('UC_CF_GODMODE')))
    pk.player('UO_PL_POWERS', _w16(0))
    pk.player('UO_PL_ARMORTYPE', _w16(0))
    pk.player('UO_PL_ARMORPOINTS', _w16(0))


def synthetic_cases(name: str) -> List[GC.Case]:
    """One synthetic group's cases."""
    bases = _scan_bases()
    out: List[GC.Case] = []
    prnd = 'm_random65.s:prndindex'
    if name in ('drop-possessed', 'drop-shotguy', 'rocket-possessed'):
        mt = uconst('UC_MT_SHOTGUY') if name == 'drop-shotguy' else \
            uconst('UC_MT_POSSESSED')
        key = 'shotguy' if name == 'drop-shotguy' else 'possessed'
        base = bases.get(key) or bases['monster']
        for k in range(4 if name.startswith('drop') else 1):
            pk = Poker(base)
            pk.mo('UO_MO_TYPE', _w16(mt))
            if name.startswith('rocket'):
                cheats = pk.u16(pk.pl + uconst('UO_PL_CHEATS'))
                pk.player('UO_PL_CHEATS', _w16(
                    cheats | uconst('UC_CF_ENEMY_ROCKETS')))
            pk.sym(prnd, _w16(17 * k + 3))
            dmg = pk.health() + (0 if k % 2 == 0 else 3)
            out.append(pk.case('%s %d: type %d killed, damage %d' % (
                name, k, mt, dmg), dmg))
    elif name == 'rocket-other':
        # the cheat's range MT_POSSESSED-MT_BRUISERSHOT: an imp drops a
        # rocket launcher; a barrel (outside it) drops nothing
        for mt in (uconst('UC_MT_TROOP'), uconst('UC_MT_BARREL')):
            pk = Poker(bases['monster'])
            pk.mo('UO_MO_TYPE', _w16(mt))
            cheats = pk.u16(pk.pl + uconst('UO_PL_CHEATS'))
            pk.player('UO_PL_CHEATS', _w16(
                cheats | uconst('UC_CF_ENEMY_ROCKETS')))
            dmg = pk.health() + 1
            out.append(pk.case('%s: type %d killed with the cheat' % (
                name, mt), dmg))
    elif name in ('xdeath-equal', 'xdeath-below'):
        base = bases.get('possessed') or bases['monster']
        pk = Poker(base)
        mt = pk.mtype()
        sh = info_word(base.entry, mt, 'UO_MI_SPAWNHEALTH')
        dmg = pk.health() + sh + (0 if name == 'xdeath-equal' else 1)
        out.append(pk.case('%s: health %d - damage %d against -%d' % (
            name, pk.health(), dmg, sh), dmg))
    elif name == 'player-death':
        for k, dmg in enumerate((200, 1000)):
            pk = Poker(bases['player'])
            _player_ok(pk)
            pk.sym(prnd, _w16(5 + 40 * k))
            out.append(pk.case('the player\'s death %d, damage %d' % (k, dmg),
                               dmg))
    elif name.startswith('armour'):
        pk = Poker(bases['player'])
        _player_ok(pk)
        kind, points, dmg = {'armour-green': (1, 100, 30),
                             'armour-blue': (2, 50, 30),
                             'armour-used-up': (1, 5, 30),
                             'armour-equal': (2, 15, 30),
                             'armour-negative': (1, 100, -7)}[name]
        pk.player('UO_PL_ARMORTYPE', _w16(kind))
        pk.player('UO_PL_ARMORPOINTS', _w16(points))
        pk.player('UO_PL_HEALTH', _w16(100))
        pk.mo('UO_MO_HEALTH', _w16(100))
        out.append(pk.case('%s: type %d, %d points, damage %d' % (
            name, kind, points, dmg), dmg))
    elif name in ('god', 'god-1000', 'invulnerable', 'invulnerable-1000'):
        pk = Poker(bases['player'])
        _player_ok(pk)
        if name.startswith('god'):
            cheats = pk.u16(pk.pl + uconst('UO_PL_CHEATS'))
            pk.player('UO_PL_CHEATS', _w16(cheats | uconst('UC_CF_GODMODE')))
        else:
            pk.player('UO_PL_POWERS', _w16(30))
        dmg = 1000 if name.endswith('1000') else 30
        out.append(pk.case('%s: damage %d' % (name, dmg), dmg))
    elif name in ('health-0', 'health-negative', 'not-shootable'):
        for key in ('monster', 'player'):
            pk = Poker(bases[key])
            if name == 'not-shootable':
                fl = int.from_bytes(pk.mem.read(pk.t + uconst('UO_MO_FLAGS'),
                                                4), 'little')
                pk.mo('UO_MO_FLAGS', _w32(fl & ~uconst('UC_MF_SHOOTABLE')))
            else:
                pk.mo('UO_MO_HEALTH', _w16(0 if name == 'health-0' else -5))
            out.append(pk.case('%s: the %s' % (name, key), 10))
    elif name == 'baby':
        pk = Poker(bases['player'])
        _player_ok(pk)
        pk.sym('g_game65.s:_g_gameskill', _w16(uconst('UC_SK_BABY')))
        for dmg in (31, -7):
            out.append(pk.case('baby: damage %d' % dmg, dmg))
    elif name in ('exit-sector', 'exit-sector-low'):
        pk = Poker(bases['player'])
        _player_ok(pk)
        up = GR.Upstream(bases['player'])
        mo = up.s_in['objects']['player'][0]['mo']
        ss = up.s_in['objects'][mo.kind][mo.id]['subsector']
        sec = up.s_in['objects']['subsector'][ss.id]['sector']
        a = up.r_in.ref_address(sec)
        pk.pokes.append((a + uconst('UO_SEC_SPECIAL'), _w16(11)))
        pk.mo('UO_MO_HEALTH', _w16(40))
        pk.player('UO_PL_HEALTH', _w16(40))
        dmg = 50 if name == 'exit-sector' else 20
        out.append(pk.case('%s: health 40, damage %d' % (name, dmg), dmg))
    elif name == 'turnover':
        base = bases['monster']
        for k in range(4):
            pk = Poker(base)
            iz = int.from_bytes(pk.mem.read(pk.i + uconst('UO_MO_Z'), 4),
                                'little', signed=True)
            pk.mo('UO_MO_Z', _w32(iz + (64 << 16) + (1 if k < 2 else
                                                     30 << 16)))
            pk.mo('UO_MO_HEALTH', _w16(20 + k))
            pk.sym(prnd, _w16(31 * k + 1))
            out.append(pk.case('turned over %d: dz > 64, health %d, damage '
                               '30' % (k, 20 + k), 30))
        pk = Poker(base)                # dz exactly 64: not turned over
        iz = int.from_bytes(pk.mem.read(pk.i + uconst('UO_MO_Z'), 4),
                            'little', signed=True)
        pk.mo('UO_MO_Z', _w32(iz + (64 << 16)))
        pk.mo('UO_MO_HEALTH', _w16(20))
        out.append(pk.case('not turned over: dz = 64, health 20, damage 30',
                           30))
    elif name in ('chainsaw', 'noclip', 'no-inflictor', 'pistol-player'):
        base = bases['monster']
        pk = Poker(base)
        mo = ptr_at(base.entry, pk.pl + uconst('UO_PL_MO'))
        if name in ('chainsaw', 'pistol-player'):
            pk.pokes.append((MSP.dp_address(base, '_Dp', 4), _w32(mo)))
            pk.pokes.append(((base.regs_in['s'] + 4) & 0xFFFF, _w32(mo)))
            pk.player('UO_PL_READYWEAPON', _w16(
                uconst('UC_WP_CHAINSAW') if name == 'chainsaw' else
                uconst('UC_WP_PISTOL')))
        elif name == 'noclip':
            fl = int.from_bytes(pk.mem.read(pk.t + uconst('UO_MO_FLAGS'), 4),
                                'little')
            pk.mo('UO_MO_FLAGS', _w32(fl | uconst('UC_MF_NOCLIP')))
        else:
            pk.pokes.append((MSP.dp_address(base, '_Dp', 4), _w32(0)))
            pk.pokes.append(((base.regs_in['s'] + 4) & 0xFFFF, _w32(0)))
        out.append(pk.case(name, 10))
    elif name == 'winfo-weapons':
        # wInfo and wInfoOf on every weapon (the paths: 0-8)
        base = case_paths('demo3', WINFO)[0]
        bo = case_paths('demo3', WINFOOF)[0]
        for w in range(9):
            pk = Poker(GC.load_case(base))
            pk.player('UO_PL_READYWEAPON', _w16(w))
            out.append(MSP.ref_case(pk.base, WINFO, pk.pokes,
                                    'wInfo, weapon %d (synthetic)' % w))
            c = GC.load_case(bo)
            out.append(MSP.ref_case(c, WINFOOF, [],
                                    'wInfoOf, weapon %d (synthetic)' % w,
                                    {'a': w}))
    elif name == 'threshold':
        # a monster hit by another one, threshold 0, in its spawn state
        # (the see state), and with a threshold (no new target)
        base = bases['monster']
        for k, th in enumerate((0, 5)):
            pk = Poker(base)
            mt = pk.mtype()
            spawn = info_word(base.entry, mt, 'UO_MI_SPAWNSTATE')
            pk.mo('UO_MO_STATE', _w32(uaddr(STATES) + 16 * spawn))
            pk.pokes.append((pk.t + uconst('UO_MO_THRESHOLD'), bytes([th])))
            pk.sym(prnd, _w16(157))     # (P_Random() 255: no pain)
            out.append(pk.case('threshold %d, the spawn state' % th, 1))
    else:
        raise PartError('no synthetic group %s' % name)
    return out


SYNTHETIC = ('drop-possessed', 'drop-shotguy', 'rocket-possessed',
             'rocket-other', 'xdeath-equal', 'xdeath-below', 'player-death',
             'armour-green', 'armour-blue', 'armour-used-up', 'armour-equal',
             'armour-negative', 'god', 'god-1000', 'invulnerable',
             'invulnerable-1000', 'health-0', 'health-negative',
             'not-shootable', 'baby', 'exit-sector', 'exit-sector-low',
             'turnover', 'chainsaw', 'pistol-player', 'noclip',
             'no-inflictor', 'threshold', 'winfo-weapons')


def synthetic(name: str, b: RC.Build, fills=FILLS, profiles=PROFILES
              ) -> List[Dict[str, Any]]:
    out = []
    for c in synthetic_cases(name):
        out += evaluate(c, spec_of(c.key), b, fills, profiles, 'synthetic',
                        c.key, '%s: %s' % (name, path_of(
                            c.key, GR.Upstream(c), c)))
    for r in out:
        r['group'] = name
    return out


# ---------------------------------------------------------------------------
# The jobs
# ---------------------------------------------------------------------------

_BUILDS: Dict[str, RC.Build] = {}


def _build(obj: str) -> RC.Build:
    if obj not in _BUILDS:
        _BUILDS[obj] = load(Path(obj))
    return _BUILDS[obj]


def _job(job) -> List[Dict[str, Any]]:
    kind, path, key, obj, fills, profiles = job
    use_cases(MYCASES)
    try:
        b = _build(obj)
        if kind == 'synthetic':
            return synthetic(path, b, fills, profiles)
        case = GC.load_case(Path(path))
        return evaluate(case, spec_of(key), b, fills, profiles, 'captured',
                        key)
    except Exception as error:              # reported, never hidden
        return [{'ok': False, 'kind': kind, 'entry': key,
                 'case': Path(path).name if kind != 'synthetic' else path,
                 'error': '%s: %s' % (type(error).__name__, error)}]


def plan(obj: Path = OUT, fills=FILLS, profiles=PROFILES, sample: int = 1,
         entries: Optional[Sequence[str]] = None,
         synthetic_groups=SYNTHETIC) -> Tuple[List[Tuple], Dict[str, Any]]:
    """The checkpoint's jobs (every captured case, every sample-th; the
    synthetic groups) and the survey's eligibility of each entry."""
    o = str(obj)
    jobs: List[Tuple] = []
    elig: Dict[str, Any] = {}
    for run, key, n in CAPTURES:
        if entries and key not in entries:
            continue
        paths = case_paths(run, key)
        reached = MSP.reached_of(run, key)
        hits = MSP.survey_hits(run, key)
        e = elig.setdefault(key, {})
        r = e[run] = {'survey_calls': len(hits), 'captured': len(paths),
                      'survey_eligible': 0, 'survey_waiting': {}}
        for p in paths:
            h = int(p.name[1:9])
            wait = [t for t in reached.get(h, [])
                    if GL.owner_of(t) not in ('core', PART) and
                    GL.owner_of(t) not in GL.built_set(extra=[PART])]
            if wait:
                for t in wait:
                    r['survey_waiting'][t] = r['survey_waiting'].get(t, 0) + 1
            else:
                r['survey_eligible'] += 1
        for p in paths[::sample]:
            jobs.append(('case', str(p), key, o, tuple(fills),
                         tuple(profiles)))
    for name in synthetic_groups:
        jobs.append(('synthetic', name, DAMAGE, o, tuple(fills),
                     tuple(profiles)))
    return jobs, elig


def job_key(j: Tuple) -> str:
    kind, path, key, obj, fills, profiles = j
    return json.dumps([kind, Path(path).parent.parent.name + '/' +
                       Path(path).name if kind != 'synthetic' else path,
                       key, list(fills), list(profiles)])


def run_jobs(jobs: Sequence[Tuple], workers: int = 2, say=None,
             journal: Optional[Path] = None) -> List[Dict[str, Any]]:
    """The jobs' results; with a journal (JSON lines) a job already there
    is not run again (an interrupted checkpoint resumes)."""
    out: List[Dict[str, Any]] = []
    done: Dict[str, List[Dict[str, Any]]] = {}
    if journal is not None and journal.exists():
        for line in journal.read_text().splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            done[d['job']] = d['results']
    todo = []
    for j in jobs:
        k = job_key(j)
        if k in done:
            out += done[k]
        else:
            todo.append(j)

    def keep(j, got):
        if journal is not None:
            with open(str(journal), 'a') as handle:
                handle.write(json.dumps({'job': job_key(j), 'results': got},
                                        default=str) + '\n')
    if workers <= 1:
        for j in todo:
            got = _job(j)
            keep(j, got)
            out += got
        return out
    n = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for j, got in zip(todo, pool.map(_job, todo, chunksize=1)):
            keep(j, got)
            out += got
            n += 1
            if say and n % 50 == 0:
                say('%d of %d jobs' % (n, len(todo)))
    return out


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Per entry: the cases and runs by kind, the failures, the paths, the
    actions waited for, the call's clock and CPU cycles (median and worst
    a profile), the lowest S, the stray writes. killMobj's are
    P_DamageMobj's runs that kill (its path 'dies')."""
    out: Dict[str, Any] = {}

    def entry_of(key):
        return out.setdefault(key, {
            'cases': set(), 'runs': 0, 'failures': 0, 'paths': {},
            'kinds': {}, 'waiting': {}, 'clock': {}, 'cpu_cycles': {},
            'lowest_s': None, 'strays': 0, 'first_failures': [],
            'fc_loads': []})
    for r in results:
        keys = [r.get('entry') or '?']
        if keys[0] == DAMAGE and 'dies' in (r.get('path') or '') and \
                r.get('kind') != 'stop':
            keys.append(KILL)
        for key in keys:
            e = entry_of(key)
            e['cases'].add((r.get('kind'), r.get('case')))
            e['runs'] += 1
            e['kinds'][r.get('kind')] = e['kinds'].get(r.get('kind'), 0) + 1
            p = r.get('path') or ''
            e['paths'][p] = e['paths'].get(p, 0) + 1
            if r.get('waiting'):
                e['waiting'][r['waiting']] = e['waiting'].get(
                    r['waiting'], 0) + 1
            if not r.get('ok'):
                e['failures'] += 1
                if len(e['first_failures']) < 5:
                    e['first_failures'].append({k: r.get(k) for k in (
                        'case', 'kind', 'path', 'fill', 'profile', 'ended',
                        'stop', 'error', 'diff', 'stray_first') if r.get(k)})
            if r.get('fc_loads') is not None:
                e['fc_loads'].append(r['fc_loads'])
            prof = r.get('profile') or 'none'
            if r.get('kind') != 'stop':
                e['clock'].setdefault(prof, []).append(r.get('clock'))
                e['cpu_cycles'].setdefault(prof, []).append(
                    r.get('cpu_cycles'))
            s = r.get('lowest_s')
            if s is not None:
                e['lowest_s'] = s if e['lowest_s'] is None else \
                    min(e['lowest_s'], s)
            e['strays'] += r.get('strays') or 0
    for e in out.values():
        cases = e.pop('cases')
        e['cases'] = len(cases)
        e['cases_by_kind'] = {}
        for k, _ in cases:
            e['cases_by_kind'][k] = e['cases_by_kind'].get(k, 0) + 1
        e['clock'] = {k: MSP._stats(v) for k, v in e['clock'].items()}
        e['cpu_cycles'] = {k: MSP._stats(v)
                           for k, v in e['cpu_cycles'].items()}
        e['fc_loads'] = MSP._stats(e['fc_loads'])
    return out


def check(jobs: int = 2, sample: int = 1, entries=None,
          synthetic_groups=SYNTHETIC, fills=FILLS, profiles=PROFILES,
          rebuild: bool = True, say=print) -> Dict[str, Any]:
    """The checkpoint on the part's image: report.json's checkpoint
    half."""
    if rebuild:
        build()
    b = load()
    js, elig = plan(OUT, fills, profiles, sample, entries, synthetic_groups)
    say('%d jobs' % len(js))
    start = time.time()
    journal = None
    if sample == 1 and not entries:
        import hashlib
        h = hashlib.sha256()
        for p in sorted(OUT.glob(NAME + '.*')):
            if p.suffix not in ('.lbl', '.map'):
                h.update(p.name.encode() + p.read_bytes())
        journal = OUT / ('journal-%s.jsonl' % h.hexdigest()[:16])
        for old in OUT.glob('journal-*.jsonl'):
            if old != journal:
                old.unlink()
    res = run_jobs(js, jobs, say, journal)
    rep = {'entries': summarize(res), 'eligibility': elig,
           'runs': len(res),
           'failures': sum(1 for r in res if not r.get('ok')),
           'strays': sum(r.get('strays') or 0 for r in res),
           'seconds': round(time.time() - start),
           'fills': ['%02x' % f for f in fills], 'profiles': list(profiles),
           'sizes': sizes(b), 'sample': sample}
    return rep


# ---------------------------------------------------------------------------
# The random check of the thrust (GAME.md 2.4 "Arithmetic", risk 6):
# upstream's thrust (p_inter65.s, with its R_PointToAngle3, _Div32,
# FixedMulAngle and the turn-over's P_Random) by mathref batch against the
# native thrust (dtest.s dm_t_bulk) on the same inputs
# ---------------------------------------------------------------------------

MATHREF = BUILD / 'native' / 'math' / 'mathref'
BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
IN_SIZE, OUT_SIZE = 38, 17
EDGE_DAMAGE = (0, 1, -1, 2, 3, 39, 40, 41, 100, 255, 1000, 5461, 5462,
               10000, 32767, -32768, -40)
NUMTYPES = 50
_MASS: Dict[int, int] = {}


def mass_low(mtype: int) -> int:
    """The low word of mobjinfo[mtype].mass (the thrust's divisor)."""
    if not _MASS:
        base = _scan_bases()['monster']
        for k in range(NUMTYPES):
            _MASS[k] = info_word(base.entry, k, 'UO_MI_MASS')
    return _MASS[mtype]


def thrust_types() -> List[int]:
    """The types whose mass's low word is not 0. Type 49's is 0 (it is
    not shootable, so P_DamageMobj never reaches its thrust): a division
    by zero, the port's own result (NATIVE.md 15.1 row 5), which
    div0_check() checks apart."""
    return [k for k in range(NUMTYPES) if mass_low(k)]


def _s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def thrust_inputs(n: int, seed: int = 1, types: Optional[Sequence[int]] =
                  None) -> List[Dict[str, int]]:
    """n inputs: the damage's edges with every type first, then random
    damages (any, small, below 40), positions far apart, close, on an
    axis, on a diagonal, at the same point and at the 32-bit extremes,
    heights around the turn-over's 64 units, healths around the damage."""
    rnd = random.Random(seed)
    types = thrust_types() if types is None else list(types)
    out = []
    while len(out) < n:
        k = len(out)
        ne = len(EDGE_DAMAGE) * len(types)
        if k < ne:
            d, mtype = EDGE_DAMAGE[k % len(EDGE_DAMAGE)], \
                types[(k // len(EDGE_DAMAGE)) % len(types)]
        else:
            d = rnd.choice((rnd.randint(-32768, 32767), rnd.randint(0, 200),
                            rnd.randint(1, 40)))
            mtype = rnd.choice(types)
        tx, ty = rnd.randint(-1 << 31, (1 << 31) - 1), \
            rnd.randint(-1 << 31, (1 << 31) - 1)
        style = k % 6
        if style == 0:
            ix, iy = rnd.randint(-1 << 31, (1 << 31) - 1), \
                rnd.randint(-1 << 31, (1 << 31) - 1)
        elif style == 1:
            ix, iy = tx + rnd.randint(-1 << 22, 1 << 22), \
                ty + rnd.randint(-1 << 22, 1 << 22)
        elif style == 2:
            r = rnd.randint(-1 << 24, 1 << 24)
            ix, iy = (tx + r, ty) if k % 12 < 6 else (tx, ty + r)
        elif style == 3:
            r = rnd.randint(-1 << 24, 1 << 24)
            ix, iy = tx + r, ty + rnd.choice((r, -r))
        elif style == 4:
            ix, iy = tx, ty
        else:
            tx, ty = rnd.choice((-1 << 31, (1 << 31) - 1, 0)), \
                rnd.choice((-1 << 31, (1 << 31) - 1, 0))
            ix, iy = rnd.choice((-1 << 31, (1 << 31) - 1, 0, 1, -1)), \
                rnd.choice((-1 << 31, (1 << 31) - 1, 0, 1, -1))
        tz = rnd.randint(-1 << 24, 1 << 24)
        dz = rnd.choice((64 << 16, (64 << 16) + 1, (64 << 16) - 1,
                         rnd.randint(-1 << 31, (1 << 31) - 1),
                         rnd.randint(0, 200 << 16)))
        iz = tz - dz
        h = rnd.choice((d - 1, d, d + 1, rnd.randint(-100, 300), 0, -1,
                        32767, -32768))
        h = max(-32768, min(32767, h))
        mom = [rnd.choice((0, rnd.randint(-1 << 31, (1 << 31) - 1),
                           rnd.randint(-1 << 20, 1 << 20)))
               for _ in range(2)]
        out.append({'d': d, 'type': mtype, 'prnd': rnd.randrange(256),
                    't': (tx, ty, tz), 'h': h, 'mom': mom,
                    'i': (ix, iy, iz)})
    return out[:n]


def _xyz(v) -> bytes:
    return b''.join(struct.pack('<I', x & 0xFFFFFFFF) for x in v)


def native_record(x: Dict[str, int]) -> bytes:
    return struct.pack('<HBB', x['d'] & 0xFFFF, x['type'], x['prnd']) + \
        _xyz(x['t']) + struct.pack('<H', x['h'] & 0xFFFF) + \
        _xyz(x['mom']) + _xyz(x['i'])


def upstream_record(x: Dict[str, int]) -> bytes:
    info = (uaddr('info65.s:mobjinfo') + 64 * x['type']) & 0xFFFF
    return struct.pack('<HHH', x['d'] & 0xFFFF, info, x['prnd']) + \
        _xyz(x['t']) + struct.pack('<H', x['h'] & 0xFFFF) + \
        _xyz(x['mom']) + _xyz(x['i'])


def native_bulk(b, records: bytes) -> List[bytes]:
    per = min(BULK_ROOM // IN_SIZE, BULK_ROOM // OUT_SIZE)
    n = len(records) // IN_SIZE
    out: List[bytes] = []
    for start in range(0, n, per):
        k = min(per, n - start)
        img = G.Image(b, 0xA5, store=True)
        img.aux(BULK_IN, 0x0200, records[start * IN_SIZE:(start + k) *
                                         IN_SIZE])
        work = Path(tempfile.mkdtemp(prefix='tmp-damage-bulk-',
                                     dir=str(BUILD)))
        try:
            r = G.run(img, work, GL.MODES['ROUTINE'], 'dm_t_bulk',
                      regs=(0, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                p = work / 'crash.img'
                raise PartError('dm_t_bulk ended %s %s' % (
                    r.ended(), G.stop_codes(G.load_snapshot(p))
                    if p.exists() else ''))
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + k * OUT_SIZE])
        out += [data[i:i + OUT_SIZE] for i in range(0, len(data), OUT_SIZE)]
    return out


def mathref_thrust(records: bytes) -> List[bytes]:
    """upstream's thrust on each record (mathref batch), from a captured
    P_DamageMobj call's memory with DM_TARGET, DM_INFL its target and
    inflictor, no DM_SOURCE, the target not MF_NOCLIP."""
    base = _scan_bases()['monster']
    pk = Poker(base)
    mem = base.entry.copy()
    mem.header = base.entry.header
    mem.write(uaddr('p_inter65.s:DM_TARGET'), _w32(pk.t))
    mem.write(uaddr('p_inter65.s:DM_INFL'), _w32(pk.i))
    mem.write(uaddr('p_inter65.s:DM_SOURCE'), _w32(0))
    fl = int.from_bytes(mem.read(pk.t + uconst('UO_MO_FLAGS'), 4), 'little')
    mem.write(pk.t + uconst('UO_MO_FLAGS'), _w32(fl & ~uconst('UC_MF_NOCLIP')))
    t, i = pk.t, pk.i
    mx = uconst('UO_MO_X')
    ins = ['%06X 2' % uaddr('p_inter65.s:DM_DAMAGE'),
           '%06X 2' % uaddr('p_inter65.s:DM_INFO'),
           '%06X 2' % uaddr('m_random65.s:prndindex'),
           '%06X 12' % (t + mx), '%06X 2' % (t + uconst('UO_MO_HEALTH')),
           '%06X 8' % (t + uconst('UO_MO_MOMX')), '%06X 12' % (i + mx)]
    outs = ['%06X 8' % (t + uconst('UO_MO_MOMX')),
            '%06X 2' % uaddr('m_random65.s:prndindex'),
            '%06X 4' % uaddr('p_inter65.s:DM_THRUST'),
            '%06X 4' % uaddr('p_inter65.s:DM_ANG')]
    work = Path(tempfile.mkdtemp(prefix='tmp-damage-ref-', dir=str(BUILD)))
    try:
        (work / 'base.ram').write_bytes(GC._ram_bytes(mem))
        r = base.regs_in
        hdr = bytes.fromhex(base.header['image_header'])
        (work / 'entry').write_text(
            'pc %06X\ndbr %02X\nd %04X\np %02X\ne 0\ns %04X\na 0\nx 0\n'
            'y 0\nret 2\nstack 00 00\nswitches %s\n' % (
                uaddr('p_inter65.s:thrust'), r['dbr'], r['d'],
                r['p'] & ~0x30 & 0xFF, r['s'],
                ' '.join('%02X' % v for v in hdr[26:30])))
        spec = ['routine thrust %06X' % uaddr('p_inter65.s:thrust')] + \
            ['in %s' % x for x in ins] + ['out %s' % x for x in outs]
        (work / 'spec').write_text('\n'.join(spec) + '\n')
        (work / 'cases').write_bytes(records)
        res = bounded.run([str(MATHREF), 'batch', str(work / 'base.ram'),
                           str(work / 'entry'), str(work / 'spec'),
                           'thrust', str(work / 'cases'), str(work / 'out')],
                          timeout=1200, max_bytes=1 << 28,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)
        if res.returncode:
            raise PartError('mathref: %s' % res.stdout[-1000:])
        data = (work / 'out').read_bytes()
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    step = 18 + 4
    return [data[k:k + 18] for k in range(0, len(data), step)]


def random_check(n: int = 100_000, seed: int = 1, b=None,
                 inputs: Optional[List[Dict[str, int]]] = None
                 ) -> Dict[str, Any]:
    """The thrust on n inputs, upstream against native: the target's
    momentum, P_Random's index, the thrust and its angle."""
    use_cases()
    b = b or load()
    xs = inputs or thrust_inputs(n, seed)
    ups = mathref_thrust(b''.join(upstream_record(x) for x in xs))
    nat = native_bulk(b, b''.join(native_record(x) for x in xs))
    bad = []
    turned = 0
    for x, u, m in zip(xs, ups, nat):
        want = u[0:8] + u[8:9] + u[10:14] + u[14:18]
        if (u[8] - x['prnd']) & 0xFF:
            turned += 1
        if want != m:
            bad.append({'input': x, 'upstream': want.hex(), 'native': m.hex()})
    return {'seed': seed, 'inputs': len(xs), 'compared': min(len(ups),
                                                             len(nat)),
            'different': len(bad) + abs(len(ups) - len(nat)),
            'turn_over_random': turned, 'first': bad[:5],
            'division_by_zero': div0_check(b, seed)}


def div0_check(b, seed: int = 1, n: int = 500) -> Dict[str, Any]:
    """The thrust of the types whose mass's low word is 0 (type 49): the
    native thrust is the port's quotient of a division by zero
    (src/native/MATH.md: $7FFFFFFF for a dividend >= 0, $80000000
    below), never compared with upstream's vendor divide."""
    types = [k for k in range(NUMTYPES) if not mass_low(k)]
    if not types:
        return {'types': [], 'inputs': 0, 'different': 0}
    xs = thrust_inputs(n, seed + 1, types)
    nat = native_bulk(b, b''.join(native_record(x) for x in xs))
    bad = 0
    for x, m in zip(xs, nat):
        d = x['d'] & 0xFFFF
        hi = (12 * d + ((d >> 1) | (0x8000 if d & 0x8000 else 0))) & 0xFFFF
        want = 0x80000000 if hi & 0x8000 else 0x7FFFFFFF
        thr = int.from_bytes(m[9:13], 'little')
        if x['h'] < x['d'] < 40 and (x['t'][2] - x['i'][2]) > 64 << 16:
            want = None             # (turned over: x 4, if P_Random says)
        if want is not None and thr != want:
            bad += 1
    return {'types': types, 'inputs': len(xs), 'different': bad}


# ---------------------------------------------------------------------------
# The planted bugs (GAME.md 2.4's row): each made in a scratch copy of the
# part's sources (build()'s bugs), its image built in a temporary
# directory, and run on the check that must catch it
# ---------------------------------------------------------------------------

DI = 'game/%s/dinter.s' % PART
PLANTS: Dict[str, Dict[str, Any]] = {
    # the thrust divided before the multiply: damage / mass first, then
    # x 819200 (the captured hits with an inflictor; the random check)
    'thrust-divided-first': {'check': 'captured', 'bugs': [
        (DI, """        lda DM_DMG              ; 12 * damage (16 bits) in M_A+2""",
         """        lda DM_DMG              ; (planted: damage / mass first)
        sta M_A
        lda DM_DMG+1
        sta M_A+1
        and #$80
        beq :+
        lda #$FF
:       sta M_A+2
        sta M_A+3
        jsr sdiv32
        lda M_R
        sta DM_T
        lda M_R+1
        sta DM_T+1
        lda #<819200
        sta M_A
        lda #>819200
        sta M_A+1
        lda #^819200
        sta M_A+2
        stz M_A+3
        lda DM_T
        sta M_B
        lda DM_T+1
        sta M_B+1
        and #$80
        beq :+
        lda #$FF
:       sta M_B+2
        sta M_B+3
        jsr mul32
        ldx #3
:       lda M_R,x
        sta DM_THR,x
        dex
        bpl :-
        jmp @over
        lda DM_DMG              ; 12 * damage (16 bits) in M_A+2"""),
        (DI, """        ; turned over: health < damage && damage < 40 && z - inflictor's z""",
         """@over:  ; turned over: health < damage && damage < 40 && z - inflictor's z"""),
        (DI, """        .import sdiv32, sdiv16, fixmulang, udiv32, pta3, finesine, finecosine""",
         """        .import sdiv32, sdiv16, fixmulang, udiv32, pta3, finesine, finecosine, mul32""")]},
    # the pain chance's P_Random taken before the thrust's (the index): a
    # hit turned over (the two numbers swapped), god mode (upstream takes
    # none) and a death (upstream takes the tics' only)
    'pain-before-thrust': {'check': ('turnover', 'god', 'drop-possessed'),
                           'bugs': [
        (DI, """@thr:   FCALL thrust""",
         """@thr:   jsr g_random            ; (planted: the pain chance's first)
        sta DM_K
        FCALL thrust"""),
        (DI, """@pain:  jsr g_random            ; the pain chance (its low byte, unsigned:""",
         """@pain:  lda DM_K                ; (planted: taken before the thrust)""")]},
    # the extreme death at health <= -spawnhealth (the synthetic boundary)
    'xdeath-at-equal': {'check': ('xdeath-equal',), 'bugs': [
        (DI, """        ldy #LN_A + MA_HEALTH
        sec
        lda (GC_MP),y
        sbc DM_T""", """        ldy #LN_A + MA_HEALTH
        clc                     ; (planted: <= instead of <)
        lda (GC_MP),y
        sbc DM_T""")]},
    # the drop spawned before the death state (the spawn's P_Random before
    # the tics')
    'drop-before-death': {'check': ('drop-possessed', 'drop-shotguy'),
                          'bugs': [
        (DI, """@state: lda DM_TYPE             ; health < -spawnhealth and an extreme""",
         """@state: jsr kdrop               ; (planted: the drop first)
        lda DM_TYPE             ; health < -spawnhealth and an extreme"""),
        (DI, """        lda DM_TGT              ; the item to drop""",
         """        rts
kdrop:  lda DM_TGT              ; the item to drop""")]},
}


def plant_jobs(check_name, obj: Path, limit: int = 24) -> List[Tuple]:
    """The jobs of a plant's check: one fill, no cost model."""
    fills, profiles = (0xA5,), (None,)
    if isinstance(check_name, tuple):
        return [('synthetic', n, DAMAGE, str(obj), fills, profiles)
                for n in check_name]
    js, _ = plan(obj, fills, profiles, entries=[DAMAGE],
                 synthetic_groups=())
    return js[:limit]


def run_plant(name: str, say=None) -> Dict[str, Any]:
    """The plant's image in a temporary directory (deleted), its check's
    jobs until one fails: caught when one does."""
    p = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-damage-plant-', dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', p['bugs'])
        js = plant_jobs(p['check'], obj)
        ran = failed = 0
        first = None
        for j in js:
            for r in _job(j):
                ran += 1
                if not r.get('ok'):
                    failed += 1
                    first = first or {k: r.get(k) for k in (
                        'case', 'path', 'ended', 'stop', 'diff', 'error')
                        if r.get(k)}
            if failed:
                break
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        _BUILDS.clear()
        MSP._GROUPS.clear()
    out = {'check': p['check'], 'runs': ran, 'failed': failed,
           'caught': failed > 0, 'first': first}
    if say:
        say('%-24s %s' % (name, ('caught (%s): %s' % (p['check'], str(
            first)[:300])) if failed else 'NOT CAUGHT (%d runs)' % ran))
    return out


def run_plant_random(n: int = 2000) -> Dict[str, Any]:
    """The divided-first plant on the random check too."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-damage-plant-', dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', PLANTS['thrust-divided-first']['bugs'])
        rep = random_check(n, 1, G.load_build(obj, NAME))
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return {'inputs': rep['inputs'], 'different': rep['different'],
            'caught': rep['different'] > 0}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def write_report(rep: Dict[str, Any], **parts: Any) -> Path:
    """build/native/game/damage/report.json (GAME.md 2.5 item 2): per
    entry the cases and runs, failures, the call's clock and cycles on
    each profile, the lowest S, the stray writes; the sizes against the
    budget; the eligibility; the random check; the planted bugs; the
    part's build/ use. Halves not given are kept from the old report."""
    old = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    out = dict(old)
    out.update(rep)
    out.update({k: v for k, v in parts.items() if v is not None})
    out['format'] = 'game-part-report 1'
    out['part'] = PART
    out['wave'] = 2
    out['build_kb'] = MSP.du_kb(OUT)
    out['notes'] = [
        'clock: the call\'s time from call_entry to its return under the '
        'profile (a2vm --cost-timed: fabric clocks); cpu_cycles: the '
        'W65C02S\'s cycles of the same span; every number is routine mode '
        'with the slots empty at the call',
        'lowest_s: the lowest S of the run (the driver starts at $EF)',
        'stop: a call that reaches an unbuilt action stops at its DCALL '
        '(the stop check); "action removed": its variant with that '
        'state\'s action removed on both sides, compared whole',
        'killMobj: P_DamageMobj\'s runs that kill (upstream enters it by '
        'brl: no capture counts it)',
        'sizes: own_bytes is the part without the math stand-in (request '
        'R1) and with the weaponinfo table (108 B, in the core)']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1, default=str) + '\n')
    return REPORT


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--synthetic', action='store_true',
                        help='the synthetic groups alone')
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--n', type=int, default=100_000)
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--entries', default='')
    args = parser.parse_args(argv)
    status = 0
    if args.build:
        b = load(build())
        print(json.dumps(sizes(b), indent=1))
    if args.capture:
        capture(args.jobs)
    if args.synthetic:
        build()
        res = run_jobs([('synthetic', n, DAMAGE, str(OUT), FILLS, PROFILES)
                        for n in SYNTHETIC], args.jobs)
        for r in res:
            print('%-6s %-14s %s %s' % ('ok' if r.get('ok') else 'FAIL',
                                        r.get('kind'), r.get('path'),
                                        '' if r.get('ok') else
                                        (r.get('diff') or r.get('error'))))
        status |= 0 if all(r.get('ok') for r in res) else 1
    if args.check:
        rep = check(args.jobs, args.sample, [e for e in args.entries.split(
            ',') if e] or None)
        write_report(rep)
        for k, e in sorted(rep['entries'].items()):
            print('%-28s %4d cases %5d runs %3d failed  cycles f121 %s '
                  'fastpath %s  S %s  waiting %s' % (
                      k, e['cases'], e['runs'], e['failures'],
                      e['cpu_cycles'].get('f121'),
                      e['cpu_cycles'].get('fastpath'), e['lowest_s'],
                      e['waiting']))
        print('runs %d, failures %d, stray writes %d, %d s' % (
            rep['runs'], rep['failures'], rep['strays'], rep['seconds']))
        status |= 1 if rep['failures'] or rep['strays'] else 0
    if args.random:
        if not (args.build or args.check or args.synthetic):
            build()
        r = random_check(args.n)
        write_report({}, random=r)
        print('thrust: %d inputs, %d different, %d turned over (P_Random)'
              % (r['inputs'], r['different'], r['turn_over_random']))
        for f in r['first']:
            print('  ', json.dumps(f))
        status |= 1 if r['different'] else 0
    if args.plants:
        pl = {n: run_plant(n, print) for n in PLANTS}
        pr = run_plant_random()
        print('thrust-divided-first on the random check: %s' % pr)
        write_report({}, plants=pl, plant_random=pr)
        status |= 0 if all(p['caught'] for p in pl.values()) and \
            pr['caught'] else 1
    return status


if __name__ == '__main__':
    sys.exit(main())
