#!/usr/bin/env python3
"""Part look's checkpoint (milestone 10, wave 3; docs/GAME.md 2.4, 3.5;
docs/game-parts/look.md), lean (the owner's rules of 2026-10-02: at most
40 calls a routine, the $A5 machine only, one profile): its image, its
captures, its routine-mode runs, its synthetic cases, its planted bugs,
and build/native/game/look/report.json.

Usage:  python3 tools/native/gparts/look.py --build
        python3 tools/native/gparts/look.py --log        (the callFn logs)
        python3 tools/native/gparts/look.py --capture [--jobs 2]
        python3 tools/native/gparts/look.py --check [--jobs 2]
        python3 tools/native/gparts/look.py --plants [--jobs 2]

The image (build()): `make -f game.mk part P=look` from a scratch copy of
the build files (the planted bugs' too), into build/native/game/look/.

The captures (capture()): tools/native/gamecap.py's, into the part's own
build/native/game/look/cases/. The routines entered by JSR or JSL
(lookForPlayers, behindFast, checkMeleeRange, checkMissileRange) at
calls of demo3 spread evenly (the survey's hits). The actions are entered
by p_tick65.s's callFn (JML [FN_P]), which --capture does not count: a
call log of callFn with FN_P (the JML's operand, DC_ENTRY) at each entry
(log(): ref816 --call-log through a pipe, never stored; the hits and
their action kept in OUT/callfn-RUN.json) gives callFn's hits that enter
each action, and those are captured at callFn (the same state and
return). A_Explode's calls (demo2) give the P_RadiusAttack cases: the
reference's own P_RadiusAttack (ref816 --call) on the state at the call
with _Dp[4-7] = the barrel's target and C = 128, what A_Explode passes.

A run (run_one()): part mobjstate's Prepared (the case's entry state
through the game manifest into a machine poisoned with $A5, the entry's
inputs), the call on a2vm (f121), the state read back and compared with
the reference's (gcanon's routine mode, exclusions R1-R7), every
declared output (A's low byte; behindFast's carry and A), and no CPU
write outside the places this part, sight, damage, mobjstate and geom
may write (stray()). A call that reaches an unbuilt action stops at its
DCALL (a "stop" check: the stop's action is a state's of a mobj the
snapshot holds); its variant with that state's action removed on both
sides (upstream's states table and the native GTAB copy, the reference
run again by --call) is compared whole ("action removed"), as part
damage does.

Synthetic cases: behindFast at its edges (an actor at an angle of k *
ANG45 and a target placed where |d| - 2 = T or 2 (|d| - 1) = T, and one
unit beyond, for each k: the reference's behindFast by --call);
A_FaceTarget at a shadow target (its target's MF_SHADOW set); the radius
attack with a thing on the spot (its distance below 0, clamped) and a
damage of 400 (things behind walls in range).
"""

import argparse
import json
import os
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

from bridge.port import PortReader, PortError  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL, \
    render_check as RC  # noqa: E402
from ref816 import bounded, calls as CL  # noqa: E402
import mobjstate as MSP  # noqa: E402  (part mobjstate's harness, wave 1)

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'look'
OUT = GL.GAME / PART
MYCASES = OUT / 'cases'
REPORT = OUT / 'report.json'
FILL = 0xA5
PROFILE = 'f121'
NAME = 'ptest'
BUDGET = 2300                   # GAME.md 2.4: upstream 1,729 x 1.3
UPSTREAM_BYTES = 1729
MODULES = ('look', 'radius')
PER_ROUTINE = 40                # the lean rule
CALLFN = 'p_tick65.s:callFn'
FN_P = 'DC_ENTRY'               # callFn's JML [FN_P] operand (bank 0)
E = 'p_enemy65.s:'
A = 'p_attack65.s:'
LOOK, LFP, BF = E + 'A_Look', E + 'lookForPlayers', E + 'behindFast'
FACE, MELEE, MISSILE = E + 'A_FaceTarget', E + 'checkMeleeRange', \
    E + 'checkMissileRange'
SCREAM, XSCREAM, PAIN, FALL, PSCREAM = (E + n for n in (
    'A_Scream', 'A_XScream', 'A_Pain', 'A_Fall', 'A_PlayerScream'))
EXPLODE = E + 'A_Explode'
RADIUS, PIT = A + 'P_RadiusAttack', A + 'PIT_RadiusAttack'
ACTIONS = (LOOK, FACE, SCREAM, XSCREAM, PAIN, FALL, PSCREAM, EXPLODE)
# (run, file:label, how many) of the routines entered by JSR or JSL
DIRECT = [('demo3', LFP, PER_ROUTINE), ('demo3', BF, PER_ROUTINE),
          ('demo3', MELEE, PER_ROUTINE), ('demo3', MISSILE, PER_ROUTINE)]
# (run, action, how many) of callFn's hits
VIA_CALLFN = [('demo3', LOOK, PER_ROUTINE), ('demo3', FACE, 20),
              ('demo3', SCREAM, 10), ('demo3', PAIN, 10),
              ('demo3', FALL, 10), ('demo3', PSCREAM, 1),
              ('demo2', XSCREAM, 2), ('demo2', EXPLODE, 10)]
