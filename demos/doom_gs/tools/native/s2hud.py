#!/usr/bin/env python3
"""Part s2hud's checks (docs/SCREENS.md 1.5.2, 7.3; docs/m11-parts/
s2hud.md): the HUD's tic side (src/native/s2t_hu.s) and its drawer in
P2DW (src/native/s2_hu.s) against upstream on ref816.

The reference (`capture`): ref816 runs of RUNS (demo3, newgame, and part
s2cap's coverage/m11/menus.script and automap.script) with a call log
streamed through a pipe (part s2cap's `machine`, imported) and distilled
into build/native/m11/s2hud/cases/RUN.json.z:

  display      the frame: the screen's rows 0-9 and 160-167 at its entry
               and its return, the menu flag
  HU_Drawer    upstream's HUD drawer: the lines, message_on, the text
               cache (textValid, textLen, textY, textText,
               iigs_textShown), automapmode, the rows' palettes (scb), the
               back buffer's rows 0-9 and 160-169 and the marks, at the
               entry and the return; the nibble tables of the palettes 0,
               10 and 11 at the entry
  HU_Ticker    (jumps=1: G_Ticker reaches it by JMP) the counter,
  HU_Start     message_on, message_new, the line, player.message,
               showMessages, _g_message_dontfuckwithme, gamemap
  R_RenderPlayerView  (entry) viewtop, message_on, DD_PAUSED, automapmode
               (point PV)
  I_MessageStrip, textInvalidate, clearStrip, clearView, titleBand,
  AM_Clean     what the frame does to the HUD's rows and cache before
               HU_Drawer (the inputs of the native drawer's flags)

The native runs (a2vm, tools/native/s2run.py; the test image s2ht of
src/native/m11/s2hud.mk):

  tics     every HU_Ticker and HU_Start of a run in order, chained (the
           card's state carried by the native code; message_new set from
           the reference, the frame side's) and injected (each call from
           the reference's state at its entry), and synthetic calls whose
           truth is ref816 --call of HU_Ticker on part s2draw's base state
  frames   every HU_Drawer of a run in order, chained (the text cache and
           its records carried by the native code); the screen's rows
           after each frame (the frame's entry rows, the blacks the map
           publishes, then the bytes the native HUD published, from the
           write log) against display's return; the cache after each
           frame against HU_Drawer's return; the same frames with the
           cache off (every line drawn afresh) give the same screens;
           synthetic lines (every glyph, lower case, characters outside
           the font, the line's width at 319, 320, 321) against ref816
           --call of HU_Drawer

Usage:  python3 tools/native/s2hud.py --capture [--runs ...] [--jobs 2]
        python3 tools/native/s2hud.py --check [--runs ...]
        python3 tools/native/s2hud.py --all      (the checkpoint, the
                                                  timing, report.json)
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, s2layout as S, s2msgs as MS, \
    s2run as SR  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
OUT = M11 / 's2hud'
CASES = OUT / 'cases'
SOURCE = ROOT / 'src' / 'native'
RUNS = ('demo3', 'newgame', 'menus', 'automap')
JOBS = 2
FORMAT = 's2hud-cases 1'
CALL_TIMEOUT = 60.0
MIN_FREE = 20 * 10 ** 9

# upstream's places [R memmap.inc, i_viigs65.s, hu_stuff65.s]
SCREEN = 0xE12000
SHRBUF = 0x012000
NIBTAB = 0x0B8000
ROW = 160
STRIP_ROWS = 10
TITLE_Y = 160
TITLE_ROWS = 8                  # the font's '$', '@', 'Q' are 8 high
TEXT_H = 10
TEXTMAX = 40
MSG_PAL, AMAP_PAL = 10, 11
SET_PALS = (0, MSG_PAL, AMAP_PAL)
AM_ACTIVE, AM_OVERLAY = 1, 2
HU_MSGTIMEOUT = 140
# the line [R hu_stuff65.s:29-32]
TL_Y, TL_TEXT, TL_LEN, TL_SIZE = 0, 2, 37, 39
ROWS18 = tuple(range(STRIP_ROWS)) + tuple(range(TITLE_Y,
                                                TITLE_Y + TITLE_ROWS))


class HudError(Exception):
    pass


def sym(name: str) -> int:
    from native import s2cap as C
    return C.sym(name)


# ---------------------------------------------------------------------------
# The reference: the call log
# ---------------------------------------------------------------------------

class Places(NamedTuple):
    hu: Tuple[int, int]         # hu_stuff65.s's znear (address, size)
    cache: Tuple[Tuple[str, int, int], ...]     # (name, address, size)


def places() -> Places:
    from native import s2cap as C
    hu = C.fragments('hu_stuff65.s', ('znear',))
    if len(hu) != 1:
        raise HudError('hu_stuff65.s has %d znear fragments' % len(hu))
    cache = (('textValid', 4), ('textLen', 4), ('textY', 4),
             ('textText', 2 * TEXTMAX), ('iigs_textShown', 4))
    return Places(hu[0], tuple((n, sym('i_viigs65.s:' + n), z)
                               for n, z in cache))


def hu_offset(name: str) -> int:
    """A label of hu_stuff65.s's znear: its offset in the fragment."""
    return sym('hu_stuff65.s:' + name) - places().hu[0]


def _r(address: int, size: int) -> str:
    return '%06X:%d' % (address, size)


# the HU_Drawer log's ranges, in order (mem: entry and return)
def drawer_ranges() -> List[Tuple[str, int, int]]:
    p = places()
    out = [('hu', p.hu[0], p.hu[1])]
    out += list(p.cache)
    out += [('automapmode', sym('am_map65.s:automapmode'), 2),
            ('scb', sym('i_viigs65.s:scb'), 200),
            ('buf0', SHRBUF, STRIP_ROWS * ROW),
            ('buf160', SHRBUF + TITLE_Y * ROW, TEXT_H * ROW),
            ('drb', sym('i_viigs65.s:DRB'), 200),
            ('dre', sym('i_viigs65.s:DRE'), 200),
            ('dry', sym('i_viigs65.s:DRY0'), 4)]
    return out


def nib_ranges() -> List[Tuple[str, int, int]]:
    return [('nib%d' % p, NIBTAB + p * 0x400, 0x400) for p in SET_PALS]


def ticker_ranges() -> List[Tuple[str, int, int]]:
    from native import s2state as SS
    p = places()
    pl = sym('g_game65.s:_g_player') + SS.offsets()['OFS_PL_MESSAGE']
    return [('hu', p.hu[0], p.hu[1]), ('msg', pl, 4),
            ('show', sym('m_menu65.s:showMessages'), 2),
            ('keep', sym('hu_stuff65.s:_g_message_dontfuckwithme'), 2),
            ('gamemap', sym('g_game65.s:_g_gamemap'), 2)]


def display_ranges() -> List[Tuple[str, int, int]]:
    return [('scr0', SCREEN, STRIP_ROWS * ROW),
            ('scr160', SCREEN + TITLE_Y * ROW, TITLE_ROWS * ROW),
            ('menu', sym('m_menu65.s:_g_menuactive'), 2),
            ('scr168', SCREEN + (TITLE_Y + TITLE_ROWS) * ROW,
             (TEXT_H - TITLE_ROWS) * ROW)]


def pv_ranges() -> List[Tuple[str, int, int]]:
    return [('viewtop', sym('r_state65.s:viewtop'), 2),
            ('message_on', sym('hu_stuff65.s:message_on'), 2),
            ('paused', sym('d_main65.s:DD_PAUSED'), 2),
            ('automapmode', sym('am_map65.s:automapmode'), 2)]


def _spec(ranges: Sequence[Tuple[str, int, int]]) -> str:
    return '+'.join(_r(a, z) for _, a, z in ranges)


def routines() -> List[Tuple[str, str, Tuple]]:
    """(name, the call log's routine, (mem ranges, in-only ranges))."""
    dr, nb = drawer_ranges(), nib_ranges()
    tr, ds, pv = ticker_ranges(), display_ranges(), pv_ranges()
    strippal = [('strippal', sym('i_viigs65.s:strippal'), 2)]
    band = [('am_band', sym('am_map65.s:am_band'), 2)]
    out = [
        ('display', 'd_main65.s:display,mem=%s' % _spec(ds), (ds, ())),
        ('HU_Drawer', 'hu_stuff65.s:HU_Drawer,mem=%s,in=%s' % (
            _spec(dr), _spec(nb)), (dr, nb)),
        ('HU_Ticker', 'hu_stuff65.s:HU_Ticker,jumps=1,mem=%s' % _spec(tr),
         (tr, ())),
        ('HU_Start', 'hu_stuff65.s:HU_Start,mem=%s' % _spec(tr), (tr, ())),
        ('PV', 'r_frame65.s:R_RenderPlayerView,entry=1,in=%s' % _spec(pv),
         ((), pv)),
        ('I_MessageStrip', 'i_viigs65.s:I_MessageStrip,entry=1,in=%s' %
         _spec(strippal), ((), strippal)),
        ('textInvalidate', 'i_viigs65.s:textInvalidate,entry=1', ((), ())),
        ('clearStrip', 'am_map65.s:clearStrip,entry=1', ((), ())),
        ('clearView', 'am_map65.s:clearView,entry=1', ((), ())),
        ('titleBand', 'am_map65.s:titleBand,entry=1,in=%s' % _spec(band),
         ((), band)),
        ('AM_Clean', 'am_map65.s:AM_Clean,entry=1', ((), ())),
    ]
    return [(n, t + ',name=' + n, spec) for n, t, spec in out]


