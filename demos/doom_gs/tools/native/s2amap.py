#!/usr/bin/env python3
"""Part s2amap's checks (docs/SCREENS.md 1.5.4, 4.1, 6, 7.3; docs/m11-parts/
s2amap.md): the automap's full mode, the image AMAPW, against upstream's
frames of coverage/m11/automap.script on ref816.

The truth is a capture of its own (part s2cap's cases hold the 2D state
but not the level the map is drawn from: the lines, sides and sectors are
in the zone, which s2cap leaves out): one ref816 run of automap.script
(after a first, cheap run that finds where the level's arrays and the
player's mobj are in the zone), with

  - at AM_Drawer's entry in the full mode (automapmode 9 or 1): the
    automap's near data, the lines, sides and sectors, the player and his
    mobj, the palette state (iigs_rowbase, scb, viewpal), the HUD's
    message_on and message_new, the menu flag, gamemap, AM_LISTS, the
    screen and the nibble tables;
  - at AM_Drawer's return in display's full path: the automap's near
    data, AM_LISTS and the HUD's text flags;
  - at displayCall + 3 (the frame's end): the screen;
  - call logs of AM_Responder (its event, the automap's state, gamemap and
    the mobj's place in, the state and player.message out) and AM_Ticker
    (the state and the mobj's place), every call of the script.

The native side is the image AMAPW (src/native/s2_am.s, s2_amline.s, the
publish s2_pub.s) under the test driver s2_drv with the glue s2_amt.s
(the image s2at): the level in its native places (LVG0, LVS, LVG1,
LVMAP's sectors, LNMAP, the player's RTHING; built here from upstream's
arrays), each case staged in RamWorks and copied into place by the glue,
then am_frame (or am_responder, am_ticker) in the cost phase 30.

Checks:
  frames     every full-map frame, injected (fill $A5 with the screen as
             captured; fill $5A with every byte the frame changes in the
             map's rows poisoned): the map's rows (AM_WTOP .. 159) equal
             to the reference's screen after the frame; every other screen
             byte its injected value or black in a frame that clears it
             (redraw: rows 0-167; clearStrip: rows 0-9); the SCBs and
             palettes untouched; the state after equal to the reference's
             at AM_Drawer's return (am_valid, am_band, AM_OLDTOP, message_
             new, the set of bytes in the new list); no stray write;
  chained    the full-map frames in order from the first one's state: the
             state, the old list and the screen carried by the native code,
             the reference's AM_Responder events and the frame's tics
             (am_frame's A) between frames;
  calls      every AM_Responder and AM_Ticker call of the script from the
             reference's state at its entry: the state after (and A, and
             player.message) equal; and chained: every call in order from
             the first one's state, carried by the native code.

Also: the host model of upstream's drawing (class Model) against the
reference on every frame (--model), and S2_MAIL's two inputs on a frame
(MAIL_AMVIEW: all again; MAIL_AMSTOP: nothing drawn).

Usage:
  python3 tools/native/s2amap.py --inc OUT      the generated s2amap.inc
  python3 tools/native/s2amap.py --capture      the reference (ref816)
  python3 tools/native/s2amap.py --model        the host model's check
  python3 tools/native/s2amap.py --check [--profile f121] [--jobs 2]
  python3 tools/native/s2amap.py --planted [--jobs 2]
  python3 tools/native/s2amap.py --timing [--jobs 2]
  python3 tools/native/s2amap.py --all [--jobs 2]  (the model, the checks,
                                    the timing on f121 and fastpath, the
                                    planted bugs, the sizes: build/native/
                                    m11/s2amap/report.json)
"""

import argparse
import json
import shutil
import struct
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, rlayout as R, s2layout as S  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
OUT = M11 / 's2amap'
CAP = OUT / 'cap'
SOURCE = ROOT / 'src' / 'native'
RUN = 'automap'
JOBS = 2
PROFILES = ('f121', 'fastpath')
FILLS = ((0xA5, False), (0x5A, True))     # (fill, poisoned)
CAP_FORMAT = 's2amap-cap 1'
DRAIN_US = 0.991        # µs a published byte drains on F1.2.1 [M: s2draw.md]
LOAD_US = 0.246         # µs a byte of far_pload [A on M: NATIVE.md 4.3]


class AmError(Exception):
    pass


# ---------------------------------------------------------------------------
# Upstream's automap (am_map65.s) and the structures it reads (offsets.inc)
# ---------------------------------------------------------------------------

AM_ACTIVE, AM_OVERLAY, AM_ROTATE, AM_FOLLOW = 1, 2, 4, 8
F_W, F_H = 320, 168
AM_TITLEY = F_H - 1 - 7         # 160: the lines' rows end there
STRIP_ROWS = 10
AM_LMAX = 3000                  # upstream's entries a list
SIZEOF_LINE, SIZEOF_SIDE, SIZEOF_SEC, SIZEOF_MO = 36, 14, 58, 120
OFS_LINE = {'V1': 0, 'V2': 4, 'DX': 8, 'DY': 10, 'SIDENUM': 12, 'BBOX': 16,
            'TAG': 24, 'FLAGS': 26, 'SLOPE': 27, 'VALID': 28, 'RVALID': 30,
            'RFLAGS': 32, 'SPECIAL': 34}
OFS_SIDE_SECTOR = 0
OFS_SEC = {'FLOOR': 0, 'CEIL': 4, 'OLDSPECIAL': 52}
OFS_MO = {'X': 12, 'Y': 16, 'ANGLE': 32}
OFS_PL_MO, OFS_PL_POWERS, OFS_PL_MESSAGE = 0, 41, 113
PW_ALLMAP = 4
ML_MAPPED = 0x100
SIZEOF_PL = 155
# the line drawer's colours (am_map65.s COLOR_*), by the native index
COLOURS = (('WALL', 23), ('FCHG', 55), ('CCHG', 215), ('CLSD', 208),
           ('RDOR', 175), ('BDOR', 204), ('YDOR', 231), ('TELE', 119),
           ('SECR', 252), ('UNSN', 104))
AMAP_PAL = 11                   # i_viigs65.s: the full automap's palette

# ---------------------------------------------------------------------------
# The native places this part needs beyond s2.inc (marked stand-ins until
# the integrator applies the requests of docs/m11-parts/s2amap.md)
# ---------------------------------------------------------------------------

# Requests S2AMAP-1 to -4, applied in wave 6's integration: AMAPW's own
# fields after the field map's A_* in its state block (s2layout's
# AMAPW_NATIVE: AM_MODE, AM_OLDTOP, the old list's entries, its four
# bands' first entries), S2STATE's SS_AMSEG for the frame's clipped lines
# (8 bytes a line: 1,520 lines and the arrow's 7), S2_MAIL's bits for P2DW
# and the frame driver (MAIL_AMSTRIP, MAIL_AMTITLE, MAIL_AMVIEW) and the
# stops PL_AMPALS, PL_AMSEGS: all in s2.inc.
AMAPW_NATIVE = S.AMAPW_NATIVE
SS_AMSEG_SIZE = S.SS_SIZE['SS_AMSEG']
SEG_SIZE = 8
SEG_MAX = SS_AMSEG_SIZE // SEG_SIZE
MAIL_AMSTRIP = S.MAIL_AMSTRIP
MAIL_AMTITLE = S.MAIL_AMTITLE
MAIL_AMVIEW = S.MAIL_AMVIEW
LIST_ENTRIES = 2048     # the native byte list (SCREENS.md 4.1)
BAND_ROWS = 42
BANDS = 4


def state_places() -> Dict[str, int]:
    """AMAPW's state fields at their W addresses: s2layout's (the field
    map's A_*), then this part's native ones (S2AMAP-1)."""
    return S.state_places('AMAPW')


def ss_amseg() -> int:
    """SS_AMSEG's place in S2STATE (s2layout's, S2AMAP-2)."""
    return S.SS['SS_AMSEG']


def mail_bits() -> Dict[str, int]:
    return {'MAIL_AMSTRIP': MAIL_AMSTRIP, 'MAIL_AMTITLE': MAIL_AMTITLE,
            'MAIL_AMVIEW': MAIL_AMVIEW}


# ---------------------------------------------------------------------------
# The release: symbols, constants
# ---------------------------------------------------------------------------

def symbols():
    from native import s2cap as C
    return C.symbols()


def sym(name: str) -> int:
    from native import s2cap as C
    return C.sym(name)


def release_word(name: str) -> int:
    from native import s2cap as C
    a = sym(name)
    return int.from_bytes(C.code().get(a, 2), 'little')


KEY_NAMES = ('key_map_right', 'key_map_left', 'key_map_up', 'key_map_down',
             'key_map_zoomin', 'key_map_zoomout', 'key_map', 'key_map_follow')


def keys() -> Dict[str, int]:
    """upstream's automap keys (g_game65.s's cnear constants [R
    g_game65.s:96-106]), read from the release."""
    return {n: release_word('g_game65.s:' + n) for n in KEY_NAMES}


def player_arrow() -> List[int]:
    """playerArrow [R am_map65.s:212-218]: 7 lines of 4 int32."""
    from native import s2cap as C
    a = sym('am_map65.s:playerArrow')
    data = C.code().get(a, 7 * 16)
    return list(struct.unpack('<28i', data))


def door_colours() -> bytes:
    from native import s2cap as C
    return C.code().get(sym('am_map65.s:doorColors'), 9)


def message_ids() -> Dict[str, int]:
    ids = {s: k for k, s in enumerate(LL.symbol_list())}
    return {'on': ids['am_map65.s:msgFollowOn'],
            'off': ids['am_map65.s:msgFollowOff']}


def player_offsets() -> Dict[str, int]:
    pl = {}
    for path, enc, at in LL.player_layout():
        pl[path] = at
    return {'mo': pl[('mo',)], 'allmap': pl[('powers', PW_ALLMAP)],
            'message': pl[('message',)]}


# ---------------------------------------------------------------------------
# The generated include
# ---------------------------------------------------------------------------

def inc_values() -> List[Tuple[str, int, str]]:
    po = player_offsets()
    k = keys()
    ids = message_ids()
    rows = [
        ('AM_GPLAYER', LL.G['G_PLAYER'], 'the player (milestone 10)'),
        ('AM_PLMO', LL.G['G_PLAYER'] + po['mo'], 'player.mo, a handle'),
        ('AM_PLALLMAP', LL.G['G_PLAYER'] + po['allmap'],
         'player.powers[pw_allmap], a word'),
        ('AM_PLMSG', LL.G['G_PLAYER'] + po['message'],
         'player.message: tag, id (2), offset (2)'),
        ('AM_GAMEMAP', LL.G['G_GAMEMAP'], 'gamemap, a word'),
        ('AM_MENU', LL.G['G_MENUACTIVE'], 'menuactive, a word'),
        ('AM_NLINES', LL.LVCOUNT2, 'the level\'s lines, a word'),
        ('AM_LNMAP', LL.LNMAP, 'ML_MAPPED, a bit a line'),
        ('AM_FAUTO', R.FRAME['AUTOMAP'],
         'the frame block\'s AUTOMAP (the renderer reads it)'),
        ('AM_LVG0', LL.LVG0, 'the lines\' bank'),
        ('AM_LINE0', LL.LINES.base, 'the first line record'),
        ('AM_LINE_SIZE', LL.LINE_SIZE, ''),
        ('AM_LINE_FETCH', LL.LINE['FLAGS'] + 1, 'the bytes of a line read'),
        ('AM_LV1X', LL.LINE['V1X'], ''), ('AM_LV1Y', LL.LINE['V1Y'], ''),
        ('AM_LV2X', LL.LINE['V2X'], ''), ('AM_LV2Y', LL.LINE['V2Y'], ''),
        ('AM_LSIDE1', LL.LINE['SIDE1'], ''),
        ('AM_LSPECIAL', LL.LINE['SPECIAL'], 'a byte, sign-extended'),
        ('AM_LFLAGS', LL.LINE['FLAGS'], ''),
        ('AM_LVS', LL.LVS, 'LNSECF, LNSECB\'s bank'),
        ('AM_LNSECF', LL.LVS_LNSECF, 'each line\'s front sector'),
        ('AM_LNSECB', LL.LVS_LNSECB, 'each line\'s back sector'),
        ('AM_LVG1', LL.LVG1, 'the sectors\' game part'),
        ('AM_SECG0', LL.SECGS.base, ''), ('AM_SECG_OLDSP',
                                          LL.SECG['OLDSPECIAL'], ''),
        ('AM_LVMAP', R.LVMAP, 'the sectors\' render part'),
        ('AM_SEC0', R.SECTORS.base, ''), ('AM_SEC_FLOOR', R.SEC['FLOOR'], ''),
        ('AM_SEC_CEIL', R.SEC['CEIL'], ''),
        ('AM_RTH', R.RTH, 'the render things (a mobj\'s x, y, angle)'),
        ('AM_RTH0', R.RTHINGS.base, ''), ('AM_TH_X', R.RTHING['X'], ''),
        ('AM_TH_Y', R.RTHING['Y'], ''), ('AM_TH_ANGHI', R.RTHING['ANG'], ''),
        ('AM_TH_ANGLO', LL.TH_ANGLO, ''),
        ('AM_SEG_MAX', SEG_MAX, ''),
        ('AM_MSG_ON', ids['on'], 'am_map65.s:msgFollowOn\'s id'),
        ('AM_MSG_OFF', ids['off'], 'am_map65.s:msgFollowOff\'s id'),
    ]
    for n, v in k.items():
        rows.append(('AM_' + n.upper(), v, 'g_game65.s:' + n))
    return rows


