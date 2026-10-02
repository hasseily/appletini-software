#!/usr/bin/env python3
"""Part missile's checkpoint (milestone 10, docs/GAME.md 2.4 row missile,
3.4, 3.5; docs/game-parts/missile.md): routine mode on the part's entries
(P_SpawnMissile, checkMissile), halfMom's random check, and the planted
bugs.

Usage:  python3 tools/native/gparts/missile.py --capture [--jobs 2]
        python3 tools/native/gparts/missile.py --check [--jobs 2]
                [--sample K] [--keys KEY,...]
        python3 tools/native/gparts/missile.py --random [--count N]
        python3 tools/native/gparts/missile.py --plants [--keys NAME,...]
        python3 tools/native/gparts/missile.py --eligible
        python3 tools/native/gparts/missile.py --report

Everything it writes is under build/native/game/missile/ (the part's own
directory): the cases (cases/RUN/ROUTINE/hNNNNNNNN.case.z and each run's
base.ram.z: tools/native/gamecap.py with its case directory pointed here),
the candidates' paths (paths.json), report.json. The shared outputs are
read only.

The checks are lean (the owner's request of 2026-10-02): at most CHOSEN
(40) calls an entry, chosen to take as many paths as the candidates take
(a greedy cover of the paths, then spread evenly), from the $A5 machine
only, under f121 and fastpath.

--capture: every call of both entries in demo3, DEMO1 and DEMO2 (76 each:
the imps' fireballs; newgame and the tour fire none). Each candidate's
path comes from the reference alone (path_of): the type, the see sound, a
shadow or visible destination, the distance clamped at 1, momz's sign and
whether its divide is exact (a negative inexact one is where the
rounding shows), the move made or refused (the explosion), a damage done.

The synthetic calls (P_SpawnMissile, ref816 --call of upstream's routine on
a captured call's memory with pokes, gamecap.call_case):
  * wall: the source moved onto the middle of the one-sided line nearest
    it, so that the missile is spawned inside the wall: the move is
    refused and the missile explodes;
  * damage: the source 20 units east of the destination, 13 units and
    1/65536 above it: the half step puts the missile into the destination,
    PIT_CheckThing calls P_DamageMobj and the missile explodes (review 1's
    chain: P_SpawnMissile in slot 1, checkMissile in slot 2, P_TryMove in
    slot 1, checkThing in slot 1, P_DamageMobj paged into checkMissile's
    slot 2, each slot restored on the way back: the integrator's placement,
    shared/placement.json, which the part's image takes); momz negative and
    inexact;
  * close: the source 6 units north of the destination: the distance
    clamped at 1;
  * shadow: the destination made MF_SHADOW: the angle's P_Random noise.

--check: the chosen calls on the part's image (make -f game.mk part
P=missile MS_TEST=1) with part checkpos's run machinery (checkpos.Prep,
check_writes; secfind's and mobjstate's checks): the canonical state after
the call equal to ref816's (gcanon's routine mode, R1-R7), every declared
output of src/native/game/missile/args.json equal (P_SpawnMissile's
missile in A:X), no stray write. A call that reaches a routine of a part
not in the image stops at its FCALL or DCALL (GS_UNBUILT, GS_UNBUILTD): it
is "waiting", never counted equal.

--random: halfMom (GAME.md 2.4 "Arithmetic") on --count inputs (100,000;
0, +-1 and the extremes among them) through mathref batch of upstream's
halfMom (on a captured checkMissile call's machine) against the native
one (mstest.s ms_bulk), and against the model x + (mom >> 1).

--plants: each planted bug built from a scratch copy of the part's
sources in a temporary directory (deleted), run on its check (the chosen
calls, $A5, f121), which must fail.
"""

import argparse
import json
import random
import shutil
import struct
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

import checkpos as CP  # noqa: E402  (wave 3's run machinery)
import secfind as SF  # noqa: E402
from native import gamecap as GC, glayout as GL, grun as G  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'missile'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
PATHS_FILE = OUT / 'paths.json'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
PART_SRC = SRC / 'game' / PART
SOURCES = ('part.mk', 'missile.s', 'missile.inc', 'mstest.s')
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory

SPAWN = 'p_spawn65.s:P_SpawnMissile'
CHECK = 'p_spawn65.s:checkMissile'
HALFMOM = 'p_spawn65.s:halfMom'
ENTRIES = (SPAWN, CHECK)
RUNS = ('demo3', 'demo1', 'demo2')
CHOSEN = 40                     # the lean checks: calls an entry
FILLS = (0xA5,)                 # the lean checks: one machine
PROFILES = SF.PROFILES
VARIABLES = ('MS_TEST=1',)      # the part's image with ms_bulk
SYNTHETIC = ('wall', 'damage', 'close', 'shadow')


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC) -> Path:
    """The part's test image (make -f game.mk part P=missile MS_TEST=1);
    its directory."""
    variables = ['P=%s' % PART] + list(VARIABLES)
    if game is not None:
        variables.append('GAME=%s' % game)
    G.make('part', variables, source)
    return (game or GL.GAME) / PART


