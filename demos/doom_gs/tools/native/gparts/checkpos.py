#!/usr/bin/env python3
"""Part checkpos's checkpoint (milestone 10, docs/GAME.md 2.4 row
checkpos, 3.5; docs/game-parts/checkpos.md): routine mode on the part's
two entries (P_CheckPosition, and checkPos as P_TryMove calls it), and its
planted bugs.

Usage:  python3 tools/native/gparts/checkpos.py --capture [--jobs 2]
        python3 tools/native/gparts/checkpos.py --check [--jobs 2]
                [--sample K] [--fills a5] [--profiles f121,fastpath]
        python3 tools/native/gparts/checkpos.py --plants [--keys NAME,...]
        python3 tools/native/gparts/checkpos.py --eligible
        python3 tools/native/gparts/checkpos.py --report

Everything it writes is under build/native/game/checkpos/ (the part's own
directory): the cases (cases/RUN/ROUTINE/hNNNNNNNN.case.z, each run's
base.ram.z: tools/native/gamecap.py with its case directory pointed here),
the candidates' paths (paths.json), report.json. The shared outputs are
read only.

The checks are lean (the owner's request of 2026-10-02): at most CHOSEN
(40) captured calls an entry, chosen to take as many paths as the
candidates take (a greedy cover of the paths, then spread evenly), from
the $A5 machine only, under f121 and fastpath.

--capture: the candidates. P_CheckPosition (P_ThingHeightClip's calls):
evenly over demo3 and demo2. checkPos (P_TryMove's): evenly over demo3,
and every call in the first tics of demo3's, DEMO1's and DEMO2's where
PIT_CheckThing ran (missiles and pickups). Each candidate's path comes
from the reference alone (paths()): fits or blocked (by a thing or a
line), MP_TRY, MF_NOCLIP, PIT_CheckThing ran (MP_CLOB), tmthing a
missile or the player, special lines (numspechit), the line record (its
lines, too many, none), ceilingline, the walk over more than one column
and row.

--check: the chosen calls (every sample-th), on the part's image
(make -f game.mk part P=checkpos), with part secfind's run machinery
(secfind.Prep, Native, check_writes: the reference's states, the
native pre-state through the port writer, the write log): the canonical
state after the call equal to ref816's (gcanon's routine mode, R1-R7),
every declared output of src/native/game/checkpos/args.json equal (the
result; tmfloorz, tmceilingz, tmdropoffz in GW; numspechit and the
spechit lines it counts; the line record), no stray write. A call that
reaches a routine of a part not in the image stops at its FCALL or DCALL
(GS_UNBUILT, GS_UNBUILTD): it is "waiting", never counted equal.

--plants: each planted bug built from a scratch copy of the part's
sources in a temporary directory (deleted), run on its check (the chosen
calls, $A5, f121), which must fail.
"""

import argparse
import json
import shutil
import subprocess
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

import secfind as SF  # noqa: E402  (wave 1's run machinery)
import mobjstate as MS  # noqa: E402  (its native checks)
from bridge.port import PortReader  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL  # noqa: E402
from ref816 import calls as CL  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'checkpos'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
PATHS_FILE = OUT / 'paths.json'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
PART_SRC = SRC / 'game' / PART
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory

CHECKPOSITION = 'p_map65.s:P_CheckPosition'
CHECKPOS = 'p_map65.s:checkPos'
CHECKTHING = 'p_map65.s:checkThing'
ENTRIES = (CHECKPOSITION, CHECKPOS)
CHOSEN = 40                     # the lean checks: calls an entry
FILLS = (0xA5,)                 # the lean checks: one machine
PROFILES = SF.PROFILES
RUN_CYCLES = SF.RUN_CYCLES
BATCH = 40
EVEN = {CHECKPOSITION: (('demo3', 40), ('demo2', 20)),
        CHECKPOS: (('demo3', 60),)}
THING_TICS = {'demo3': 6, 'demo1': 6, 'demo2': 6}   # tics with checkThing
THING_TIC_CALLS = 8             # checkPos calls kept in each such tic


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


# ---------------------------------------------------------------------------
# What the part needs of build/; its image
# ---------------------------------------------------------------------------