def inc_text() -> str:
    lines = ['; Generated by tools/native/s2amap.py (part s2amap, docs/'
             'm11-parts/s2amap.md). Do not edit.', '']
    for name, value, why in inc_values():
        lines.append('%-15s = $%04X%s' % (name, value,
                                          ' ; ' + why if why else ''))
    arrow = player_arrow()
    lines += ['', '; playerArrow [R am_map65.s:212-218], read from the '
              'release', '.macro AM_ARROW']
    for i in range(0, 28, 4):
        lines.append('        .dword %s' % ', '.join(
            '$%08X' % (v & 0xFFFFFFFF) for v in arrow[i:i + 4]))
    lines += ['.endmacro', '',
              '; doorColors [R am_map65.s:219-220] as colour indexes',
              '.macro AM_DOORS']
    idx = {c: k for k, (_, c) in enumerate(COLOURS)}
    lines.append('        .byte %s' % ', '.join(
        '$%02X' % (idx[c] if c else 0xFF) for c in door_colours()))
    lines += ['.endmacro', '', '; the colours by index (COLOR_*)',
              '.macro AM_COLOURS',
              '        .byte %s' % ', '.join('%d' % c for _, c in COLOURS),
              '.endmacro']
    for k, (n, _) in enumerate(COLOURS):
        lines.append('AMC_%-11s = %d' % (n, k))
    lines.append('AM_NCOLOURS     = %d' % len(COLOURS))
    return '\n'.join(lines) + '\n'


def write_inc(path: Path) -> None:
    text = inc_text()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)


def inc_dict(path: Path) -> Dict[str, int]:
    out = {}
    for line in path.read_text().splitlines():
        f = line.split(';')[0].split('=')
        if len(f) == 2 and f[1].strip().startswith('$'):
            out[f[0].strip()] = int(f[1].strip()[1:], 16)
    return out


# ---------------------------------------------------------------------------
# The capture (ref816): two runs of automap.script
# ---------------------------------------------------------------------------

LEVEL_PTRS = (('p_setup65.s:_g_lines', 4), ('p_setup65.s:_g_numlines', 2),
              ('p_setup65.s:_g_sides', 4), ('p_setup65.s:numsides', 2),
              ('p_setup65.s:_g_sectors', 4),
              ('p_setup65.s:_g_numsectors', 2),
              ('g_game65.s:_g_player', 4))


def frag(unit: str, section: str) -> Tuple[int, int]:
    from native import s2cap as C
    fr = C.fragments(unit, (section,))
    if len(fr) != 1:
        raise AmError('%s has %d %s fragments' % (unit, len(fr), section))
    return fr[0]


def am_state_ranges() -> List[Tuple[int, int]]:
    """The automap's near and znear data (am_map65.s): its whole state."""
    from native import s2cap as C
    return C.merge(C.fragments('am_map65.s', ('near', 'znear')))


def iv_ranges() -> List[Tuple[int, int]]:
    from native import s2cap as C
    return C.merge(C.fragments('i_viigs65.s', ('near', 'znear')), 96)


def am_drawer_full_return() -> int:
    """display's full-map JSL AM_Drawer, +4 [R d_main65.s:533-536]: the
    later of display's two sites."""
    from native import s2cap as C
    amd = sym('am_map65.s:AM_Drawer')
    lo, hi = sym('d_main65.s:display'), sym('d_main65.s:onlyTics')
    op = bytes([0x22, amd & 0xFF, amd >> 8 & 0xFF, amd >> 16])
    data = C.code().get(lo, hi - lo)
    sites = [lo + i for i in range(len(data) - 3) if data[i:i + 4] == op]
    if len(sites) != 2:
        raise AmError('display has %d JSL AM_Drawer' % len(sites))
    return sites[1] + 4


class Level(NamedTuple):
    lines: int
    nlines: int
    sides: int
    nsides: int
    sectors: int
    nsectors: int
    mo: int


def _logged(text: str) -> Tuple[str, str]:
    return (text.split(',')[0].split(':')[-1], text)


def _mem(ranges: Sequence[Tuple[str, int]]) -> str:
    return '+'.join('%s:%d' % (n, z) for n, z in ranges)


def _abs(ranges: Sequence[Tuple[int, int]]) -> str:
    return '+'.join('%06X:%d' % (a, n) for a, n in ranges)


def find_level(work: Path) -> Level:
    """The first run: where the level's arrays and the player's mobj are
    (the call log of AM_Drawer's entries)."""
    from native import s2cap as C
    sink = C.CallSink()
    text = 'am_map65.s:AM_Drawer,entry=1,in=' + _mem(LEVEL_PTRS)
    C.machine(RUN, work, [], [_logged(text)], lambda h: None, sink.feed)
    seen = set()
    for line in sink.lines:
        mem = bytes.fromhex(''.join(line['in']['mem']))
        seen.add(mem)
    if len(seen) != 1:
        raise AmError('the level moves in the zone during the script (%d '
                      'places)' % len(seen))
    mem = seen.pop()
    v = struct.unpack('<IHIHIHI', mem)
    return Level(v[0] & 0xFFFFFF, v[1], v[2] & 0xFFFFFF, v[3],
                 v[4] & 0xFFFFFF, v[5], v[6] & 0xFFFFFF)


def capture_points(lv: Level) -> List[Any]:
    from native import s2cap as C
    am = am_state_ranges()
    mode = sym('am_map65.s:automapmode')
    lists = (sym('am_map65.s:AM_LISTS'), 4 * AM_LMAX)
    hu = frag('hu_stuff65.s', 'znear')
    entry = am + [(lv.lines, lv.nlines * SIZEOF_LINE),
                  (lv.sides, lv.nsides * SIZEOF_SIDE),
                  (lv.sectors, lv.nsectors * SIZEOF_SEC),
                  (lv.mo, SIZEOF_MO), (sym('g_game65.s:_g_player'),
                                       SIZEOF_PL)] + iv_ranges() + \
        [hu, (sym('m_menu65.s:_g_menuactive'), 2),
         (sym('g_game65.s:_g_gamemap'), 2), lists, C.SCREEN,
         (sym('am_map65.s:NIBTAB'), 0x4000),
         (sym('am_map65.s:VW_THIRD'), 4)]
    ret = am + [lists, hu] + iv_ranges()
    out = []
    for m in (AM_ACTIVE | AM_FOLLOW, AM_ACTIVE):
        cond = ',if=%06X:2:eq:0x%X' % (mode, m)
        out.append(C._pc('E%d' % m, sym('am_map65.s:AM_Drawer'), entry,
                         cond))
        out.append(C._pc('R%d' % m, am_drawer_full_return(), ret, cond))
    dc = sym('d_main65.s:displayCall')
    disp = sym('d_main65.s:display')
    # the frame's start: the palette state before display's
    # I_ViewPalette(AMAP_PAL) (what AMAPW sees: P2DW comes after it)
    out.append(C._pc('P', dc, iv_ranges(),
                     ',if=%06X:2:eq:0x%04X' % (dc + 1, disp & 0xFFFF)))
    out.append(C._pc('F', dc + 3, [C.SCREEN],
                     ',if=%06X:2:eq:0x%04X' % (dc + 1, disp & 0xFFFF)))
    return out


def capture_logs(lv: Level) -> List[Tuple[str, str]]:
    am = _abs(am_state_ranges())
    mo = _abs([(lv.mo + OFS_MO['X'], 8), (lv.mo + OFS_MO['ANGLE'], 4)])
    msg = '%06X:4' % (sym('g_game65.s:_g_player') + OFS_PL_MESSAGE)
    gm = '%06X:2' % sym('g_game65.s:_g_gamemap')
    ev = '%06X:4' % sym('i_iigs65.s:EVENT')
    return [_logged('am_map65.s:AM_Responder,in=%s+%s+%s+%s+%s,out=%s+%s'
                    % (ev, am, gm, mo, msg, am, msg)),
            _logged('am_map65.s:AM_Ticker,in=%s+%s,out=%s' % (am, mo, am))]


class Store:
    """The capture's files: index.json and blobs.pack (s2cap's store: each
    distinct range once, by its SHA-256)."""

    def __init__(self, root: Path, keys: Optional[Dict] = None):
        from native import s2cap as C
        self.root = root
        self.blobs = C.BlobStore(root, keys)

    def put(self, data: bytes) -> str:
        return self.blobs.put(data)

    def get(self, key: str) -> bytes:
        return self.blobs.get(key)


def capture(out: Path = CAP, work_root: Path = OUT) -> Dict[str, Any]:
    """The reference: the level's places (a first run), then the dumps and
    the call logs of automap.script (a second run), distilled as they
    come into out (index.json, blobs.pack)."""
    from native import s2cap as C
    from ref816 import dumps as D
    C.check_disk(BUILD)
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tmp-cap-', dir=str(work_root)))
    try:
        lv = find_level(work)
        if out.exists():
            shutil.rmtree(str(out))
        out.mkdir(parents=True)
        store = Store(out)
        pts = capture_points(lv)
        names = [p.name for p in pts]
        frames: List[Dict[str, Any]] = []
        problems: List[str] = []

        def dump_reader(handle) -> None:
            cur: Optional[Dict[str, Any]] = None
            start: Optional[Dict[str, Any]] = None
            for d in D.read(handle):
                name = names[d.header['point']]
                rec = {'cycles': d.header['cycles'],
                       'ranges': [[a, n, store.put(d.get(a, n))]
                                  for a, n in d.ranges()]}
                if name == 'P':
                    start = rec
                    continue
                if name[0] == 'E':
                    if cur is not None:
                        problems.append('a full frame without its end at '
                                        'cycle %d' % cur['E']['cycles'])
                    if start is None:
                        problems.append('a full frame without its start at '
                                        'cycle %d' % rec['cycles'])
                    cur = {'E': rec, 'P': start}
                elif name[0] == 'R':
                    if cur is None or 'R' in cur:
                        problems.append('AM_Drawer returns at cycle %d '
                                        'outside a frame' % rec['cycles'])
                    else:
                        cur['R'] = rec
                elif cur is not None:
                    if 'R' not in cur:
                        problems.append('a frame ends at cycle %d before '
                                        'AM_Drawer returns' % rec['cycles'])
                    cur['F'] = rec
                    frames.append(cur)
                    cur = None
        sink = C.CallSink()
        st = C.machine(RUN, work, pts, capture_logs(lv), dump_reader,
                       sink.feed)
        problems += list(st['problems'])
        calls = []
        heads = [r['name'] for r in sink.head['routines']]
        for line in sink.lines:
            calls.append({'routine': heads[line['routine']],
                          'cycles': line['cycles'],
                          'in': line['in']['mem'],
                          'out': line['out']['mem'] if line['out'] else None,
                          'a_out': line['out']['a'] if line['out'] else None,
                          'returned': line['returned']})
        index = {'format': CAP_FORMAT, 'run': RUN,
                 'level': lv._asdict(), 'frames': frames,
                 'calls': calls, 'problems': problems,
                 'traffic': st['traffic'],
                 'blobs': {'keys': store.blobs.keys}}
        (out / 'index.json').write_text(json.dumps(index, sort_keys=True))
        return index
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


class Ref:
    """A captured dump: its ranges by address."""

    def __init__(self, rec: Dict[str, Any], store: Store):
        self.cycles = rec['cycles']
        self.parts = [(a, n, store.get(k)) for a, n, k in rec['ranges']]

    def get(self, address: int, length: int) -> bytes:
        for a, n, data in self.parts:
            if a <= address and address + length <= a + n:
                return data[address - a:address - a + length]
        raise KeyError('$%06X+%d is not captured' % (address, length))

    def word(self, address: int, size: int = 2) -> int:
        return int.from_bytes(self.get(address, size), 'little')

    def sym(self, name: str, size: int = 2) -> int:
        return self.word(sym(name), size)

    def sym_bytes(self, name: str, size: int) -> bytes:
        return self.get(sym(name), size)


