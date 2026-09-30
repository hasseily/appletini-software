"""The canonical outputs of the renderer front end, from both machines
(milestone 7, docs/RENDER.md 4.3): the reference's (the dumps and the
call log of tools/native/rendercap.py) and the native's (a2vm's
snapshots, tools/native/render_check.py). The diff is exact.

Stage A (checkpoint A, RENDER.md 5.1 item 4) compares:

    calls       the calls of R_StoreWallRange in order: start, stop, the
                seg (upstream's by index: its pointer less _g_segs, over
                18), the front sector (the same, over 58), the floor and
                ceiling plane colours, worldbottom
    bsp_entry   at R_RenderBSPNode's entry (P0b) and nr_bsp's: CEILCLIP,
                FLOORCLIP (after the seam), SOLIDCOL, the drawseg count,
                lastopening (an index into openings), LT_BASE, LT_FIXED,
                viewsin, viewcos, validcount, the vertex cache's map unit;
                stage C: the plane stamps of R_FillStamps (every span's
                stamp, W_FSC, W_FSP, W_TOPR, W_BOTR, W_LCC, W_LFC,
                W_CEILW, W_FLOORW) and the weapon skip of weaponClipSame
                (FR_SKIP, W_WSK, WPREV, WCLIP)
    end         at drawMasked (P3) and the walk's end: validcount, every
                sector's validcount, the vertex cache's map unit
    vtxangle    the vertex angles computed: ref816's vtxAngle calls, the
                native VA_COUNT

The reference's clip arrays are words whose high bytes must be 0
(segvar.inc); one that is not is a failure of the capture, not a case
to skip.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import linkmap as blink  # noqa: E402
from native import layout as L5, rlayout as R  # noqa: E402
from ref816 import lists as ulists  # noqa: E402

SIZEOF_SEG, SIZEOF_SEC, SIZEOF_DS = 18, 58, 42
DS_COUNT = 0x0AB600             # dscols.inc
DSX1_UP, DSX2_UP = 0x0AB500, 0x0AB580
CALL_MEMS = ('stop', 'bspdp', 'fpc', 'cpc', 'wbot', 'ds_p', 'lastopening')
MM_FS = 0x23EF00                # the spans and covered ranges (lists.inc)
MM_WCLIP = 0x0AC500             # WCLIP; WPREV at + $180
WPAGE_W = {'W_FSC': (0xE8, 1), 'W_FSP': (0xE9, 1), 'W_TOPR': (0xEA, 1),
           'W_BOTR': (0xEB, 1), 'W_LCC': (0xEE, 2), 'W_LFC': (0xF0, 2),
           'W_CEILW': (0xE4, 2), 'W_FLOORW': (0xE6, 2)}
W_WSK_OFS = 0xB0


class CanonError(Exception):
    pass


def le(b: bytes) -> int:
    return int.from_bytes(b, 'little')


def words_low(data: bytes, what: str) -> List[int]:
    if any(data[2 * i + 1] for i in range(len(data) // 2)):
        raise CanonError('%s has a high byte other than 0' % what)
    return [data[2 * i] for i in range(len(data) // 2)]


def reference_calls(frame, sym: blink.Symbols) -> List[Dict[str, int]]:
    p0 = frame.dump('p0')
    segs = p0.u(sym.address('_g_segs'), 3)
    sectors = p0.u(sym.address('_g_sectors'), 3)
    out = []
    for line in frame.calls['storewall']:
        mem = dict(zip(CALL_MEMS, (bytes.fromhex(m)
                                   for m in line['in']['mem'])))
        seg_ptr = le(mem['bspdp'][0:3])
        sec_ptr = le(mem['bspdp'][9:12])
        seg, rs = divmod(seg_ptr - segs, SIZEOF_SEG)
        sector, rc = divmod(sec_ptr - sectors, SIZEOF_SEC)
        if rs or rc or seg < 0 or sector < 0:
            raise CanonError('%s: a call whose seg or sector is not one '
                             '($%06X, $%06X)' % (frame.name, seg_ptr,
                                                 sec_ptr))
        out.append({'start': line['in']['a'] & 0xFFFF,
                    'stop': le(mem['stop']), 'seg': seg, 'sector': sector,
                    'fpc': le(mem['fpc']), 'cpc': le(mem['cpc']),
                    'wbot': le(mem['wbot'])})
    return out


def ref_stamps_weapon(d, sym: blink.Symbols) -> Dict[str, Any]:
    """R_FillStamps' and weaponClipSame's outputs in a reference dump:
    the span stamps (FS_STAMP: bytes 2c and 2c + 1 as two planes), the
    WPAGE stamps and plane state, FR_SKIP, W_WSK (a word whose high byte
    must be 0: the native one is a byte), WPREV (upstream's vissprite),
    WCLIP (its low bytes, written by weaponClipSame)."""
    sp = d.read(MM_FS + 0x600, 0x200)
    out = {'fs_stamps': [sp[2 * c + k] for k in (0, 1) for c in range(160)]}
    for name, (off, n) in WPAGE_W.items():
        out[name.lower()] = le(d.read(0x000A00 + off, n))
    wsk = le(d.read(0x000A00 + W_WSK_OFS, 2))
    if wsk > 255:
        raise CanonError('W_WSK $%04X has a high byte' % wsk)
    out['w_wsk'] = wsk
    out['fr_skip'] = le(d.read(sym.address('FR_SKIP'), 2))
    out['wprev'] = list(d.read(MM_WCLIP + 0x180, R.VIS_SIZE))
    wc = d.read(MM_WCLIP, 320)
    out['wclip'] = [wc[2 * c] for c in range(160)]
    return out


def native_stamps_weapon(m) -> Dict[str, Any]:
    """The same of a native snapshot (m: Snapshot.main)."""
    F = R.FRAME
    out = {'fs_stamps': list(m(L5.FSSTT, 160)) + list(m(L5.FSSTB, 160))}
    for name, (_, n) in WPAGE_W.items():
        out[name.lower()] = le(m(F[name], n))
    out['w_wsk'] = m(F['W_WSK'], 1)[0]
    out['fr_skip'] = le(m(F['FR_SKIP'], 2))
    out['wprev'] = list(m(R.WPREV, R.VIS_SIZE))
    out['wclip'] = list(m(R.WCLIP, 160))
    return out


def reference(frame, sym: blink.Symbols) -> Dict[str, Any]:
    a = sym.address
    b = frame.dump('p0b')
    p3 = frame.dump('p3')
    ds = b.u(a('ds_p'), 2)
    drawsegs = a('_s_drawsegs') & 0xFFFF
    lastop = b.u(a('lastopening'), 3)
    entry = {
        'ceilclip': words_low(b.read(a('ceilingclip'), 320),
                              'ceilingclip'),
        'floorclip': words_low(b.read(a('floorclip'), 320), 'floorclip'),
        'solidcol': list(b.read(a('solidcol'), 160)),
        'dscount': b.u(DS_COUNT, 2),
        'ds_p': (ds - drawsegs) // SIZEOF_DS,
        'lastopening': (lastop - a('openings')) // 2,
        'lt_base': b.u(a('LT_BASE'), 2),
        'lt_fixed': b.u(a('LT_FIXED'), 2),
        'viewsin': b.u(a('viewsin'), 4), 'viewcos': b.u(a('viewcos'), 4),
        'validcount': b.u(a('validcount'), 2),
        'va_vx': b.u(a('VA_VX'), 2), 'va_vy': b.u(a('VA_VY'), 2),
    }
    entry.update(ref_stamps_weapon(b, sym))
    secs = p3.u(a('_g_sectors'), 3)
    nsec = p3.u(a('_g_numsectors'), 2)
    end = {
        'validcount': p3.u(a('validcount'), 2),
        'sector_valid': [p3.u(secs + SIZEOF_SEC * i + 20, 2)
                         for i in range(nsec)],
        'va_vx': p3.u(a('VA_VX'), 2), 'va_vy': p3.u(a('VA_VY'), 2),
    }
    return {'calls': reference_calls(frame, sym), 'bsp_entry': entry,
            'end': end, 'vtxangle': frame.calls['vtxangle']}


class Snapshot:
    """An a2vm range snapshot (A2VMIMG1 records): main and aux bytes."""

    def __init__(self, records: List[Tuple[int, int, int, bytes]]):
        self.mem: Dict[Tuple[int, int], bytearray] = {}
        self.have: Dict[Tuple[int, int], bytearray] = {}
        for kind, bank, address, data in records:
            key = (kind, bank)
            m = self.mem.setdefault(key, bytearray(0x10000))
            h = self.have.setdefault(key, bytearray(0x10000))
            m[address:address + len(data)] = data
            h[address:address + len(data)] = b'\x01' * len(data)

    def read(self, kind: int, bank: int, address: int, length: int
             ) -> bytes:
        h = self.have.get((kind, bank))
        if h is None or not all(h[address:address + length]):
            raise CanonError('the snapshot lacks %d:%d $%04X+%d' % (
                kind, bank, address, length))
        return bytes(self.mem[(kind, bank)][address:address + length])

    def main(self, address: int, length: int) -> bytes:
        return self.read(0, 0, address, length)

    def aux(self, bank: int, address: int, length: int) -> bytes:
        return self.read(1, bank, address, length)


def native(bsp: Snapshot, end: Snapshot, nsectors: int) -> Dict[str, Any]:
    F = R.FRAME
    m = bsp.main
    entry = {
        'ceilclip': list(m(R.CEILCLIP, 160)),
        'floorclip': list(m(R.FLOORCLIP, 160)),
        'solidcol': list(m(R.SOLIDCOL, 160)),
        'dscount': m(F['DSCOUNT'], 1)[0],
        'ds_p': m(F['DSCOUNT'], 1)[0],
        'lastopening': le(m(F['LASTOPEN'], 2)),
        'lt_base': le(m(F['LT_BASE'], 2)),
        'lt_fixed': le(m(F['LT_FIXED'], 2)),
        'viewsin': le(m(F['VIEWSIN'], 4)), 'viewcos': le(m(F['VIEWCOS'], 4)),
        'validcount': le(m(F['VALIDCOUNT'], 2)),
        'va_vx': le(m(F['VA_VX'], 2)), 'va_vy': le(m(F['VA_VY'], 2)),
    }
    entry.update(native_stamps_weapon(m))
    e = end.main
    out_end = {
        'validcount': le(e(F['VALIDCOUNT'], 2)),
        'sector_valid': [le(end.aux(R.LVMAP, R.SECTORS.address(i) +
                                    R.SEC['VALID'], 2))
                         for i in range(nsectors)],
        'va_vx': le(e(F['VA_VX'], 2)), 'va_vy': le(e(F['VA_VY'], 2)),
    }
    return {'bsp_entry': entry, 'end': out_end,
            'vtxangle': le(e(F['VA_COUNT'], 2)),
            'status': e(F['STATUS'], 1)[0], 'rules': e(F['RULES'], 1)[0]}


def native_calls(end: Snapshot, count: int) -> List[Dict[str, int]]:
    out = []
    for k in range(min(count, R.SEAM_MAXCALLS - 1)):
        r = end.aux(R.SEAM, R.SEAM_CALLS + R.SEAM_CALLREC * k,
                    R.SEAM_CALLREC)
        out.append({'start': r[0], 'stop': r[1], 'seg': le(r[2:4]),
                    'sector': r[4], 'fpc': le(r[5:7]), 'cpc': le(r[7:9]),
                    'wbot': le(r[9:13])})
    return out


def diff(ref: Dict[str, Any], nat: Dict[str, Any]) -> List[str]:
    """Every difference, described; empty when equal."""
    out = []
    rc, nc = ref['calls'], nat['calls']
    if len(rc) != len(nc):
        out.append('calls: %d native, %d reference' % (len(nc), len(rc)))
    for k, (a, b) in enumerate(zip(rc, nc)):
        if a != b:
            fields = [f for f in a if a[f] != b.get(f)]
            out.append('call %d: %s: native %s, reference %s' % (
                k, ','.join(fields), [b.get(f) for f in fields],
                [a[f] for f in fields]))
            if len(out) > 20:
                break
    for part in ('bsp_entry', 'end'):
        for key, want in ref[part].items():
            got = nat[part][key]
            if got != want:
                if isinstance(want, list):
                    bad = [i for i, (x, y) in enumerate(zip(want, got))
                           if x != y]
                    out.append('%s %s: %d differ (first %d: native %r, '
                               'reference %r)' % (
                                   part, key, len(bad) + abs(
                                       len(want) - len(got)),
                                   bad[0] if bad else -1,
                                   got[bad[0]] if bad else None,
                                   want[bad[0]] if bad else None))
                else:
                    out.append('%s %s: native %r, reference %r' % (
                        part, key, got, want))
    if ref['vtxangle'] != nat['vtxangle']:
        out.append('vertex angles computed: native %d, reference %d' % (
            nat['vtxangle'], ref['vtxangle']))
    if nat.get('status'):
        out.append('status %d' % nat['status'])
    if nat.get('rules'):
        out.append(rules_problem(nat['rules']))
    return out


# ===========================================================================
# Routine mode (stage B, RENDER.md 4.3; acceptance 2): R_StoreWallRange and
# R_RenderSegLoop, one call each, from their entries (routinecap.py,
# segdesc.py) to their returns.
#
#   records     the records the call made, by column in the order made:
#               upstream's walked from the entry's end of each column's
#               list (COLW) to the return's, through K_NEXT (dropped), in
#               the record bank of the wall's return (the seg loop makes
#               every record of the wall: nothing after it writes one);
#               the native staging and spill, bucketed by the column byte.
#               A K_TEX: rows, TF, TI, SF, SI, CMP and R_SRC as upstream's
#               texel pointer (the native slot mapped back through the
#               level's texture map, levelconv.py); a K_FILL: rows, B1, B2
#   clips       FLOORCLIP, CEILCLIP (the words' low bytes: their high bytes
#               must be 0), SOLIDCOL, didsolidcol, the spans (8 planes) and
#               covered ranges, W_LCC, W_LFC, W_CEILW, W_FLOORW
#   drawseg     (the wall) the drawseg the call made: the fields it
#               defines (below), its dsX1, dsX2, the drawseg count,
#               lastopening, the openings it wrote (by drawseg field: the
#               masked columns, 16 bits; the clips, their low bytes, the
#               reference's high bytes 0), rw_scalestep (kept for the next
#               wall), the line's ML_MAPPED
#   masked      (the seg loop) the masked texture columns it wrote
#
# A drawseg's fields as upstream defines them: the seg, x1, x2, scale1,
# scale2, the silhouette (its low byte: upstream stores a byte), and
# maskedtexturecol (NULL, or an opening index less x1) always; scalestep
# when x2 > x1 (scaleSlow leaves it for one column); bsilheight and
# sprbottomclip with SIL_BOTTOM, tsilheight and sprtopclip with SIL_TOP
# (screenheightarray, negonearray, or an opening index less x1). The
# other fields keep what the drawseg's slot held before.
# ===========================================================================

K_TEX, K_FILL, K_NEXT = 0, 2, 12
UP_SIZES = {0: 11, 2: 5, 6: 7, 8: 4, 10: 4, 12: 2}
RECBANK = 0x1D0000
WPAGE = 0x000A00
W_STATE = (('W_CEILW', 0xE4), ('W_FLOORW', 0xE6), ('W_LCC', 0xEE),
           ('W_LFC', 0xF0))
DS_UP = {'curline': 0, 'x1': 4, 'x2': 6, 'scale1': 8, 'scale2': 12,
         'scalestep': 16, 'sil': 20, 'bsil': 22, 'tsil': 26, 'topclip': 30,
         'botclip': 34, 'masked': 38}
ML_MAPPED = 256
OFS_LINE_R_FLAGS, SIZEOF_LINE = 32, 36


def s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def s32(v: int) -> int:
    return v - 0x100000000 if v & 0x80000000 else v


def slot_map(level_dir: Path) -> Dict[Tuple[int, int], int]:
    """A native texel slot (bank, address) to upstream's texel pointer
    it holds the 128 bytes of (levelconv.py's texture map)."""
    import json
    info = json.loads((Path(level_dir) / 'level.json').read_text())
    slots = json.loads((Path(level_dir) / 'texmap.json').read_text())
    out = {}
    for key, ptr in slots['slots'].items():
        t, c = key.split(':')
        if t == 'sky':
            sky = info['sky']
            out[(sky['bank'], sky['base'] + 128 * int(c))] = ptr
        else:
            tx = info['textures'][t]
            out[(tx['bank'], tx['base'] + 128 * int(c))] = ptr
    return out


def ref_records(entry, colw_exit: bytes, bank1d: bytes, sym
                ) -> Dict[int, List[Tuple]]:
    """The records made between two states of upstream's lists."""
    colw_entry = entry.read(sym.address('COLW'), 320)
    out: Dict[int, List[Tuple]] = {}
    for c in range(160):
        pos = le(colw_entry[2 * c:2 * c + 2])
        end = le(colw_exit[2 * c:2 * c + 2])
        recs = []
        guard = 0
        while pos != end:
            guard += 1
            if guard > 4096:
                raise CanonError('column %d: the list does not reach its '
                                 'end' % c)
            kind = bank1d[pos]
            if kind == K_NEXT:
                pos = bank1d[pos + 1] << 8
                continue
            if kind not in (K_TEX, K_FILL):
                raise CanonError('column %d: a record of kind %d from the '
                                 'walls' % (c, kind))
            r = bank1d[pos:pos + UP_SIZES[kind]]
            if kind == K_TEX:
                recs.append(('tex', r[1], r[2], r[3], r[4], r[5], r[6],
                             le(r[7:10]), r[10]))
            else:
                recs.append(('fill', r[1], r[2], r[3], r[4]))
            pos += UP_SIZES[kind]
        if recs:
            out[c] = recs
    return out


def staged_bytes(snap: 'Snapshot', stg_bank: int, stg_ptr: int) -> bytes:
    """The native staging then the spill, to the staging pointer."""
    if stg_bank == 0:
        return snap.aux(0, R.STAGE, stg_ptr - R.STAGE)
    data = snap.aux(0, R.STAGE, R.STAGE_END - R.STAGE)
    for bank in R.RECSP:
        if bank < stg_bank:
            data += snap.aux(bank, 0x0200, R.STAGE_END - 0x0200)
        elif bank == stg_bank:
            data += snap.aux(bank, 0x0200, stg_ptr - 0x0200)
    return data


def native_records(data: bytes, slots: Dict[Tuple[int, int], int]
                   ) -> Dict[int, List[Tuple]]:
    out: Dict[int, List[Tuple]] = {}
    at = 0
    while at < len(data):
        kind = data[at]
        if kind == K_TEX:
            r = data[at:at + 12]
            key = (r[10], le(r[8:10]))
            if key not in slots:
                raise CanonError('a record\'s texels at %d:$%04X are no slot'
                                 % key)
            out.setdefault(r[1], []).append(
                ('tex', r[2], r[3], r[4], r[5], r[6], r[7], slots[key],
                 r[11]))
            at += 12
        elif kind == K_FILL:
            r = data[at:at + 6]
            out.setdefault(r[1], []).append(('fill', r[2], r[3], r[4], r[5]))
            at += 6
        else:
            raise CanonError('a staged record of kind %d at %d' % (kind, at))
    return out


def ref_state(d, sym) -> Dict[str, Any]:
    """The clips, spans and plane state of a reference dump."""
    a = sym.address
    sp = d.read(0x23EF00, 0xC00)
    return {
        'floorclip': words_low(d.read(a('floorclip'), 320), 'floorclip'),
        'ceilclip': words_low(d.read(a('ceilingclip'), 320), 'ceilingclip'),
        'solidcol': list(d.read(a('solidcol'), 160)),
        'didsolid': le(d.read(a('didsolidcol'), 2)),
        'spans': [sp[0x200 * t + 2 * c + k] for t in range(4)
                  for k in (0, 1) for c in range(160)],
        'cv': [sp[0x800 + 2 * c + k] for k in (0, 1) for c in range(160)],
        'wstate': {n: le(d.read(WPAGE + o, 2)) for n, o in W_STATE},
    }


def native_state(snap: 'Snapshot') -> Dict[str, Any]:
    F = R.FRAME
    m = snap.main
    return {
        'floorclip': list(m(R.FLOORCLIP, 160)),
        'ceilclip': list(m(R.CEILCLIP, 160)),
        'solidcol': list(m(R.SOLIDCOL, 160)),
        'didsolid': m(F['DIDSOLID'], 1)[0],
        'spans': list(m(R.SPANS, 8 * 160)),
        'cv': list(m(R.CVFIRST, 320)),
        'wstate': {n: le(m(F[n], 2)) for n, _ in W_STATE},
    }


def ref_opening(d, sym, index: int) -> int:
    return le(d.read(sym.address('openings') + 2 * index, 2))


def ref_drawseg(d, sym, index: int, segs: int) -> Dict[str, Any]:
    """Upstream's drawseg `index` in a dump, the fields it defines."""
    base = sym.address('_s_drawsegs') + 42 * index
    f = {k: le(d.read(base + o, 4)) for k, o in DS_UP.items()}
    seg, rest = divmod((f['curline'] & 0xFFFFFF) - segs, 18)
    if rest or seg < 0:
        raise CanonError('drawseg %d: curline $%06X is no seg'
                         % (index, f['curline']))
    x1, x2 = f['x1'] & 0xFF, f['x2'] & 0xFF
    sil = f['sil'] & 0xFF
    openings = sym.address('openings')

    def clip(ptr: int) -> Any:
        ptr &= 0xFFFFFF
        if ptr == sym.address('screenheightarray'):
            return 'screenheightarray'
        if ptr == sym.address('negonearray'):
            return 'negonearray'
        off = ptr - openings
        if off % 2:
            raise CanonError('drawseg %d: an odd opening pointer' % index)
        return off // 2             # the opening index less x1
    out = {'seg': seg, 'x1': x1, 'x2': x2, 'scale1': f['scale1'],
           'scale2': f['scale2'], 'sil': sil}
    m = f['masked'] & 0xFFFFFF
    out['masked'] = None if m == 0 else clip(m)
    if x2 > x1:
        out['scalestep'] = f['scalestep']
    if sil & 1:
        out['bsil'] = f['bsil']
        out['botclip'] = clip(f['botclip'])
    if sil & 2:
        out['tsil'] = f['tsil']
        out['topclip'] = clip(f['topclip'])
    return out


def native_drawseg(snap: 'Snapshot', index: int) -> Dict[str, Any]:
    r = snap.aux(R.RENDB, R.DRAWSEGS + R.DS_SIZE * index, R.DS_SIZE)
    D = R.DS

    def g(k: str, n: int) -> int:
        return le(r[D[k]:D[k] + n])

    def clip(v: int) -> Any:
        if v == R.DS_SCREENH:
            return 'screenheightarray'
        if v == R.DS_NEGONE:
            return 'negonearray'
        return s16(v)
    x1, x2, sil = r[D['X1']], r[D['X2']], r[D['SIL']]
    out = {'seg': g('SEG', 2), 'x1': x1, 'x2': x2,
           'scale1': g('SCALE1', 4), 'scale2': g('SCALE2', 4), 'sil': sil}
    m = g('MASKED', 2)
    out['masked'] = None if m == R.DS_NULL else s16(m)
    if x2 > x1:
        out['scalestep'] = g('STEP', 4)
    if sil & 1:
        out['bsil'] = g('BSIL', 4)
        out['botclip'] = clip(g('BOTCLIP', 2))
    if sil & 2:
        out['tsil'] = g('TSIL', 4)
        out['topclip'] = clip(g('TOPCLIP', 2))
    return out


def ref_openings(d, sym, ds: Dict[str, Any]) -> Dict[str, List[int]]:
    """The openings a drawseg's fields point at: its masked columns (16
    bits) and its clips (low bytes; the high bytes must be 0)."""
    out = {}
    cols = range(ds['x1'], ds['x2'] + 1)
    if isinstance(ds['masked'], int):
        # upstream's index is the pointer's (openings + 2 (i - x1))
        out['masked'] = [ref_opening(d, sym, ds['masked'] + x)
                         for x in cols]
    for key in ('topclip', 'botclip'):
        v = ds.get(key)
        if isinstance(v, int):
            vals = [ref_opening(d, sym, v + x) for x in cols]
            if any(x >> 8 for x in vals):
                raise CanonError('a saved clip has a high byte')
            out[key] = vals
    return out


def native_openings(snap: 'Snapshot', ds: Dict[str, Any]
                    ) -> Dict[str, List[int]]:
    out = {}
    cols = range(ds['x1'], ds['x2'] + 1)

    def lo(i: int) -> int:
        return snap.aux(0, R.OPENLO + i, 1)[0]

    def hi(i: int) -> int:
        return snap.aux(R.RENDB, R.OPENHI + i, 1)[0]
    if isinstance(ds['masked'], int):
        out['masked'] = [lo(ds['masked'] + x) | hi(ds['masked'] + x) << 8
                         for x in cols]
    for key in ('topclip', 'botclip'):
        v = ds.get(key)
        if isinstance(v, int):
            out[key] = [lo(v + x) for x in cols]
    return out


def ref_routine(case, kind: str, sym, info: Dict[str, Any]
                ) -> Dict[str, Any]:
    """The canonical outputs of upstream's call (kind 'wall' or 'seg')."""
    entry = case.points['SWE' if kind == 'wall' else 'SLE']
    exit_ = case.points['SWR' if kind == 'wall' else 'SLR']
    last = case.points[case.header['order'][-1]]
    bank1d = last.get(RECBANK, 0x10000)
    colw_exit = exit_.get(sym.address('COLW'), 320)
    from native.segdesc import Ref
    ent, ex = Ref(entry, sym), Ref(exit_, sym)
    out = ref_state(ex, sym)
    out['records'] = ref_records(ent, colw_exit, bank1d, sym)
    if kind == 'wall':
        a = sym.address
        ds_index = (le(entry.get(a('ds_p'), 2)) - (a('_s_drawsegs') &
                                                   0xFFFF)) // 42
        count_in = le(entry.get(DS_COUNT, 2))
        count_out = le(exit_.get(DS_COUNT, 2))
        out['dscount'] = count_out
        out['lastopening'] = ex.opening_index(le(exit_.get(
            a('lastopening'), 3)))
        out['rw_step'] = le(exit_.get(a('rw_scalestep'), 4))
        if count_out != count_in:
            if ds_index != count_in:
                raise CanonError('ds_p is drawseg %d, dsCount %d'
                                 % (ds_index, count_in))
            ds = ref_drawseg(ex, sym, ds_index, info['segs'])
            out['drawseg'] = ds
            out['openings'] = ref_openings(ex, sym, ds)
            out['dsx'] = (exit_.get(DSX1_UP + count_in, 1)[0],
                          exit_.get(DSX2_UP + count_in, 1)[0])
        # ML_MAPPED: R_StoreWallRange sets it (r_wall65.s:360-366) unless
        # the drawsegs are full; the line's bit at drawMasked (P3) must
        # agree. Expected: set, or as it was before the call.
        full = count_in >= 128
        if not full and not info['mapped_p3']:
            raise CanonError('the line is not mapped at drawMasked')
        out['mapped'] = info['mapped_in'] if full else True
    else:
        if info['flags']['MASKED']:
            maskb = info['maskb']
            out['masked'] = [ref_opening(ex, sym, maskb + x)
                             for x in range(info['x'], info['stopx'])]
    return out


def native_routine(end: 'Snapshot', kind: str, info: Dict[str, Any],
                   slots: Dict[Tuple[int, int], int],
                   lnmap_in: bytes) -> Dict[str, Any]:
    F = R.FRAME
    m = end.main
    out = native_state(end)
    stg_bank = m(F['STG_BANK'], 1)[0]
    stg_ptr = le(m(F['STG_PTR'], 2))
    out['records'] = native_records(staged_bytes(end, stg_bank, stg_ptr),
                                    slots)
    if kind == 'wall':
        count_in = info['dscount']
        count_out = m(F['DSCOUNT'], 1)[0]
        out['dscount'] = count_out
        out['lastopening'] = le(m(F['LASTOPEN'], 2))
        out['rw_step'] = le(m(F['RW_STEP'], 4))
        if count_out != count_in:
            ds = native_drawseg(end, count_in)
            out['drawseg'] = ds
            out['openings'] = native_openings(end, ds)
            out['dsx'] = (m(R.DSX1 + count_in, 1)[0],
                          m(R.DSX2 + count_in, 1)[0])
        line = info['line']
        after = m(R.LNMAP, R.LNMAP_LINES // 8)
        out['mapped'] = bool(after[line >> 3] & (1 << (line & 7)))
        changed = [i for i in range(len(after)) if after[i] != lnmap_in[i]
                   and i != line >> 3]
        if changed or (after[line >> 3] | (1 << (line & 7))) != \
                (lnmap_in[line >> 3] | (1 << (line & 7))):
            out['lnmap_other'] = 'changed'
    else:
        if info['flags']['MASKED']:
            maskb = info['maskb']
            out['masked'] = [
                end.aux(0, R.OPENLO + maskb + x, 1)[0] |
                end.aux(R.RENDB, R.OPENHI + maskb + x, 1)[0] << 8
                for x in range(info['x'], info['stopx'])]
    return out


def diff_routine(ref: Dict[str, Any], nat: Dict[str, Any]) -> List[str]:
    out = []
    keys = sorted(set(ref) | set(nat))
    for key in keys:
        a, b = ref.get(key), nat.get(key)
        if a == b:
            continue
        if key == 'records':
            cols = sorted(set(a or {}) | set(b or {}))
            bad = [c for c in cols if (a or {}).get(c) != (b or {}).get(c)]
            c = bad[0]
            ra, rb = (a or {}).get(c, []), (b or {}).get(c, [])
            k = next((i for i in range(max(len(ra), len(rb)))
                      if i >= len(ra) or i >= len(rb) or ra[i] != rb[i]), 0)
            out.append('records: %d columns differ (first %d, record %d: '
                       'native %s, reference %s)' % (
                           len(bad), c, k, rb[k] if k < len(rb) else None,
                           ra[k] if k < len(ra) else None))
        elif isinstance(a, list) and isinstance(b, list) and \
                len(a) == len(b):
            bad = [i for i in range(len(a)) if a[i] != b[i]]
            out.append('%s: %d differ (first %d: native %r, reference %r)'
                       % (key, len(bad), bad[0], b[bad[0]], a[bad[0]]))
        elif isinstance(a, dict) and isinstance(b, dict):
            fields = sorted(k for k in set(a) | set(b)
                            if a.get(k) != b.get(k))
            out.append('%s: %s: native %s, reference %s' % (
                key, ','.join(fields), [b.get(f) for f in fields],
                [a.get(f) for f in fields]))
        else:
            out.append('%s: native %r, reference %r' % (key, b, a))
    return out


# ===========================================================================
# Frame mode (stage C, RENDER.md 2.4, 4.3; acceptance 1): the whole front
# end from R_FillStamps to drawMasked, against the reference at drawMasked
# (P3) and at each early flush (P2):
#
#   records     every record of the frame by column, in the order made:
#               upstream's lists walked from COLPAGE(c) through K_NEXT to
#               COLW(c), those of each early flush (P2) first, in flush
#               order, then those at drawMasked; the native staging and
#               spill bucketed by the column byte (NATIVE.md 11). The lists
#               must be empty at R_FillStamps (P0): the replay of the frame
#               before emptied them. Only K_TEX and K_FILL come from the
#               front end
#   clips       FLOORCLIP, CEILCLIP (low bytes; the high bytes must be 0),
#               SOLIDCOL, didsolidcol
#   drawsegs    the count, each drawseg's fields as upstream defines them
#               (ref_drawseg), its dsX1/dsX2, ds_p at the count; the
#               openings each one's clips and masked columns point to;
#               lastopening
#   spans       the 8 planes of FS_*; the covered ranges, which must be 0
#               (only the masked phase sets them)
#   stamps      W_FSC, W_FSP, W_TOPR, W_BOTR; the plane state W_LCC, W_LFC,
#               W_CEILW, W_FLOORW; rw_scalestep
#   weapon      FR_SKIP, W_WSK, WPREV, WCLIP
#   validcount  validcount, every sector's validcount
#   mapped      ML_MAPPED of every line (LNMAP)
#   vtxangle    the vertex angles computed (ref816's vtxAngle calls)
# ===========================================================================

def walk_lists(d, sym: blink.Symbols, where: str) -> Dict[int, List[Tuple]]:
    """The records of upstream's column lists in a dump (bank $1D and
    COLW), each column from its first page, K_NEXT dropped."""
    colw = d.read(sym.address('COLW'), 320)
    bank = RECBANK
    out: Dict[int, List[Tuple]] = {}
    for c in range(160):
        end = le(colw[2 * c:2 * c + 2])
        page, off = ulists.colpage(c), 0
        recs = []
        steps = 0
        while (page << 8 | off) != end:
            steps += 1
            if steps > 4096 or off >= 256:
                raise CanonError('%s: column %d: the list does not reach '
                                 'its end $%04X' % (where, c, end))
            at = bank + (page << 8) + off
            kind = d.read(at, 1)[0]
            if kind == K_NEXT:
                page, off = d.read(at + 1, 1)[0], 0
                continue
            if kind not in (K_TEX, K_FILL):
                raise CanonError('%s: column %d: a record of kind %d before '
                                 'drawMasked' % (where, c, kind))
            r = d.read(at, UP_SIZES[kind])
            if kind == K_TEX:
                recs.append(('tex', r[1], r[2], r[3], r[4], r[5], r[6],
                             le(r[7:10]), r[10]))
            else:
                recs.append(('fill', r[1], r[2], r[3], r[4]))
            off += UP_SIZES[kind]
        if recs:
            out[c] = recs
    return out


def frame_truth(frame, sym: blink.Symbols, nlines: int) -> Dict[str, Any]:
    """The reference's outputs of the frame at drawMasked (P3), with the
    records of its early flushes (P2)."""
    a = sym.address
    p0, p3 = frame.dump('p0'), frame.dump('p3')
    colw0 = p0.read(a('COLW'), 320)
    for c in range(160):
        if le(colw0[2 * c:2 * c + 2]) != ulists.colpage(c) << 8:
            raise CanonError('%s: the list of column %d is not empty at '
                             'R_FillStamps' % (frame.name, c))
    records: Dict[int, List[Tuple]] = {}
    for k in range(frame.meta.get('flushes', 0)):
        for c, recs in walk_lists(frame.dump('p2-%d' % k), sym,
                                  'flush %d' % k).items():
            records.setdefault(c, []).extend(recs)
    for c, recs in walk_lists(p3, sym, 'drawMasked').items():
        records.setdefault(c, []).extend(recs)
    out: Dict[str, Any] = {'records': records}
    out['floorclip'] = words_low(p3.read(a('floorclip'), 320), 'floorclip')
    out['ceilclip'] = words_low(p3.read(a('ceilingclip'), 320),
                                'ceilingclip')
    out['solidcol'] = list(p3.read(a('solidcol'), 160))
    didsolid = le(p3.read(a('didsolidcol'), 2))
    if didsolid > 255:
        raise CanonError('didsolidcol $%04X' % didsolid)
    out['didsolid'] = didsolid
    count = p3.u(DS_COUNT, 2)
    ds_p = (p3.u(a('ds_p'), 2) - (a('_s_drawsegs') & 0xFFFF)) // SIZEOF_DS
    if ds_p != count:
        raise CanonError('ds_p is drawseg %d, dsCount %d' % (ds_p, count))
    out['dscount'] = count
    segs = p0.u(a('_g_segs'), 3)
    drawsegs, openings, dsx = [], [], []
    for i in range(count):
        ds = ref_drawseg(p3, sym, i, segs)
        drawsegs.append(ds)
        openings.append(ref_openings(p3, sym, ds))
        dsx.append((p3.read(DSX1_UP + i, 1)[0], p3.read(DSX2_UP + i, 1)[0]))
    out['drawsegs'], out['openings'], out['dsx'] = drawsegs, openings, dsx
    out['lastopening'] = (p3.u(a('lastopening'), 3) - a('openings')) // 2
    sp = p3.read(MM_FS, 0xC00)
    out['spans'] = [sp[0x200 * t + 2 * c + k] for t in range(4)
                    for k in (0, 1) for c in range(160)]
    cv = [sp[0x800 + 2 * c + k] for k in (0, 1) for c in range(160)]
    if any(cv):
        raise CanonError('a covered range before drawMasked')
    out['cv'] = cv
    w = ref_stamps_weapon(p3, sym)
    del w['fs_stamps']                  # (in the spans)
    out.update(w)
    out['rw_step'] = p3.u(a('rw_scalestep'), 4)
    secs = p3.u(a('_g_sectors'), 3)
    nsec = p3.u(a('_g_numsectors'), 2)
    out['validcount'] = p3.u(a('validcount'), 2)
    out['sector_valid'] = [p3.u(secs + SIZEOF_SEC * i + 20, 2)
                           for i in range(nsec)]
    lines = p3.u(a('_g_lines'), 3)
    out['mapped'] = [bool(p3.u(lines + SIZEOF_LINE * i + OFS_LINE_R_FLAGS,
                               2) & ML_MAPPED) for i in range(nlines)]
    if frame.calls['vtxangle'] is not None:     # (a synthetic frame: none)
        out['vtxangle'] = frame.calls['vtxangle']
    return out


def frame_native(end: 'Snapshot', slots: Dict[Tuple[int, int], int],
                 nsectors: int, nlines: int) -> Dict[str, Any]:
    """The native front end's outputs at the end of nr_frame."""
    F = R.FRAME
    m = end.main
    stg_bank = m(F['STG_BANK'], 1)[0]
    stg_ptr = le(m(F['STG_PTR'], 2))
    out: Dict[str, Any] = {'records': native_records(
        staged_bytes(end, stg_bank, stg_ptr), slots)}
    out['floorclip'] = list(m(R.FLOORCLIP, 160))
    out['ceilclip'] = list(m(R.CEILCLIP, 160))
    out['solidcol'] = list(m(R.SOLIDCOL, 160))
    out['didsolid'] = m(F['DIDSOLID'], 1)[0]
    count = m(F['DSCOUNT'], 1)[0]
    out['dscount'] = count
    drawsegs, openings, dsx = [], [], []
    for i in range(count):
        ds = native_drawseg(end, i)
        drawsegs.append(ds)
        openings.append(native_openings(end, ds))
        dsx.append((m(R.DSX1 + i, 1)[0], m(R.DSX2 + i, 1)[0]))
    out['drawsegs'], out['openings'], out['dsx'] = drawsegs, openings, dsx
    out['lastopening'] = le(m(F['LASTOPEN'], 2))
    out['spans'] = list(m(R.SPANS, 8 * 160))
    out['cv'] = list(m(R.CVFIRST, 320))
    w = native_stamps_weapon(m)
    del w['fs_stamps']
    out.update(w)
    out['rw_step'] = le(m(F['RW_STEP'], 4))
    out['validcount'] = le(m(F['VALIDCOUNT'], 2))
    out['sector_valid'] = [le(end.aux(R.LVMAP, R.SECTORS.address(i) +
                                      R.SEC['VALID'], 2))
                           for i in range(nsectors)]
    bits = m(R.LNMAP, R.LNMAP_LINES // 8)
    out['mapped'] = [bool(bits[i >> 3] & (1 << (i & 7)))
                     for i in range(nlines)]
    out['vtxangle'] = le(m(F['VA_COUNT'], 2))
    out['status'] = m(F['STATUS'], 1)[0]
    out['rules'] = m(F['RULES'], 1)[0]
    return out


RULE_NAMES = {R.RULE_SINE: 'the sine of a column seen from behind',
              R.RULE_TANGENT: 'a texture angle past finetangent'}


def rules_problem(rules: int) -> str:
    """The problem a frame or call whose native run took a rule of our own
    reports (RENDER.md 3.9): upstream left its tables there, so it cannot
    be compared; a case that expects it says so (render_check.RULED)."""
    names = [n for bit, n in sorted(RULE_NAMES.items()) if rules & bit]
    return 'rules %d: a rule of our own ran (%s; upstream leaves its ' \
        'tables)' % (rules, ', '.join(names) or '?')


def diff_frame(ref: Dict[str, Any], nat: Dict[str, Any]) -> List[str]:
    """Every difference of frame mode, described; empty when equal."""
    out = []
    if nat.get('status'):
        out.append('status %d' % nat['status'])
    if nat.get('rules'):
        out.append(rules_problem(nat['rules']))
    for key in ('drawsegs', 'openings', 'dsx'):
        a, b = ref.get(key, []), nat.get(key, [])
        if a != b:
            bad = [i for i in range(max(len(a), len(b)))
                   if i >= len(a) or i >= len(b) or a[i] != b[i]]
            i = bad[0]
            out.append('%s: %d differ (first %d: native %r, reference %r)'
                       % (key, len(bad), i, b[i] if i < len(b) else None,
                          a[i] if i < len(a) else None))
    rest = {k: v for k, v in ref.items()
            if k not in ('drawsegs', 'openings', 'dsx')}
    nrest = {k: v for k, v in nat.items()
             if k not in ('drawsegs', 'openings', 'dsx', 'status',
                          'rules')}
    return out + diff_routine(rest, nrest)
