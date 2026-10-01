#!/usr/bin/env python3
"""Routine mode of the native masked phase (milestone 8, stage B;
docs/RENDER-MASKED.md 4.1, 5.2 item 1): each call of R_DrawSprite,
R_DrawVisSprite and R_RenderMaskedSegRange (maskedSeg's included) of
tools/native/maskcap.py's captures, run alone on a2vm from the reference's
state at its entry, against the reference's state at its return.

Usage:  python3 tools/native/maskroutine.py [--frames NAME,...]
                 [--kinds sprite,vis,range,seg] [--fills a5,5a] [--jobs 2]

For each case and each fill ($A5, then $5A: every byte the case does not
define), the image is milestone 8's masked build (mtest, with the clip
log), the frame's level and state (render_check.prepare_masked: the level,
framestate.py's records of the frame's P0, the W tables and TXMP in their
images' banks), and the call's entry state in native form:

  - the vissprites of the frame (P3's, unchanged by the masked phase) as
    native records in W (VIS): the thing's slot, its x and y, the patch
    store index of the vissprite's patch, the colormap's page, gzt;
  - the drawsegs (P3's) as native records in RENDB, those that clip or
    hold masked columns (DSX1 not 255) also in W's DSW; DSX1, DSX2, the
    count;
  - at the call's entry: the openings (low bytes in aux 0, high bytes in
    RENDB, the drawn marks included), floorclip, ceilingclip, the spans'
    rows, the covered ranges, COLW's offsets (UPOFS) and XPNEXT (XPUSED),
    FZ_POS, W_WSK, WCLIP, WTMP, rw_scalestep, LT_BASE, LT_FIXED, viewz;
    an empty staging (RECSEQ 0).

The driver (rdriver.s drv_mroutine) loads the windows, sets the draw
phase's constants and calls nm_drawsprite, nm_visx (R_DrawVisSprite with
the clips) or nm_mwall, then flushes the last batch. At the return every
output must equal the reference's (rcanon's forms): the records the call
appended by column, floorclip, ceilingclip, the spans' rows, the covered
ranges (and the record of each range the call set, as its index among the
column's appended records), UPOFS and XPNEXT, FZ_POS; a masked range's
rw_scalestep and its columns' marks; an R_DrawSprite call's clip log (the
R_DrawVisSprite call it made, or none); no stray write.
"""

import argparse
import json
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import linkmap as blink  # noqa: E402
from native import framestate as FS, maskcap as MC, projmodel as PM, \
    rcanon, render_check as RCK, rlayout as R  # noqa: E402

KINDS = {'sprite': 0, 'vis': 1, 'range': 2, 'seg': 2}
SIZEOF_VIS, SIZEOF_DS = 42, 42
DS_UP = rcanon.DS_UP
WPAGE_W_WSK = 0x000AB0
MM_FS = rcanon.MM_FS
WTMP_UP = rcanon.MM_WCLIP + 0x1C0


class RoutineError(Exception):
    pass


def le(v: int, n: int) -> bytes:
    return (v & ((1 << (8 * n)) - 1)).to_bytes(n, 'little')


class FrameState(NamedTuple):
    mc: Any                         # render_check.MaskCase
    vis: bytes                      # the native vissprites (VIS)
    nvis: int
    drawsegs: bytes                 # the native drawsegs (RENDB)
    dsw: bytes                      # those whose DSX1 is not 255 (DSW)
    slots: Dict[int, int]           # drawseg -> its DSW slot
    dsx: bytes                      # DSX1 (128), DSX2 (128)
    dscount: int