class Capture:
    def __init__(self, root: Path = CAP):
        self.root = root
        p = root / 'index.json'
        if not p.exists():
            raise AmError('%s is missing: python3 tools/native/s2amap.py '
                          '--capture' % p)
        self.index = json.loads(p.read_text())
        if self.index.get('format') != CAP_FORMAT:
            raise AmError('%s is not an s2amap capture' % p)
        self.store = Store(root, self.index['blobs']['keys'])
        self.level = Level(**self.index['level'])

    def frames(self) -> List[Dict[str, Ref]]:
        return [{k: Ref(v, self.store) for k, v in f.items()}
                for f in self.index['frames']]


# ---------------------------------------------------------------------------
# The cases: the full-map frames and the automap's calls
# ---------------------------------------------------------------------------

_S2INC: Dict[str, int] = {}


def s2inc() -> Dict[str, int]:
    """The generated s2.inc's values (the test build's card places)."""
    if not _S2INC:
        p = M11 / 'shared' / 'gen' / 's2.inc'
        if not p.exists():
            raise AmError('%s is missing: make -C src/native -f m11.mk gen'
                          % p)
        _S2INC.update(inc_dict(p))
    return _S2INC


def amsym(name: str) -> int:
    return sym('am_map65.s:' + name)


class Frame(NamedTuple):
    k: int                      # its index among the full-map frames
    P: Ref                      # the frame's start (the palette state)
    E: Ref                      # AM_Drawer's entry
    R: Ref                      # its return
    F: Ref                      # the frame's end
    tics: int                   # AM_Ticker calls since the frame before
    events: Tuple[Tuple[int, int], ...]     # AM_Responder (type, key)
    chain: int                  # the full-map stretch it is in


class AmCall(NamedTuple):
    k: int
    routine: str                # 'responder' or 'ticker'
    cycles: int
    state_in: Dict[int, int]    # the automap's state bytes by address
    state_out: Dict[int, int]
    event: Tuple[int, int]      # (type, key) for the responder
    mo: bytes                   # x (4), y (4), angle (4)
    gamemap: int
    msg_in: bytes
    msg_out: bytes
    ret: Optional[int]


def _state_map(ranges: Sequence[Tuple[int, int]], data: bytes,
               at: int = 0) -> Tuple[Dict[int, int], int]:
    out = {}
    for a, n in ranges:
        for i in range(n):
            out[a + i] = data[at + i]
        at += n
    return out, at


def calls(cap: Capture) -> List[AmCall]:
    out = []
    am = am_state_ranges()
    for k, c in enumerate(cap.index['calls']):
        mi = bytes.fromhex(''.join(c['in']))
        mo_ = bytes.fromhex(''.join(c['out'] or []))
        if c['routine'].endswith('AM_Responder'):
            ev = mi[:4]
            st_in, at = _state_map(am, mi, 4)
            gm = int.from_bytes(mi[at:at + 2], 'little')
            mo = mi[at + 2:at + 14]
            msg_in = mi[at + 14:at + 18]
            st_out, at2 = _state_map(am, mo_)
            msg_out = mo_[at2:at2 + 4]
            out.append(AmCall(k, 'responder', c['cycles'], st_in, st_out,
                              (int.from_bytes(ev[:2], 'little'),
                               int.from_bytes(ev[2:4], 'little')), mo, gm,
                              msg_in, msg_out, c['a_out'] & 0xFFFF))
        else:
            st_in, at = _state_map(am, mi)
            st_out, _ = _state_map(am, mo_)
            out.append(AmCall(k, 'ticker', c['cycles'], st_in, st_out,
                              (0, 0), mi[at:at + 12], 0, b'', b'', None))
    return out


def frames(cap: Capture) -> List[Frame]:
    """The full-map frames with the calls since the frame before (in the
    same stretch of full-map frames)."""
    fr = cap.frames()
    cl = calls(cap)
    out = []
    chain = 0
    last_cycles = None
    for k, f in enumerate(fr):
        E = f['E']
        lo = last_cycles if last_cycles is not None else -1
        between = [c for c in cl if lo < c.cycles < E.cycles]
        if k and any(c.routine == 'responder' and
                     c.state_in.get(amsym('automapmode')) is not None and
                     _word(c.state_in, amsym('automapmode')) & 3 !=
                     AM_ACTIVE for c in between):
            chain += 1          # (left the full map in between)
        tics = sum(1 for c in between if c.routine == 'ticker')
        ev = tuple(c.event for c in between if c.routine == 'responder')
        out.append(Frame(k, f['P'], E, f['R'], f['F'], tics if k else 0,
                         ev if k else (), chain))
        last_cycles = f['R'].cycles
    return out


def _word(m: Dict[int, int], a: int, n: int = 2) -> int:
    return int.from_bytes(bytes(m[a + i] for i in range(n)), 'little')


# ---------------------------------------------------------------------------
# The native forms: the level, the state block, the old list
# ---------------------------------------------------------------------------

def sext8(v: int) -> int:
    return v - 0x100 if v & 0x80 else v


class LevelData(NamedTuple):
    lvg0: bytes
    lnsecf: bytes
    lnsecb: bytes
    oldsp: bytes                # a byte a sector
    lnmap: bytes
    sectors: bytes              # LVMAP's records, floor and ceiling only
    unfit: List[str]


def level_of(E: Ref, lv: Level, fill: int) -> LevelData:
    """The level's native records from upstream's arrays at AM_Drawer's
    entry (llayout's LINE, LVS's LNSECF/LNSECB, SECG's OLDSPECIAL, rlayout's
    SEC; LNMAP from r_flags' ML_MAPPED)."""
    lines = E.get(lv.lines, lv.nlines * SIZEOF_LINE)
    sides = E.get(lv.sides, lv.nsides * SIZEOF_SIDE)
    secs = E.get(lv.sectors, lv.nsectors * SIZEOF_SEC)
    unfit = []

    def secnum(side: int) -> int:
        ptr = int.from_bytes(sides[side * SIZEOF_SIDE + OFS_SIDE_SECTOR:
                                   side * SIZEOF_SIDE + 4], 'little') & \
            0xFFFFFF
        k, r = divmod(ptr - lv.sectors, SIZEOF_SEC)
        if r or not 0 <= k < lv.nsectors:
            raise AmError('side %d: sector pointer $%06X' % (side, ptr))
        return k
    lvg0 = bytearray()
    lnsecf = bytearray()
    lnsecb = bytearray()
    lnmap = bytearray(LL.LNMAP_END - LL.LNMAP)
    for i in range(lv.nlines):
        ln = lines[i * SIZEOF_LINE:(i + 1) * SIZEOF_LINE]
        rec = bytearray([fill]) * LL.LINE_SIZE
        L = LL.LINE
        rec[L['V1X']:L['V1X'] + 8] = ln[0:8]
        rec[L['DX']:L['DX'] + 4] = ln[8:12]
        rec[L['SIDE0']:L['SIDE0'] + 4] = ln[12:16]
        rec[L['TOP']:L['TOP'] + 8] = ln[16:24]
        tag = int.from_bytes(ln[24:26], 'little')
        special = int.from_bytes(ln[34:36], 'little')
        if sext8(special & 0xFF) & 0xFFFF != special:
            unfit.append('line %d: special $%04X' % (i, special))
        rec[L['TAG']] = tag & 0xFF
        rec[L['SPECIAL']] = special & 0xFF
        rec[L['FLAGS']] = ln[26]
        rec[L['SLOPE']] = ln[27]
        rec[L['VALID']:L['VALID'] + 2] = ln[28:30]
        rec[L['RVALID']:L['RVALID'] + 2] = ln[30:32]
        lvg0 += rec
        s0 = int.from_bytes(ln[12:14], 'little')
        s1 = int.from_bytes(ln[14:16], 'little')
        f = secnum(s0)
        lnsecf.append(f)
        lnsecb.append(f if s1 == 0xFFFF else secnum(s1))
        if int.from_bytes(ln[32:34], 'little') & ML_MAPPED:
            lnmap[i >> 3] |= 1 << (i & 7)
    oldsp = bytearray()
    sectors = bytearray([fill]) * (R.SEC_SIZE * lv.nsectors)
    for k in range(lv.nsectors):
        sc = secs[k * SIZEOF_SEC:(k + 1) * SIZEOF_SEC]
        o = int.from_bytes(sc[OFS_SEC['OLDSPECIAL']:
                              OFS_SEC['OLDSPECIAL'] + 2], 'little')
        if o > 0xFF:
            unfit.append('sector %d: oldspecial %d' % (k, o))
        oldsp.append(o & 0xFF)
        at = k * R.SEC_SIZE
        sectors[at + R.SEC['FLOOR']:at + R.SEC['FLOOR'] + 4] = sc[0:4]
        sectors[at + R.SEC['CEIL']:at + R.SEC['CEIL'] + 4] = sc[4:8]
    return LevelData(bytes(lvg0), bytes(lnsecf), bytes(lnsecb),
                     bytes(oldsp), bytes(lnmap), bytes(sectors), unfit)


def static_key(d: LevelData) -> bytes:
    """What a run holds once, which the frames of a run must agree on: the
    lines' fields the automap reads (the ends, the sides, the special, the
    flags; not the game's validcounts), their sectors, the oldspecials."""
    L = LL.LINE
    out = bytearray()
    for i in range(0, len(d.lvg0), LL.LINE_SIZE):
        r = d.lvg0[i:i + LL.LINE_SIZE]
        out += r[L['V1X']:L['V1X'] + 8] + r[L['SIDE0']:L['SIDE0'] + 4] + \
            r[L['SPECIAL']:L['FLAGS'] + 1]
    return bytes(out) + d.lnsecf + d.lnsecb + d.oldsp


def math_records() -> List[Tuple[int, int, int, bytes]]:
    """The math's RamWorks tables as the boot leaves them (src/native/
    MATH.md): MT_TBANK the sines, tantoangle and the quarter sine, MT_RLO
    and MT_RHI the reciprocals."""
    m = BUILD / 'native' / 'render' / 'tables' / 'math'
    t = R.MT_TBANK
    recs = [(1, t, 0x2000, (m / 'sinelo.bin').read_bytes()),
            (1, t, 0x4000, (m / 'sinehi.bin').read_bytes())]
    for k in range(4):
        recs.append((1, t, 0x6000 + 256 * 9 * k,
                     (m / ('tanto%d.bin' % k)).read_bytes()))
    recs += [(1, t, 0x8400, (m / 'quartlo.bin').read_bytes()),
             (1, t, 0x8C00, (m / 'quarthi.bin').read_bytes()),
             (1, R.MT_RLO, 0x2000, (m / 'reciplo.bin').read_bytes()),
             (1, R.MT_RHI, 0x2000, (m / 'reciphi.bin').read_bytes())]
    return recs


def level_records(d: LevelData, nibtab: bytes, nlines: int
                  ) -> List[Tuple[int, int, int, bytes]]:
    return [(1, LL.LVG0, LL.LINES.base, d.lvg0),
            (1, LL.LVS, LL.LVS_LNSECF, d.lnsecf),
            (1, LL.LVS, LL.LVS_LNSECB, d.lnsecb),
            (0, 0, LL.LVCOUNT2, struct.pack('<H', nlines)),
            (1, S.S2PAL, S.S2PAL_AT['S2P_NIB'], nibtab)] + \
        [(1, LL.LVG1, LL.SECGS.base + LL.SECG_SIZE * k +
          LL.SECG['OLDSPECIAL'], bytes([v])) for k, v in enumerate(d.oldsp)]


def state_fields() -> List[Tuple[str, int, str, int]]:
    """(upstream's label, size, encoding, the native place) of AMAPW's
    state block (the field map's), then this part's native ones."""
    sp = state_places()
    out = []
    for f in S.field_map():
        if f.screen == 'automap' and f.kind == 'state':
            out.append((f.ref.split(':', 1)[1], f.size, f.enc,
                        sp[f.place]))
    return out


def encode_state(st: Dict[int, int], fill: int, old_entries: int,
                 ob: Sequence[int]) -> bytes:
    """The native state block (its first ST_END - AMST bytes) from
    upstream's automap state."""
    sp = state_places()
    base = S.OWN_STATE['AMAPW'][1]
    end = sp['A_OB'] + 8
    blk = bytearray([fill]) * (end - base)
    for name, size, enc, place in state_fields():
        a = amsym(name)
        blk[place - base:place - base + size] = bytes(
            st[a + i] for i in range(size))
    blk[sp['A_MODE'] - base] = st[amsym('AM_MODE')]
    blk[sp['A_OLDTOP'] - base] = st[amsym('AM_OLDTOP')]
    blk[sp['A_ON'] - base:sp['A_ON'] - base + 2] = struct.pack(
        '<H', old_entries)
    blk[sp['A_OB'] - base:sp['A_OB'] - base + 8] = struct.pack('<4H', *ob)
    return bytes(blk)


