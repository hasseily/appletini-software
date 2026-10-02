#!/usr/bin/env python3
"""Part s2draw's cases (docs/SCREENS.md 7.3, docs/m11-parts/s2draw.md):
upstream's 2D drawers run alone on ref816 as the truth, the native drawers
of src/native/s2_draw.s and s2_pub.s run on a2vm under the test driver
(the test image s2dt, src/native/s2_drawt.s), and the comparison.

The truth (ref816 --call, on a state of the release in play):

  synthetic   the base state (the tour's 50th call of
              V_DrawNumPatchNotScaled, captured once into
              build/native/m11/s2draw/base.img) with a background set
              poked: a screen of random bytes in the back buffer, marks
              before, 16 random nibble tables and each row's pages (8 of
              the 16 palettes, consistent tables), random CAPVAL, CAPMSK;
              then a case's own pokes: its source in bank $7E, the
              arguments. IIGS_DrawPatch and V_DrawPatchNotScaled of every
              2D patch of DOOM1.WAD (ST*, M_*, WI*) at four positions with
              both x parities and clipped at each edge, half of them
              recording CAPVAL and CAPMSK; V_DrawRaw of STBAR's lump (the
              resident lump, its bytes poked) at whole-row offsets;
              V_DrawBackground of four flats (poked over a resident lump);
              I_RestoreStatusRect over a random STCACHE.
  captured    calls of a run (`--capture`): V_DrawPatchNotScaled (the
              HUD's text, the menus), V_DrawNumPatchNotScaled (the status
              bar), V_DrawNumPatchScaled (the intermission), V_DrawRaw,
              V_DrawBackground and I_RestoreStatusRect of the tour, each
              run again alone by --call on its entry.

A case's truth is the back buffer, the marks and CAPVAL, CAPMSK after the
call in the rows the case can reach, and whether every other byte of them
kept its value. The native run draws each case into bands (at most 32
rows, 10 when it records) cut at varying rows, each band's rows, marks,
nibble slots and row tables loaded from RamWorks, and writes each band
back to RamWorks; every band's bytes and marks must equal the truth's.

The publish: bands of random bytes and random marks, published in one
frame; the screen after equals a host copy (tools/native/s2draw.py's
`publish`), the write log has no stray write, and s2_begin (the stand-in
s2_beginstub.s) runs once, before the first band store.

Usage:  python3 tools/native/s2drawcase.py [--limit N] [--profile f121]
        (every case: the truth, the model against it, the native runs)
"""

import argparse
import hashlib
import json
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import s2check as C2, s2draw as D, s2layout as S, \
    s2run as SR  # noqa: E402
from native import rendercap as RC  # noqa: E402
from ref816 import bounded, lumps, make_image, refimage, script, \
    title  # noqa: E402

OUT = SR.M11 / 's2draw'
BASE = OUT / 'base.img'
TRUTH = OUT / 'truth'
CAPTURED = OUT / 'captured'
FORMAT = 's2draw-truth 1'
JOBS = 2
CALL_TIMEOUT = 60.0
CAPTURE_TIMEOUT = 1200.0
MAX_FILE = 64 << 20
SEED = 0x2D2D

# upstream's places [R memmap.inc, i_viigs65.s, patch65.s]
SHRBUF = 0x012000
STCACHE = 0x01A200
NIBTAB = 0x0B8000
CAPVAL = 0x266000               # + the buffer address ($2000-$9CFF)
CAPMSK = 0x256000
MM_WAD = 0x100000
SRC_AT = 0x7E0000               # a synthetic case's source
ST_ROWS = 168

# the native test image's places (src/native/s2_drawt.s)
DESC_BANK = 50
R_BANK = 80
BG_FIRST = 51
SRC_BANKS = range(10, 50)
SRC_LO, SRC_END = 0x0200, 0xBC00
SLOT_PAGE = 0x98                # P2DW's eight nibble slots at $9800
SLOTS = 8
BAND_ROWS = 32
CAP_ROWS = 10
MARK = 0xA5FF                   # (R_BANK) the case's number
MAX_SETS = (R_BANK - BG_FIRST) // 4
PUB_A_RUN = 16                  # publish cases a run (a bank each)
S2ZP = (0x48, 0x82)             # s2.inc's S2_* and the test image's
W_RUNTIME = (0x8300, 0xC000)    # P2DW's runtime W
W_BAND = (0x8300, 0x9700)       # the band (and CAPVAL, CAPMSK in it)
PHASE = 0x0300
KIND = {'patch': 0, 'vpatch': 1, 'raw': 2, 'back': 3, 'rect': 4}
CASES_A_RUN = 32
CAPTURED_A_RUN = 7
CAPTURE_CHUNK = 10              # entries a capture run (6.6 MB each)
SET_BANKS = 4                   # a background set's banks


class CaseError(Exception):
    pass


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------

_SYM = None


def sym() -> script.Symbols:
    global _SYM
    if _SYM is None:
        with open(str(make_image.LINKMAP)) as handle:
            _SYM = script.Symbols(json.load(handle))
    return _SYM


def at(name: str) -> int:
    return sym().address(name)


def places() -> Dict[str, int]:
    v = 'i_viigs65.s:'
    p = {'dp': at('crt0.s:_Dp'), 'px': at('patch65.s:PX'),
         'capture': at('patch65.s:iigs_capture'),
         'caplo': at('patch65.s:CAPLO'), 'caphi': at('patch65.s:CAPHI'),
         'patch': at('patch65.s:IIGS_DrawPatch')}
    for n in ('DRB', 'DRE', 'DRY0', 'DRY1', 'iigs_rowpageL', 'iigs_rowpageR',
              'iigs_rowbase', 'stcachenum', 'VP_Y0', 'VP_REC',
              'V_DrawPatchNotScaled', 'V_DrawRaw', 'V_DrawBackground',
              'I_RestoreStatusRect'):
        p[n] = at(v + n)
    p['V_DrawNumPatchNotScaled'] = at('r_data65.s:V_DrawNumPatchNotScaled')
    p['V_DrawNumPatchScaled'] = at('r_data65.s:V_DrawNumPatchScaled')
    return p


# ---------------------------------------------------------------------------
# ref816
# ---------------------------------------------------------------------------

def capture_run(spec: str, routine: int, hits: Sequence[int], work: Path
                ) -> Path:
    """ref816 --capture of the calls `hits` of `routine` in the coverage
    run `spec`: the capture directory."""
    RC.check_disk(work)
    s = sym()
    prog = RC.program(RC.RunSpec(spec, spec, None, ()), s, work)
    (work / 'input.txt').write_text(prog)
    cap = work / 'cap'
    cap.mkdir()
    extra = ['--capture', str(cap), '--capture-entry', '%06X' % routine]
    for h in hits:
        extra += ['--capture-hit', str(h)]
    command = RC.machine_command(work / 'input.txt', work, s,
                                 RC.limit_seconds(RC.RunSpec(spec, spec, None,
                                                             ())), extra)
    result = bounded.run(command, timeout=CAPTURE_TIMEOUT,
                         max_bytes=256 << 20, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode:
        raise CaseError('the capture of %s failed: %s'
                        % (spec, result.stderr[-800:]))
    return cap


def ensure_base() -> Path:
    """build/native/m11/s2draw/base.img: all RAM at the tour's 50th call
    of V_DrawNumPatchNotScaled (a level frame's status bar)."""
    if BASE.exists():
        return BASE
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tmp-m11-s2draw-base-',
                                 dir=str(SR.BUILD)))
    try:
        cap = capture_run('tour', places()['V_DrawNumPatchNotScaled'], [50],
                          work)
        tmp = BASE.with_suffix('.tmp')
        shutil.copy(str(cap / 'hit-00000050' / 'entry.img'), str(tmp))
        tmp.replace(BASE)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return BASE