def native_vissprites(frame, sym, level: Dict[str, Any]) -> Tuple[bytes,
                                                                  int]:
    """P3's vissprites as native records (rlayout.VISREC)."""
    a = sym.address
    p0, p3 = frame.dump('p0'), frame.dump('p3')
    secs = p0.u(a('_g_sectors'), 3)
    nsec = p0.u(a('_g_numsectors'), 2)
    slot_of = FS.slot_map(p0, sym, secs, nsec)
    store = {e['address']: e['index'] for e in level['sprites']['store']}
    full = a('fullcolormap')
    out = bytearray()
    V = R.VISREC
    vis = PM.vissprites_ref(p3, sym)
    for v in vis:
        rec = bytearray(R.VISREC_SIZE)
        th = v['gx'] & 0xFFFFFF
        gy = v['gy'] & 0xFFFFFF
        if gy not in store:
            raise RoutineError('a vissprite\'s patch $%06X is not in the '
                               'store' % gy)
        rec[V['X1']] = v['x1'] & 0xFF
        rec[V['X2']] = v['x2'] & 0xFF
        rec[V['SCALE']:V['SCALE'] + 4] = le(v['scale'], 4)
        rec[V['GZ']:V['GZ'] + 4] = le(v['gz'], 4)
        rec[V['GZT']:V['GZT'] + 2] = le((v['gz'] >> 16) + v['topoffset'], 2)
        rec[V['TX']:V['TX'] + 4] = le(p3.u(th + PM.OFS_MO['x'], 4), 4)
        rec[V['TY']:V['TY'] + 4] = le(p3.u(th + PM.OFS_MO['y'], 4), 4)
        rec[V['STARTFRAC']:V['STARTFRAC'] + 4] = le(v['startfrac'], 4)
        rec[V['XISCALE']:V['XISCALE'] + 4] = le(v['xiscale'], 4)
        rec[V['TMID']:V['TMID'] + 4] = le(v['texturemid'], 4)
        rec[V['FSTEP']:V['FSTEP'] + 2] = le(v['fracstep'], 2)
        rec[V['PATCH']:V['PATCH'] + 2] = le(store[gy], 2)
        rec[V['PAGE']] = rcanon.colormap_page(v['colormap'], full)
        rec[V['SLOT']:V['SLOT'] + 2] = le(slot_of[th], 2)
        out += rec
    return bytes(out), len(vis)