def decode_state(blk: bytes) -> Dict[str, int]:
    """The native block's fields by upstream's names (and AM_MODE,
    AM_OLDTOP, AM_ON as entries)."""
    sp = state_places()
    base = S.OWN_STATE['AMAPW'][1]
    out = {}
    for name, size, enc, place in state_fields():
        out[name] = int.from_bytes(blk[place - base:place - base + size],
                                   'little')
    out['AM_MODE'] = blk[sp['A_MODE'] - base]
    out['AM_OLDTOP'] = blk[sp['A_OLDTOP'] - base]
    out['AM_ON'] = int.from_bytes(blk[sp['A_ON'] - base:
                                      sp['A_ON'] - base + 2], 'little')
    return out


def upstream_fields(st: Dict[int, int]) -> Dict[str, int]:
    out = {}
    for name, size, enc, place in state_fields():
        out[name] = _word(st, amsym(name), size)
    out['AM_MODE'] = st[amsym('AM_MODE')]
    out['AM_OLDTOP'] = st[amsym('AM_OLDTOP')]
    return out


def ref_state(d: Ref) -> Dict[int, int]:
    out = {}
    for a, n in am_state_ranges():
        data = d.get(a, n)
        for i in range(n):
            out[a + i] = data[i]
    return out


def upstream_list(d: Ref, which: str) -> List[int]:
    """The old list (at AM_Drawer's entry: the half not at AM_LB) or the
    new one (at its return: the half not at AM_LB, after the swap), as
    screen addresses ($2000 + row * 160 + byte)."""
    lb = d.sym('am_map65.s:AM_LB')
    n = d.sym('am_map65.s:AM_ON')
    data = d.get(amsym('AM_LISTS') + (lb ^ (2 * AM_LMAX)), n)
    return [int.from_bytes(data[i:i + 2], 'little') for i in range(0, n, 2)]


def native_list(entries: Sequence[int]) -> Tuple[List[int], List[int]]:
    """A list in the native order: by band, upstream's order inside one;
    and the bands' first entries."""
    if len(entries) > LIST_ENTRIES:
        raise AmError('a list of %d entries (the native one holds %d)'
                      % (len(entries), LIST_ENTRIES))
    out: List[int] = []
    ob = []
    for k in range(BANDS):
        ob.append(len(out))
        lo = S.SHR + k * BAND_ROWS * S.ROW_BYTES
        hi = lo + BAND_ROWS * S.ROW_BYTES
        out += [e for e in entries if lo <= e < hi]
    if len(out) != len(entries):
        raise AmError('a list entry outside the view\'s rows')
    return out, ob


def msg_native(ptr4: bytes) -> bytes:
    """player.message: upstream's pointer as milestone 10's reference (tag
    1, the symbol's id, offset 0), or NULL."""
    ptr = int.from_bytes(ptr4[:3], 'little')
    if ptr == 0:
        return bytes(5)
    ids = message_ids()
    if ptr == amsym('msgFollowOn'):
        ident = ids['on']
    elif ptr == amsym('msgFollowOff'):
        ident = ids['off']
    else:
        from native import s2msgs
        names = s2msgs.by_address()
        if ptr not in names:
            raise AmError('player.message $%06X is no symbol' % ptr)
        ident = {s: k for k, s in enumerate(LL.symbol_list())}[names[ptr]]
    return bytes([1, ident & 0xFF, ident >> 8, 0, 0])


def rthing(mo: bytes, fill: int) -> bytes:
    """The player's RTHING (slot 0) from upstream's x, y and angle."""
    rec = bytearray([fill]) * R.RTHING_SIZE
    rec[R.RTHING['X']:R.RTHING['X'] + 4] = mo[0:4]
    rec[R.RTHING['Y']:R.RTHING['Y'] + 4] = mo[4:8]
    rec[R.RTHING['ANG']:R.RTHING['ANG'] + 2] = mo[10:12]
    rec[LL.TH_ANGLO:LL.TH_ANGLO + 2] = mo[8:10]
    return bytes(rec)


def player_block(allmap: int, msg: bytes, fill: int) -> bytes:
    po = player_offsets()
    size = dict(LL.GLOBAL_FIELDS)['G_PLAYER']
    blk = bytearray([fill]) * size
    blk[po['mo']:po['mo'] + 2] = bytes(2)            # the mobj: slot 0
    blk[po['allmap']:po['allmap'] + 2] = struct.pack('<H', allmap & 0xFFFF)
    blk[po['message']:po['message'] + 5] = msg
    return bytes(blk)


# ---------------------------------------------------------------------------
# The stage: the glue's directory and cases (src/native/s2_amt.s)
# ---------------------------------------------------------------------------

T_DIR, T_RES = 76, 75
STAGE_BANKS = tuple(range(77, 93)) + tuple(range(8, 50))
CALL_SLOT = 0x300
K_MAIN, K_AUX, K_CARD = 0, 1, 2
CALL_FRAME, CALL_RESP, CALL_TICK = 0, 1, 2
CASE_HEAD = 0x100
MAX_EVENTS = 19
MAX_COPIES = 24


class Case(NamedTuple):
    copies: Tuple[Tuple[int, int, int, bytes], ...]  # (kind, bank, addr, data)
    events: Tuple[Tuple[int, int], ...]
    call: Tuple[int, int, int, int]                  # kind, A, X, Y


def case_bytes(c: Case) -> bytes:
    if len(c.copies) > MAX_COPIES or len(c.events) > MAX_EVENTS:
        raise AmError('a case of %d copies, %d events' % (len(c.copies),
                                                          len(c.events)))
    head = bytearray(CASE_HEAD)
    head[0] = len(c.copies)
    head[1] = len(c.events)
    head[2:6] = bytes(c.call)
    for e, (t, key) in enumerate(c.events):
        head[6 + 3 * e:9 + 3 * e] = bytes([t, key & 0xFF, key >> 8])
    data = bytearray()
    for i, (kind, bank, addr, blob) in enumerate(c.copies):
        off = CASE_HEAD + len(data)
        head[0x40 + 8 * i:0x48 + 8 * i] = struct.pack(
            '<BBHHH', kind, bank, addr, len(blob), off)
        data += blob
    return bytes(head + data)


def stage_records(cases: Sequence[Case], per_bank: Optional[int] = None
                  ) -> List[Tuple[int, int, int, bytes]]:
    """The cases in the stage banks (one a bank, or `per_bank` slots of
    CALL_SLOT bytes) and the directory."""
    banks: Dict[int, bytearray] = {}
    entries = []
    for k, c in enumerate(cases):
        blob = case_bytes(c)
        if per_bank is None:
            bank, at = STAGE_BANKS[k], 0x0200
            if 0x0200 + len(blob) > 0xC000:
                raise AmError('a case of %d bytes' % len(blob))
        else:
            if len(blob) > CALL_SLOT:
                raise AmError('a call case of %d bytes' % len(blob))
            j, r = divmod(k, per_bank)
            bank, at = STAGE_BANKS[j], 0x0200 + r * CALL_SLOT
        data = banks.setdefault(bank, bytearray(0xC000 - 0x0200))
        data[at - 0x0200:at - 0x0200 + len(blob)] = blob
        entries.append((bank, at))
    direc = bytearray([len(cases)])
    for bank, at in entries:
        direc += bytes([bank, at & 0xFF, at >> 8])
    return [(1, b, 0x0200, bytes(d)) for b, d in sorted(banks.items())] + \
        [(1, T_DIR, 0x0200, bytes(direc))]


def frame_case(fr: Frame, d: LevelData, fill: int, poison: bool,
               chained: bool, first: bool,
               carry: Optional[Tuple[bytes, bytes, bytes]] = None
               ) -> Tuple[Case, bytes]:
    """A frame's case and the screen it starts from (aux 0 $2000-$9FFF)."""
    E = fr.E
    copies: List[Tuple[int, int, int, bytes]] = []
    pl = E.get(sym('g_game65.s:_g_player'), SIZEOF_PL)
    allmap = int.from_bytes(pl[OFS_PL_POWERS + 2 * PW_ALLMAP:
                               OFS_PL_POWERS + 2 * PW_ALLMAP + 2], 'little')
    msg = msg_native(pl[OFS_PL_MESSAGE:OFS_PL_MESSAGE + 4])
    copies.append((K_MAIN, 0, LL.G['G_PLAYER'], player_block(allmap, msg,
                                                              fill)))
    copies.append((K_MAIN, 0, LL.LNMAP, d.lnmap))
    copies.append((K_MAIN, 0, LL.G['G_GAMEMAP'],
                   E.get(sym('g_game65.s:_g_gamemap'), 2)))
    copies.append((K_MAIN, 0, LL.G['G_MENUACTIVE'],
                   E.get(sym('m_menu65.s:_g_menuactive'), 2)))
    hu_on = E.sym('hu_stuff65.s:message_on')
    hu_new = E.sym('hu_stuff65.s:message_new')
    if hu_on > 1 or hu_new > 1:
        raise AmError('frame %d: message_on %d, message_new %d' % (
            fr.k, hu_on, hu_new))
    gen = s2inc()
    copies.append((K_CARD, 0, gen['HU_ON'], bytes([hu_on])))
    copies.append((K_CARD, 0, gen['HU_NEW'], bytes([hu_new])))
    copies.append((K_CARD, 0, gen['S2_MAIL'], bytes(1)))
    mo = E.get(_mo_addr(E) + OFS_MO['X'], 8) + \
        E.get(_mo_addr(E) + OFS_MO['ANGLE'], 4)
    copies.append((K_AUX, R.RTH, R.RTHINGS.base, rthing(mo, fill)))
    copies.append((K_AUX, R.LVMAP, R.SECTORS.base, d.sectors))
    palst = bytearray([fill]) * S.PALST_SIZE
    pp = S.palst_places()
    P = fr.P                    # (before display's I_ViewPalette)
    palst[pp['PS_SCB']:pp['PS_SCB'] + 200] = P.sym_bytes(
        'i_viigs65.s:scb', 200)
    palst[pp['PS_VIEWPAL']] = P.sym('i_viigs65.s:viewpal') & 0xFF
    copies.append((K_AUX, S.S2STATE, S.SS['SS_PALST'], bytes(palst)))
    screen = bytearray(E.get(*_screen()))
    if chained and first and carry is not None:
        blk, old, screen_ = carry      # a chain goes on: the native state
        copies.append((K_AUX, S.S2STATE, S.SS['SS_AMAPW'], blk))
        copies.append((K_AUX, S.S2STATE, S.SS['SS_AMOLD'], old))
        copies.append((K_AUX, 0, S.SHR, screen_))
        screen = bytearray(screen_)
    elif not chained or first:
        st = ref_state(E)
        old = upstream_list(E, 'old')
        nat, ob = native_list(old)
        copies.append((K_AUX, S.S2STATE, S.SS['SS_AMAPW'],
                       encode_state(st, fill, len(nat), ob)))
        copies.append((K_AUX, S.S2STATE, S.SS['SS_AMOLD'],
                       b''.join(struct.pack('<H', e) for e in nat) or
                       bytes(2)))
        if poison:
            for o in changed_bytes(fr):
                screen[o] = fill
        copies.append((K_AUX, 0, S.SHR, bytes(screen)))
    goes_on = chained and (not first or carry is not None)
    return (Case(tuple(copies), fr.events if goes_on else (),
                 (CALL_FRAME, fr.tics if goes_on else 0, 0, 0)),
            bytes(screen))


def _screen() -> Tuple[int, int]:
    from native import s2cap as C
    return C.SCREEN


def _mo_addr(E: Ref) -> int:
    return int.from_bytes(E.get(sym('g_game65.s:_g_player') + OFS_PL_MO,
                                3), 'little')


def redraws(fr: Frame) -> Tuple[bool, bool]:
    """(upstream redraws all, upstream clears the strip) in the frame, by
    AM_Drawer's rules at its entry [R am_map65.s:1059-1074]."""
    E = fr.E
    wtop = STRIP_ROWS if E.sym('hu_stuff65.s:message_on') else 0
    redraw = not E.sym('am_map65.s:am_valid') or \
        wtop != E.sym('am_map65.s:AM_OLDTOP') or \
        bool(E.sym('m_menu65.s:_g_menuactive'))
    strip = not redraw and bool(E.sym('hu_stuff65.s:message_new'))
    return redraw, strip