def call(base: Path, loads: Sequence[Path], routine: int,
         regs: Dict[str, int], saves: Sequence[Tuple[int, int]], work: Path
         ) -> Tuple[Dict[str, Any], List[bytes]]:
    """ref816 --call of `routine` on `base` and the `loads`: its final
    state and the `saves` (address, length) after it."""
    command = [str(title.MACHINE), str(base)]
    for p in loads:
        command += ['--load-image', str(p)]
    for k, v in regs.items():
        command += ['--reg', '%s=%X' % (k, v)]
    files = []
    for k, (address, length) in enumerate(saves):
        path = work / ('save-%d.bin' % k)
        files.append(path)
        command += ['--save', '%06X:%d:%s' % (address, length, path)]
    command += ['--call', '%06X' % routine, '--cycles', '50000000']
    result = bounded.run(command, timeout=CALL_TIMEOUT, max_bytes=MAX_FILE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True)
    if result.returncode:
        raise CaseError('--call failed (%d): %s' % (result.returncode,
                                                   result.stderr[-800:]))
    state = json.loads(result.stdout)
    if state.get('end', {}).get('reason') != 'return':
        raise CaseError('--call did not return: %s' % state.get('end'))
    data = [p.read_bytes() for p in files]
    for p in files:
        p.unlink()
    return state, data


def write_pokes(path: Path, records: Sequence[Tuple[int, bytes]]) -> None:
    regs = make_image.Registers(pc=0, pbr=0, dbr=0, a=0, x=0, y=0, s=0,
                                d=0, p=0, e=0)
    path.write_bytes(refimage.image_bytes(
        regs, refimage.Switches(0, 0, 0, 0), records))


# ---------------------------------------------------------------------------
# A background set: the state before a case
# ---------------------------------------------------------------------------

class State(NamedTuple):
    buf: bytes                  # the back buffer, 32,000
    drb: bytes
    dre: bytes
    dry: Tuple[int, int]
    tables: D.Tables
    capval: bytes               # CAPVAL, CAPMSK by the buffer offset
    capmsk: bytes
    stcache: bytes              # 5,120


def random_state(rng: random.Random) -> State:
    buf = bytes(rng.getrandbits(8) for _ in range(D.SCREEN))
    drb = bytearray(D.ROWS)
    dre = bytearray(D.ROWS)
    for r in range(D.ROWS):             # about one row in four marked
        if rng.random() < 0.25:
            a = rng.randrange(160)
            drb[r], dre[r] = a, rng.randrange(a + 1, 161)
    rows = [r for r in range(D.ROWS) if dre[r]]
    dry = (rows[0], rows[-1] + 1) if rows else (0, 0)
    nib = bytes(rng.getrandbits(8) for _ in range(16 * 1024))
    pals = rng.sample(range(16), SLOTS)
    rowl = bytes(rng.choice(pals) * 4 + (r & 1) for r in range(D.ROWS))
    tables = D.Tables(nib, rowl, bytes(p + 2 for p in rowl),
                      tuple(p << 8 for p in rowl))
    capval = bytes(rng.getrandbits(8) for _ in range(D.SCREEN))
    capmsk = bytes(rng.getrandbits(8) for _ in range(D.SCREEN))
    stcache = bytes(rng.getrandbits(8) for _ in range(ST_ROWS * 0 + 5120))
    return State(buf, bytes(drb), bytes(dre), dry, tables, capval, capmsk,
                 stcache)


def state_records(st: State, p: Dict[str, int]) -> List[Tuple[int, bytes]]:
    rb = b''.join(struct.pack('<H', v) for v in st.tables.rowbase)
    return [(SHRBUF, st.buf), (p['DRB'], st.drb), (p['DRE'], st.dre),
            (p['DRY0'], struct.pack('<H', st.dry[0])),
            (p['DRY1'], struct.pack('<H', st.dry[1])),
            (NIBTAB, st.tables.nibtab), (p['iigs_rowpageL'], st.tables.rowl),
            (p['iigs_rowpageR'], st.tables.rowr), (p['iigs_rowbase'], rb),
            (CAPVAL + 0x2000, st.capval), (CAPMSK + 0x2000, st.capmsk),
            (STCACHE, st.stcache)]


def state_of(mem: refimage.Memory, p: Dict[str, int]) -> State:
    """The state before a captured call, from its entry's RAM."""
    rb = tuple(mem.word(p['iigs_rowbase'] + 2 * r) for r in range(D.ROWS))
    return State(mem.get(SHRBUF, D.SCREEN), mem.get(p['DRB'], D.ROWS),
                 mem.get(p['DRE'], D.ROWS),
                 (mem.word(p['DRY0']), mem.word(p['DRY1'])),
                 D.Tables(mem.get(NIBTAB, 16384),
                          mem.get(p['iigs_rowpageL'], D.ROWS),
                          mem.get(p['iigs_rowpageR'], D.ROWS), rb),
                 mem.get(CAPVAL + 0x2000, D.SCREEN),
                 mem.get(CAPMSK + 0x2000, D.SCREEN),
                 mem.get(STCACHE, 5120))


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

class Case(NamedTuple):
    name: str
    kind: str                   # patch, vpatch, raw, back, rect
    source: bytes
    x: int                      # patch: x; raw: the first row; rect: y0
    y: int                      # patch: y; raw: the row after; rect: y1
    b0: int                     # rect: the bytes
    b1: int
    cap: bool
    rows: Tuple[int, int]       # the rows the case can change
    src_row0: int               # rect: the source's offset of screen row 0
    truth: Dict[str, Any]       # after: rows' bytes, marks, CAPVAL/MSK


def touched(kind: str, source: bytes, x: int, y: int) -> Tuple[int, int]:
    """The rows a case can change, and where none: a band beside the
    screen's edge it crosses, so that the native clip still runs."""
    if kind in ('patch', 'vpatch'):
        if kind == 'vpatch':
            x, y = D.vpatch_position(source, x, y)
        h = D.u16(source, 2)
        sy = D.s16(y)
        a, b = max(sy, 0), min(sy + h, 200)
        if a < b:
            return a, b
        return (0, 8) if sy < 0 else (192, 200)
    if kind == 'raw':
        return x, min(y, 200)
    if kind == 'back':
        return 0, 200
    return x, y