def split(blobs: Sequence[bytes], ranges) -> Dict[str, bytes]:
    return {name: blob for (name, _, _), blob in zip(ranges, blobs)}


def distill(lines, table) -> List[Dict[str, Any]]:
    """The call log's lines (JSON) to the calls, in the order of their
    entries: name, cycles, regs, and each range by name ('in', 'out')."""
    head = json.loads(lines.readline())
    names = [r['name'] for r in head['routines']]
    out = []
    for raw in iter(lines.readline, b''):
        line = json.loads(raw)
        if line.get('end'):
            break
        name = names[line['routine']]
        mem_r, in_r = table[name]
        ins = [bytes.fromhex(m) for m in line['in']['mem']]
        o = line['out']
        outs = [bytes.fromhex(m) for m in o['mem']] if o else []
        rec: Dict[str, Any] = {
            'name': name, 'call': line['call'], 'cycles': line['cycles'],
            'a': line['in']['a'], 'x': line['in']['x'],
            'in': {k: v.hex() for k, v in split(ins, list(mem_r) +
                                                list(in_r)).items()},
            'out': {k: v.hex() for k, v in split(outs, mem_r).items()}}
        out.append(rec)
    out.sort(key=lambda r: r['call'])
    return out


def capture(run: str, rs: Optional[List] = None) -> Dict[str, Any]:
    """One ref816 run with the call log: build/native/m11/s2hud/cases/
    RUN.json.z. (rs: routines(), made before any thread starts: the
    symbol caches it fills are not thread safe.)"""
    from native import s2cap as C
    CASES.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tmp-s2hud-%s-' % run,
                                 dir=str(OUT)))
    try:
        rs = rs if rs is not None else routines()
        table = {n: spec for n, _, spec in rs}
        box: List[List[Dict[str, Any]]] = []

        def reader(handle):
            box.append(distill(handle, table))
        res = C.machine(run, work, [], [(n, t) for n, t, _ in rs], None,
                        reader)
        if res['problems']:
            raise HudError('%s: %s' % (run, res['problems'][:3]))
        if not box:
            raise HudError('%s: no call log' % run)
        data = {'format': FORMAT, 'run': run, 'calls': box[0],
                'traffic': res['traffic']}
        blob = zlib.compress(json.dumps(data).encode(), 6)
        path = CASES / (run + '.json.z')
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_bytes(blob)
        tmp.replace(path)
        return {'run': run, 'calls': len(box[0]), 'traffic': res['traffic'],
                'bytes': len(blob)}
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def load(run: str) -> List[Dict[str, Any]]:
    path = CASES / (run + '.json.z')
    if not path.exists():
        raise HudError('%s is missing: python3 tools/native/s2hud.py '
                       '--capture' % path)
    data = json.loads(zlib.decompress(path.read_bytes()))
    if data.get('format') != FORMAT:
        raise HudError('%s: not %s' % (path, FORMAT))
    for c in data['calls']:
        c['in'] = {k: bytes.fromhex(v) for k, v in c['in'].items()}
        c['out'] = {k: bytes.fromhex(v) for k, v in c['out'].items()}
    return data['calls']




def free_disk() -> int:
    st = os.statvfs(str(BUILD))
    return st.f_bavail * st.f_frsize


def w16(b: bytes, k: int = 0) -> int:
    return b[k] | b[k + 1] << 8


# ---------------------------------------------------------------------------
# The texts: ids and their texts (tools/native/s2msgs.py)
# ---------------------------------------------------------------------------

class Texts:
    def __init__(self, test: bool = False):
        es = MS.entries(test)
        self.by_id = {e.id: e.text for e in es}
        self.msg_by_text: Dict[bytes, int] = {}
        for e in es:
            if e.id < MS.TEST_ID:
                self.msg_by_text.setdefault(e.text, e.id)
        self.map_by_text = {e.text: e.id - MS.TITLE_ID for e in es
                            if MS.TITLE_ID < e.id <= MS.TITLE_ID + MS.NMAPS}
        self.addr = MS.by_address()
        self.ids = MS.symbol_ids()

    def id_of_ptr(self, ptr: int) -> Optional[int]:
        ref = self.addr.get(ptr)
        return self.ids.get(ref) if ref else None

    def text(self, ident: int) -> bytes:
        return self.by_id.get(ident, b'')


def line_of(hu: bytes, label: str) -> Tuple[int, bytes, int, bytes]:
    """A line of hu_stuff65.s's znear: its y, its text (len bytes), its
    length, its 39 bytes."""
    k = hu_offset(label)
    raw = hu[k:k + TL_SIZE]
    n = w16(raw, TL_LEN)
    return w16(raw, TL_Y), raw[TL_TEXT:TL_TEXT + min(n, TL_LEN - TL_TEXT)], \
        n, raw


# ---------------------------------------------------------------------------
# The tics
# ---------------------------------------------------------------------------

class Tic(NamedTuple):
    call: int
    kind: int                   # 0 HU_Ticker, 1 HU_Start
    tag: int
    ident: int
    show: int
    keep: int
    gamemap: int
    counter: int                # the state at the entry
    on: int
    new: int
    msgid: int
    want: Dict[str, Any]        # the reference's after


def tic_cases(calls, tx: Texts) -> Tuple[List[Tic], List[str]]:
    out, problems = [], []
    o_cnt, o_on, o_new = (hu_offset(n) for n in (
        'message_counter', 'message_on', 'message_new'))
    for c in calls:
        if c['name'] not in ('HU_Ticker', 'HU_Start'):
            continue
        i, o = c['in'], c['out']
        ptr = w16(i['msg']) | i['msg'][2] << 16 | i['msg'][3] << 24
        ident = 0
        if ptr:
            got = tx.id_of_ptr(ptr)
            if got is None or tx.text(got) == b'':
                problems.append('call %d: player.message $%06X is not a '
                                'message of the table' % (c['call'], ptr))
                continue
            ident = got
        _, text, n, _ = line_of(i['hu'], 'w_message')
        msgid = tx.msg_by_text.get(bytes(text), MS.NONE_ID) if n else \
            MS.NONE_ID
        if n and msgid == MS.NONE_ID:
            problems.append('call %d: the line %r is not in the table' % (
                c['call'], bytes(text)))
        _, otext, on_, _ = line_of(o['hu'], 'w_message')
        _, ttext, _, _ = line_of(o['hu'], 'w_title')
        want = {'counter': w16(o['hu'], o_cnt), 'on': w16(o['hu'], o_on),
                'new': w16(o['hu'], o_new), 'text': bytes(otext),
                'msg': w16(o['msg']) | w16(o['msg'], 2) << 16,
                'keep': w16(o['keep']), 'title': bytes(ttext)}
        out.append(Tic(c['call'], 0 if c['name'] == 'HU_Ticker' else 1,
                       1 if ptr else 0, ident, w16(i['show']),
                       w16(i['keep']), w16(i['gamemap']),
                       w16(i['hu'], o_cnt), w16(i['hu'], o_on),
                       w16(i['hu'], o_new), msgid, want))
    return out, problems


TIC_SIZE = 16
TICS_A_BANK = 2975


def tic_banks(tics: Sequence[Tic], first: int, mode: str
              ) -> List[Tuple[int, int, int, bytes]]:
    """The records of hut_tics: mode 'chained' (HU_NEW from the record),
    'injected' (the whole state from it)."""
    banks: List[bytearray] = []
    for k, t in enumerate(tics):
        b, j = divmod(k, TICS_A_BANK)
        if j == 0:
            banks.append(bytearray(0xC000 - 0x0200))
        rec = bytearray(TIC_SIZE)
        rec[0] = t.kind
        rec[1] = 1 if mode == 'injected' else 2
        rec[2] = t.tag
        rec[3:5] = t.ident.to_bytes(2, 'little')
        if t.kind == 0:
            rec[5:7] = t.show.to_bytes(2, 'little')
        else:
            rec[5:7] = t.gamemap.to_bytes(2, 'little')
        rec[7:9] = t.keep.to_bytes(2, 'little')
        rec[9:11] = t.counter.to_bytes(2, 'little')
        rec[11] = t.on & 0xFF
        rec[12] = t.new & 0xFF
        rec[13:15] = t.msgid.to_bytes(2, 'little')
        at = 0x10 + j * TIC_SIZE
        banks[b][at:at + TIC_SIZE] = rec
    if not banks:
        banks.append(bytearray(0xC000 - 0x0200))
    banks[0][0:2] = len(tics).to_bytes(2, 'little')
    return [(1, first + k, 0x0200, bytes(d)) for k, d in enumerate(banks)]


def tic_compare(t: Tic, got: bytes, tx: Texts, name: str) -> List[str]:
    """The native's state after a call (hut_tics' output) against the
    reference's."""
    out = []
    on, new, cnt = got[0], got[1], w16(got, 2)
    msgid, tmap, tag, keep = w16(got, 4), got[6], got[7], w16(got, 8)
    w = t.want
    for field, a, b in (('message_on', on, w['on']),
                        ('message_new', new, w['new']),
                        ('message_counter', cnt, w['counter']),
                        ('the line', tx.text(msgid), w['text']),
                        ('player.message set', tag != 0, w['msg'] != 0),
                        ('G_MSGKEEP', keep, w['keep'])):
        if a != b:
            out.append('%s: %s %r, ref %r' % (name, field, a, b))
    if t.kind == 1 and tx.text(MS.TITLE_ID + tmap) != w['title']:
        out.append('%s: the title %r, ref %r' % (
            name, tx.text(MS.TITLE_ID + tmap), w['title']))
    return out