def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC) -> Path:
    """The part's test image (make -f game.mk part P=checkpos); its
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
    return d['entries']


# ---------------------------------------------------------------------------
# The calls: eligibility (GAME.md 3.5 step 6), candidates, captures
# ---------------------------------------------------------------------------

def built() -> Set[str]:
    return set(GL.built_set(extra=[PART]))


def eligible_calls(key: str, runs: Sequence[str] = GC.RUNS
                   ) -> Tuple[List[Tuple[str, int, int]], Dict[str, int]]:
    """The eligible calls of an entry over the survey's runs, (run, hit,
    tic), and the waiting ones by the target they wait for."""
    ok_parts = built()
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
                    if GL.owner_of(targets[i]) not in ('core',) and
                    GL.owner_of(targets[i]) not in ok_parts]
            for m in miss:
                waiting[m] = waiting.get(m, 0) + 1
            if not miss:
                out.append((run, hit, r['tic'][hit - 1]))
    return out, waiting


def spread(items: Sequence[Any], n: int) -> List[Any]:
    if len(items) <= n:
        return list(items)
    return [items[(2 * k + 1) * len(items) // (2 * n)] for k in range(n)]


def candidates(key: str) -> Dict[str, List[Tuple[int, int]]]:
    """run -> [(hit, tic)] of the entry's candidates (see the module's
    text)."""
    out: Dict[str, Dict[int, int]] = {}
    for run, n in EVEN.get(key, ()):
        calls = eligible_calls(key, (run,))[0]
        for _, hit, tic in spread(calls, n):
            out.setdefault(run, {})[hit] = tic
    if key == CHECKPOS:
        for run, ntics in THING_TICS.items():
            sv = GC.survey_of(run)
            if not sv or CHECKTHING not in sv['routines']:
                continue
            tics = []
            for t in sv['routines'][CHECKTHING]['tic']:
                if t not in tics:
                    tics.append(t)
            tics = spread(tics, ntics)
            calls = eligible_calls(key, (run,))[0]
            for t in tics:
                for _, hit, tic in [c for c in calls
                                    if c[2] == t][:THING_TIC_CALLS]:
                    out.setdefault(run, {})[hit] = tic
    return {r: sorted(d.items()) for r, d in out.items()}


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, key) / ('h%08d.case.z' % hit)


def capture(keys: Sequence[str] = ENTRIES, batch: int = BATCH) -> int:
    made = 0
    for key in keys:
        for run, calls in sorted(candidates(key).items()):
            todo = [h for h, _ in calls
                    if not case_path(run, key, h).exists()]
            if not todo:
                continue
            sv = GC.survey_of(run)
            tics = sv['routines'][key]['tic']
            start = time.time()
            got = GC.capture(run, key, todo, tics, batch=batch, say=say)
            made += len(got)
            say('%s %s: %d cases (%.0f s)' % (run, key, len(got),
                                              time.time() - start))
    return made


def captured(key: str) -> List[Tuple[str, int, Path]]:
    out = []
    for run, calls in sorted(candidates(key).items()):
        for hit, _ in calls:
            p = case_path(run, key, hit)
            if p.exists():
                out.append((run, hit, p))
    return out


# ---------------------------------------------------------------------------
# A call's path, from the reference's memory alone (the coverage, GAME.md
# 3.5 step 2)
# ---------------------------------------------------------------------------

_TABLE: List[Any] = []


def table() -> CL.Linkmap:
    if not _TABLE:
        _TABLE.append(CL.Linkmap())
    return _TABLE[0]


def sym(name: str) -> int:
    return table().address(name) & 0xFFFFFF


def path_of(case: GC.Case) -> List[str]:
    """The paths a call took: its result, how it ended, what it met."""
    uc = SF.uconst()
    e, a = case.entry, case.after
    key = case.key

    def u16(m, name: str, off: int = 0) -> int:
        return m.read(sym(name) + off, 2)[0] | m.read(sym(name) + off,
                                                       2)[1] << 8

    def u8(m, name: str) -> int:
        return m.read(sym(name), 1)[0]
    if key == CHECKPOS:
        fits = case.regs_out['p'] & 1
        try_ = u16(e, 'p_map65.s:MP_TRY') & 0xFF
    else:
        fits = case.regs_out['a'] & 1
        try_ = 0
    tm = int.from_bytes(a.read(sym('p_map65.s:tmthing'), 3), 'little')
    flags = int.from_bytes(a.read(tm + uc['UO_MO_FLAGS'], 4), 'little')
    out = ['fits' if fits else 'blocked', 'try' if try_ else 'notry']
    if flags & uc['UC_MF_NOCLIP']:
        out.append('noclip')
        return out
    if flags & (uc['UC_MF_MISSILE_HI'] << 16):
        out.append('missile')
    if flags & uc['UC_MF_PICKUP_LO']:
        out.append('pickup')
    if u16(a, 'p_map65.s:MP_CLOB') & 0xFF:
        out.append('checkthing')
    lrn_in, lrn = u8(e, 'p_map65.s:LR_N'), u8(a, 'p_map65.s:LR_N')
    lines_in = e.read(sym('p_map65.s:LR_LINES'), 48)
    lines = a.read(sym('p_map65.s:LR_LINES'), 48)
    walked = (lrn != lrn_in or lines != lines_in or
              u16(a, 'p_map65.s:LR_OK') != u16(e, 'p_map65.s:LR_OK'))
    if not fits:
        out.append('line-block' if walked and lrn else 'thing-block')
    if lrn == 0xFF:
        out.append('lr-many')
    elif walked and lrn:
        out.append('lr-%d' % min(lrn // 2, 6))
    n = u16(a, '_g_numspechit')
    if n:
        out.append('spechit-%d' % n)
    if int.from_bytes(a.read(sym('_g_ceilingline'), 3), 'little'):
        out.append('ceilingline')
    # the box's blocks: more than one column and row (the walk's order)
    box = [int.from_bytes(a.read(sym('_g_tmbbox') + 4 * k, 4), 'little',
                          signed=True) >> 16 for k in range(4)]
    orgx = u16(a, '_g_bmaporgx', 2)
    orgy = u16(a, '_g_bmaporgy', 2)
    t, b, l_, r = (box[uc['UC_BOXTOP']], box[uc['UC_BOXBOTTOM']],
                   box[uc['UC_BOXLEFT']], box[uc['UC_BOXRIGHT']])
    cols = ((r - orgx) >> 7) - ((l_ - orgx) >> 7)
    rows = ((t - orgy) >> 7) - ((b - orgy) >> 7)
    if cols and rows:
        out.append('blocks-2x2')
    return out


def _path_job(item: Tuple[str, str]) -> Tuple[str, List[str]]:
    key, path = item
    try:
        return path, path_of(GC.load_case(Path(path)))
    except Exception as error:      # reported, never hidden
        return path, ['error: %s: %s' % (type(error).__name__, error)]


def paths(jobs: int = 2) -> Dict[str, Dict[str, List[str]]]:
    """key -> case path -> its paths (kept in paths.json)."""
    old = json.loads(PATHS_FILE.read_text()) if PATHS_FILE.exists() else {}
    out: Dict[str, Dict[str, List[str]]] = {}
    new = False
    for key in ENTRIES:
        have = old.get(key, {})
        todo = [(key, str(p)) for _, _, p in captured(key)
                if str(p) not in have]
        got = dict(have)
        new = new or bool(todo)
        if todo:
            if jobs <= 1:
                got.update(map(_path_job, todo))
            else:
                with ProcessPoolExecutor(max_workers=jobs) as pool:
                    got.update(pool.map(_path_job, todo))
        out[key] = got
    if new or not PATHS_FILE.exists():
        PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PATHS_FILE.write_text(json.dumps(out, indent=1, sort_keys=True) +
                              '\n')
    return out


def selection(key: str, ps: Optional[Dict[str, Dict[str, List[str]]]] = None,
              n: int = CHOSEN) -> List[str]:
    """CHOSEN cases of the entry: a greedy cover of the candidates' paths
    (each new pick the case with the most paths not yet taken), then
    spread evenly over the rest."""
    ps = ps if ps is not None else paths()
    cand = {p: set(v) for p, v in ps.get(key, {}).items()
            if not any(x.startswith('error') for x in v)}
    order = sorted(cand)
    chosen: List[str] = []
    seen: Set[str] = set()
    while len(chosen) < n:
        best = max(order, key=lambda p: (len(cand[p] - seen), -order.index(
            p)) if p not in chosen else (-1, 0), default=None)
        if best is None or best in chosen or not cand[best] - seen:
            break
        chosen.append(best)
        seen |= cand[best]
    rest = [p for p in order if p not in chosen]
    chosen += spread(rest, n - len(chosen))
    return sorted(chosen)


# ---------------------------------------------------------------------------
# The synthetic calls: things at block corners where the walk's order shows
# (as milestone 9's secorder.py): P_CheckPosition of a captured call's
# thing moved (x in X:C, y in _Dp[4-7]) to just past a corner of four
# blocks whose two off-diagonal blocks both list lines, its radius made
# CORNER_RADIUS so that its box takes the four blocks; ref816 --call of
# upstream's routine on that memory gives the reference
# ---------------------------------------------------------------------------

SYN_FILE = OUT / 'synthetic.json'
CORNER_RADIUS = 48
CORNERS = 10                    # corners a base
CORNER_BASES = (('demo3', 0), ('demo2', 0))  # (run, the base's index)


def _block_lines(mem, uc) -> Tuple[int, int, int, int, List[int]]:
    """(width, height, orgx, orgy, lines of each block) of the level in
    upstream's memory."""
    w = mem.u16(sym('_g_bmapwidth'))
    h = mem.u16(sym('_g_bmapheight'))
    orgx = mem.u16(sym('_g_bmaporgx') + 2)
    orgy = mem.u16(sym('_g_bmaporgy') + 2)
    lump = int.from_bytes(mem.read(sym('_g_blockmaplump'), 3), 'little')
    bmap = int.from_bytes(mem.read(sym('_g_blockmap'), 3), 'little')
    counts = []
    for b in range(w * h):
        off = mem.u16(bmap + 2 * b)
        a = lump + 2 * off + 2
        n = 0
        while not mem.u16(a) & 0x8000 and n < 400:
            n += 1
            a += 2
        counts.append(n)
    return w, h, orgx, orgy, counts