def wtop_of(fr: Frame) -> int:
    return STRIP_ROWS if fr.E.sym('hu_stuff65.s:message_on') else 0


def published(fr: Frame) -> int:
    """The screen bytes the frame publishes (upstream's count, which the
    native bands keep): all view rows when it redraws, else the old and
    the new lists' entries and the strip when it clears it."""
    redraw, strip = redraws(fr)
    if redraw:
        return F_H * S.ROW_BYTES
    n = len(upstream_list(fr.E, 'old')) + len(upstream_list(fr.R, 'new'))
    return n + (STRIP_ROWS * S.ROW_BYTES if strip else 0)


def changed_bytes(fr: Frame) -> List[int]:
    """The screen offsets (from $2000) upstream's frame writes in the map's
    rows and the rows it blacks: all view rows when it redraws, else the
    old and the new list's bytes and the strip's rows when it clears it."""
    redraw, strip = redraws(fr)
    if redraw:
        return list(range(F_H * S.ROW_BYTES))
    out = set(e - S.SHR for e in upstream_list(fr.E, 'old'))
    out |= set(e - S.SHR for e in upstream_list(fr.R, 'new'))
    if strip:
        out |= set(range(STRIP_ROWS * S.ROW_BYTES))
    return sorted(out)
# ---------------------------------------------------------------------------
# A host model of upstream's full-map drawing (am_map65.s, read as the
# rest of this part): the debugging aid and the second opinion of the
# reference's lists (the model's frames equal ref816's: --model)
# ---------------------------------------------------------------------------

_TABLES: Dict[str, List[int]] = {}


def model_tables() -> Dict[str, List[int]]:
    if not _TABLES:
        m = BUILD / 'native' / 'render' / 'tables' / 'math'
        lo, hi = (m / 'reciplo.bin').read_bytes(), \
            (m / 'reciphi.bin').read_bytes()
        _TABLES['recip'] = [lo[i] | hi[i] << 8 for i in range(len(lo))]
        lo, hi = (m / 'quartlo.bin').read_bytes(), \
            (m / 'quarthi.bin').read_bytes()
        _TABLES['quarter'] = [lo[i] | hi[i] << 8 for i in range(len(lo))]
    return _TABLES


def _s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def _s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class Model:
    """drawWalls, drawPlayers, the clip and drawFL of upstream on a host
    copy of the screen, from a frame's AM_Drawer entry."""

    def __init__(self, fr: Frame, lv: Level):
        from native import mathdefs as MD
        self.MD = MD
        self.t = model_tables()
        E = fr.E
        self.E = E
        self.st = upstream_fields(ref_state(E))
        self.lines = E.get(lv.lines, lv.nlines * SIZEOF_LINE)
        self.sides = E.get(lv.sides, lv.nsides * SIZEOF_SIDE)
        self.secs = E.get(lv.sectors, lv.nsectors * SIZEOF_SEC)
        self.lv = lv
        mo = _mo_addr(E)
        self.mo = E.get(mo, SIZEOF_MO)
        pl = E.get(sym('g_game65.s:_g_player'), SIZEOF_PL)
        self.allmap = int.from_bytes(pl[OFS_PL_POWERS + 2 * PW_ALLMAP:
                                        OFS_PL_POWERS + 2 * PW_ALLMAP + 2],
                                     'little')
        self.rowbase = E.get(sym('i_viigs65.s:iigs_rowbase'), 400)
        self.nib = E.get(amsym('NIBTAB'), 0x4000)
        self.mode = self.st['automapmode']
        self.segs: List[Tuple[int, int, int, int, int]] = []

    def mtof(self, v):
        return _s16(self.MD.m_fixmul(v, self.st['scale_mtof']) >> 16)

    def to_screen(self, x, y):
        return (self.mtof(x - _s32(self.st['m_x'])) & 0xFFFF,
                (F_H - self.mtof(y - _s32(self.st['m_y']))) & 0xFFFF)

    def map_code(self, x, y):
        st = self.st
        c = 0
        if _s32(st['m_y2']) < y:
            c = 8
        elif y < _s32(st['m_y']):
            c = 4
        if x < _s32(st['m_x']):
            return c | 1
        if _s32(st['m_x2']) < x:
            return c | 2
        return c

    @staticmethod
    def outcode(x, y):
        c = 0
        if y & 0x8000:
            c = 8
        elif not (y - F_H) & 0x8000:
            c = 4
        if x & 0x8000:
            return c | 1
        if not (x - F_W) & 0x8000:
            return c | 2
        return c

    def sdiv(self, a, b):
        return self.MD.m_sdiv(a, b, 16)[0]

    def mline(self, ax, ay, bx, by, colour):
        o1 = self.map_code(ax, ay)
        if o1 & self.map_code(bx, by):
            return
        fl = list(self.to_screen(ax, ay) + self.to_screen(bx, by))
        o1 = self.outcode(fl[0], fl[1])
        o2 = self.outcode(fl[2], fl[3])
        if o1 & o2:
            return
        while o1 | o2:
            out = o1 or o2
            if out & 8:
                cl = (fl[1] - fl[3]) & 0xFFFF
                p = (fl[1] * ((fl[2] - fl[0]) & 0xFFFF)) & 0xFFFF
                tx, ty = (self.sdiv(p, cl) + fl[0]) & 0xFFFF, 0
            elif out & 4:
                cl = (fl[1] - fl[3]) & 0xFFFF
                p = (((fl[1] - F_H) & 0xFFFF) *
                     ((fl[2] - fl[0]) & 0xFFFF)) & 0xFFFF
                tx, ty = (self.sdiv(p, cl) + fl[0]) & 0xFFFF, F_H - 1
            elif out & 2:
                cl = (fl[2] - fl[0]) & 0xFFFF
                p = (((F_W - 1 - fl[0]) & 0xFFFF) *
                     ((fl[3] - fl[1]) & 0xFFFF)) & 0xFFFF
                tx, ty = F_W - 1, (self.sdiv(p, cl) + fl[1]) & 0xFFFF
            else:
                cl = (fl[2] - fl[0]) & 0xFFFF
                p = (((0 - fl[0]) & 0xFFFF) *
                     ((fl[3] - fl[1]) & 0xFFFF)) & 0xFFFF
                tx, ty = 0, (self.sdiv(p, cl) + fl[1]) & 0xFFFF
            if out == o1:
                fl[0], fl[1] = tx, ty
                o1 = self.outcode(tx, ty)
                if o1 & o2:
                    return
            else:
                fl[2], fl[3] = tx, ty
                o2 = self.outcode(tx, ty)
                if o2 & o1:
                    return
        self.segs.append((fl[0], fl[1], fl[2], fl[3], colour))

    def sector(self, side):
        ptr = int.from_bytes(self.sides[side * SIZEOF_SIDE:
                                        side * SIZEOF_SIDE + 3], 'little')
        k = (ptr - self.lv.sectors) // SIZEOF_SEC
        return self.secs[k * SIZEOF_SEC:(k + 1) * SIZEOF_SEC]

    def walls(self):
        if self.mode & AM_ROTATE:
            raise AmError('the model draws the full map only')
        doors = door_colours()
        for i in range(self.lv.nlines):
            ln = self.lines[i * SIZEOF_LINE:(i + 1) * SIZEOF_LINE]
            w = lambda o: int.from_bytes(ln[o:o + 2], 'little')
            flags = w(26)
            if not w(32) & ML_MAPPED:
                if not self.allmap or flags & 128:
                    continue
                colour = 104
            else:
                if flags & 128:
                    continue
                colour = None
                s1 = w(14)
                if flags & 32:
                    colour = 23 if s1 != 0xFFFF else None
                    one = s1 == 0xFFFF
                else:
                    sp = w(34)
                    if (sp - 26) & 0xFFFF < 9 and doors[sp - 26]:
                        colour = doors[sp - 26]
                    one = s1 == 0xFFFF
                    if colour is None and not one:
                        if sp == 97:
                            colour = 119
                        else:
                            f, b = self.sector(w(12)), self.sector(s1)
                            fh = lambda s: s[0:4]
                            ch = lambda s: s[4:8]
                            os_ = lambda s: int.from_bytes(s[52:54],
                                                           'little')
                            if fh(b) == ch(b) or fh(f) == ch(f):
                                colour = 208
                            elif os_(f) == 9 or os_(b) == 9:
                                colour = 252
                            elif fh(b) != fh(f):
                                colour = 55
                            elif ch(b) != ch(f):
                                colour = 215
                            else:
                                continue
                if colour is None and one:
                    s = self.sector(w(12))
                    colour = 252 if int.from_bytes(s[52:54], 'little') \
                        == 9 else 23
            pts = [_s16(w(o)) << 12 for o in (0, 2, 4, 6)]
            self.mline(pts[0], pts[1], pts[2], pts[3], colour)

    def players(self):
        MD, q = self.MD, self.t['quarter']
        mo = self.mo
        x = _s32(int.from_bytes(mo[OFS_MO['X']:OFS_MO['X'] + 4],
                                'little')) >> 4
        y = _s32(int.from_bytes(mo[OFS_MO['Y']:OFS_MO['Y'] + 4],
                                'little')) >> 4
        ang = int.from_bytes(mo[OFS_MO['ANGLE']:OFS_MO['ANGLE'] + 4],
                             'little')
        turn = ang != 0
        fine = (ang >> 16) >> 3
        c = MD.m_cosineapprox(fine, q)
        sn = MD.m_sineapprox(fine, q)
        arrow = player_arrow()
        for k in range(7):
            p = arrow[4 * k:4 * k + 4]
            out = []
            for j in (0, 2):
                px, py = p[j], p[j + 1]
                if turn:
                    nx = _s32(MD.m_fixmulang(px, c)) - \
                        _s32(MD.m_fixmulang(py, sn))
                    ny = _s32(MD.m_fixmulang(px, sn)) + \
                        _s32(MD.m_fixmulang(py, c))
                    px, py = _s32(nx), _s32(ny)
                out += [_s32(px + x), _s32(py + y)]
            self.mline(out[0], out[1], out[2], out[3], 208)

    def segments(self) -> List[Tuple[int, int, int, int, int]]:
        self.segs = []
        self.walls()
        self.players()
        return self.segs

    def draw(self, screen: bytearray, wtop: int) -> List[int]:
        """The segments' pixels into the screen (the rows wtop .. 159), the
        list of the bytes (upstream's: once after the entry before)."""
        lst: List[int] = []
        last = None
        for x0, y0, x1, y1, colour in self.segs:
            dx = _s16(x1 - x0)
            sx = 1 if dx > 0 else -1
            dx = abs(dx)
            dy = _s16(y1 - y0)
            sy = 1 if dy > 0 else -1
            dy = -abs(dy)
            err2 = 2 * dx + 2 * dy
            x, y = _s16(x0), _s16(y0)

            def plot():
                nonlocal last
                if not wtop <= y < AM_TITLEY:
                    return
                rb = int.from_bytes(self.rowbase[2 * y:2 * y + 2],
                                    'little')
                o = y * S.ROW_BYTES + (x >> 1)
                if x & 1:
                    v = screen[o] & 0xF0 | self.nib[rb + colour + 0x200]
                else:
                    v = screen[o] & 0x0F | self.nib[rb + colour]
                screen[o] = v
                e = S.SHR + o
                if e != last:
                    last = e
                    lst.append(e)
            if dx + dy >= 0:
                for n in range(dx + 1):
                    plot()
                    if n == dx:
                        break
                    x += sx
                    if _s16(err2 - dx) <= 0:
                        err2 += 2 * dx + 2 * dy
                        y += sy
                    else:
                        err2 += 2 * dy
            else:
                for n in range(-dy + 1):
                    plot()
                    if n == -dy:
                        break
                    if _s16(err2 - dy) >= 0:
                        err2 += 2 * dx + 2 * dy
                        x += sx
                    else:
                        err2 += 2 * dx
                    y += sy
        return lst


# ---------------------------------------------------------------------------
# The build and the machine
# ---------------------------------------------------------------------------

def make(m11: Path = M11, source: Path = SOURCE) -> None:
    from native import s2run as SR
    SR.make('s2amap', m11, source)


def build_of(obj: Path = OUT):
    from native import s2run as SR
    if not (obj / 's2at.map').exists():
        raise AmError('%s is missing: make -C src/native -f m11.mk part '
                      'P=s2amap' % (obj / 's2at.map'))
    return SR.load_build(obj, 's2at', 'AMAPW')


def module_pcs(b) -> Dict[str, Tuple[int, int]]:
    from native import s2drawcase as DC
    return DC.module_pcs(b)