def args() -> Dict[str, Dict[str, Any]]:
    d = json.loads(ARGS.read_text())
    if d.get('format') != CP.GR.ARGS_FORMAT:
        raise PartError('%s is not %s' % (ARGS, CP.GR.ARGS_FORMAT))
    return d['entries']


# ---------------------------------------------------------------------------
# The calls: eligibility (GAME.md 3.5 step 6), candidates, captures
# ---------------------------------------------------------------------------

def eligible_calls(key: str, runs: Sequence[str] = GC.RUNS
                   ) -> Tuple[List[Tuple[str, int, int]], Dict[str, int]]:
    """The eligible calls of an entry over the survey's runs, (run, hit,
    tic), and the waiting ones by the target they wait for."""
    ok_parts = set(GL.built_set(extra=[PART]))
    out: List[Tuple[str, int, int]] = []
    waiting: Dict[str, int] = {}
    for run in runs:
        sv = GC.survey_of(run)
        r = sv['routines'].get(key) if sv else None
        if not r:
            continue
        targets = sv['targets']
        reached = r['reached'] if isinstance(r['reached'], dict) else {}
        for hit in range(1, r['calls'] + 1):
            miss = [targets[i] for i in reached.get(str(hit), [])
                    if GL.owner_of(targets[i]) != 'core' and
                    GL.owner_of(targets[i]) not in ok_parts]
            for m in miss:
                waiting[m] = waiting.get(m, 0) + 1
            if not miss:
                out.append((run, hit, r['tic'][hit - 1]))
    return out, waiting


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, key) / ('h%08d.case.z' % hit)


def capture(batch: int = CP.BATCH) -> int:
    """Every eligible call of both entries in RUNS."""
    made = 0
    for key in ENTRIES:
        for run in RUNS:
            calls = eligible_calls(key, (run,))[0]
            todo = [h for _, h, _ in calls
                    if not case_path(run, key, h).exists()]
            if not todo:
                continue
            tics = GC.survey_of(run)['routines'][key]['tic']
            start = time.time()
            got = GC.capture(run, key, todo, tics, batch=batch, say=say)
            made += len(got)
            say('%s %s: %d cases (%.0f s)' % (run, key, len(got),
                                              time.time() - start))
    return made


def captured(key: str) -> List[Tuple[str, int, Path]]:
    out = []
    for run in RUNS:
        for _, hit, _ in eligible_calls(key, (run,))[0]:
            p = case_path(run, key, hit)
            if p.exists():
                out.append((run, hit, p))
    return out


# ---------------------------------------------------------------------------
# A call's path, from the reference's memory alone (the coverage, GAME.md
# 3.5 step 2)
# ---------------------------------------------------------------------------

def sym(name: str) -> int:
    return CP.sym(name)


def _s32(b: bytes) -> int:
    return int.from_bytes(b, 'little', signed=True)


def _ptr(m, a: int) -> int:
    return int.from_bytes(m.read(a, 3), 'little')