def corner_plan() -> List[Dict[str, Any]]:
    """The synthetic calls: base case, x, y (whole units), radius."""
    uc = SF.uconst()
    out = []
    caps = captured(CHECKPOSITION)
    for run, k in CORNER_BASES:
        bases = [p for r, _, p in caps if r == run]
        if not bases:
            continue
        base = bases[k]
        case = GC.load_case(base)
        w, h, orgx, orgy, n = _block_lines(case.entry, uc)
        good = [(i, j) for j in range(1, h) for i in range(1, w)
                if n[j * w + i - 1] >= 2 and n[(j - 1) * w + i] >= 2]
        for i, j in spread(good, CORNERS):
            out.append({'base': str(base), 'x': orgx + 128 * i + 3,
                        'y': orgy + 128 * j + 5, 'radius': CORNER_RADIUS,
                        'note': 'corner %s (%d, %d)' % (run, i, j)})
    return out


def synthetic_plan() -> List[Dict[str, Any]]:
    if not SYN_FILE.exists():
        SYN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SYN_FILE.write_text(json.dumps(corner_plan(), indent=1) + '\n')
    return json.loads(SYN_FILE.read_text())


def corner_case(rec: Dict[str, Any]) -> GC.Case:
    """A synthetic call's case: the base's entry memory with the thing's
    radius and y poked, x in X:C, upstream's P_CheckPosition run alone."""
    uc = SF.uconst()
    base = GC.load_case(Path(rec['base']))
    t = table()
    dp = (base.regs_in['d'] + t.address('_Dp') - t.direct_page) & 0xFFFF
    thing = int.from_bytes(base.entry.read(dp, 3), 'little')
    entry = base.entry.copy()
    entry.header = base.entry.header
    entry.write(dp + 4, (rec['y'] << 16 & 0xFFFFFFFF).to_bytes(4, 'little'))
    entry.write(thing + uc['UO_MO_RADIUS'],
                (rec['radius'] << 16).to_bytes(4, 'little'))
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-checkpos-call-',
                                 dir=str(BUILD)))
    try:
        (work / 'entry.img').write_bytes(entry.image_bytes())
        call, writes = SF.ref_call(sym(CHECKPOSITION), [],
                                   {'a': 0, 'x': rec['x'] & 0xFFFF}, work)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    after = entry.copy()
    for a, d in writes:
        after.write(a, d)
    header = dict(base.header, note=rec['note'], call=call,
                  writes=GC._ranges(writes), hit=0)
    return GC.Case(header, entry, after, None)


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def place(nat: 'SF.Native', name: str) -> int:
    """A native place of args.json: zp:, main: (the globals block), gw:
    (glayout's tic GW fields: the shared GM_TM* of request R1, wave 3 as
    integrated), cp: (a label of the part's image)."""
    kind, _, n = name.partition(':')
    if kind == 'zp':
        return GR.zp_address(n)
    if kind == 'main':
        return LL.G[n]
    if kind == 'gw':
        return GL.TGW[n]
    if kind == 'cp':
        return nat.b.labels[n]
    raise PartError('a native place %r' % name)


