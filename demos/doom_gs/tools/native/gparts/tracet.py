#!/usr/bin/env python3
"""Part tracet's checkpoint (milestone 10, docs/GAME.md 1.9, 2.4 row
tracet, 3.5): a sample of the captured calls of its entries (traceLines,
traceThings, sideSetup, longTrace: the block steps of P_PathTraverse and
their setup), run natively and compared with ref816's, the evidence that
no release call writes the dead guard's state (3.5 R4), the planted bugs
and report.json.

Usage:  python3 tools/native/gparts/tracet.py --select
        python3 tools/native/gparts/tracet.py --capture
        python3 tools/native/gparts/tracet.py --synth
        python3 tools/native/gparts/tracet.py --run [--entries ...]
                                             [--limit N] [--obj DIR]
        python3 tools/native/gparts/tracet.py --guard
        python3 tools/native/gparts/tracet.py --plants
        python3 tools/native/gparts/tracet.py --report
        python3 tools/native/gparts/tracet.py --all

The lean checkpoint (the owner's request of 2026-10-02): at most SAMPLE
(40) calls an entry, spread evenly over the survey's runs (demo3, demo1,
demo2, newgame, tour), from one poisoned machine ($A5) under f121. The
coverage of upstream's branches comes from a model of each routine on the
case's own inputs (paths_of: SIDE1 step by step, the walks' lists read
from the case's memory); report.json lists the branches no sampled call
takes.

Everything it writes is under build/native/game/tracet/ (the part's
directory, GAME.md 2.5): its cases (cases/RUN/NAME/, gamecap.py's format
against a base of its own a run; the synthetic ones in cases/synth/),
select.json, run.json, guard.json, plants.json, report.json; temporary
files in build/tmp-tracet-* directories (--synth: geom_check's
call_synth, build/tmp-geom-call-*), deleted after each step.

--synth makes the synthetic cases (synth_specs): a sampled case's state
with pokes, the calls run alone on ref816 (--call); a new trace goes
through upstream's sideSetup first. traceLines through a line's vertex
(both axes) and along a slanted line (SIDE1 cannot tell: vtxSlowR), and
with the list full; traceThings with VT_RR 0 (the slow sides) and with
the list full; sideSetup's edges; longTrace's dx below -16 units.

A case runs on the part's test image (make -f game.mk part P=tracet): the
map's level base, the case's entry state through the manifest
(gameroutine's method, part tracel's run harness), with this part's
args.json. Beyond tracel's forms ("trace", "list"), the form "sides":
upstream's SIDE1 constants (VT_RR, VT_P1, VT_P2, VT_CV, VT_CT, VT_OXC,
VT_OYC, VT_SGN, VT_DYF and the axis of the pair vsPatch wrote) to the
native scratch block (TT_*), compared exactly after the call. Compared
besides: the canonical state (gcanon's routine mode, R1-R7 only: the
lines' validcount stamps among it), the return value, no stray write; the
lowest S and the time.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from bridge.port import PortReader, PortWriter  # noqa: E402
from native import gamecap as GC, gcanon, glayout as GL, grun as G, \
    llayout as LL  # noqa: E402
from native import gameroutine as GR  # noqa: E402
from ref816 import bounded, title  # noqa: E402
import geom_check as GK  # noqa: E402
import tracel as TLM  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'tracet'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
ARGS = SRC / 'game' / PART / 'args.json'
IMAGE = 'ptest'
FILL = 0xA5
PROFILE = 'f121'
JOBS = 2
MIN_FREE = 20 * 10 ** 9
SAMPLE = 40
CAPTURE_BATCH = 250
UPSTREAM_DP = 0x900

ENTRIES = ['p_trace65.s:traceLines', 'p_trace65.s:traceThings',
           'p_trace65.s:sideSetup', 'p_trace65.s:longTrace']
ROUTINES = [k for p in GL.PARTS if p['name'] == PART for k in p['routines']]
HELPERS = [k for p in GL.PARTS if p['name'] == PART for k in p['helpers']]
# the part's routines and helpers that have no native code (request R1):
# upstream's patched templates and their patchers are data here, thFastL a
# long-call wrapper
NO_CODE = ('p_trace65.s:ptT1', 'p_trace65.s:ptT2', 'p_trace65.s:vsPatch',
           'p_trace65.s:ptPatch', 'p_trace65.s:thFastL', 'p_trace65.s:tlP1',
           'p_trace65.s:tlP2', 'p_trace65.s:thP', 'p_trace65.s:gtP1',
           'p_trace65.s:gtP2')

M16 = 0xFFFF
MM_B3F = TLM.MM_B3F
VT = {'p1': MM_B3F + 0xF400, 'p2': MM_B3F + 0xF402, 'cv': MM_B3F + 0xF404,
      'ct': MM_B3F + 0xF406, 'oxc': MM_B3F + 0xF408,
      'oyc': MM_B3F + 0xF40A}
VT_SGN = MM_B3F + 0xF40C
VT_DYF = MM_B3F + 0xF410
VT_INVB = MM_B3F + 0xF412
BMROW = MM_B3F + 0x6000
# vsPatch's pairs (p_trace65.s:1806-1815): txa, sty (x) and tya, stx (y)
PAIR = {0x848A: 0, 0x8698: 4}
VRN, VJ, VBV, VBTH, VBTL = 2040, 23, 5, 21, 13
UC = GK.UC

# the dead guard's state (GAME.md 3.5 R4) and its places in upstream
MM_GSTAMP, MM_VIEWSAVE, MM_GW_TAB, GW_MAXB = 0x228000, 0x229000, \
    0x0B0000, 3276
GUARD_SYMBOLS = ('G_ID', 'GW_TAG', 'G_N', 'G_OFS', 'G_MX', 'G_MY',
                 'G_XI', 'G_YI', 'G_COUNT', 'G_PREV', 'PT_OK')


class CheckError(Exception):
    pass


def check_disk() -> None:
    st = os.statvfs(str(BUILD))
    if st.f_bavail * st.f_frsize < MIN_FREE:
        raise CheckError('less than 20 GB free: stop')


def tmpdir(tag: str) -> Path:
    return Path(tempfile.mkdtemp(prefix='tmp-tracet-%s-' % tag,
                                 dir=str(BUILD)))


def addr(sym: str) -> int:
    return TLM.addr(sym)


@contextmanager
def own_cases() -> Iterator[None]:
    saved = GC.CASES, GC._BASES
    GC.CASES, GC._BASES = CASES, {}
    try:
        yield
    finally:
        GC.CASES, GC._BASES = saved


def native_name(key: str) -> str:
    return GL.native_names().get(key, key.replace(':', '_'))


def case_file(run: str, key: str, hit: int) -> Path:
    return CASES / run / native_name(key) / ('h%08d.case.z' % hit)


SYNTH = CASES / 'synth'


def synth_paths(key: str) -> List[Path]:
    d = SYNTH / native_name(key)
    return sorted(d.glob('s*.case.z')) if d.exists() else []


def load_case(path: Path) -> GC.Case:
    with own_cases():
        return GC.load_case(path)


# ---------------------------------------------------------------------------
# Selection: SAMPLE calls an entry, spread over every run
# ---------------------------------------------------------------------------

def survey_calls(key: str) -> List[Tuple[str, int, int]]:
    """Every call of key in the survey's runs: (run, hit, tic), the last
    call of each run left out. No entry of the part dispatches: every
    call is eligible."""
    out = []
    for run in GC.RUNS:
        sv = GC.survey_of(run)
        if sv is None:
            continue
        r = sv['routines'].get(key)
        if r is None or not r['calls']:
            continue
        if r.get('reached'):
            raise CheckError('%s %s reached a dispatch target' % (run, key))
        for hit in range(1, r['calls']):
            out.append((run, hit, r['tic'][hit - 1]))
    return out


# sideSetup and longTrace (one call each a trace): half of the sample from
# the tics in which traceLines runs (the long traces with the fast sides,
# which only those calls set up), half spread over all
FAST_HALF = ('p_trace65.s:sideSetup', 'p_trace65.s:longTrace')


def select(n: int = SAMPLE) -> Dict[str, Any]:
    out: Dict[str, Any] = {'format': 'tracet-select 1', 'sample': n,
                           'entries': {}}
    fast_tics = {(run, tic) for run, _, tic in
                 survey_calls('p_trace65.s:traceLines')}
    for key in ENTRIES:
        calls = survey_calls(key)
        if key in FAST_HALF:
            fast = [c for c in calls if (c[0], c[2]) in fast_tics]
            chosen = TLM.spread(fast, n // 2)
            rest = [c for c in calls if c not in set(chosen)]
            chosen = sorted(set(chosen) | set(TLM.spread(rest, n - len(
                chosen))), key=lambda c: (GC.RUNS.index(c[0]), c[1]))
        else:
            chosen = TLM.spread(calls, n)
        e: Dict[str, List[List[int]]] = {}
        for run, hit, tic in chosen:
            e.setdefault(run, []).append([hit, tic])
        out['entries'][key] = {'calls': len(calls), 'eligible': len(calls),
                               'chosen': e}
    return out


def load_select() -> Dict[str, Any]:
    p = OUT / 'select.json'
    if not p.exists():
        raise CheckError('no %s: run tracet.py --select' % p)
    return json.loads(p.read_text())


def _capture_job(job: Tuple[str, str, List[int]]) -> str:
    run, key, hits = job
    check_disk()
    sv = GC.survey_of(run)
    tics = sv['routines'][key]['tic'] if sv else None
    with own_cases():
        made = GC.capture(run, key, hits, tics, batch=CAPTURE_BATCH,
                          say=lambda *a: None)
    return '%s %s: %d cases made' % (run, key, len(made))


def capture(jobs: int = JOBS, say=print) -> None:
    sel = load_select()
    work = []
    for key, e in sel['entries'].items():
        for run, calls in e['chosen'].items():
            todo = [h for h, _ in calls if not case_file(run, key,
                                                         h).exists()]
            if todo:
                work.append((run, key, todo))
    firsts: Dict[str, Any] = {}
    for w in work:
        firsts.setdefault(w[0], w)
    first = list(firsts.values())
    rest = [w for w in work if w not in first]
    for group in (first, rest):     # (each run's base made once)
        if not group:
            continue
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for msg in pool.map(_capture_job, group):
                say(msg, flush=True)


def chosen_paths(key: str, sel: Dict[str, Any]) -> List[Path]:
    e = sel['entries'].get(key, {'chosen': {}})
    out = []
    for run, calls in e['chosen'].items():
        for hit, _ in calls:
            p = case_file(run, key, hit)
            if p.exists():
                out.append(p)
    return out


# ---------------------------------------------------------------------------
# SIDE1's constants: upstream's, in the native form
# ---------------------------------------------------------------------------

def up_sides(mem) -> Dict[str, Any]:
    rr = mem.u16(addr('VT_RR'))
    out: Dict[str, Any] = {'rr': 1 if rr else 0,
                           'ax': PAIR.get(rr) if rr else None}
    if rr and rr not in PAIR:
        raise CheckError('VT_RR $%04X is no pair of vsPatch' % rr)
    for k, a in VT.items():
        out[k] = mem.u16(a)
    out['sgn'] = mem.u16(VT_SGN) >> 8
    out['dyf'] = mem.u16(VT_DYF) >> 8
    return out


def nat_sides(b, m) -> Dict[str, Any]:
    lab = b.labels

    def w(name: str) -> int:
        return m.main[lab[name]] | m.main[lab[name] + 1] << 8
    return {'rr': 1 if m.main[lab['TT_RR']] else 0,
            'ax': m.main[lab['TT_AX']], 'p1': w('TT_P1'), 'p2': w('TT_P2'),
            'cv': w('TT_CV'), 'ct': w('TT_CT'), 'oxc': w('TT_OXC'),
            'oyc': w('TT_OYC'), 'sgn': m.main[lab['TT_SGN']],
            'dyf': m.main[lab['TT_DYF']]}


def sides_pokes(b, s: Dict[str, Any]) -> List[Tuple[int, bytes]]:
    lab = b.labels
    out = [(lab['TT_RR'], bytes([s['rr']])),
           (lab['TT_AX'], bytes([s['ax'] or 0])),
           (lab['TT_SGN'], bytes([s['sgn']])),
           (lab['TT_DYF'], bytes([s['dyf']]))]
    for k in VT:
        out.append((lab['TT_' + k.upper()], s[k].to_bytes(2, 'little')))
    return out


def compare_sides(want: Dict[str, Any], got: Dict[str, Any]) -> List[str]:
    out = []
    for k, v in want.items():
        if k == 'ax' and not want['rr']:
            continue
        if got[k] != v:
            out.append('sides %s: %s, upstream %s' % (k, got[k], v))
    return out


# ---------------------------------------------------------------------------
# A case on the native image (tracel.run_native's steps, with "sides")
# ---------------------------------------------------------------------------

def args() -> Dict[str, Any]:
    d = json.loads(ARGS.read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise CheckError('%s: not %s' % (ARGS, GR.ARGS_FORMAT))
    return d


def spec_of(key: str) -> Dict[str, Any]:
    return args()['entries'][key]


def run_native(case: GC.Case, spec: Dict[str, Any], b, fill: int,
               profile: Optional[str], pokes_native=()) -> Dict[str, Any]:
    up = GR.Upstream(case)
    res: Dict[str, Any] = {'case': case.path.name if case.path else
                           case.header.get('note'), 'routine': case.key,
                           'hit': case.header.get('hit'),
                           'fill': '%02x' % fill, 'profile': profile,
                           'ok': False}
    probs = up.r_in.problems + up.r_out.problems
    if probs:
        res['error'] = 'bridge: ' + '; '.join(probs[:3])
        return res
    if case.regs_in['d'] != UPSTREAM_DP:
        res['error'] = 'D $%04X' % case.regs_in['d']
        return res
    mf, header, banks = GR.manifest(up.gamemap)
    skip = gcanon.skips('routine', up.s_in)
    img = G.Image(b, fill, store=True)
    img.recs += GR.base_records(up.gamemap)
    pm = G.tracked_memory()
    PortWriter(mf).write(gcanon.strip(up.s_in, skip), pm)
    img.recs += G.port_records(pm)
    img.recs += GR.derived(pm, header)
    regs = [0, 0, 0, 0x34]
    for item in spec.get('in', []):
        src, to = item['from'], item['to']
        if src == 'trace':
            for a, d in TLM.trace_pokes(b, TLM.up_trace(case.entry)):
                img.main(a, d)
            continue
        if src == 'list':
            for a, d in TLM.list_pokes(TLM.up_list(up, mf, 'in'), b):
                img.main(a, d)
            continue
        if src == 'sides':
            for a, d in sides_pokes(b, up_sides(case.entry)):
                img.main(a, d)
            continue
        data = GK.convert_in(up, mf, item, GK.up_source(up, src, 'in'))
        n = item.get('bytes', len(data))
        data = data[:n].ljust(n, b'\0')
        if to in ('a', 'x', 'y'):
            regs['axy'.index(to)] = data[0]
        elif to.startswith(('zp:', 'main:')):
            img.main(GK.native_address(b, to.split(':', 1)[1]), data)
        else:
            raise CheckError('an input destination %r' % to)
    for address, data in pokes_native:
        img.main(address, data)
    work = tmpdir('run')
    try:
        r = GK.run_entry(img, work, spec['native'], regs=tuple(regs),
                         banks=list(banks) + [LL.GTEST], profile=profile,
                         write_log=GK.write_log_ranges())
        res['lowest_s'] = (r.state.get('lowest_s') or {}).get('s')
        ended = r.ended()
        res['ended'] = ended
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                res['stop'] = G.stop_codes(G.load_snapshot(p))
            return res
        m = G.load_snapshot(work / 'done.img')
        lines = GK.read_write_log(work / 'writes.log')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    win, t = GK.call_window(lines, b)
    if t is not None:
        res['clocks'], res['cycles'] = t
    res['writes'] = len(win)
    stray = GK.stray_writes(win, b, banks)
    res['stray'] = stray[:6]
    res['stray_n'] = len(stray)
    from native import setupcheck as SC
    nat = PortReader(mf).read(SC.port_memory(m))
    diff = gcanon.compare(up.s_out, nat, 'routine')
    plain = {'in': [], 'out': []}
    regs_n = GK.native_regs(b, m)
    for item in spec.get('out', []):
        nv, uv = item['native'], item['upstream']
        if nv == 'list':
            diff += TLM.compare_list(TLM.up_list(up, mf, 'out'),
                                     TLM.nat_list(b, m))
        elif nv == 'trace':
            diff += TLM.compare_trace(TLM.up_trace(case.after),
                                      TLM.nat_trace(b, m))
        elif nv == 'sides':
            diff += compare_sides(up_sides(case.after), nat_sides(b, m))
        elif item.get('as') == 'bool':
            got = regs_n['p'] & 1
            want = 1 if TLM.u(GK.up_source(up, uv, 'out')) else 0
            if got != want:
                diff.append('output %s: C %d, upstream %d' % (uv, got,
                                                               want))
            if regs_n['a'] != want:
                diff.append('output %s: A %d, upstream %d' % (
                    uv, regs_n['a'], want))
        else:
            plain['out'].append(item)
    diff += GK.compare_outputs(up, mf, plain, b, m, nat)
    res['diff'] = diff[:12]
    res['ok'] = not diff and not stray
    return res


# ---------------------------------------------------------------------------
# The paths: a model of upstream's routines on the case's inputs (for the
# coverage only; the truth is ref816's)
# ---------------------------------------------------------------------------

PATHS = {
    'p_trace65.s:traceLines': [
        'off-map', 'stamped', 'side-sign', 'side-fast', 'side-limit',
        'side-range', 'side-overflow', 'crossed', 'not-crossed', 'end',
        'full'],
    'p_trace65.s:traceThings': [
        'off-map', 'empty', 'fast-crossed', 'fast-not-crossed', 'unk-rr',
        'unk-radius', 'unk-overflow', 'unk-side', 'quadrant-pos',
        'quadrant-neg', 'slow-crossed', 'slow-not-crossed', 'end', 'full'],
    'p_trace65.s:sideSetup': [
        'lines', 'things', 'short', 'dx-0', 'dy-0', 'dx-large', 'sum-large',
        'oxc-overflow', 'oyc-overflow', 'axis-x', 'axis-y', 'sq-neg',
        'sq-pos', 'fraction-0', 'fraction'],
    'p_trace65.s:longTrace': ['dx-above', 'dy-above', 'dx-below',
                              'dy-below', 'short'],
}


def s16(v: int) -> int:
    v &= M16
    return v - 0x10000 if v & 0x8000 else v


def side1(xp: int, yp: int, sides: Dict[str, Any], thing: bool,
          paths: List[str]) -> Optional[int]:
    """SIDE1 (p_trace65.s:1068-1113): 0x8000 (side ^ inv) or None."""
    if (yp ^ sides['sgn'] << 8) & 0x8000:
        if not xp & 0x8000:
            paths.append('side-sign')
            return (xp ^ sides['dyf'] << 8) & 0x8000
    elif xp & 0x8000:
        paths.append('side-sign')
        return (xp ^ sides['dyf'] << 8) & 0x8000
    if (xp + VRN) & M16 >= 2 * VRN + 1 or (yp + VRN) & M16 >= 2 * VRN + 1:
        paths.append('side-range')
        return None
    sub, main = (xp, yp) if sides['ax'] == 0 else (yp, xp)
    o1 = (2 * sub + sides['p1']) & M16
    o2 = (o1 - sides['p2']) & M16

    def mid(o: int) -> int:
        n = o >> 1
        return (n * n // 4) >> 8 & M16
    mb = (mid(o1) - mid(o2)) & M16
    cst = sides['ct'] if thing else sides['cv']
    lim = VBTL + VBTH + 1 if thing else 2 * VBV + 1
    v = (8 * main - mb - cst) & M16
    if v < lim:
        paths.append('side-limit')
        return None
    paths.append('side-fast')
    return v & 0x8000


def _ptr(mem, sym: str, n: int = 3) -> int:
    return int.from_bytes(mem.read(addr(sym), n), 'little')


def _block(case: GC.Case) -> Optional[int]:
    mem = case.entry
    x = s16(case.regs_in['a'])
    y = s16(GK.up_source(GR.Upstream(case), 'dp:_Dp:2', 'in')[0] |
            GK.up_source(GR.Upstream(case), 'dp:_Dp:2', 'in')[1] << 8)
    w, h = mem.u16(addr('_g_bmapwidth')), mem.u16(addr('_g_bmapheight'))
    if x < 0 or x >= s16(w) or y < 0 or y >= s16(h):
        return None
    return y * w + x


def _trace(mem) -> List[int]:
    return TLM._trace_of(mem)


def lines_paths(case: GC.Case) -> List[str]:
    mem = case.entry
    out: List[str] = []
    blk = _block(case)
    if blk is None:
        return ['off-map']
    sides = up_sides(mem)
    bm = _ptr(mem, '_g_blockmap')
    off = mem.u16(bm + 2 * blk)
    lst = (bm & 0xFF0000) | ((mem.u16(addr('_g_blockmaplump')) + 2 * off)
                             & M16)
    lines = _ptr(mem, '_g_lines')
    vc = mem.u16(addr('validcount'))
    oxc, oyc = sides['oxc'], sides['oyc']
    i = 2
    while True:
        n = mem.u16((lst & 0xFF0000) | ((lst + i) & M16))
        if n == M16:
            break
        i += 2
        lp = (lines & 0xFF0000) | ((lines + 36 * n) & M16)
        if mem.u16(lp + UC['UO_LINE_VALIDCOUNT']) == vc:
            out.append('stamped')
            continue
        s = []
        for o in (UC['UO_LINE_V1'], UC['UO_LINE_V2']):
            vx, vy = mem.u16(lp + o), mem.u16(lp + o + 2)
            yp, xp = s16(vy) - s16(oyc), s16(vx) - s16(oxc)
            if not -0x8000 <= yp < 0x8000 or not -0x8000 <= xp < 0x8000:
                out.append('side-overflow')
                s.append(None)
                continue
            s.append(side1(xp & M16, yp & M16, sides, False, out))
        if None in s:
            continue                    # (vtxSlowR: not modelled)
        out.append('crossed' if s[0] != s[1] else 'not-crossed')
    out.append('full' if not case.regs_out['a'] & M16 else 'end')
    return out


def things_paths(case: GC.Case) -> List[str]:
    mem = case.entry
    out: List[str] = []
    blk = _block(case)
    if blk is None:
        return ['off-map']
    sides = up_sides(mem)
    tr = _trace(mem)
    links = _ptr(mem, '_g_blocklinks')
    th = int.from_bytes(mem.read((links & 0xFF0000) |
                                 ((links + 4 * blk) & M16), 3), 'little')
    if not th & 0xFF0000:
        out.append('empty')
    x = (tr[2] ^ tr[3]) & 0xFFFFFFFF
    quad = 'quadrant-pos' if x and not x & 0x80000000 else 'quadrant-neg'
    k = 0
    while th & 0xFF0000 and k < 600:
        k += 1
        r = int.from_bytes(mem.read(th + UC['UO_MO_RADIUS'], 4), 'little')
        tx = int.from_bytes(mem.read(th + UC['UO_MO_X'], 4), 'little')
        ty = int.from_bytes(mem.read(th + UC['UO_MO_Y'], 4), 'little')
        unk = None
        if not sides['rr']:
            unk = 'unk-rr'
        elif r & M16:
            unk = 'unk-radius'
        else:
            R = r >> 16
            dy = TLM.s32(ty - tr[1])
            dx = TLM.s32(tx - tr[0])
            yd, xd = (dy >> 16) & M16, (dx >> 16) & M16
            ovf = not (-(1 << 31) <= TLM.s32(ty) - TLM.s32(tr[1]) <
                       (1 << 31)) or not (-(1 << 31) <= TLM.s32(tx) -
                                          TLM.s32(tr[0]) < (1 << 31))
            if ovf:
                unk = 'unk-overflow'
            else:
                if quad == 'quadrant-pos':
                    y1, y2 = yd + R, yd - R
                else:
                    y1, y2 = yd - R, yd + R
                tmp: List[str] = []
                a = side1((xd - R) & M16, y1 & M16, sides, True, tmp)
                b2 = side1((xd + R) & M16, y2 & M16, sides, True, tmp) \
                    if a is not None else None
                if a is None or b2 is None:
                    unk = 'unk-side'
                else:
                    out.append('fast-crossed' if a != b2 else
                               'fast-not-crossed')
        if unk:
            out += [unk, quad]
            rad = TLM.s32(r)
            x1 = TLM.s32(tx - rad)
            y1 = TLM.s32(ty + rad if quad == 'quadrant-pos' else ty - rad)
            dlx = TLM.s32(2 * rad)
            dly = -dlx if quad == 'quadrant-pos' else dlx
            s1 = TLM.divline_side(tr, x1, y1)
            s2 = TLM.divline_side(tr, TLM.s32(x1 + dlx), TLM.s32(y1 + dly))
            out.append('slow-crossed' if s1 != s2 else 'slow-not-crossed')
        elif 'fast-crossed' == out[-1]:
            out.append(quad)
        th = int.from_bytes(mem.read(th + UC['UO_MO_BNEXT'], 3), 'little')
    out.append('full' if not case.regs_out['a'] & M16 else 'end')
    return out


def setup_paths(case: GC.Case) -> List[str]:
    mem = case.entry
    out: List[str] = []
    flags = mem.u16(addr('PT_FLAGS'))
    out.append('things' if flags & UC['UC_PT_ADDTHINGS'] else 'lines')
    tr = _trace(mem)
    if not mem.u16(addr('TR_LONG')):
        return out + ['short']
    if not tr[2] & 0xFFFFFFFF:
        return out + ['dx-0']
    if not tr[3] & 0xFFFFFFFF:
        return out + ['dy-0']
    adx, ady = abs(s16(tr[2] >> 16)), abs(s16(tr[3] >> 16))
    if adx > 2900:
        return out + ['dx-large']
    if adx + ady > 2900:
        return out + ['sum-large']
    if tr[0] & M16 and tr[0] >> 16 & M16 == 0x7FFF:
        return out + ['oxc-overflow']
    if tr[1] & M16 and tr[1] >> 16 & M16 == 0x7FFF:
        return out + ['oyc-overflow']
    out.append('axis-y' if ady > adx else 'axis-x')
    out.append('sq-neg' if (tr[2] ^ tr[3]) & 0x80000000 else 'sq-pos')
    out.append('fraction' if tr[0] & M16 or tr[1] & M16 else 'fraction-0')
    return out


def long_paths(case: GC.Case) -> List[str]:
    tr = [TLM.s32(v) for v in _trace(case.entry)]
    for name, v in (('dx-above', tr[2] > 0x100000),
                    ('dy-above', tr[3] > 0x100000),
                    ('dx-below', tr[2] < -0x100000),
                    ('dy-below', tr[3] < -0x100000)):
        if v:
            return [name]
    return ['short']


PATH_OF = {'p_trace65.s:traceLines': lines_paths,
           'p_trace65.s:traceThings': things_paths,
           'p_trace65.s:sideSetup': setup_paths,
           'p_trace65.s:longTrace': long_paths}


def paths_of(case: GC.Case, key: str) -> List[str]:
    return sorted(set(PATH_OF[key](case)))


# ---------------------------------------------------------------------------
# Synthetic cases (--synth): a captured case's entry state with pokes, the
# calls run alone on ref816 (--call): upstream's own results. A new trace
# goes through upstream's sideSetup first (its constants for the next
# call), then the call itself from the state sideSetup left.
# ---------------------------------------------------------------------------

def le32(v: int) -> bytes:
    return (v & 0xFFFFFFFF).to_bytes(4, 'little')


def save_case(case: GC.Case, path: Path) -> None:
    """A synthetic case as a case file against the part's base of its run
    (tracel.save_case's format)."""
    with own_cases():
        base = GC.load_base(case.header['run'])
    pages = GC.reader_pages(case.entry) | GC.reader_pages(case.after)
    for key in ('writes', 'reads', 'pokes'):
        for a, n in case.header.get(key, []):
            pages |= set(range(a >> 8, (a + n + 0xFF) >> 8))
    for reg in ('d', 's'):
        v = case.header['call']['start'][reg]
        pages |= {v >> 8, (v + 0xFF) >> 8 & 0xFF}
    pages = sorted(pages)
    payload = bytearray()
    for pg in pages:
        a = pg << 8
        payload += bytes(x ^ y for x, y in zip(case.entry.read(a, GC.PAGE),
                                               base.read(a, GC.PAGE)))
    wbytes = bytearray()
    for a, n in case.header['writes']:
        wbytes += case.after.read(a, n)
    header = dict(case.header, format=GC.CASE_FORMAT,
                  pages=GC._compress_pages(pages),
                  image_header=case.entry.header.hex())
    head = json.dumps(header, separators=(',', ':')).encode() + b'\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    import zlib
    path.write_bytes(zlib.compress(head + bytes(payload) + bytes(wbytes), 6))


def trace_set(x: int, y: int, dx: int, dy: int) -> List[Tuple[int, bytes]]:
    """Pokes: upstream's _g_trace and TR_LONG (longTrace's answer)."""
    t = addr('_g_trace')
    long_ = any(abs(TLM.s32(v)) > 0x100000 for v in (dx, dy)) or \
        TLM.s32(dx) < -0x100000 or TLM.s32(dy) < -0x100000
    return [(t, le32(x) + le32(y) + le32(dx) + le32(dy)),
            (addr('TR_LONG'), bytes([1 if long_ else 0, 0]))]


def chained(base: GC.Case, key: str, pokes: Sequence[Tuple[int, bytes]],
            note: str) -> GC.Case:
    """sideSetup on base's state with pokes, then key from the state it
    left (upstream's both)."""
    c1 = GK.call_synth(base, 'p_trace65.s:sideSetup', pokes,
                       note + ' (its setup)')
    mid_entry = c1.after.copy()
    mid_entry.header = base.entry.header
    mid = GC.Case(dict(base.header), mid_entry, mid_entry.copy(), None)
    c2 = GK.call_synth(mid, key, [], note)
    c2.header['pokes'] = [[a, len(d)] for a, d in pokes] + \
        [list(w) for w in c1.header['writes']]
    return c2


def block_lines(case: GC.Case) -> List[Dict[str, int]]:
    """The lines of the call's block not stamped yet (upstream's records)."""
    mem = case.entry
    blk = _block(case)
    if blk is None:
        return []
    bm = _ptr(mem, '_g_blockmap')
    off = mem.u16(bm + 2 * blk)
    lst = (bm & 0xFF0000) | ((mem.u16(addr('_g_blockmaplump')) + 2 * off)
                             & M16)
    lines = _ptr(mem, '_g_lines')
    vc = mem.u16(addr('validcount'))
    out = []
    i = 2
    while True:
        n = mem.u16((lst & 0xFF0000) | ((lst + i) & M16))
        if n == M16:
            return out
        i += 2
        lp = (lines & 0xFF0000) | ((lines + 36 * n) & M16)
        if mem.u16(lp + UC['UO_LINE_VALIDCOUNT']) == vc:
            continue
        w = [s16(mem.u16(lp + o)) for o in (0, 2, 4, 6)]
        out.append({'n': n, 'v1x': w[0], 'v1y': w[1], 'v2x': w[2],
                    'v2y': w[3]})


def first_with(key: str, path: str) -> GC.Case:
    sel = load_select()
    for p in chosen_paths(key, sel):
        c = load_case(p)
        if path in PATH_OF[key](c):
            return c
    raise CheckError('no case of %s takes %s' % (key, path))


def first_adding(key: str) -> GC.Case:
    """The first chosen case of key whose call adds an intercept."""
    ipt = addr('intercept_p')
    for p in chosen_paths(key, load_select()):
        c = load_case(p)
        if c.after.u16(ipt) != c.entry.u16(ipt):
            return c
    raise CheckError('no case of %s adds an intercept' % key)


def synth_specs() -> List[Tuple[str, str, Any]]:
    """(entry, name, a function making the case)."""
    TL, TT = 'p_trace65.s:traceLines', 'p_trace65.s:traceThings'
    SS, LT = 'p_trace65.s:sideSetup', 'p_trace65.s:longTrace'
    ipt = addr('intercept_p')
    full = [(ipt, ((addr('intercepts') + 10 * 64) & M16).to_bytes(2,
                                                                 'little'))]

    def vertex(d: Tuple[int, int], name: str):
        def make():
            base = first_with(TL, 'crossed')
            ln = block_lines(base)[0]
            vx, vy = ln['v1x'] << 16, ln['v1y'] << 16
            return chained(base, TL, trace_set(vx - d[0], vy - d[1],
                                               2 * d[0], 2 * d[1]), name)
        return make

    def along():
        for cp in chosen_paths(TL, load_select()):
            base = load_case(cp)
            for ln in block_lines(base):
                ldx, ldy = ln['v2x'] - ln['v1x'], ln['v2y'] - ln['v1y']
                if ldx and ldy and 2 * (abs(ldx) + abs(ldy)) <= 2900 and \
                        max(abs(ldx), abs(ldy)) > 8:
                    return chained(base, TL, trace_set(
                        (ln['v1x'] << 16) - ldx * 0x8000,
                        (ln['v1y'] << 16) - ldy * 0x8000,
                        ldx * 0x20000, ldy * 0x20000), 'along a line')
        raise CheckError('no slanted line for the trace along a line')

    def single(key: str, path: str, pokes, name: str):
        def make():
            base = first_adding(key) if path == 'adding' else \
                first_with(key, path)
            return GK.call_synth(base, key, pokes, name)
        return make

    def setup(trace: Tuple[int, int, int, int], name: str):
        def make():
            base = first_with(SS, 'axis-x')
            return GK.call_synth(base, SS, trace_set(*trace), name)
        return make

    U = 0x10000
    return [
        (TL, 'vertex-x', vertex((300 * U + 0x8000, 177 * U + 0x4000),
                                'through a vertex (x axis)')),
        (TL, 'vertex-y', vertex((-211 * U - 0xC000, 389 * U + 0x8000),
                                'through a vertex (y axis)')),
        (TL, 'along', along),
        (TL, 'full', single(TL, 'adding', full, 'the list full')),
        (TT, 'slow', single(TT, 'fast-crossed',
                            [(addr('VT_RR'), b'\0\0')],
                            'no fast sides (VT_RR 0)')),
        (TT, 'full', single(TT, 'adding', full, 'the list full')),
        (SS, 'dx-0', setup((100 * U + 5, 200 * U + 7, 0, 300 * U),
                           'dx 0')),
        (SS, 'dy-0', setup((100 * U + 5, 200 * U + 7, -300 * U, 0),
                           'dy 0')),
        (SS, 'dx-large', setup((100 * U, 200 * U, 2901 * U, 5 * U),
                               '|DX| 2901')),
        (SS, 'sum-large', setup((100 * U, 200 * U, -2000 * U, 901 * U),
                                '|DX| + |DY| 2901')),
        (SS, 'oxc-overflow', setup((0x7FFF8000, 200 * U, -300 * U,
                                    100 * U), 'x at $7FFF.8000')),
        (SS, 'oyc-overflow', setup((100 * U, 0x7FFF0001, -300 * U,
                                    100 * U), 'y at $7FFF.0001')),
        (SS, 'fraction-0', setup((100 * U, 200 * U, 300 * U, -101 * U),
                                 'whole units')),
        (LT, 'dx-below', single(LT, 'short', trace_set(
            0, 0, -17 * U, 3 * U)[:1], 'dx -17')),
    ]


def make_synth(say=print) -> int:
    n = 0
    for key, name, make in synth_specs():
        check_disk()
        c = make()
        c.header['synthetic'] = True
        save_case(c, SYNTH / native_name(key) / ('s-%s.case.z' % name))
        say('synthetic %s %s: %s' % (key, name, PATH_OF[key](c)))
        n += 1
    return n


# ---------------------------------------------------------------------------
# The runs
# ---------------------------------------------------------------------------

def classify_result(r: Dict[str, Any]) -> str:
    if r.get('ok'):
        return 'equal'
    if (r.get('error') or '').startswith('bridge:'):
        return 'undecodable'
    return 'failed'


def failed(r: Dict[str, Any]) -> bool:
    return r.get('class', 'failed' if not r.get('ok') else 'equal') == \
        'failed'


def _run_job(job) -> Dict[str, Any]:
    path, key, obj = job
    b = G.load_build(Path(obj), IMAGE)
    spec = spec_of(key)
    case = load_case(Path(path))
    try:
        paths = paths_of(case, key)
    except Exception as error:
        paths = ['? %s: %s' % (type(error).__name__, error)]
    try:
        r = run_native(case, spec, b, FILL, PROFILE)
    except Exception as error:
        r = {'case': Path(path).name, 'routine': key, 'ok': False,
             'fill': '%02x' % FILL, 'profile': PROFILE,
             'error': '%s: %s' % (type(error).__name__, error)}
    r.pop('_m', None)
    r['paths'] = paths
    r['run'] = case.header['run']
    r['synthetic'] = case.header.get('note') if case.header.get(
        'synthetic') else None
    r['class'] = classify_result(r)
    return r


def check_cases(entries: Sequence[str] = (), obj: Path = OUT,
                jobs: int = JOBS, limit: Optional[int] = None,
                synth: bool = True, say=print
                ) -> Dict[str, List[Dict[str, Any]]]:
    """The chosen cases of the entries (limit: that many of each, spread)
    and the synthetic ones on the image in obj: {key: results}."""
    sel = load_select()
    work = []
    for key in ENTRIES:
        if entries and key not in entries:
            continue
        paths = chosen_paths(key, sel)
        if limit:
            paths = TLM.spread(paths, limit)
        if synth:
            paths += synth_paths(key)
        work += [(str(p), key, str(obj)) for p in paths]
    out: Dict[str, List[Dict[str, Any]]] = {}
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for r in pool.map(_run_job, work, chunksize=2):
            out.setdefault(r['routine'], []).append(r)
    for key, res in out.items():
        bad = [r for r in res if failed(r)]
        say('%s: %d runs, %d failed' % (key, len(res), len(bad)),
            flush=True)
        for r in bad[:3]:
            say('  %s' % json.dumps(r)[:700], flush=True)
    return out


# ---------------------------------------------------------------------------
# The dead guard (GAME.md 3.5 R4): no captured call writes its state, and
# G_IDT (= G_OFS) is 0 at every call of traceLines
# ---------------------------------------------------------------------------

def guard_ranges() -> List[Tuple[str, int, int]]:
    out = [('line.gstamp (GSTAMP)', MM_GSTAMP, MM_VIEWSAVE),
           ('GW_TAB', MM_GW_TAB, MM_GW_TAB + 10 * GW_MAXB)]
    for s in GUARD_SYMBOLS:
        a = addr(s)
        out.append((s, a, a + 2))
    return out


def guard_evidence(say=print) -> Dict[str, Any]:
    sel = load_select()
    ranges = guard_ranges()
    rep: Dict[str, Any] = {'cases': 0, 'writes': {}, 'g_idt_nonzero': 0,
                           'traceLines_cases': 0}
    for key in ENTRIES:
        for p in chosen_paths(key, sel):
            c = load_case(p)
            rep['cases'] += 1
            for a, n in c.header.get('writes', []):
                for name, lo, hi in ranges:
                    if a < hi and lo < a + n:
                        rep['writes'].setdefault(name, []).append(
                            '%s %s' % (key, p.name))
            if key == 'p_trace65.s:traceLines':
                rep['traceLines_cases'] += 1
                if c.entry.u16(addr('G_OFS')):
                    rep['g_idt_nonzero'] += 1
    rep['ok'] = not rep['writes'] and not rep['g_idt_nonzero']
    say('guard: %d cases, writes %s, G_IDT not 0 in %d of %d traceLines '
        'calls' % (rep['cases'], {k: len(v) for k, v in
                                  rep['writes'].items()},
                   rep['g_idt_nonzero'], rep['traceLines_cases']))
    return rep


# ---------------------------------------------------------------------------
# Builds and planted bugs
# ---------------------------------------------------------------------------

def build(source: Path = SRC, game: Optional[Path] = None) -> Path:
    """make -f game.mk part P=tracet (source: the tree's src/native or a
    scratch copy; game: its GAME directory): the image's directory. A
    warning fails it."""
    cmd = ['make', '-s', '-C', str(source), '-f', 'game.mk', 'part',
           'P=%s' % PART, 'ROOT=%s' % ROOT]
    if game is not None:
        cmd.append('GAME=%s' % game)
    r = bounded.run(cmd, timeout=600, max_bytes=16 << 20,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    universal_newlines=True)
    if r.returncode:
        raise CheckError('the build failed:\n' + r.stdout[-3000:])
    if 'arning' in r.stdout:
        raise CheckError('the build warns:\n' + r.stdout[-3000:])
    return (game or GL.GAME) / PART


def planted(tmp: Path, bugs: Sequence[Tuple[str, str, str]]) -> Path:
    """The part's image from a scratch copy in tmp (game.mk, the
    fragments, the part's own files, each (file, old, new) of bugs applied
    once; the rest through game.mk's vpath): its directory."""
    src = tmp / 'src'
    for f in G.PLANT_COPY:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    part = SRC / 'game' / PART
    (src / 'game' / PART).mkdir(parents=True, exist_ok=True)
    for f in part.iterdir():
        if f.is_file():
            shutil.copy(str(f), str(src / 'game' / PART / f.name))
    for name, old, new in bugs:
        path = src / name
        text = path.read_text()
        if text.count(old) != 1:
            raise CheckError('the bug no longer applies: %r' % old)
        path.write_text(text.replace(old, new))
    return build(src, tmp / 'game')


S = 'game/tracet/tracet.s'
STAMP = """tlNew:  ldy #LN_VALID                   ; its stamp, before its sides
        lda G_VALID
        sta (GC_LP),y
        iny
        lda G_VALID+1
        sta (GC_LP),y
        jsr ln_dirty
"""
# The planted bugs (docs/GAME.md 2.4 row tracet), each (file, old, new) in
# src/native/ and the entry whose sampled cases must catch it
PLANTS = {
    # a thing's diagonal chosen by the wrong quadrant: trace.dx ^ trace.dy
    # < 0 taken as > 0 (the corners (x - r, y + r), (x + r, y - r))
    'quadrant': ([(S, """        eor TR_DY+3                     ;   signed)?
        bmi ttNeg""", """        eor TR_DY+3                     ;   signed)?
        bmi ttPos                       ; (planted)""")],
                 'p_trace65.s:traceThings'),
    # the stamp written after the side test: only a crossed line is stamped
    'stamp-after': ([(S, STAMP, "tlNew:                                  ; "
                      "(planted: no stamp here)\n"),
                     (S, """        lda TT_LN                       ; the intercept
        ldx TT_LN+1
        FCALL lineCross""", """        lda TT_LN                       ; (planted: the stamp)
        ldx TT_LN+1
        jsr ln_get
        ldy #LN_VALID
        lda G_VALID
        sta (GC_LP),y
        iny
        lda G_VALID+1
        sta (GC_LP),y
        jsr ln_dirty
        lda TT_LN                       ; the intercept
        ldx TT_LN+1
        FCALL lineCross""")], 'p_trace65.s:traceLines'),
    # a line shared by two blocks met twice: the stamp is not tested, so a
    # line an earlier block of the trace took is taken again
    'met-twice': ([(S, """        cmp G_VALID+1
        beq tlNext""", """        cmp G_VALID+1
        bra tlNew                       ; (planted)""")],
                  'p_trace65.s:traceLines'),
}


def plant_check(name: str, jobs: int = JOBS, limit: Optional[int] = None,
                say=print) -> Dict[str, Any]:
    """The plant's image from a scratch copy (deleted after), run on the
    sampled cases of its entry (limit: that many, spread) and its
    synthetic ones: how many runs fail."""
    bugs, key = PLANTS[name]
    check_disk()
    tmp = tmpdir('plant')
    try:
        obj = planted(tmp, bugs)
        res = check_cases([key], obj, jobs, limit=limit,
                          say=lambda *a, **k: None)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    rs = res.get(key, [])
    caught = sum(1 for r in rs if failed(r))
    out = {'plant': name, 'entry': key, 'runs': len(rs), 'caught': caught,
           'first': next((r.get('diff') or r.get('error') or r.get('stop')
                          for r in rs if failed(r)), None)}
    say('plant %s: %d of %d runs fail' % (name, caught, len(rs)))
    return out


# ---------------------------------------------------------------------------
# Sizes and the report
# ---------------------------------------------------------------------------

BUDGET = {'up': 2189, 'native': 2800}
GAME_MODULES = ('tracet',)


def load_build(obj: Path = OUT):
    return G.load_build(obj, IMAGE)


def routine_sizes(b) -> Dict[str, int]:
    """Each routine's bytes: the module's bytes in each segment, split
    among the routines placed there by their addresses."""
    text = (b.obj / (b.name + '.map')).read_text()
    text = text.split('Modules list:', 1)[-1].split('Segment list:', 1)[0]
    module, segs = None, []
    for line in text.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module in GAME_MODULES and f and (f[0] == 'GCORE' or
                                              f[0].startswith('GGRP')):
            start = next(int(x[5:], 16) for x in f if x.startswith('Offs='))
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            segs.append((f[0], b.segments[f[0]][0] + start, size))
    names = [native_name(k) for k in ROUTINES + HELPERS]
    out = {}
    for seg, lo, size in segs:
        here = sorted((b.labels[n], n) for n in names if n in b.labels and
                      GK.seg_of(b, n) == seg and lo <= b.labels[n] <
                      lo + size)
        for i, (a, n) in enumerate(here):
            out[n] = (here[i + 1][0] if i + 1 < len(here) else lo + size) - a
    return out


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    b = load_build(obj)
    ms = G.module_sizes(b)
    game = sum(ms.get(m, 0) for m in GAME_MODULES)
    return {'modules': {m: ms.get(m, 0) for m in GAME_MODULES},
            'native_bytes': game, 'budget': BUDGET['native'],
            'upstream_bytes': BUDGET['up'],
            'over_budget_pct': round(100.0 * (game - BUDGET['native']) /
                                     BUDGET['native'], 1),
            'routines': routine_sizes(b)}


def _stats(xs: Sequence[Optional[float]]) -> Optional[Dict[str, float]]:
    ys = sorted(x for x in xs if x is not None)
    if not ys:
        return None
    return {'median': ys[len(ys) // 2], 'worst': ys[-1], 'n': len(ys)}


def summarise(results: Sequence[Dict[str, Any]], key: str
              ) -> Dict[str, Any]:
    from a2vm import costs
    mhz = costs.parameters(PROFILE)['fabric_mhz']
    classes: Dict[str, int] = {}
    paths: Dict[str, int] = {}
    for r in results:
        classes[r.get('class', '?')] = classes.get(r.get('class', '?'), 0) \
            + 1
        for p in r.get('paths', []):
            paths[p] = paths.get(p, 0) + 1
    return {'runs': len(results), 'cases': len(results),
            'failures': sum(1 for r in results if failed(r)),
            'classes': classes,
            'stray_writes': sum(r.get('stray_n', 0) for r in results),
            'lowest_s': min((r['lowest_s'] for r in results
                             if r.get('lowest_s') is not None),
                            default=None),
            'cycles': {PROFILE: _stats([r.get('cycles') for r in results])},
            'us': {PROFILE: _stats([round(r['clocks'] / mhz, 2)
                                    for r in results if r.get('clocks')])},
            'paths': paths,
            'paths_declared': PATHS[key],
            'paths_not_taken': [p for p in PATHS[key] if p not in paths],
            'first_failures': [{k: v for k, v in r.items() if k != 'paths'}
                               for r in results if failed(r)][:5]}


def report(run_res: Dict[str, List[Dict[str, Any]]],
           guard: Optional[Dict[str, Any]],
           plants: Optional[List[Dict[str, Any]]], obj: Path = OUT
           ) -> Dict[str, Any]:
    sel = load_select()
    rep: Dict[str, Any] = {
        'format': 'game-part-report 1', 'part': PART, 'wave': 3,
        'lean': 'the owner\'s request of 2026-10-02: at most %d calls an '
                'entry, one fill ($%02X), one profile (%s)' % (
                    SAMPLE, FILL, PROFILE),
        'entries': {}, 'sizes': sizes(obj), 'fills': ['%02X' % FILL],
        'profiles': [PROFILE],
        'exclusions': [n for n, _, _ in gcanon.ROUTINE_EXCLUSIONS],
        'no_native_code': list(NO_CODE)}
    for key in ENTRIES:
        e = sel['entries'].get(key, {})
        s = summarise(run_res.get(key, []), key)
        s['survey_calls'] = e.get('calls', 0)
        s['eligible'] = e.get('eligible', 0)
        s['chosen'] = sum(len(c) for c in e.get('chosen', {}).values())
        rep['entries'][key] = s
    if guard is not None:
        rep['dead_guard'] = guard
    if plants is not None:
        rep['plants'] = plants
    rep['failures'] = sum(v['failures'] for v in rep['entries'].values())
    rep['stray_writes'] = sum(v['stray_writes']
                              for v in rep['entries'].values())
    rep['lowest_s'] = min((v['lowest_s'] for v in rep['entries'].values()
                           if v['lowest_s'] is not None), default=None)
    return rep


def need() -> Optional[str]:
    """What build/ lacks for the checkpoint (None: all there)."""
    for p, cmd in (
            (GL.SHARED / 'gen' / 'ggame.inc',
             'make -s -C src/native -f game.mk shared ROOT=$PWD'),
            (GL.SHARED / 'native-game-1.json',
             'make -s -C src/native -f game.mk shared ROOT=$PWD'),
            (GL.SHARED / 'survey.json',
             'python3 tools/native/gamecap.py --survey'),
            (G.A2VM, 'make -C tools/a2vm'),
            (title.MACHINE, 'make -C tools/ref816')):
        if not Path(p).exists():
            return '%s is missing (%s)' % (p, cmd)
    if not GR.have_bases():
        return 'the level bases are missing (python3 tools/native/' \
            'level_check.py --setup)'
    return None


def save(name: str, data: Any) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_text(json.dumps(data, indent=1) + '\n')
    return p


def load(name: str) -> Any:
    p = OUT / name
    return json.loads(p.read_text()) if p.exists() else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ('select', 'capture', 'synth', 'run', 'guard', 'plants',
                 'report', 'all'):
        parser.add_argument('--' + flag, action='store_true')
    parser.add_argument('--entries', nargs='*', default=())
    parser.add_argument('--limit', type=int)
    parser.add_argument('--obj', type=Path, default=OUT)
    parser.add_argument('--jobs', type=int, default=JOBS)
    a = parser.parse_args(argv)
    missing = need()
    if missing:
        print(missing, file=sys.stderr)
        return 2
    if a.all:
        a.select = a.capture = a.synth = a.run = a.guard = a.plants = \
            a.report = True
    if a.select:
        save('select.json', select())
    if a.capture:
        capture(a.jobs)
    if a.synth:
        make_synth()
    if a.run:
        build()
        res = check_cases(a.entries, a.obj, a.jobs, a.limit)
        save('run.json', res)
    if a.guard:
        save('guard.json', guard_evidence())
    if a.plants:
        save('plants.json', [plant_check(n, a.jobs) for n in PLANTS])
    if a.report:
        rep = report(load('run.json') or {}, load('guard.json'),
                     load('plants.json'), a.obj)
        save('report.json', rep)
        print('report: %d failures, %d stray writes, %d B of %d' % (
            rep['failures'], rep['stray_writes'],
            rep['sizes']['native_bytes'], BUDGET['native']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