LOG_RUNS = ('demo3', 'demo2')
ALLOWED_PARTS = ('look', 'sight', 'damage', 'mobjstate', 'geom')


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
    """The part's image (game/look/ptest.*) from a scratch copy of the
    build files and the bugs (file under src/native, old, new) applied to
    copies; every other source from the tree (game.mk's vpath). The copy
    is deleted."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-look-build-', dir=str(BUILD)))
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
    """The part's bytes by module (the image's map); own_bytes without the
    stand-in (distanceAT's copy of math.s's aproxdist, lk_standin ..
    lk_standin_end: request 2), against the budget."""
    ms = MSP.module_ranges(b)
    by = {m: sum(hi + 1 - lo for _, lo, hi in ms.get(m, ()))
          for m in MODULES}
    part = sum(by.values())
    mine = set(next(x for x in GL.PARTS if x['name'] == PART)['routines'] +
               next(x for x in GL.PARTS if x['name'] == PART)['helpers'])
    try:
        rs = {k: v for k, v in G.routine_sizes(b)[0].items() if k in mine}
    except Exception as error:          # (a report only)
        rs = {'error': str(error)}
    lab = b.labels
    standin = lab['lk_standin_end'] - lab['lk_standin'] \
        if 'lk_standin' in lab and 'lk_standin_end' in lab else 0
    own = part - standin
    return {'routines': rs, 'modules': by, 'part_bytes': part,
            'standin_bytes': standin, 'own_bytes': own,
            'budget': BUDGET, 'upstream_bytes': UPSTREAM_BYTES,
            'over_budget_pct': round(100.0 * (own - BUDGET) / BUDGET, 1),
            'groups': sorted({seg for m in MODULES for seg, _, _ in
                              ms.get(m, ())})}


# ---------------------------------------------------------------------------
# The callFn logs
# ---------------------------------------------------------------------------

def log_path(run: str) -> Path:
    return OUT / ('callfn-%s.json' % run)


def log(run: str, say=print) -> Dict[str, Any]:
    """One call log of run (ref816 --call-log through a pipe): callFn's
    hits by the action they enter ({action: [[hit, tic], ...]} for
    ACTIONS); of A_Look's, those whose call reached P_SetMobjState (the
    actor saw: 'look_seen'); and every call of the routines entered by
    JSR, with its A at the entry and at the return ('direct': {key:
    [[hit, tic, a in, a out], ...]}), so that the choice can take every
    branch's calls."""
    table = CL.Linkmap()
    want = {table.address(k) & 0xFFFFFF: k for k in ACTIONS}
    fn_p = table.address(FN_P)
    hits: Dict[str, List[List[int]]] = {k: [] for k in ACTIONS}
    direct: Dict[str, List[List[int]]] = {k: [] for _, k, _ in DIRECT}
    seen_hits: List[List[int]] = []
    box: Dict[str, Any] = {}

    def reader(handle) -> None:
        first = json.loads(handle.readline())
        names = [r['name'] for r in first['routines']]
        tic = -1
        n = 0
        callfn: Dict[int, Tuple[int, str, int]] = {}
        parents = set()
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
                target = int.from_bytes(bytes.fromhex(
                    line['in']['mem'][0]), 'little') & 0xFFFFFF
                key = want.get(target)
                if key:
                    hits[key].append([line['hit'], tic])
                    if key == LOOK:
                        callfn[line['call']] = (line['hit'], key, tic)
            elif name == 'setstate':
                parents.add(line['parent'])
            elif name == LOOK:
                c = line['call']
                got = callfn.pop(c - 1, None)
                if got is None:
                    raise PartError('%s: A_Look call %d follows no callFn'
                                    % (run, c))
                if c in parents:
                    seen_hits.append([got[0], got[2]])
                    parents.discard(c)
            elif name in direct:
                o = line['out'] or {}
                direct[name].append([line['hit'], tic,
                                     line['in']['a'] & 0xFFFF,
                                     o.get('a', 0) & 0xFFFF,
                                     o.get('p', 0) & 0xFF])
        box['calls'] = n

    routines = ['%s,name=%s,in=_g_gametic:4,entry=1' % (GC.TICKER,
                                                       GC.TIC_NAME),
                '%s,name=callFn,in=%06X:3,entry=1' % (CALLFN, fn_p),
                '%s,name=%s,jumps=1' % (LOOK, LOOK),
                'p_tick65.s:P_SetMobjState,name=setstate,entry=1']
    routines += ['%s,name=%s' % (k, k) for _, k, _ in DIRECT]
    check_disk()
    work = Path(tempfile.mkdtemp(prefix='tmp-look-log-', dir=str(BUILD)))
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
    out = {'format': 'look-callfn 2', 'run': run, 'calls': box.get('calls'),
           'hits': hits, 'look_seen': seen_hits, 'direct': direct,
           'seconds': round(time.time() - start)}
    OUT.mkdir(parents=True, exist_ok=True)
    log_path(run).write_text(json.dumps(out) + '\n')
    say('%s: %d callFn calls, %s; A_Look seeing %d; %s' % (
        run, out['calls'], ', '.join('%s %d' % (k.split(':')[1], len(v))
                                     for k, v in hits.items()),
        len(seen_hits), ', '.join('%s %d' % (k.split(':')[1], len(v))
                                  for k, v in direct.items())))
    return out