class Prep(SF.Prep):
    """secfind's Prep with the part's destinations (gw:, cp:)."""

    nat: Optional['SF.Native'] = None

    def inputs(self) -> Tuple[List[int], List[Tuple[int, bytes]]]:
        regs = [0, 0, 0, 0x34]
        pokes: List[Tuple[int, bytes]] = []
        for item in self.spec.get('in', []):
            data = self.ref.source(item['from'])
            kind = item.get('as')
            if kind:
                r = self.ref.ref(int.from_bytes(data, 'little'),
                                 SF.kinds_of(kind))
                data = SF.native_value(self.mf, kind, r).to_bytes(2,
                                                                  'little')
            to = item['to']
            n = item.get('bytes', len(data))
            if to in ('a', 'x', 'y'):
                regs['axy'.index(to)] = data[0]
            elif to == 'ax':
                regs[0], regs[1] = data[0], data[1]
            else:
                pokes.append((place(self.nat, to), data[:n].ljust(n, b'\0')))
        return regs, pokes


def outputs(prep: Prep, nat: 'SF.Native', m) -> List[str]:
    """The declared outputs against upstream's: registers (a, c: the carry
    of dg_rp), places (place()), "as": "spechit" (the first numspechit
    lines of spechit against upstream's line pointers)."""
    lab = nat.b.labels
    regs = {'a': G.card_byte(m, lab['dg_ra']),
            'x': G.card_byte(m, lab['dg_rx']),
            'y': G.card_byte(m, lab['dg_ry']),
            'c': G.card_byte(m, lab['dg_rp']) & 1}
    up_c = prep.case.regs_out['p'] & 1
    out = []
    for item in prep.spec.get('out', []):
        nv = item['native']
        n = item.get('bytes', 2)
        if item.get('as') == 'spechit':
            count = int.from_bytes(prep.ref.source(item['count'], 'out'),
                                   'little')
            raw = prep.ref.source(item['upstream'], 'out')
            a = place(nat, nv)
            for k in range(min(count, 4)):
                ptr = int.from_bytes(raw[4 * k:4 * k + 3], 'little')
                want = SF.native_value(prep.mf, 'line', prep.ref.ref(
                    ptr, ('line',), 'out'))
                got = m.main[a + 2 * k] | m.main[a + 2 * k + 1] << 8
                if got != want:
                    out.append('output spechit[%d]: line %d, upstream %d' % (
                        k, got, want))
            continue
        if nv in regs:
            value = regs[nv]
        else:
            a = place(nat, nv)
            value = int.from_bytes(bytes(m.main[a:a + n]), 'little')
        if item['upstream'] == 'c':
            want = up_c
        elif item.get('as'):
            raw = prep.ref.source(item['upstream'], 'out')
            want = SF.native_value(prep.mf, item['as'], prep.ref.ref(
                int.from_bytes(raw, 'little'), SF.kinds_of(item['as']),
                'out'))
        else:
            want = int.from_bytes(prep.ref.source(item['upstream'], 'out'),
                                  'little')
        mask = (1 << (8 * n)) - 1
        if value & mask != want & mask:
            out.append('output %s (%s): %X, upstream %X' % (
                nv, item['upstream'], value & mask, want & mask))
    return out


