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


def ref_stamps_weapon(d, sym: blink.Symbols,
                      index: Dict[int, int]) -> Dict[str, Any]:
    """R_FillStamps' and weaponClipSame's outputs in a reference dump:
    the span stamps (FS_STAMP: bytes 2c and 2c + 1 as two planes), the
    WPAGE stamps and plane state, FR_SKIP, W_WSK (a word whose high byte
    must be 0: the native one is a byte), WPREV (upstream's vissprite in
    the native 12 bytes, milestone 8's stage C: framestate.native_vis with
    the level's patch store index, `index`), WCLIP (its low bytes, written
    by weaponClipSame)."""
    from native import framestate as FS
    sp = d.read(MM_FS + 0x600, 0x200)
    out = {'fs_stamps': [sp[2 * c + k] for k in (0, 1) for c in range(160)]}
    for name, (off, n) in WPAGE_W.items():
        out[name.lower()] = le(d.read(0x000A00 + off, n))
    wsk = le(d.read(0x000A00 + W_WSK_OFS, 2))
    if wsk > 255:
        raise CanonError('W_WSK $%04X has a high byte' % wsk)
    out['w_wsk'] = wsk
    out['fr_skip'] = le(d.read(sym.address('FR_SKIP'), 2))
    out['wprev'] = list(FS.native_vis(d.read(MM_WCLIP + 0x180,
                                             FS.SIZEOF_VIS), index,
                                      sym.address('fullcolormap')))
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
    out['wprev'] = list(m(R.WPREV, R.WPREV_USED))
    out['wclip'] = list(m(R.WCLIP, 160))
    return out


def reference(frame, sym: blink.Symbols, index: Dict[int, int]
              ) -> Dict[str, Any]:
    """Checkpoint A's truth (`index`: the level's patch store index of
    each stored lump, framestate.store_index)."""
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
    entry.update(ref_stamps_weapon(b, sym, index))
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


def frame_truth(frame, sym: blink.Symbols, nlines: int,
                index: Dict[int, int]) -> Dict[str, Any]:
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
    w = ref_stamps_weapon(p3, sym, index)
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


# ===========================================================================
# Milestone 8, stage A (docs/RENDER-MASKED.md 2.4, 4.3, 5.1): the
# projection and the sort.
#
#   vis         the vissprites in the order made: x1, x2, the thing (its
#               RTHING slot: upstream's gx through framestate.slot_map),
#               its x and y, the lump (upstream's lump_num; natively the
#               patch header's), gz, startfrac, scale, xiscale,
#               texturemid, fracstep, topoffset (natively the patch
#               header's), the colormap as its record page (0 a shadow;
#               upstream's colormap - fullcolormap, a multiple of 256, over
#               256, + $46); natively also gzt = gz's high word +
#               topoffset
#   order       the sort's order (FR_ORDER after sortSkip, P3s) as
#               vissprite indexes; FR_SKIP, W_WSK after sortSkip
#   sectors     the sectors R_AddSprites was called for, in order (the
#               call log), against the walk's SPRSEC list
# ===========================================================================

SIZEOF_VIS_UP = 42
MM_W_WSK = 0x000AB0
CMAPS = 34


def colormap_page(ptr: int, full: int) -> int:
    """A vissprite's colormap pointer as its record page: 0 for NULL (a
    shadow), else $46 + (ptr - fullcolormap) / 256."""
    ptr &= 0xFFFFFF
    if ptr == 0:
        return 0
    off = ptr - full
    if off < 0 or off % 256 or off // 256 >= CMAPS:
        raise CanonError('a colormap pointer $%06X is no colormap' % ptr)
    return 0x46 + off // 256