def native_drawsegs(frame, sym) -> Tuple[bytes, int]:
    """P3's drawsegs as native records (rlayout.DS): the seg's number, the
    pointers of the clips and masked columns as the opening index less x1
    (or DS_SCREENH, DS_NEGONE, DS_NULL); a pointer that is none of them (a
    field the drawseg does not define) as 0."""
    a = sym.address
    p0, p3 = frame.dump('p0'), frame.dump('p3')
    segs = p0.u(a('_g_segs'), 3)
    openings = a('openings')
    count = p3.u(rcanon.DS_COUNT, 2)
    D = R.DS
    out = bytearray()

    def ptr(v: int, masked: bool) -> int:
        v &= 0xFFFFFF
        if masked and v == 0:
            return R.DS_NULL
        if v == a('screenheightarray'):
            return R.DS_SCREENH
        if v == a('negonearray'):
            return R.DS_NEGONE
        off = v - openings
        if off % 2 or not -1024 <= off // 2 < 4096:
            return 0
        return (off // 2) & 0xFFFF
    for i in range(count):
        base = a('_s_drawsegs') + SIZEOF_DS * i
        f = {k: p3.u(base + o, 4) for k, o in DS_UP.items()}
        rec = bytearray(R.DS_SIZE)
        seg, rest = divmod((f['curline'] & 0xFFFFFF) - segs, 18)
        if rest or seg < 0:
            raise RoutineError('drawseg %d: no seg' % i)
        rec[D['SEG']:D['SEG'] + 2] = le(seg, 2)
        rec[D['X1']] = f['x1'] & 0xFF
        rec[D['X2']] = f['x2'] & 0xFF
        for k, n in (('SCALE1', 'scale1'), ('SCALE2', 'scale2'),
                     ('STEP', 'scalestep'), ('BSIL', 'bsil'),
                     ('TSIL', 'tsil')):
            rec[D[k]:D[k] + 4] = le(f[n], 4)
        rec[D['SIL']] = f['sil'] & 0xFF
        rec[D['TOPCLIP']:D['TOPCLIP'] + 2] = le(ptr(f['topclip'], False), 2)
        rec[D['BOTCLIP']:D['BOTCLIP'] + 2] = le(ptr(f['botclip'], False), 2)
        rec[D['MASKED']:D['MASKED'] + 2] = le(ptr(f['masked'], True), 2)
        out += rec
    return bytes(out), count


_FRAMES: Dict[str, FrameState] = {}


def frame_state(name: str, sym) -> FrameState:
    if name not in _FRAMES:
        d = RCK.RENDER / 'frames' / name
        mc = RCK.prepare_masked(d, sym)
        frame = mc.full.case.frame
        vis, nvis = native_vissprites(frame, sym, mc.full.case.level)
        ds, count = native_drawsegs(frame, sym)
        p3 = frame.dump('p3')
        dsx = p3.read(rcanon.DSX1_UP, 128) + p3.read(rcanon.DSX2_UP, 128)
        slots, dsw = {}, bytearray()
        for i in range(count):
            if dsx[i] != 0xFF:
                slots[i] = len(slots)
                if slots[i] < R.DSW_MAX:
                    dsw += ds[R.DS_SIZE * i:R.DS_SIZE * (i + 1)]
        if len(_FRAMES) > 3:
            _FRAMES.pop(next(iter(_FRAMES)))
        _FRAMES[name] = FrameState(mc, vis, nvis, ds, bytes(dsw), slots,
                                   dsx, count)
    return _FRAMES[name]


def case_records(fs: FrameState, case: MC.Case, sym, lab: Dict[str, int]
                 ) -> List[Tuple[int, int, int, bytes]]:
    """The call's entry state in native form (module docstring)."""
    a = sym.address
    e = case.entry
    h = case.header
    out: List[Tuple[int, int, int, bytes]] = []

    def main(address: int, data: bytes) -> None:
        out.append((0, 0, address, bytes(data)))
    F = R.FRAME
    # W's drawseg copy and vissprites: the driver loads them from bank
    # MRTN_BANK after the images (whose loads cover W)
    out.append((1, R.MRTN_BANK, R.VIS, fs.vis))
    main(F['NVIS'], bytes([fs.nvis]))
    if fs.dsw:
        out.append((1, R.MRTN_BANK, R.DSW, fs.dsw))
    if fs.drawsegs:
        out.append((1, R.RENDB, R.DRAWSEGS, fs.drawsegs))
    main(R.DSX1, fs.dsx)
    main(F['DSCOUNT'], bytes([fs.dscount]))
    op = e.get(a('openings'), 2 * R.MAXOPENINGS)
    out.append((1, 0, R.OPENLO, bytes(op[0::2])))
    out.append((1, R.RENDB, R.OPENHI, bytes(op[1::2])))
    fl = e.get(a('floorclip'), 320)
    ce = e.get(a('ceilingclip'), 320)
    main(R.FLOORCLIP, bytes(fl[0::2]))
    main(R.CEILCLIP, bytes(ce[0::2]))
    sp = e.get(MM_FS, 0xC00)
    main(R.FSTOP, bytes(sp[0:0x140:2]))
    main(R.FSBOT, bytes(sp[1:0x140:2]))
    main(R.CVFIRST, bytes(sp[0x800:0x940:2]) + bytes(sp[0x801:0x940:2]))
    main(R.L5.CVRECLO, b'\xff' * 320)     # (CVRECLO, CVRECHI: not read)
    colw = e.get(a('COLW'), 320)
    main(R.UPOFS, bytes(colw[0::2]))
    xp = e.get(a('XPNEXT'), 1)[0]
    main(F['XPUSED'], bytes([50 if xp == 0 else xp - rcanon.XP_FIRST]))
    main(F['UPFLUSH'], b'\0')
    main(F['RECSEQ'], b'\0\0')
    main(F['STG_BANK'], b'\0')
    main(F['STG_PTR'], le(R.STAGE, 2))
    main(F['STATUS'], b'\0')
    main(F['RULES'], b'\0')
    main(F['FZPOS'], bytes([e.get(a('FZ_POS'), 1)[0]]))
    main(F['W_WSK'], bytes([e.get(WPAGE_W_WSK, 1)[0]]))
    main(F['RW_STEP'], e.get(a('rw_scalestep'), 4))
    main(F['LT_BASE'], e.get(a('LT_BASE'), 2))
    main(F['LT_FIXED'], e.get(a('LT_FIXED'), 2))
    main(F['VIEWZ'], e.get(a('viewz'), 4))
    wc = e.get(rcanon.MM_WCLIP, 320)
    main(R.WCLIP, bytes(wc[0::2]))
    wt = e.get(WTMP_UP, 320)
    main(R.WTMP, bytes(wt[0::2]))
    # the driver's parameters
    kind = h['kind']
    info = h['info']
    params = [KINDS[kind], info.get('vis', 0), info.get('ds', 0),
              fs.slots.get(info.get('ds', -1), 0)]
    if kind == 'range':
        params += [info['x1'] & 0xFF, info['x2'] & 0xFF]
    elif kind == 'seg':
        rec = fs.drawsegs[R.DS_SIZE * info['ds']:R.DS_SIZE * (info['ds'] + 1)]
        params += [rec[R.DS['X1']], rec[R.DS['X2']]]
    else:
        params += [0, 0]
    out.append((2, 0, lab['mr_kind'], bytes(params)))
    return out


def outputs_ref(fs: FrameState, case: MC.Case, sym) -> Dict[str, Any]:
    a = sym.address
    x = case.exit
    h = case.header
    out: Dict[str, Any] = {
        'records': {int(c): [tuple(r) for r in v]
                    for c, v in h['records'].items()},
        'cvrec': {int(c): v for c, v in h['cvrec'].items()},
    }
    fl, ce = x.get(a('floorclip'), 320), x.get(a('ceilingclip'), 320)
    out['floorclip'] = rcanon.words_low(fl, 'floorclip')
    out['ceilclip'] = rcanon.words_low(ce, 'ceilingclip')
    sp = x.get(MM_FS, 0xC00)
    out['spans'] = list(sp[0:0x140:2]) + list(sp[1:0x140:2])
    out['cv'] = list(sp[0x800:0x940:2]) + list(sp[0x801:0x940:2])
    colw = x.get(a('COLW'), 320)
    out['upofs'] = list(colw[0::2])
    out['xpnext'] = x.get(a('XPNEXT'), 1)[0]
    out['fzpos'] = int.from_bytes(x.get(a('FZ_POS'), 2), 'little')
    if h['kind'] in ('range', 'seg'):
        out['rw_step'] = int.from_bytes(x.get(a('rw_scalestep'), 4),
                                        'little')
        i = h['info']['ds']
        base = a('_s_drawsegs') + SIZEOF_DS * i
        m = int.from_bytes(x.get(base + DS_UP['masked'], 4), 'little') \
            & 0xFFFFFF
        x1 = int.from_bytes(x.get(base + DS_UP['x1'], 2), 'little')
        x2 = int.from_bytes(x.get(base + DS_UP['x2'], 2), 'little')
        out['marks'] = [int.from_bytes(x.get(m + 2 * c, 2), 'little')
                        for c in range(x1, x2 + 1)]
    if h['kind'] == 'sprite':
        out['cliplog'] = [] if h['drawvis'] is None else [h['drawvis']]
    return out


def outputs_native(end, fs: FrameState, case: MC.Case) -> Dict[str, Any]:
    F = R.FRAME
    m = end.main
    h = case.header
    mc = fs.mc
    stg_bank = m(F['STG_BANK'], 1)[0]
    stg_ptr = rcanon.le(m(F['STG_PTR'], 2))
    records, seq = rcanon.native_records_all(
        rcanon.staged_bytes(end, stg_bank, stg_ptr), mc.full.slots, mc.pmap)
    out: Dict[str, Any] = {'records': records}
    lo, hi = m(R.L5.CVRECLO, 160), m(R.L5.CVRECHI, 160)
    cvrec = {}
    for c in h['cvrec']:
        c = int(c)
        n = lo[c] | hi[c] << 8
        if n >= len(seq):
            cvrec[c] = 'sequence number %d past the records' % n
        else:
            col, index = seq[n]
            cvrec[c] = index if col == c else 'record %d of column %d' % (
                index, col)
    out['cvrec'] = cvrec
    out['floorclip'] = list(m(R.FLOORCLIP, 160))
    out['ceilclip'] = list(m(R.CEILCLIP, 160))
    out['spans'] = list(m(R.FSTOP, 160)) + list(m(R.FSBOT, 160))
    out['cv'] = list(m(R.CVFIRST, 320))
    out['upofs'] = list(m(R.UPOFS, 160))
    out['xpnext'] = (rcanon.XP_FIRST + m(F['XPUSED'], 1)[0]) & 0xFF
    out['fzpos'] = m(F['FZPOS'], 1)[0]
    if h['kind'] in ('range', 'seg'):
        out['rw_step'] = rcanon.le(m(F['RW_STEP'], 4))
        i = h['info']['ds']
        ds = rcanon.native_drawseg(end, i)
        out['marks'] = rcanon.native_openings(end, ds)['masked']
    if h['kind'] == 'sprite':
        n = m(R.ZPD['CL_N'], 1)[0]
        calls = []
        for k in range(n):
            r = end.aux(R.SEAM, R.SEAM_CLIPLOG + R.CLIPLOG_REC * k,
                        R.CLIPLOG_REC)
            calls.append({'vis': rcanon.le(r[0:2]),
                          'floorclip': list(r[2:162]),
                          'ceilclip': list(r[162:322])})
        out['cliplog'] = calls
    out['status'] = m(F['STATUS'], 1)[0]
    return out


def diff(ref: Dict[str, Any], nat: Dict[str, Any]) -> List[str]:
    out = []
    if nat.get('status'):
        out.append('status %d' % nat['status'])
    for key in sorted(ref):
        a, b = ref[key], nat.get(key)
        if a == b:
            continue
        if key == 'records':
            cols = sorted(set(a) | set(b))
            bad = [c for c in cols if a.get(c) != b.get(c)]
            c = bad[0]
            x, y = a.get(c, []), b.get(c, [])
            k = next(i for i in range(max(len(x), len(y)))
                     if i >= len(x) or i >= len(y) or x[i] != y[i])
            out.append('records: %d columns differ (first %d, record %d: '
                       'native %s, reference %s)' % (
                           len(bad), c, k, y[k] if k < len(y) else None,
                           x[k] if k < len(x) else None))
        elif isinstance(a, list) and isinstance(b, list) and \
                len(a) == len(b) and key != 'cliplog':
            bad = [i for i in range(len(a)) if a[i] != b[i]]
            out.append('%s: %d differ (first %d: native %r, reference %r)'
                       % (key, len(bad), bad[0], b[bad[0]], a[bad[0]]))
        elif key == 'cliplog':
            if len(a) != len(b):
                out.append('the clip log: %d native calls, %d in the '
                           'reference' % (len(b), len(a)))
            else:
                keys = [k for k in a[0] if a[0][k] != b[0][k]]
                out.append('the clip log: %s differ' % keys)
        else:
            out.append('%s: native %r, reference %r' % (key, b, a))
    return out


def check_case(path: Path, b, fill: int, base, sym,
               keep: Optional[Path] = None) -> Dict[str, Any]:
    case = MC.load_case(path)
    h = case.header
    name = '%s/%s-%02d' % (h['frame'], h['kind'], h['k'])
    fs = frame_state(h['frame'], sym)
    recs = list(base) + RCK.to_window(fs.mc.full.case.records) + \
        case_records(fs, case, sym, b.labels)
    work = Path(tempfile.mkdtemp(prefix='tmp-m8-mroutine-',
                                 dir=str(RCK.BUILD)))
    try:
        lab = b.labels
        events = ['pc %X snapshot end' % lab['drv_ret'],
                  'pc %X snapshot crash' % lab['drv_crash']]
        ranges = ','.join('%X-%X' % r for r in RCK.code_ranges(b))
        extra = ['--speed', '1', '--snapshot-ranges', RCK.MASK_SNAP,
                 '--irq-bounds', RCK.IRQ_BOUNDS, '--lowest-s-in', ranges,
                 '--write-log', RCK.WRITE_LOG, '--write-log-file',
                 str(work / 'writes.log'), '--write-log-limit',
                 str(RCK.WRITE_LOG_LIMIT)]
        state = RCK.a2vm_run(b, recs, work, events, extra,
                             start='drv_mroutine')
        out: Dict[str, Any] = {'case': name, 'kind': h['kind'],
                               'fill': fill, 'problems': []}
        if state.get('pc') == lab['drv_crash']:
            try:
                st = RCK.snapshot(work, 'crash').main(R.FRAME['STATUS'], 1)[0]
            except RCK.CheckError:
                st = None
            out['problems'].append('the call stopped (BRK), status %s' % st)
            return out
        if state.get('end') != 'stop-pc' or state.get('pc') != \
                lab['drv_halt']:
            out['problems'].append('the run ended with %s at $%04X' % (
                state.get('end'), state.get('pc', -1)))
            return out
        end = RCK.snapshot(work, 'end')
        ref = outputs_ref(fs, case, sym)
        try:
            nat = outputs_native(end, fs, case)
        except rcanon.CanonError as e:
            out['problems'].append('the native outputs: %s' % e)
            return out
        out['problems'] += diff(ref, nat)
        writes = RCK.read_writes(work / 'writes.log')
        # (the driver sets the call's arguments in overlay 1)
        strays = RCK.stray_masked(writes, b, driver_extra=[
            ('main', 0, R.ZP_OV1[0], R.ZP_OV1[1])])
        if strays:
            out['problems'].append('%d stray writes: %s' % (
                len(strays), '; '.join(strays[:5])))
        out['records'] = sum(len(v) for v in ref['records'].values())
        irqs = int.from_bytes(end.main(0xD8, 2), 'little')
        out['irqs'] = irqs
        low = None
        for r in state.get('lowest_s', {}).get('ranges', []):
            if r.get('s') is not None:
                low = r['s'] if low is None else min(low, r['s'])
        out['stack_bytes'] = None if low is None else RCK.DRV_STACK - low
        out['problems'] += RCK.stack_problem(out['stack_bytes'])
        return out
    finally:
        if keep is not None:
            shutil.copytree(str(work), str(keep), dirs_exist_ok=True)
        shutil.rmtree(str(work), ignore_errors=True)


def case_paths(frames: Optional[str], kinds: Sequence[str]) -> List[Path]:
    root = MC.OUT
    if not root.exists():
        return []
    dirs = [root / f for f in frames.split(',')] if frames else \
        sorted(p for p in root.iterdir() if p.is_dir())
    out = []
    for d in dirs:
        for p in sorted(d.glob('*.case.z')):
            if p.name.split('-')[0] in kinds:
                out.append(p)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames')
    parser.add_argument('--kinds', default='sprite,vis,range,seg')
    parser.add_argument('--fills', default='a5,5a')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args(argv)
    if not args.no_build:
        RCK.make()
    paths = case_paths(args.frames, args.kinds.split(','))
    if not paths:
        print('no cases: run python3 tools/native/maskcap.py',
              file=sys.stderr)
        return 1
    sym = blink.Symbols()
    b = RCK.load_build(RCK.OBJ, 'mtest')
    fills = [int(f, 16) for f in args.fills.split(',')]
    bases = {f: RCK.base_records(b, f, window=True) for f in fills}
    # the cases of a frame together (the frame's state is built once)
    by_frame: Dict[str, List[Path]] = {}
    for p in paths:
        by_frame.setdefault(p.parent.name, []).append(p)

    def one(frame: str) -> List[Dict[str, Any]]:
        res = []
        for p in by_frame[frame]:
            for f in fills:
                try:
                    res.append(check_case(p, b, f, bases[f], sym))
                except (RoutineError, RCK.CheckError, rcanon.CanonError,
                        FS.FrameError, MC.CaptureError) as e:
                    res.append({'case': '%s/%s' % (frame, p.name),
                                'fill': f, 'problems': [str(e)]})
        return res
    results = []
    failed = 0
    with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
        for rs in pool.map(one, sorted(by_frame)):
            for r in rs:
                results.append(r)
                if r['problems']:
                    failed += 1
                if r['problems'] or args.verbose:
                    print('%-24s %02X: %s' % (r['case'], r['fill'],
                                              'DIFFERS' if r['problems']
                                              else 'equal'), flush=True)
                    for p in r['problems'][:6]:
                        print('    ' + p)
    kinds: Dict[str, int] = {}
    for r in results:
        if not r['problems']:
            kinds[r.get('kind', '?')] = kinds.get(r.get('kind', '?'), 0) + 1
    print('%d cases, %d runs: %d equal, %d failed (%s); %d records compared'
          % (len(paths), len(results), len(results) - failed, failed,
             ', '.join('%s %d' % kv for kv in sorted(kinds.items())),
             sum(r.get('records', 0) for r in results
                 if not r['problems'])))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