def load_log(run: str) -> Dict[str, Any]:
    p = log_path(run)
    if not p.exists():
        raise PartError('no %s (python3 tools/native/gparts/look.py --log)'
                        % p)
    return json.loads(p.read_text())


# ---------------------------------------------------------------------------
# The captures
# ---------------------------------------------------------------------------

def use_cases() -> None:
    MSP.use_cases(MYCASES)


def spread(items: Sequence[Any], n: int) -> List[Any]:
    if len(items) <= n:
        return list(items)
    return [items[int((i + 0.5) * len(items) / n)] for i in range(n)]


def by_class(items: Sequence[Any], cls, n: int) -> List[Any]:
    """n of items with every class cls(item) represented: the smallest
    classes first, each an equal share of what is left (all of a class
    smaller than its share), spread evenly in each; in items' order."""
    classes: Dict[Any, List[Any]] = {}
    for it in items:
        classes.setdefault(cls(it), []).append(it)
    order = sorted(classes.values(), key=len)
    out: List[Any] = []
    left = n
    for i, members in enumerate(order):
        if left <= 0:
            break
        take = spread(members, max(1, left // (len(order) - i)))
        out += take
        left -= len(take)
    return sorted(out)


def selection() -> List[Tuple[str, str, str, List[Tuple[int, int]]]]:
    """(run, capture key, entry key, [(hit, tic)]) of every chosen call:
    the JSR routines' calls by their branch (lookForPlayers by allaround
    and its answer, the range checks by their answer, from the log's A at
    the entry and the return), A_Look's calls that see and that do not,
    the other actions' spread evenly; the last call of a run left out."""
    out = []
    for run, key, n in DIRECT:
        lg = load_log(run)
        calls = lg['direct'][key][:-1]
        if key == LFP:
            cls = (lambda c: (c[2] & 1, c[3] & 0xFF))
        elif key == BF:
            cls = (lambda c: (c[4] & 1, c[3] & 1 if c[4] & 1 else 0))
        else:
            cls = (lambda c: c[3] & 0xFF)
        out.append((run, key, key, [(c[0], c[1]) for c in
                                    by_class(calls, cls, n)]))
    for run, key, n in VIA_CALLFN:
        lg = load_log(run)
        if key == LOOK:
            seen = {h for h, _ in lg['look_seen']}
            calls = lg['hits'][key][:-1]
            chosen = by_class(calls, lambda c: c[0] in seen, n)
        else:
            chosen = spread(lg['hits'][key], n)
        out.append((run, CALLFN, key, [tuple(x) for x in chosen]))
    return out


def case_path(run: str, key: str, hit: int) -> Path:
    use_cases()
    return GC.case_dir(run, key) / ('h%08d.case.z' % hit)


def _capture_job(job) -> str:
    run, key, hits = job
    use_cases()
    made = GC.capture(run, key, [h for h, _ in hits], _tics_list(hits),
                      say=lambda *a: None)
    return '%s %s: %d made' % (run, key, len(made))


def _tics_list(hits: Sequence[Tuple[int, int]]) -> List[int]:
    top = max(h for h, _ in hits)
    tics = [-1] * top
    for h, t in hits:
        tics[h - 1] = t
    return tics


def nesting_hits(run: str) -> set:
    """callFn's hits whose call enters callFn again before it returns (an
    A_Look that sees: P_SetMobjState runs the see state's action). ref816's
    --capture does not count a nested call of the routine it is
    capturing, so every later hit of the same run would be one late: such
    a hit is always the last of its capture run."""
    try:
        lg = load_log(run)
    except PartError:
        return set()
    return {h for h, _ in lg.get('look_seen', [])}


def capture(jobs: int = 2, say=print) -> None:
    """Every chosen call the part's case directory lacks, by run and
    capture key, at most GC.BATCH a ref816 run, a nesting hit last; the
    first batch of a run alone (it writes the run's base). Then every
    callFn case is checked to enter the action the log names (verify())."""
    use_cases()
    by: Dict[Tuple[str, str], Dict[int, int]] = {}
    for run, key, _, hits in selection():
        d = by.setdefault((run, key), {})
        for h, t in hits:
            if not case_path(run, key, h).exists():
                d[h] = t
    todo = []
    for (run, key), d in sorted(by.items()):
        nest = nesting_hits(run) if key == CALLFN else set()
        batch: List[Tuple[int, int]] = []
        for h, t in sorted(d.items()):
            batch.append((h, t))
            if h in nest or len(batch) == GC.BATCH:
                todo.append((run, key, batch))
                batch = []
        if batch:
            todo.append((run, key, batch))
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
        raise PartError('%d callFn cases entered another action' % len(bad))


def verify() -> List[Path]:
    """The callFn cases whose FN_P at the entry is not the action the
    log names for their hit, or whose gametic is not the logged one, or
    an A_Look whose state change is not the log's seeing."""
    use_cases()
    table = CL.Linkmap()
    fn_p = table.address(FN_P)
    bad = []
    for run, key, entry, hits in selection():
        if key != CALLFN:
            continue
        want = table.address(entry) & 0xFFFFFF
        seen = nesting_hits(run)
        for h, tic in hits:
            p = case_path(run, key, h)
            if not p.exists():
                continue
            c = GC.load_case(p)
            got = int.from_bytes(c.entry.read(fn_p, 3), 'little')
            gametic = int.from_bytes(c.entry.read(table.address(
                'g_game65.s:_g_gametic'), 4), 'little')
            ok = got == want and gametic == tic
            if ok and entry == LOOK:
                ap = ptr(c.entry, MSP.dp_address(c, '_Dp', 0))
                o = uconst('UO_MO_STATE')
                ok = (c.entry.read(ap + o, 2) != c.after.read(ap + o, 2)) \
                    == (h in seen)
            if not ok:
                bad.append(p)
    return bad


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

LOG_RANGES = MSP.LOG_RANGES
ACTTAB_TABLE = list(GL.DISPATCH).index('ACTTAB') + 1


def allowed_main(b: RC.Build) -> List[Tuple[int, int]]:
    """Part mobjstate's places (P_SetMobjState runs in this part's calls)
    and the scratch blocks of the parts this part's calls reach: its own,
    sight's (P_CheckSight), damage's (P_DamageMobj), geom's
    (P_BlockThingsIterator)."""
    out = MSP.allowed_main(b)
    blocks = GL.scratch_blocks()
    for name in ALLOWED_PARTS:
        lo, n = blocks[name]
        out.append((lo, lo + n))
    return out


def stray(writes, b: RC.Build, header: Dict[str, Any]) -> List[str]:
    """CPU writes outside the allowed places (part mobjstate's rule with
    allowed_main(), and math.s's mt_far patching its own two operands in
    the card's bank 1: the game's math, damage.md R6)."""
    allowed = allowed_main(b)
    desc = b.segments['DESC']
    drv = b.segments['DRIVER']
    loader = b.segments['RLOAD']
    far = b.segments['RFAR']
    mfar = b.segments.get('MATHFAR')
    patched = MSP.mt_far_operands(b)
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


def outputs(spec: Dict[str, Any], case: GC.Case, m, b: RC.Build
            ) -> List[str]:
    """The declared outputs: 'a' (A's low byte), 'bf' (behindFast: the
    carry; A when it is set, native A $FF when it is clear)."""
    lab = b.labels
    na = G.card_byte(m, lab['dg_ra'])
    nc = G.card_byte(m, lab['dg_rp']) & 1
    ua = case.regs_out['a'] & 0xFF
    uc = case.regs_out['p'] & 1
    diff = []
    for item in spec.get('out', []):
        if item['native'] == 'a':
            if na != ua:
                diff.append('A %02X, upstream %02X' % (na, ua))
        elif item['native'] == 'bf':
            if (nc, na if nc else 0xFF if na == 0xFF else na) != \
                    (uc, ua if uc else 0xFF):
                diff.append('behindFast C %d A %02X, upstream C %d A %02X'
                            % (nc, na, uc, ua))
        else:
            raise PartError('an output %r' % item)
    return diff


def run_one(case, spec: Dict[str, Any], b: RC.Build, extra: Sequence = (),
            prep: Optional[MSP.Prepared] = None, keep_crash: bool = False,
            fill: int = FILL, profile: Optional[str] = PROFILE
            ) -> Dict[str, Any]:
    """The case on image b ($A5, f121): the comparison (gcanon's routine
    mode), the declared outputs, the stray writes, the native checks, the
    call's clock and cycles, the lowest S. extra: image records after the
    state (a synthetic poke of GTAB); keep_crash: a stop's snapshot in
    _crash."""
    if prep is None:
        prep = MSP.Prepared(case, spec)
    case, up = prep.case, prep.up
    res: Dict[str, Any] = {
        'case': '%s/%s' % (case.path.parent.parent.name, case.path.name)
        if case.path else case.header.get('note') or 'synthetic',
        'routine': case.key, 'hit': case.header['hit'],
        'fill': '%02x' % fill, 'profile': profile, 'ok': False}
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
    work = Path(tempfile.mkdtemp(prefix='tmp-look-run-', dir=str(BUILD)))
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
    diff += outputs(spec, case, m, b)
    res['fc_loads'] = m.main[GL.RT['FC_LOADS']] | \
        m.main[GL.RT['FC_LOADS'] + 1] << 8
    res['diff'] = diff[:12]
    res['ok'] = not diff and not res['strays']
    return res


# ---------------------------------------------------------------------------
# A call that reaches an unbuilt action: the stop, then the variant with
# the action removed (part damage's method)
# ---------------------------------------------------------------------------

def stopped_states(cm, case: GC.Case, number: int) -> List[int]:
    """The states whose action is ACTTAB entry `number` among the states
    of the mobjs the stop's snapshot holds in the cache (P_SetMobjState
    sets the state before the action) and of the player's psprites
    (setPsprite the same)."""
    nums = MSP.act_numbers()
    out: List[int] = []
    for i in range(LL.MOC_LINES):
        slot = cm.main[GL.RT['MOC_TL'] + i] | cm.main[GL.RT['MOC_TH'] + i] \
            << 8
        if slot == 0xFFFF:
            continue
        got = MSP.mobj_at_stop(cm, slot)
        s = got['state'] if got else 0xFFFF
        if s == 0xFFFF or s in out or s >= LL.NUMSTATES:
            continue
        act = MSP.state_record(case.entry, s)['action']
        if act and nums.get(act) == number:
            out.append(s)
    consts = dict(LL.game_constants())
    pl = LL.G['G_PLAYER']
    for k in ('PL_PSPRITES_0_STATE', 'PL_PSPRITES_1_STATE'):
        a = pl + consts[k]              # the psprites' (setPsprite)
        s = cm.main[a] | cm.main[a + 1] << 8
        if s == 0xFFFF or s in out or s >= LL.NUMSTATES:
            continue
        act = MSP.state_record(case.entry, s)['action']
        if act and nums.get(act) == number:
            out.append(s)
    return out


def ref_regs(case: GC.Case) -> Dict[str, int]:
    return {k: case.regs_in[k] & 0xFFFF for k in ('a', 'x', 'y')}


def action_removed(case: GC.Case, states: Sequence[int], extra: Sequence
                   ) -> Tuple[GC.Case, List]:
    """The case with the states' actions removed (their action 0 in
    upstream's table, and the native GTAB copy from the same bytes), run
    again on ref816 (--call)."""
    t = GC.CL.Linkmap()
    mem = case.entry.copy()
    mem.header = case.entry.header
    for s in states:
        mem.write(t.address(MSP.STATES) + 16 * s + 6, bytes(4))
    after, call = MSP.ref_call(mem, case.key, (), ref_regs(case))
    note = '%s, state %s\'s action removed' % (
        '%s/%s' % (case.path.parent.parent.name, case.path.name)
        if case.path else case.header.get('note') or '',
        '/'.join(str(s) for s in states))
    v = GC.Case(dict(case.header, note=note, call=call), mem, after, None)
    return v, list(extra) + MSP.gtab_state_records(mem, states)


_KEYS: List[Any] = []


def acttab_keys() -> List[str]:
    if not _KEYS:
        from native import gcallgraph as CG
        _KEYS.append(GL.dispatch_entries(CG.load(write=False))['ACTTAB'])
    return _KEYS[0]


def evaluate(case: GC.Case, spec: Dict[str, Any], b: RC.Build, kind: str,
             entry: str, extra: Sequence = (), depth: int = 0
             ) -> List[Dict[str, Any]]:
    """A case's run, or its stop check and the variants."""
    prep = MSP.Prepared(case, spec)
    path = '' if prep.problems else path_of(entry, prep.up, case)
    r = run_one(case, spec, b, extra, prep, keep_crash=True)
    cm = r.pop('_crash', None)
    stop = r.get('stop')
    r.update(kind=kind, entry=entry, path=path)
    if not (stop and stop[0] == GL.GS['UNBUILTD'] and
            stop[1] >> 8 == ACTTAB_TABLE):
        return [r]
    number = stop[1] & 0xFF
    states = stopped_states(cm, case, number)
    keys = acttab_keys()
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
            v, vextra = action_removed(case, states, extra)
        except Exception as error:      # reported, never hidden
            out.append({'ok': False, 'kind': 'action removed',
                        'entry': entry, 'path': path, 'error': '%s: %s' % (
                            type(error).__name__, error)})
            return out
        out += evaluate(v, spec, b, 'action removed', entry, vextra,
                        depth + 1)
    return out


# ---------------------------------------------------------------------------
# The paths (the branches a case takes, from the reference)
# ---------------------------------------------------------------------------

def uconst(name: str) -> int:
    return MSP.uconst(name)


def ptr(mem, a: int) -> int:
    return int.from_bytes(mem.read(a, 4), 'little') & 0xFFFFFF


def path_of(entry: str, up: GR.Upstream, case: GC.Case) -> str:
    """A short name of the branch the reference took."""
    ra, rp = case.regs_out['a'] & 0xFF, case.regs_out['p'] & 1
    mem, after = case.entry, case.after
    if entry == BF:
        return 'cannot tell' if not rp else ('behind' if ra else 'front')
    if entry == LFP:
        return 'allaround %d, seen %d' % (case.regs_in['a'] & 1, ra)
    if entry in (MELEE, MISSILE):
        ap = ptr(mem, MSP.dp_address(case, '_Dp', 8))
        tgt = ptr(mem, ap + uconst('UO_MO_TARGET')) if ap else 0
        if not tgt:
            return 'no target'
        if entry == MISSILE:
            fl = mem.read(ap + uconst('UO_MO_FLAGS'), 1)[0]
            if ra and fl & 0x40:
                return 'just hit'
        return 'true' if ra else 'false'
    if entry in (LOOK, FACE, SCREAM, XSCREAM, PAIN, FALL, PSCREAM,
                 RADIUS):
        ap = ptr(mem, MSP.dp_address(case, '_Dp', 0))
        if entry == LOOK:
            st0 = mem.read(ap + uconst('UO_MO_STATE'), 2)
            st1 = after.read(ap + uconst('UO_MO_STATE'), 2)
            return 'seen' if st0 != st1 else 'not seen'
        if entry == FACE:
            tgt = ptr(mem, ap + uconst('UO_MO_TARGET'))
            if not tgt:
                return 'no target'
            shadow = mem.read(tgt + uconst('UO_MO_FLAGS') + 2, 1)[0] & 4
            return 'shadow target' if shadow else 'target'
        if entry == RADIUS:
            return case.header.get('variant') or 'explosion'
        return 'call'
    return ''


# ---------------------------------------------------------------------------
# Synthetic cases
# ---------------------------------------------------------------------------

DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1),
        (1, -1)]