WAITING = (GL.GS['UNBUILT'], GL.GS['UNBUILTD'])
# the writes beyond secfind's allowed ones (its check_writes): the
# native-only globals of the globals block (G_THLAST and the other derived
# state a pickup's removal changes: mobjstate.py's rule, then its
# native_checks on them) and the same-value write-backs of the sector
# nodes' records (ZONE1: P_DelSeclist through the API, as of the other
# record banks); in the aux banks, mobjstate.py's shared rule (the
# records of the game state's kinds: a removal's native-only thinker links)
NATIVE_MAIN = (LL.GBLOCK, GL.TIC_MAIN_END)
RECORD_BANKS = set(SF.RECORD_BANKS) | {LL.ZONE1}


def check_writes(log: Path, canon: Set[int], start: int,
                 header: Dict[str, Any]) -> 'SF.Writes':
    """secfind.check_writes with NATIVE_MAIN, RECORD_BANKS and
    mobjstate.allowed_aux."""
    aux = MS.allowed_aux(header)
    changed = 0
    stray: List[str] = []
    n = 0
    with open(str(log)) as handle:
        for line in handle:
            if not line.startswith('w '):
                continue
            f = line.split()
            storage = f[5]
            old, new = int(f[8], 16), int(f[9], 16)
            before = int(f[1]) < start
            if storage == 'main':
                off = int(f[7], 16)
                a = SF.bmem.MAIN | off
                if a in canon:
                    changed += old != new
                    continue
                if any(lo <= off < hi for lo, hi in SF.R1_MAIN) or \
                        NATIVE_MAIN[0] <= off < NATIVE_MAIN[1]:
                    continue
            elif storage == 'aux':
                bk, off = int(f[6]), int(f[7], 16)
                a = (bk << 16) | off
                if a in canon:
                    changed += old != new
                    continue
                if bk == LL.GTEST or (bk in RECORD_BANKS and old == new) or \
                        any(lo <= off < hi for lo, hi in aux.get(bk, ())):
                    continue
            if before:
                continue
            n += 1
            if len(stray) < 6:
                stray.append('%s %s %s %02X->%02X pc %s' % (
                    storage, f[6], f[7], old, new, f[3]))
    return SF.Writes(changed, stray, n)