def _tdiv(a: int, b: int) -> int:
    """C's division (truncation toward 0)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def aproxdist(dx: int, dy: int) -> int:
    """P_AproxDistance as C writes it (32-bit wrap)."""
    def w(v: int) -> int:
        v &= 0xFFFFFFFF
        return v - (1 << 32) if v & 0x80000000 else v
    dx, dy = abs(w(dx)), abs(w(dy))
    return w(dx + dy - (min(dx, dy) >> 1))


def dp_of(case: GC.Case) -> int:
    t = CP.table()
    return (case.regs_in['d'] + t.address('_Dp') - t.direct_page) & 0xFFFF


def mo_field(m, mo: int, name: str, n: int = 4) -> int:
    return _s32(m.read(mo + SF.uconst()['UO_MO_' + name], n))


def info_of(m, mtype: int, name: str, n: int = 4) -> int:
    return _s32(m.read(sym('mobjinfo') + 64 * mtype +
                       SF.uconst()['UO_MI_' + name], n))


def player_mo(m) -> int:
    return _ptr(m, sym('_g_player') + SF.uconst()['UO_PL_MO'])


def path_of(case: GC.Case) -> List[str]:
    """The paths a call took."""
    uc = SF.uconst()
    e, a = case.entry, case.after
    out: List[str] = []
    if case.key == CHECK:
        th = _ptr(e, sym('p_spawn65.s:SP_TH'))
    else:
        dp = dp_of(case)
        src, dest = _ptr(e, dp), _ptr(e, dp + 4)
        th = _ptr(a, sym('p_spawn65.s:SP_TH'))
        mtype = mo_field(a, th, 'TYPE', 2) & 0xFF
        out.append('type-%d' % mtype)
        out.append('see-sound' if info_of(e, mtype, 'SEESOUND', 2)
                   else 'no-see-sound')
        flags = mo_field(e, dest, 'FLAGS') & 0xFFFFFFFF
        out.append('shadow' if flags & (uc['UC_MF_SHADOW_HI'] << 16)
                   else 'visible')
        speed = info_of(e, mtype, 'SPEED')
        d = aproxdist(mo_field(e, dest, 'X') - mo_field(e, src, 'X'),
                      mo_field(e, dest, 'Y') - mo_field(e, src, 'Y'))
        dist = _tdiv(d, speed)
        if dist < 1:
            out.append('dist-clamped')
            dist = 1
        dz = mo_field(e, dest, 'Z') - mo_field(e, src, 'Z')
        momz = _tdiv(dz, dist)          # (P_ExplodeMissile clears it)
        out.append('momz-zero' if momz == 0 else 'momz-pos' if momz > 0
                   else 'momz-neg')
        if abs(dz) % dist:
            out.append('momz-neg-inexact' if dz < 0 else 'momz-inexact')
    moms = [mo_field(a, th, n) for n in ('MOMX', 'MOMY', 'MOMZ')]
    exploded = not any(moms)
    out.append('exploded' if exploded else 'moved')
    if case.key == SPAWN and not exploded and moms[2] != momz:
        out.append('model-differs')     # (the model of momz is wrong)
    if case.key == CHECK and not mo_field(e, th, 'FLAGS') & (
            uc['UC_MF_MISSILE_HI'] << 16):
        out.append('not-a-missile')
    pmo = player_mo(e)
    if mo_field(e, pmo, 'HEALTH') != mo_field(a, pmo, 'HEALTH'):
        out.append('damage')
    return out


def _path_job(item: Tuple[str, str]) -> Tuple[str, str, List[str]]:
    key, path = item
    try:
        return key, path, path_of(GC.load_case(Path(path)))
    except Exception as error:      # reported, never hidden
        return key, path, ['error: %s: %s' % (type(error).__name__, error)]


def paths(jobs: int = 2) -> Dict[str, Dict[str, List[str]]]:
    """entry -> case path -> its paths (kept in paths.json)."""
    old = json.loads(PATHS_FILE.read_text()) if PATHS_FILE.exists() else {}
    got: Dict[str, Dict[str, List[str]]] = {k: dict(old.get(k, {}))
                                            for k in ENTRIES}
    todo = [(k, str(p)) for k in ENTRIES for _, _, p in captured(k)
            if str(p) not in got[k]]
    if todo:
        if jobs <= 1:
            res = list(map(_path_job, todo))
        else:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                res = list(pool.map(_path_job, todo))
        for k, p, v in res:
            got[k][p] = v
    if todo or not PATHS_FILE.exists():
        PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PATHS_FILE.write_text(json.dumps(got, indent=1, sort_keys=True) +
                              '\n')
    return got


def selection(key: str, ps: Optional[Dict[str, Dict[str, List[str]]]] = None,
              n: int = CHOSEN) -> List[str]:
    """CHOSEN cases of an entry: a greedy cover of the candidates' paths,
    then spread evenly over the rest (checkpos.selection)."""
    ps = ps if ps is not None else paths()
    return CP.selection(key, ps, n)


# ---------------------------------------------------------------------------
# The synthetic calls of P_SpawnMissile
# ---------------------------------------------------------------------------

def _wall_point(m, x: int, y: int) -> Tuple[int, int]:
    """The middle of the one-sided line nearest (x, y) (fixed point).
    Upstream's line holds its vertices inline, each an x and a y word of
    whole units (v1 at 0, v2 at 4); sidenum[1] is $FFFF for one side."""
    uc = SF.uconst()
    lines = _ptr(m, sym('_g_lines'))
    n = m.u16(sym('_g_numlines'))
    best = None

    def s16(a: int) -> int:
        return _s32(m.read(a, 2)) << 16
    for i in range(n):
        ln = lines + 36 * i                 # SIZEOF_LINE (offsets.inc)
        if m.u16(ln + uc['UO_LINE_SIDENUM'] + 2) != 0xFFFF:
            continue
        v1, v2 = ln + uc['UO_LINE_V1'], ln + uc['UO_LINE_V2']
        x1, y1, x2, y2 = s16(v1), s16(v1 + 2), s16(v2), s16(v2 + 2)
        if abs(x2 - x1) + abs(y2 - y1) < 32 << 16:   # room for the box
            continue
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        d = abs(mx - x) + abs(my - y)
        if best is None or d < best[0]:
            best = (d, mx, my)
    if best is None:
        raise PartError('no one-sided line')
    return best[1], best[2]


def synthetic_plan() -> List[Dict[str, Any]]:
    """The synthetic calls: each on the first captured P_SpawnMissile call
    of demo3 (and the shadow one also on DEMO1's)."""
    caps = captured(SPAWN)
    if not caps:
        return []
    first = {r: str(p) for r, _, p in reversed(caps)}
    plan = [{'kind': k, 'base': first['demo3'],
             'note': '%s demo3/%s' % (k, Path(first['demo3']).name)}
            for k in SYNTHETIC if 'demo3' in first]
    if 'demo1' in first:
        plan.append({'kind': 'shadow', 'base': first['demo1'],
                     'note': 'shadow demo1/%s' % Path(first['demo1']).name})
    return plan


def synthetic_case(rec: Dict[str, Any]) -> GC.Case:
    """A synthetic call: the base's entry memory with the pokes of its
    kind, upstream's P_SpawnMissile run alone on ref816."""
    uc = SF.uconst()
    base = GC.load_case(Path(rec['base']))
    e = base.entry
    dp = dp_of(base)
    src, dest = _ptr(e, dp), _ptr(e, dp + 4)

    def s32(v: int) -> bytes:
        return (v & 0xFFFFFFFF).to_bytes(4, 'little')
    dx, dy, dz = (mo_field(e, dest, n) for n in ('X', 'Y', 'Z'))
    pokes: List[Tuple[int, bytes]] = []
    kind = rec['kind']
    if kind == 'wall':
        x, y = _wall_point(e, mo_field(e, src, 'X'), mo_field(e, src, 'Y'))
        pokes += [(src + uc['UO_MO_X'], s32(x)), (src + uc['UO_MO_Y'], s32(y))]
    elif kind == 'damage':
        pokes += [(src + uc['UO_MO_X'], s32(dx + (20 << 16))),
                  (src + uc['UO_MO_Y'], s32(dy)),
                  (src + uc['UO_MO_Z'], s32(dz + (13 << 16) + 1))]
    elif kind == 'close':
        pokes += [(src + uc['UO_MO_X'], s32(dx)),
                  (src + uc['UO_MO_Y'], s32(dy + (6 << 16))),
                  (src + uc['UO_MO_Z'], s32(dz))]
    elif kind == 'shadow':
        flags = mo_field(e, dest, 'FLAGS') | uc['UC_MF_SHADOW_HI'] << 16
        pokes.append((dest + uc['UO_MO_FLAGS'], s32(flags)))
    else:
        raise PartError('a synthetic kind %r' % kind)
    return GC.call_case(base, pokes, note=rec['note'])


# ---------------------------------------------------------------------------
# The runs
# ---------------------------------------------------------------------------

def outputs(prep: CP.Prep, nat: 'SF.Native', m) -> List[str]:
    """checkpos.outputs, and the native A:X (the missile's slot, against
    upstream's X:C as a mobj)."""
    rest = dict(prep.spec, out=[o for o in prep.spec.get('out', [])
                                if o['native'] != 'ax'])
    diff: List[str] = []
    for item in prep.spec.get('out', []):
        if item['native'] != 'ax':
            continue
        lab = nat.b.labels
        got = G.card_byte(m, lab['dg_ra']) | G.card_byte(m, lab['dg_rx']) << 8
        raw = prep.ref.source(item['upstream'], 'out')
        want = SF.native_value(prep.mf, item['as'], prep.ref.ref(
            int.from_bytes(raw, 'little'), SF.kinds_of(item['as']), 'out'))
        if got != want:
            diff.append('output ax (%s): %X, upstream %X' % (
                item['upstream'], got, want))
    saved, prep.spec = prep.spec, rest
    try:
        diff += CP.outputs(prep, nat, m)
    finally:
        prep.spec = saved
    return diff


def run_one(prep: CP.Prep, nat: 'SF.Native', fill: int, profile: str
            ) -> Dict[str, Any]:
    """One run of a case (checkpos.run_one's steps with this part's
    outputs): equal, the differences, the cycles from the routine's entry
    to its return, the lowest S, the strays, the slots' groups at the
    return; a stop at an unbuilt routine is "waiting"."""
    spec = prep.spec
    res: Dict[str, Any] = {'entry': prep.key, 'fill': '%02x' % fill,
                           'profile': profile, 'ok': False}
    if prep.ref.problems:
        res['error'] = 'bridge: ' + '; '.join(prep.ref.problems[:3])
        return res
    img = prep.image(nat, fill)
    pre, canon = prep.pre_state(img, fill)
    entry = nat.b.labels[spec['native']]
    img.poke_word('dg_entry', entry)
    img.poke_label('dg_grp', bytes([nat.group(spec['native'])]))
    events = ['pc %X@1 snapshot start' % entry,
              'pc %X@1 snapshot ret' % nat.ret]
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-missile-', dir=str(BUILD)))
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), events=events,
                  banks=list(prep.banks) + [CP.LL.GTEST],
                  profile=profile, write_log=SF.LOG_RANGES,
                  cycles=SF.RUN_CYCLES)
        ended = r.ended()
        res['ended'] = ended
        res['lowest_s'] = r.state.get('lowest_s')
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                stop = G.stop_codes(G.load_snapshot(p))
                res['stop'] = stop
                if stop[0] in CP.WAITING:
                    res['waiting'] = True
            return res
        c0, c1 = SF.snapshot_cycles(work, 'start'), \
            SF.snapshot_cycles(work, 'ret')
        res['cycles'] = c1 - c0 if c0 is not None and c1 is not None \
            else None
        if c0 is None:
            raise PartError('no snapshot at the routine\'s entry')
        w = CP.check_writes(work / 'writes.log', canon, c0, prep.header)
        res['stray'] = w.strays
        res['stray_first'] = w.stray
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if w.canonical:
        from native import setupcheck as SC
        nat_state = CP.PortReader(prep.mf).read(SC.port_memory(m))
    else:
        nat_state = pre
    diff = CP.gcanon.compare(prep.ref.s_out, nat_state, 'routine')
    diff += outputs(prep, nat, m)
    diff += CP.MS.native_checks(m)
    res['sounds'] = len(SF.sounds(m))
    if w.strays:
        diff.append('%d stray writes: %s' % (w.strays, w.stray))
    res['diff'] = diff[:12]
    res['ok'] = not diff
    return res