def bands_of(case_index: int, rows: Tuple[int, int], cap: bool,
             tables: D.Tables) -> List[Tuple[int, int, List[int]]]:
    """The case's bands: at most 32 rows (10 recording), the first cut at
    a row that varies with the case, each with at most 8 palettes."""
    top = BAND_ROWS if not cap else CAP_ROWS
    a, b = rows
    out = []
    first = 1 + (case_index * 7) % top
    while a < b:
        n = min(first, b - a)
        first = top
        out += split_palettes(a, a + n, tables)
        a += n
    return out


def split_palettes(a: int, b: int, t: D.Tables
                   ) -> List[Tuple[int, int, List[int]]]:
    pals = sorted({t.rowl[r] >> 2 for r in range(a, b)} |
                  {t.rowr[r] >> 2 for r in range(a, b)})
    if len(pals) <= SLOTS:
        return [(a, b, pals)]
    m = (a + b) // 2
    return split_palettes(a, m, t) + split_palettes(m, b, t)


# -- synthetic cases --------------------------------------------------------

def positions(w: int, h: int, k: int) -> List[Tuple[str, int, int]]:
    """Four positions on the screen (two even x, two odd), then clipped at
    the left, right, top and bottom edges (parities alternating)."""
    xa = max(0, (320 - w) // 4) & ~1
    xb = max(0, (320 - w) * 3 // 4) & ~1
    ya = max(0, (200 - h) // 4)
    yb = max(0, (200 - h) * 3 // 4)
    p = k & 1
    return [('in-even', xa, ya), ('in-odd', xa + 1, yb),
            ('in-even2', xb, yb), ('in-odd2', xb + 1, ya),
            ('left', -(w // 2) - p, ya), ('right', 320 - w // 2 + p, yb),
            ('top', xb + p, -(h // 2)), ('bottom', xa + 1 - p, 200 - h // 2)]


def synthetic_inputs(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Every synthetic case's inputs (no truth yet), in a fixed order."""
    wad = lumps.read_wad()
    patches = D.wad_patches()
    out: List[Dict[str, Any]] = []
    k = 0
    for name, data in patches.items():
        longest = max(D.column_bytes(data, o) for o in D.columns(data))
        if longest > D.COLUMN_LIMIT:
            continue                    # WIMAP0: a picture in the release
        w, h = D.u16(data, 0), D.u16(data, 2)
        for where, x, y in positions(w, h, k):
            kind = 'vpatch' if k & 2 else 'patch'
            if kind == 'vpatch':        # the same place, offsets applied
                x += D.s16(D.u16(data, 4))
                y += D.s16(D.u16(data, 6))
            out.append({'name': '%s-%s' % (name, where), 'kind': kind,
                        'lump': name, 'x': x & 0xFFFF, 'y': y & 0xFFFF,
                        'cap': bool(k % 3 == 0) and h <= 2 * CAP_ROWS * 4})
            k += 1
    rng = random.Random(SEED)
    stbar = bytes(rng.getrandbits(8) for _ in range(10240))
    for row in (0, 1, 50, 99, 168, 170, 180):
        out.append({'name': 'STBAR-raw-%d' % row, 'kind': 'raw',
                    'data': stbar, 'x': row, 'y': row + 32, 'cap': False})
    for flat in ('FLOOR4_8', 'FLAT5_4', 'CEIL3_5', 'FLOOR7_2'):
        if flat in wad and len(wad[flat]) == 4096:
            out.append({'name': flat + '-back', 'kind': 'back',
                        'data': wad[flat], 'x': 0, 'y': 0, 'cap': False})
    for k2 in range(24):                # I_RestoreStatusRect
        x = rng.randrange(-40, 330)
        y = rng.randrange(150, 210)
        out.append({'name': 'strect-%d' % k2, 'kind': 'strect',
                    'x': x, 'y': y, 'w': rng.randrange(1, 120),
                    'h': rng.randrange(1, 40), 'cap': False})
    if limit:
        out = out[:limit]
    return out


def lump_data(inp: Dict[str, Any], patches: Dict[str, bytes]) -> bytes:
    return inp['data'] if 'data' in inp else patches[inp['lump']]


def resident(mem: refimage.Memory, name: str) -> Tuple[int, int, int]:
    """A resident lump of the WAD in RAM: (number, address, size)."""
    ident, count, _, start = struct.unpack('<4shhi', mem.get(MM_WAD, 12))
    if ident != b'IWAD':
        raise CaseError('no WAD at MM_WAD')
    for i in range(count):
        pos, size, _, raw = struct.unpack('<IHH8s',
                                          mem.get(MM_WAD + start + 16 * i,
                                                  16))
        if raw.rstrip(b'\0').decode('latin-1') == name:
            return i, MM_WAD + pos, size
    raise CaseError('no lump %s' % name)


def synthetic_truth(inputs: List[Dict[str, Any]], work: Path
                    ) -> List[Case]:
    """The truth of the synthetic cases: CASES_A_RUN a background set."""
    p = places()
    base = ensure_base()
    mem = refimage.load(refimage.read(base))
    regs0 = refimage.read(base).registers
    stbar_num, stbar_at, _ = resident(mem, 'STBAR')
    patches = D.wad_patches()
    groups = [inputs[i:i + CASES_A_RUN]
              for i in range(0, len(inputs), CASES_A_RUN)]

    def one_group(g: int) -> List[Case]:
        rng = random.Random(SEED * 1000 + g)
        st = random_state(rng)
        gw = work / ('g%03d' % g)
        gw.mkdir()
        set_img = gw / 'set.img'
        write_pokes(set_img, state_records(st, p))
        out = []
        for i, inp in enumerate(groups[g]):
            out.append(one_truth(inp, st, set_img, p, regs0, stbar_num,
                                 stbar_at, patches, gw, g * CASES_A_RUN + i))
        shutil.rmtree(str(gw), ignore_errors=True)
        return out

    with ThreadPoolExecutor(max_workers=JOBS) as pool:
        results = list(pool.map(one_group, range(len(groups))))
    return [c for r in results for c in r]


def one_truth(inp, st: State, set_img: Path, p, regs0, stbar_num: int,
              stbar_at: int, patches, gw: Path, index: int) -> Case:
    kind = inp['kind']
    pokes: List[Tuple[int, bytes]] = [
        (p['capture'], struct.pack('<H', 1 if inp['cap'] else 0)),
        (p['caplo'], struct.pack('<HH', 0xFFFF, 0))]
    regs: Dict[str, int] = {}
    b0 = b1 = 0
    src_row0 = 0
    if kind in ('patch', 'vpatch'):
        source = lump_data(inp, patches)
        pokes += [(SRC_AT, source),
                  (p['dp'], struct.pack('<HHI', inp['y'], 0, SRC_AT))]
        regs['a'] = inp['x']
        routine = p['patch'] if kind == 'patch' else \
            p['V_DrawPatchNotScaled']
        x, y = inp['x'], inp['y']
    elif kind == 'raw':
        source = inp['data']
        pokes += [(stbar_at, source), (p['stcachenum'], b'\xff\xff'),
                  (p['dp'], struct.pack('<H', inp['x'] * 320))]
        regs['a'] = stbar_num
        routine = p['V_DrawRaw']
        x, y = inp['x'], inp['y']
    elif kind == 'back':
        source = inp['data']
        pokes += [(stbar_at, source)]
        regs['a'] = stbar_num
        routine = p['V_DrawBackground']
        x = y = 0
    else:                               # I_RestoreStatusRect
        source = st.stcache
        pokes += [(p['dp'], struct.pack('<HHH', inp['y'] & 0xFFFF, 0,
                                        inp['w'])),
                  (regs0.s + 4, struct.pack('<H', inp['h']))]
        regs['a'] = inp['x'] & 0xFFFF
        routine = p['I_RestoreStatusRect']
        kind = 'rect'
        src_row0 = -ST_ROWS * D.ROW
    case_img = gw / ('c%d.img' % index)
    write_pokes(case_img, pokes)
    saves = [(SHRBUF, D.SCREEN), (p['DRB'], D.ROWS), (p['DRE'], D.ROWS),
             (CAPVAL + 0x2000, D.SCREEN), (CAPMSK + 0x2000, D.SCREEN),
             (p['VP_Y0'], 8)]
    state, data = call(BASE, [set_img, case_img], routine, regs, saves, gw)
    case_img.unlink()
    if kind == 'rect':
        vy0, vy1, vb0, vb1 = struct.unpack('<hhhh', data[5])
        if D.rect_empty(vy0, vy1, vb0, vb1):
            x, y, b0, b1 = ST_ROWS, ST_ROWS, 0, 0
        else:
            x, y, b0, b1 = vy0, vy1, vb0, vb1
    rows = touched(kind, source, x, y)
    truth = truth_of(st, data, rows, inp['cap'], state)
    return Case(inp['name'], kind, source, x, y, b0, b1, inp['cap'], rows,
                src_row0, truth)


def truth_of(st: State, data: List[bytes], rows: Tuple[int, int],
             cap: bool, state: Dict[str, Any]) -> Dict[str, Any]:
    """The after state in `rows`, and what changed outside them."""
    buf, drb, dre, capval, capmsk = data[:5]
    a, b = rows
    outside = []
    for name, before, after, width in (
            ('pixels', st.buf, buf, D.ROW), ('DRB', st.drb, drb, 1),
            ('DRE', st.dre, dre, 1), ('CAPVAL', st.capval, capval, D.ROW),
            ('CAPMSK', st.capmsk, capmsk, D.ROW)):
        for r in list(range(0, a)) + list(range(b, D.ROWS)):
            if before[r * width:(r + 1) * width] != \
                    after[r * width:(r + 1) * width]:
                outside.append('%s row %d' % (name, r))
                break
    if not cap and (capval != st.capval or capmsk != st.capmsk):
        outside.append('CAPVAL/CAPMSK written without iigs_capture')
    return {'pixels': buf[a * D.ROW:b * D.ROW], 'drb': drb, 'dre': dre,
            'capval': capval[a * D.ROW:b * D.ROW] if cap else b'',
            'capmsk': capmsk[a * D.ROW:b * D.ROW] if cap else b'',
            'outside': outside, 'cycles': state.get('cycles', 0)}


# -- the model against the truth --------------------------------------------

def model_after(c: Case, st: State) -> Dict[str, Any]:
    """tools/native/s2draw.py's result of the case (upstream's rules)."""
    buf = bytearray(st.buf)
    m = D.Marks(st.drb, st.dre, *st.dry)
    cap = D.Capture(st.capval, st.capmsk) if c.cap else None
    if c.kind in ('patch', 'vpatch'):
        x, y = (c.x, c.y) if c.kind == 'patch' else \
            D.vpatch_position(c.source, c.x, c.y)
        D.draw_patch(buf, m, c.source, x, y, st.tables, cap)
    elif c.kind == 'raw':
        D.draw_raw(buf, m, c.source, c.x * 320, (c.y - c.x) * 320,
                   st.tables)
    elif c.kind == 'back':
        D.draw_back(buf, m, c.source, st.tables)
    else:
        def row(r):
            o = (r * D.ROW + c.src_row0) % 0x10000
            return c.source[o:o + D.ROW]
        D.copy_rect(buf, m, row, c.x, c.y, c.b0, c.b1)
    a, b = c.rows
    return {'pixels': bytes(buf[a * D.ROW:b * D.ROW]), 'drb': bytes(m.drb),
            'dre': bytes(m.dre),
            'capval': bytes(cap.val[a * D.ROW:b * D.ROW]) if cap else b'',
            'capmsk': bytes(cap.msk[a * D.ROW:b * D.ROW]) if cap else b''}


def model_problems(c: Case, st: State) -> List[str]:
    m = model_after(c, st)
    out = ['%s: the model\'s %s differs from ref816\'s' % (c.name, k)
           for k in ('pixels', 'drb', 'dre', 'capval', 'capmsk')
           if m[k] != c.truth[k]]
    out += ['%s: ref816 changed %s outside its rows' % (c.name, o)
            for o in c.truth['outside']]
    return out


# ---------------------------------------------------------------------------
# The native runs
# ---------------------------------------------------------------------------

class Packer:
    """Sources into the banks 10-49, in $0200-$BFFF (a RAMRD window reaches
    no other byte of a bank) and ending 1 KB before $C000 (the fetch buffer
    reads up to 1 KB from a column's start)."""

    def __init__(self):
        self.bank, self.at = SRC_BANKS[0], SRC_LO
        self.records: List[SR.Record] = []

    def put(self, data: bytes) -> Tuple[int, int]:
        if self.at + len(data) > SRC_END:
            self.bank += 1
            self.at = SRC_LO
            if self.bank not in SRC_BANKS:
                raise CaseError('the sources pass bank %d' % SRC_BANKS[-1])
        where = (self.bank, self.at)
        self.records.append((1, self.bank, self.at, data))
        self.at = (self.at + len(data) + 0xFF) & ~0xFF
        return where


def bg_records(st: State, bank: int) -> List[SR.Record]:
    return [(1, bank, 0x2000, st.buf), (1, bank, 0xA000, st.drb),
            (1, bank, 0xA100, st.dre), (1, bank + 3, 0x2000, st.tables.nibtab),
            (1, bank + 1, 0x2000, st.capval),
            (1, bank + 2, 0x2000, st.capmsk)]


def descriptor(k: int, c: Case, bg: int, src: Tuple[int, int],
               bands: List[Tuple[int, int, List[int]]], t: D.Tables,
               flags: int = 0) -> List[SR.Record]:
    area = bytearray(0x100)
    rows = bytearray(0x200)
    if c.kind in ('patch', 'vpatch'):
        xy = struct.pack('<HH', c.x & 0xFFFF, c.y & 0xFFFF)
    else:
        xy = bytes([c.x, c.y, c.b0, c.b1])
    paddr = (src[1] + c.src_row0) & 0xFFFF
    area[0:12] = bytes([KIND[c.kind], src[0]]) + struct.pack('<H', paddr) + \
        xy + bytes([0x80 if c.cap else 0, bg, len(bands), flags])
    if 12 + 10 * len(bands) > 0x100:
        raise CaseError('%s: %d bands' % (c.name, len(bands)))
    for i, (a, b, pals) in enumerate(bands):
        slots = list(pals) + [0xFF] * (SLOTS - len(pals))
        area[12 + 10 * i:22 + 10 * i] = bytes([a, b] + slots)
        for r in range(a, b):
            for table, base in ((t.rowl, 0), (t.rowr, 0x100)):
                page = table[r]
                rows[base + r] = SLOT_PAGE + 4 * pals.index(page >> 2) + \
                    (page & 3)
    return [(1, DESC_BANK, 0x2000 + k * 0x100, bytes(area)),
            (1, DESC_BANK, 0x4000 + k * 0x200, bytes(rows))]


def native_cases(b: SR.Build, cases: Sequence[Case], states: Sequence[State],
                 set_of: Sequence[int], work: Path,
                 profile: Optional[str] = None, fill: int = 0xA5,
                 write_log: bool = False) -> Tuple[List[str], Dict[str, Any]]:
    """One a2vm run of up to 32 cases (each with its state set_of[k] of
    `states`): the problems, and the run's measures."""
    if len(cases) > CASES_A_RUN:
        raise CaseError('%d cases in a run' % len(cases))
    sets = sorted(set(set_of))
    if len(sets) * SET_BANKS + BG_FIRST > R_BANK:
        raise CaseError('%d background sets in a run' % len(sets))
    bank_of = {s: BG_FIRST + SET_BANKS * i for i, s in enumerate(sets)}
    recs: List[SR.Record] = []
    for s in sets:
        recs += bg_records(states[s], bank_of[s])
    pk = Packer()
    all_bands = []
    for k, c in enumerate(cases):
        st = states[set_of[k]]
        src = pk.put(c.source)
        bands = bands_of(k + len(c.name), c.rows, c.cap, st.tables)
        all_bands.append(bands)
        recs += descriptor(k, c, bank_of[set_of[k]], src, bands, st.tables)
    recs += pk.records
    ranges = 'aux%d:2000-A5FF,aux%d:2000-9CFF,aux%d:2000-9CFF' % (
        R_BANK, R_BANK + 1, R_BANK + 2)
    r = SR.run(b, [SR.Call('s2x_case', k) for k in range(len(cases))], fill,
               work, extra_records=recs, write_log=write_log,
               snap_ranges=ranges, profile=profile)
    problems = []
    if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
        problems.append('the run ended %s, status %s' % (r.ended(),
                                                         r.status()))
        return problems, {}
    snaps = call_snapshots(r, len(cases))
    if len(snaps) != len(cases):
        return ['the run gave %d of %d calls\' marks' % (len(snaps),
                                                       len(cases))], {}
    for k, c in enumerate(cases):
        problems += compare_case(c, all_bands[k], snaps[k])
    measures = {'bands': sum(len(x) for x in all_bands)}
    if profile:
        measures['phases_ms'] = SR.phase_ms(r, profile)
    if write_log:
        n, shown = SR.stray(r.writes(), owners(b, r.loads))
        if n:
            problems.append('%d stray writes: %s' % (n, '; '.join(shown[:3])))
        measures['writes'] = len(r.writes())
    return problems, measures


def call_snapshots(r: SR.Run, n: int) -> List[SR.Machine]:
    """Each call's snapshot, checked by the case number the test image
    writes last (R_BANK $A5FF): exactly one a call (the driver masks the
    interrupt over its snapshot point, request S2DRAW-3)."""
    out = []
    for m in r.calls():
        k = m.storage('aux', R_BANK)[MARK]
        if k != len(out):
            raise CaseError('a call snapshot marked %d after %d' %
                            (k, len(out) - 1))
        out.append(m)
    return out


def compare_case(c: Case, bands, m: SR.Machine) -> List[str]:
    out = []
    r1, r2, r3 = (m.storage('aux', R_BANK + i) for i in range(3))
    a0 = c.rows[0]
    t = c.truth
    for i, (a, b, _) in enumerate(bands):
        got = bytes(r1[0x2000 + a * D.ROW:0x2000 + b * D.ROW])
        want = t['pixels'][(a - a0) * D.ROW:(b - a0) * D.ROW]
        if got != want:
            j = next(j for j in range(len(got)) if got[j] != want[j])
            out.append('%s band %d-%d: the byte of row %d, $%02X: $%02X, '
                       'ref816 $%02X' % (c.name, a, b, a + j // D.ROW,
                                         j % D.ROW, got[j], want[j]))
        for name, page, ref in (('DRB', 0xA000, t['drb']),
                                ('DRE', 0xA100, t['dre'])):
            got = bytes(r1[page + a:page + b])
            if got != ref[a:b]:
                j = next(j for j in range(b - a) if got[j] != ref[a + j])
                out.append('%s band %d-%d: %s of row %d $%02X, ref816 $%02X'
                           % (c.name, a, b, name, a + j, got[j],
                              ref[a + j]))
        marked = [r - a for r in range(a, b) if r1[0xA100 + r]]
        hull = (marked[0], marked[-1] + 1) if marked else (0, 0)
        dry = (r1[0xA400 + 2 * i], r1[0xA401 + 2 * i])
        if dry != hull and not (hull == (0, 0) and dry[1] == 0):
            out.append('%s band %d-%d: S2_DRY0/1 %s, the marked rows %s'
                       % (c.name, a, b, dry, hull))
        if c.cap:
            for name, rb, ref in (('CAPVAL', r2, t['capval']),
                                  ('CAPMSK', r3, t['capmsk'])):
                got = bytes(rb[0x2000 + a * D.ROW:0x2000 + b * D.ROW])
                if got != ref[(a - a0) * D.ROW:(b - a0) * D.ROW]:
                    out.append('%s band %d-%d: %s differs' % (c.name, a, b,
                                                              name))
    return out


# ---------------------------------------------------------------------------
# The truth's cache
# ---------------------------------------------------------------------------

def inputs_key(inputs: Sequence[Dict[str, Any]], extra: str = '') -> str:
    h = hashlib.sha256()
    h.update(FORMAT.encode() + extra.encode())
    h.update(BASE.read_bytes()[:4096] if BASE.exists() else b'')
    h.update(Path(__file__).read_bytes())
    for inp in inputs:
        h.update(json.dumps({k: v for k, v in inp.items() if k != 'data'},
                            sort_keys=True).encode())
        if 'data' in inp:
            h.update(inp['data'])
    return h.hexdigest()[:16]


def save_cases(path: Path, cases: Sequence[Case],
               states: Sequence[State], set_of: Sequence[int]) -> None:
    def enc(v):
        if isinstance(v, bytes):
            return {'b': zlib.compress(v).hex()}
        if isinstance(v, (list, tuple)):
            return [enc(x) for x in v]
        if isinstance(v, dict):
            return {k: enc(x) for k, x in v.items()}
        return v
    doc = {'format': FORMAT,
           'cases': [enc(c._asdict()) for c in cases],
           'states': [enc(s._asdict()) for s in states],
           'set_of': list(set_of)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_bytes(zlib.compress(json.dumps(doc).encode()))
    tmp.replace(path)


def load_cases(path: Path) -> Tuple[List[Case], List[State], List[int]]:
    def dec(v):
        if isinstance(v, dict) and set(v) == {'b'}:
            return zlib.decompress(bytes.fromhex(v['b']))
        if isinstance(v, list):
            return [dec(x) for x in v]
        if isinstance(v, dict):
            return {k: dec(x) for k, x in v.items()}
        return v
    doc = json.loads(zlib.decompress(path.read_bytes()))
    if doc.get('format') != FORMAT:
        raise CaseError('%s: not %s' % (path, FORMAT))
    cases = []
    for c in doc['cases']:
        c = dec(c)
        c['rows'] = tuple(c['rows'])
        cases.append(Case(**c))
    states = []
    for s in doc['states']:
        s = dec(s)
        tb = s['tables']
        s['tables'] = D.Tables(tb[0], tb[1], tb[2], tuple(tb[3]))
        s['dry'] = tuple(s['dry'])
        states.append(State(**s))
    return cases, states, doc['set_of']


def synthetic(limit: Optional[int] = None
              ) -> Tuple[List[Case], List[State], List[int]]:
    """The synthetic cases with their truth (cached in build/)."""
    inputs = synthetic_inputs(limit)
    ensure_base()
    path = TRUTH / ('synthetic-%s.z' % inputs_key(inputs))
    if path.exists():
        return load_cases(path)
    work = Path(tempfile.mkdtemp(prefix='tmp-m11-s2draw-truth-',
                                 dir=str(SR.BUILD)))
    try:
        cases = synthetic_truth(inputs, work)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    states = [random_state(random.Random(SEED * 1000 + g))
              for g in range((len(cases) + CASES_A_RUN - 1) // CASES_A_RUN)]
    set_of = [i // CASES_A_RUN for i in range(len(cases))]
    if TRUTH.exists():
        for old in TRUTH.glob('synthetic-*.z'):
            old.unlink()
    save_cases(path, cases, states, set_of)
    return cases, states, set_of


# ---------------------------------------------------------------------------
# Captured calls
# ---------------------------------------------------------------------------

# (the routine, its kind, the hits of the tour: spread over its calls)
CAPTURES = (
    # the HUD's two texts with CAPVAL, CAPMSK recorded (after the tour's
    # IIGS_BeginCapture calls: hits 2-21 and 423-436), the menus' patches
    ('V_DrawPatchNotScaled', 'vpatch', tuple(range(2, 22)) +
     (40, 100, 160, 230, 300, 380) + tuple(range(423, 437))),
    ('V_DrawNumPatchNotScaled', 'num', (1, 20, 60, 120, 180, 240, 290)),
    ('V_DrawNumPatchScaled', 'num', (1, 300, 800, 1300, 1800, 2300)),
    ('V_DrawRaw', 'raw', (1, 2, 3, 5, 8, 9)),
    ('V_DrawBackground', 'back', (1, 2, 3)),
    ('I_RestoreStatusRect', 'strect', (1, 2, 3)),
)


def captured_case(name: str, how: str, entry: Path, p: Dict[str, int],
                  routine: int, work: Path) -> Tuple[Case, State]:
    img = refimage.read(entry)
    mem = refimage.load(img)
    st = state_of(mem, p)
    regs = img.registers
    cap = mem.word(p['capture']) != 0
    saves = [(SHRBUF, D.SCREEN), (p['DRB'], D.ROWS), (p['DRE'], D.ROWS),
             (CAPVAL + 0x2000, D.SCREEN), (CAPMSK + 0x2000, D.SCREEN),
             (p['VP_Y0'], 8), (p['dp'], 8), (p['px'], 4), (p['VP_REC'], 4),
             (p['stcachenum'], 2)]
    state, data = call(entry, [], routine, {}, saves, work)
    dp, pxy, rec = data[6], data[7], data[8]
    b0 = b1 = 0
    src_row0 = 0
    if how in ('vpatch', 'num'):
        ptr = struct.unpack_from('<I', dp, 4)[0] & 0xFFFFFF
        _, more = call(entry, [], routine, {}, [(ptr, 16384)], work)
        source = patch_bytes(more[0])
        if how == 'vpatch':
            kind, x, y = 'vpatch', regs.a, mem.word(p['dp'])
        else:
            kind, (x, y) = 'patch', struct.unpack('<HH', pxy)
    elif how in ('raw', 'back'):
        ptr = struct.unpack('<I', rec)[0] & 0xFFFFFF
        num = regs.a
        size = lump_size(mem, num)
        if how == 'back':
            _, more = call(entry, [], routine, {}, [(ptr, 4096)], work)
            kind, source, x, y = 'back', more[0], 0, 0
        elif size == 36864:                 # drawPicture: its pixels
            _, more = call(entry, [], routine, {}, [(ptr, D.SCREEN)], work)
            kind, source, x, y, b1 = 'rect', more[0], 0, 200, 159
        else:
            offset = mem.word(p['dp'])
            if offset % 320 or size % 320:
                raise CaseError('%s: V_DrawRaw at %d, %d bytes: outside '
                                's2_raw\'s whole rows' % (name, offset,
                                                          size))
            if offset == ST_ROWS * 320 and size == 32 * 320 and \
                    mem.word(p['stcachenum']) == num:
                kind, source, x, y, b1 = 'rect', st.stcache, ST_ROWS, 200, \
                    159
                src_row0 = -ST_ROWS * D.ROW
            else:
                _, more = call(entry, [], routine, {}, [(ptr, size)], work)
                kind, source = 'raw', more[0]
                x, y = offset // 320, min(offset // 320 + size // 320, 255)
    else:
        source = st.stcache
        vy0, vy1, vb0, vb1 = struct.unpack('<hhhh', data[5])
        kind, src_row0 = 'rect', -ST_ROWS * D.ROW
        if D.rect_empty(vy0, vy1, vb0, vb1):
            x, y, b0, b1 = ST_ROWS, ST_ROWS, 0, 0
        else:
            x, y, b0, b1 = vy0, vy1, vb0, vb1
    rows = touched(kind, source, x, y)
    truth = truth_of(st, data, rows, cap, state)
    return Case(name, kind, source, x, y, b0, b1, cap, rows, src_row0,
                truth), st


def lump_size(mem: refimage.Memory, num: int) -> int:
    _, count, _, start = struct.unpack('<4shhi', mem.get(MM_WAD, 12))
    return struct.unpack('<IHH8s', mem.get(MM_WAD + start + 16 * num,
                                           16))[1]


def patch_bytes(data: bytes) -> bytes:
    """A patch's bytes: to the end of its last column."""
    end = 8 + 4 * D.u16(data, 0)
    for o in D.columns(data):
        end = max(end, o + D.column_bytes(data, o))
    return data[:end]


def captured() -> Tuple[List[Case], List[State], List[int]]:
    """The captured calls with their truth (cached in build/)."""
    key = hashlib.sha256(repr(CAPTURES).encode() + FORMAT.encode() +
                         Path(__file__).read_bytes()).hexdigest()[:16]
    path = CAPTURED / ('captured-%s.z' % key)
    if path.exists():
        return load_cases(path)
    p = places()
    work = Path(tempfile.mkdtemp(prefix='tmp-m11-s2draw-cap-',
                                 dir=str(SR.BUILD)))
    cases: List[Case] = []
    states: List[State] = []
    try:
        for routine_name, how, hits in CAPTURES:
            routine = p[routine_name]
            for at in range(0, len(hits), CAPTURE_CHUNK):
                chunk = hits[at:at + CAPTURE_CHUNK]
                rw = work / ('%s-%d' % (routine_name, at))
                rw.mkdir()
                cap = capture_run('tour', routine, chunk, rw)
                for h in chunk:
                    entry = cap / ('hit-%08d' % h) / 'entry.img'
                    c, st = captured_case('%s-%d' % (routine_name, h), how,
                                          entry, p, routine, rw)
                    cases.append(c)
                    states.append(st)
                shutil.rmtree(str(rw), ignore_errors=True)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    set_of = list(range(len(cases)))
    if CAPTURED.exists():
        for old in CAPTURED.glob('captured-*.z'):
            old.unlink()
    save_cases(path, cases, states, set_of)
    return cases, states, set_of


# ---------------------------------------------------------------------------
# The write log's writers
# ---------------------------------------------------------------------------

def module_pcs(b: SR.Build) -> Dict[str, Tuple[int, int]]:
    """Each module's S2CODE (inclusive), from the image's ld65 map."""
    text = (b.obj / (b.name + '.map')).read_text()
    start = b.segments['S2CODE'][0]
    out: Dict[str, Tuple[int, int]] = {}
    module = None
    part = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    for line in part.splitlines():
        if line and not line.startswith(' ') and line.rstrip().endswith(':'):
            module = Path(line.strip()[:-1].split('(')[0]).stem
            continue
        f = line.split()
        if module and f and f[0] == 'S2CODE':
            offs = int(f[1][5:], 16)
            size = int(f[2][5:], 16)
            out[module] = (start + offs, start + offs + size - 1)
    return out


def owners(b: SR.Build, loads) -> List[SR.Owner]:
    """The writers of a run of the test image and what each may write."""
    pcs = module_pcs(b)
    lab = b.labels
    marks, begun = lab['s2_marks'], lab['s2_begun']
    io_window = frozenset({0xC002, 0xC003, 0xC004, 0xC005, 0xC073})
    zp = ('main', 0, S2ZP[0], S2ZP[1])
    return [
        SR.driver_owner(b), SR.loader_owner(b, loads),
        SR.Owner('the far layer', (b.segments['RFAR'],),
                 (('main', 0, 0x0000, 0x0100), ('main', 0, W_RUNTIME[0],
                                                 W_RUNTIME[1])) +
                 tuple(('aux', k, 0x0000, 0x10000)
                       for k in range(R_BANK, R_BANK + 3)), io_window),
        SR.Owner('the test image', (pcs['s2_drawt'],),
                 (zp, ('main', 0, 0x0000, 0x0006),
                  ('main', 0, PHASE, PHASE + 1),
                  ('main', 0, begun, begun + 1)), frozenset()),
        SR.Owner('s2_draw', (pcs['s2_draw'],),
                 (zp, ('main', 0, 0x0000, 0x0006),
                  ('main', 0, W_BAND[0], W_BAND[1]),
                  ('main', 0, marks, marks + 0x100),
                  ('main', 0, pcs['s2_draw'][0], pcs['s2_draw'][1] + 1)),
                 frozenset()),
        SR.Owner('s2_pub', (pcs['s2_pub'],),
                 (zp, ('aux', 0, 0x2000, 0x9D00),
                  ('main', 0, marks + 0x40, marks + 0x80),
                  ('main', 0, begun, begun + 1)),
                 frozenset({0xC004, 0xC005})),
        SR.Owner('s2_begin (stand-in)', (pcs['s2_beginstub'],),
                 (('aux', 0, 0x9D00, 0x9DC8),), frozenset({0xC004, 0xC005})),
    ]


# ---------------------------------------------------------------------------
# The publish
# ---------------------------------------------------------------------------

class PubCase(NamedTuple):
    y0: int
    y1: int
    band: bytes                 # its rows, 160 bytes each
    drb: bytes                  # each band row's marks
    dre: bytes


def publish_cases(seed: int, n: int = PUB_A_RUN, full: bool = False
                  ) -> List[PubCase]:
    """n bands of random bytes and random marks (the first with none, so
    it must not count as the frame's first band); `full`: whole rows."""
    rng = random.Random(seed)
    out = []
    for k in range(n):
        y0 = rng.randrange(0, 200)
        y1 = min(200, y0 + rng.randrange(1, BAND_ROWS + 1))
        rows = y1 - y0
        band = bytes(rng.getrandbits(8) for _ in range(rows * D.ROW))
        drb, dre = bytearray(rows), bytearray(rows)
        for r in range(rows):
            if full:
                drb[r], dre[r] = 0, 160
            elif k and rng.random() < 0.7:
                a = rng.choice((0, rng.randrange(160), 159))
                drb[r], dre[r] = a, rng.choice((a + 1, 160,
                                                rng.randrange(a + 1, 161)))
        out.append(PubCase(y0, y1, band, bytes(drb), bytes(dre)))
    return out


def publish_run(b: SR.Build, cases: Sequence[PubCase], fill: int,
                work: Path, profile: Optional[str] = None,
                begun: bool = False) -> Tuple[List[str], Dict[str, Any]]:
    """The bands published in one frame: the problems (the screen against
    the host copy, the stray writes, s2_begin's place), the measures."""
    recs: List[SR.Record] = []
    for k, c in enumerate(cases):
        bank = BG_FIRST + k
        screen = bytearray(D.SCREEN)
        screen[c.y0 * D.ROW:c.y1 * D.ROW] = c.band
        drb, dre = bytearray(D.ROWS), bytearray(D.ROWS)
        drb[c.y0:c.y1], dre[c.y0:c.y1] = c.drb, c.dre
        recs += [(1, bank, 0x2000, bytes(screen)), (1, bank, 0xA000, drb),
                 (1, bank, 0xA100, dre)]
        area = bytearray(0x100)
        area[0:12] = bytes([0, 0, 0, 0, 0, 0, 0, 0, 0, bank, 1,
                            1 if begun else 0])
        area[12:22] = bytes([c.y0, c.y1] + [0xFF] * SLOTS)
        recs.append((1, DESC_BANK, 0x2000 + k * 0x100, bytes(area)))
    ranges = 'aux0:2000-9FFF,aux%d:A100-A5FF' % R_BANK
    r = SR.run(b, [SR.Call('s2x_pub', k) for k in range(len(cases))], fill,
               work, extra_records=recs, write_log=profile is None,
               snap_ranges=ranges, profile=profile)
    problems = []
    if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
        return ['the run ended %s, status %s' % (r.ended(), r.status())], {}
    # the host copy: the poison, s2_begin's SCBs at the first band with
    # a mark, then each band's marked bytes
    screen = bytearray([fill]) * 0x8000
    started = begun
    nbytes = 0
    for c in cases:
        if any(c.dre) and not started:
            started = True
            for i in range(D.ROWS):
                screen[0x7D00 + i] = 0x50 | (i & 0x0F)
        marked = [r for r in range(c.y1 - c.y0) if c.dre[r]]
        if marked:
            nbytes += D.publish(screen, c.band, c.y0, c.drb, c.dre,
                                marked[0], marked[-1] + 1)
    stop = SR.read_snapshot(r.work / 'stop.img')
    got = stop.storage('aux', 0)[0x2000:0xA000]
    if bytes(got) != bytes(screen):
        j = next(j for j in range(len(got)) if got[j] != screen[j])
        problems.append('the screen at $%04X: $%02X, the host copy $%02X'
                        % (0x2000 + j, got[j], screen[j]))
    for k, m in enumerate(call_snapshots(r, len(cases))):
        c = cases[k]
        r1 = m.storage('aux', R_BANK)
        if any(r1[0xA100 + c.y0:0xA100 + c.y1]) or r1[0xA400] or \
                r1[0xA401]:
            problems.append('band %d: its marks not cleared' % k)
    measures = {'bytes': nbytes}
    if profile:
        measures['phases_ms'] = SR.phase_ms(r, profile)
        return problems, measures
    writes = r.writes()
    n, shown = SR.stray(writes, owners(b, r.loads))
    if n:
        problems.append('%d stray writes: %s' % (n, '; '.join(shown[:3])))
    stores = C2.screen_stores(writes)
    scb = [i for i, s in enumerate(stores) if C2.kind(s.offset) == 'scb']
    band = [i for i, s in enumerate(stores) if C2.kind(s.offset) == 'band']
    pcs = module_pcs(b)['s2_beginstub']
    stub = [w for w in writes if pcs[0] <= w.pc <= pcs[1] and
            w.storage == 'aux']
    if not begun:
        if len(stub) != D.ROWS:
            problems.append('s2_begin wrote %d SCBs, not once its 200'
                            % len(stub))
        if band and (not scb or scb[-1] > band[0]):
            problems.append('the first band store (%d) before s2_begin\'s '
                            'last SCB store (%s)' % (
                                band[0], scb[-1] if scb else 'none'))
    elif stub:
        problems.append('s2_begin ran in a frame that had begun')
    problems += C2.order(stores, False)
    measures['stores'] = len(band)
    return problems, measures


# ---------------------------------------------------------------------------
# Runs of many cases
# ---------------------------------------------------------------------------

def run_all(b: SR.Build, cases: Sequence[Case], states: Sequence[State],
            set_of: Sequence[int], per_run: int = CASES_A_RUN,
            profile: Optional[str] = None, write_log: bool = False
            ) -> Tuple[List[str], List[Dict[str, Any]]]:
    groups: List[List[int]] = []
    for i in range(len(cases)):         # at most 7 background sets a run
        g = groups[-1] if groups else None
        if g is None or len(g) == per_run or \
                len({set_of[j] for j in g} | {set_of[i]}) > MAX_SETS:
            groups.append([i])
        else:
            g.append(i)

    def one(g):
        work = Path(tempfile.mkdtemp(prefix='tmp-m11-s2draw-run-',
                                     dir=str(SR.BUILD)))
        try:
            return native_cases(b, [cases[i] for i in g], states,
                                [set_of[i] for i in g], work, profile,
                                write_log=write_log)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)

    with ThreadPoolExecutor(max_workers=JOBS) as pool:
        results = list(pool.map(one, groups))
    return [x for r, _ in results for x in r], [m for _, m in results]


def pixels(c: Case, st: State) -> int:
    """The pixels a patch case writes (the model's count)."""
    x, y = (c.x, c.y) if c.kind == 'patch' else \
        D.vpatch_position(c.source, c.x, c.y)
    return D.draw_patch(bytearray(st.buf), D.Marks(), c.source, x, y,
                        st.tables)


def timing(b: SR.Build, profile: str, sample: int = 128
           ) -> Dict[str, float]:
    """us a patch pixel (the in-screen patch cases, recording off; the
    drawer alone, phase 30: its column fetches and every band it is drawn
    in counted) and us a published byte (whole marked rows, a frame whose
    s2_begin has run), on `profile`."""
    cases, states, set_of = synthetic()
    sel = [i for i, c in enumerate(cases) if c.kind in ('patch', 'vpatch')
           and '-in-' in c.name and not c.cap]
    sel = sel[:sample]
    probs, ms = run_all(b, [cases[i] for i in sel], states,
                        [set_of[i] for i in sel], profile=profile)
    if probs:
        raise CaseError('timing: %s' % probs[:3])
    px = sum(pixels(cases[i], states[set_of[i]]) for i in sel)
    t = sum(m['phases_ms'].get(S.PHASE_2D, 0.0) for m in ms)
    work = Path(tempfile.mkdtemp(prefix='tmp-m11-s2draw-time-',
                                 dir=str(SR.BUILD)))
    try:
        pp, pm = publish_run(b, publish_cases(1, full=True), 0xA5, work,
                             profile=profile, begun=True)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if pp:
        raise CaseError('timing: %s' % pp[:3])
    tp = pm['phases_ms'].get(S.PHASE_2D, 0.0)
    return {'patch_cases': len(sel), 'pixels': px, 'patch_ms': t,
            'us_pixel': 1000.0 * t / px, 'published': pm['bytes'],
            'publish_ms': tp, 'us_byte': 1000.0 * tp / pm['bytes']}


def build() -> SR.Build:
    SR.make('s2draw')
    return SR.load_build(OUT, 's2dt', 'P2DW')


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--limit', type=int)
    parser.add_argument('--no-captured', action='store_true')
    parser.add_argument('--timing', action='store_true')
    args = parser.parse_args(argv)
    b = build()
    if args.timing:
        for profile in ('f121', 'fastpath'):
            t = timing(b, profile)
            print('%s: %.3f us a patch pixel (%d pixels, %d cases, %.2f ms);'
                  ' %.3f us a published byte (%d bytes, %.2f ms)' % (
                      profile, t['us_pixel'], t['pixels'], t['patch_cases'],
                      t['patch_ms'], t['us_byte'], t['published'],
                      t['publish_ms']))
        return 0
    cases, states, set_of = synthetic(args.limit)
    print('synthetic: %d cases' % len(cases))
    probs = [x for i, c in enumerate(cases)
             for x in model_problems(c, states[set_of[i]])]
    print('model against ref816: %d problems %s' % (len(probs), probs[:5]))
    native, _ = run_all(b, cases, states, set_of, CASES_A_RUN)
    print('native against ref816: %d problems %s' % (len(native),
                                                     native[:5]))
    if not args.no_captured:
        cc, cs, co = captured()
        print('captured: %d cases' % len(cc))
        probs = [x for i, c in enumerate(cc) for x in model_problems(c,
                                                                     cs[i])]
        print('model against ref816: %d problems %s' % (len(probs),
                                                        probs[:5]))
        native, _ = run_all(b, cc, cs, co, CAPTURED_A_RUN)
        print('native against ref816: %d problems %s' % (len(native),
                                                         native[:5]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