def bf_model(k: int, xi: int, yi: int) -> Optional[int]:
    """behindFast's answer (None: it cannot tell) for an actor angle k *
    ANG45 and whole units xi, yi (a host model, to place the synthetic
    targets; the truth is the reference's run)."""
    if abs(xi) >= 4096 or abs(yi) >= 4096:
        return None
    s = abs(xi) + abs(yi)
    if s < 64:
        return None
    t = (s + 2) >> 4
    cx, cy = DIRS[k]
    d = cx * xi + cy * yi
    v = abs(d) - 2 if k & 1 else 2 * (abs(d) - 1)
    if v < 0 or v <= t:
        return None
    return 1 if d < 0 else 0


def bf_points(k: int) -> List[Tuple[int, int, str]]:
    """Two targets behind an actor at angle k: at the edge (v = T: it
    cannot tell) and one unit beyond (v = T + 1: it tells); a units
    behind along the direction, bb across it."""
    out: List[Tuple[int, int, str]] = []
    cx, cy = DIRS[k]
    px, py = -cy, cx
    for want in ('edge', 'beyond'):
        found = None
        for a in range(2, 300):
            for bb in range(0, 4096):
                xi, yi = -cx * a + px * bb, -cy * a + py * bb
                if abs(xi) >= 4096 or abs(yi) >= 4096:
                    break
                s = abs(xi) + abs(yi)
                d = cx * xi + cy * yi
                if s < 64 or d >= 0:
                    continue
                t = (s + 2) >> 4
                v = abs(d) - 2 if k & 1 else 2 * (abs(d) - 1)
                if v == t + (want == 'beyond'):
                    found = (xi, yi)
                    break
            if found:
                break
        if found:
            out.append((found[0], found[1], want))
    return out