# ---------------------------------------------------------------------------
# The frames
# ---------------------------------------------------------------------------

class Frame(NamedTuple):
    name: str
    flags: int
    on: int
    msgid: int
    titlemap: int
    automap: int
    txtinv: int
    scb: bytes                  # the 18 rows' palettes
    nib: Tuple[bytes, ...]      # the tables of palettes 0, 10, 11
    before: bytes               # the screen's 18 rows at display's entry
    after: bytes                # and at its return (None: synthetic)
    blacks: Tuple[str, ...]     # the map's blacks: 'strip', 'title'
    strip: bool                 # the region: rows 0-9
    title: bool                 # rows 160-167
    excluded: Optional[str]
    hin: Dict[str, bytes]       # HU_Drawer's entry and return
    hout: Dict[str, bytes]
    state: Optional[bytes]      # P2DW's own block to inject (256 B)
    after168: Optional[bytes] = None    # rows 168-169 at display's return


def rows18(r0: bytes, r160: bytes) -> bytes:
    return bytes(r0[:STRIP_ROWS * ROW]) + bytes(r160[:TITLE_ROWS * ROW])


def state_block(hin: Dict[str, bytes], tx: Texts, fill: int,
                msgfill: int, mapfill: int) -> bytes:
    """P2DW's own block ($BF00-$BFFF) with the HUD's fields from
    HU_Drawer's entry (upstream's layout) and the fills' ids."""
    sp = S.state_places('P2DW')
    blk = bytearray([fill]) * 256

    def put(addr: int, data: bytes) -> None:
        blk[addr - 0xBF00:addr - 0xBF00 + len(data)] = data
    hu = hin['hu']
    put(sp['P_TITLE'], line_of(hu, 'w_title')[3])
    put(sp['P_MESSAGE'], line_of(hu, 'w_message')[3])
    put(sp['P_TXTVALID'], hin['textValid'])
    put(sp['P_TXTLEN'], hin['textLen'])
    put(sp['P_TXTY'], hin['textY'])
    put(sp['P_TXTSHOWN'], hin['iigs_textShown'])
    put(sp['P_TXTTEXT'], hin['textText'])
    put(sp['P_MSGFILL'], msgfill.to_bytes(2, 'little'))
    put(sp['P_MAPFILL'], bytes([mapfill]))
    return bytes(blk)


def frame_cases(calls, tx: Texts, fill: int = 0xA5
                ) -> Tuple[List[Frame], List[str]]:
    """Each HU_Drawer of a run, with what its frame did before it."""
    out, problems = [], []
    o_on = hu_offset('message_on')
    disp = None
    events: List[Dict[str, Any]] = []
    inval = True                # (the run starts with the cache empty)
    first = True
    for c in calls:
        n = c['name']
        if n == 'display':
            disp, events = c, []
            continue
        if n == 'textInvalidate':
            inval = True
            continue
        if n != 'HU_Drawer':
            events.append(c)
            continue
        i, o = c['in'], c['out']
        if disp is None or not disp['out']:
            problems.append('call %d: HU_Drawer outside a display' %
                            c['call'])
            continue
        on = w16(i['hu'], o_on)
        am = i['automapmode'][0]
        flags, blacks = 0, []
        for e in events:
            en = e['name']
            if en == 'I_MessageStrip' and e['a'] and (
                    w16(e['in']['strippal']) != MSG_PAL or e['x']):
                flags |= 1
            elif en == 'PV':
                if w16(e['in']['viewtop']) & 0x8000:
                    flags |= 2
                if w16(e['in']['automapmode']) & 3 != 3:
                    flags |= 4
            elif en == 'clearStrip':
                flags |= 2
                blacks.append('strip')
            elif en == 'clearView':
                flags |= 6
                blacks += ['strip', 'title']
            elif en == 'titleBand' and w16(e['in']['am_band']) == 0:
                flags |= 4
                blacks.append('title')
            elif en == 'AM_Clean':
                flags |= 4
        _, mtext, mlen, _ = line_of(i['hu'], 'w_message')
        _, ttext, tlen, _ = line_of(i['hu'], 'w_title')
        msgid = tx.msg_by_text.get(bytes(mtext), MS.NONE_ID) if mlen \
            else MS.NONE_ID
        if on and mlen and msgid == MS.NONE_ID:
            problems.append('call %d: the message %r is not in the table' %
                            (c['call'], bytes(mtext)))
        tmap = tx.map_by_text.get(bytes(ttext), 0)
        if am & AM_ACTIVE and not tmap:
            problems.append('call %d: the title %r is not in the table' %
                            (c['call'], bytes(ttext)))
        txtinv = 1 if inval else 0
        inval = False
        state = None
        if first:
            state = state_block(i, tx, fill, MS.NONE_ID - 1, 0xFF)
            if any(i['textValid']):         # (no record of it natively)
                txtinv = 1
            first = False
        dm = w16(disp['in']['menu']) or w16(disp['out']['menu'])
        scb = bytes(i['scb'][r] for r in ROWS18)
        bad = sorted(set(scb) - set(SET_PALS))
        if bad:
            problems.append('call %d: rows in palettes %s (the test has '
                            '0, 10, 11)' % (c['call'], bad))
        out.append(Frame(
            'call %d' % c['call'], flags, 1 if on else 0, msgid, tmap, am,
            txtinv, scb, tuple(i['nib%d' % p] for p in SET_PALS),
            rows18(disp['in']['scr0'], disp['in']['scr160']),
            rows18(disp['out']['scr0'], disp['out']['scr160']),
            tuple(blacks), bool(on or flags & 1), bool(am & AM_ACTIVE),
            'the menu over the screen (s2menu1\'s region)' if dm else None,
            i, o, state, disp['out'].get('scr168')))
    return out, problems


FRAME_REC = 0x140
FRAMES_A_BANK = 150


def frame_banks(frames: Sequence[Frame], first: int, sets: Dict[bytes, int],
                fresh: bool = False) -> List[Tuple[int, int, int, bytes]]:
    banks: List[bytearray] = []
    for k, f in enumerate(frames):
        b, j = divmod(k, FRAMES_A_BANK)
        if j == 0:
            banks.append(bytearray(0xC000 - 0x0200))
        key = b''.join(f.nib)
        if key not in sets:
            sets[key] = len(sets)
        rec = bytearray(FRAME_REC)
        rec[0] = f.flags
        rec[1] = f.on
        rec[2:4] = f.msgid.to_bytes(2, 'little')
        rec[4] = f.titlemap & 0xFF
        rec[5] = f.automap
        rec[6] = 1 if fresh else f.txtinv
        rec[7] = sets[key]
        if f.state is not None:
            rec[8] = 1
            rec[0x40:0x140] = f.state
        rec[16:34] = f.scb
        at = 0x100 + j * FRAME_REC
        banks[b][at:at + FRAME_REC] = rec
    if not banks:
        banks.append(bytearray(0xC000 - 0x0200))
    banks[0][0:2] = len(frames).to_bytes(2, 'little')
    return [(1, first + k, 0x0200, bytes(d)) for k, d in enumerate(banks)]


def set_bank(sets: Dict[bytes, int], bank: int
             ) -> Tuple[int, int, int, bytes]:
    if len(sets) > 15:
        raise HudError('%d sets of nibble tables (the bank holds 15)' %
                       len(sets))
    data = bytearray(0xC000 - 0x0200)
    for key, k in sets.items():
        data[k * 0xC00:k * 0xC00 + len(key)] = key
    return (1, bank, 0x0200, bytes(data))


# ---------------------------------------------------------------------------
# The native runs
# ---------------------------------------------------------------------------

FRAME_IN, FRESH_IN = 10, 40     # the frames' (up to 20 each)
SYN_IN = 70
FRESH_CHUNK = 200
NIB_BANK = 90
SHARED_GEN = M11 / 'shared' / 'gen'
KEEP_GEN = ('s2.inc', 's2-release.inc', 's2-m11.inc', 's2-fxch8.inc',
            'rlayout.inc')


def make(obj: Path = OUT, source: Path = SOURCE, m11: Path = M11) -> str:
    """make -f m11.mk part P=s2hud. Returns a note (empty: the shared
    includes are made by s2layout.py, whose check must pass; the wave 4
    integration settled S2HUD-4)."""
    cmd = ['make', '-s', '-C', str(source), '-f', 'm11.mk', 'part',
           'P=s2hud', 'M11=%s' % m11, 'ROOT=%s' % ROOT]
    from ref816 import bounded
    r = bounded.run(cmd, timeout=300, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, universal_newlines=True)
    note = ''
    if r.returncode:
        raise HudError('the build failed:\n' + r.stdout[-3000:])
    if 'arning' in r.stdout:
        raise HudError('the build warns:\n' + r.stdout[-3000:])
    return note