def vis_truth(frame, sym: blink.Symbols) -> Dict[str, Any]:
    """The reference's vissprites at drawMasked (P3), the sort after
    sortSkip (P3s), the sectors of R_AddSprites (the call log; None for a
    synthetic frame, which has none)."""
    from native import framestate as FS
    a = sym.address
    p0, p3, p3s = frame.dump('p0'), frame.dump('p3'), frame.dump('p3s')
    secs = p0.u(a('_g_sectors'), 3)
    nsec = p0.u(a('_g_numsectors'), 2)
    slots = FS.slot_map(p0, sym, secs, nsec)
    full = a('fullcolormap')
    n = p3.u(a('num_vissprite'), 2)
    base = a('vissprites')
    vis = []
    for i in range(n):
        at = base + SIZEOF_VIS_UP * i

        def f(o: int, size: int) -> int:
            return p3.u(at + o, size)
        th = f(4, 4) & 0xFFFFFF
        if th not in slots:
            raise CanonError('vissprite %d: gx $%06X is no listed thing'
                             % (i, th))
        vis.append({'x1': f(0, 2), 'x2': f(2, 2), 'slot': slots[th],
                    'tx': p0.u(th + 12, 4), 'ty': p0.u(th + 16, 4),
                    'lump': f(34, 2), 'gz': f(12, 4), 'startfrac': f(16, 4),
                    'scale': f(20, 4), 'xiscale': f(24, 4),
                    'texturemid': f(28, 4), 'fracstep': f(32, 2),
                    'topoffset': f(36, 2),
                    'page': colormap_page(f(38, 4), full)})
    order = []
    for i in range(n):
        off = p3s.u(a('FR_ORDER') + 2 * i, 2)
        if off % SIZEOF_VIS_UP:
            raise CanonError('FR_ORDER %d is no vissprite' % i)
        order.append(off // SIZEOF_VIS_UP)
    wsk = p3s.u(MM_W_WSK, 2)
    if wsk > 255:
        raise CanonError('W_WSK $%04X has a high byte' % wsk)
    sectors = None
    if 'addsprites' in frame.calls:
        sectors = []
        for ptr, _ in frame.calls['addsprites']:
            k, r = divmod((ptr & 0xFFFFFF) - secs, SIZEOF_SEC)
            if r or not 0 <= k < nsec:
                raise CanonError('R_AddSprites of $%06X, no sector' % ptr)
            sectors.append(k)
    return {'vis': vis, 'order': order,
            'fr_skip': p3s.u(a('FR_SKIP'), 2), 'w_wsk': wsk,
            'sectors': sectors}


def vis_native(end: 'Snapshot') -> Dict[str, Any]:
    """The same of the native masked phase's end (nm_sort's return)."""
    F = R.FRAME
    m = end.main
    n = m(F['NVIS'], 1)[0]
    V = R.VISREC
    vis = []
    for i in range(n):
        r = m(R.VIS + R.VISREC_SIZE * i, R.VISREC_SIZE)

        def g(k: str, size: int) -> int:
            return le(r[V[k]:V[k] + size])
        patch = g('PATCH', 2)
        ph = end.aux(R.SPRT, R.PHDRS.address(patch), R.PHDR_SIZE)
        top = le(ph[R.PHDR['TOP']:R.PHDR['TOP'] + 2])
        gz = g('GZ', 4)
        rec = {'x1': r[V['X1']], 'x2': r[V['X2']], 'slot': g('SLOT', 2),
               'tx': g('TX', 4), 'ty': g('TY', 4),
               'lump': le(ph[R.PHDR['LUMP']:R.PHDR['LUMP'] + 2]),
               'gz': gz, 'startfrac': g('STARTFRAC', 4),
               'scale': g('SCALE', 4), 'xiscale': g('XISCALE', 4),
               'texturemid': g('TMID', 4), 'fracstep': g('FSTEP', 2),
               'topoffset': top, 'page': r[V['PAGE']]}
        if g('GZT', 2) != ((gz >> 16) + top) & 0xFFFF:
            rec['gzt'] = 'gzt %d, not gz.hi + topoffset' % g('GZT', 2)
        vis.append(rec)
    return {'vis': vis, 'order': list(m(R.FRORD, n)),
            'fr_skip': le(m(F['FR_SKIP'], 2)), 'w_wsk': m(F['W_WSK'], 1)[0],
            'sectors': list(end.aux(0, R.SPRSEC, m(F['SPRN'], 1)[0])),
            'status': m(F['STATUS'], 1)[0], 'rules': m(F['RULES'], 1)[0]}


def dsw_problems(end: 'Snapshot') -> List[str]:
    """The drawseg copy: W's DSW holds the native drawsegs whose DSX1 is
    not 255, the first DSW_MAX, in index order (RENDER-MASKED.md 1.10)."""
    m = end.main
    count = m(R.FRAME['DSCOUNT'], 1)[0]
    want = [i for i in range(count) if m(R.DSX1 + i, 1)[0] != 0xFF]
    want = want[:R.DSW_MAX]
    out = []
    for k, i in enumerate(want):
        got = m(R.DSW + R.DS_SIZE * k, R.DS_SIZE)
        if got != end.aux(R.RENDB, R.DRAWSEGS + R.DS_SIZE * i, R.DS_SIZE):
            out.append('DSW %d is not drawseg %d' % (k, i))
            break
    return out


def diff_vis(ref: Dict[str, Any], nat: Dict[str, Any]) -> List[str]:
    """Every difference of the projection and the sort, described."""
    out = []
    if nat.get('status'):
        out.append('status %d' % nat['status'])
    rv, nv = ref['vis'], nat['vis']
    if len(rv) != len(nv):
        out.append('vissprites: native %d, reference %d' % (len(nv),
                                                            len(rv)))
    for i, (a, b) in enumerate(zip(rv, nv)):
        if a != b:
            keys = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            out.append('vissprite %d: %s: native %s, reference %s' % (
                i, ','.join(keys), [b.get(k) for k in keys],
                [a.get(k) for k in keys]))
            break
    for key in ('order', 'fr_skip', 'w_wsk'):
        if ref[key] != nat[key]:
            out.append('%s: native %r, reference %r' % (key, nat[key],
                                                        ref[key]))
    if ref['sectors'] is not None and ref['sectors'] != nat['sectors']:
        out.append('the listed sectors: native %d %s, reference %d %s' % (
            len(nat['sectors']), nat['sectors'][:8], len(ref['sectors']),
            ref['sectors'][:8]))
    return out


# ===========================================================================
# Milestone 8, stage B (docs/RENDER-MASKED.md 2.4, 4.2, 4.3, 5.2): the
# masked phase to the weapon's draw, against the reference at playerSkip
# (P3w), with the records of any early flush (P2) before it.
#
#   records     every record of the frame by column in the order made:
#               upstream's lists walked from COLPAGE(c) through K_NEXT (each
#               early flush's first, in flush order, then P3w's); the
#               native staging and spill bucketed by the column byte. A
#               K_TEX's texels as upstream's address (a texel slot through
#               the level's texture map, a patch store address through its
#               patch map); a K_TEXC's as its chain's bank with R_TCSRC; a
#               K_FUZZ's row, count and fuzz position
#   cv          CV_ROW (first, end: two planes) and, on a frame with no
#               early flush, each covered column's record as its index in
#               the column's list (upstream: CV_REC's address; native: the
#               sequence number's record)
#   spans       the 8 planes of FS_*
#   pages       UPOFS against COLW's low bytes, XPUSED against XPNEXT
#               ($CE + XPUSED, 0 when all 50 are used), UPFLUSH against the
#               early flushes
#   fzpos, rw_step, floorclip, ceilclip (words' low bytes), the masked
#               columns' openings of every drawseg that has them (the drawn
#               marks, $7FFF)
#   cliplog     each sprite's R_DrawVisSprite call (the call log: VS_CLIP 0,
#               a vissprite of the array, in order) against the native clip
#               log: the vissprite's index, floorclip and ceilingclip (all
#               160 columns)
# ===========================================================================

K_TEXC, K_FUZZ, K_OVL = 6, 8, 10
XP_FIRST = 0xCE
# K_OVL: the automap overlay's pixel (milestone 11: the kind, the column,
# the row, the nibble kept, the colour; bucket.s's ssize)
NATIVE_SIZES = {K_TEX: 12, K_FILL: 6, K_TEXC: 8, K_FUZZ: 5, K_OVL: 5}


def patch_map(level_dir: Path) -> List[Tuple[int, int, int, int]]:
    """The level's patch map (levelconv.py): (bank, address, size with the
    tail, upstream's address) of each stored lump."""
    import json
    pm = json.loads((Path(level_dir) / 'patchmap.json').read_text())
    return sorted(tuple(e) for e in pm['entries'])


def native_src(bank: int, addr: int, slots: Dict[Tuple[int, int], int],
               pmap: List[Tuple[int, int, int, int]]) -> int:
    """A native texel source as upstream's address: a texel slot, or a
    place in the patch store."""
    key = (bank, addr)
    if key in slots:
        return slots[key]
    import bisect
    k = bisect.bisect_right(pmap, (bank, addr, 1 << 30, 0)) - 1
    if k >= 0:
        b, at, size, up = pmap[k]
        if b == bank and at <= addr < at + size:
            return up + addr - at
    raise CanonError('a record\'s texels at %d:$%04X are neither a slot nor '
                     'the patch store' % key)


def walk_lists_all(d, sym: blink.Symbols, where: str
                   ) -> Tuple[Dict[int, List[Tuple]], Dict[int, Dict[int, int]]]:
    """The records of upstream's lists in a dump, every kind (K_NEXT
    dropped), and each record's place (page << 8 | offset) -> its index in
    its column's list."""
    colw = d.read(sym.address('COLW'), 320)
    bank = RECBANK
    out: Dict[int, List[Tuple]] = {}
    places: Dict[int, Dict[int, int]] = {}
    for c in range(160):
        end = le(colw[2 * c:2 * c + 2])
        page, off = ulists.colpage(c), 0
        recs: List[Tuple] = []
        idx: Dict[int, int] = {}
        chain = None
        steps = 0
        while (page << 8 | off) != end:
            steps += 1
            if steps > 8192 or off >= 256:
                raise CanonError('%s: column %d: the list does not reach '
                                 'its end $%04X' % (where, c, end))
            at = bank + (page << 8) + off
            kind = d.read(at, 1)[0]
            if kind == K_NEXT:
                page, off = d.read(at + 1, 1)[0], 0
                continue
            if kind not in UP_SIZES:
                raise CanonError('%s: column %d: a record of kind %d'
                                 % (where, c, kind))
            r = d.read(at, UP_SIZES[kind])
            idx[page << 8 | off] = len(recs)
            if kind == K_TEX:
                chain = r[9]
                recs.append(('tex', r[1], r[2], r[3], r[4], r[5], r[6],
                             le(r[7:10]), r[10]))
            elif kind == K_FILL:
                recs.append(('fill', r[1], r[2], r[3], r[4]))
            elif kind == K_TEXC:
                if chain is None:
                    raise CanonError('%s: column %d: a K_TEXC with no K_TEX '
                                     'before it' % (where, c))
                recs.append(('texc', r[1], r[2], r[3], r[4],
                             chain << 16 | le(r[5:7])))
            elif kind == K_OVL:
                recs.append(('ovl', r[1], r[2], r[3]))
            else:
                recs.append(('fuzz', r[1], r[2], r[3]))
            off += UP_SIZES[kind]
        if recs:
            out[c] = recs
        places[c] = idx
    return out, places


def native_records_all(data: bytes, slots: Dict[Tuple[int, int], int],
                       pmap: List[Tuple[int, int, int, int]]
                       ) -> Tuple[Dict[int, List[Tuple]], List[Tuple[int, int]]]:
    """The native staging by column (every kind), and each record's
    (column, index in its column) by sequence number."""
    out: Dict[int, List[Tuple]] = {}
    seq: List[Tuple[int, int]] = []
    chain: Dict[int, int] = {}
    at = 0
    while at < len(data):
        kind = data[at]
        if kind not in NATIVE_SIZES:
            raise CanonError('a staged record of kind %d at %d' % (kind, at))
        r = data[at:at + NATIVE_SIZES[kind]]
        if len(r) < NATIVE_SIZES[kind]:
            raise CanonError('the staging ends in a record')
        c = r[1]
        lst = out.setdefault(c, [])
        seq.append((c, len(lst)))
        if kind == K_TEX:
            chain[c] = r[10]
            lst.append(('tex', r[2], r[3], r[4], r[5], r[6], r[7],
                        native_src(r[10], le(r[8:10]), slots, pmap),
                        r[11]))
        elif kind == K_FILL:
            lst.append(('fill', r[2], r[3], r[4], r[5]))
        elif kind == K_TEXC:
            if c not in chain:
                raise CanonError('column %d: a K_TEXC with no K_TEX before '
                                 'it' % c)
            lst.append(('texc', r[2], r[3], r[4], r[5],
                        native_src(chain[c], le(r[6:8]), slots, pmap)))
        elif kind == K_OVL:
            lst.append(('ovl', r[2], r[3], r[4]))
        else:
            lst.append(('fuzz', r[2], r[3], r[4]))
        at += NATIVE_SIZES[kind]
    return out, seq


def masked_truth(frame, sym: blink.Symbols) -> Dict[str, Any]:
    """The reference's outputs at playerSkip (P3w), stage B's."""
    a = sym.address
    p3w = frame.dump('p3w')
    cyc = p3w.header['cycles']
    records: Dict[int, List[Tuple]] = {}
    flushes = 0
    for k in range(frame.meta.get('flushes', 0)):
        for c, recs in walk_lists_all(frame.dump('p2-%d' % k), sym,
                                      'flush %d' % k)[0].items():
            records.setdefault(c, []).extend(recs)
        flushes += 1
    for k in range(frame.meta.get('mflushes', 0)):
        d = frame.dump('p2m-%d' % k)
        if d.header['cycles'] > cyc:
            continue                    # (the weapon's draw: after P3w)
        for c, recs in walk_lists_all(d, sym, 'masked flush %d' % k
                                      )[0].items():
            records.setdefault(c, []).extend(recs)
        flushes += 1
    lists, places = walk_lists_all(p3w, sym, 'playerSkip')
    before = {c: len(v) for c, v in records.items()}
    for c, recs in lists.items():
        records.setdefault(c, []).extend(recs)
    out: Dict[str, Any] = {'records': records, 'flushes': flushes}
    sp = p3w.read(MM_FS, 0xC00)
    out['spans'] = [sp[0x200 * t + 2 * c + k] for t in range(4)
                    for k in (0, 1) for c in range(160)]
    if not flushes:
        # (an early flush resets upstream's ranges, the native model keeps
        # the frame's: RENDER-MASKED.md 2.4, 3.4; not compared then)
        out['cv'] = [sp[0x800 + 2 * c + k] for k in (0, 1)
                     for c in range(160)]
        cvrec = {}
        for c in range(160):
            if sp[0x800 + 2 * c] < sp[0x800 + 2 * c + 1]:
                place = le(sp[0xA00 + 2 * c:0xA00 + 2 * c + 2])
                if place not in places[c]:
                    raise CanonError('column %d: CV_REC $%04X is no record '
                                     'of its list' % (c, place))
                cvrec[c] = places[c][place] + before.get(c, 0)
        out['cvrec'] = cvrec
    colw = p3w.read(a('COLW'), 320)
    out['upofs'] = [colw[2 * c] for c in range(160)]
    out['xpnext'] = p3w.u(a('XPNEXT'), 1)
    out['fzpos'] = p3w.u(a('FZ_POS'), 2)
    out['rw_step'] = p3w.u(a('rw_scalestep'), 4)
    out['floorclip'] = words_low(p3w.read(a('floorclip'), 320), 'floorclip')
    out['ceilclip'] = words_low(p3w.read(a('ceilingclip'), 320),
                                'ceilingclip')
    p0 = frame.dump('p0')
    segs = p0.u(a('_g_segs'), 3)
    count = frame.dump('p3').u(DS_COUNT, 2)   # (the drawsegs stay; P3w
    masked = {}                                 #   has their openings)
    for i in range(count):
        ds = ref_drawseg(p3w, sym, i, segs)
        if isinstance(ds['masked'], int):
            masked[i] = ref_openings(p3w, sym, ds)['masked']
    out['masked'] = masked
    calls = []
    vbase = a('vissprites')
    for call in frame.calls.get('drawvis', []):
        mem = call['in']['mem']
        if le(bytes.fromhex(mem[1])):
            continue                    # VS_CLIP: the weapon's clip pass
        ptr = le(bytes.fromhex(mem[0])) & 0xFFFFFF
        if not vbase <= ptr < vbase + SIZEOF_VIS_UP * 80:
            continue                    # the weapon's draw (FR_VIS)
        if (ptr - vbase) % SIZEOF_VIS_UP:
            raise CanonError('R_DrawVisSprite of $%06X: no vissprite' % ptr)
        fl = bytes.fromhex(mem[4])
        ce = bytes.fromhex(mem[5])
        calls.append({'vis': (ptr - vbase) // SIZEOF_VIS_UP,
                      'floorclip': words_low(fl, 'floorclip'),
                      'ceilclip': words_low(ce, 'ceilingclip')})
    out['cliplog'] = calls if 'drawvis' in frame.calls else None
    return out


def batch_bytes(snap: 'Snapshot') -> bytes:
    """The masked phase's records not yet staged: the record batch in W
    (BATCH, MRB bytes), at a snapshot inside the phase."""
    return snap.main(R.BATCH, snap.main(R.ZPD1['MRB'], 1)[0])


def masked_native(end: 'Snapshot', slots: Dict[Tuple[int, int], int],
                  pmap: List[Tuple[int, int, int, int]], cliplog: bool,
                  masked_ds: List[int], batch: bool = False
                  ) -> Dict[str, Any]:
    """The native masked phase's outputs at nm_masked's return, or (stage
    C) at the weapon's draw (nm_psp's entry, `batch`: the records of the
    batch buffer not yet staged count too)."""
    F = R.FRAME
    m = end.main
    stg_bank = m(F['STG_BANK'], 1)[0]
    stg_ptr = le(m(F['STG_PTR'], 2))
    records, seq = native_records_all(
        staged_bytes(end, stg_bank, stg_ptr) +
        (batch_bytes(end) if batch else b''), slots, pmap)
    out: Dict[str, Any] = {'records': records,
                           'flushes': m(F['UPFLUSH'], 1)[0]}
    out['spans'] = list(m(R.SPANS, 8 * 160))
    out['cv'] = list(m(R.CVFIRST, 320))
    lo, hi = m(L5.CVRECLO, 160), m(L5.CVRECHI, 160)
    cvrec = {}
    for c in range(160):
        if out['cv'][c] < out['cv'][160 + c]:
            n = lo[c] | hi[c] << 8
            if n >= len(seq):
                cvrec[c] = 'sequence number %d past the %d records' % (
                    n, len(seq))
                continue
            col, index = seq[n]
            cvrec[c] = index if col == c else 'record %d of column %d' % (
                index, col)
    out['cvrec'] = cvrec
    out['upofs'] = list(m(R.UPOFS, 160))
    out['xpnext'] = (XP_FIRST + m(F['XPUSED'], 1)[0]) & 0xFF
    out['fzpos'] = m(F['FZPOS'], 1)[0]
    out['rw_step'] = le(m(F['RW_STEP'], 4))
    out['floorclip'] = list(m(R.FLOORCLIP, 160))
    out['ceilclip'] = list(m(R.CEILCLIP, 160))
    out['masked'] = {i: native_openings(end, native_drawseg(end, i))
                     ['masked'] for i in masked_ds}
    if cliplog:
        n = m(R.ZPD['CL_N'], 1)[0]
        calls = []
        for k in range(n):
            r = end.aux(R.SEAM, R.SEAM_CLIPLOG + R.CLIPLOG_REC * k,
                        R.CLIPLOG_REC)
            calls.append({'vis': le(r[0:2]), 'floorclip': list(r[2:162]),
                          'ceilclip': list(r[162:322])})
        out['cliplog'] = calls
    out['status'] = m(F['STATUS'], 1)[0]
    out['rules'] = m(F['RULES'], 1)[0]
    return out


def diff_masked(ref: Dict[str, Any], nat: Dict[str, Any]) -> List[str]:
    """Every difference of stage B's outputs, described."""
    out = []
    if nat.get('status'):
        out.append('status %d' % nat['status'])
    ra, na = ref['records'], nat['records']
    if ra != na:
        cols = sorted(set(ra) | set(na))
        bad = [c for c in cols if ra.get(c) != na.get(c)]
        c = bad[0]
        x, y = ra.get(c, []), na.get(c, [])
        k = next(i for i in range(max(len(x), len(y)))
                 if i >= len(x) or i >= len(y) or x[i] != y[i])
        out.append('records: %d columns differ (first %d, record %d: native '
                   '%s, reference %s)' % (len(bad), c, k,
                                          y[k] if k < len(y) else None,
                                          x[k] if k < len(x) else None))
    for key in ('spans', 'cv', 'upofs', 'floorclip', 'ceilclip'):
        if key not in ref:
            continue
        a, b = ref[key], nat[key]
        if a != b:
            bad = [i for i in range(len(a)) if a[i] != b[i]]
            out.append('%s: %d differ (first %d: native %r, reference %r)'
                       % (key, len(bad), bad[0], b[bad[0]], a[bad[0]]))
    for key in ('xpnext', 'fzpos', 'rw_step', 'flushes'):
        if ref[key] != nat[key]:
            out.append('%s: native %r, reference %r' % (key, nat[key],
                                                        ref[key]))
    if 'cvrec' in ref and ref['cvrec'] != nat['cvrec']:
        bad = sorted(c for c in set(ref['cvrec']) | set(nat['cvrec'])
                     if ref['cvrec'].get(c) != nat['cvrec'].get(c))
        out.append('covering records: %d differ (column %d: native %s, '
                   'reference %s)' % (len(bad), bad[0],
                                      nat['cvrec'].get(bad[0]),
                                      ref['cvrec'].get(bad[0])))
    if ref['masked'] != nat['masked']:
        bad = [i for i in ref['masked'] if ref['masked'][i] !=
               nat['masked'].get(i)]
        out.append('the masked columns\' openings of drawsegs %s differ'
                   % bad[:4])
    if ref.get('cliplog') is not None and 'cliplog' in nat:
        rc, nc = ref['cliplog'], nat['cliplog']
        for k in range(max(len(rc), len(nc))):
            if k >= len(rc) or k >= len(nc):
                out.append('the clip log: %d native calls, %d in the call '
                           'log (the first without a partner: %d)'
                           % (len(nc), len(rc), k))
                break
            if rc[k] != nc[k]:
                keys = [x for x in rc[k] if rc[k][x] != nc[k][x]]
                detail = ''
                if keys and keys[0] != 'vis':
                    col = [i for i in range(160) if rc[k][keys[0]][i] !=
                           nc[k][keys[0]][i]]
                    detail = ' (column %d: native %d, reference %d)' % (
                        col[0], nc[k][keys[0]][col[0]],
                        rc[k][keys[0]][col[0]])
                out.append('the clip log, call %d (vissprite %s): %s '
                           'differ%s' % (k, rc[k]['vis'], keys, detail))
                break
    return out


# ===========================================================================
# Milestone 8, stage C (docs/RENDER-MASKED.md 2.4, 4.3, 5.3): the frame's
# end, against the reference at R_DrawLists (P4) with every early flush
# (P2, before and in the masked phase) before it, the weapon's clip pass
# against P1, and the replay's SHR against P5 (tools/native/frame8.py).
#
#   records     as stage B's, to R_DrawLists: the weapon's records too
#   cv, cvrec   the covered ranges and their records (no flush), spans
#   upofs, xpnext, flushes, fzpos, floorclip, ceilclip   as stage B's
#   weapon      FR_SKIP, W_WSK (not in P4's ranges: 0 after playerSkip in
#               a frame that skips, else P3s's), WPREV, WCLIP, FR_VIS in
#               the native 12 bytes, MM_WPOK
#   cliplog     every R_DrawVisSprite call but the clip pass's: a
#               vissprite's index, or 'weapon' (FR_VIS; the native log's
#               $FF00 + the psprite)
# ===========================================================================

def weapon_truth(d, sym: blink.Symbols, index: Dict[int, int]
                 ) -> Dict[str, Any]:
    """FR_VIS and MM_WPOK of a dump (P1, P4), FR_VIS native."""
    from native import framestate as FS
    return {'frvis': list(FS.native_vis(d.read(sym.address('FR_VIS'),
                                               FS.SIZEOF_VIS), index,
                                        sym.address('fullcolormap'))),
            'wpok': int(d.u(FS.MM_WPOK, 2) == 0x5AA5)}


def clip_truth(frame, sym: blink.Symbols, index: Dict[int, int]
               ) -> Dict[str, Any]:
    """The weapon's clip pass: floorclip, FR_VIS, MM_WPOK after it (P1)."""
    p1 = frame.dump('p1')
    out = weapon_truth(p1, sym, index)
    out['floorclip'] = words_low(p1.read(sym.address('floorclip'), 320),
                                 'floorclip')
    return out


def clip_native(snap: 'Snapshot') -> Dict[str, Any]:
    m = snap.main
    return {'frvis': list(m(R.FRVIS, R.FV_SIZE)),
            'wpok': m(R.FRAME['MM_WPOK'], 1)[0],
            'floorclip': list(m(R.FLOORCLIP, 160))}


def final_truth(frame, sym: blink.Symbols, index: Dict[int, int]
                ) -> Dict[str, Any]:
    """The reference's outputs at R_DrawLists (P4)."""
    a = sym.address
    p4 = frame.dump('p4')
    records: Dict[int, List[Tuple]] = {}
    flushes = 0
    names = ['p2-%d' % k for k in range(frame.meta.get('flushes', 0))] + \
        ['p2m-%d' % k for k in range(frame.meta.get('mflushes', 0))]
    for name in names:
        for c, recs in walk_lists_all(frame.dump(name), sym, name)[0].items():
            records.setdefault(c, []).extend(recs)
        flushes += 1
    lists, places = walk_lists_all(p4, sym, 'R_DrawLists')
    before = {c: len(v) for c, v in records.items()}
    for c, recs in lists.items():
        records.setdefault(c, []).extend(recs)
    out: Dict[str, Any] = {'records': records, 'flushes': flushes}
    sp = p4.read(MM_FS, 0xC00)
    out['spans'] = [sp[0x200 * t + 2 * c + k] for t in range(4)
                    for k in (0, 1) for c in range(160)]
    if not flushes:
        out['cv'] = [sp[0x800 + 2 * c + k] for k in (0, 1)
                     for c in range(160)]
        cvrec = {}
        for c in range(160):
            if sp[0x800 + 2 * c] < sp[0x800 + 2 * c + 1]:
                place = le(sp[0xA00 + 2 * c:0xA00 + 2 * c + 2])
                if place not in places[c]:
                    raise CanonError('column %d: CV_REC $%04X is no record '
                                     'of its list' % (c, place))
                cvrec[c] = places[c][place] + before.get(c, 0)
        out['cvrec'] = cvrec
    colw = p4.read(a('COLW'), 320)
    out['upofs'] = [colw[2 * c] for c in range(160)]
    out['xpnext'] = p4.u(a('XPNEXT'), 1)
    out['fzpos'] = p4.u(a('FZ_POS'), 2)
    out['floorclip'] = words_low(p4.read(a('floorclip'), 320), 'floorclip')
    out['ceilclip'] = words_low(p4.read(a('ceilingclip'), 320),
                                'ceilingclip')
    from native import framestate as FS
    out['fr_skip'] = p4.u(a('FR_SKIP'), 2)
    out['w_wsk'] = p4.u(MM_W_WSK, 2)       # (captured at P4: rendercap)
    out['wprev'] = list(FS.native_vis(p4.read(MM_WCLIP + 0x180,
                                              FS.SIZEOF_VIS), index,
                                      a('fullcolormap')))
    wc = p4.read(MM_WCLIP, 320)
    out['wclip'] = [wc[2 * c] for c in range(160)]
    out.update(weapon_truth(p4, sym, index))
    calls = []
    vbase = a('vissprites')
    for call in frame.calls.get('drawvis', []):
        mem = call['in']['mem']
        if le(bytes.fromhex(mem[1])):
            continue                    # VS_CLIP: the weapon's clip pass
        ptr = le(bytes.fromhex(mem[0])) & 0xFFFFFF
        if vbase <= ptr < vbase + SIZEOF_VIS_UP * 80:
            if (ptr - vbase) % SIZEOF_VIS_UP:
                raise CanonError('R_DrawVisSprite of $%06X: no vissprite'
                                 % ptr)
            vis: Any = (ptr - vbase) // SIZEOF_VIS_UP
        elif ptr == a('FR_VIS') & 0xFFFFFF:
            vis = 'weapon'
        else:
            raise CanonError('R_DrawVisSprite of $%06X' % ptr)
        calls.append({'vis': vis,
                      'floorclip': words_low(bytes.fromhex(mem[4]),
                                             'floorclip'),
                      'ceilclip': words_low(bytes.fromhex(mem[5]),
                                            'ceilingclip')})
    out['cliplog'] = calls if 'drawvis' in frame.calls else None
    return out


def final_native(end: 'Snapshot', slots: Dict[Tuple[int, int], int],
                 pmap: List[Tuple[int, int, int, int]], cliplog: bool
                 ) -> Dict[str, Any]:
    """The native frame's outputs at the masked phase's end (the weapon
    drawn, the last batch staged)."""
    out = masked_native(end, slots, pmap, cliplog, [])
    del out['masked'], out['rw_step']
    m = end.main
    F = R.FRAME
    out['fr_skip'] = le(m(F['FR_SKIP'], 2))
    out['w_wsk'] = m(F['W_WSK'], 1)[0]
    out['wprev'] = list(m(R.WPREV, R.WPREV_USED))
    out['wclip'] = list(m(R.WCLIP, 160))
    out['frvis'] = list(m(R.FRVIS, R.FV_SIZE))
    out['wpok'] = m(F['MM_WPOK'], 1)[0]
    if cliplog:
        for c in out['cliplog']:
            if c['vis'] >= 0xFF00:
                c['vis'] = 'weapon'
    return out


def diff_final(ref: Dict[str, Any], nat: Dict[str, Any]) -> List[str]:
    """Every difference at the frame's end, described."""
    out = diff_masked(dict(ref, masked={}, rw_step=None),
                      dict(nat, masked={}, rw_step=None))
    for key in ('fr_skip', 'w_wsk', 'wpok'):
        if ref[key] != nat[key]:
            out.append('%s: native %r, reference %r' % (key, nat[key],
                                                        ref[key]))
    for key in ('wprev', 'wclip', 'frvis'):
        if ref[key] != nat[key]:
            bad = [i for i in range(len(ref[key]))
                   if ref[key][i] != nat[key][i]]
            out.append('%s: %d differ (first %d: native %r, reference %r)'
                       % (key, len(bad), bad[0], nat[key][bad[0]],
                          ref[key][bad[0]]))
    return out