def _check_job(job) -> List[Dict[str, Any]]:
    items, obj, fills, profiles, ps = job
    GC.CASES = CASES
    nat = SF.Native(Path(obj))
    CP.Prep.nat = nat
    spec_all = args()
    out: List[Dict[str, Any]] = []
    for key, item in items:
        path: List[str] = []
        try:
            if isinstance(item, dict):
                name = 'synthetic: ' + item['note']
                try:
                    case = synthetic_case(item)
                except GC.CapError as error:
                    out.append({'case': name, 'entry': key, 'ok': False,
                                'undecodable': ['no reference: %s' % error],
                                'path': []})
                    continue
                path = ['synthetic-' + item['kind']] + path_of(case)
            else:
                name = '/'.join(Path(item).parts[-3:])
                case = GC.load_case(Path(item))
                path = ps.get(key, {}).get(item, [])
            prep = CP.Prep(case, key, spec_all[key])
        except Exception as error:      # reported per case, never hidden
            out.append({'case': name, 'entry': key, 'ok': False,
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
                r.update(case=name, path=path)
                out.append(r)
    return out


def check_jobs(sample: int = 1, obj: Path = OUT,
               fills: Sequence[int] = FILLS,
               profiles: Sequence[str] = PROFILES, chunk: int = 5,
               keys: Sequence[str] = ENTRIES,
               synthetic: bool = True) -> List[Tuple]:
    ps = paths()
    chosen: List[Tuple[str, Any]] = []
    for key in keys:
        chosen += [(key, p) for p in selection(key, ps)[::sample]]
        if synthetic and key == SPAWN:
            chosen += [(key, r) for r in synthetic_plan()]
    jobs: List[Tuple] = []
    for i in range(0, len(chosen), chunk):
        jobs.append((chosen[i:i + chunk], str(obj), tuple(fills),
                     tuple(profiles), ps))
    return jobs


def run_jobs(jobs: List[Tuple], workers: int = 2) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if workers <= 1:
        for j in jobs:
            out += _check_job(j)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(_check_job, jobs):
            out += got
    return out


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ENTRIES:
        rs = [r for r in results if r.get('entry') == key]
        if not rs:
            continue
        waiting = [r for r in rs if r.get('waiting')]
        undecodable = [r for r in rs if r.get('undecodable')]
        run = [r for r in rs if not r.get('waiting') and
               not r.get('undecodable')]
        bad = [r for r in run if not r.get('ok')]
        paths_: Set[str] = set()
        for r in run:
            paths_.update(r.get('path', []))
        ls = [r['lowest_s']['s'] for r in run
              if isinstance(r.get('lowest_s'), dict)]
        out[key] = {
            'cases_chosen': len({r['case'] for r in rs}),
            'cases_run': len({r['case'] for r in run}),
            'cases_synthetic': len({r['case'] for r in run
                                    if r['case'].startswith('synthetic')}),
            'cases_waiting': sorted({r['case'] for r in waiting}),
            'cases_undecodable': [(r['case'], r['undecodable'])
                                  for r in undecodable],
            'runs': len(run), 'failures': len(bad),
            'stray_writes': sum(r.get('stray') or 0 for r in run),
            'cycles': {p: CP._stats([r['cycles'] for r in run
                                     if r.get('profile') == p and
                                     r.get('cycles')]) for p in PROFILES},
            'lowest_s': min(ls) if ls else None,
            'paths': sorted(paths_),
            'first_failures': [{k: r.get(k) for k in (
                'case', 'fill', 'profile', 'diff', 'error', 'ended', 'stop')}
                for r in bad[:4]]}
    return out


def placement_note(obj: Path = OUT) -> Dict[str, Any]:
    """Review 1's chain in the image's placement: each routine's group and
    slot (0: the core)."""
    nat = SF.Native(obj)
    text = (obj / 'gen' / 'gplace.inc').read_text()
    slots = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) == 3 and f[0].startswith('GRP') and f[0].endswith('_SLOT'):
            slots[int(f[0][3:-5])] = int(f[2])
    out = {}
    for n in LABELS + ('P_TryMove', 'checkPos', 'checkThing',
                       'P_DamageMobj', 'P_ExplodeMissile'):
        g = nat.group(n)
        out[n] = {'group': g, 'slot': slots.get(g, 0)}
    out['damage_pages_into_checkMissiles_slot'] = (
        out['checkMissile']['slot'] == out['P_DamageMobj']['slot'] != 0 and
        out['checkMissile']['group'] != out['P_DamageMobj']['group'])
    return out


# ---------------------------------------------------------------------------
# halfMom's random check (GAME.md 2.4 "Arithmetic")
# ---------------------------------------------------------------------------

BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
EDGES = (0, 1, -1, 2, -2, 3, -3, 0x7FFFFFFF, -0x80000000, 0x7FFFFFFE,
         -0x7FFFFFFF, 0xFFFF, 0x10000, -0x10000, 0x8000, -0x8000, 0x1FFFF,
         -0x1FFFF, 10 << 16, -(10 << 16))


def halfmom_inputs(n: int, seed: int = 1) -> List[Tuple[int, int]]:
    """(mom, coordinate) pairs: every pair of the edges, then random ones
    (any word; momentum-like; small)."""
    rnd = random.Random(seed)
    out = [(a, b) for a in EDGES for b in EDGES]
    while len(out) < n:
        k = len(out) % 3
        if k == 0:
            out.append((rnd.randint(-0x80000000, 0x7FFFFFFF),
                        rnd.randint(-0x80000000, 0x7FFFFFFF)))
        elif k == 1:
            out.append((rnd.randint(-(40 << 16), 40 << 16),
                        rnd.randint(-(4096 << 16), 4096 << 16)))
        else:
            out.append((rnd.randint(-8, 8), rnd.choice(EDGES)))
    return out[:n]


def _w32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def native_bulk(obj: Path, pairs: Sequence[Tuple[int, int]]) -> List[int]:
    b = G.load_build(obj, IMAGE)
    per = BULK_ROOM // 8
    out: List[int] = []
    for start in range(0, len(pairs), per):
        chunk = pairs[start:start + per]
        img = G.Image(b, 0xA5, store=False)
        img.aux(BULK_IN, 0x0200, b''.join(struct.pack('<ii', m, c)
                                           for m, c in chunk))
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-missile-bulk-',
                                     dir=str(BUILD)))
        try:
            k = len(chunk)
            r = G.run(img, work, GL.MODES['ROUTINE'], 'ms_bulk',
                      regs=(0, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise PartError('ms_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + 4 * k])
        out += [_s32(data[i:i + 4]) for i in range(0, len(data), 4)]
    return out


def upstream_bulk(pairs: Sequence[Tuple[int, int]]) -> List[int]:
    """Upstream's halfMom (mathref batch) on a captured checkMissile call's
    machine: X = OFS_MO_X, Y = OFS_MO_MOMX, _Dp[0-3] = the call's missile,
    its momx and x the inputs, its x the output."""
    import sight as SG
    uc = SF.uconst()
    caps = captured(CHECK)
    if not caps:
        raise PartError('no checkMissile case (python3 tools/native/gparts/'
                        'missile.py --capture)')
    case = GC.load_case(caps[0][2])
    th = _ptr(case.entry, sym('p_spawn65.s:SP_TH'))
    dp = dp_of(case)                 # (_Dp in bank 0: the direct page)
    mom, x = th + uc['UO_MO_MOMX'], th + uc['UO_MO_X']
    recs = b''.join(struct.pack('<HHIii', uc['UO_MO_X'], uc['UO_MO_MOMX'],
                                th, m, c) for m, c in pairs)
    pc = GC.CL.Linkmap().address(HALFMOM)
    got = SG.mathref(case, 'halfMom', pc,
                     ['x', 'y', '%06X 4' % dp, '%06X 4' % mom,
                      '%06X 4' % x], ['%06X 4' % x], recs, 4)
    return [_s32(g) for g in got]


def random_check(n: int = 100_000, seed: int = 1,
                 obj: Path = OUT) -> Dict[str, Any]:
    pairs = halfmom_inputs(n, seed)
    ups = upstream_bulk(pairs)
    nat = native_bulk(obj, pairs)
    bad = [(p, u, v) for p, u, v in zip(pairs, ups, nat) if u != v]
    model = sum(1 for (m, c), u in zip(pairs, ups) if u == _w32(c + (m >> 1)))
    return {'inputs': len(pairs), 'compared': min(len(ups), len(nat)),
            'different': len(bad) + abs(len(ups) - len(nat)),
            'first': bad[:5], 'edges': len(EDGES) ** 2,
            'upstream_is_the_model': model, 'seed': seed}


# ---------------------------------------------------------------------------
# The planted bugs (each in a scratch copy of the part's sources)
# ---------------------------------------------------------------------------

PLANT_EDITS: Dict[str, Tuple[str, List[Tuple[str, str]]]] = {
    # momz rounded the other way: the quotient floored (toward minus
    # infinity) instead of C's truncation, for a negative inexact divide
    'momz-floored': ('missile.s', [(
        '''        jsr sdiv32
        lda MSL_TH
        ldx MSL_TH+1''',
        '''        jsr sdiv32
        lda M_R+3               ; (planted) floor: a negative quotient
        bpl :++                 ;   with a remainder one less
        lda M_T
        ora M_T+1
        ora M_T+2
        ora M_T+3
        beq :++
        ldx #0
:       lda M_R,x
        sec
        sbc #1
        sta M_R,x
        bcs :+
        inx
        cpx #4
        bne :-
:       lda MSL_TH
        ldx MSL_TH+1''')]),
    # the shadow P_Random taken for a visible target too
    'shadow-random-always': ('missile.s', [(
        '''        and #<UC_MF_SHADOW_HI
        beq @mom''',
        '''        and #<UC_MF_SHADOW_HI
        nop                     ; (planted) for any target
        nop''')]),
    # the tics noise skipped
    'tics-noise-skipped': ('missile.s', [(
        '''        FCALL ticsNoise         ; tics -= P_Random() & 3, at least 1''',
        '''        ; (planted) FCALL ticsNoise''')]),
}
PLANT_NAMES = tuple(PLANT_EDITS)


def plant_build(name: str, tmp: Path) -> Path:
    """The part's image with the planted bug `name`, from a scratch copy of
    its sources in tmp (game.mk and its includes, the parts' fragments,
    this part's sources; the rest from the tree through game.mk's vpath):
    the image's directory."""
    src = tmp / 'src'
    files = list(G.PLANT_COPY) + ['game/%s/%s' % (PART, f) for f in SOURCES]
    for f in files:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    fname, edits = PLANT_EDITS[name]
    target = src / 'game' / PART / fname
    text = target.read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise PartError('the planted bug %s no longer applies: %r' % (
                name, old[:60]))
        text = text.replace(old, new)
    target.write_text(text)
    return build(game=tmp / 'game', source=src)


def plants(names: Optional[Sequence[str]] = None, sample: int = 1,
           workers: int = 2) -> Dict[str, Any]:
    out = {}
    for name in (names or PLANT_NAMES):
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-missile-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            res = run_jobs(check_jobs(obj=obj, sample=sample,
                                      profiles=(PROFILES[0],)), workers)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        run = [r for r in res if not r.get('waiting') and
               not r.get('undecodable')]
        bad = [r for r in run if not r.get('ok')]
        out[name] = {'runs': len(run), 'failed': len(bad),
                     'caught': bool(bad),
                     'first': (bad[0].get('diff') or [bad[0].get('error') or
                                                     bad[0].get('ended')])[:2]
                     if bad else None}
        say('%-24s %s' % (name, 'caught: %d of %d runs fail, %s' % (
            len(bad), len(run), out[name]['first']) if bad else
            'NOT CAUGHT (%d runs)' % len(run)))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)
LABELS = ('P_SpawnMissile', 'checkMissile', 'halfMom', 'srcAbove', 'seeTarget',
          'thSpeed', 'angleMom')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's game bytes (missile.o; mstest.o is the driver area's,
    test builds only) against its budget, by segment and group."""
    b = G.load_build(obj, IMAGE)
    text = (obj / (IMAGE + '.map')).read_text()
    mods = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    module = None
    total = 0
    segs: Dict[str, int] = {}
    for line in mods.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module == 'missile' and f and f[0] in b.segments:
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            total += size
            segs[f[0]] = segs.get(f[0], 0) + size
    nat = SF.Native(obj)
    lab = b.labels
    routines = {n: {'group': nat.group(n), 'address': '%04X' % lab[n]}
                for n in LABELS}
    return {'bytes': total, 'budget': BUDGET, 'upstream': UPSTREAM_BYTES,
            'over_10_percent': total > BUDGET * 1.1, 'segments': segs,
            'routines': routines}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def write_report(results: Optional[Sequence[Dict[str, Any]]] = None,
                 **parts) -> Dict[str, Any]:
    rep: Dict[str, Any] = {}
    if REPORT.exists():
        rep = json.loads(REPORT.read_text())
    rep.update(format='game-part-report 1', part=PART,
               wave=next(p['wave'] for p in GL.PARTS if p['name'] == PART),
               exclusions=[n for n, _, _ in CP.gcanon.ROUTINE_EXCLUSIONS],
               fills=['%02x' % f for f in FILLS], profiles=list(PROFILES))
    if results is not None:
        rep['entries'] = summarize(results)
        run = [r for r in results if not r.get('waiting') and
               not r.get('undecodable')]
        rep['runs'] = len(run)
        rep['waiting_runs'] = sum(1 for r in results if r.get('waiting'))
        rep['undecodable_cases'] = sum(1 for r in results
                                       if r.get('undecodable'))
        rep['failures'] = sum(1 for r in run if not r.get('ok'))
        rep['stray_writes'] = sum(r.get('stray') or 0 for r in run)
        ls = [r['lowest_s']['s'] for r in run
              if isinstance(r.get('lowest_s'), dict)]
        rep['lowest_s'] = min(ls) if ls else None
    rep.update(parts)
    rep['build_kb'] = CP.du_kb(OUT)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=1, default=str) + '\n')
    return rep


def print_report(rep: Dict[str, Any]) -> None:
    CP.print_report(rep)
    if 'random' in rep:
        r = rep['random']
        say('halfMom random: %d inputs, %d different, %d equal to the model'
            % (r['inputs'], r['different'], r['upstream_is_the_model']))
    if 'placement' in rep:
        say('placement: %s' % json.dumps(rep['placement']))


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--eligible', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--keys', default=None)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--count', type=int, default=100_000)
    parser.add_argument('--json', type=Path)
    a = parser.parse_args(argv)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if a.eligible:
        for key in ENTRIES:
            elig, waiting = eligible_calls(key)
            say('%-34s eligible %d, waiting %s' % (key, len(elig), waiting))
        return 0
    if a.capture:
        say('%d cases made' % capture())
        ps = paths(a.jobs)
        for key in ENTRIES:
            count: Dict[str, int] = {}
            for v in ps[key].values():
                for x in v:
                    count[x] = count.get(x, 0) + 1
            say('%s: %d candidates, %s' % (key, len(ps[key]), json.dumps(
                count, sort_keys=True)))
        return 0
    if a.check:
        start = time.time()
        build()
        keys = a.keys.split(',') if a.keys else ENTRIES
        res = run_jobs(check_jobs(sample=a.sample, keys=keys), a.jobs)
        rep = write_report(res, sizes=sizes(), placement=placement_note(),
                           check_seconds=round(time.time() - start),
                           sample=a.sample)
        if a.json:
            a.json.write_text(json.dumps(res, indent=1, default=str) + '\n')
        print_report(rep)
        return 1 if rep['failures'] else 0
    if a.random:
        build()
        start = time.time()
        r = random_check(a.count)
        r['seconds'] = round(time.time() - start)
        rep = write_report(random=r)
        print_report(rep)
        return 1 if r['different'] else 0
    if a.plants:
        build()
        r = plants(a.keys.split(',') if a.keys else None, workers=a.jobs)
        write_report(plants=r)
        return 0 if all(x['caught'] for x in r.values()) else 1
    if a.report:
        print_report(json.loads(REPORT.read_text()))
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