W_RUNTIME = (S.IMAGE['AMAPW'].runtime[0][0], 0xC000)    # $8E00-$BFFF


def owners(b, loads) -> List[Any]:
    """The writers of a run of s2at and what each may write."""
    from native import s2run as SR
    pcs = module_pcs(b)
    lab = b.labels
    gen = s2inc()
    data = b.segments['S2DATA']
    fa = ('main', 0, 0x0000, 0x0006)
    amz = ('main', 0, 0x80, 0xB0)
    s2zp = ('main', 0, 0x48, 0x78)
    mzp = ('main', 0, 0xB0, 0xD8)
    wrt = ('main', 0) + W_RUNTIME
    dat = ('main', 0, data[0], data[1] + 1)
    pixels = ('aux', 0, S.SHR, S.SCB)
    screen = ('aux', 0, S.SHR, S.SCREEN_END)
    ss = ('aux', S.S2STATE, LL.ROOM[0], LL.ROOM[1])
    hu_new = ('lc', 0, gen['HU_NEW'], gen['HU_NEW'] + 1)
    mail = ('lc', 0, gen['S2_MAIL'], gen['S2_MAIL'] + 1)
    fauto = ('main', 0, R.FRAME['AUTOMAP'], R.FRAME['AUTOMAP'] + 1)
    plmsg = ('main', 0, LL.G['G_PLAYER'] + player_offsets()['message'],
             LL.G['G_PLAYER'] + player_offsets()['message'] + 5)
    phase = ('main', 0, R.PHASE, R.PHASE + 2)
    status = ('main', 0, S.PL_STATUS, S.PL_STATUS + 1)
    begun = lab['s2_begun']
    # the glue's places: every stage copy's (main, the card, the banks)
    stage = (('main', 0, 0x0200, 0xC000), ('lc', 0, 0xC000, 0x10000),
             ('aux', 0, 0, 0x10000), ('aux', R.RTH, 0, 0x10000),
             ('aux', R.LVMAP, 0, 0x10000), ('aux', S.S2STATE, 0, 0x10000),
             ('aux', T_RES, 0, 0x10000))
    io_window = frozenset({0xC002, 0xC003, 0xC004, 0xC005, 0xC073})
    mf = b.segments.get('MATHFAR')
    math_pcs = tuple(b.segments[x] for x in ('MATHW', 'MATHLC', 'MATHFAR')
                     if x in b.segments)
    return [
        SR.driver_owner(b), SR.loader_owner(b, loads),
        SR.Owner('the far layer', (b.segments['RFAR'],),
                 (fa, amz, wrt, dat) + stage + (ss, screen),
                 io_window),
        SR.Owner('the math', math_pcs,
                 (mzp,) + ((('lc1', 0, mf[0], mf[1] + 1),) if mf else ()),
                 frozenset({0xC002, 0xC003, 0xC073})),
        SR.Owner('the test glue', (pcs['s2_amt'],),
                 (fa, phase, dat, wrt), frozenset()),
        SR.Owner('s2_am', (pcs['s2_am'],),
                 (fa, amz, mzp, s2zp, wrt, dat, hu_new, mail, plmsg, fauto,
                  pixels, status, ('main', 0, begun, begun + 1)),
                 frozenset({0xC004, 0xC005})),
        SR.Owner('s2_amline', (pcs['s2_amline'],),
                 (fa, amz, mzp, wrt, fauto), frozenset()),
        SR.Owner('s2_pub', (pcs['s2_pub'],),
                 (s2zp, pixels, wrt, ('main', 0, begun, begun + 1)),
                 frozenset({0xC004, 0xC005})),
    ]


def write_log_ranges() -> str:
    """Every CPU write but the stack page, the automap's and the math's zero
    page ($80-$D7: thousands a line) and AMAPW's runtime W (the band, the
    marks and caches, the state block, the new list: the image's own,
    judged on the snapshots)."""
    return ('main:0000-007F,main:00D8-00FF,main:0200-8DFF,lc,lc1,aux0-127,'
            'cpu:C000-C0FF')


def snap_ranges() -> str:
    gen = s2inc()
    st = S.OWN_STATE['AMAPW'][1]
    return ','.join([
        'aux0:2000-9FFF',
        'main:%04X-%04X' % (st, st + 0xFF),
        'aux%d:%04X-%04X' % (S.S2STATE, S.SS['SS_AMAPW'],
                             S.SS['SS_AMAPW'] + 0xFF),
        'aux%d:%04X-%04X' % (S.S2STATE, S.SS['SS_AMOLD'],
                             S.SS['SS_AMOLD'] + S.SS_SIZE['SS_AMOLD'] - 1),
        'lc:%04X-%04X' % (gen['HU_ON'], gen['S2_MAIL']),
        'main:%04X-%04X' % (R.FRAME['AUTOMAP'], R.FRAME['AUTOMAP']),
        'main:%04X-%04X' % (LL.G['G_PLAYER'], LL.G['G_PLAYER'] + 0x93),
        'aux%d:0200-BFFF' % T_RES])


class RunOut(NamedTuple):
    snaps: List[Any]
    writes: int
    stray: int
    stray_list: List[str]
    stack: Optional[int]
    spans: List[Tuple[int, int]]        # each call's (start, end) clocks
    problems: List[str]


def run_cases(b, cases: Sequence[Case], fill: int, statics: Sequence[Any],
              calls_: Sequence[Any], profile: Optional[str] = None,
              per_bank: Optional[int] = None, work_root: Path = OUT,
              tag: str = '') -> RunOut:
    """One a2vm run: the static records, the cases staged, the calls."""
    from native import s2run as SR
    recs = list(math_records()) + list(statics) + \
        stage_records(cases, per_bank)
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tmp-run-', dir=str(work_root)))
    problems: List[str] = []
    try:
        r = SR.run(b, list(calls_), fill, work, extra_records=recs,
                   write_log=False, snap_ranges=snap_ranges(),
                   profile=profile, timeout=900.0,
                   cycles=SR.CYCLE_LIMIT * 4, extra_args=[
                       '--write-log', write_log_ranges(),
                       '--write-log-file', str(work / 'writes.log'),
                       '--write-log-limit', str(SR.WRITE_LOG_LIMIT)])
        if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
            st = r.status()
            return RunOut([], 0, 0, [], None, [], [
                '%s: the run ended %s, status %s' % (
                    tag, r.ended(), 'none' if st is None else
                    '$%02X' % st)])
        snaps = r.calls()
        writes = r.writes()
        n_stray, stray_list = SR.stray(writes, owners(b, r.loads))
        stack = SR.stack_depth(r)
        spans = phase_spans(b, writes)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return RunOut(snaps, len(writes), n_stray, stray_list, stack, spans,
                  problems)


def phase_spans(b, writes) -> List[Tuple[int, int]]:
    """The glue's cost phase 30 spans (PHASE written PHV_2D, then 0) of the
    calls (am_frame, am_tick, am_responder), in clocks."""
    pcs = module_pcs(b)
    glue = pcs['s2_amt']
    out = []
    start = None
    for w in writes:
        if w.storage == 'main' and w.offset == R.PHASE and \
                glue[0] <= w.pc <= glue[1]:
            if w.new == 2 * S.PHASE_2D:
                start = w.clock
            elif w.new == 0 and start is not None:
                out.append((start, w.clock))
                start = None
    return out


def ms(profile: str, clocks: int) -> float:
    from a2vm import costs
    return clocks / (costs.parameters(profile)['fabric_mhz'] * 1000.0)


# ---------------------------------------------------------------------------
# The frames' checks
# ---------------------------------------------------------------------------

def expected_after(fr: Frame) -> Dict[str, Any]:
    R_ = fr.R
    st = ref_state(R_)
    redraw, strip = redraws(fr)
    return {'screen': fr.F.get(*_screen()),
            'state': upstream_fields(st),
            'list': set(upstream_list(R_, 'new')),
            'ovf': R_.sym('am_map65.s:AM_OVF'),
            'hu_new': R_.sym('hu_stuff65.s:message_new'),
            'redraw': redraw, 'strip': strip,
            'mode': R_.sym('am_map65.s:automapmode')}


def judge_frame(fr: Frame, before: bytes, m, tag: str,
                redraw: bool = False) -> List[str]:
    """A frame's snapshot against the reference: the map's rows equal; the
    other rows their value before or black where upstream blacks them; the
    colours untouched; the state, the list, the HUD's flag, the mail.
    redraw: the frame redraws all whatever its state said (a view frame
    came between: S2_MAIL's MAIL_AMVIEW)."""
    out = []
    want = expected_after(fr)
    if redraw:
        want['redraw'], want['strip'] = True, False
    got = bytes(m.storage('aux', 0)[S.SHR:S.SCREEN_END])
    wtop = wtop_of(fr)
    rb = S.ROW_BYTES
    region = range(wtop * rb, AM_TITLEY * rb)
    bad = [o for o in region if got[o] != want['screen'][o]]
    if bad:
        o = bad[0]
        out.append('%s: row %d byte %d: $%02X, ref $%02X (%d bytes differ)'
                   % (tag, o // rb, o % rb, got[o], want['screen'][o],
                      len(bad)))
    black = set()
    if want['redraw']:
        black = set(range(0, F_H * rb))
    elif want['strip']:
        black = set(range(0, STRIP_ROWS * rb))
    outside = [o for o in range(len(got)) if not wtop * rb <= o <
               AM_TITLEY * rb and got[o] != before[o] and
               not (o in black and got[o] == 0)]
    if outside:
        o = outside[0]
        out.append('%s: $%04X changed outside the map: $%02X, was $%02X '
                   '(%d bytes)' % (tag, S.SHR + o, got[o], before[o],
                                   len(outside)))
    st = S.OWN_STATE['AMAPW'][1]
    blk = bytes(m.main[st:st + 0x100])
    nat = decode_state(blk)
    for k, v in want['state'].items():
        if nat[k] != v:
            out.append('%s: %s %d, ref %d' % (tag, k, nat[k], v))
            break
    n = nat['AM_ON']
    old = m.storage('aux', S.S2STATE)[S.SS['SS_AMOLD']:
                                       S.SS['SS_AMOLD'] + 2 * n]
    lst = set(int.from_bytes(old[i:i + 2], 'little')
              for i in range(0, 2 * n, 2))
    if not want['ovf'] and n < LIST_ENTRIES and lst != want['list']:
        out.append('%s: the new list: %d bytes not the reference\'s, %d '
                   'of its missing' % (tag, len(lst - want['list']),
                                       len(want['list'] - lst)))
    gen = s2inc()
    hu_new = m.lc[gen['HU_NEW'] - 0xC000]
    if hu_new != want['hu_new']:
        out.append('%s: message_new %d, ref %d' % (tag, hu_new,
                                                   want['hu_new']))
    mail = m.lc[gen['S2_MAIL'] - 0xC000]
    bits = mail_bits()
    exp = (bits['MAIL_AMSTRIP'] if want['redraw'] or want['strip'] else 0) \
        | (bits['MAIL_AMTITLE'] if want['redraw'] else 0)
    if mail != exp:
        out.append('%s: S2_MAIL $%02X, expected $%02X' % (tag, mail, exp))
    if m.main[R.FRAME['AUTOMAP']] != want['mode'] & 0xFF:
        out.append('%s: AUTOMAP $%02X, automapmode $%02X' % (
            tag, m.main[R.FRAME['AUTOMAP']], want['mode']))
    return out


class FrameJob(NamedTuple):
    tag: str
    frames: Tuple[Frame, ...]
    fill: int
    poison: bool
    chained: bool


