#!/usr/bin/env python3
"""Part geom's checkpoint (milestone 10, docs/GAME.md 2.4 row geom, 3.5):
the captured calls of its entries, the iterators with a recording
callback, the synthetic cases for paths no run takes, the random
point-line, box-line and posMul checks, and report.json.

Usage:  python3 tools/native/gparts/geom_check.py --select
        python3 tools/native/gparts/geom_check.py --capture [--entries ...]
        python3 tools/native/gparts/geom_check.py --synth
        python3 tools/native/gparts/geom_check.py --run [--entries ...]
                                                 [--limit N] [--obj DIR]
        python3 tools/native/gparts/geom_check.py --iter [--obj DIR]
        python3 tools/native/gparts/geom_check.py --rand [--n 100000]
        python3 tools/native/gparts/geom_check.py --report
        python3 tools/native/gparts/geom_check.py --all

Everything this tool writes is under build/native/game/geom/ (the part's
directory, docs/GAME.md 2.5): its own cases (cases/RUN/NAME/, gamecap.py's
format, distilled against a base of its own a run: the shared case
directory is not touched), select.json, the results of each step
(run.json, iter.json, rand.json) and report.json. Temporary files go in
build/tmp-geom-* directories, deleted after each run.

The selection (GAME.md 3.5 step 2, the task's minimums): for each entry,
every call of the survey's runs when there are fewer than 300 (the last
call of a run left out: it may not return before the run ends), else 300
spread evenly over them; only calls whose reached dispatch targets are
built (eligibility: P_BlockLinesIterator's calls that reached
PIT_AddLineIntercepts wait for part tracel), and for the iterators 100 more
calls of those, run with the recording callback only. The paths of each
entry (PATHS: computed from each case's inputs, upstream's branches) are
reported; a path no chosen call takes gets a synthetic case (--synth):
a real case's entry state with inputs poked so that upstream takes that
path, run on ref816 alone (--call), as the skeleton's synthetic ceiling
spawns are (gamecap.call_case). baseFloor, baseFloorL and blockRange have
no call in any run (the survey): their cases are all synthetic.

A case runs (--run) on the part's test image (make -f game.mk part
P=geom) from both poisoned machines ($A5, $5A), under the cost profiles
f121 and fastpath (four runs a case): gameroutine.py's method (the map's
level base, the case's entry state through the manifest, the native-only
state derived), with this part's args.json (src/native/game/geom/
args.json), whose inputs and outputs need more than gameroutine.py reads
(request R5): sources "deref:dp:SYM:LEN" (the bytes at a far pointer),
"derefy:dp:SYM:LEN" (the same plus Y), conversions "as" line, sector,
subsector (a pointer to its index), "sector_dbr" (a register under DBR),
"ittab" (a callback to its ITTAB number), "sbyte" (a native byte against
upstream's word, sign-extended); native places "geo:NAME" (the part's
scratch block, a label of the build), "math:NAME", "c" (the carry at the
return); "when": "c_clear" (an output read only when upstream returns C
clear); "check": "unchanged" (upstream does not write it: _g_lowfloor).
Each native output place is seeded with upstream's value at the entry
(so an output a path leaves unwritten compares as upstream leaves it).

Compared: the canonical state after the call (gcanon, routine mode: R1-R6
only), every declared output, the return values; checked: no stray write
(a2vm's write log from the call to the driver's end, the flush included:
every write must be to the zero page, the stack, the API's caches and
state, the scratch blocks, the code slots, the planes, the globals, or a
bank the game manifest describes, whose bytes the canonical comparison
holds; the driver's own writes and the far layer's soft switches aside);
measured: the call's time from the write log's clock (the cost model's
fabric clocks under a profile, in microseconds) and its CPU cycles, and
the run's lowest S.
"""

import argparse
import json
import os
import random
import re
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import zlib
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

from bridge import memory as bmem  # noqa: E402
from bridge.port import PortReader, PortWriter  # noqa: E402
from native import gamecap as GC, gcanon, glayout as GL, grun as G, \
    llayout as LL  # noqa: E402
from native import gameroutine as GR  # noqa: E402
from ref816 import bounded, calls as CL, title  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'geom'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
SYNTH = CASES / 'synth'
ARGS = SRC / 'game' / PART / 'args.json'
IMAGE = 'ptest'
FILLS = (0xA5, 0x5A)
PROFILES = ('f121', 'fastpath')
JOBS = 2
MIN_FREE = 20 * 10 ** 9
CAPTURE_BATCH = 150
CHOSEN = 300
ITER_EXTRA = 100
UPSTREAM_DP = 0x900             # (the case's D; checked per case)

ENTRIES = [k for p in GL.PARTS if p['name'] == PART for k in p['routines']]
ITERATORS = ('p_map65.s:P_BlockLinesIterator',
             'p_map65.s:P_BlockThingsIterator')
NO_CALLS = ('p_map65.s:baseFloor', 'p_map65.s:baseFloorL',
            'p_map65.s:blockRange')
# ITTAB's targets in their order (GAME.md 2.2; glayout.DISPATCH), the
# harness's after them
ITTAB = GL.DISPATCH['ITTAB']['targets']
IT_HARNESS = len(ITTAB) + 1

# the reference's recording callback (65816, poked into bank $7C, $0000-
# $04FF, zero in every run's RAM: upstream's banks end at $78, the demo
# lumps go at $7E0000 (lumps.py); checked before each use): each call
# appends _Dp
# (the line or mobj, 4 bytes) to REC_BUF, counts in REC_N, and answers 0
# (stop) at the call REC_STOP, else 1; the iterators call it with 16-bit
# A, X and Y (their immediates are words) and the game's D
REC_BANK = 0x7C
REC_CODE = 0x7C0000
REC_STOP = 0x7C00F0
REC_N = 0x7C0100
REC_BUF = 0x7C0102
REC_MAX = 256


def rec_code(dp: int) -> bytes:
    """The recording callback's bytes (dp: _Dp's offset in the direct
    page)."""
    def long(a: int) -> bytes:
        return bytes([a & 0xFF, a >> 8 & 0xFF, a >> 16 & 0xFF])
    code = bytearray()
    code += b'\xDA'                                 # phx
    code += b'\xAF' + long(REC_N)                   # lda REC_N
    code += b'\x0A\x0A'                             # asl a; asl a
    code += b'\xAA'                                 # tax
    code += bytes([0xA5, dp])                       # lda _Dp
    code += b'\x9F' + long(REC_BUF)                 # sta REC_BUF,x
    code += bytes([0xA5, dp + 2])                   # lda _Dp+2
    code += b'\x9F' + long(REC_BUF + 2)             # sta REC_BUF+2,x
    code += b'\xAF' + long(REC_N)                   # lda REC_N
    code += b'\x1A'                                 # inc a
    code += b'\x8F' + long(REC_N)                   # sta REC_N
    code += b'\xFA'                                 # plx
    code += b'\xCF' + long(REC_STOP)                # cmp REC_STOP
    code += b'\xF0\x04'                             # beq stop
    code += b'\xA9\x01\x00'                         # lda #1
    code += b'\x6B'                                 # rtl
    code += b'\xA9\x00\x00'                         # stop: lda #0
    code += b'\x6B'                                 # rtl
    return bytes(code)


class CheckError(Exception):
    pass


# ---------------------------------------------------------------------------
# The part's own case directory (gamecap.py's functions, pointed here)
# ---------------------------------------------------------------------------

@contextmanager
def own_cases() -> Iterator[None]:
    """gamecap's case directory and base cache set to this part's while
    the block runs (never at import: other modules of the same process use
    the shared ones)."""
    saved = GC.CASES, GC._BASES
    GC.CASES, GC._BASES = CASES, {}
    try:
        yield
    finally:
        GC.CASES, GC._BASES = saved


def case_paths(run: str, key: str) -> List[Path]:
    with own_cases():
        return sorted(GC.case_dir(run, key).glob('h*.case.z'))


def synth_paths(key: str) -> List[Path]:
    d = SYNTH / GL.native_names()[key]
    return sorted(d.glob('s*.case.z')) if d.exists() else []


def load_case(path: Path) -> GC.Case:
    with own_cases():
        return GC.load_case(path)


def check_disk() -> None:
    st = os.statvfs(str(BUILD))
    free = st.f_bavail * st.f_frsize
    if free < MIN_FREE:
        raise CheckError('only %.1f GB free: stop below 20 GB' % (free / 1e9))


def tmpdir(tag: str) -> Path:
    return Path(tempfile.mkdtemp(prefix='tmp-geom-%s-' % tag,
                                 dir=str(BUILD)))


# ---------------------------------------------------------------------------
# Selection (GAME.md 3.5 step 2)
# ---------------------------------------------------------------------------

def survey_calls(key: str) -> List[Tuple[str, int, int, bool]]:
    """Every call of key in the survey's runs: (run, hit, tic, eligible),
    the last call of each run left out."""
    built = set(GL.built_set()) | {PART}
    out = []
    for run in GC.RUNS:
        sv = GC.survey_of(run)
        if sv is None:
            continue
        r = sv['routines'].get(key)
        if r is None or not r['calls']:
            continue
        targets = sv['targets']
        for hit in range(1, r['calls']):
            reached = r['reached'].get(str(hit), [])
            ok = all((GL.owner_of(targets[i]) or 'core') in built or
                     GL.owner_of(targets[i]) == 'core' for i in reached)
            out.append((run, hit, r['tic'][hit - 1], ok))
    return out


def spread(items: Sequence[Any], n: int) -> List[Any]:
    if len(items) <= n:
        return list(items)
    return [items[int((i + 0.5) * len(items) / n)] for i in range(n)]


def select() -> Dict[str, Any]:
    """The chosen calls of each entry: {key: {run: [[hit, tic, role]]}},
    role "check" (the checkpoint, eligible) or "record" (the iterators'
    recording runs only)."""
    out: Dict[str, Any] = {'format': 'geom-select 1', 'entries': {}}
    for key in ENTRIES:
        calls = survey_calls(key)
        elig = [c for c in calls if c[3]]
        chosen = [(c, 'check') for c in spread(elig, CHOSEN)]
        if key in ITERATORS:
            rest = [c for c in calls if not c[3]]
            chosen += [(c, 'record') for c in spread(rest, ITER_EXTRA)]
        e: Dict[str, List[List[Any]]] = {}
        for (run, hit, tic, _), role in chosen:
            e.setdefault(run, []).append([hit, tic, role])
        out['entries'][key] = {'calls': len(calls), 'eligible': len(elig),
                               'chosen': e}
    return out


def load_select() -> Dict[str, Any]:
    p = OUT / 'select.json'
    if not p.exists():
        raise CheckError('no %s: run geom_check.py --select' % p)
    return json.loads(p.read_text())


# ---------------------------------------------------------------------------
# Capture (gamecap.capture into the part's directory)
# ---------------------------------------------------------------------------

def _capture_job(job: Tuple[str, str, List[int]]) -> str:
    run, key, hits = job
    check_disk()
    sv = GC.survey_of(run)
    tics = sv['routines'][key]['tic'] if sv else None
    with own_cases():
        made = GC.capture(run, key, hits, tics, batch=CAPTURE_BATCH,
                          say=lambda *a: None)
    return '%s %s: %d cases made' % (run, key, len(made))