def store_records(obj: Path = OUT) -> List[Tuple[int, int, int, bytes]]:
    """The 2D store (part s2data's GFX.n: the font's patches) and the
    HUD's texts (HUDTXT-test.1: the release's table and the test's
    lines)."""
    from native import lstore
    out = []
    path = obj / 'HUDTXT-test.1'
    if not path.exists():
        raise HudError('%s is missing: make -f m11.mk part P=s2hud' % path)
    for bank, address, data in lstore.read_bank_file(path.read_bytes()):
        out.append((1, bank, address, bytes(data)))
    files = sorted((M11 / 's2data').glob('GFX.*'))
    if not files:
        raise HudError('no GFX.n in %s: make -f m11.mk part P=s2data' %
                       (M11 / 's2data'))
    for p in files:
        for bank, address, data in lstore.read_bank_file(p.read_bytes()):
            out.append((1, bank, address, bytes(data)))
    return out


def module_pcs(b) -> Dict[str, Tuple[int, int]]:
    from native import s2drawcase as DC
    return DC.module_pcs(b)


def segment_of(b, seg: str, module: str) -> Optional[Tuple[int, int]]:
    """A module's part of a segment (inclusive), from the map."""
    text = (b.obj / (b.name + '.map')).read_text()
    start = b.segments[seg][0]
    part = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    mod = None
    for line in part.splitlines():
        if line and not line.startswith(' ') and line.rstrip().endswith(':'):
            mod = Path(line.strip()[:-1].split('(')[0]).stem
            continue
        f = line.split()
        if mod == module and f and f[0] == seg:
            offs, size = int(f[1][5:], 16), int(f[2][5:], 16)
            return start + offs, start + offs + size - 1
    return None


def owners(b, loads) -> List[Any]:
    """The writers of a run of s2ht and what each may write."""
    pcs = module_pcs(b)
    lab = b.labels
    hu = 's2_hu'
    marks, begun = lab['s2_marks'], lab['s2_begun']
    data = b.segments['S2DATA']
    zp = ('main', 0, 0x48, 0x80)
    fa = ('main', 0, 0x0000, 0x0006)
    card = ('lc', 0, S.BUILDS['test'].s2t_base,
            S.BUILDS['test'].s2t_base + S.S2T_SIZE)
    io_window = frozenset({0xC002, 0xC003, 0xC004, 0xC005, 0xC073})
    huc = segment_of(b, 'S2CODE', hu)
    strip = ('aux', 0, 0x2000, 0x2000 + STRIP_ROWS * ROW)
    title = ('aux', 0, 0x2000 + TITLE_Y * ROW,
             0x2000 + (TITLE_Y + TITLE_ROWS) * ROW)
    return [
        SR.driver_owner(b), SR.loader_owner(b, loads),
        SR.Owner('the far layer', (b.segments['RFAR'],),
                 (fa, ('main', 0, 0x8300, 0xC000),
                  ('main', 0, data[0], data[1] + 1),
                  ('aux', 0, 0x2000, 0x2000),
                  ('aux', S.S2STATE, S.SS['SS_HUDTXT'],
                   S.SS['SS_HUDTXT'] + S.SS_SIZE['SS_HUDTXT']),
                  ('aux', S.S2PAL, S.S2PAL_AT['S2P_NIB'],
                   S.S2PAL_AT['S2P_NIB'] + S.S2PAL_SIZE['S2P_NIB'])) +
                 tuple(('aux', k, 0x0200, 0xC000)
                       for _, k in TIC_CALLS), io_window),
        SR.Owner('the test glue', (pcs['s2_hut'],),
                 (fa, card, ('main', 0, data[0], data[1] + 1),
                              ('main', 0, 0x0300, 0x0301),
                              ('main', 0, 0x1C80, 0x1FFF),
                              ('main', 0, 0x0310, 0x0370),
                              ('main', 0, S.PALST_W, S.PALST_W + 0x300)),
                 frozenset()),
        SR.Owner('s2t_hu', (pcs['s2t_hu'],), (card,), frozenset()),
        SR.Owner('s2_hu', (pcs[hu],),
                 (zp, fa, ('main', 0, 0x8300, 0x9700),
                  ('main', 0, marks, marks + 0x100),
                  ('main', 0, 0xBF00, 0xC000),
                  ('main', 0, S.PALST_W + S.palst_places()['PS_TXTINV'],
                   S.PALST_W + S.palst_places()['PS_TXTINV'] + 1),
                  ('main', 0, data[0], data[1] + 1),
                  ('main', 0, huc[0], huc[1] + 1)), frozenset()),
        SR.Owner('s2_draw', (pcs['s2_draw'],),
                 (zp, fa, ('main', 0, 0x8300, 0x9700),
                  ('main', 0, marks, marks + 0x100),
                  ('main', 0, pcs['s2_draw'][0], pcs['s2_draw'][1] + 1)),
                 frozenset()),
        SR.Owner('s2_pub', (pcs['s2_pub'],),
                 (zp, strip, title, ('main', 0, marks + 0x40, marks + 0x80),
                  ('main', 0, begun, begun + 1)),
                 frozenset({0xC004, 0xC005})),
        # part s2pal's s2_pal (s2_begin; until the final integration the
        # stand-in s2_beginstub.s): the glue sets s2_begun, so it never
        # runs here and may write nothing
        SR.Owner('s2_pal (s2_begin, never run)', (pcs['s2_pal'],),
                 (), frozenset()),
    ]


class Span(NamedTuple):
    start: int                  # the clocks
    end: int
    published: Dict[int, int]   # aux 0 offset -> value (s2_pub's)
    state: bytes                # $BF00-$BFFF after
    records: int                # lines drawn afresh (textValid set)


def spans(b, writes, routine: str) -> List[Span]:
    """Each call of hu_drawer (or hu_ticker/hu_start) in the write log:
    the glue's PHASE 30 window; what s2_pub published in it; P2DW's own
    block after it."""
    pcs = module_pcs(b)
    glue = pcs['s2_hut']
    pub = pcs['s2_pub']
    valid = S.state_places('P2DW')['P_TXTVALID']
    shadow = bytearray(256)
    out: List[Span] = []
    cur: Optional[Dict[str, Any]] = None
    for w in writes:
        if w.storage == 'main' and 0xBF00 <= w.offset < 0xC000:
            shadow[w.offset - 0xBF00] = w.new
        if w.storage == 'main' and w.offset == 0x0300 and \
                glue[0] <= w.pc <= glue[1]:
            if w.new == 2 * S.PHASE_2D:
                cur = {'start': w.clock, 'pub': {}, 'rec': 0}
            elif w.new == 0 and cur is not None:
                out.append(Span(cur['start'], w.clock, cur['pub'],
                                bytes(shadow), cur['rec']))
                cur = None
            continue
        if cur is None:
            continue
        if w.storage == 'aux' and w.bank == 0 and pub[0] <= w.pc <= pub[1]:
            cur['pub'][w.offset] = w.new
        elif w.storage == 'main' and valid <= w.offset < valid + 4 and \
                w.new:
            cur['rec'] += 1     # (a line drawn afresh: I_EndTextCapture)
    del routine
    return out


# The write log of these runs: every CPU write but the stack page's, the
# far layer's arguments FA_* ($00-$05) and the 2D images' zero page
# $48-$7F (S2_*, S2P_*: the drawers' temporaries), the image's code (its
# loops patch their own operands), the HUD's own W runtime ranges (the
# band and its records, the marks, the nibble slots, the fetch buffer:
# $8300-$BBFF) and the bulk copies into S2STATE (104: the records) and
# S2PAL (106: the test's nibble tables), which a run of a few hundred
# frames drawn afresh would make too large
WRITE_LOG_LIMIT = 1_000_000


def write_log_ranges(b) -> str:
    lo, hi = b.segments['S2DATA']
    return ('main:0006-0047,main:0080-00FF,main:0200-65FF,main:%04X-%04X,'
            'main:BC00-FFFF,lc,lc1,aux0-103,aux105,aux107-127,'
            'cpu:C000-C0FF' % (lo, hi))


def run_native(b, calls, recs, work: Path, profile: Optional[str]):
    r = SR.run(b, calls, 0xA5, work, extra_records=recs, write_log=False,
               profile=profile, timeout=600.0, extra_args=[
                   '--write-log', write_log_ranges(b), '--write-log-file',
                   str(work / 'writes.log'), '--write-log-limit',
                   str(WRITE_LOG_LIMIT)])
    if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
        raise HudError('the run ended %s, status %s' % (r.ended(),
                                                        r.status()))
    return r


def fstate(blk: bytes) -> Dict[str, Any]:
    sp = S.state_places('P2DW')

    def g(name, n):
        a = sp[name] - 0xBF00
        return blk[a:a + n]
    return {'valid': g('P_TXTVALID', 4), 'len': g('P_TXTLEN', 4),
            'y': g('P_TXTY', 4), 'shown': g('P_TXTSHOWN', 4),
            'text': g('P_TXTTEXT', 80), 'title': g('P_TITLE', TL_SIZE),
            'message': g('P_MESSAGE', TL_SIZE)}