def bf_case(base: GC.Case, k: int, xi: int, yi: int, note: str) -> GC.Case:
    """base (a captured behindFast call) with the actor's angle k * ANG45
    and its target at the actor's x, y + (xi, yi) whole units: the
    reference's behindFast by --call."""
    mem = base.entry
    ap = ptr(mem, MSP.dp_address(base, '_Dp', 8))
    at = ptr(mem, MSP.dp_address(base, '_Dp', 12))
    ox, oy, oa = (uconst('UO_MO_X'), uconst('UO_MO_Y'),
                  uconst('UO_MO_ANGLE'))
    ax = int.from_bytes(mem.read(ap + ox, 4), 'little')
    ay = int.from_bytes(mem.read(ap + oy, 4), 'little')
    pokes = [(ap + oa, (k << 29).to_bytes(4, 'little')),
             (at + ox, ((ax + (xi << 16)) & 0xFFFFFFFF).to_bytes(4,
                                                                 'little')),
             (at + oy, ((ay + (yi << 16)) & 0xFFFFFFFF).to_bytes(4,
                                                                 'little'))]
    return poked_case(base, BF, pokes, ref_regs(base), note)


def poked_case(base: GC.Case, key: str, pokes, regs: Dict[str, int],
               note: str, variant: str = '') -> GC.Case:
    entry = base.entry.copy()
    entry.header = base.entry.header
    for a, d in pokes:
        entry.write(a, d)
    after, call = MSP.ref_call(entry, key, (), regs)
    hdr = dict(base.header, routine=key, note=note, call=call,
               variant=variant)
    return GC.Case(hdr, entry, after, None)