def run_one(prep: Prep, nat: 'SF.Native', fill: int, profile: str
            ) -> Dict[str, Any]:
    """One run of a case (secfind.run_one's steps, this part's outputs):
    equal, the differences, the cycles from the routine's entry to its
    return, the lowest S, the strays; a stop at an unbuilt routine is
    "waiting"."""
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
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-checkpos-', dir=str(BUILD)))
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), events=events,
                  banks=list(prep.banks) + [LL.GTEST],
                  profile=profile, write_log=SF.LOG_RANGES, cycles=RUN_CYCLES)
        ended = r.ended()
        res['ended'] = ended
        res['lowest_s'] = r.state.get('lowest_s')
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                stop = G.stop_codes(G.load_snapshot(p))
                res['stop'] = stop
                if stop[0] in WAITING:
                    res['waiting'] = True
            return res
        c0, c1 = SF.snapshot_cycles(work, 'start'), \
            SF.snapshot_cycles(work, 'ret')
        res['cycles'] = c1 - c0 if c0 is not None and c1 is not None \
            else None
        if c0 is None:
            raise PartError('no snapshot at the routine\'s entry')
        w = check_writes(work / 'writes.log', canon, c0, prep.header)
        res['stray'] = w.strays
        res['stray_first'] = w.stray
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if w.canonical:
        from native import setupcheck as SC
        nat_state = PortReader(prep.mf).read(SC.port_memory(m))
    else:
        nat_state = pre
    diff = gcanon.compare(prep.ref.s_out, nat_state, 'routine')
    diff += outputs(prep, nat, m)
    diff += MS.native_checks(m)
    res['sounds'] = len(SF.sounds(m))
    if w.strays:
        diff.append('%d stray writes: %s' % (w.strays, w.stray))
    res['diff'] = diff[:12]
    res['ok'] = not diff
    return res


def _check_job(job) -> List[Dict[str, Any]]:
    items, obj, fills, profiles, ps = job
    nat = SF.Native(Path(obj))
    Prep.nat = nat
    spec_all = args()
    out: List[Dict[str, Any]] = []
    for key, path in items:
        try:
            if isinstance(path, dict):
                name = 'synthetic: ' + path['note']
                case = corner_case(path)
                ps = dict(ps, **{name: path_of(case)})
            else:
                name = '/'.join(Path(path).parts[-3:])
                case = GC.load_case(Path(path))
            prep = Prep(case, key, spec_all[key])
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
                r.update(case=name, path=ps.get(
                    name if isinstance(path, dict) else path, []))
                out.append(r)
    return out


def check_jobs(keys: Sequence[str] = ENTRIES, sample: int = 1,
               obj: Path = OUT, fills: Sequence[int] = FILLS,
               profiles: Sequence[str] = PROFILES, chunk: int = 6,
               synthetic: bool = True) -> List[Tuple]:
    ps = paths()
    jobs: List[Tuple] = []
    for key in keys:
        chosen: List[Any] = selection(key, ps)[::sample]
        if synthetic and key == CHECKPOSITION:
            chosen += synthetic_plan()[::sample]
        for i in range(0, len(chosen), chunk):
            jobs.append(([(key, p) for p in chosen[i:i + chunk]], str(obj),
                         tuple(fills), tuple(profiles), ps[key]))
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