def native_rows(base: bytes, blacks: Sequence[str],
                published: Dict[int, int]) -> Tuple[bytearray, List[int]]:
    """The 18 rows after a frame: the base, the map's blacks, the native
    HUD's published bytes; and the published offsets outside the 18
    rows."""
    rows = bytearray(base)
    if 'strip' in blacks:
        rows[0:STRIP_ROWS * ROW] = bytes(STRIP_ROWS * ROW)
    if 'title' in blacks:
        rows[STRIP_ROWS * ROW:] = bytes(TITLE_ROWS * ROW)
    stray = []
    for off, v in published.items():
        r, x = divmod(off - 0x2000, ROW)
        if 0 <= r < STRIP_ROWS:
            rows[r * ROW + x] = v
        elif TITLE_Y <= r < TITLE_Y + TITLE_ROWS:
            rows[(STRIP_ROWS + r - TITLE_Y) * ROW + x] = v
        else:
            stray.append(off)
    return rows, stray


def first_diff(a: bytes, b: bytes, lo: int, hi: int) -> Optional[str]:
    for k in range(lo, hi):
        if a[k] != b[k]:
            r = ROWS18[k // ROW]
            return 'row %d byte %d: $%02X, ref $%02X' % (r, k % ROW, a[k],
                                                        b[k])
    return None


def frame_problems(f: Frame, sp: Span, cache: bool = True,
                   base: Optional[bytes] = None) -> List[str]:
    out = []
    rows, stray = native_rows(f.before if base is None else base, f.blacks,
                              sp.published)
    if stray:
        out.append('%s: published outside rows 0-9, 160-167 ($%04X)' % (
            f.name, stray[0]))
    wrote = {(o - 0x2000) // ROW for o in sp.published}
    if not f.strip and wrote & set(range(STRIP_ROWS)):
        out.append('%s: rows 0-9 written with the strip off' % f.name)
    if not f.title and wrote & set(range(TITLE_Y, TITLE_Y + TITLE_ROWS)):
        out.append('%s: the title\'s rows written with the map off' %
                   f.name)
    if f.excluded is None and f.after is not None:
        if f.strip:
            d = first_diff(rows, f.after, 0, STRIP_ROWS * ROW)
            if d:
                out.append('%s: the strip %s' % (f.name, d))
        if f.title:
            d = first_diff(rows, f.after, STRIP_ROWS * ROW, len(rows))
            if d:
                out.append('%s: the title %s' % (f.name, d))
    if cache:
        st, o = fstate(sp.state), f.hout
        for key, ref in (('valid', 'textValid'), ('len', 'textLen'),
                         ('y', 'textY'), ('shown', 'iigs_textShown')):
            if bytes(st[key]) != bytes(o[ref]):
                out.append('%s: %s %s, ref %s' % (f.name, ref,
                                                  bytes(st[key]).hex(),
                                                  bytes(o[ref]).hex()))
        for slot in (0, 1):
            if w16(o['textValid'], 2 * slot):
                n = w16(o['textLen'], 2 * slot)
                a = bytes(st['text'][40 * slot:40 * slot + n])
                if a != bytes(o['textText'][40 * slot:40 * slot + n]):
                    out.append('%s: slot %d\'s text %r, ref %r' % (
                        f.name, slot, a, bytes(o['textText'][
                            40 * slot:40 * slot + n])))
        for label, key, cond in (('w_message', 'message', f.on),
                                 ('w_title', 'title', f.automap & 1)):
            if cond:
                _, text, n, _ = line_of(f.hin['hu'], label)
                got = bytes(st[key])
                gn = w16(got, TL_LEN)
                if gn != n or got[TL_TEXT:TL_TEXT + len(text)] != text:
                    out.append('%s: %s %r, ref %r' % (
                        f.name, label, got[TL_TEXT:TL_TEXT + gn],
                        bytes(text)))
    return out


def tic_outputs(writes, n: int, bank: int) -> List[bytes]:
    """hut_tics' outputs (16 bytes a call) from the write log."""
    mem = bytearray(n * 16)
    for w in writes:
        if w.storage == 'aux' and w.bank == bank and \
                0x0200 <= w.offset < 0x0200 + n * 16:
            mem[w.offset - 0x0200] = w.new
    return [bytes(mem[16 * k:16 * k + 16]) for k in range(n)]


TIC_CALLS = ((91, 92), (93, 94), (95, 96))      # chained, injected, synth
TIC_BANKS = range(91, 97)


# ---------------------------------------------------------------------------
# Synthetic cases: ref816 --call on part s2draw's base state
# ---------------------------------------------------------------------------

SYNTH = OUT / 'synth'


def base_path() -> Path:
    from native import s2drawcase as DC
    if not DC.BASE.exists():
        raise HudError('%s is missing: python3 tools/native/s2drawcase.py '
                       '(part s2draw\'s truth base)' % DC.BASE)
    return DC.BASE


def ref_call(routine: str, pokes: Sequence[Tuple[int, bytes]],
             saves: Sequence[Tuple[int, int]], work: Path) -> List[bytes]:
    from native import s2drawcase as DC
    path = work / 'pokes.img'
    DC.write_pokes(path, pokes)
    _, data = DC.call(base_path(), [path], sym(routine), {}, saves, work)
    return data


def cached_truth(name: str, inputs: Any, fn, jobs: int) -> List[Any]:
    """fn(input, work) for each input, cached under a hash of the inputs,
    the base state and this file."""
    key = hashlib.sha256(json.dumps(inputs).encode() + hashlib.sha256(
        base_path().read_bytes()).digest() + Path(__file__).read_bytes()
    ).hexdigest()[:16]
    cache = SYNTH / ('%s-%s.json' % (name, key))
    if cache.exists():
        return json.loads(cache.read_text())
    SYNTH.mkdir(parents=True, exist_ok=True)

    def one(inp):
        work = Path(tempfile.mkdtemp(prefix='tmp-s2hud-call-',
                                     dir=str(SYNTH)))
        try:
            return fn(inp, work)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    with ThreadPoolExecutor(max(1, min(jobs, JOBS))) as ex:
        out = list(ex.map(one, inputs))
    for old in SYNTH.glob('%s-*.json' % name):
        old.unlink()
    tmp = cache.with_name(cache.name + '.tmp')
    tmp.write_text(json.dumps(out))
    tmp.replace(cache)
    return out


def tic_inputs() -> List[List[int]]:
    """HU_Ticker's paths and edges: the counter (0, 1, 2, the timeout,
    the byte's edges), a message or none, showMessages and the keep."""
    out = []
    for cnt in (0, 1, 2, 139, 140, 255, 256, 257):
        for msg in (0, 1):
            for show, keep in ((0, 0), (1, 0), (0, 1), (1, 1)):
                out.append([cnt, msg, show, keep])
    return out


def tic_truth(jobs: int = JOBS) -> List[Dict[str, Any]]:
    from native import s2state as SS
    hu = places().hu
    o = {n: hu_offset(n) for n in ('message_counter', 'message_on',
                                   'message_new')}
    msgptr = sym('g_game65.s:_g_player') + SS.offsets()['OFS_PL_MESSAGE']
    show, keep = sym('m_menu65.s:showMessages'), \
        sym('hu_stuff65.s:_g_message_dontfuckwithme')
    clip = sym('p_inter65.s:msgClip')
    w = lambda v: v.to_bytes(2, 'little')  # noqa: E731

    def fn(inp, work):
        cnt, msg, sh, kp = inp
        ptr = (clip & 0xFFFF).to_bytes(2, 'little') + \
            bytes([clip >> 16, 0]) if msg else bytes(4)
        pokes = [(hu[0] + o['message_counter'], w(cnt)),
                 (hu[0] + o['message_on'], w(1)),
                 (hu[0] + o['message_new'], w(0)),
                 (msgptr, ptr), (show, w(sh)), (keep, w(kp))]
        data = ref_call('hu_stuff65.s:HU_Ticker', pokes,
                        [(hu[0], hu[1]), (msgptr, 4), (keep, 2)], work)
        return [d.hex() for d in data]
    return [{'input': i, 'out': [bytes.fromhex(x) for x in r]}
            for i, r in zip(tic_inputs(), cached_truth(
                'tic', tic_inputs(), fn, jobs))]


def tic_synth_cases(tx: Texts) -> List[Tic]:
    """The synthetic HU_Ticker calls as cases: the base state's line (its
    text's id) at the entry, the reference's state after."""
    from ref816 import refimage
    o_cnt, o_on, o_new = (hu_offset(n) for n in (
        'message_counter', 'message_on', 'message_new'))
    hu = places().hu
    base = refimage.load(refimage.read(base_path())).get(hu[0], hu[1])
    _, btext, bn, _ = line_of(base, 'w_message')
    base_id = tx.msg_by_text.get(bytes(btext), MS.NONE_ID) if bn else \
        MS.NONE_ID
    if bn and base_id == MS.NONE_ID:
        raise HudError('the base state\'s line %r is not in the table' %
                       bytes(btext))
    clip = tx.ids['p_inter65.s:msgClip']
    out = []
    for k, t in enumerate(tic_truth()):
        cnt, msg, sh, kp = t['input']
        huo, msgo, keepo = t['out']
        _, text, _, _ = line_of(huo, 'w_message')
        _, ttext, _, _ = line_of(huo, 'w_title')
        want = {'counter': w16(huo, o_cnt), 'on': w16(huo, o_on),
                'new': w16(huo, o_new), 'text': bytes(text),
                'msg': w16(msgo) | w16(msgo, 2) << 16, 'keep': w16(keepo),
                'title': bytes(ttext)}
        out.append(Tic(k, 0, msg, clip if msg else 0, sh, kp, 0, cnt, 1, 0,
                       base_id, want))
    return out


def line_end(text: bytes, widths: Dict[int, int]) -> Tuple[int, int]:
    """drawTextLine's walk [R hu_stuff65.s:150-207] over the bytes:
    (x at the end, the index where it ended)."""
    x = 0
    for k, c in enumerate(text):
        if 0x61 <= c <= 0x7A:
            c -= 0x20
        if MS.FONT_LO <= c <= MS.FONT_HI:
            if x + widths[c] > 320:
                return x, k
            x += widths[c]
        else:
            x += 4
            if x >= 320:
                return x, k
    return x, len(text)


def long_titles() -> List[bytes]:
    """Titles whose last glyph ('M', 9 wide) ends at x = 319 or 320
    (drawn) or would end at 321 (cut), and one whose spaces reach x = 320
    (the end) before a glyph: the line's end [R hu_stuff65.s:177-205].
    A title longer than 35 characters runs on into its own TL_LEN (the
    length's two bytes are characters: the length, then 0, a space) and
    into w_message, as upstream's loop reads them; natively the same
    bytes (P_TITLE, then P_MESSAGE)."""
    widths = {g.char: g.width for g in MS.font()}
    out = []
    for target in (319, 320, 321):
        found = None
        for n in range(37, 75):
            for small in (b'I', b'1', b'S'):
                for k in range(0, n):
                    text = bytearray(b'A' * (n - 1) + b'M')
                    text[:k] = small * k
                    text[35:37] = bytes([n, 0])
                    x, end = line_end(bytes(text), widths)
                    drawn = end == n and x == target
                    cut = end == n - 1 and x + widths[ord('M')] == target
                    if (target < 321 and drawn) or (target == 321 and cut):
                        found = bytes(text)
                        break
                if found:
                    break
            if found:
                break
        if found is None:
            raise HudError('no title ends at %d' % target)
        out.append(found)
    text = bytearray(b'M' * 32 + b'    ')       # spaces to x = 320
    text[35:37] = bytes([45, 0])
    text += b' ' * 6 + b'I'
    out.append(bytes(text))
    return out


def drawer_inputs() -> List[Tuple[str, str]]:
    """(slot, the text hex): the test table's lines as messages, the
    long titles as titles."""
    out = [('msg', t.hex()) for t in MS.test_texts()]
    out += [('title', t.hex()) for t in long_titles()]
    return out


def drawer_truth(jobs: int = JOBS) -> List[Dict[str, Any]]:
    p = places()
    hu = p.hu
    o_t, o_m, o_on = (hu_offset(n) for n in ('w_title', 'w_message',
                                             'message_on'))
    cache = {n: (a, z) for n, a, z in p.cache}
    am = sym('am_map65.s:automapmode')
    drb = sym('i_viigs65.s:DRB')
    dry = sym('i_viigs65.s:DRY0')
    w = lambda v: v.to_bytes(2, 'little')  # noqa: E731

    def fn(inp, work):
        slot, text = inp[0], bytes.fromhex(inp[1])
        lines = bytearray(2 * TL_SIZE)
        lines[TL_Y:TL_Y + 2] = w(TITLE_Y)
        lines[TL_SIZE + TL_Y:TL_SIZE + TL_Y + 2] = w(0)
        if slot == 'msg':
            lines[TL_SIZE + TL_TEXT:TL_SIZE + TL_TEXT + len(text)] = text
            lines[TL_SIZE + TL_LEN:TL_SIZE + TL_LEN + 2] = w(len(text))
        else:
            lines[TL_TEXT:TL_TEXT + len(text)] = text
            if len(text) < TL_LEN - TL_TEXT:
                lines[TL_LEN:TL_LEN + 2] = w(len(text))
        pokes = [(hu[0] + o_t, bytes(lines)),
                 (hu[0] + o_on, w(1 if slot == 'msg' else 0)),
                 (am, w(0 if slot == 'msg' else AM_ACTIVE)),
                 (cache['textValid'][0], bytes(4)),
                 (cache['textLen'][0], bytes(4)),
                 (cache['textY'][0], bytes(4)),
                 (cache['textText'][0], bytes(2 * TEXTMAX)),
                 (cache['iigs_textShown'][0], bytes(4)),
                 (SHRBUF, bytes(STRIP_ROWS * ROW)),
                 (SHRBUF + TITLE_Y * ROW, bytes(TEXT_H * ROW)),
                 (drb, bytes(400)), (dry, bytes(4))]
        saves = [(SHRBUF, STRIP_ROWS * ROW),
                 (SHRBUF + TITLE_Y * ROW, TEXT_H * ROW), (drb, 400)] + \
            [cache[n] for n in ('textValid', 'textLen', 'textY', 'textText',
                                'iigs_textShown')] + [(hu[0], hu[1])]
        data = ref_call('hu_stuff65.s:HU_Drawer', pokes, saves, work)
        return [bytes(lines).hex()] + [d.hex() for d in data]
    ins = drawer_inputs()
    return [{'input': i, 'out': [bytes.fromhex(x) for x in r]}
            for i, r in zip(ins, cached_truth('drawer', ins, fn, jobs))]


def drawer_synth_cases(tx: Texts) -> List[Frame]:
    from ref816 import refimage
    mem = refimage.load(refimage.read(base_path()))
    scb = mem.get(sym('i_viigs65.s:scb'), 200)
    nib = tuple(mem.get(NIBTAB + p * 0x400, 0x400) for p in SET_PALS)
    out = []
    for k, t in enumerate(drawer_truth()):
        slot = t['input'][0]
        lines, buf0, buf160, marks, valid, tlen, ty, ttext, shown, hu = \
            t['out']
        hin = {'hu': bytearray(places().hu[1]), 'textValid': bytes(4),
               'textLen': bytes(4), 'textY': bytes(4),
               'textText': bytes(80), 'iigs_textShown': bytes(4)}
        o_t = hu_offset('w_title')
        hin['hu'][o_t:o_t + 2 * TL_SIZE] = lines
        hin['hu'] = bytes(hin['hu'])
        hout = {'textValid': valid, 'textLen': tlen, 'textY': ty,
                'textText': ttext, 'iigs_textShown': shown, 'hu': hu}
        if slot == 'msg':
            ident = MS.TEST_ID + k
            st = state_block(hin, tx, 0, MS.NONE_ID - 1, 0xF0)
            f = Frame('synthetic %d (%s)' % (k, slot), 0, 1, ident, 0xF0, 0,
                      1, bytes(scb[r] for r in ROWS18), nib, bytes(18 * ROW),
                      rows18(buf0, buf160), (), True, False, None, hin, hout,
                      st)
        else:
            st = state_block(hin, tx, 0, MS.NONE_ID, 0xF0)
            f = Frame('synthetic %d (%s)' % (k, slot), 0, 0, MS.NONE_ID,
                      0xF0, AM_ACTIVE, 1, bytes(scb[r] for r in ROWS18),
                      nib, bytes(18 * ROW), rows18(buf0, buf160), (), False,
                      True, None, hin, hout, st)
        if any(buf160[TITLE_ROWS * ROW:]):
            raise HudError('%s: upstream drew rows 168-169' % f.name)
        out.append(f)
    return out


# ---------------------------------------------------------------------------
# A run's checks
# ---------------------------------------------------------------------------

def build_of(obj: Path = OUT):
    return SR.load_build(obj, 's2ht', 'P2DW')


def check_run(run: str, b, tx: Texts, profile: Optional[str],
              work_root: Path) -> Dict[str, Any]:
    """The checkpoint on one run: its tics (chained and injected), the PV
    rule, its frames (with the cache and afresh)."""
    calls = load(run)
    tics, problems = tic_cases(calls, tx)
    frames, p2 = frame_cases(calls, tx)
    problems += p2
    if len(tics) > TICS_A_BANK or len(frames) > 20 * FRAMES_A_BANK:
        raise HudError('%s: %d tics, %d frames' % (run, len(tics),
                                                   len(frames)))
    store = store_records()
    sets: Dict[bytes, int] = {}
    recs = list(store)
    recs += tic_banks(tics, TIC_CALLS[0][0], 'chained')
    recs += tic_banks(tics, TIC_CALLS[1][0], 'injected')
    recs += frame_banks(frames, FRAME_IN, sets)
    recs.append(set_bank(sets, NIB_BANK))
    # the card's HUD state before the first chained tic: the reference's
    if tics:
        t0 = tics[0]
        st = bytearray(7)
        st[0], st[1] = t0.on & 0xFF, t0.new & 0xFF
        st[2:4] = t0.counter.to_bytes(2, 'little')
        st[4:6] = t0.msgid.to_bytes(2, 'little')
        recs.append((2, 0, S.BUILDS['test'].s2t_base + S.S2T['HU_ON'],
                     bytes(st)))
    calls_ = [SR.Call('hut_tics', TIC_CALLS[0][0], TIC_CALLS[0][1]),
              SR.Call('hut_tics', TIC_CALLS[1][0], TIC_CALLS[1][1]),
              SR.Call('hut_frames', FRAME_IN, 0, NIB_BANK)]
    work = Path(tempfile.mkdtemp(prefix='tmp-%s-' % run, dir=str(work_root)))
    n_stray, stray_list = 0, []
    try:
        r = run_native(b, calls_, recs, work, profile)
        writes = r.writes()
        n, s = SR.stray(writes, owners(b, r.loads))
        n_stray, stray_list = n_stray + n, stray_list + s
        sps = spans(b, writes, 'hu_drawer')
        nt = len(tics)
        if len(sps) != 2 * nt + len(frames):
            raise HudError('%s: %d windows for %d tics and %d frames' % (
                run, len(sps), nt, len(frames)))
        outs = {m: tic_outputs(writes, nt, TIC_CALLS[k][1])
                for k, m in enumerate(('chained', 'injected'))}
        stack = SR.stack_depth(r)
        cost = r.cost() if profile else None
        del writes, r
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    # the same frames drawn afresh (PS_TXTINV every frame), in runs of
    # FRESH_CHUNK frames, each starting from the reference's state
    fresh: List[Span] = []
    for k0 in range(0, len(frames), FRESH_CHUNK):
        chunk = list(frames[k0:k0 + FRESH_CHUNK])
        chunk[0] = chunk[0]._replace(state=state_block(
            chunk[0].hin, tx, 0xA5, MS.NONE_ID - 1, 0xFF))
        sets2: Dict[bytes, int] = {}
        recs2 = list(store) + frame_banks(chunk, FRESH_IN, sets2, True)
        recs2.append(set_bank(sets2, NIB_BANK))
        work = Path(tempfile.mkdtemp(prefix='tmp-%s-fresh-' % run,
                                     dir=str(work_root)))
        try:
            r = run_native(b, [SR.Call('hut_frames', FRESH_IN, 0,
                                       NIB_BANK)], recs2, work, None)
            writes = r.writes()
            n, s = SR.stray(writes, owners(b, r.loads))
            n_stray, stray_list = n_stray + n, stray_list + s
            got = spans(b, writes, 'hu_drawer')
            if len(got) != len(chunk):
                raise HudError('%s: %d windows for %d frames afresh' % (
                    run, len(got), len(chunk)))
            fresh += got
            del writes, r
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    if n_stray:
        problems.append('%s: %d stray writes: %s' % (run, n_stray,
                                                      stray_list[:3]))
    for mode in ('chained', 'injected'):
        for t, got in zip(tics, outs[mode]):
            problems += tic_compare(t, got, tx, '%s %s call %d' % (
                run, mode, t.call))
    # PV: message_on after the frame's tics, and R7's VIEWTOP
    pv_n = 0
    by_call = {t.call: k for k, t in enumerate(tics)}
    last = None
    for c in calls:
        if c['call'] in by_call:
            last = outs['chained'][by_call[c['call']]]
        if c['name'] != 'PV':
            continue
        pv_n += 1
        on = last[0] if last is not None else 0
        ref_on = w16(c['in']['message_on'])
        top = 9 if on and not w16(c['in']['paused']) else 0xFFFF
        if on != ref_on:
            problems.append('%s PV call %d: message_on %d, ref %d' % (
                run, c['call'], on, ref_on))
        if top != w16(c['in']['viewtop']):
            problems.append('%s PV call %d: VIEWTOP $%04X, ref $%04X' % (
                run, c['call'], top, w16(c['in']['viewtop'])))
    fsp = sps[2 * nt:2 * nt + len(frames)]
    excluded: Dict[str, int] = {}
    kinds = {'fresh': 0, 'replay': 0, 'shown': 0}
    native_fresh = 0
    for f, sp, sq in zip(frames, fsp, fresh):
        problems += frame_problems(f, sp)
        if f.excluded:
            excluded[f.excluded] = excluded.get(f.excluded, 0) + 1
        a, _ = native_rows(f.before, f.blacks, sp.published)
        c_, _ = native_rows(f.before, f.blacks, sq.published)
        if a != c_:
            problems.append('%s %s: the cached frame differs from the '
                            'fresh draw: %s' % (run, f.name, first_diff(
                                a, c_, 0, len(a))))
        native_fresh += 1 if sp.records else 0
        for k, cond in ((0, f.on), (1, f.automap & 1)):
            if cond:
                kinds[kind_of(f, k)] += 1
    # named difference D2: a replay of the title marks rows 160-169 whole
    # upstream, 160-167 natively; rows 168-169 of the back buffer (the
    # status bar's) must then be the screen's already
    d2 = 0
    for f in frames:
        if f.automap & 1 and kind_of(f, 1) == 'replay':
            d2 += 1
            if f.after168 is None or bytes(f.hout['buf160'][
                    TITLE_ROWS * ROW:]) != bytes(f.after168):
                problems.append('%s %s: the title\'s replay: rows 168-169 '
                                'of the back buffer are not the screen\'s'
                                % (run, f.name))
    ref_fresh = sum(1 for f in frames if any(
        kind_of(f, k) == 'fresh' for k, cnd in ((0, f.on), (1, f.automap & 1))
        if cnd))
    if native_fresh != ref_fresh:
        problems.append('%s: %d frames drew a line afresh, the reference %d'
                        % (run, native_fresh, ref_fresh))
    return {'run': run, 'tics': nt, 'pv': pv_n, 'frames': len(frames),
            'kinds': kinds, 'excluded': excluded, 'sets': len(sets),
            'd2': d2,
            'stack': stack, 'problems': problems,
            'tic_ms': [round(ms(profile, s.end - s.start), 4)
                       for s in sps[:nt]] if profile else [],
            'frame_ms': [(kind_of_frame(f), round(ms(profile, s.end -
                                                      s.start), 4))
                         for f, s in zip(frames, fsp)] if profile else [],
            'cost': cost['phases'][S.PHASE_2D] if cost else None}


def kind_of(f: Frame, slot: int) -> str:
    """The reference's: 'shown' (nothing drawn), 'replay', 'fresh'."""
    i = f.hin
    label = 'w_message' if slot == 0 else 'w_title'
    y, text, n, _ = line_of(i['hu'], label)
    same = w16(i['textValid'], 2 * slot) and \
        w16(i['textLen'], 2 * slot) == n and \
        w16(i['textY'], 2 * slot) == (0 if slot == 0 else TITLE_Y) and \
        bytes(i['textText'][40 * slot:40 * slot + n]) == bytes(text)
    if not same:
        return 'fresh'
    return 'shown' if w16(i['iigs_textShown'], 2 * slot) else 'replay'


def kind_of_frame(f: Frame) -> str:
    ks = [kind_of(f, k) for k, c in ((0, f.on), (1, f.automap & 1)) if c]
    if 'fresh' in ks:
        return 'fresh'
    if 'replay' in ks:
        return 'replay'
    return 'clear' if f.flags & 1 else 'nothing'


def ms(profile: str, clocks: int) -> float:
    from a2vm import costs
    return clocks / (costs.parameters(profile)['fabric_mhz'] * 1000.0)


def check_synth(b, tx: Texts, profile: Optional[str], work_root: Path
                ) -> Dict[str, Any]:
    """The synthetic tics and lines against ref816 --call."""
    tics = tic_synth_cases(tx)
    frames = drawer_synth_cases(tx)
    sets: Dict[bytes, int] = {}
    recs = store_records() + tic_banks(tics, TIC_CALLS[2][0], 'injected')
    recs += frame_banks(frames, SYN_IN, sets)
    recs.append(set_bank(sets, NIB_BANK))
    calls_ = [SR.Call('hut_tics', TIC_CALLS[2][0], TIC_CALLS[2][1]),
              SR.Call('hut_frames', SYN_IN, 0, NIB_BANK)]
    work = Path(tempfile.mkdtemp(prefix='tmp-synth-', dir=str(work_root)))
    try:
        r = run_native(b, calls_, recs, work, profile)
        writes = r.writes()
        n_stray, stray_list = SR.stray(writes, owners(b, r.loads))
        sps = spans(b, writes, 'hu_drawer')
        outs = tic_outputs(writes, len(tics), TIC_CALLS[2][1])
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    problems = []
    if n_stray:
        problems.append('synthetic: %d stray writes: %s' % (n_stray,
                                                             stray_list[:3]))
    if len(sps) != len(tics) + len(frames):
        raise HudError('synthetic: %d windows' % len(sps))
    for t, got in zip(tics, outs):
        problems += tic_compare(t, got, tx, 'synthetic tic %d %s' % (
            t.call, tic_inputs()[t.call]))
    for f, sp in zip(frames, sps[len(tics):]):
        problems += frame_problems(f, sp, base=bytes(18 * ROW))
    return {'tics': len(tics), 'frames': len(frames), 'problems': problems}


# ---------------------------------------------------------------------------
# The checkpoint, the timing, the sizes
# ---------------------------------------------------------------------------

PROFILES = ('f121', 'fastpath')


def stats(values: Sequence[float]) -> Dict[str, float]:
    v = sorted(values)
    if not v:
        return {}
    return {'n': len(v), 'median': round(v[len(v) // 2], 3),
            'p99': round(v[min(len(v) - 1, (99 * len(v)) // 100)], 3),
            'worst': round(v[-1], 3)}


def check_all(runs: Sequence[str], profile: str = 'f121',
              obj: Path = OUT, jobs: int = JOBS, synth: bool = True
              ) -> Dict[str, Any]:
    b = build_of(obj)
    tx = Texts(test=True)
    work_root = Path(tempfile.mkdtemp(prefix='tmp-s2hud-run-',
                                      dir=str(obj)))
    try:
        with ThreadPoolExecutor(max(1, min(jobs, JOBS))) as ex:
            futs = [ex.submit(check_run, r, b, tx, profile, work_root)
                    for r in runs]
            if synth:
                fs = ex.submit(check_synth, b, tx, profile, work_root)
            results = [f.result() for f in futs]
            syn = fs.result() if synth else None
    finally:
        shutil.rmtree(str(work_root), ignore_errors=True)
    problems = [p for r in results for p in r['problems']]
    if syn:
        problems += syn['problems']
    return {'runs': results, 'synthetic': syn, 'problems': problems,
            'profile': profile}


def timing(result: Dict[str, Any]) -> Dict[str, Any]:
    by: Dict[str, List[float]] = {}
    tic: List[float] = []
    for r in result['runs']:
        for kind, v in r['frame_ms']:
            by.setdefault(kind, []).append(v)
            by.setdefault('all', []).append(v)
        tic += r['tic_ms']
    return {'frames': {k: stats(v) for k, v in sorted(by.items())},
            'tic_us': {k: round(v * 1000, 2) for k, v in
                       stats(tic).items() if k != 'n'}}


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """Each module of s2ht (P2DW's room), s2_hu's segments, the bank
    table, against the budgets (SCREENS.md 7.3: P2DW 700 B and the texts'
    1,000, the tic side 150)."""
    b = build_of(obj)
    ms_ = S.read_map((obj / 's2ht.map').read_text())
    segs = {s: segment_of(b, s, 's2_hu') for s in S.IMG_SEGMENTS}
    seg_n = {s: (v[1] - v[0] + 1) if v else 0 for s, v in segs.items()}
    return {'modules': dict(ms_.modules), 's2_hu': seg_n,
            'p2dw': ms_.modules.get('s2_hu', 0), 'p2dw_budget': 1700,
            'tic': ms_.modules.get('s2t_hu', 0), 'tic_budget': 150,
            'texts_bank': len(MS.bank_table()),
            'texts_bank_room': MS.SS_HUDMSG_SIZE,
            'room': (obj / 's2ht.sizes').read_text().splitlines()[-1]}


# ---------------------------------------------------------------------------
# The planted bugs (each in a scratch copy of the part's sources)
# ---------------------------------------------------------------------------

LATE_OLD = """        lda HU_COUNTER          ; the counter, before a new message: at its
        ora HU_COUNTER+1        ;   end the line goes
        beq @take
        lda HU_COUNTER
        bne :+
        dec HU_COUNTER+1
:       dec HU_COUNTER
        lda HU_COUNTER
        ora HU_COUNTER+1
        bne @take
        stz HU_ON
@take:"""
LATE_NEW = """        lda HU_COUNTER          ; (planted: off a tic after the end)
        ora HU_COUNTER+1
        bne :+
        stz HU_ON
        bra @take
:       lda HU_COUNTER
        bne :+
        dec HU_COUNTER+1
:       dec HU_COUNTER
@take:"""
PLANTED = (
    ('the replay not marking its rows', 's2_hu.s',
     (('        lda S2_Y0\n        jmp s2_mark\n',
       '        lda S2_Y0\n        rts\n'),)),
    ('lower case not mapped', 's2_hu.s',
     (("        cmp #'a'                ; toupper\n",
       "        cmp #$FF                ; toupper\n"),)),
    ('the space width 3', 's2_hu.s', (('SPACE_W = 4 ', 'SPACE_W = 3 '),)),
    ('the line cut at 319', 's2_hu.s',
     (('        cmp #<(SCREENWIDTH + 1)\n        lda hz_t+1\n'
       '        sbc #>(SCREENWIDTH + 1)\n',
       '        cmp #<SCREENWIDTH\n        lda hz_t+1\n'
       '        sbc #>SCREENWIDTH\n'),)),
    ('message_on cleared a tic late', 's2t_hu.s', ((LATE_OLD, LATE_NEW),)),
    # the end's test made before the take, its clear of message_on after
    # it: a new message dies at once when the old counter reaches 1
    ('the counter tested after the take', 's2t_hu.s',
     (('hu_ticker:\n        lda HU_COUNTER',
       'hu_ticker:\n        stz HU_SPARE\n        lda HU_COUNTER'),
      ('        bne @take\n        stz HU_ON\n@take:',
       '        bne @take\n        inc HU_SPARE\n@take:'),
      ('@done:  rts\n\nhu_start:',
       '@done:  lda HU_SPARE\n        beq :+\n        stz HU_ON\n'
       ':       rts\n\nhu_start:'))),
    ('hu_ticker reading player.message after hu_tick\'s clear', 's2_hut.s',
     (('        jsr hu_ticker\n        stz PHASE\n        jsr hutick\n',
       '        jsr hutick\n        jsr hu_ticker\n        stz PHASE\n'),)),
)


def plant(k: int, runs: Sequence[str], jobs: int = JOBS
          ) -> Tuple[str, List[str]]:
    """Planted bug k in a scratch copy: built, then the checks; the
    problems it gives (the first ones)."""
    name, source, edits = PLANTED[k]
    scratch = Path(tempfile.mkdtemp(prefix='tmp-s2hud-plant-',
                                    dir=str(OUT)))
    try:
        src = scratch / 'src'
        (src / 'm11').mkdir(parents=True)
        for f in ('m11.mk',):
            shutil.copy(str(SOURCE / f), str(src / f))
        for f in ('s2lay.mk', 's2hud.mk'):
            shutil.copy(str(SOURCE / 'm11' / f), str(src / 'm11' / f))
        for f in ('s2_hu.s', 's2t_hu.s', 's2_hut.s'):
            shutil.copy(str(SOURCE / f), str(src / f))
        text = (src / source).read_text()
        for old, new in edits:
            if text.count(old) != 1:
                raise HudError('planted %r: %r is not found once' % (
                    name, old[:40]))
            text = text.replace(old, new)
        (src / source).write_text(text)
        m11 = scratch / 'm11'
        (m11 / 'shared' / 'gen').mkdir(parents=True)
        for f in KEEP_GEN:
            shutil.copy(str(SHARED_GEN / f), str(m11 / 'shared' / 'gen' / f))
        (m11 / 's2data').mkdir()
        for f in (M11 / 's2data').glob('s2data.*'):
            shutil.copy(str(f), str(m11 / 's2data' / f.name))
        make(m11 / 's2hud', src, m11)
        try:
            res = check_all(runs, None, m11 / 's2hud', jobs)
        except (HudError, SR.RunError) as error:
            text = str(error).strip().splitlines()
            return name, ['the run failed: %s' % (text[0] if text else
                                                  type(error).__name__)]
        return name, res['problems']
    finally:
        shutil.rmtree(str(scratch), ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--planted', action='store_true')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--runs', default=','.join(RUNS))
    parser.add_argument('--jobs', type=int, default=JOBS)
    args = parser.parse_args(argv)
    runs = [r for r in args.runs.split(',') if r]
    jobs = max(1, min(args.jobs, JOBS))
    report: Dict[str, Any] = {}
    status = 0
    try:
        if args.capture or args.all:
            if free_disk() < MIN_FREE:
                raise HudError('less than 20 GB free')
            rs = routines()
            with ThreadPoolExecutor(jobs) as ex:
                report['captures'] = list(ex.map(
                    lambda run: capture(run, rs), runs))
            for c in report['captures']:
                print('captured', c)
        if not args.no_build and (args.check or args.all or args.planted):
            note = make()
            if note:
                print(note)
                report['build_note'] = note
        if args.check or args.all:
            for prof in (PROFILES if args.all else PROFILES[:1]):
                res = check_all(runs, prof, jobs=jobs)
                report[prof] = {'timing': timing(res),
                                'runs': [{k: v for k, v in r.items()
                                          if k not in ('tic_ms', 'frame_ms')}
                                         for r in res['runs']],
                                'synthetic': res['synthetic'],
                                'problems': res['problems'][:50]}
                for r in res['runs']:
                    print('%s %s: %d tics, %d PV, %d frames %s, excluded %s,'
                          ' %d problems' % (prof, r['run'], r['tics'],
                                            r['pv'], r['frames'], r['kinds'],
                                            r['excluded'],
                                            len(r['problems'])))
                syn = res['synthetic']
                print('%s synthetic: %d tics, %d lines, %d problems' % (
                    prof, syn['tics'], syn['frames'], len(syn['problems'])))
                print('%s timing: %s' % (prof, json.dumps(timing(res))))
                for p in res['problems'][:20]:
                    print('  ' + p)
                if res['problems']:
                    status = 1
            report['sizes'] = sizes()
            print('sizes: %s' % report['sizes'])
        if args.planted or args.all:
            report['planted'] = []
            for k in range(len(PLANTED)):
                name, problems = plant(k, runs, jobs)
                report['planted'].append({'bug': name,
                                          'caught': len(problems),
                                          'first': problems[:2]})
                print('planted %r: %d problems; %s' % (
                    name, len(problems), problems[:1]))
                if not problems:
                    status = 1
    except HudError as error:
        print('s2hud: %s' % error, file=sys.stderr)
        return 1
    if args.all:
        report['ok'] = status == 0
        path = OUT / 'report.json'
        path.write_text(json.dumps(report, indent=1) + '\n')
        print('%s: %s' % (path, 'ok' if status == 0 else 'problems'))
    return status


if __name__ == '__main__':
    sys.exit(main())