def radius_case(base: GC.Case, damage: int = 128, on_spot: bool = False
                ) -> GC.Case:
    """An A_Explode call (captured at callFn) as the reference's own
    P_RadiusAttack(barrel, barrel->target, damage) by --call; on_spot:
    a shootable mobj of the attack's blocks moved onto the spot (x, y:
    its distance below 0, clamped), its lists kept."""
    mem = base.entry
    dp0 = MSP.dp_address(base, '_Dp', 0)
    spot = ptr(mem, dp0)
    src = mem.read(spot + uconst('UO_MO_TARGET'), 4)
    pokes = [(MSP.dp_address(base, '_Dp', 4), src)]
    variant = 'damage %d' % damage
    if on_spot:
        got = spot_candidate(base, damage)
        if got is None:
            raise PartError('no shootable mobj near the spot')
        a, sx, sy = got
        ox, oy = uconst('UO_MO_X'), uconst('UO_MO_Y')
        pokes += [(a + ox, (sx & 0xFFFFFFFF).to_bytes(4, 'little')),
                  (a + oy, (sy & 0xFFFFFFFF).to_bytes(4, 'little'))]
        variant += ', a thing on the spot'
    regs = dict(ref_regs(base), a=damage)
    return poked_case(base, RADIUS, pokes, regs, '%s: %s' % (
        base.path.name if base.path else '?', variant), variant)