def run_frame_job(job: FrameJob, b, cap: Capture, profile: Optional[str],
                  carry: Optional[Tuple[bytes, bytes, bytes]] = None
                  ) -> Dict[str, Any]:
    lv = cap.level
    first = job.frames[0]
    d0 = level_of(first.E, lv, job.fill)
    problems = list(d0.unfit)
    key = static_key(d0)
    cases = []
    befores = []
    for i, fr in enumerate(job.frames):
        d = level_of(fr.E, lv, job.fill)
        if static_key(d) != key:
            raise AmError('%s: frame %d\'s level differs from the run\'s'
                          % (job.tag, fr.k))
        c, before = frame_case(fr, d, job.fill, job.poison, job.chained,
                               i == 0, carry)
        cases.append(c)
        befores.append(before)
    nib = first.E.get(amsym('NIBTAB'), 0x4000)
    statics = level_records(d0, nib, lv.nlines)
    from native import s2run as SR
    calls_ = [SR.Call('amt_case', k) for k in range(len(cases))]
    ro = run_cases(b, cases, job.fill, statics, calls_, profile,
                   tag=job.tag)
    problems += ro.problems
    if ro.problems:
        return {'tag': job.tag, 'frames': len(job.frames),
                'problems': problems, 'ms': [], 'stray': 0, 'stack': None,
                'writes': 0}
    if ro.stray:
        problems.append('%s: %d stray writes: %s' % (job.tag, ro.stray,
                                                    ro.stray_list[:3]))
    if len(ro.snaps) != len(cases):
        raise AmError('%s: %d snapshots for %d cases' % (
            job.tag, len(ro.snaps), len(cases)))
    prev = None
    for i, (fr, m) in enumerate(zip(job.frames, ro.snaps)):
        tag = 'automap/f%02d (fill %02X%s%s)' % (
            fr.k, job.fill, ', poisoned' if job.poison else '',
            ', chained' if job.chained else '')
        before = befores[i] if (not job.chained or i == 0) else prev
        problems += judge_frame(fr, before, m, tag)
        prev = bytes(m.storage('aux', 0)[S.SHR:S.SCREEN_END])
    frame_ms = [ms(profile, b_ - a) for a, b_ in ro.spans] if profile \
        else []
    m = ro.snaps[-1]
    st = S.OWN_STATE['AMAPW'][1]
    blk = bytes(m.main[st:st + (state_places()['A_OB'] + 8 - st)])
    ssold = S.SS['SS_AMOLD']
    old = bytes(m.storage('aux', S.S2STATE)[ssold:ssold +
                                             S.SS_SIZE['SS_AMOLD']])
    return {'tag': job.tag, 'frames': len(job.frames), 'problems': problems,
            'carry': (blk, old, prev),
            'ms': frame_ms, 'stray': ro.stray, 'stack': ro.stack,
            'writes': ro.writes,
            'kinds': [('redraw' if redraws(f)[0] else 'strip' if
                       redraws(f)[1] else 'lists') for f in job.frames]}


FRAMES_A_RUN = 8


def frame_jobs(fr: Sequence[Frame]) -> List[FrameJob]:
    jobs = []
    for fill, poison in FILLS:
        for i in range(0, len(fr), FRAMES_A_RUN):
            part = tuple(fr[i:i + FRAMES_A_RUN])
            jobs.append(FrameJob('frames %d-%d %02X' % (part[0].k,
                                                       part[-1].k, fill),
                                 part, fill, poison, False))
    return jobs


def chain_jobs(fr: Sequence[Frame]) -> List[List[FrameJob]]:
    """Each stretch of full-map frames from its first frame's state, the
    native code carrying the rest (across runs too: a run's last state,
    old list and screen start the next)."""
    by_chain: Dict[int, List[Frame]] = {}
    for f in fr:
        by_chain.setdefault(f.chain, []).append(f)
    out = []
    for ch, part in sorted(by_chain.items()):
        runs = []
        for i in range(0, len(part), FRAMES_A_RUN):
            runs.append(FrameJob('chain %d: %d-%d' % (ch, part[i].k, part[
                min(i + FRAMES_A_RUN, len(part)) - 1].k),
                tuple(part[i:i + FRAMES_A_RUN]), 0xA5, False, True))
        out.append(runs)
    return out


def run_chain(runs: Sequence[FrameJob], b, cap: Capture,
              profile: Optional[str]) -> List[Dict[str, Any]]:
    out = []
    carry = None
    for j in runs:
        r = run_frame_job(j, b, cap, profile, carry)
        out.append(r)
        carry = r.get('carry')
        if carry is None:
            break
    return out


def check_mail(b, cap: Capture) -> Dict[str, Any]:
    """S2_MAIL's two inputs on a frame whose map is on the screen (the
    reference's frame 3, its lists only): MAIL_AMVIEW (a view frame came
    between, upstream's display zeroed am_valid and am_band) makes it
    redraw all, with the reference's map; MAIL_AMSTOP (an AM_Stop in the
    tics) stops the automap: nothing drawn, automapmode 0, stopped 1."""
    from native import s2run as SR
    fr = frames(cap)
    f = next(x for x in fr if not any(redraws(x)) and x.k >= 3)
    d = level_of(f.E, cap.level, 0xA5)
    gen = s2inc()
    cases, befores = [], []
    for bit in (mail_bits()['MAIL_AMVIEW'], S.MAIL_AMSTOP):
        c, before = frame_case(f, d, 0xA5, False, False, True)
        copies = tuple(x if x[2] != gen['S2_MAIL'] or x[0] != K_CARD else
                       (K_CARD, 0, gen['S2_MAIL'], bytes([bit]))
                       for x in c.copies)
        cases.append(Case(copies, c.events, c.call))
        befores.append(before)
    statics = level_records(d, f.E.get(amsym('NIBTAB'), 0x4000),
                            cap.level.nlines)
    ro = run_cases(b, cases, 0xA5, statics,
                   [SR.Call('amt_case', k) for k in range(2)], tag='mail')
    problems = list(ro.problems)
    if ro.problems:
        return {'problems': problems}
    if ro.stray:
        problems.append('mail: %d stray writes: %s' % (ro.stray,
                                                      ro.stray_list[:3]))
    problems += judge_frame(f, befores[0], ro.snaps[0],
                            'automap/f%02d with MAIL_AMVIEW' % f.k, True)
    m = ro.snaps[1]
    tag = 'automap/f%02d with MAIL_AMSTOP' % f.k
    got = bytes(m.storage('aux', 0)[S.SHR:S.SCREEN_END])
    if got != befores[1]:
        problems.append('%s: the screen changed' % tag)
    st = S.OWN_STATE['AMAPW'][1]
    nat = decode_state(bytes(m.main[st:st + 0x100]))
    want = upstream_fields(ref_state(f.E))
    want['automapmode'], want['stopped'] = 0, 1
    for k, v in want.items():
        if nat[k] != v:
            problems.append('%s: %s %d, expected %d' % (tag, k, nat[k], v))
    if m.lc[gen['S2_MAIL'] - 0xC000] or m.main[R.FRAME['AUTOMAP']]:
        problems.append('%s: S2_MAIL $%02X, AUTOMAP $%02X' % (
            tag, m.lc[gen['S2_MAIL'] - 0xC000], m.main[R.FRAME['AUTOMAP']]))
    return {'frame': f.k, 'problems': problems}


def check_frames(b, cap: Capture, profile: Optional[str] = None,
                 jobs_n: int = JOBS) -> Dict[str, Any]:
    fr = frames(cap)
    jobs = frame_jobs(fr)
    chains = chain_jobs(fr)
    with ThreadPoolExecutor(max_workers=jobs_n) as ex:
        futs = [ex.submit(run_frame_job, j, b, cap, profile) for j in jobs]
        cfuts = [ex.submit(run_chain, c, b, cap, profile) for c in chains]
        mfut = ex.submit(check_mail, b, cap)
        res = [f.result() for f in futs]
        chained = [r for f in cfuts for r in f.result()]
        mail = mfut.result()
    for r in res + chained:
        r.pop('carry', None)
    return {'jobs': res, 'chained': chained, 'mail': mail,
            'problems': [p for r in res + chained for p in r['problems']] +
            mail['problems']}
# ---------------------------------------------------------------------------
# The calls' checks: AM_Responder and AM_Ticker
# ---------------------------------------------------------------------------

CALLS_A_RUN = 240               # (amt_calls: a byte of cases)
CALLS_A_BANK = (0xC000 - 0x0200) // CALL_SLOT


def call_case(c: AmCall, fill: int, state: Optional[bytes]) -> Case:
    """A call's case: the state block (the reference's at the entry, or
    none when a chain carries it), the mobj, player.message, gamemap."""
    copies: List[Tuple[int, int, int, bytes]] = []
    if state is not None:
        copies.append((K_AUX, S.S2STATE, S.SS['SS_AMAPW'], state))
    copies.append((K_AUX, R.RTH, R.RTHINGS.base, rthing(c.mo, fill)))
    gen = s2inc()
    copies.append((K_CARD, 0, gen['S2_MAIL'], bytes(1)))
    if c.routine == 'responder':
        copies.append((K_MAIN, 0, LL.G['G_PLAYER'],
                       player_block(0, msg_native(c.msg_in), fill)))
        copies.append((K_MAIN, 0, LL.G['G_GAMEMAP'],
                       struct.pack('<H', c.gamemap)))
        t, key = c.event
        return Case(tuple(copies), (), (CALL_RESP, t & 0xFF, key & 0xFF,
                                         key >> 8 & 0xFF))
    return Case(tuple(copies), (), (CALL_TICK, 0, 0, 0))


# the fields AM_Drawer and display own (am_valid, am_band, AM_MODE,
# AM_OLDTOP: the frames compare them); a chain of the calls alone does not
# carry them
DRAWER_FIELDS = ('am_valid', 'am_band', 'AM_MODE', 'AM_OLDTOP')


def judge_call(c: AmCall, res: bytes, tag: str, chained: bool = False
               ) -> List[str]:
    out = []
    n = state_places()['A_OB'] + 8 - S.OWN_STATE['AMAPW'][1]
    nat = decode_state(bytes(res[:n]) + bytes(256 - n))
    want = upstream_fields(c.state_out)
    for k, v in want.items():
        if chained and k in DRAWER_FIELDS:
            continue
        if nat[k] != v:
            out.append('%s: %s $%X, ref $%X' % (tag, k, nat[k], v))
            break
    if c.routine == 'responder':
        if res[n + 5] != c.ret:
            out.append('%s: returned %d, ref %d' % (tag, res[n + 5], c.ret))
        if bytes(res[n:n + 5]) != msg_native(c.msg_out):
            out.append('%s: player.message %s, ref %s' % (
                tag, bytes(res[n:n + 5]).hex(),
                msg_native(c.msg_out).hex()))
    if res[n + 6] != want['automapmode'] & 0xFF:
        out.append('%s: AUTOMAP $%02X, automapmode $%02X' % (
            tag, res[n + 6], want['automapmode']))
    return out


def run_calls(b, cap: Capture, cl: Sequence[AmCall], fill: int,
              chained: bool, profile: Optional[str] = None,
              carry: Optional[bytes] = None) -> Dict[str, Any]:
    """Up to CALLS_A_RUN calls in one run (amt_calls), injected or chained
    (the first call's state, then the native code's)."""
    from native import s2run as SR
    fr0 = frames(cap)[0]
    d0 = level_of(fr0.E, cap.level, fill)
    statics = level_records(d0, fr0.E.get(amsym('NIBTAB'), 0x4000),
                            cap.level.nlines)
    nst = state_places()['A_OB'] + 8 - S.OWN_STATE['AMAPW'][1]
    cases = []
    for i, c in enumerate(cl):
        if chained and i:
            st = None
        elif chained and carry is not None:
            st = carry
        else:
            st = encode_state(c.state_in, fill, 0, (0, 0, 0, 0))
        cases.append(call_case(c, fill, st))
    tag = 'calls %d-%d%s' % (cl[0].k, cl[-1].k, ' chained' if chained
                             else ' %02X' % fill)
    ro = run_cases(b, cases, fill, statics, [SR.Call('amt_calls',
                                                     len(cases))],
                   profile, per_bank=CALLS_A_BANK, tag=tag)
    problems = list(ro.problems)
    if ro.problems:
        return {'tag': tag, 'calls': len(cl), 'problems': problems}
    if ro.stray:
        problems.append('%s: %d stray writes: %s' % (tag, ro.stray,
                                                    ro.stray_list[:3]))
    res = ro.snaps[-1].storage('aux', T_RES)
    last = None
    for k, c in enumerate(cl):
        r = bytes(res[0x0200 + 128 * k:0x0200 + 128 * k + 128])
        problems += judge_call(c, r, 'automap/%s %d (%s)' % (
            c.routine, c.k, 'chained' if chained else 'fill %02X' % fill),
            chained)
        last = r[:nst]
    us: Dict[str, List[float]] = {'responder': [], 'ticker': []}
    if profile:
        for c, (a, b_) in zip(cl, ro.spans):
            us[c.routine].append(ms(profile, b_ - a) * 1000.0)
    return {'tag': tag, 'calls': len(cl), 'problems': problems,
            'stray': ro.stray, 'stack': ro.stack, 'carry': last, 'us': us}


def check_calls(b, cap: Capture, profile: Optional[str] = None,
                jobs_n: int = JOBS) -> Dict[str, Any]:
    cl = calls(cap)
    parts = [cl[i:i + CALLS_A_RUN] for i in range(0, len(cl), CALLS_A_RUN)]
    with ThreadPoolExecutor(max_workers=jobs_n) as ex:
        futs = [ex.submit(run_calls, b, cap, part, fill, False, profile)
                for fill, _ in FILLS for part in parts]
        res = [f.result() for f in futs]
    chained = []
    carry = None
    for part in parts:
        r = run_calls(b, cap, part, 0xA5, True, profile, carry)
        chained.append(r)
        carry = r.get('carry')
        if carry is None:
            break
    for r in res + chained:
        r.pop('carry', None)
    return {'jobs': res, 'chained': chained,
            'problems': [p for r in res + chained for p in r['problems']]}