def _stats(values: Sequence[int]) -> Dict[str, Any]:
    v = sorted(values)
    return {'median': v[len(v) // 2] if v else None,
            'worst': v[-1] if v else None}


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ENTRIES:
        rs = [r for r in results if r.get('entry') == key]
        if not rs:
            continue
        waiting = [r for r in rs if r.get('waiting')]
        run = [r for r in rs if not r.get('waiting')]
        bad = [r for r in run if not r.get('ok')]
        paths_: Set[str] = set()
        for r in run:
            paths_.update(r.get('path', []))
        ls = [r['lowest_s']['s'] for r in run
              if isinstance(r.get('lowest_s'), dict)]
        out[key] = {
            'cases_chosen': len({r['case'] for r in rs}),
            'cases_run': len({r['case'] for r in run}),
            'cases_waiting': sorted({r['case'] for r in waiting}),
            'runs': len(run), 'failures': len(bad),
            'stray_writes': sum(r.get('stray') or 0 for r in run),
            'cycles': {p: _stats([r['cycles'] for r in run
                                  if r.get('profile') == p and
                                  r.get('cycles')]) for p in PROFILES},
            'lowest_s': min(ls) if ls else None,
            'paths': sorted(paths_),
            'first_failures': [{k: r.get(k) for k in (
                'case', 'fill', 'profile', 'diff', 'error', 'ended', 'stop')}
                for r in bad[:4]]}
    return out


# ---------------------------------------------------------------------------
# The planted bugs (each in a scratch copy of the part's sources)
# ---------------------------------------------------------------------------

PLANT_EDITS: Dict[str, List[Tuple[str, str]]] = {
    'y-outer': [(
        '''@walk:  ROWBASE
        stz CP_WIN
@lcol:  COLUMN
''',
        '''@walk:  ROWBASE
        stz CP_WIN
        lda CP_BX                       ; (planted: y outer, x inner: the
        sta CP + 30                     ;   first x kept in CP + 30)
        lda CP_YL
        sta CP_BY
@lcol:  lda CP_ROW                      ; (planted) a row's first block
        sta CP_IDX
        lda CP_ROW+1
        sta CP_IDX+1
        lda CP + 30
        sta CP_BX
        clc
        lda CP_IDX
        adc CP_BX
        sta CP_IDX
        lda CP_IDX+1
        adc #0
        sta CP_IDX+1
'''), (
        '''@lnextblk:
        NEXTBLOCK @lcol, @lend
        jmp @lblk
''',
        '''@lnextblk:
        lda CP_BX                       ; (planted: x inner)
        cmp CP_XH
        beq :+
        inc CP_BX
        inc CP_IDX
        jne @lblk
        inc CP_IDX+1
        jmp @lblk
:       lda CP_BY
        cmp CP_YH
        jeq @lend
        inc CP_BY
        clc
        lda CP_ROW
        adc G_BMW
        sta CP_ROW
        lda CP_ROW+1
        adc #0
        sta CP_ROW+1
        jmp @lcol
''')],
    # the line record not kept: LR_OK never set at the walk's end
    'record-not-kept': [(
        '''@lend:  ldx #1                          ; the walk's end: its record (LR_N''',
        '''@lend:  ldx #0                          ; (planted) the walk's end: its record (LR_N''')],
    # the lines walked before the things
    'lines-first': [(
        '''@things:
        lda #$FF                        ; no radius yet''',
        '''@things:
        jsr @plines                     ; (planted: the lines first)
        jcc @false
        lda #$FF                        ; no radius yet'''), (
        ''':       sty CP_PLAY
        FCALL lineBlocks
        bcc @false
        lda #1
        rts
''',
        ''':       sty CP_PLAY
        lda #1                          ; (planted: walked already)
        sec
        rts
@plines:
        lda CP_TMTHING
        ldx CP_TMTHING+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #<UC_MF_MISSILE_HI
        sta CP_MISS
        ldy #0
        lda CP_TMTHING
        cmp G_PLAYER + PL_MO
        bne :+
        lda CP_TMTHING+1
        cmp G_PLAYER + PL_MO + 1
        bne :+
        iny
:       sty CP_PLAY
        FCALL lineBlocks
        rts
''')],
}
PLANT_NAMES = tuple(PLANT_EDITS)


def plant_build(name: str, tmp: Path) -> Path:
    """The part's image with the planted bug `name`, from a scratch copy of
    its sources in tmp (game.mk and its includes, the parts' fragments,
    this part's sources; the rest from the tree through game.mk's vpath):
    the image's directory."""
    src = tmp / 'src'
    files = list(G.PLANT_COPY) + ['game/%s/%s' % (PART, f) for f in
                                  ('part.mk', 'checkpos.s', 'checkpos.inc')]
    for f in files:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    target = src / 'game' / PART / 'checkpos.s'
    text = target.read_text()
    for old, new in PLANT_EDITS[name]:
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
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-checkpos-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            res = run_jobs(check_jobs(obj=obj, sample=sample,
                                      profiles=(PROFILES[0],)), workers)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        run = [r for r in res if not r.get('waiting')]
        bad = [r for r in run if not r.get('ok')]
        out[name] = {'runs': len(run), 'failed': len(bad),
                     'caught': bool(bad),
                     'first': (bad[0].get('diff') or [bad[0].get('error') or
                                                     bad[0].get('ended')])[:2]
                     if bad else None}
        say('%-16s %s' % (name, 'caught: %d of %d runs fail, %s' % (
            len(bad), len(run), out[name]['first']) if bad else
            'NOT CAUGHT (%d runs)' % len(run)))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)