def spot_candidate(base: GC.Case, damage: int
                   ) -> Optional[Tuple[int, int, int]]:
    """The shootable mobj nearest the spot (not the spot) within damage
    units: (its address, the spot's x, y), or None."""
    from bridge.fields import R as Ref
    mem = base.entry
    spot = ptr(mem, MSP.dp_address(base, '_Dp', 0))
    up = GR.Upstream(base)
    ox, oy = uconst('UO_MO_X'), uconst('UO_MO_Y')
    sx = int.from_bytes(mem.read(spot + ox, 4), 'little', signed=True)
    sy = int.from_bytes(mem.read(spot + oy, 4), 'little', signed=True)
    best = None
    for kind in ('mobj', 'zmobj'):
        for i in sorted(up.s_in['objects'].get(kind, {})):
            a = up.r_in.ref_address(Ref(kind, i, None))
            if a == spot:
                continue
            fl = int.from_bytes(mem.read(a + uconst('UO_MO_FLAGS'), 4),
                                'little')
            if not fl & 4:              # MF_SHOOTABLE
                continue
            x = int.from_bytes(mem.read(a + ox, 4), 'little', signed=True)
            y = int.from_bytes(mem.read(a + oy, 4), 'little', signed=True)
            dd = max(abs(x - sx), abs(y - sy))
            if dd < (damage << 16) and (best is None or dd < best[0]):
                best = (dd, a)
    return (best[1], sx, sy) if best else None


def face_shadow_case(base: GC.Case) -> GC.Case:
    """A captured A_FaceTarget call with its target's MF_SHADOW set."""
    mem = base.entry
    ap = ptr(mem, MSP.dp_address(base, '_Dp', 0))
    tgt = ptr(mem, ap + uconst('UO_MO_TARGET'))
    a = tgt + uconst('UO_MO_FLAGS') + 2
    pokes = [(a, bytes([mem.read(a, 1)[0] | 4]))]
    return poked_case(base, CALLFN, pokes, ref_regs(base),
                      '%s: a shadow target' % base.path.name,
                      'shadow target')


# ---------------------------------------------------------------------------
# The checkpoint
# ---------------------------------------------------------------------------

def spec_of(key: str) -> Dict[str, Any]:
    return GR.all_args()[key]


def chosen_paths() -> List[Tuple[str, str]]:
    """(entry, case path) of every chosen call that is captured."""
    out = []
    for run, key, entry, hits in selection():
        for h, _ in hits:
            p = case_path(run, key, h)
            if p.exists():
                out.append((entry, str(p)))
    return out


def plan(synthetic: bool = True, entries=None) -> List[Tuple]:
    js: List[Tuple] = []
    for entry, path in chosen_paths():
        if entry == EXPLODE:
            js.append(('radius', path, 128, False))
            if synthetic:
                use_cases()
                if spot_candidate(GC.load_case(Path(path)), 128):
                    js.append(('radius', path, 128, True))
                js.append(('radius', path, 400, False))
        else:
            js.append(('case', path, entry))
    if synthetic:
        bfs = [p for e, p in chosen_paths() if e == BF]
        for k in range(8):
            for xi, yi, want in bf_points(k):
                js.append(('bf', bfs[k % len(bfs)], k, xi, yi, want))
        faces = [p for e, p in chosen_paths() if e == FACE]
        for p in faces[:4]:
            js.append(('shadow', p))
    if entries:
        js = [j for j in js if job_entry(j) in entries]
    return js


def job_entry(j: Tuple) -> str:
    return {'radius': RADIUS, 'bf': BF, 'shadow': FACE}.get(j[0]) or j[2]