# ---------------------------------------------------------------------------
# The checkpoint, the model, the sizes, the timing, the planted bugs
# ---------------------------------------------------------------------------

def check_model(cap: Capture) -> List[str]:
    """The host model against the reference on every full-map frame (the
    map's rows and the new list, in upstream's order): the reading of
    am_map65.s the native code follows."""
    out = []
    for f in frames(cap):
        m = Model(f, cap.level)
        m.segments()
        redraw, strip = redraws(f)
        screen = bytearray(f.E.get(*_screen()))
        if redraw:
            screen[0:F_H * S.ROW_BYTES] = bytes(F_H * S.ROW_BYTES)
        else:
            for e in upstream_list(f.E, 'old'):
                screen[e - S.SHR] = 0
            if strip:
                screen[0:STRIP_ROWS * S.ROW_BYTES] = bytes(
                    STRIP_ROWS * S.ROW_BYTES)
        wt = wtop_of(f)
        lst = m.draw(screen, wt)
        want = f.F.get(*_screen())
        lo, hi = wt * S.ROW_BYTES, AM_TITLEY * S.ROW_BYTES
        if screen[lo:hi] != want[lo:hi]:
            out.append('model f%02d: the map\'s rows differ' % f.k)
        if lst != upstream_list(f.R, 'new'):
            out.append('model f%02d: the list differs' % f.k)
    return out


def check(profile: Optional[str] = None, obj: Path = OUT,
          jobs_n: int = JOBS, parts: Sequence[str] = ('frames', 'calls')
          ) -> Dict[str, Any]:
    cap = Capture()
    b = build_of(obj)
    out: Dict[str, Any] = {'profile': profile, 'problems': []}
    if 'frames' in parts:
        fr = check_frames(b, cap, profile, jobs_n)
        out['frames'] = fr
        out['problems'] += fr['problems']
    if 'calls' in parts:
        cr = check_calls(b, cap, profile, jobs_n)
        out['calls'] = cr
        out['problems'] += cr['problems']
    return out


PLANTED = (
    ('the y-major loop\'s step on the wrong axis', 's2_amline.s', (
        ('        clc\n        lda PX\n        adc SXS\n        sta PX\n'
         '        lda PX+1\n        adc SXS+1\n        sta PX+1\n'
         '        bra @step\n',
         '        jsr ystep               ; (planted: the step on y)\n'
         '        bra @step\n'),)),
    ('the clip\'s outcode bits swapped', 's2_amline.s', (
        ('        bpl :+\n        ldy #8\n        bra @x\n',
         '        bpl :+\n        ldy #4                  ; (planted)\n'
         '        bra @x\n'),
        ('        bmi @x\n        ldy #4\n',
         '        bmi @x\n        ldy #8                  ; (planted)\n'))),
    ('the follow mode not recentring', 's2_amline.s', (
        ('        ldx #ST_MY - AMST\n        jsr st_mr\n'
         '        jsr am_center\n        jmp am_setx2y2\n',
         '        ldx #ST_MY - AMST\n        jsr st_mr\n'
         '        jmp am_setx2y2          ; (planted: no centring)\n'),)),
    ('the zoom applied once a frame instead of once a tic', 's2_am.s', (
        ('        jsr am_ticker\n        dec AMTICS\n        bra @tic\n',
         '        jsr am_ticker\n        stz AMTICS              ; '
         '(planted: one tic a frame)\n        bra @tic\n'),)),
)

KEEP_GEN = ('s2.inc', 's2-release.inc', 's2-m11.inc', 's2-fxch8.inc',
            'rlayout.inc')


def plant(k: int, jobs_n: int = JOBS
          ) -> Tuple[str, List[str], Dict[str, int]]:
    """Planted bug k in a scratch copy of the sources: built, then the
    checks (fill $A5 only); the problems they give."""
    global FILLS
    name, source, edits = PLANTED[k]
    scratch = Path(tempfile.mkdtemp(prefix='tmp-s2amap-plant-',
                                    dir=str(OUT)))
    try:
        src = scratch / 'src'
        (src / 'm11').mkdir(parents=True)
        shutil.copy(str(SOURCE / 'm11.mk'), str(src / 'm11.mk'))
        for f in ('s2lay.mk', 's2amap.mk'):
            shutil.copy(str(SOURCE / 'm11' / f), str(src / 'm11' / f))
        for f in ('s2_am.s', 's2_amline.s', 's2_amt.s', 's2_am.inc'):
            shutil.copy(str(SOURCE / f), str(src / f))
        text = (src / source).read_text()
        for old, new in edits:
            if text.count(old) != 1:
                raise AmError('planted %r: %r is not found once' % (
                    name, old[:50]))
            text = text.replace(old, new)
        (src / source).write_text(text)
        m11 = scratch / 'm11'
        (m11 / 'shared' / 'gen').mkdir(parents=True)
        for f in KEEP_GEN:
            shutil.copy(str(M11 / 'shared' / 'gen' / f),
                        str(m11 / 'shared' / 'gen' / f))
        make(m11, src)
        keep = FILLS
        FILLS = ((0xA5, False),)
        try:
            res = check(None, m11 / 's2amap', jobs_n)
        except Exception as error:      # a run that fails is a catch too
            text = str(error).strip().splitlines()
            return name, ['the run failed: %s' % (text[0] if text else
                                                  type(error).__name__)], {}
        finally:
            FILLS = keep
        by = {'frames injected': sum(len(r['problems']) for r in
                                     res['frames']['jobs']),
              'frames chained': sum(len(r['problems']) for r in
                                    res['frames']['chained']),
              'calls injected': sum(len(r['problems']) for r in
                                    res['calls']['jobs']),
              'calls chained': sum(len(r['problems']) for r in
                                   res['calls']['chained'])}
        return name, res['problems'], by
    finally:
        shutil.rmtree(str(scratch), ignore_errors=True)


def planted(jobs_n: int = JOBS) -> List[Dict[str, Any]]:
    out = []
    for k in range(len(PLANTED)):
        name, problems, by = plant(k, jobs_n)
        out.append({'bug': name, 'caught': bool(problems),
                    'failures': len(problems), 'by_check': by,
                    'first': problems[0] if problems else None})
    return out


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """AMAPW (amw: the image without the test glue) against its room and
    the size table; its modules (no pl_poll, no fx_service: 1.5.4)."""
    text = (obj / 'amw.map').read_text()
    ms_ = S.read_map(text)
    mods = dict(ms_.modules)
    return {'modules': mods,
            'own': sum(v for k, v in mods.items()
                       if k in ('s2_am', 's2_amline')),
            'own_budget': S.IMAGE['AMAPW'].own,
            'no_poll_or_service': not any(k in mods for k in
                                          ('pl_input', 'fx')),
            'table': (obj / 'amw.sizes').read_text().splitlines()}


def stats(values: Sequence[float]) -> Dict[str, float]:
    v = sorted(values)
    if not v:
        return {}
    return {'n': len(v), 'median': round(v[len(v) // 2], 3),
            'p99': round(v[min(len(v) - 1, (99 * len(v)) // 100)], 3),
            'worst': round(v[-1], 3)}


def timing(profile: str, jobs_n: int = JOBS) -> Dict[str, Any]:
    """am_frame's time by kind of frame (injected, fill $A5), the
    responder's and the ticker's µs a call."""
    cap = Capture()
    b = build_of()
    fr = frames(cap)
    jobs = [j for j in frame_jobs(fr) if j.fill == 0xA5 and not j.chained]
    with ThreadPoolExecutor(max_workers=jobs_n) as ex:
        res = list(ex.map(lambda j: run_frame_job(j, b, cap, profile), jobs))
    kinds: Dict[str, List[float]] = {}
    drain: Dict[str, List[float]] = {}
    for r, j in zip(res, jobs):
        for kind, v, f in zip(r.get('kinds', []), r['ms'], j.frames):
            kinds.setdefault(kind, []).append(v)
            kinds.setdefault('all', []).append(v)
            d = published(f) * DRAIN_US / 1000.0
            drain.setdefault(kind, []).append(d)
            drain.setdefault('all', []).append(d)
    cl = calls(cap)
    rc = run_calls(b, cap, cl[:CALLS_A_RUN], 0xA5, False, profile)
    load = sum(n for m, n in sizes()['modules'].items()) + \
        (S.MATHW_END - S.MATHW_LO)
    return {'frames': {k: stats(v) for k, v in kinds.items()},
            'drain_ms': {k: stats(v) for k, v in drain.items()},
            'load_ms': round(load * LOAD_US / 1000.0, 3),
            'responder_us': stats(rc['us']['responder']),
            'ticker_us': stats(rc['us']['ticker']),
            'problems': [p for r in res for p in r['problems']] +
            rc['problems']}


def run_all(jobs_n: int = JOBS) -> Dict[str, Any]:
    from native import s2cap as C
    t0 = time.time()
    report: Dict[str, Any] = {'df': C.df_report()}
    cap = Capture()
    report['capture'] = {'frames': len(cap.index['frames']),
                         'calls': len(cap.index['calls']),
                         'problems': cap.index['problems']}
    report['model'] = check_model(cap)
    report['check'] = check(None, OUT, jobs_n)
    report['timing'] = {p: timing(p, jobs_n) for p in PROFILES}
    report['planted'] = planted(jobs_n)
    report['sizes'] = sizes()
    problems = list(report['capture']['problems']) + report['model'] + \
        report['check']['problems']
    for p in PROFILES:
        problems += report['timing'][p]['problems']
    problems += ['planted bug not caught: %s' % x['bug']
                 for x in report['planted'] if not x['caught']]
    sz = report['sizes']
    if sz['own'] > sz['own_budget']:
        problems.append('AMAPW own %d of %d B' % (sz['own'],
                                                  sz['own_budget']))
    if not sz['no_poll_or_service']:
        problems.append('AMAPW links pl_poll or fx_service')
    report['problems'] = problems
    report['ok'] = not problems
    report['seconds'] = round(time.time() - t0, 1)
    (OUT / 'report.json').write_text(json.dumps(report, indent=1,
                                                sort_keys=True))
    return report


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--inc', type=Path)
    ap.add_argument('--capture', action='store_true')
    ap.add_argument('--profile')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--model', action='store_true')
    ap.add_argument('--planted', action='store_true')
    ap.add_argument('--timing', action='store_true')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--jobs', type=int, default=JOBS)
    args = ap.parse_args(argv)
    if args.model:
        p = check_model(Capture())
        print('the model: %d problems' % len(p))
        for x in p[:10]:
            print('  ' + x)
        return 1 if p else 0
    if args.check:
        r = check(args.profile, OUT, args.jobs)
        fr, cl = r['frames'], r['calls']
        print('frames: %d jobs, %d chained runs; calls: %d jobs, %d chained'
              ' runs; %d problems' % (len(fr['jobs']), len(fr['chained']),
                                      len(cl['jobs']), len(cl['chained']),
                                      len(r['problems'])))
        for x in r['problems'][:20]:
            print('  ' + x)
        return 1 if r['problems'] else 0
    if args.planted:
        res = planted(args.jobs)
        for x in res:
            print('%-55s %s (%d) %s' % (x['bug'], 'caught' if x['caught']
                                         else 'NOT CAUGHT', x['failures'],
                                         x['first']))
            print('    %s' % x['by_check'])
        return 0 if all(x['caught'] for x in res) else 1
    if args.timing:
        for p in PROFILES:
            print(p, json.dumps(timing(p, args.jobs)))
        return 0
    if args.all:
        r = run_all(args.jobs)
        print('report.json: ok %s, %d problems (%.0f s)' % (
            r['ok'], len(r['problems']), r['seconds']))
        for x in r['problems'][:20]:
            print('  ' + x)
        return 0 if r['ok'] else 1

    if args.inc:
        write_inc(args.inc)
        return 0
    if args.capture:
        t = time.time()
        idx = capture()
        print('captured %d full-map frames, %d calls, %.1f MB of pipe, '
              '%d problems (%.0f s)' % (len(idx['frames']), len(idx['calls']),
                                        idx['traffic'] / 1e6,
                                        len(idx['problems']), time.time() - t))
        for p in idx['problems'][:10]:
            print('  ' + p)
        return 1 if idx['problems'] else 0
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