LABELS = ('P_CheckPosition', 'cpCopy', 'setBox', 'walkRange', 'checkPos',
          'lineBlocks', 'checkThing')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (checkpos.o) against its budget; each routine's
    bytes (to the next of the part's routines in its segment) and group."""
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
            routines[n] = {'bytes': end - a, 'group': g, 'segment': seg}
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
               exclusions=[n for n, _, _ in gcanon.ROUTINE_EXCLUSIONS],
               fills=['%02x' % f for f in FILLS], profiles=list(PROFILES))
    if results is not None:
        rep['entries'] = summarize(results)
        run = [r for r in results if not r.get('waiting')]
        rep['runs'] = len(run)
        rep['waiting_runs'] = len(results) - len(run)
        rep['failures'] = sum(1 for r in run if not r.get('ok'))
        rep['stray_writes'] = sum(r.get('stray') or 0 for r in run)
        ls = [r['lowest_s']['s'] for r in run
              if isinstance(r.get('lowest_s'), dict)]
        rep['lowest_s'] = min(ls) if ls else None
    rep.update(parts)
    rep['build_kb'] = du_kb(OUT)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=1, default=str) + '\n')
    return rep


def print_report(rep: Dict[str, Any]) -> None:
    for key, e in rep.get('entries', {}).items():
        cyc = '; '.join('%s %s/%s' % (p, c['median'], c['worst'])
                        for p, c in e['cycles'].items())
        say('%-28s %2d cases (%d waiting) %3d runs %d failed %d stray, '
            'S %s; cycles %s' % (key, e['cases_run'],
                                 len(e['cases_waiting']), e['runs'],
                                 e['failures'], e['stray_writes'],
                                 e['lowest_s'], cyc))
        say('    paths: %s' % ', '.join(e['paths']))
        for f in e['first_failures']:
            say('    FAILED %s' % f)
    if 'sizes' in rep:
        sz = rep['sizes']
        say('bytes %d of %d (upstream %d)' % (sz['bytes'], sz['budget'],
                                             sz['upstream']))
    for name, r in rep.get('plants', {}).items():
        say('planted %-16s %s' % (name, 'caught' if r['caught'] else
                                  'NOT CAUGHT'))


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--eligible', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--keys', default=None)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--json', type=Path)
    a = parser.parse_args(argv)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if a.eligible:
        for key in ENTRIES:
            elig, waiting = eligible_calls(key)
            say('%-28s eligible %d, waiting %s' % (key, len(elig), waiting))
        return 0
    if a.capture:
        n = capture(a.keys.split(',') if a.keys else ENTRIES)
        say('%d cases made' % n)
        ps = paths(a.jobs)
        for key, d in ps.items():
            count: Dict[str, int] = {}
            for v in d.values():
                for x in v:
                    count[x] = count.get(x, 0) + 1
            say('%s: %d candidates, %s' % (key, len(d), json.dumps(
                count, sort_keys=True)))
        return 0
    if a.check:
        start = time.time()
        build()
        res = run_jobs(check_jobs(sample=a.sample), a.jobs)
        rep = write_report(res, sizes=sizes(), check_seconds=round(
            time.time() - start), sample=a.sample)
        if a.json:
            a.json.write_text(json.dumps(res, indent=1, default=str) + '\n')
        print_report(rep)
        return 1 if rep['failures'] else 0
    if a.plants:
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