def _job(job: Tuple) -> List[Dict[str, Any]]:
    obj, j = job
    use_cases()
    b = G.load_build(Path(obj), NAME)
    try:
        if j[0] == 'case':
            _, path, entry = j
            case = GC.load_case(Path(path))
            return evaluate(case, spec_of(entry), b, 'captured', entry)
        if j[0] == 'radius':
            _, path, damage, on_spot = j
            case = radius_case(GC.load_case(Path(path)), damage, on_spot)
            return evaluate(case, spec_of(RADIUS), b,
                            'synthetic' if on_spot or damage != 128 else
                            'captured (A_Explode)', RADIUS)
        if j[0] == 'bf':
            _, path, k, xi, yi, want = j
            case = bf_case(GC.load_case(Path(path)), k, xi, yi,
                           'behindFast k %d (%d, %d) %s' % (k, xi, yi, want))
            rs = evaluate(case, spec_of(BF), b, 'synthetic', BF)
            for r in rs:
                r['path'] = 'k %d %s: %s' % (k, want, r.get('path'))
            return rs
        if j[0] == 'shadow':
            case = face_shadow_case(GC.load_case(Path(j[1])))
            return evaluate(case, spec_of(FACE), b, 'synthetic', FACE)
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
    out: Dict[str, Any] = {}
    for r in results:
        e = out.setdefault(r.get('entry') or '?', {
            'runs': 0, 'failures': 0, 'kinds': {}, 'paths': {},
            'waiting': {}, 'cpu_cycles': [], 'clock': [], 'lowest_s': None,
            'strays': 0, 'first_failures': []})
        e['runs'] += 1
        k = r.get('kind')
        e['kinds'][k] = e['kinds'].get(k, 0) + 1
        p = r.get('path') or ''
        e['paths'][p] = e['paths'].get(p, 0) + 1
        if r.get('waiting'):
            e['waiting'][r['waiting']] = e['waiting'].get(r['waiting'],
                                                          0) + 1
        if not r.get('ok'):
            e['failures'] += 1
            if len(e['first_failures']) < 5:
                e['first_failures'].append({x: r.get(x) for x in (
                    'case', 'kind', 'path', 'ended', 'stop', 'error',
                    'diff', 'stray_first') if r.get(x)})
        if k != 'stop':
            e['cpu_cycles'].append(r.get('cpu_cycles'))
            e['clock'].append(r.get('clock'))
        s = r.get('lowest_s')
        if s is not None:
            e['lowest_s'] = s if e['lowest_s'] is None else \
                min(e['lowest_s'], s)
        e['strays'] += r.get('strays') or 0
    for e in out.values():
        e['cpu_cycles'] = MSP._stats(e['cpu_cycles'])
        e['clock'] = MSP._stats(e['clock'])
    return out


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

LK = 'game/%s/look.s' % PART
RA = 'game/%s/radius.s' % PART
PLANTS = {
    # behindFast's 90 degree edge on the other side: v = T tells
    'bf-edge': ([(LK, """        cmp GT_4
        beq bf_no
        bcc bf_no""", """        cmp GT_4
        bcc bf_no""")], [BF]),
    # the shadow's P_Random shift: << 4, not << 5 (upstream's << 21)
    'shadow-shift': ([(LK, """        ldx #5                  ; v << 5""",
                       """        ldx #4                  ; v << 5""")],
                     [FACE]),
    # the radius damage's distance not clamped at 0
    'no-clamp': ([(RA, """        bpl :+
        stz LK_BDIST
        stz LK_BDIST+1""", """        bra :+
        stz LK_BDIST
        stz LK_BDIST+1""")], [RADIUS]),
}


def run_plant(name: str, jobs: int = 2, say=None) -> Dict[str, Any]:
    bugs, entries = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-look-plant-', dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', bugs)
        res = run_jobs(plan(True, entries), obj, jobs)
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
    out['wave'] = 3
    out['build_kb'] = MSP.du_kb(OUT)
    out['notes'] = [
        'lean checkpoint (the owner, 2026-10-02): at most 40 calls a '
        'routine, the $A5 machine only, the f121 profile only',
        'cpu_cycles: the W65C02S cycles from call_entry to the return '
        '(routine mode, the slots empty at the call); clock: fabric clocks',
        'stop: a call that reaches an unbuilt action stops at its DCALL; '
        '"action removed": its variant with that state\'s action removed '
        'on both sides, compared whole',
        'P_RadiusAttack: no demo calls it by JSL; A_Explode jumps to it '
        '(demo2, 3 barrels): its cases are the reference\'s P_RadiusAttack '
        'by --call on those states with A_Explode\'s arguments']
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
            for got in pool.map(log, runs):
                pass
    if args.capture:
        capture(args.jobs)
    if args.check:
        rep = check(args.jobs, [e for e in args.entries.split(',') if e]
                    or None)
        if not args.entries:
            write_report(rep)
        for k, e in sorted(rep['entries'].items()):
            print('%-32s %4d runs %3d failed  cycles %s  S %s  paths %s'
                  % (k, e['runs'], e['failures'], e['cpu_cycles'],
                     e['lowest_s'], e['paths']))
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