def capture(entries: Sequence[str] = (), jobs: int = JOBS,
            say=print) -> None:
    sel = load_select()
    work = []
    for key, e in sel['entries'].items():
        if entries and key not in entries:
            continue
        for run, calls in e['chosen'].items():
            todo = [h for h, _, _ in calls
                    if not (CASES / run / GL.native_names()[key] /
                            ('h%08d.case.z' % h)).exists()]
            if todo:
                work.append((run, key, todo))
    # the run's base first (the first batch of a run writes it): one job a
    # run before the others of that run
    firsts = {}
    for w in work:
        firsts.setdefault(w[0], w)
    first = list(firsts.values())
    rest = [w for w in work if w not in first]
    for group in (first, rest):
        if not group:
            continue
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for msg in pool.map(_capture_job, group):
                say(msg, flush=True)


# ---------------------------------------------------------------------------
# Synthetic cases (a case's entry state with pokes, --call on ref816)
# ---------------------------------------------------------------------------

HEADER_FORMAT = '<HBBHHHHHBB4B'


def with_registers(header: bytes, **regs: int) -> bytes:
    """A ref816 image header with registers changed (pc, pbr, dbr, a, x,
    y, s, d, p, e)."""
    names = ('pc', 'pbr', 'dbr', 'a', 'x', 'y', 's', 'd', 'p', 'e')
    fields = list(struct.unpack_from(HEADER_FORMAT, header, 8))
    for k, v in regs.items():
        fields[names.index(k)] = v
    return header[:8] + struct.pack(HEADER_FORMAT, *fields) + \
        header[8 + struct.calcsize(HEADER_FORMAT):]


def call_synth(case: GC.Case, key: str, pokes: Sequence[Tuple[int, bytes]],
               note: str, regs: Optional[Dict[str, int]] = None
               ) -> GC.Case:
    """A synthetic case of routine key: case's entry memory with pokes and
    registers (the header's), run alone on ref816 (--call key's address,
    --call-writes): its return state is upstream's own."""
    entry = case.entry.copy()
    entry.header = with_registers(case.entry.header, **(regs or {}))
    for a, d in pokes:
        entry.write(a, d)
    work = tmpdir('call')
    try:
        (work / 'entry.img').write_bytes(entry.image_bytes())
        address = CL.Linkmap().address(key)
        cmd = [str(title.MACHINE), str(work / 'entry.img'), '--call',
               '%06X' % address, '--call-writes', str(work / 'writes.img'),
               '--state', str(work / 'state.json')]
        r = bounded.run(cmd, timeout=120, max_bytes=GC.MAX_FILE,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode:
            raise CheckError('ref816 --call failed: %s' % r.stdout[-800:])
        state = json.loads((work / 'state.json').read_text())
        if not state['call']['returned']:
            raise CheckError('the call did not return')
        writes = GC.image_records(work / 'writes.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    after = entry.copy()
    for a, d in writes:
        after.write(a, d)
    header = dict(case.header, routine=key, note=note, call=state['call'],
                  writes=GC._ranges(writes), synthetic=True)
    return GC.Case(header, entry, after, None)


def save_case(case: GC.Case, path: Path) -> None:
    """A case (synthetic) as a case file: its pages (the reader's, the
    pokes', the writes', the direct page and the stack) xor the run's base
    of this part's directory, then the written bytes."""
    with own_cases():
        base = GC._BASES.get(case.header['run']) or \
            GC.load_base(case.header['run'])
        GC._BASES[case.header['run']] = base
    pages = GC.reader_pages(case.entry) | GC.reader_pages(case.after)
    for a, n in case.header['writes'] + case.header.get('reads', []):
        pages |= {p for p in range(a >> 8, (a + n + 0xFF) >> 8)}
    for a, n in case.header.get('pokes', []):
        pages |= {p for p in range(a >> 8, (a + n + 0xFF) >> 8)}
    for reg in ('d', 's'):
        v = case.header['call']['start'][reg]
        pages |= {v >> 8, (v + 0xFF) >> 8 & 0xFF}
    pages = sorted(pages)
    payload = bytearray()
    for p in pages:
        a = p << 8
        payload += bytes(x ^ y for x, y in zip(case.entry.read(a, GC.PAGE),
                                               base.read(a, GC.PAGE)))
    wbytes = bytearray()
    for a, n in case.header['writes']:
        wbytes += case.after.read(a, n)
    header = dict(case.header, pages=GC._compress_pages(pages),
                  image_header=case.entry.header.hex())
    head = json.dumps(header, separators=(',', ':')).encode() + b'\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zlib.compress(head + bytes(payload) + bytes(wbytes), 6))


# ---------------------------------------------------------------------------
# The upstream side of a case
# ---------------------------------------------------------------------------

_TABLE = None


def table() -> CL.Linkmap:
    global _TABLE
    if _TABLE is None:
        _TABLE = CL.Linkmap()
    return _TABLE


def up_source(up: GR.Upstream, text: str, when: str) -> bytes:
    """upstream's bytes of a source (gameroutine's, and deref, derefy, c)."""
    case = up.case
    regs = case.regs_in if when == 'in' else case.regs_out
    mem = case.entry if when == 'in' else case.after
    if text == 'c':
        return bytes([regs['p'] & 1])
    if text.startswith('deref:') or text.startswith('derefy:'):
        kind, rest = text.split(':', 1)
        where, _, length = rest.rpartition(':')
        ptr = int.from_bytes(up_source(up, where + ':3', 'in'), 'little')
        if kind == 'derefy':
            ptr += case.regs_in['y'] & 0xFFFF
        return mem.read(ptr & 0xFFFFFF, int(length))
    return up.source(text, when)


def classify(up: GR.Upstream, pointer: int, kinds: Tuple[str, ...],
             when: str = 'in'):
    r = up.r_in if when == 'in' else up.r_out
    ref, why = r.classify(pointer & 0xFFFFFF, kinds)
    if ref is None:
        raise CheckError('$%06X is no %s (%s)' % (pointer, '/'.join(kinds),
                                                    why))
    return ref


def convert_in(up: GR.Upstream, mf, item: Dict[str, Any], data: bytes
               ) -> bytes:
    a = item.get('as')
    if a is None:
        return data
    v = int.from_bytes(data, 'little')
    if a == 'mobj':
        return GR.handle_of(mf, up.ref(v)).to_bytes(2, 'little')
    if a in ('line', 'sector', 'subsector'):
        return classify(up, v, (a,)).id.to_bytes(2, 'little')
    if a == 'sector_dbr':
        return classify(up, up.case.regs_in['dbr'] << 16 | v & 0xFFFF,
                        ('sector',)).id.to_bytes(2, 'little')
    if a == 'ittab':
        if v & 0xFFFFFF == REC_CODE:
            return bytes([IT_HARNESS])
        for n, k in enumerate(ITTAB, 1):
            if table().address(k) == v & 0xFFFFFF:
                return bytes([n])
        raise CheckError('callback $%06X is no ITTAB target' % v)
    raise CheckError('an input conversion %r' % a)


# ---------------------------------------------------------------------------
# The native side
# ---------------------------------------------------------------------------

def native_address(b, name: str) -> int:
    if '+' in name:
        base, _, off = name.partition('+')
        return native_address(b, base) + int(off, 0)
    if name in b.labels:
        return b.labels[name]
    if name in LL.G:
        return LL.G[name]
    return GR.zp_address(name)


def entry_group(b, name: str) -> int:
    """The group of a routine in an image (its gen/gplace.inc's GP_name_G).
    grun.run looks the entry's group up by address, and several groups
    share a slot's addresses, so it can take another group's code (request
    R6): the entry and its group are poked here instead."""
    text = (b.obj / 'gen' / 'gplace.inc').read_text()
    m = re.search(r'^GP_%s_G = (\d+)$' % re.escape(name), text, re.M)
    if m is None:
        return 0
    return int(m.group(1))


def run_entry(img, work: Path, name: str, **kw):
    """grun.run in routine mode with the entry and its group poked (see
    entry_group)."""
    b = img.b
    img.poke_word('dg_entry', b.labels[name])
    img.poke_label('dg_grp', bytes([entry_group(b, name)]))
    return G.run(img, work, GL.MODES['ROUTINE'], None, **kw)


def write_log_ranges() -> str:
    items = ['main:0000-BFFF', 'lc:D000-FFFF']
    items += ['aux%d' % bank for bank in range(128)]
    return ','.join(items)


def allowed_main(b) -> List[Tuple[int, int]]:
    """Main ranges a game routine (and the flush after it) may write."""
    lab = b.labels
    w = [(0x0000, 0x0200),                          # zero page, the stack
         (LL.BL_BUF, LL.BL_BUF + 0x100),            # bl_get's buffer
         (LL.MOC, LL.MOC + LL.MOC_LINES * LL.MOC_LINE),
         (LL.SCC, LL.SCC + LL.SCC_LINES * LL.SCC_LINE),
         (LL.RT_STATE, LL.RT_END),                  # the runtime's state
         (LL.GBLOCK, LL.GLOBALS_END),               # the globals
         (LL.G_VALID, LL.G_VALID + 2),              # validcount
         (GL.GS_STATUS, GL.GS_ARG + 2),             # the stops
         (LL.PRND, LL.MRND + 1),    # P_Random's index (a built callback's
                                    #   P_DamageMobj: wave 3 as integrated)
         GL.WR['SCRATCH'], GL.WR['SLOT1'], GL.WR['SLOT2'], GL.WR['GW'],
         GL.WR['PLANES']]
    for name in ('rec_v', 'rec_n', 'rec_stop'):     # the harness's callback
        if name in lab:
            w.append((lab[name], lab[name] + (8 if name == 'rec_v' else 2)))
    # ghook's event buffer: a built callback's sound (S_StartSound), as
    # mobjstate's shared rule allows it (wave 5 as integrated: part path's
    # captured calls through player's PTR_UseTraverse)
    for name, n in (('hk_ev', 6), ('hk_y', 1)):
        if name in lab:
            w.append((lab[name], lab[name] + n))
    return w


def stray_writes(lines: Sequence[Tuple[int, int, int, int, str, int, int]],
                 b, banks: Sequence[int]) -> List[str]:
    lab = b.labels
    drv = b.segments['DRIVER']
    far = [b.segments[s] for s in ('MATHFAR', 'RFAR', 'RLOAD', 'MATHLC')
           if s in b.segments]
    main_ok = allowed_main(b)
    aux_ok = set(banks) | {LL.MOBJP, LL.GTEST}
    io_ok = {0xC002, 0xC003, 0xC004, 0xC005, 0xC008, 0xC009, 0xC073}
    out = []
    for clock, cyc, pc, address, storage, bank, offset in lines:
        in_drv = drv[0] <= pc <= drv[1]
        in_far = any(lo <= pc <= hi for lo, hi in far)
        if storage == 'io':
            ok = address in io_ok
        elif storage == 'main':
            ok = any(lo <= offset < hi for lo, hi in main_ok)
        elif storage == 'aux':
            ok = bank in aux_ok
        elif storage in ('lc', 'lc1'):
            ok = in_drv or in_far
        else:
            ok = False
        if not ok:
            out.append('pc $%04X wrote %s %d $%04X' % (pc, storage, bank,
                                                        offset))
    return out


def read_write_log(path: Path) -> List[Tuple[int, int, int, int, str, int,
                                             int]]:
    out = []
    with open(str(path)) as handle:
        for line in handle:
            if line.startswith('#'):
                continue
            f = line.split()
            io = f[5] == 'io'
            out.append((int(f[1]), int(f[2]), int(f[3], 16),
                        int(f[4], 16), f[5], 0 if io else int(f[6]),
                        int(f[4], 16) if io else int(f[7], 16)))
    return out


def call_window(lines, b) -> Tuple[List, Optional[Tuple[int, int]]]:
    """The writes from the call (the driver's call_entry) to the driver's
    end, and the call's (clock, CPU cycles) from call_entry's first write
    to the store of its A at the return (dg_ra)."""
    lab = b.labels
    start = next((i for i, w in enumerate(lines)
                  if w[2] == lab['call_entry']), None)
    if start is None:
        return [], None
    ret = next((i for i in range(start, len(lines))
                if lines[i][3] == lab['dg_ra']), None)
    end = lab['drv_done']
    win = [w for w in lines[start:] if not (end <= w[2] <= lab['drv_halt'])]
    t = None
    if ret is not None:
        t = (lines[ret][0] - lines[start][0], lines[ret][1] - lines[start][1])
    return win, t


def run_native(case: GC.Case, spec: Dict[str, Any], b, fill: int,
               profile: Optional[str], pokes_native=(), banks_extra=(),
               regs_override=None, labels_native=()) -> Dict[str, Any]:
    """One case on the native image: the result with the canonical
    differences, the outputs' differences, stray writes, timing."""
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
        data = convert_in(up, mf, item, up_source(up, item['from'], 'in'))
        to = item['to']
        n = item.get('bytes', len(data))
        data = data[:n].ljust(n, b'\0')
        if to in ('a', 'x', 'y'):
            regs['axy'.index(to)] = data[0]
        elif to == 'ax':
            regs[0], regs[1] = data[0], data[1]
        elif to.startswith(('zp:', 'main:', 'geo:', 'math:')):
            img.main(native_address(b, to.split(':', 1)[1]), data)
        else:
            raise CheckError('an input destination %r' % to)
    # each native output place seeded with upstream's value at the entry
    for item in spec.get('out', []):
        nv = item.get('native', 'none')
        if not nv.startswith('geo:'):
            continue
        try:
            data = out_value(up, mf, item, 'in')
        except CheckError:
            continue
        n = item.get('bytes', 2)
        img.main(native_address(b, nv[4:]), data.to_bytes(8, 'little')[:n])
    for address, data in callback_context(case, up, mf):
        img.main(address, data)
    for address, data in pokes_native:
        img.main(address, data)
    for name, data in labels_native:        # (a label of the core: the
        img.poke_label(name, data)          #   image's, loaded into W)
    if regs_override:
        regs = list(regs_override)
    work = tmpdir('run')
    try:
        r = run_entry(img, work, spec['native'], regs=tuple(regs), banks=list(banks) + [LL.GTEST] +
                  list(banks_extra), profile=profile,
                  write_log=write_log_ranges())
        res['lowest_s'] = (r.state.get('lowest_s') or {}).get('s')
        ended = r.ended()
        res['ended'] = ended
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                res['stop'] = G.stop_codes(G.load_snapshot(p))
            return res
        m = G.load_snapshot(work / 'done.img')
        lines = read_write_log(work / 'writes.log')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    win, t = call_window(lines, b)
    if t is not None:
        res['clocks'], res['cycles'] = t
    res['writes'] = len(win)
    stray = stray_writes(win, b, banks)
    res['stray'] = stray[:6]
    res['stray_n'] = len(stray)
    from native import setupcheck as SC
    nat = PortReader(mf).read(SC.port_memory(m))
    diff = gcanon.compare(up.s_out, nat, 'routine')
    diff += compare_outputs(up, mf, spec, b, m, nat)
    res['diff'] = diff[:12]
    res['ok'] = not diff and not stray
    res['_m'] = m
    return res


# An iterator's callback whose caller leaves it context in scratch (wave 3
# as integrated): PIT_RadiusAttack reads bombspot, bombsource and
# bombdamage, which P_RadiusAttack keeps in upstream's p_attack65.s
# scratch (AT_BSPOT, AT_BSOURCE, AT_BDAMAGE: in the reference's entry
# state) and natively in part look's scratch block (look.inc LK_BSPOT,
# LK_BSRC, LK_BDMG). A call of the iterator alone seeds them there, as the
# caller would have.
CALLBACK_CONTEXT = {
    'p_attack65.s:PIT_RadiusAttack': ('look', (
        ('abs:p_attack65.s:AT_BSPOT:4', 'LK_BSPOT', 'mobj'),
        ('abs:p_attack65.s:AT_BSOURCE:4', 'LK_BSRC', 'mobj'),
        ('abs:p_attack65.s:AT_BDAMAGE:2', 'LK_BDMG', None)))}


def _inc_offsets(part: str) -> Dict[str, int]:
    """name -> offset from the part's scratch block of `NAME = BASE + n`
    lines in game/<part>/<part>.inc, BASE being `X = SB_<PART>`."""
    import re
    text = (SRC / 'game' / part / ('%s.inc' % part)).read_text()
    bases = {m.group(1) for m in re.finditer(
        r'^(\w+)\s*=\s*SB_%s\s*$' % part.upper(), text, re.M)}
    out = {}
    for m in re.finditer(r'^(\w+)\s*=\s*(\w+)\s*\+\s*(\d+)', text, re.M):
        if m.group(2) in bases:
            out[m.group(1)] = int(m.group(3))
    return out


def callback_context(case: GC.Case, up: GR.Upstream, mf
                     ) -> List[Tuple[int, bytes]]:
    """The native pokes of CALLBACK_CONTEXT for an iterator's call whose
    callback is built and needs them; none otherwise."""
    if case.key not in ITERATORS:
        return []
    t = table()
    dp = case.regs_in['d'] + t.address('_Dp') - t.direct_page
    fn = int.from_bytes(case.entry.read(dp + 4, 3), 'little')
    key = next((k for k in ITTAB if t.address(k) == fn), None)
    if key not in CALLBACK_CONTEXT:
        return []
    part, items = CALLBACK_CONTEXT[key]
    if part not in set(GL.built_set()) | {PART}:
        return []
    base = GL.scratch_blocks()[part][0]
    offs = _inc_offsets(part)
    out = []
    for source, name, kind in items:
        data = up_source(up, source, 'in')
        if kind == 'mobj':
            v = int.from_bytes(data, 'little') & 0xFFFFFF
            data = (b'\xff\xff' if v == 0 else
                    GR.handle_of(mf, up.ref(v)).to_bytes(2, 'little'))
        out.append((base + offs[name], data[:2]))
    return out


def native_regs(b, m) -> Dict[str, int]:
    lab = b.labels
    return {'a': G.card_byte(m, lab['dg_ra']), 'x': G.card_byte(m, lab['dg_rx']),
            'y': G.card_byte(m, lab['dg_ry']),
            'p': G.card_byte(m, lab['dg_rp'])}


def out_value(up: GR.Upstream, mf, item: Dict[str, Any], when: str) -> int:
    """upstream's value of an output (converted to the native form)."""
    data = up_source(up, item['upstream'], when)
    v = int.from_bytes(data, 'little')
    a = item.get('as')
    if a in ('line', 'sector', 'subsector'):
        if v & 0xFFFFFF == 0:
            return 0xFFFF
        return classify(up, v, (a,), when).id
    return v


def compare_outputs(up: GR.Upstream, mf, spec: Dict[str, Any], b, m,
                    nat) -> List[str]:
    regs = native_regs(b, m)
    out = []
    up_c = up.case.regs_out['p'] & 1
    for item in spec.get('out', []):
        if item.get('when') == 'c_clear' and up_c:
            continue
        if item.get('check') == 'unchanged':
            a = up_source(up, item['upstream'], 'in')
            z = up_source(up, item['upstream'], 'out')
            if a != z:
                out.append('output %s: upstream changed it' %
                           item['upstream'])
            continue
        nv = item['native']
        n = item.get('bytes', 2)
        if nv == 'c':
            value = regs['p'] & 1
        elif nv == 'ax':
            value = regs['a'] | regs['x'] << 8
        elif nv in regs:
            value = regs[nv]
        else:
            a = native_address(b, nv.split(':', 1)[1])
            value = int.from_bytes(bytes(m.main[a:a + n]), 'little')
        try:
            uv = out_value(up, mf, item, 'out')
        except CheckError as error:
            out.append('output %s: %s' % (item['upstream'], error))
            continue
        a = item.get('as')
        if a == 'sbyte':
            value = value - 0x100 if value & 0x80 else value
            uv = uv - 0x10000 if uv & 0x8000 else uv
        elif a == 'zbyte':
            value &= 0xFF
            uv &= 0xFFFF
        elif a == 'mobj':
            mine = GR.ref_of_handle(mf, ('mobj', 'zmobj'), value)
            if mine != up.ref(uv, 'out'):
                out.append('output %s: %s, upstream %s' % (
                    item['upstream'], mine, up.ref(uv, 'out')))
            continue
        else:
            mask = (1 << (8 * n)) - 1
            value, uv = value & mask, uv & mask
        if value != uv:
            out.append('output %s: %X, upstream %X' % (item['upstream'],
                                                       value, uv))
    return out


# ---------------------------------------------------------------------------
# args.json
# ---------------------------------------------------------------------------

def args() -> Dict[str, Dict[str, Any]]:
    d = json.loads(ARGS.read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise CheckError('%s: not %s' % (ARGS, GR.ARGS_FORMAT))
    return d['entries']


def load_build(obj: Path = OUT):
    return G.load_build(obj, IMAGE)


def need() -> Optional[str]:
    """What the checkpoint needs that build/ lacks (None: all there)."""
    for p, cmd in (
            (GL.SHARED / 'gen' / 'ggame.inc',
             'make -s -C src/native -f game.mk shared ROOT=$PWD'),
            (GL.SHARED / 'native-game-1.json',
             'make -s -C src/native -f game.mk shared ROOT=$PWD'),
            (GL.SHARED / 'survey.json',
             'python3 tools/native/gamecap.py --survey'),
            (G.A2VM, 'make -C tools/a2vm'),
            (title.MACHINE, 'make -C tools/ref816'),
            (BUILD / 'native' / 'math' / 'mathref', 'make -C tools/native')):
        if not Path(p).exists():
            return '%s is missing (%s)' % (p, cmd)
    if not GR.have_bases():
        return 'the level bases are missing (python3 tools/native/' \
            'level_check.py --setup)'
    return None


# ---------------------------------------------------------------------------
# The paths of each entry (from a case's inputs: upstream's branches)
# ---------------------------------------------------------------------------

UC = dict(GL.upstream_constants())
SIZEOF_LINE = 36


def _s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def _s32(v: int) -> int:
    return v - (1 << 32) if v & 0x80000000 else v


def _line(mem, ptr: int) -> Dict[str, int]:
    rec = mem.read(ptr, SIZEOF_LINE)

    def w(o):
        return _s16(int.from_bytes(rec[o:o + 2], 'little'))
    return {'v1x': w(UC['UO_LINE_V1']), 'v1y': w(UC['UO_LINE_V1'] + 2),
            'dx': w(UC['UO_LINE_DX']), 'dy': w(UC['UO_LINE_DY']),
            'slope': rec[UC['UO_LINE_SLOPETYPE']],
            'side1': int.from_bytes(rec[UC['UO_LINE_SIDENUM'] + 2:
                                        UC['UO_LINE_SIDENUM'] + 4], 'little')}


def side_model(x: int, y: int, ln: Dict[str, int]) -> Tuple[int, str]:
    """upstream's P_PointOnLineSide (for choosing inputs and naming paths;
    the truth is always ref816's): (side, path)."""
    def le(p, v):
        hi = _s16(p >> 16 & 0xFFFF)
        return hi < v or (hi == v and p & 0xFFFF == 0), \
            hi == v and p & 0xFFFF == 0
    if ln['dx'] == 0:
        ok, eq = le(x, ln['v1x'])
        return (int(ln['dy'] > 0) if ok else int(ln['dy'] < 0),
                'dx0-' + ('eq' if eq else 'le' if ok else 'gt'))
    if ln['dy'] == 0:
        ok, eq = le(y, ln['v1y'])
        return (int(ln['dx'] < 0) if ok else int(ln['dx'] > 0),
                'dy0-' + ('eq' if eq else 'le' if ok else 'gt'))
    dy_ = (y - (ln['v1y'] << 16)) & 0xFFFFFFFF
    dx_ = (x - (ln['v1x'] << 16)) & 0xFFFFFFFF
    left = _s32(((_s32(dy_) >> 8) * ln['dx']) & 0xFFFFFFFF)
    right = _s32(((_s32(dx_) >> 8) * ln['dy']) & 0xFFFFFFFF)
    if left == right:
        return 1, 'gen-eq'
    return (1, 'gen-1') if left > right else (0, 'gen-0')


PATHS = {
    'p_map65.s:P_PointOnLineSide': ['dx0-le', 'dx0-gt', 'dx0-eq', 'dy0-le',
                                    'dy0-gt', 'dy0-eq', 'gen-1', 'gen-0',
                                    'gen-eq'],
    'p_map65.s:P_BoxOnLineSide': ['%s=%s' % (s, r) for s in
                                  ('horizontal', 'vertical', 'positive',
                                   'negative') for r in (0, 1, -1)],
    'p_map65.s:P_LineOpening': ['one-sided', 'back-higher', 'front-higher',
                                'same-floor', 'back-ceil-lower',
                                'front-ceil-lower', 'same-ceil'],
    'p_map65.s:P_LineOpeningXY': ['back-higher', 'front-higher',
                                  'same-floor', 'back-ceil-lower',
                                  'front-ceil-lower', 'same-ceil'],
    'p_map65.s:posMul': ['ah0', 'ahm1', 'ahpos', 'ahneg', 'fpos', 'fneg',
                         'f0'],
    'p_map65.s:pointSector': ['any'],
    'p_map65.s:sectorFloor': ['any'],
    'p_map65.s:baseLite': ['ceilingline-none', 'ceilingline-set'],
    'p_map65.s:baseFloor': ['any'],
    'p_map65.s:baseFloorL': ['any'],
    'p_map65.s:blockRange': ['blocks', 'none-x', 'none-y', 'clamp-low',
                             'clamp-high'],
    'p_map65.s:P_BlockLinesIterator': ['off-map', 'lines', 'all-stamped',
                                       'stop'],
    'p_map65.s:P_BlockThingsIterator': ['off-map', 'empty', 'things',
                                        'stop'],
}


def paths_of(case: GC.Case) -> List[str]:
    """The paths a case takes (upstream's branches, from its inputs and
    its results)."""
    key = case.key
    mem = case.entry
    t = table()
    dp = case.regs_in['d'] + t.address('_Dp') - t.direct_page

    def dpw(off, n=4):
        return int.from_bytes(mem.read(dp + off, n), 'little')
    out = []
    if key == 'p_map65.s:P_PointOnLineSide':
        x = (case.regs_in['x'] & 0xFFFF) << 16 | case.regs_in['a'] & 0xFFFF
        y = dpw(0)
        ln = _line(mem, dpw(4) & 0xFFFFFF)
        out.append(side_model(x, y, ln)[1])
    elif key == 'p_map65.s:P_BoxOnLineSide':
        ln = _line(mem, dpw(4) & 0xFFFFFF)
        names = {0: 'horizontal', 1: 'vertical', 2: 'positive',
                 3: 'negative'}
        r = _s16(case.regs_out['a'] & 0xFFFF)
        out.append('%s=%s' % (names.get(ln['slope'], 'horizontal'), r))
    elif key in ('p_map65.s:P_LineOpening', 'p_map65.s:P_LineOpeningXY'):
        if key == 'p_map65.s:P_LineOpening':
            ln = _line(mem, dpw(0) & 0xFFFFFF)
            if ln['side1'] == 0xFFFF:
                return ['one-sided']
            sides = int.from_bytes(mem.read(t.address('_g_sides'), 3),
                                   'little')
            secs = []
            for k in (1, 0):
                n = int.from_bytes(mem.read(dpw(0) + UC['UO_LINE_SIDENUM'] +
                                            2 * k, 2), 'little')
                secs.append(int.from_bytes(mem.read(
                    sides + 14 * n + UC['UO_SIDE_SECTOR'], 3), 'little'))
            back, front = secs
        else:
            dbr = case.regs_in['dbr'] << 16
            back = dbr | case.regs_in['x'] & 0xFFFF
            front = dbr | case.regs_in['y'] & 0xFFFF

        def h(sec, o):
            return _s32(int.from_bytes(mem.read(sec + o, 4), 'little'))
        fb, ff = h(back, 0), h(front, 0)
        cb, cf = h(back, 4), h(front, 4)
        out.append('same-floor' if fb == ff else 'back-higher' if fb > ff
                   else 'front-higher')
        out.append('same-ceil' if cb == cf else 'back-ceil-lower' if cb < cf
                   else 'front-ceil-lower')
    elif key == 'p_map65.s:posMul':
        ah = int.from_bytes(mem.read(t.address('TM_L'), 2), 'little')
        out.append('ah0' if ah == 0 else 'ahm1' if ah == 0xFF else
                   'ahneg' if ah >= 0x80 else 'ahpos')
        wk = case.regs_in['d'] + t.address('DC_ENTRY') - t.direct_page
        ptr = int.from_bytes(mem.read(wk, 3), 'little') + \
            (case.regs_in['y'] & 0xFFFF)
        f = _s16(int.from_bytes(mem.read(ptr, 2), 'little'))
        out.append('f0' if f == 0 else 'fneg' if f < 0 else 'fpos')
    elif key == 'p_map65.s:baseLite':
        cl = int.from_bytes(mem.read(t.address('_g_ceilingline'), 3),
                            'little')
        out.append('ceilingline-set' if cl else 'ceilingline-none')
    elif key in ITERATORS:
        x, y = _s16(case.regs_in['a'] & 0xFFFF), _s16(dpw(0, 2))
        w = int.from_bytes(mem.read(t.address('_g_bmapwidth'), 2), 'little')
        hh = int.from_bytes(mem.read(t.address('_g_bmapheight'), 2),
                            'little')
        if not (0 <= x < w and 0 <= y < hh):
            out.append('off-map')
        elif (case.regs_out['a'] & 0xFFFF) == 0:
            out.append('stop')
        elif key == ITERATORS[0]:
            lines = int.from_bytes(mem.read(t.address('_g_lines'), 3),
                                   'little')
            n = int.from_bytes(mem.read(t.address('_g_numlines'), 2),
                               'little')
            stamps = [a for a, k in case.header['writes']
                      for a in range(a, a + k)
                      if lines <= a < lines + SIZEOF_LINE * n and
                      (a - lines) % SIZEOF_LINE == UC['UO_LINE_VALIDCOUNT']]
            out.append('lines' if stamps else 'all-stamped')
        else:
            head = int.from_bytes(mem.read(
                int.from_bytes(mem.read(t.address('_g_blocklinks'), 3),
                               'little') + 4 * (y * w + x), 3), 'little')
            out.append('things' if head else 'empty')
    elif key == 'p_map65.s:blockRange':
        def mw(sym):
            return _s16(int.from_bytes(case.after.read(t.address(
                'p_map65.s:' + sym), 2), 'little'))
        xl, xh, yl, yh = mw('MP_XL'), mw('MP_XH'), mw('MP_YL'), mw('MP_YH')
        if case.regs_out['p'] & 1:
            out.append('none-y' if yh < yl else 'none-x')
        else:
            out.append('blocks')
        w = _ptr(mem, '_g_bmapwidth', 2)
        hh = _ptr(mem, '_g_bmapheight', 2)
        box = [_s32(int.from_bytes(mem.read(t.address('_g_tmbbox') + 4 * k,
                                            4), 'little')) for k in range(4)]
        ox = _s32(_ptr(mem, '_g_bmaporgx', 4))
        oy = _s32(_ptr(mem, '_g_bmaporgy', 4))
        if box[2] < ox or box[1] < oy:
            out.append('clamp-low')
        if xh == w - 1 or yh == hh - 1:
            out.append('clamp-high')
    else:
        out.append('any')
    return out


# ---------------------------------------------------------------------------
# Running cases (--run)
# ---------------------------------------------------------------------------

COMBOS = [(f, p) for f in FILLS for p in PROFILES]


def _strip(r: Dict[str, Any]) -> Dict[str, Any]:
    r.pop('_m', None)
    return r


def _run_job(job: Tuple[str, str, str, Sequence[Tuple[int, str]]]
             ) -> List[Dict[str, Any]]:
    path, key, obj, combos = job
    b = load_build(Path(obj))
    spec = args()[key]
    case = load_case(Path(path))
    try:
        paths = paths_of(case)
    except Exception as error:                  # reported, never hidden
        paths = ['? %s' % error]
    out = []
    for fill, prof in combos:
        try:
            r = _strip(run_native(case, spec, b, fill, prof))
        except Exception as error:
            r = {'case': Path(path).name, 'routine': key, 'ok': False,
                 'fill': '%02x' % fill, 'profile': prof,
                 'error': '%s: %s' % (type(error).__name__, error)}
        r['paths'] = paths
        r['synthetic'] = bool(case.header.get('synthetic'))
        r['run'] = case.header['run']
        r['class'] = classify_result(case, paths, r)
        out.append(r)
    return out


ITTAB_TABLE = list(GL.DISPATCH).index('ITTAB') + 1


def classify_result(case: GC.Case, paths: Sequence[str],
                    r: Dict[str, Any]) -> str:
    """equal; undecodable (the reference's entry state is not a canonical
    state: a call inside a setup's spawn, as the skeleton's S2 counts
    them); waiting (an iterator's call whose reference ran its callback,
    an ITTAB entry not built yet: the native must stop at that entry,
    GS_UNBUILTD with its number: the survey's reached targets missed it,
    open point 2); failed."""
    if r.get('ok'):
        return 'equal'
    if (r.get('error') or '').startswith('bridge:'):
        return 'undecodable'
    if case.key in ITERATORS and ({'things', 'lines'} & set(paths)):
        t = table()
        dp = case.regs_in['d'] + t.address('_Dp') - t.direct_page
        fn = int.from_bytes(case.entry.read(dp + 4, 3), 'little')
        n = next((k for k, key in enumerate(ITTAB, 1)
                  if t.address(key) == fn), None)
        built = set(GL.built_set()) | {PART}
        if n is not None and GL.owner_of(ITTAB[n - 1]) not in built and \
                r.get('stop') and r['stop'][0] == GL.GS['UNBUILTD'] and \
                r['stop'][1] == n | ITTAB_TABLE << 8:
            return 'waiting:' + ITTAB[n - 1]
    return 'failed'


def failed(r: Dict[str, Any]) -> bool:
    return r.get('class', 'failed' if not r.get('ok') else 'equal') == \
        'failed'



def check_cases(entries: Sequence[str] = (), obj: Path = OUT,
                jobs: int = JOBS, limit: Optional[int] = None,
                sample: int = 1, combos=COMBOS, say=print
                ) -> Dict[str, List[Dict[str, Any]]]:
    """Every chosen case of the entries ("check" role) and every synthetic
    case, on the image in obj: {key: results}."""
    sel = load_select()
    work = []
    for key in ENTRIES:
        if entries and key not in entries:
            continue
        paths: List[Path] = []
        e = sel['entries'].get(key, {'chosen': {}})
        for run, calls in e['chosen'].items():
            for hit, _, role in calls:
                if role != 'check':
                    continue
                p = CASES / run / GL.native_names()[key] / \
                    ('h%08d.case.z' % hit)
                if p.exists():
                    paths.append(p)
        paths = paths[::sample] + synth_paths(key)
        if limit:
            paths = paths[:limit]
        work += [(str(p), key, str(obj), combos) for p in paths]
    out: Dict[str, List[Dict[str, Any]]] = {}
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_run_job, work, chunksize=2):
            for r in got:
                out.setdefault(r['routine'], []).append(r)
    for key, res in out.items():
        bad = [r for r in res if failed(r)]
        classes: Dict[str, int] = {}
        for r in res:
            classes[r.get('class', '?')] = classes.get(r.get('class', '?'),
                                                       0) + 1
        say('%s: %d runs, %d failed %s' % (key, len(res), len(bad),
                                           classes), flush=True)
        for r in bad[:3]:
            say('  %s' % json.dumps(r)[:500])
    return out


# ---------------------------------------------------------------------------
# The iterators with the recording callback (--iter)
# ---------------------------------------------------------------------------

def record_variant(case: GC.Case, stop: int = 0) -> GC.Case:
    """The case with the reference's recording callback in place of its
    callback (answering stop at call `stop`, 0 never): upstream's run."""
    t = table()
    dp = case.regs_in['d'] + t.address('_Dp') - t.direct_page
    if any(case.entry.read(REC_CODE, 0x800)):
        raise CheckError('bank $7C is not free in %s' % case.path)
    code = rec_code(t.address('_Dp') - t.direct_page)
    pokes = [(REC_CODE, code), (REC_STOP, stop.to_bytes(2, 'little')),
             (REC_N, b'\0\0'), (dp + 4, REC_CODE.to_bytes(4, 'little'))]
    c = call_synth(case, case.key, pokes, 'record stop %d of %s' % (
        stop, case.path.name if case.path else case.header.get('note')))
    c.header['pokes'] = [[a, len(d)] for a, d in pokes]
    return c


def recorded(case: GC.Case) -> List[int]:
    n = int.from_bytes(case.after.read(REC_N, 2), 'little')
    return [int.from_bytes(case.after.read(REC_BUF + 4 * k, 3), 'little')
            for k in range(min(n, REC_MAX))]


def _iter_job(job) -> List[Dict[str, Any]]:
    path, obj, stops, combos = job
    b = load_build(Path(obj))
    case = load_case(Path(path))
    spec = args()[case.key]
    out = []
    for stop in stops:
        try:
            var = record_variant(case, stop)
        except Exception as error:
            out.append({'case': Path(path).name, 'routine': case.key,
                        'stop': stop, 'ok': False,
                        'error': '%s: %s' % (type(error).__name__, error)})
            continue
        up = GR.Upstream(var)
        mf = GR.manifest(up.gamemap)[0]
        want = []
        for ptr in recorded(var):
            ref = classify(up, ptr, ('line',) if case.key == ITERATORS[0]
                           else ('mobj', 'zmobj'), 'out')
            want.append(ref.id if case.key == ITERATORS[0] else
                        GR.handle_of(mf, ref))
        for fill, prof in combos:
            try:
                r = run_native(var, spec, b, fill, prof,
                               labels_native=[('rec_stop',
                                               stop.to_bytes(2, 'little'))])
                m = r.pop('_m', None)
                if m is not None:
                    n = int.from_bytes(bytes(m.main[b.labels['rec_n']:
                                                    b.labels['rec_n'] + 2]),
                                       'little')
                    g = m.aux.get(LL.GTEST, bytearray(0x10000))
                    got = [int.from_bytes(bytes(g[GL.GTB['GT_RECORD'] + 8 * k:
                                                 GL.GTB['GT_RECORD'] + 8 * k +
                                                 2]), 'little')
                           for k in range(min(n, 256))]
                    r['recorded'] = len(got)
                    if got != want:
                        r['ok'] = False
                        r.setdefault('diff', []).append(
                            'recorded %s, upstream %s' % (got[:12],
                                                           want[:12]))
            except Exception as error:
                r = {'ok': False, 'error': '%s: %s' % (
                    type(error).__name__, error)}
            r.update(case=Path(path).name, routine=case.key, stop=stop,
                     fill='%02x' % fill, profile=prof, calls=len(want),
                     run=case.header['run'])
            out.append(r)
    return out


def iter_cases(obj: Path = OUT, jobs: int = JOBS, sample: int = 1,
               stop_every: int = 5, combos=COMBOS, say=print
               ) -> List[Dict[str, Any]]:
    """Every captured call of the two iterators (both roles), with the
    recording callback, never stopping; every stop_every-th also stopped
    at its first call and at its middle one (the k-stop runs)."""
    sel = load_select()
    work = []
    for key in ITERATORS:
        paths = []
        for run, calls in sel['entries'][key]['chosen'].items():
            for hit, _, _ in calls:
                p = CASES / run / GL.native_names()[key] / \
                    ('h%08d.case.z' % hit)
                if p.exists():
                    paths.append(p)
        for i, p in enumerate(paths[::sample]):
            stops = [0]
            if i % stop_every == 0:
                stops += [1, 2]
            work.append((str(p), str(obj), stops, combos))
    out: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_iter_job, work, chunksize=2):
            out += got
    bad = [r for r in out if not r.get('ok')]
    say('the iterators with the recording callback: %d runs, %d failed, '
        '%d callbacks recorded' % (len(out), len(bad),
                                   sum(r.get('recorded', 0) for r in out)),
        flush=True)
    for r in bad[:3]:
        say('  %s' % json.dumps(r)[:500])
    return out


# ---------------------------------------------------------------------------
# Synthetic cases (--synth): the paths no chosen call takes, and the
# entries no run calls
# ---------------------------------------------------------------------------

def _ptr(mem, sym: str, n: int = 3) -> int:
    return int.from_bytes(mem.read(table().address(sym), n), 'little')


def map_lines(mem) -> List[Tuple[int, Dict[str, int]]]:
    base, n = _ptr(mem, '_g_lines'), _ptr(mem, '_g_numlines', 2)
    return [(base + SIZEOF_LINE * i, _line(mem, base + SIZEOF_LINE * i))
            for i in range(n)]


def line_sectors(mem, lp: int) -> Tuple[int, int]:
    """(back, front) sector pointers of a two-sided line."""
    sides = _ptr(mem, '_g_sides')
    out = []
    for k in (1, 0):
        n = int.from_bytes(mem.read(lp + UC['UO_LINE_SIDENUM'] + 2 * k, 2),
                           'little')
        out.append(int.from_bytes(mem.read(sides + 14 * n +
                                           UC['UO_SIDE_SECTOR'], 3),
                                  'little'))
    return out[0], out[1]


def dp_of(case: GC.Case, sym: str = '_Dp') -> int:
    t = table()
    return case.regs_in['d'] + t.address(sym) - t.direct_page


def le32(v: int) -> bytes:
    return (v & 0xFFFFFFFF).to_bytes(4, 'little')


def first_case(key: str, run: Optional[str] = None) -> GC.Case:
    for r in ([run] if run else GC.RUNS):
        ps = case_paths(r, key)
        if ps:
            return load_case(ps[len(ps) // 2])
    raise CheckError('no case of %s to make synthetic ones from' % key)


def synth_specs() -> List[Tuple[str, GC.Case, List[Tuple[int, bytes]],
                                Dict[str, int], str]]:
    """(key, base case, pokes, registers, note) of every synthetic case."""
    out = []
    # P_PointOnLineSide: each line kind, the point on, just below, just
    # above its axis or line
    key = 'p_map65.s:P_PointOnLineSide'
    c = first_case(key)
    dp = dp_of(c)
    lines = map_lines(c.entry)
    kinds = {'dx0': next(x for x in lines if x[1]['dx'] == 0),
             'dy0': next(x for x in lines if x[1]['dy'] == 0),
             'gen': next(x for x in lines if x[1]['dx'] and x[1]['dy'])}
    for kind, (lp, ln) in kinds.items():
        x0, y0 = ln['v1x'] << 16, ln['v1y'] << 16
        for name, dx_, dy_ in (('on', 0, 0), ('below', -1, -1),
                               ('above', 1, 1), ('far', 0x123456, -0x654321),
                               ('across', -0x40000, 0x30000)):
            x, y = (x0 + dx_) & 0xFFFFFFFF, (y0 + dy_) & 0xFFFFFFFF
            out.append((key, c, [(dp, le32(y)), (dp + 4, le32(lp))],
                        {'a': x & 0xFFFF, 'x': x >> 16},
                        'P_PointOnLineSide %s line, point %s' % (kind,
                                                                 name)))
    # P_BoxOnLineSide: each slope type, a box on each side and across, and
    # the edges on the line's coordinate
    key = 'p_map65.s:P_BoxOnLineSide'
    c = first_case(key)
    dp = dp_of(c)
    boxp = int.from_bytes(c.entry.read(dp, 3), 'little')
    lines = map_lines(c.entry)
    for slope in range(4):
        found = [x for x in lines if x[1]['slope'] == slope]
        if not found:
            continue
        lp, ln = found[len(found) // 2]
        x0, y0 = ln['v1x'], ln['v1y']
        nx, ny = -ln['dy'], ln['dx']
        size = max(abs(nx), abs(ny)) or 1
        for name, s, r in (('side a', 64, 16), ('side b', -64, 16),
                           ('across', 0, 16), ('thin a', 2, 1),
                           ('thin b', -2, 1)):
            cx = x0 + ln['dx'] // 2 + s * nx // size
            cy = y0 + ln['dy'] // 2 + s * ny // size
            box = [(cy + r) << 16, (cy - r) << 16, (cx - r) << 16,
                   (cx + r) << 16]
            out.append((key, c, [(boxp, b''.join(le32(v) for v in box)),
                                 (dp + 4, le32(lp))], {},
                        'P_BoxOnLineSide slope %d, box %s' % (slope, name)))
        # the edges: a box edge exactly on v1's coordinate
        for name, box in (
                ('bottom on y', [(y0 + 8) << 16, y0 << 16, (x0 - 8) << 16,
                                 (x0 + 8) << 16]),
                ('top on y', [y0 << 16, (y0 - 8) << 16, (x0 - 8) << 16,
                              (x0 + 8) << 16]),
                ('left on x', [(y0 + 8) << 16, (y0 - 8) << 16, x0 << 16,
                               (x0 + 8) << 16]),
                ('right on x', [(y0 + 8) << 16, (y0 - 8) << 16,
                                (x0 - 8) << 16, x0 << 16]),
                ('fraction above y', [(y0 + 8) << 16, (y0 << 16) + 1,
                                      (x0 - 8) << 16, (x0 + 8) << 16])):
            out.append((key, c, [(boxp, b''.join(le32(v) for v in box)),
                                 (dp + 4, le32(lp))], {},
                        'P_BoxOnLineSide slope %d, %s' % (slope, name)))
    # P_LineOpening and P_LineOpeningXY: one-sided; the floors and the
    # ceilings in each order
    for key in ('p_map65.s:P_LineOpening', 'p_map65.s:P_LineOpeningXY'):
        c = first_case(key)
        dp = dp_of(c)
        lines = map_lines(c.entry)
        two = [x for x in lines if x[1]['side1'] != 0xFFFF]
        lp = two[len(two) // 3][0]
        back, front = line_sectors(c.entry, lp)
        if back == front:
            lp = next(x[0] for x in two if len(set(line_sectors(
                c.entry, x[0]))) == 2)
            back, front = line_sectors(c.entry, lp)
        heights = (('back higher, back ceiling lower', 64, 0, 128, 192),
                   ('front higher, front ceiling lower', 0, 48, 200, 160),
                   ('the same', 24, 24, 96, 96),
                   ('negative', -32, -40, -8, 0),
                   ('closed', 64, 64, 64, 64),
                   ('fractions', 1, 0, 0x10001, 0x10000))
        for name, fb, ff, cb, cf in heights:
            def fx(v):
                return v << 16 if name != 'fractions' else v
            pokes = [(back, le32(fx(fb))), (back + 4, le32(fx(cb))),
                     (front, le32(fx(ff))), (front + 4, le32(fx(cf)))]
            regs = {}
            if key == 'p_map65.s:P_LineOpening':
                pokes.append((dp, le32(lp)))
            else:
                regs = {'x': back & 0xFFFF, 'y': front & 0xFFFF,
                        'dbr': back >> 16}
            out.append((key, c, pokes, regs, '%s, %s' % (key.split(':')[1],
                                                         name)))
        if key == 'p_map65.s:P_LineOpening':
            one = next(x[0] for x in lines if x[1]['side1'] == 0xFFFF)
            out.append((key, c, [(dp, le32(one))], {},
                        'P_LineOpening, a one-sided line'))
    # posMul: each class of the operand's top byte and of the factor
    key = 'p_map65.s:posMul'
    c = first_case(key)
    tm_l = table().address('TM_L')
    wk = dp_of(c, 'DC_ENTRY')
    fp = int.from_bytes(c.entry.read(wk, 3), 'little') + \
        (c.regs_in['y'] & 0xFFFF)
    for ah in (0, 0xFF, 0x01, 0x7F, 0x80, 0xFE):
        for f in (0, 1, 0xFFFF, 0x7FFF, 0x8000, 0x1234, 0xEDCB):
            for vlo in (0x0000, 0xFFFF, 0x8001):
                out.append((key, c, [(tm_l, ah.to_bytes(2, 'little')),
                                     (fp, f.to_bytes(2, 'little'))],
                            {'a': vlo}, 'posMul AH %02X, F %04X, V.lo %04X'
                            % (ah, f, vlo)))
    # baseLite: ceilingline set and not
    key = 'p_map65.s:baseLite'
    c = first_case(key)
    cl = table().address('_g_ceilingline')
    lp = map_lines(c.entry)[5][0]
    out.append((key, c, [(cl, le32(lp))], {}, 'baseLite, ceilingline set'))
    out.append((key, c, [(cl, le32(0))], {}, 'baseLite, ceilingline none'))
    # baseFloor, baseFloorL: no run calls them: sectorFloor's cases of each
    # run, as the routine and as its JSL entry, with ceilingline set too
    src = []
    for run in GC.RUNS:
        ps = case_paths(run, 'p_map65.s:sectorFloor')
        src += [load_case(p) for p in spread(ps, 4)]
    for key in NO_CALLS[:2]:
        for k, c in enumerate(src):
            pokes = [] if k % 3 else [(cl, le32(map_lines(c.entry)[k][0]))]
            out.append((key, c, pokes, {}, '%s from %s %s' % (
                key.split(':')[1], c.header['run'], c.path.name)))
    # blockRange: no run calls it (P_TeleportMove's): boxes inside the map,
    # off each side, across each edge, with the growths 0 and MAXRADIUS
    key = 'p_map65.s:blockRange'
    tb = table().address('_g_tmbbox')
    for c in src[::3]:
        ox = _s32(_ptr(c.entry, '_g_bmaporgx', 4)) >> 16
        oy = _s32(_ptr(c.entry, '_g_bmaporgy', 4)) >> 16
        w = _ptr(c.entry, '_g_bmapwidth', 2) * 128
        h = _ptr(c.entry, '_g_bmapheight', 2) * 128
        for name, l_, b_, r_, t_ in (
                ('inside', ox + w // 3, oy + h // 3, ox + w // 3 + 40,
                 oy + h // 3 + 40),
                ('left of the map', ox - 600, oy + 100, ox - 400, oy + 140),
                ('below the map', ox + 100, oy - 900, ox + 140, oy - 700),
                ('across the low edges', ox - 50, oy - 50, ox + 50, oy + 50),
                ('across the high edges', ox + w - 50, oy + h - 50,
                 ox + w + 50, oy + h + 50),
                ('right of the map', ox + w + 300, oy + 10, ox + w + 400,
                 oy + 90),
                ('the whole map', ox - 10, oy - 10, ox + w + 10, oy + h + 10),
                ('a fraction', ox + 128, oy + 128, ox + 255, oy + 255)):
            box = [t_ << 16, b_ << 16, l_ << 16, r_ << 16]
            if name == 'a fraction':
                box = [(t_ << 16) + 0xFFFF, (b_ << 16) + 1, (l_ << 16) + 1,
                       (r_ << 16) + 0xFFFF]
            for d in (0, 32):
                out.append((key, c, [(tb, b''.join(le32(v) for v in box))],
                            {'a': d}, 'blockRange %s, growth %d (%s)' % (
                                name, d, c.header['run'])))
    # the iterators off the map: each edge (the callback never runs)
    for key in ITERATORS:
        sel = load_select()['entries'][key]['chosen']
        c = None
        for run, calls in sel.items():
            for hit, _, role in calls:
                p = CASES / run / GL.native_names()[key] / \
                    ('h%08d.case.z' % hit)
                if role == 'check' and p.exists():
                    c = load_case(p)
                    break
            if c:
                break
        if c is None:
            continue
        dp = dp_of(c)
        w = _ptr(c.entry, '_g_bmapwidth', 2)
        h = _ptr(c.entry, '_g_bmapheight', 2)
        for name, x, y in (('x -1', -1, 1), ('x width', w, 1),
                           ('y -1', 1, -1), ('y height', 1, h),
                           ('x -32768', -32768, 0), ('the last block', w - 1,
                                                     h - 1)):
            out.append((key, c, [(dp, (y & 0xFFFF).to_bytes(2, 'little'))],
                        {'a': x & 0xFFFF}, '%s off the map: %s' % (
                            key.split(':')[1], name)))
    return out


def make_synth(say=print) -> int:
    specs = synth_specs()
    made = 0
    counts: Dict[str, int] = {}
    for key, c, pokes, regs, note in specs:
        n = counts.get(key, 0)
        counts[key] = n + 1
        path = SYNTH / GL.native_names()[key] / ('s%04d.case.z' % n)
        if path.exists():
            continue
        s = call_synth(c, key, pokes, note, regs)
        s.header['pokes'] = [[a, len(d)] for a, d in pokes]
        s.header['base_case'] = c.path.name if c.path else None
        save_case(s, path)
        made += 1
    say('%d synthetic cases (%d new)' % (len(specs), made))
    return made


# ---------------------------------------------------------------------------
# The random checks (--rand): point-line and box-line pairs on every map,
# posMul's inputs; upstream's routines in mathref's batch (ref816's
# machine, --call's way: from the entry to the return), the native ones in
# the part's test driver geomt.s (geo_t_run)
# ---------------------------------------------------------------------------

MATHREF = BUILD / 'native' / 'math' / 'mathref'
SETUPS = BUILD / 'native' / 'levels' / 'setups'
REC_BANKS = (93,)                        # geomt.s's GEO_T_BANK (spare)
REC_FIRST = 0x0200
REC_SIZE = {0: 11, 1: 19, 2: 9}
BOXPLACE = 0x7C0600                      # the box (P_BoxOnLineSide)
FPLACE = 0x7C0700                        # posMul's factor
RAND_SEED = 2026100
EDGES32 = (0, 1, 0xFFFFFFFF, 0x7FFFFFFF, 0x80000000, 0x7FFF0000,
           0x80010000, 0xFFFF0000, 0x00010000, 0x0000FFFF)


def setup_of_map(gamemap: int) -> Path:
    """The tour's setup capture of the map (by its setup.json's gamemap:
    the tour does not take the maps in order), the one whose native setup
    is gameroutine's level base of the map."""
    for d in sorted(SETUPS.glob(GR.BASE_RUN + '-*')):
        p = d / 'setup.json'
        if p.exists() and json.loads(p.read_text())['gamemap'] == gamemap:
            if GR.base_path(gamemap).name != d.name + '.img':
                raise CheckError('E1M%d: the level base is %s, the setup %s'
                                 % (gamemap, GR.base_path(gamemap).name,
                                    d.name))
            return d
    raise CheckError('no setup capture of E1M%d in %s' % (gamemap, SETUPS))


def ram_of_map(gamemap: int) -> bytes:
    p = setup_of_map(gamemap) / 'r.ram.z'
    if not p.exists():
        raise CheckError('no %s (python3 tools/native/setupcap.py)' % p)
    return zlib.decompress(p.read_bytes())


class Ram:
    """A whole RAM (banks $00-$7F, $E0, $E1) for reading."""

    def __init__(self, data: bytes):
        self.data = data

    def read(self, address: int, n: int) -> bytes:
        bank = address >> 16
        i = bank if bank < 0x80 else 0x80 + bank - 0xE0
        a = i * 0x10000 + (address & 0xFFFF)
        return self.data[a:a + n]


def entry_text(case: GC.Case, key: str, ret: int) -> str:
    f = struct.unpack_from(HEADER_FORMAT, case.entry.header, 8)
    names = ('pc', 'pbr', 'dbr', 'a', 'x', 'y', 's', 'd', 'p', 'e')
    r = dict(zip(names, f[:10]))
    stack = case.entry.read((r['s'] + 1) & 0xFFFF, ret)
    return ('pc %06X\ndbr %02X\nd %04X\np %02X\ne %u\ns %04X\na %04X\n'
            'x %04X\ny %04X\nret %u\nstack %s\nswitches %s\n' % (
                table().address(key), r['dbr'], r['d'], r['p'], r['e'],
                r['s'], r['a'], r['x'], r['y'], ret,
                ' '.join('%02X' % b for b in stack),
                ' '.join('%02X' % b for b in f[10:14])))


def mathref_batch(ram: bytes, entry: str, spec: str, name: str,
                  cases: bytes, out_bytes: int) -> List[bytes]:
    work = tmpdir('ref')
    try:
        (work / 'ram.bin').write_bytes(ram)
        (work / 'entry.txt').write_text(entry)
        (work / 'spec.txt').write_text(spec)
        (work / 'cases.bin').write_bytes(cases)
        r = bounded.run([str(MATHREF), 'batch', str(work / 'ram.bin'),
                         str(work / 'entry.txt'), str(work / 'spec.txt'),
                         name, str(work / 'cases.bin'), str(work / 'out.bin')],
                        timeout=900, max_bytes=64 << 20,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode:
            raise CheckError('mathref batch failed: %s' % r.stdout[-600:])
        data = (work / 'out.bin').read_bytes()
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    k = out_bytes + 4
    return [data[i:i + out_bytes] for i in range(0, len(data), k)]


def native_batch(b, gamemap: int, kind: int, records: Sequence[bytes],
                 fill: int) -> List[bytes]:
    """The records through geo_t_run on the part's image, the map's level
    base: each record with its result."""
    size = REC_SIZE[kind]
    per = (0xC000 - REC_FIRST) // size
    if len(records) > per * len(REC_BANKS):
        raise CheckError('too many records for a run')
    img = G.Image(b, fill, store=True)
    img.recs += GR.base_records(gamemap)
    for i, bank in enumerate(REC_BANKS):
        chunk = b''.join(records[i * per:(i + 1) * per])
        if chunk:
            img.aux(bank, REC_FIRST, chunk)
    img.poke_label('geo_t_kind', bytes([kind]))
    img.poke_word('geo_t_count', len(records))
    work = tmpdir('nat')
    try:
        r = run_entry(img, work, 'geo_t_run', banks=REC_BANKS, cycles=40_000_000_000)
        if r.ended() != 'halt':
            stop = None
            if (work / 'crash.img').exists():
                stop = G.stop_codes(G.load_snapshot(work / 'crash.img'))
            raise CheckError('the native batch ended %s (stop %s)' % (
                r.ended(), stop))
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    out = []
    for i, _ in enumerate(records):
        bank = REC_BANKS[i // per]
        at = REC_FIRST + size * (i % per)
        out.append(bytes(m.aux[bank][at:at + size]))
    return out


def line_table(ram: Ram) -> List[Tuple[int, Dict[str, int]]]:
    return map_lines(ram)


def bounds(lines) -> Tuple[int, int, int, int]:
    xs = [ln['v1x'] for _, ln in lines] + [ln['v1x'] + ln['dx']
                                           for _, ln in lines]
    ys = [ln['v1y'] for _, ln in lines] + [ln['v1y'] + ln['dy']
                                           for _, ln in lines]
    return min(xs), min(ys), max(xs), max(ys)


def rand_point(rng: random.Random, ln: Dict[str, int], bb) -> Tuple[int, int]:
    m = rng.random()
    x0, y0 = ln['v1x'] << 16, ln['v1y'] << 16
    if m < 0.30:                                    # anywhere near the map
        x = rng.randint((bb[0] - 256) << 16, (bb[2] + 256) << 16)
        y = rng.randint((bb[1] - 256) << 16, (bb[3] + 256) << 16)
    elif m < 0.55:                                  # near the segment
        t = rng.random()
        x = x0 + int(t * ln['dx'] * 65536) + rng.randint(-4 << 16, 4 << 16)
        y = y0 + int(t * ln['dy'] * 65536) + rng.randint(-4 << 16, 4 << 16)
    elif m < 0.70:                                  # on the line, exactly
        j = rng.randint(-0x20000, 0x30000)
        x, y = x0 + j * ln['dx'], y0 + j * ln['dy']
    elif m < 0.82:                                  # a vertex's neighbours
        d = (0, 0, 1, -1, 0xFFFF, -0xFFFF, 0x10000, -0x10000, 0x8000)
        x, y = x0 + rng.choice(d), y0 + rng.choice(d)
    elif m < 0.92:                                  # the extremes
        x = rng.choice(EDGES32 + (rng.getrandbits(32),))
        y = rng.choice(EDGES32 + (rng.getrandbits(32),))
    else:
        x, y = rng.getrandbits(32), rng.getrandbits(32)
    return x & 0xFFFFFFFF, y & 0xFFFFFFFF


def rand_box(rng: random.Random, ln: Dict[str, int], bb) -> List[int]:
    m = rng.random()
    x0, y0 = ln['v1x'], ln['v1y']
    if m < 0.40:                                    # a thing near the line
        t = rng.random()
        n = max(abs(ln['dx']), abs(ln['dy'])) or 1
        s = rng.randint(-300, 300)
        cx = ((x0 << 16) + int(t * ln['dx'] * 65536) -
              s * ln['dy'] * 65536 // n + rng.randint(-0xFFFF, 0xFFFF))
        cy = ((y0 << 16) + int(t * ln['dy'] * 65536) +
              s * ln['dx'] * 65536 // n + rng.randint(-0xFFFF, 0xFFFF))
        r = rng.randint(0, 128) << 16 | rng.choice((0, rng.randint(0, 0xFFFF)))
        box = [cy + r, cy - r, cx - r, cx + r]
    elif m < 0.65:                                  # edges on v1's units
        def e(v):
            return (v + rng.randint(-2, 2) << 16) + rng.choice(
                (0, 0, 1, -1, 0x8000))
        box = [e(y0), e(y0), e(x0), e(x0)]
        box[0], box[1] = max(box[0], box[1]), min(box[0], box[1])
        box[2], box[3] = min(box[2], box[3]), max(box[2], box[3])
    elif m < 0.78:                                  # anywhere in the map
        cx = rng.randint(bb[0] << 16, bb[2] << 16)
        cy = rng.randint(bb[1] << 16, bb[3] << 16)
        r = rng.randint(1, 512) << 16
        box = [cy + r, cy - r, cx - r, cx + r]
    elif m < 0.90:                                  # the extremes
        box = [rng.choice(EDGES32 + (rng.getrandbits(32),))
               for _ in range(4)]
    else:                                           # anything
        box = [rng.getrandbits(32) for _ in range(4)]
    return [v & 0xFFFFFFFF for v in box]


def rand_map(b, gamemap: int, n: int, entries: Dict[str, GC.Case],
             fill: int, say=print) -> Dict[str, Any]:
    """n point-line and n box-line pairs on the map: upstream's answers
    against the native ones."""
    data = ram_of_map(gamemap)
    ram = Ram(data)
    lines = line_table(ram)
    bb = bounds(lines)
    rng = random.Random(RAND_SEED + gamemap)
    t = table()
    out: Dict[str, Any] = {}
    # point-line
    pc = entries['p_map65.s:P_PointOnLineSide']
    dpa = pc.regs_in['d'] + t.address('_Dp') - t.direct_page
    spec = ('routine P_PointOnLineSide %06X\nin a\nin x\nin %06X 8\n'
            'out a\n' % (t.address('p_map65.s:P_PointOnLineSide'), dpa))
    entry = entry_text(pc, 'p_map65.s:P_PointOnLineSide', 3)
    ins, recs, meta = bytearray(), [], []
    for i in range(n):
        li = rng.randrange(len(lines))
        lp, ln = lines[li]
        x, y = rand_point(rng, ln, bb)
        ins += struct.pack('<HHII', x & 0xFFFF, x >> 16, y, lp)
        recs.append(struct.pack('<IIHB', x, y, li, 0))
        meta.append((li, x, y))
    ref = mathref_batch(data, entry, spec, 'P_PointOnLineSide', bytes(ins),
                        2)
    got = []
    per = (0xC000 - REC_FIRST) // REC_SIZE[0] * len(REC_BANKS)
    for k in range(0, n, per):
        got += native_batch(b, gamemap, 0, recs[k:k + per], fill)
    bad = []
    paths: Dict[str, int] = {}
    for i in range(n):
        u = int.from_bytes(ref[i], 'little')
        v = got[i][10]
        li, x, y = meta[i]
        side, path = side_model(x, y, lines[li][1])
        paths[path] = paths.get(path, 0) + 1
        if u != v:
            bad.append({'line': li, 'x': '%08X' % x, 'y': '%08X' % y,
                        'upstream': u, 'native': v, 'path': path})
    out['points'] = {'pairs': n, 'failed': len(bad), 'first': bad[:5],
                     'paths': paths}
    # box-line
    bc = entries['p_map65.s:P_BoxOnLineSide']
    dpa = bc.regs_in['d'] + t.address('_Dp') - t.direct_page
    spec = ('routine P_BoxOnLineSide %06X\nin %06X 8\nin %06X 16\n'
            'out a\n' % (t.address('p_map65.s:P_BoxOnLineSide'), dpa,
                         BOXPLACE))
    entry = entry_text(bc, 'p_map65.s:P_BoxOnLineSide', 3)
    ins, recs, meta = bytearray(), [], []
    for i in range(n):
        li = rng.randrange(len(lines))
        lp, ln = lines[li]
        box = rand_box(rng, ln, bb)
        ins += struct.pack('<II', BOXPLACE, lp) + \
            b''.join(struct.pack('<I', v) for v in box)
        recs.append(b''.join(struct.pack('<I', v) for v in box) +
                    struct.pack('<HB', li, 0))
        meta.append((li, box))
    ref = mathref_batch(data, entry, spec, 'P_BoxOnLineSide', bytes(ins), 2)
    got = []
    per = (0xC000 - REC_FIRST) // REC_SIZE[1] * len(REC_BANKS)
    for k in range(0, n, per):
        got += native_batch(b, gamemap, 1, recs[k:k + per], fill)
    bad = []
    results: Dict[str, int] = {}
    for i in range(n):
        u = int.from_bytes(ref[i], 'little')
        v = got[i][18]
        li, box = meta[i]
        key = 'slope %d: %d' % (lines[li][1]['slope'], _s16(u))
        results[key] = results.get(key, 0) + 1
        if (u & 0xFF) != v or u not in (0, 1, 0xFFFF):
            bad.append({'line': li, 'box': ['%08X' % v_ for v_ in box],
                        'upstream': _s16(u), 'native': v})
    out['boxes'] = {'pairs': n, 'failed': len(bad), 'first': bad[:5],
                    'results': results}
    say('E1M%d: %d point-line pairs, %d failed; %d box-line pairs, %d '
        'failed' % (gamemap, n, out['points']['failed'], n,
                    out['boxes']['failed']), flush=True)
    return out


def rand_posmul(b, n: int, case: GC.Case, fill: int, say=print
                ) -> Dict[str, Any]:
    """n inputs of posMul (the edges first): upstream's posMul (its
    operand A and TM_L, its factor through [WK_LN],Y) against the native
    one (M_A, M_B)."""
    t = table()
    rng = random.Random(RAND_SEED)
    edges_v = (0, 1, 0xFFFFFF, 0x7FFFFF, 0x800000, 0x00FFFF, 0xFF0000,
               0x010000, 0x000100, 0x80FFFF)
    edges_f = (0, 1, 0xFFFF, 0x7FFF, 0x8000, 0x00FF, 0xFF00)
    vals = [(v, f) for v in edges_v for f in edges_f]
    while len(vals) < n:
        vals.append((rng.getrandbits(24), rng.getrandbits(16)))
    vals = vals[:n]
    wk = case.regs_in['d'] + t.address('DC_ENTRY') - t.direct_page
    spec = ('routine posMul %06X\nin a\nin %06X 2\nin y\nin %06X 4\n'
            'in %06X 2\nout a\nout x\n' % (t.address('p_map65.s:posMul'),
                                           t.address('TM_L'), wk, FPLACE))
    entry = entry_text(case, 'p_map65.s:posMul', 2)
    ins = bytearray()
    recs = []
    for v, f in vals:
        ins += struct.pack('<HHHIH', v & 0xFFFF, v >> 16, 0, FPLACE, f)
        recs.append(struct.pack('<HBH', v & 0xFFFF, v >> 16, f) + bytes(4))
    data = ram_of_map(1)
    ref = mathref_batch(data, entry, spec, 'posMul', bytes(ins), 4)
    got = []
    per = (0xC000 - REC_FIRST) // REC_SIZE[2] * len(REC_BANKS)
    for k in range(0, n, per):
        got += native_batch(b, 1, 2, recs[k:k + per], fill)
    bad = []
    for i, (v, f) in enumerate(vals):
        u = int.from_bytes(ref[i][0:2], 'little') | \
            int.from_bytes(ref[i][2:4], 'little') << 16
        w = int.from_bytes(got[i][5:9], 'little')
        # the truth: the low 32 bits of the signed product
        sv = v - (1 << 24) if v & 0x800000 else v
        sf = f - (1 << 16) if f & 0x8000 else f
        truth = (sv * sf) & 0xFFFFFFFF
        if u != w or u != truth:
            bad.append({'v': '%06X' % v, 'f': '%04X' % f,
                        'upstream': '%08X' % u, 'native': '%08X' % w,
                        'product': '%08X' % truth})
    say('posMul: %d inputs, %d failed' % (n, len(bad)), flush=True)
    return {'inputs': n, 'failed': len(bad), 'first': bad[:5],
            'edges': len(edges_v) * len(edges_f)}


def entry_cases() -> Dict[str, GC.Case]:
    out = {}
    for key in ('p_map65.s:P_PointOnLineSide', 'p_map65.s:P_BoxOnLineSide',
                'p_map65.s:posMul'):
        out[key] = first_case(key)
    return out


def _rand_job(job) -> Dict[str, Any]:
    obj, gamemap, n, fill = job
    b = load_build(Path(obj))
    return rand_map(b, gamemap, n, entry_cases(), fill, say=lambda *a, **k:
                    None)


def rand_all(obj: Path = OUT, n: int = 100_000, maps=range(1, 10),
             jobs: int = JOBS, say=print) -> Dict[str, Any]:
    out: Dict[str, Any] = {'maps': {}}
    work = [(str(obj), m, n, FILLS[m % 2]) for m in maps]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for m, r in zip(maps, pool.map(_rand_job, work)):
            out['maps']['E1M%d' % m] = r
            say('E1M%d: %d point-line pairs, %d failed; %d box-line pairs, '
                '%d failed' % (m, n, r['points']['failed'], n,
                               r['boxes']['failed']), flush=True)
    b = load_build(obj)
    out['posMul'] = rand_posmul(b, n, entry_cases()['p_map65.s:posMul'],
                                FILLS[0], say)
    return out


# ---------------------------------------------------------------------------
# Building: the part's image, and a planted one from a scratch copy
# ---------------------------------------------------------------------------

PLANT_FILES = G.PLANT_COPY     # (every part's fragment: wave 1 as integrated)


def build(source: Path = SRC, game: Optional[Path] = None) -> Path:
    """make -f game.mk part P=geom (source: the tree's src/native or a
    scratch copy of it; game: its GAME directory): the image's directory.
    A warning fails it."""
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
    """The part's image built from a scratch copy in tmp (game.mk, the
    part's own files, each (file, old, new) of bugs applied once; the rest
    of the sources from the tree through game.mk's vpath): its
    directory."""
    src = tmp / 'src'
    part = SRC / 'game' / PART
    for f in PLANT_FILES:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
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


# ---------------------------------------------------------------------------
# The report (report.json)
# ---------------------------------------------------------------------------

BUDGET = {'up': 1707, 'native': 2200}
GAME_MODULES = ('geom', 'giter')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    b = load_build(obj)
    ms = G.module_sizes(b)
    game = sum(ms.get(m, 0) for m in GAME_MODULES)
    return {'modules': {m: ms.get(m, 0) for m in GAME_MODULES + ('geomt',)},
            'native_bytes': game, 'budget': BUDGET['native'],
            'upstream_bytes': BUDGET['up'],
            'over_budget_pct': round(100.0 * (game - BUDGET['native']) /
                                     BUDGET['native'], 1),
            'test_driver_bytes': G.module_bytes(b, 'geomt'),
            'routines': routine_sizes(b)}


def routine_sizes(b) -> Dict[str, int]:
    """Each entry's bytes: the part's modules' bytes in each segment (the
    map's module list), split among the entries placed there by their
    addresses."""
    text = (b.obj / (b.name + '.map')).read_text()
    text = text.split('Modules list:', 1)[-1].split('Segment list:', 1)[0]
    module, segs = None, []
    for line in text.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module in GAME_MODULES and f and (f[0] in ('GCORE', 'LOADW') or
                                              f[0].startswith('GGRP')):
            start = next(int(x[5:], 16) for x in f if x.startswith('Offs='))
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            lo = b.segments[f[0]][0] + start
            segs.append((f[0], lo, lo + size))
    names = [GL.native_names()[k] for k in ENTRIES]
    out = {}
    for seg, lo, hi in segs:
        here = sorted((b.labels[n], n) for n in names
                      if lo <= b.labels[n] < hi and
                      seg_of(b, n) in (seg, 'LOADW' if seg == 'GCORE'
                                       else seg))
        for i, (a, n) in enumerate(here):
            out[n] = (here[i + 1][0] if i + 1 < len(here) else hi) - a
    return out


def seg_of(b, name: str) -> str:
    """The segment of a routine: its group's (several groups share a
    slot's addresses)."""
    g = entry_group(b, name)
    return 'GCORE' if g == 0 else 'GGRP%d' % g


def _stats(xs: Sequence[float]) -> Optional[Dict[str, float]]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return {'median': xs[len(xs) // 2], 'worst': xs[-1], 'n': len(xs)}


def _classes(results: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in results:
        c = r.get('class', '?')
        out[c] = out.get(c, 0) + 1
    return out


def summarise(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    from a2vm import costs
    mhz = {p: costs.parameters(p)['fabric_mhz'] for p in PROFILES}
    out: Dict[str, Any] = {
        'runs': len(results),
        'cases': len({(r.get('case'), r.get('run')) for r in results}),
        'synthetic_cases': len({r.get('case') for r in results
                                if r.get('synthetic')}),
        'failures': sum(1 for r in results if failed(r)),
        'classes': _classes(results),
        'stray_writes': sum(r.get('stray_n', 0) for r in results),
        'lowest_s': min((r['lowest_s'] for r in results
                         if r.get('lowest_s') is not None), default=None),
        'cycles': _stats([r.get('cycles') for r in results]),
        'us': {p: _stats([round(r['clocks'] / mhz[p], 2) for r in results
                          if r.get('profile') == p and r.get('clocks')])
               for p in PROFILES}}
    paths: Dict[str, int] = {}
    for r in results:
        if r.get('profile') == PROFILES[0] and r.get('fill') == '%02x' % \
                FILLS[0]:
            for p in r.get('paths', []):
                paths[p] = paths.get(p, 0) + 1
    out['paths'] = paths
    out['first_failures'] = [{k: v for k, v in r.items() if k != 'paths'}
                             for r in results if failed(r)][:5]
    return out


def report(run_res: Dict[str, List[Dict[str, Any]]],
           iter_res: Optional[List[Dict[str, Any]]],
           rand_res: Optional[Dict[str, Any]], obj: Path = OUT
           ) -> Dict[str, Any]:
    sel = load_select()
    rep: Dict[str, Any] = {'format': 'game-part-report 1', 'part': PART,
                           'wave': 1, 'entries': {}, 'sizes': sizes(obj),
                           'fills': ['%02X' % f for f in FILLS],
                           'profiles': list(PROFILES),
                           'exclusions': [n for n, _, _ in
                                          gcanon.ROUTINE_EXCLUSIONS]}
    for key in ENTRIES:
        e = sel['entries'].get(key, {})
        res = run_res.get(key, [])
        s = summarise(res)
        s['survey_calls'] = e.get('calls', 0)
        s['eligible'] = e.get('eligible', 0)
        s['chosen'] = sum(1 for calls in e.get('chosen', {}).values()
                          for _, _, role in calls if role == 'check')
        s['paths_declared'] = PATHS.get(key, [])
        s['paths_not_taken'] = [p for p in PATHS.get(key, [])
                                if p not in s['paths']]
        rep['entries'][key] = s
    if iter_res is not None:
        by: Dict[str, Any] = {}
        for key in ITERATORS:
            rs = [r for r in iter_res if r.get('routine') == key]
            by[key] = {'runs': len(rs), 'cases': len({(r.get('case'),
                                                       r.get('run'))
                                                      for r in rs}),
                       'failures': sum(1 for r in rs if not r.get('ok')),
                       'callbacks_recorded': sum(r.get('recorded', 0)
                                                 for r in rs),
                       'stop_runs': sum(1 for r in rs if r.get('stop')),
                       'stray_writes': sum(r.get('stray_n', 0) for r in rs),
                       'first_failures': [r for r in rs
                                          if not r.get('ok')][:3]}
        rep['iterators_recording'] = by
    if rand_res is not None:
        rep['random'] = rand_res
    rep['failures'] = sum(v['failures'] for v in rep['entries'].values()) + \
        sum(v['failures'] for v in rep.get('iterators_recording',
                                           {}).values()) + \
        (sum(m['points']['failed'] + m['boxes']['failed'] for m in
             rand_res['maps'].values()) + rand_res['posMul']['failed']
         if rand_res else 0)
    return rep


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def save(name: str, data: Any) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_text(json.dumps(data, indent=1) + '\n')
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--select', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--synth', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--iter', action='store_true')
    parser.add_argument('--rand', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--entries', default='')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--n', type=int, default=100_000)
    parser.add_argument('--maps', default='1,2,3,4,5,6,7,8,9')
    parser.add_argument('--jobs', type=int, default=JOBS)
    parser.add_argument('--obj', type=Path, default=OUT)
    a = parser.parse_args(argv)
    import geom_check as M      # (the workers import the module by name)
    missing = need()
    if missing:
        print('geom_check: %s' % missing)
        return 2
    entries = [e if ':' in e else 'p_map65.s:' + e
               for e in a.entries.split(',') if e]
    bad = 0
    if a.select or a.all:
        p = save('select.json', M.select())
        print('the selection: %s' % p)
    if a.capture or a.all:
        M.capture(entries, a.jobs)
    if a.synth or a.all:
        M.make_synth()
    if a.run or a.all:
        res = M.check_cases(entries, a.obj, a.jobs, a.limit, a.sample)
        save('run.json', res)
        bad += sum(1 for rs in res.values() for r in rs if failed(r))
    if a.iter or a.all:
        it = M.iter_cases(a.obj, a.jobs, a.sample)
        save('iter.json', it)
        bad += sum(1 for r in it if not r.get('ok'))
    if a.rand or a.all:
        rr = M.rand_all(a.obj, a.n, [int(x) for x in a.maps.split(',')],
                        a.jobs)
        save('rand.json', rr)
        bad += sum(m['points']['failed'] + m['boxes']['failed']
                   for m in rr['maps'].values()) + rr['posMul']['failed']
    if a.report or a.all:
        def load(name):
            p = OUT / name
            return json.loads(p.read_text()) if p.exists() else None
        rep = M.report(load('run.json') or {}, load('iter.json'),
                       load('rand.json'), a.obj)
        p = save('report.json', rep)
        print('the report: %s (%d failures)' % (p, rep['failures']))
        bad += rep['failures']
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
