#!/usr/bin/env python3
"""Part s2menu1 of milestone 11's first half (docs/SCREENS.md 1.5.3,
7.3; docs/m11-parts/s2menu1.md): the menu engine and the main pages in
MENUW, their generated include and their checkpoint.

The include (`--inc OUT`, gen/s2menu1.inc) holds what src/native/s2_menu.s
and src/native/s2_mvid.s read beyond s2.inc and rlayout.inc: the game's
places (milestones 9-10, read only), the message symbols' ids
(llayout.symbol_list(), as part s2hud), the menu's sounds, the native
state fields and places (s2layout's since wave 5's integration: requests
S2MENU1-1 and S2MENU1-2), the patches of upstream's
`lumpNames` [R m_menu65.s:161-213] and the font `STCFN033`-`STCFN095`
with each patch's place in the 2D store (part s2data's s2data.json) and
its header (read from the store's own bytes, GFX.1), and the skulls' box
that `M_Init` computes [R m_menu65.s:613-635].

The checkpoint (`--capture`, `--check`, `--planted`, `--timing`,
`--all`): docs/m11-parts/s2menu1.md section 2.

Usage:  python3 tools/native/s2menu1.py --inc OUT/s2menu1.inc
        python3 tools/native/s2menu1.py --all [--jobs 2]
"""

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, rlayout as R, s2layout as S  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
OUT = M11 / 's2menu1'
UPSTREAM = BUILD / 'upstream' / 'src' / 'iigs'
S2DATA = M11 / 's2data'


class MenuError(Exception):
    pass


# ---------------------------------------------------------------------------
# Upstream's tables (m_menu65.s), read there; the indexes are upstream's
# ---------------------------------------------------------------------------

# lumpNames [R m_menu65.s:161-213]: the L_* patches in order (L_x / 2)
LUMP_NAMES = ('M_DOOM', 'M_NGAME', 'M_OPTION', 'M_LOADG', 'M_QUITG',
              'M_NEWG', 'M_SKILL', 'M_JKILL', 'M_ROUGH', 'M_HURT',
              'M_ULTRA', 'M_NMARE', 'M_LSLEFT', 'M_LSCNTR', 'M_LSRGHT',
              'M_OPTTTL', 'M_MSGOFF', 'M_MSGON', 'M_ENDGAM', 'M_MESSG',
              'M_ARUN', 'M_GAMMA', 'M_THERML', 'M_THERMM', 'M_THERMR',
              'M_THERMO', 'M_SKULL1', 'M_SKULL2', 'STCFN033', 'M_MOUSE',
              'M_MSPEED', 'M_MMOVE', 'M_CTRLS', 'M_SAVEG')
FONT_LO, FONT_HI = ord('!'), ord('_')    # HU_FONTSTART, HU_FONTEND [R :47-48]
SKULLS = ('M_SKULL1', 'M_SKULL2')

# the game's places the menu reads and writes (milestones 9-10, read only)
GAME_PLACES = (('SM_SHOWMSG', 'G_SHOWMSG', 'showMessages (a word)'),
               ('SM_MSGKEEP', 'G_MSGKEEP',
                '_g_message_dontfuckwithme (a word)'),
               ('SM_USERGAME', 'G_USERGAME', '_g_usergame (a word)'),
               ('SM_DEMOPLAY', 'G_DEMOPLAY', '_g_demoplayback (a word)'),
               ('SM_GAMESTATE', 'G_GAMESTATE', '_g_gamestate (a word)'),
               ('SM_MENUACTIVE', 'G_MENUACTIVE', '_g_menuactive (a word)'),
               ('SM_SINGLEDEMO', 'G_SINGLEDEMO', '_g_singledemo (a word)'))
# the message symbols changeMessages, changeAlwaysRun and saveDone store
# into player.message [R m_menu65.s:1013-1018, :1029-1035, :1580-1583]
MESSAGE_SYMBOLS = (('SM_ID_MSGON', 'm_menu65.s:msgOn'),
                   ('SM_ID_MSGOFF', 'm_menu65.s:msgOff'),
                   ('SM_ID_RUNON', 'm_menu65.s:msgRunOn'),
                   ('SM_ID_RUNOFF', 'm_menu65.s:msgRunOff'),
                   ('SM_ID_SAVED', 'g_game65.s:strGameSaved'))
SOUNDS = ('CONST_SFX_PISTOL', 'CONST_SFX_PSTOP', 'CONST_SFX_STNMOV',
          'CONST_SFX_SWTCHN', 'CONST_SFX_SWTCHX')

# MENUW's own state fields with no upstream counterpart, after the field
# map's: s2layout.MENUW_NATIVE (request S2MENU1-1, applied in wave 5's
# integration, without the first request's M_BINDWAIT and M_BINDCODE: the
# input layer's bind state is the input block's PL_BIND, which part
# plinput's shared pl_poll writes)
MENUW_NATIVE = list(S.MENUW_NATIVE)
# the requests in M_REQ (docs/m11-parts/s2menu1.md 1.2; s2layout's)
REQUESTS = S.MENU_REQUESTS


def _runtime(what: str) -> int:
    return next(lo for lo, _, w in S.IMAGE['MENUW'].runtime if w == what)


# MENUW's places (request S2MENU1-2, applied: s2layout's MENUW): PALST
# above the room, the band, UI_GRAY, the drawers' marks page, the menu
# palette's nibble slot, the fetch buffer
MENUW_PLACES = (('S2M_PALST', S.MENUW_PALST, 'PALST, 768 B (above the room)'),
                ('S2M_BAND', _runtime('a 24-row band'), 'the band, 24 rows'),
                ('S2M_GRAY', _runtime('UI_GRAY'),
                 'UI_GRAY, 16 x 16 gray indexes'),
                ('S2M_MARKS', S.DRAW_PLACES['MENUW'][0],
                 's2_draw\'s marks page'),
                ('S2M_SLOT', _runtime('the menu palette\'s nibble slot'),
                 'palette 9\'s nibble table (1 KB)'),
                ('S2M_FBUF', S.DRAW_PLACES['MENUW'][1],
                 'the patch fetch buffer'))
BAND_ROWS = 24
# the stop code of a failed save (PL_STATUS; s2layout's PL_MENUAMEM)
AMEM_STOP = S.PL['MENUAMEM']
FBPAGES = S.DRAW_PLACES['MENUW'][2]
ROOM_END = S.IMAGE['MENUW'].stored[1]       # $A500 (S2MENU1-2)

# the zero page of the menu ($80-$AF, SCREENS.md 4.3's S2M_*)
S2M_ZP = [('S2M_X', 2), ('S2M_Y', 2), ('S2M_P', 2), ('S2M_I', 1),
          ('S2M_N', 1), ('S2M_K', 1), ('S2M_T', 2), ('S2M_W', 2),
          ('S2M_TP', 1), ('S2M_CH', 1), ('S2M_A', 2), ('S2M_B', 2),
          ('S2M_C', 1), ('S2M_D', 1), ('S2M_E', 1), ('S2M_F', 1),
          ('S2M_R0', 1), ('S2M_R1', 1), ('S2M_B0', 1), ('S2M_B1', 1),
          ('S2M_LINE', 1), ('S2M_ITEM', 1), ('S2M_LEFT', 1),
          ('S2M_UIY', 2), ('S2M_MENU', 1), ('S2M_ITON', 1), ('S2M_ACT', 1),
          ('S2M_MSG', 1), ('S2M_OLDY', 1), ('S2M_OLDH', 1),
          ('S2M_EDGE', 2), ('S2M_KIND', 1), ('S2M_SEQ', 1),
          ('S2M_OLDX', 2), ('S2M_OLDW', 1), ('S2M_OLDS', 1),
          ('S2M_NEWS', 1), ('S2M_SND', 1)]


def offsets_inc() -> Dict[str, int]:
    out = {}
    for line in (UPSTREAM / 'offsets.inc').read_text().splitlines():
        f = line.split()
        if len(f) >= 3 and f[1] == '.equ':
            try:
                out[f[0]] = int(f[2], 0)
            except ValueError:
                pass
    return out


def native_fields() -> Dict[str, int]:
    """MENUW's native fields after the field map's (its state block:
    s2layout.state_places, request S2MENU1-1)."""
    places = S.state_places('MENUW')
    missing = [n for n, _ in MENUW_NATIVE if n not in places]
    if missing:
        raise MenuError('MENUW\'s state block lacks %s' % ', '.join(missing))
    return {n: places[n] for n, _ in MENUW_NATIVE}


def zero_page() -> Dict[str, int]:
    at, out = S.ZP_S2M[0], {}
    for n, size in S2M_ZP:
        out[n] = at
        at += size
    if at > S.ZP_S2M[1]:
        raise MenuError('the menu\'s zero page passes $%02X' % S.ZP_S2M[1])
    return out


# ---------------------------------------------------------------------------
# The 2D store's patches
# ---------------------------------------------------------------------------

class PatchInfo(NamedTuple):
    name: str
    bank: int
    address: int
    width: int
    height: int
    left: int
    top: int


def store_banks() -> Dict[int, bytearray]:
    from native import lstore
    banks: Dict[int, bytearray] = {}
    files = sorted(S2DATA.glob('GFX.*'))
    if not files:
        raise MenuError('no GFX.n in %s: make -C src/native -f m11.mk part '
                        'P=s2data' % S2DATA)
    for p in files:
        for bank, address, data in lstore.read_bank_file(p.read_bytes()):
            buf = banks.setdefault(bank, bytearray(0x10000))
            buf[address:address + len(data)] = data
    return banks


def patches() -> Dict[str, PatchInfo]:
    """Every patch the menu draws: its place (s2data.json) and its header
    read from the store's bytes."""
    path = S2DATA / 's2data.json'
    if not path.exists():
        raise MenuError('%s is missing: make -C src/native -f m11.mk part '
                        'P=s2data' % path)
    lumps = {x['name']: x for x in json.loads(path.read_text())['lumps']}
    banks = store_banks()
    names = list(LUMP_NAMES) + ['STCFN%03d' % c for c in
                                range(FONT_LO, FONT_HI + 1)]
    out = {}
    for n in names:
        if n not in lumps:
            raise MenuError('%s is not in the 2D store' % n)
        x = lumps[n]
        w, h, left, top = struct.unpack_from('<HHhh', banks[x['bank']],
                                             x['address'])
        out[n] = PatchInfo(n, x['bank'], x['address'], w, h, left, top)
    return out


def skull_box(ps: Dict[str, PatchInfo]) -> Tuple[int, int, int, int]:
    """M_Init's box of both skulls [R m_menu65.s:617-634]: SK_DX, SK_DY
    the smallest -leftoffset, -topoffset; SK_W, SK_H the largest right
    and bottom less them."""
    dx = dy = 0x7FFF
    w = h = -0x8000
    for n in SKULLS:
        p = ps[n]
        dx = min(dx, -p.left)
        dy = min(dy, -p.top)
        w = max(w, -p.left + p.width)
        h = max(h, -p.top + p.height)
    return dx, dy, w - dx, h - dy


def _bytes(label: str, values: Sequence[int]) -> List[str]:
    out = ['%s:' % label]
    for k in range(0, len(values), 16):
        out.append('        .byte ' + ', '.join(
            '$%02X' % (v & 0xFF) for v in values[k:k + 16]))
    return out


def patch_tables(ps: Dict[str, PatchInfo]) -> List[str]:
    """The macro S2M_PATCHES (the L_* patches) and S2M_FONT (the font):
    each patch's bank, address, width (all below 256), the rows it covers
    from its y (top offset, a signed byte) and its height."""
    lines: List[str] = []
    for macro, names, prefix in (
            ('S2M_PATCHES', LUMP_NAMES, 'mp'),
            ('S2M_FONT', ['STCFN%03d' % c for c in range(FONT_LO,
                                                          FONT_HI + 1)],
             'mf')):
        group = [ps[n] for n in names]
        for p in group:
            if not (-128 <= p.top <= 127 and 0 < p.height < 256 and
                    0 < p.width < 256):
                raise MenuError('%s: top %d, height %d, width %d do not fit '
                                'a byte' % (p.name, p.top, p.height,
                                            p.width))
        lines.append('.macro %s' % macro)
        lines += _bytes(prefix + '_bank', [p.bank for p in group])
        lines += _bytes(prefix + '_lo', [p.address & 0xFF for p in group])
        lines += _bytes(prefix + '_hi', [p.address >> 8 for p in group])
        lines += _bytes(prefix + '_w', [p.width for p in group])
        lines += _bytes(prefix + '_top', [p.top & 0xFF for p in group])
        lines += _bytes(prefix + '_h', [p.height for p in group])
        lines.append('.endmacro')
    return lines


def inc_text() -> str:
    ps = patches()
    ofs = offsets_inc()
    ids = {s: k for k, s in enumerate(LL.symbol_list())}
    pl = {p[0]: at for p, _, at in LL.player_layout()}
    if 'message' not in pl:
        raise MenuError('the player has no message field')
    lines = ['; Generated by tools/native/s2menu1.py --inc (part s2menu1, '
             'docs/m11-parts/s2menu1.md). Do not edit.', '',
             '; the game\'s places (milestones 9-10, read only)',
             'SM_PLMSG        = $%04X ; player.message: tag (1 a symbol), '
             'id (2), offset (2)' % (LL.G['G_PLAYER'] + pl['message'])]
    for name, g, why in GAME_PLACES:
        lines.append('%-15s = $%04X ; %s' % (name, LL.G[g], why))
    from native import glayout as GL
    lines += ['SM_GA           = $%02X   ; sc_start\'s arguments (GAME.md '
              '4.4: glayout GA_RANGE)' % GL.GA_RANGE[0]]
    lines += ['SM_GAMMA        = $%04X ; the render input GAMMA (0-4)'
              % R.RINS['GAMMA'],
              'SM_AUTOMAP      = $%04X ; the frame block\'s AUTOMAP: bit 0 '
              'AM_ACTIVE' % R.FRAME['AUTOMAP'],
              'SM_TAG_SYMBOL   = 1     ; player.message\'s tag of a symbol',
              '', '; the message symbols\' ids (llayout.symbol_list())']
    for name, ref in MESSAGE_SYMBOLS:
        if ref not in ids:
            raise MenuError('%s is not in llayout.symbol_list()' % ref)
        lines.append('%-15s = $%04X ; %s' % (name, ids[ref], ref))
    lines += ['', '; the menu\'s sounds [R offsets.inc]']
    for name in SOUNDS:
        lines.append('%-15s = %d' % (name[6:], ofs[name]))
    # (MENUW's native state fields M_PALON .. M_FONTBUF and the requests
    # REQ_* are s2.inc's since wave 5's integration: S2MENU1-1)
    lines += ['', '; MENUW\'s places (s2layout\'s MENUW: S2MENU1-2)']
    for name, at, why in MENUW_PLACES:
        lines.append('%-15s = $%04X ; %s' % (name, at, why))
    lines += ['S2M_AMEMSTOP    = $%02X ; PL_STATUS: the save failed'
              % AMEM_STOP,
              'S2M_BANDROWS    = %d' % BAND_ROWS,
              'S2M_FBPAGES     = %d' % FBPAGES,
              'S2M_ROOM_END    = $%04X' % ROOM_END,
              '', '; the menu\'s zero page ($80-$AF, SCREENS.md 4.3)']
    for name, at in zero_page().items():
        lines.append('%-15s = $%02X' % (name, at))
    dx, dy, w, h = skull_box(ps)
    lines += ['', '; M_Init\'s box of both skulls [R m_menu65.s:613-635]',
              'SK_DX           = %d' % dx, 'SK_DY           = %d' % dy,
              'SK_W            = %d' % w, 'SK_H            = %d' % h,
              'S2M_NPATCH      = %d' % len(LUMP_NAMES),
              'S2M_NFONT       = %d' % (FONT_HI - FONT_LO + 1), '']
    for k, n in enumerate(LUMP_NAMES):
        lines.append('P_%-13s = %d' % (n, k))
    lines.append('')
    lines += patch_tables(ps)
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# The checkpoint: the reference's frames and events of menus.script
# (part s2cap's cases), injected into MENUW on a2vm
# ---------------------------------------------------------------------------

RUN = 'menus'
MENU_PAL = 9
UI_PALON_ON = 0x6D70            # UI_PALON's "on" [R i_viigs65.s:2058-2060]
# the pages by currentMenu: this part's (main, new game and skill,
# options) and part s2menu2's (load, key setup, save, display and sound,
# controls), whose drawing is s2menu2's (exclusion X-M2 here: since wave
# 6's integration both parts link one MENUW, S2MENU2-3, and part
# s2menu2's checkpoint compares every page of this run on it but the key
# setup's frames redrawn whole, X-K)
PAGES_MINE = (0, 2, 6)
PAGES_M2 = (4, 8, 10, 12, 16)
MSG_BENCH = 16
PAGE_NAMES = {0: 'main', 2: 'new game', 4: 'load', 6: 'options',
              8: 'key setup', 10: 'save', 12: 'display & sound',
              16: 'controls'}


class Job(NamedTuple):
    kind: str                   # open, full, skull, close
    name: str                   # the case's
    case: object                # s2cap.Case
    saved: bytes                # the session's saved screen (PM)
    natives: Dict[str, int]     # MENUW's native fields (MENUW_NATIVE)
    excluded: str               # '' or why the comparison is not this part's
    after: Optional[object]     # the next frame's PD0 (staticDrawn's fields)


def uval(d, ref: str, n: int = 2) -> int:
    """An upstream value of a dump, by symbol or by hex address."""
    from native import s2cap as C
    at = int(ref, 16) if ref.isalnum() and len(ref) == 6 and \
        all(ch in '0123456789ABCDEF' for ch in ref) else C.sym(ref)
    return int.from_bytes(d.get(at, n), 'little')


def session_natives(open_case) -> Dict[str, int]:
    """What I_MenuPalette keeps at the open [R i_viigs65.s:2062-2069]."""
    d = open_case.before
    return {'M_PICTURE': uval(d, 'i_viigs65.s:picturenum'),
            'M_VIEWPAL': uval(d, 'i_viigs65.s:viewpal') & 0xFF,
            'M_STRIPPAL': uval(d, 'i_viigs65.s:strippal') & 0xFF,
            'M_UIGAMMA': uval(d, 'm_menu65.s:_g_gamma') & 0xFF}


def frame_natives(d, session: Dict[str, int], palon: bool,
                  setchg: int) -> Dict[str, int]:
    out = dict(session)
    out['M_PALON'] = 1 if palon else 0
    out['M_MAINN'] = 6 if uval(d, 'g_game65.s:_g_usergame') else 5
    out['M_BINDROW'] = uval(d, 'm_menu65.s:bindRow') & 0xFF
    out['M_SETCHG'] = setchg
    out['M_REQ'] = 0
    out['M_REQARG'] = 0
    out['M_RELOAD'] = 0
    return out


def menu_jobs(setchg: Dict[str, int], root: Optional[Path] = None
              ) -> List[Job]:
    """Every menu frame and close of the run, in order: the open (the
    frame with PM), the frames redrawn whole (PDF) or by the skull (PDS)
    while the menu's palette is on, the closes (I_MenuPaletteBack's
    events)."""
    from native import s2cap as C
    rc = C.RunCases(C.run_dir(RUN) if root is None else root)
    entries = [('frame', e) for e in rc.index['frames']] + \
        [('event', e) for e in rc.index['events']]
    entries.sort(key=lambda x: x[1]['cycles'][0])
    loaded = [(k, e, rc.load(e)) for k, e in entries]
    out: List[Job] = []
    saved, session, palon = b'', {}, False
    for i, (kind, e, case) in enumerate(loaded):
        pts = [d.point.split(':')[0] for d in case.dumps]
        nxt = None
        for k2, _, c2 in loaded[i + 1:]:
            if k2 == 'frame':
                nxt = c2.before
            break
        if kind == 'event':
            if e.get('routine') == 'I_MenuPaletteBack' and palon:
                out.append(Job('close', e['name'], case, saved,
                               frame_natives(case.before, session, True,
                                             0), '', None))
                palon = False
            continue
        d = case.before
        active = uval(d, 'm_menu65.s:_g_menuactive') or \
            uval(d, 'm_menu65.s:messageToPrint')
        if not active:
            continue
        menu = uval(d, 'm_menu65.s:currentMenu')
        msg = uval(d, 'm_menu65.s:messageToPrint')
        why = ''
        if msg and uval(d, 'm_menu65.s:messageKind') == MSG_BENCH:
            why = 'X-M2: the benchmark\'s result (s2menu2)'
        if 'PM' in pts:
            pm = case.one('PM')
            saved = pm.get(*C.SCREEN)
            session = session_natives(case)
            out.append(Job('open', e['name'], case, saved,
                           frame_natives(d, session, False,
                                         setchg.get(e['name'], 0)),
                           why, nxt))
            palon = True
            continue
        if not palon:
            continue
        if 'PDF' in pts:
            k = 'full'
            if not msg and menu in PAGES_M2:
                why = 'X-M2: the %s page (s2menu2)' % PAGE_NAMES[menu]
        elif 'PDS' in pts:
            k = 'skull'
        else:
            continue
        out.append(Job(k, e['name'], case, saved,
                       frame_natives(d, session, True,
                                     setchg.get(e['name'], 0)), why, nxt))
    return out


def native_record(natives: Dict[str, int]) -> List[Tuple]:
    """MENUW's native fields into its block in S2STATE (SS_MENUW)."""
    places = native_fields()
    sizes = dict(MENUW_NATIVE)
    recs = []
    base = S.SS['SS_MENUW'] - S.OWN_STATE['MENUW'][1]
    for name, value in natives.items():
        n = sizes[name]
        recs.append((1, S.S2STATE, base + places[name],
                     (value & ((1 << 8 * n) - 1)).to_bytes(n, 'little')))
    return recs


def store_records() -> List[Tuple]:
    """The 2D store (part s2data's GFX.n)."""
    from native import lstore
    out = []
    files = sorted(S2DATA.glob('GFX.*'))
    if not files:
        raise MenuError('no GFX.n in %s: make -C src/native -f m11.mk part '
                        'P=s2data' % S2DATA)
    for p in files:
        for bank, address, data in lstore.read_bank_file(p.read_bytes()):
            out.append((1, bank, address, bytes(data)))
    return out


_STORE: List[Tuple] = []


def sound_records(b) -> List[Tuple]:
    """The channel logic's and the effect player's blocks empty (no
    channel busy, no listener, effects off: FX_ON 0), S2's player idle
    (snd_playing 0): the menu's sounds only reach the mailboxes."""
    sc = S.BUILDS['test'].sc_base
    recs = [(2, 0, sc, bytes(0x40)), (2, 0, 0xE737, bytes(9)),
            (2, 0, S.FXV_BASE, bytes(S.VOICES * S.VOICE_SIZE))]
    if 'snd_playing' in b.labels:
        recs.append((2, 0, b.labels['snd_playing'], bytes(1)))
    return recs


def job_records(b, job: Job, fill: int, poison: bool
                ) -> Tuple[List[Tuple], bytes]:
    """The injection of a job: the menu's and the palette's fields (part
    s2cap's field map), the native fields, PS_BEGUN 0, the screen before
    (PM for an open: the screen upstream saves), the session's saved
    screen in S2VIEW, the 2D store, the sound blocks."""
    from native import s2state as T
    global _STORE
    case = job.case
    inj = T.inject(case, 'menus', fill, with_screen=False)
    pal = T.inject(case, 'palettes', fill, with_screen=False)
    if inj.unfit or pal.unfit:
        raise MenuError('%s: unfit values %s' % (job.name,
                                                  inj.unfit + pal.unfit))
    recs = list(inj.records) + list(pal.records)
    recs += native_record(job.natives)
    # the input as pl_init leaves it: no key setup over these pages
    # (s2menu2's), so PL_BIND idle
    recs += input_records(PLB_IDLE)
    recs.append((1, S.S2STATE, S.SS['SS_PALST'] +
                 S.palst_places()['PS_BEGUN'], bytes(1)))
    if job.kind == 'open':
        screen = bytearray(job.saved)       # the input: never poisoned
    else:
        screen = bytearray(case.screen_before)
        if poison:
            for o in T.marked(case):
                screen[o] = fill
        recs.append((1, S.S2VIEW, 0x2000, job.saved))
    recs.append((1, 0, 0x2000, bytes(screen)))
    if not _STORE:
        _STORE = store_records()
    recs += _STORE
    recs += sound_records(b)
    return recs, bytes(screen)


SNAP = 'aux0:2000-9FFF,main:A500-BFFF,aux104:0200-0FFF'


def run_job(b, job: Job, fill: int, poison: bool, work: Path,
            profile: Optional[str] = None, write_log: bool = True):
    from native import s2run as SR
    recs, screen = job_records(b, job, fill, poison)
    if job.kind == 'close':
        calls = [SR.Call('t_close')]
    else:
        calls = [SR.Call('t_frame', 0 if job.kind == 'open' else 1)]
    return SR.run(b, calls, fill, work, extra_records=recs,
                  snap_ranges=SNAP, profile=profile, write_log=write_log)


# ---------------------------------------------------------------------------
# The reference's calls (a ref816 call log of menus.script, distilled)
# ---------------------------------------------------------------------------

CAP = OUT / 'cap'
CALLS_FILE = CAP / 'menus-calls.json.z'
CALL_LOG_LIMIT = 64 << 20
# what M_Responder and M_Ticker read and write, logged at the entry and the
# return: m_menu65.s's znear (its state) and near (the settings),
# d_main65.s's static screen, the game's words, menuNum's main row,
# the input layer's bind state, the sound volume, the automap's mode,
# UI_PALON (viewwin.inc: MM_BV + $BB56), newpal, the event
STATE_RANGES = ('m_menu65.s:_g_alwaysRun:216', 'm_menu65.s:showMessages:10',
                'd_main65.s:viewsaved:22',
                'g_game65.s:_g_usergame:8',      # demoplayback, singledemo
                'g_game65.s:_g_gamestate:2', '%d',
                'hu_stuff65.s:_g_message_dontfuckwithme:2',
                'm_menu65.s:menuNum:2',
                'i_iigs65.s:iigs_bindwait:12',   # bindcode, EVENT
                's_sound65.s:snd_SfxVolume:2',
                # the music's volume, the field map's SS_SETTINGS+5 since
                # wave 6 (S2MENU2-2)
                's_sound65.s:snd_MusicVolume:2', 'am_map65.s:automapmode:2',
                '0ABB56:2', 'i_viigs65.s:newpal:2')
# the calls M_Responder's handlers make (entries only): the sounds, the
# game's actions (the requests), the close, the input layer's
ACTIONS = ('S_StartSound', 'G_DeferedInitNew', 'I_Quit', 'D_StartTitle',
           'G_CheckDemoStatus', 'G_LoadGame', 'G_SaveGame', 'G_SaveSettings',
           'G_DeferedPlayDemo', 'I_MenuPaletteBack', 'I_BindKey',
           'I_DefaultKeys', 'IIGS_MouseUp', 'I_SetPalette',
           'M_StartControlPanel')


def state_ranges() -> str:
    """STATE_RANGES with player.message's address in hex (a symbol's
    +offset would read as the list's separator)."""
    from native import s2cap as C
    at = C.sym('g_game65.s:_g_player') + offsets_inc()['OFS_PL_MESSAGE']
    return '+'.join('%06X:5' % at if '%d' in r else r for r in STATE_RANGES)


def routines() -> List[str]:
    mem = state_ranges()
    out = ['m_menu65.s:M_Responder,in=dp:_Dp:4,mem=%s' % mem,
           'm_menu65.s:M_Ticker,mem=%s' % mem,
           'm_config65.s:G_SettingsChanged']
    out += ['%s,entry=1,in=dp:_Dp:4' % a for a in ACTIONS]
    return out


def capture(work_root: Path = OUT) -> Dict:
    """menus.script on ref816 with the call log of routines() (bounded by
    run_script's wall-time limit and CALL_LOG_LIMIT), distilled into
    CALLS_FILE: each logged call's name, number, parent, cycles, registers
    and memory. The raw log and the run's files are deleted."""
    import shutil
    import tempfile
    import zlib
    from ref816 import calls as RC, run_script, title
    title.build_machine()
    title.ensure_image()
    CAP.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tmp-cap-', dir=str(CAP)))
    try:
        log = work / 'calls.log'
        extra = RC.options(routines(), log) + ['--call-log-limit',
                                               str(CALL_LOG_LIMIT)]
        script = ROOT / 'coverage' / 'm11' / (RUN + '.script')
        report = run_script.run(script, extra=extra, name=RUN,
                                runs=work / 'runs', shots=work / 'shots')
        if report['problems']:
            raise MenuError('the capture run: %s' % report['problems'])
        head, lines, end = RC.read(log)
        names = [r['name'] for r in head['routines']]
        out = []
        for line in lines:
            o = line['out']
            out.append({'call': line['call'], 'name': names[line['routine']],
                        'parent': line['parent'], 'cycles': line['cycles'],
                        'in': {k: v for k, v in line['in'].items()},
                        'out': None if o is None else
                        {k: v for k, v in o.items()}})
        data = {'format': 's2menu1-calls 1', 'ranges': state_ranges(),
                'arrivals': end['arrivals'], 'names': names, 'calls': out,
                'cycles': report['cycles']}
        CALLS_FILE.write_bytes(zlib.compress(
            json.dumps(data, sort_keys=True).encode(), 9))
        return data
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def load_calls() -> Dict:
    import zlib
    if not CALLS_FILE.exists():
        raise MenuError('%s is missing: python3 tools/native/s2menu1.py '
                        '--capture' % CALLS_FILE)
    data = json.loads(zlib.decompress(CALLS_FILE.read_bytes()))
    if data.get('ranges') != state_ranges():
        raise MenuError('%s was captured with other ranges: --capture '
                        'again' % CALLS_FILE)
    return data


def range_list() -> List[Tuple[int, int]]:
    """state_ranges() as (address, length), resolved."""
    from ref816 import calls as RC
    table = RC.Linkmap()
    out = []
    for part in RC._ranges(state_ranges(), table).split('+'):
        a, n = part.split(':')
        out.append((int(a, 16), int(n)))
    return out


def call_dump(call: Dict, which: str = 'in'):
    """A logged call's memory as an s2cap Dump named PD0, so the field
    map's injection and read back take it as a case's start."""
    from native import s2cap as C
    ranges = tuple(range_list())
    mems = call[which]['mem']
    if len(mems) == len(ranges) + 1:     # M_Responder's in: the event's
        mems = mems[1:]                  #   pointer first (in=dp:_Dp:4)
    if len(mems) != len(ranges):
        raise MenuError('call %d: %d ranges logged' % (call['call'],
                                                       len(mems)))
    data = b''.join(bytes.fromhex(m) for m in mems)
    return C.Dump('PD0', {}, ranges, data)


def event_of(call: Dict) -> Tuple[int, int]:
    """M_Responder's event (type, data1): at its pointer, which must be
    i_iigs65.s's EVENT (postKey's, every event of the game's input)."""
    from native import s2cap as C
    at = C.sym('i_iigs65.s:EVENT')
    ptr = int.from_bytes(bytes.fromhex(call['in']['mem'][0])[:3], 'little')
    if ptr != at:
        raise MenuError('call %d: an event at $%06X' % (call['call'], ptr))
    d = call_dump(call)
    return (int.from_bytes(d.get(at, 2), 'little'),
            int.from_bytes(d.get(at + 2, 2), 'little'))


def call_case(call: Dict, which: str = 'in'):
    from native import s2cap as C
    return C.Case({'kind': 'frame', 'blank': []}, (call_dump(call, which),))


def settings_by_frame(data: Dict) -> Dict[str, int]:
    """G_SettingsChanged's answer in each frame of the cases (by cycles):
    M_SETCHG."""
    from native import s2cap as C
    rc = C.RunCases(C.run_dir(RUN))
    spans = [(e['cycles'][0], e['cycles'][1], e['name'])
             for e in rc.index['frames']]
    out: Dict[str, int] = {}
    for c in data['calls']:
        if c['name'] != 'm_config65.s:G_SettingsChanged' or not c['out']:
            continue
        for lo, hi, name in spans:
            if lo <= c['cycles'] <= hi:
                out[name] = c['out']['a'] & 0xFF
    return out


# ---------------------------------------------------------------------------
# M_Responder and M_Ticker, call by call
# ---------------------------------------------------------------------------

RESPONDER = 'm_menu65.s:M_Responder'
TICKER = 'm_menu65.s:M_Ticker'
SFX_MASK = 0x7FFF               # S_StartSound's sound (PICKUP_SOUND off)
# the requests the reference's calls under M_Responder make
REQUEST_OF = {'G_DeferedInitNew': 'REQ_NEWGAME', 'I_Quit': 'REQ_QUIT',
              'D_StartTitle': 'REQ_ENDGAME', 'G_LoadGame': 'REQ_LOAD',
              'G_SaveGame': 'REQ_SAVE', 'G_DeferedPlayDemo': 'REQ_BENCH',
              'G_SaveSettings': 'REQ_SAVESET'}
HOOKS = ('I_BindKey', 'I_DefaultKeys', 'IIGS_MouseUp')


def message_ref(raw: bytes) -> Tuple[int, int]:
    """player.message (a 24-bit pointer) as milestone 10's reference:
    (tag, id): (0, 0) for NULL, (1, the symbol's id)."""
    from native import s2msgs as MS
    ptr = int.from_bytes(raw[:3], 'little')
    if ptr == 0:
        return 0, 0
    ref = MS.by_address().get(ptr)
    if ref is None:
        raise MenuError('player.message at $%06X is not a symbol' % ptr)
    return 1, MS.symbol_ids()[ref]


def call_natives(d) -> Dict[str, int]:
    """The native fields of a logged call's state."""
    return {'M_PALON': 1 if uval(d, '0ABB56') == UI_PALON_ON else 0,
            'M_MAINN': uval(d, 'm_menu65.s:menuNum') & 0xFF,
            'M_BINDROW': uval(d, 'm_menu65.s:bindRow') & 0xFF,
            'M_SETCHG': 0, 'M_REQ': 0, 'M_REQARG': 0, 'M_RELOAD': 0}


# the reference's key codes are the IIgs's ADB codes; 6.2's poke maps them
# 1:1 to the //e's, but for Esc (ADB $35, the //e's $1B: D-M6), the one
# code M_Ticker tests
ADB_ESC = 0x35
PLB_WAIT, PLB_IDLE = dict(S.PL_BIND_VALUES)['PLB_WAIT'], \
    dict(S.PL_BIND_VALUES)['PLB_IDLE']


def pl_bind_of(d) -> int:
    """The input block's PL_BIND for upstream's input layer's bind state
    (iigs_bindwait, iigs_bindcode) and bindRow: PLB_WAIT while the key
    setup waits, the code taken while bindRow waits for M_Ticker to bind
    it, PLB_IDLE else (wave 5's integration: S2MENU1-4 with PLINPUT-3)."""
    if uval(d, 'i_iigs65.s:iigs_bindwait') & 0xFF:
        return PLB_WAIT
    if uval(d, 'm_menu65.s:bindRow') & 0x80:
        return PLB_IDLE
    code = uval(d, 'i_iigs65.s:iigs_bindcode') & 0xFF
    if code >= 0x80:
        raise MenuError('iigs_bindcode $%02X is no key' % code)
    return 0x1B if code == ADB_ESC else code


def input_records(pl_bind: int) -> List[Tuple]:
    """The input block as pl_init leaves it (part plinput's model) with
    PL_BIND, and the key table's defaults (PL_KEYTAB)."""
    from native import plinput as PI
    return PI.boot_records(pl_bind)


def call_records(b, call: Dict, fill: int) -> List[Tuple]:
    """A logged call's state into the machine: the field map's 'menus'
    fields, the native fields, player.message, the volume, the automap's
    mode, newpal, the sound blocks, the 2D store."""
    from native import s2state as T
    global _STORE
    case = call_case(call)
    d = case.before
    inj = T.inject(case, 'menus', fill, with_screen=False)
    if inj.unfit:
        raise MenuError('call %d: unfit %s' % (call['call'], inj.unfit))
    recs = list(inj.records) + native_record(call_natives(d))
    recs += input_records(pl_bind_of(d))
    tag, ident = message_ref(d.get(C_sym('g_game65.s:_g_player') +
                                   offsets_inc()['OFS_PL_MESSAGE'], 3))
    recs.append((0, 0, LL.G['G_PLAYER'] + player_message_offset(),
                 bytes([tag, ident & 0xFF, ident >> 8, 0, 0])))
    recs.append((0, 0, R.FRAME['AUTOMAP'],
                 bytes([uval(d, 'am_map65.s:automapmode') & 1])))
    recs.append((1, S.S2STATE, S.SS['SS_PALST'] +
                 S.palst_places()['PS_NEWPAL'],
                 bytes([uval(d, 'i_viigs65.s:newpal') & 0xFF])))
    if not _STORE:
        _STORE = store_records()
    recs += _STORE + sound_records(b)
    recs.append((2, 0, s2const('SND_SFXVOL'),
                 bytes([uval(d, 's_sound65.s:snd_SfxVolume') & 0xFF])))
    return recs


def s2const(name: str) -> int:
    return dict(S.constants('test'))[name]


def C_sym(ref: str) -> int:
    from native import s2cap as C
    return C.sym(ref)


def player_message_offset() -> int:
    pl = {p[0]: at for p, _, at in LL.player_layout()}
    return pl['message']


def children(data: Dict) -> Dict[int, List[Dict]]:
    out: Dict[int, List[Dict]] = {}
    for c in data['calls']:
        if c['parent']:
            out.setdefault(c['parent'], []).append(c)
    return out


def expected_request(kids: List[Dict]) -> Tuple[int, int]:
    """(M_REQ, M_REQARG) from the reference's calls under a call."""
    req = dict(REQUESTS)
    names = [k['name'] for k in kids]
    out = (0, 0)
    for k in kids:
        name = REQUEST_OF.get(k['name'])
        if name is None:
            continue
        a = k['in']['a'] & 0xFF
        if name == 'REQ_ENDGAME':
            a = 1 if 'G_CheckDemoStatus' in names else 0
        elif name in ('REQ_QUIT', 'REQ_BENCH', 'REQ_SAVESET'):
            a = 0
        out = (req[name], a)
    return out


RESP_SNAP = 'aux104:0200-0FFF,main:0300-03FF,main:1C00-1FFF,lc:E8C0-E8FF,' \
    'main:6600-A4FF'


def responder_problems(b, call: Dict, kids: List[Dict], m) -> List[str]:
    """A call's native result (the machine m after t_resp) against the
    reference's return."""
    from native import s2state as T
    out: List[str] = []
    lab = b.labels
    after = call_case(call, 'out')
    da = after.before
    want = call['out']['a'] & 0xFF
    got = m.main[lab['t_ret']]
    if got != want:
        out.append('the answer %d for %d' % (got, want))
    inj = T.inject(after, 'menus', 0, with_screen=False)
    out += T.read_back(T.snapshot_getter(m), inj)
    nat = call_natives(da)
    places = native_fields()
    base = S.SS['SS_MENUW'] - S.OWN_STATE['MENUW'][1]
    bank = m.storage('aux', S.S2STATE)
    for name in ('M_PALON', 'M_MAINN', 'M_BINDROW'):
        v = bank[base + places[name]]
        if v != nat[name]:
            out.append('%s %d for %d' % (name, v, nat[name]))
    v, want_bind = m.main[S.INPUT['PL_BIND']], pl_bind_of(da)
    if v != want_bind:
        out.append('PL_BIND $%02X for $%02X' % (v, want_bind))
    req, arg = expected_request(kids)
    got = (bank[base + places['M_REQ']], bank[base + places['M_REQARG']])
    if got != (req, arg):
        out.append('the request %d,%d for %d,%d' % (got + (req, arg)))
    tag, ident = message_ref(da.get(C_sym('g_game65.s:_g_player') +
                                    offsets_inc()['OFS_PL_MESSAGE'], 3))
    at = LL.G['G_PLAYER'] + player_message_offset()
    pm = bytes(m.main[at:at + 3])
    if pm[0] != tag or (tag and pm[1] | pm[2] << 8 != ident):
        out.append('player.message %s for %d,%d' % (pm.hex(), tag, ident))
    vol = m.lc[s2const('SND_SFXVOL') - 0xC000]
    if vol != uval(da, 's_sound65.s:snd_SfxVolume') & 0xFF:
        out.append('SND_SFXVOL %d for %d' % (
            vol, uval(da, 's_sound65.s:snd_SfxVolume')))
    npal = bank[S.SS['SS_PALST'] + S.palst_places()['PS_NEWPAL']]
    if npal != uval(da, 'i_viigs65.s:newpal') & 0xFF:
        out.append('newpal %d for %d' % (npal, uval(da,
                                                     'i_viigs65.s:newpal')))
    log = m.main[lab['s2m_sndbuf']:lab['s2m_sndbuf'] + 64]
    sounds = list(log[1:1 + log[0]])
    ref = [k['in']['a'] & SFX_MASK for k in kids
           if k['name'] == 'S_StartSound']
    origins = [k['in']['mem'][0] for k in kids if k['name'] == 'S_StartSound']
    if sounds != ref:
        out.append('the sounds %s for %s' % (sounds, ref))
    if any(o != '00000000' for o in origins):
        out.append('a menu sound with an origin: %s' % origins)
    return out


def run_calls(b, recs: List[Tuple], calls: List, fill: int, work: Path,
              snap: str, profile: Optional[str] = None,
              write_log: bool = False):
    from native import s2run as SR
    return SR.run(b, calls, fill, work, extra_records=recs, snap_ranges=snap,
                  profile=profile, write_log=write_log)


def check_responders(b, data: Dict, fill: int = 0xA5, jobs: int = 2,
                     work_root: Path = OUT,
                     only: Optional[Sequence[int]] = None) -> Dict:
    """Every logged M_Responder call, injected from its entry's state and
    run alone (t_resp): its answer, the state after (the field map's
    menus fields and the native ones), the request, player.message, the
    volume, newpal and the sounds against the reference's."""
    import shutil
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    from native import s2run as SR
    kids = children(data)
    todo = [c for c in data['calls'] if c['name'] == RESPONDER and
            (only is None or c['call'] in only)]
    root = Path(tempfile.mkdtemp(prefix='tmp-resp-', dir=str(work_root)))

    def one(call):
        work = root / ('c%05d' % call['call'])
        try:
            typ, data1 = event_of(call)
            r = run_calls(b, call_records(b, call, fill),
                          [SR.Call('t_resp', typ & 0xFF, data1 & 0xFF)],
                          fill, work, RESP_SNAP)
            if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
                return call, ['the run: %s, status %s' % (r.ended(),
                                                           r.status())]
            m = SR.read_snapshot(work / 'stop.img')
            return call, responder_problems(b, call, kids.get(call['call'],
                                                              []), m)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    out = {'calls': 0, 'eaten': 0, 'sounds': 0, 'requests': 0,
           'problems': []}
    try:
        with ThreadPoolExecutor(jobs) as ex:
            for call, probs in ex.map(one, todo):
                out['calls'] += 1
                out['eaten'] += call['out']['a'] & 1
                ks = kids.get(call['call'], [])
                out['sounds'] += sum(1 for k in ks
                                     if k['name'] == 'S_StartSound')
                out['requests'] += 1 if expected_request(ks)[0] else 0
                for pr in probs:
                    out['problems'].append('M_Responder call %d %s: %s' % (
                        call['call'], event_of(call), pr))
    finally:
        shutil.rmtree(str(root), ignore_errors=True)
    return out


TICK_FIELDS = (('m_menu65.s:skullAnimCounter', 'M_SKULLCOUNT', 1),
               ('m_menu65.s:whichSkull', 'M_WHICHSKULL', 1),
               ('m_menu65.s:skullversion', 'M_SKULLVER', 2),
               ('m_menu65.s:menuversion', 'M_MENUVER', 2),
               ('m_menu65.s:bindRow', 'M_BINDROW', 1))
TICK_CHAIN = 30


def tick_chains(data: Dict) -> List[List[Dict]]:
    """The M_Ticker calls in runs that nothing else logged interrupts (the
    state carried natively from the first call's), at most TICK_CHAIN."""
    out: List[List[Dict]] = []
    cur: List[Dict] = []

    def key(d) -> Tuple:
        return tuple(uval(d, ref, n) for ref, _, n in TICK_FIELDS) + \
            tuple(sorted(call_natives(d).items())) + (pl_bind_of(d),)
    for c in data['calls']:
        if c['name'] == TICKER:
            if cur and key(call_dump(c)) != key(call_dump(cur[-1], 'out')):
                out.append(cur)         # changed between the tics: the
                cur = []                #   input layer's bind state
            cur.append(c)
            if len(cur) == TICK_CHAIN:
                out.append(cur)
                cur = []
        elif c['name'] != 'm_config65.s:G_SettingsChanged' and \
                c['parent'] == 0:
            if cur:
                out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def check_tickers(b, data: Dict, fill: int = 0xA5, jobs: int = 2,
                  work_root: Path = OUT) -> Dict:
    """M_Ticker in chains: the first call's state injected, the native
    state carried; after each call the skull's counter, which skull, the
    versions and bindRow against the reference's; the key setup's
    I_BindKey against the native pl_bindkey (counted: the //e's key codes
    are plinput's)."""
    import shutil
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    from native import s2run as SR
    kids = children(data)
    places = S.state_places('MENUW')
    nat = native_fields()
    base = S.SS['SS_MENUW'] - S.OWN_STATE['MENUW'][1]
    root = Path(tempfile.mkdtemp(prefix='tmp-tick-', dir=str(work_root)))

    def one(chain):
        work = root / ('c%05d' % chain[0]['call'])
        try:
            r = run_calls(b, call_records(b, chain[0], fill),
                          [SR.Call('t_tick')] * len(chain), fill, work,
                          'aux104:0600-06FF,main:%04X-%04X' % (
                              S.INPUT['PL_BIND'], S.INPUT['PL_BIND']))
            if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
                return chain, ['the run: %s' % r.ended()]
            probs = []
            for k, (call, m) in enumerate(zip(chain, r.calls())):
                da = call_dump(call, 'out')
                bank = m.storage('aux', S.S2STATE)
                for ref, place, n in TICK_FIELDS:
                    at = base + (places.get(place) or nat[place])
                    got = int.from_bytes(bank[at:at + n], 'little')
                    want = uval(da, ref, n)
                    if got != want:
                        probs.append('M_Ticker call %d: %s %d for %d' % (
                            call['call'], place, got, want))
                got, want = m.main[S.INPUT['PL_BIND']], pl_bind_of(da)
                if got != want:
                    probs.append('M_Ticker call %d: PL_BIND $%02X for $%02X'
                                 % (call['call'], got, want))
            return chain, probs
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    out = {'calls': 0, 'chains': 0, 'blinks': 0, 'binds': 0,
           'problems': []}
    try:
        with ThreadPoolExecutor(jobs) as ex:
            for chain, probs in ex.map(one, tick_chains(data)):
                out['chains'] += 1
                out['calls'] += len(chain)
                for c in chain:
                    a, z = call_dump(c), call_dump(c, 'out')
                    out['blinks'] += uval(a, 'm_menu65.s:whichSkull') != \
                        uval(z, 'm_menu65.s:whichSkull')
                    out['binds'] += sum(1 for k in kids.get(c['call'], [])
                                        if k['name'] == 'I_BindKey')
                out['problems'] += probs
    finally:
        shutil.rmtree(str(root), ignore_errors=True)
    return out


# ---------------------------------------------------------------------------
# The frames: the screen, staticDrawn's state, the writes, the order
# ---------------------------------------------------------------------------

def owners(b, loads) -> List:
    """The writers of a run of the test image and what each may write
    (SCREENS.md 6.3: its W ranges, its bank ranges, the card's, aux 0)."""
    from native import plinput as PI, s2drawcase as DC, s2run as SR
    pcs = DC.module_pcs(b)
    lab = b.labels
    data = b.segments['S2DATA']
    zp_s2 = ('main', 0, S.ZP_S2[0], S.ZP_S2[1])
    zp_m = ('main', 0, S.ZP_S2M[0], S.ZP_S2M[1])
    zp_math = ('main', 0, S.ZP_MATH[0], S.ZP_MATH[1])
    fa = ('main', 0, 0x0000, 0x0006)
    w = {n: a for n, a, _ in MENUW_PLACES}
    palst = ('main', 0, w['S2M_PALST'], w['S2M_PALST'] + S.PALST_SIZE)
    band = ('main', 0, w['S2M_BAND'], w['S2M_GRAY'])
    gray = ('main', 0, w['S2M_GRAY'], w['S2M_MARKS'])
    marks = ('main', 0, w['S2M_MARKS'], w['S2M_SLOT'])
    slot = ('main', 0, w['S2M_SLOT'], w['S2M_FBUF'])
    fbuf = ('main', 0, w['S2M_FBUF'], S.OWN_STATE['MENUW'][1])
    state = ('main', 0, S.OWN_STATE['MENUW'][1], 0xC000)
    s2data = ('main', 0, data[0], data[1] + 1)
    screen = ('aux', 0, S.SHR, S.SCREEN_END)
    colors = ('aux', 0, S.SCB, S.SCREEN_END)
    s2state = ('aux', S.S2STATE, S.SS['SS_PALST'],
               S.SS['SS_SETTINGS'] + S.SS_SIZE['SS_SETTINGS'])
    game = [('main', 0, LL.G[g], LL.G[g] + 2) for g in
            ('G_MENUACTIVE', 'G_SHOWMSG', 'G_MSGKEEP')]
    game.append(('main', 0, LL.G['G_PLAYER'] + player_message_offset(),
                 LL.G['G_PLAYER'] + player_message_offset() + 5))
    game.append(('main', 0, R.RINS['GAMMA'], R.RINS['GAMMA'] + 1))
    sc = S.BUILDS['test'].sc_base
    card_sc = ('lc', 0, sc, sc + 0x40)
    card_fx = ('lc', 0, 0xE413, 0xE8C0)
    card_t = ('lc', 0, S.BUILDS['test'].s2t_base,
              S.BUILDS['test'].s2t_base + S.S2T_SIZE)
    io_window = frozenset({0xC002, 0xC003, 0xC004, 0xC005, 0xC073})
    page1 = ('main', 0, 0x0100, 0x0180)
    menu = pcs.get('s2_menu-log') or pcs['s2_menu']

    def code(name):
        lo, hi = pcs[name]
        return ('main', 0, lo, hi + 1)
    return [
        SR.driver_owner(b), SR.loader_owner(b, loads),
        SR.Owner('the far layer', (b.segments['RFAR'],),
                 (fa, zp_s2, zp_m, palst, band, gray, marks, slot, fbuf,
                  state, s2data, s2state), io_window),
        SR.Owner('the test glue', (pcs['s2_menut'],),
                 (('main', 0, R.PHASE, R.PHASE + 1), s2data), frozenset()),
        SR.Owner('s2_menu', (menu,),
                 (zp_s2, zp_m, fa, band, state, s2data, card_sc) +
                 tuple(game),
                 frozenset()),
        # part s2menu2's hooks, linked since wave 6 (S2MENU2-3): their zero
        # page (S2M_* the hooks may change, the drawers' marks' bytes),
        # far_get's arguments, the band (X2)
        SR.Owner('s2_menu2', (pcs['s2_menu2'],), (zp_s2, zp_m, fa, band),
                 frozenset()),
        SR.Owner('s2_mvid', (pcs['s2_mvid'],),
                 (zp_s2, zp_m, fa, palst, band, gray, marks, slot, state,
                  s2data,
                  ('main', 0, S.PL_STATUS, S.PL_STATUS + 1)), frozenset()),
        SR.Owner('s2_draw', (pcs['s2_draw'],),
                 (zp_s2, fa, band, marks, code('s2_draw')), frozenset()),
        SR.Owner('s2_pub', (pcs['s2_pub'],),
                 (zp_s2, screen, marks, ('main', 0, lab['s2_begun'],
                                         lab['s2_begun'] + 1)),
                 frozenset({0xC004, 0xC005})),
        SR.Owner('s2_pal', (pcs['s2_pal'],),
                 (zp_s2, fa, palst, colors, page1), io_window),
        SR.Owner('fx_chan', (pcs['fx_chan-ns'], pcs['fx_pcache']),
                 (zp_s2, zp_math, card_sc, card_t,
                  ('main', 0, 0xBEE0, 0xBF00)), frozenset()),
        SR.Owner('fx_service', (pcs['fx'],), (card_fx, card_sc, zp_s2),
                 io_window),
    ] + PI.image_owners(b)      # pl_poll, pl_keys, pl_time (wave 5)


DRAWN = (('d_main65.s:screenmenuversion', 'M_SCRMENUVER', 2),
         ('d_main65.s:screenskullversion', 'M_SCRSKULLVER', 2),
         ('d_main65.s:skullshown', 'M_SKSHOWN', 1),
         ('d_main65.s:skx', 'M_SKX', 2), ('d_main65.s:sky', 'M_SKY', 1),
         ('d_main65.s:skw', 'M_SKW', 1), ('d_main65.s:skh', 'M_SKH', 1))


# the menu's frames show the whole screen: the regions 'menu' (every row)
# and 'colors' (the SCBs, the 16 palettes); $9DC8-$9DFF must keep its value
REGION = S.Region('menu+colors', 's2menu1', S.REGIONS['menu'].rows,
                  S.REGIONS['colors'].scbs, S.REGIONS['colors'].palettes)


def frame_problems(b, job: Job, r, fill: int, poison: bool,
                   screen_in: bytes) -> Tuple[List[str], int]:
    """A frame's or a close's run against the reference: the whole screen
    (pixels, SCBs, palettes: the regions menu and colors, every other
    byte its value), staticDrawn's fields against the next frame's start,
    the menu's palette flag; (problems, bytes compared)."""
    from native import s2check as K, s2run as SR
    out: List[str] = []
    if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
        return ['the run: %s, status %s' % (r.ended(), r.status())], 0
    m = SR.read_snapshot(r.work / 'stop.img')
    got = bytes(m.storage('aux', 0)[S.SHR:S.SCREEN_END])
    res = K.compare(job.case.screen_after, screen_in, got, REGION)
    differ, outside = res.differ, res.outside
    if differ:
        out.append('%d screen bytes differ (first $%04X: $%02X for $%02X)'
                   % ((len(differ),) + differ[0]))
    if outside:
        out.append('%d bytes outside the regions changed (first $%04X)'
                   % (len(outside), outside[0][0]))
    base = S.SS['SS_MENUW'] - S.OWN_STATE['MENUW'][1]
    bank = m.storage('aux', S.S2STATE)
    places = S.state_places('MENUW')
    nat = native_fields()
    palon = bank[base + nat['M_PALON']]
    if palon != (0 if job.kind == 'close' else 1):
        out.append('M_PALON %d after the %s' % (palon, job.kind))
    if job.after is not None and job.kind != 'close':
        for ref, place, n in DRAWN:
            at = base + places[place]
            v = int.from_bytes(bank[at:at + n], 'little')
            want = uval(job.after, ref, 2) & ((1 << 8 * n) - 1)
            if v != want:
                out.append('%s %d for %d' % (place, v, want))
    return out, res.compared


def check_frames(b, setchg: Dict[str, int], jobs: int = 2,
                 work_root: Path = OUT, profile: Optional[str] = None,
                 names: Optional[Sequence[str]] = None) -> Dict:
    """Every job of menu_jobs() not excluded, twice: fill $A5 with the
    write log (the strays and the publish order judged; an open as a
    whole paused frame, m_frame), fill $5A with the reference's marked
    bytes poisoned (an open's screen is its input: not poisoned)."""
    import shutil
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    from native import s2check as K
    js = [j for j in menu_jobs(setchg) if not j.excluded and
                      (names is None or j.name in names)]
    root = Path(tempfile.mkdtemp(prefix='tmp-frames-', dir=str(work_root)))

    def one(arg):
        job, fill, poison = arg
        paused = not poison         # the opens whole (m_frame), logged
        work = root / ('%s-%02x' % (job.name, fill))
        try:
            recs, screen = job_records(b, job, fill, poison)
            r = run_calls(b, recs, [call_of(job, paused)], fill, work, SNAP,
                          write_log=not poison)
            probs, compared = frame_problems(b, job, r, fill, poison,
                                             screen)
            depth = SR_depth(r)
            if depth is not None and depth > S.STACK_2D:
                probs.append('the stack %d B deep (at most %d)' % (
                    depth, S.STACK_2D))
            if not poison and r.ended() == 'stop':
                n, shown = SR_stray(r, owners(b, r.loads))
                if n:
                    probs.append('%d stray writes: %s' % (n, shown[:3]))
                black = job.kind in ('open', 'close')
                probs += ['publish order: ' + x for x in
                          K.order(K.screen_stores(r.writes()), black)]
            return job, fill, probs, compared, depth
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    # the opens run whole paused frames (m_frame) in the logged pass
    work_list = [(j, 0xA5, False) for j in js] + \
        [(j, 0x5A, True) for j in js]
    out = {'jobs': len(js), 'runs': 0, 'compared': 0, 'kinds': {},
           'problems': [], 'stack': 0, 'excluded': {}}
    for j in menu_jobs(setchg):
        if j.excluded:
            out['excluded'][j.excluded] = out['excluded'].get(
                j.excluded, 0) + 1
    try:
        with ThreadPoolExecutor(jobs) as ex:
            for job, fill, probs, compared, depth in ex.map(one,
                                                            work_list):
                out['runs'] += 1
                out['compared'] += compared
                out['stack'] = max(out['stack'], depth or 0)
                if fill == 0xA5:
                    out['kinds'][job.kind] = out['kinds'].get(job.kind,
                                                              0) + 1
                for pr in probs:
                    out['problems'].append('%s %s fill $%02X: %s' % (
                        job.kind, job.name, fill, pr))
    finally:
        shutil.rmtree(str(root), ignore_errors=True)
    return out


def call_of(job: Job, paused: bool = False):
    """The entry a job runs: t_close, t_frame (with the tables for a frame
    after the open), or for an open t_paused (paused: m_frame whole)."""
    from native import s2run as SR
    if job.kind == 'close':
        return SR.Call('t_close')
    if paused and job.kind == 'open':
        return SR.Call('t_paused')
    return SR.Call('t_frame', 0 if job.kind == 'open' else 1)


def SR_depth(r) -> Optional[int]:
    from native import s2run as SR
    return SR.stack_depth(r)


def SR_stray(r, owners_list) -> Tuple[int, List[str]]:
    from native import s2run as SR
    return SR.stray(r.writes(), owners_list)


# ---------------------------------------------------------------------------
# Chained sessions (SCREENS.md 6.3): from each open's state only
# ---------------------------------------------------------------------------

CHAIN_CALLS = 30
# what a chunk's machine carries to the next (the stop's snapshot): the
# 2D state's bank, the saved screen, the screen, MENUW's runtime W (PALST,
# UI_GRAY, the slot, the state block), the game's places, the card's
# channel block
CARRY = ((1, S.S2STATE, 0x0200, 0x0F00), (1, S.S2VIEW, 0x2000, 0xA000),
         (1, 0, 0x2000, 0xA000), (0, 0, 0xA500, 0xC000),
         (0, 0, 0x1C00, 0x2000), (0, 0, 0x0300, 0x0400),
         (2, 0, 0xE8C0, 0xE900))
CHAIN_SNAP = 'aux0:2000-9FFF,aux104:0200-0FFF,aux105:2000-9FFF,' \
    'main:A500-BFFF,main:1C00-1FFF,main:0300-03FF,lc:E8C0-E8FF,' \
    'main:6600-A4FF'


class Step(NamedTuple):
    kind: str                   # frame, close, resp, tick
    cycles: int
    job: Optional[Job]
    call: Optional[Dict]


def sessions(setchg: Dict[str, int], data: Dict) -> List[List[Step]]:
    """Each menu session in the run's order: its open, then every frame,
    M_Responder and M_Ticker call up to its close, by cycles."""
    js = menu_jobs(setchg)
    out: List[List[Step]] = []
    cur: Optional[List[Step]] = None
    calls = [c for c in data['calls'] if c['name'] in (RESPONDER, TICKER)]
    steps = [Step('frame' if j.kind != 'close' else 'close',
                  j.case.head['cycles'][0], j, None) for j in js]
    steps += [Step('resp' if c['name'] == RESPONDER else 'tick',
                   c['cycles'], None, c) for c in calls]
    steps.sort(key=lambda x: x.cycles)
    for st in steps:
        if st.job is not None and st.job.kind == 'open':
            cur = [st]
            out.append(cur)
        elif cur is not None:
            cur.append(st)
            if st.kind == 'close':
                cur = None
    return out


def on_m2(job: Job) -> bool:
    """A frame drawn over one of part s2menu2's pages (its content is
    not this part's; the screen's other bytes keep what it drew)."""
    d = job.case.before
    return not uval(d, 'm_menu65.s:messageToPrint') and \
        uval(d, 'm_menu65.s:currentMenu') in PAGES_M2


def carry_records(m) -> List[Tuple]:
    out = []
    for kind, bank, lo, hi in CARRY:
        st = m.storage({0: 'main', 1: 'aux', 2: 'lc'}[kind], bank)
        base = 0xC000 if kind == 2 else 0
        out.append((kind, bank, lo, bytes(st[lo - base:hi - base])))
    return out


def check_chains(b, setchg: Dict[str, int], data: Dict, jobs: int = 2,
                 work_root: Path = OUT,
                 only: Optional[Sequence[str]] = None) -> Dict:
    """Each session run natively from its open's state alone: the frames
    (t_frame), the events (t_resp), the tics (t_tick) and the close
    (t_close) in the reference's order, chunks of CHAIN_CALLS carried by
    the stop's snapshot; after every frame and the close the whole screen
    against the reference's, after every event the answer and the sounds."""
    import shutil
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    from native import s2check as K, s2run as SR
    kids = children(data)
    lab = b.labels
    root = Path(tempfile.mkdtemp(prefix='tmp-chain-', dir=str(work_root)))

    def one(sess: List[Step]):
        probs: List[str] = []
        counts = {'frame': 0, 'close': 0, 'resp': 0, 'tick': 0}
        recs, _ = job_records(b, sess[0].job, 0xA5, False)
        # chunks of CHAIN_CALLS, a new one where G_SettingsChanged's answer
        # (the second half's input M_SETCHG) changes before a frame
        chunks: List[List[Step]] = []
        value = sess[0].job.natives['M_SETCHG']
        for st in sess:
            v = st.job.natives['M_SETCHG'] if st.kind == 'frame' else value
            if not chunks or len(chunks[-1]) == CHAIN_CALLS or v != value:
                chunks.append([])
                value = v
            chunks[-1].append(st)
        for k, chunk in enumerate(chunks):
            if k:
                recs = list(job_records(b, sess[0].job, 0xA5, False)[0]) + \
                    carry + native_record({'M_SETCHG': chunk[0].job.natives[
                        'M_SETCHG'] if chunk[0].kind == 'frame' else value})
            calls = []
            for st in chunk:
                if st.kind == 'frame':
                    calls.append(SR.Call('t_frame', 0))
                elif st.kind == 'close':
                    calls.append(SR.Call('t_close'))
                elif st.kind == 'resp':
                    typ, d1 = event_of(st.call)
                    calls.append(SR.Call('t_resp', typ & 0xFF, d1 & 0xFF))
                else:
                    calls.append(SR.Call('t_tick'))
            work = root / ('%s-%03d' % (sess[0].job.name, k))
            try:
                r = run_calls(b, recs, calls, 0xA5, work, CHAIN_SNAP)
                if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
                    probs.append('%s: the run %s' % (sess[0].job.name,
                                                     r.ended()))
                    break
                snaps = r.calls()
                for st, m in zip(chunk, snaps):
                    counts[st.kind] += 1
                    if st.kind == 'frame' and on_m2(st.job):
                        counts['excluded'] = counts.get('excluded', 0) + 1
                        continue        # X-M2: s2menu2's page is up
                    if st.kind in ('frame', 'close'):
                        got = bytes(m.storage('aux', 0)[S.SHR:S.SCREEN_END])
                        res = K.compare(st.job.case.screen_after,
                                        st.job.case.screen_after, got,
                                        REGION)
                        if res.differ:
                            probs.append('%s %s: %d bytes differ' % (
                                st.kind, st.job.name, len(res.differ)))
                    elif st.kind == 'resp':
                        want = st.call['out']['a'] & 0xFF
                        if m.main[lab['t_ret']] != want:
                            probs.append('M_Responder call %d: the answer'
                                         % st.call['call'])
                        log = m.main[lab['s2m_sndbuf']:lab['s2m_sndbuf'] + 64]
                        ref = [x['in']['a'] & SFX_MASK for x in
                               kids.get(st.call['call'], [])
                               if x['name'] == 'S_StartSound']
                        if list(log[1:1 + log[0]]) != ref:
                            probs.append('M_Responder call %d: the sounds'
                                         % st.call['call'])
                carry = carry_records(SR.read_snapshot(work / 'stop.img'))
                value = sess[0].job.natives['M_SETCHG']
                for st in chunk:
                    if st.kind == 'frame':
                        value = st.job.natives['M_SETCHG']
            finally:
                shutil.rmtree(str(work), ignore_errors=True)
        return sess[0].job.name, counts, probs
    out = {'sessions': 0, 'steps': {}, 'problems': []}
    try:
        with ThreadPoolExecutor(jobs) as ex:
            todo = [x for x in sessions(setchg, data)
                    if only is None or x[0].job.name in only]
            for name, counts, probs in ex.map(one, todo):
                out['sessions'] += 1
                for kk, v in counts.items():
                    out['steps'][kk] = out['steps'].get(kk, 0) + v
                out['problems'] += probs
    finally:
        shutil.rmtree(str(root), ignore_errors=True)
    return out


# ---------------------------------------------------------------------------
# Timing (SCREENS.md 6.4)
# ---------------------------------------------------------------------------

PROFILES = ('f121', 'fastpath')


def stats(values: Sequence[float]) -> Dict[str, float]:
    v = sorted(values)
    if not v:
        return {}
    p99 = v[min(len(v) - 1, int(round(0.99 * (len(v) - 1))))]
    return {'n': len(v), 'median': round(v[len(v) // 2], 3),
            'p99': round(p99, 3), 'worst': round(v[-1], 3)}


def timing(b, setchg: Dict[str, int], jobs: int = 2,
           work_root: Path = OUT) -> Dict:
    """Each frame and close of the checkpoint (fill $A5, no write log)
    under each profile with --cost-timed: the routine alone in phase 30
    (t_frame's m_display, t_close's m_close), ms by kind; the image's load
    (a run without calls: the driver's far_pload of MENUW's pages, phase
    0) and the open's save alone (t_save: mv_amem)."""
    import shutil
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    from native import s2run as SR
    js = [j for j in menu_jobs(setchg) if not j.excluded]
    root = Path(tempfile.mkdtemp(prefix='tmp-time-', dir=str(work_root)))
    out: Dict = {}

    def one(arg):
        job, prof, calls = arg
        work = root / ('%s-%s-%s' % (job.name, prof, calls[0].routine
                                       if calls else 'load'))
        try:
            recs, _ = job_records(b, job, 0xA5, False)
            r = run_calls(b, recs, calls, 0xA5, work, SNAP, profile=prof)
            if r.ended() != 'stop':
                raise MenuError('%s: %s' % (job.name, r.ended()))
            return job, prof, calls, SR.phase_ms(r, prof)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    try:
        for prof in PROFILES:
            work_list = [(j, prof, [call_of(j)]) for j in js]
            first = js[0]
            work_list += [(first, prof, []),
                          (first, prof, [SR.Call('t_save')]),
                          (first, prof, [SR.Call('t_tables')])]
            kinds: Dict[str, List[float]] = {}
            res: Dict = {}
            with ThreadPoolExecutor(jobs) as ex:
                for job, p_, calls, ms in ex.map(one, work_list):
                    if not calls:
                        res['load'] = round(ms.get(0, 0.0), 3)
                    elif calls[0].routine in ('t_save', 't_tables'):
                        res[calls[0].routine[2:]] = round(ms.get(30, 0.0), 3)
                    else:
                        kinds.setdefault(job.kind, []).append(
                            ms.get(30, 0.0))
            for k, v in kinds.items():
                res[k] = stats(v)
            out[prof] = res
    finally:
        shutil.rmtree(str(root), ignore_errors=True)
    return out


# ---------------------------------------------------------------------------
# The planted bugs (each in a scratch copy of the sources)
# ---------------------------------------------------------------------------

class Plant(NamedTuple):
    name: str
    what: str
    source: str                 # the file of src/native
    old: str
    new: str
    check: str                  # frames, chains, responders
    names: Tuple                # the jobs, sessions or calls checked


PLANTS = (
    Plant('gray-nibble', 'the gray of the right nibble from the left',
          's2_mvid.s',
          '@lo:    tya\n        and #$0F\n        ora S2M_T\n',
          '@lo:    tya\n        lsr a\n        lsr a\n        lsr a\n'
          '        lsr a\n        ora S2M_T\n', 'frames',
          ('f000001', 'f000008')),
    Plant('skull-old', 'the skull\'s old rectangle not restored',
          's2_mvid.s', '        stz S2M_A+1\n        jsr mv_restore\n@new:',
          '        stz S2M_A+1\n@new:', 'frames', ('f000002', 'f000004')),
    Plant('save-length', 'the save request with a wrong length',
          's2_mvid.s', '        .word SAVE_N\n',
          '        .word SAVE_N - $100\n', 'chains', ('f000001',)),
    Plant('reds', 'the menu palette\'s reds from the wrong colours (the '
          'green nibble)', 's2_mvid.s',
          '        lda TMP+$201,x          ; |R - red|\n        and #$0F\n',
          '        lda TMP+$200,x          ; |R - red|\n        lsr a\n'
          '        lsr a\n        lsr a\n        lsr a\n        and #$0F\n',
          'frames', ('f000008', 'f000043')),
    Plant('sound', 'a menu sound not started (back to the parent menu)',
          's2_menu.s', '@sw:    lda #SFX_SWTCHX\n        ; (on to sound)\n',
          '@sw:    sec\n        rts\n', 'responders', ()),
)


def planted(setchg: Dict[str, int], data: Dict, jobs: int = 2,
            only: Optional[Sequence[str]] = None) -> Dict:
    """Each planted bug in a scratch copy of s2_menu.s and s2_mvid.s, built
    into a scratch directory, and the checks that must catch it."""
    import shutil
    import tempfile
    from native import s2run as SR
    out = {}
    for pl in PLANTS:
        if only is not None and pl.name not in only:
            continue
        root = Path(tempfile.mkdtemp(prefix='tmp-plant-', dir=str(OUT)))
        try:
            src = root / 'src'
            src.mkdir()
            for f in ('s2_menu.s', 's2_mvid.s'):
                shutil.copy(str(ROOT / 'src' / 'native' / f), str(src / f))
            text = (src / pl.source).read_text()
            if text.count(pl.old) != 1:
                raise MenuError('%s: the planted text is not in %s once'
                                % (pl.name, pl.source))
            (src / pl.source).write_text(text.replace(pl.old, pl.new))
            build = root / 'build'
            SR.make('s2menu1', variables=['S2M1SRC=%s' % src,
                                          'S2M1_DIR=%s' % build])
            b = SR.load_build(build, 's2m1t', 'MENUW')
            if pl.check == 'frames':
                r = check_frames(b, setchg, jobs, root, names=pl.names)
            elif pl.check == 'chains':
                r = check_chains(b, setchg, data, jobs, root, only=pl.names)
            else:
                r = check_responders(b, data, 0xA5, jobs, root)
            out[pl.name] = {'what': pl.what, 'check': pl.check,
                            'caught': bool(r['problems']),
                            'problems': len(r['problems']),
                            'first': r['problems'][:2]}
        finally:
            shutil.rmtree(str(root), ignore_errors=True)
    return out


# ---------------------------------------------------------------------------
# Sizes, the report
# ---------------------------------------------------------------------------

BUDGET = 5000                   # s2menu1's (SCREENS.md 4.1, 7.3)
DATA_BUDGET = 2500              # MENUW's names and strings (4.1's split)
OWN_MODULES = ('s2_menu', 's2_mvid')


def module_segments(text: str) -> Dict[str, Dict[str, int]]:
    """Each module's bytes in each segment of the room (an ld65 map)."""
    out: Dict[str, Dict[str, int]] = {}
    module = None
    part = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    for line in part.splitlines():
        if line and not line.startswith(' ') and line.rstrip().endswith(':'):
            module = Path(line.strip()[:-1].split('(')[0]).stem
            continue
        f = line.split()
        if module and f and f[0] in S.IMG_SEGMENTS:
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            out.setdefault(module, {})[f[0]] = size
    return out


def sizes(obj: Path = OUT) -> Dict:
    """The release-like image s2m1's size table (s2layout's), this part's
    modules, and the room this part asks for (S2MENU1-2: $6600-$A4FF)."""
    from native import s2run as SR
    b = SR.load_build(obj, 's2m1', 'MENUW')
    ms = SR.module_sizes(b)
    rows, problems = S.check_map('MENUW', (obj / 's2m1.map').read_text())
    own = {k: v for k, v in ms.modules.items() if k in OWN_MODULES}
    segs = module_segments((obj / 's2m1.map').read_text())
    code = sum(segs.get(m, {}).get('S2CODE', 0) for m in OWN_MODULES)
    data = sum(v for m in OWN_MODULES for k, v in segs.get(m, {}).items()
               if k != 'S2CODE')
    out = {'table': rows, 'problems': problems, 'own': own,
           'own_total': sum(own.values()), 'budget': BUDGET,
           'code': code, 'data': data, 'data_budget': DATA_BUDGET,
           'segments': {m: segs.get(m, {}) for m in OWN_MODULES},
           'glue': ms.modules.get('s2_menut', 0),
           'extent': ['$%04X' % ms.extent[0], '$%04X' % (ms.extent[1] - 1)],
           'room_end': '$%04X' % ROOM_END}
    if ms.extent[1] > ROOM_END:
        out['problems'].append('MENUW ends at $%04X, past the room this '
                               'part asks for ($%04X)' % (ms.extent[1] - 1,
                                                          ROOM_END - 1))
    return out


def report(args, jobs: int = 2) -> Dict:
    from native import s2run as SR
    out: Dict = {}
    if not args.no_build:
        SR.make('s2menu1')
    if args.capture or not CALLS_FILE.exists():
        capture()
    data = load_calls()
    setchg = settings_by_frame(data)
    b = SR.load_build(OUT, 's2m1t', 'MENUW')
    out['sizes'] = sizes()
    out['frames'] = check_frames(b, setchg, jobs)
    out['responders'] = check_responders(b, data, 0xA5, jobs)
    out['tickers'] = check_tickers(b, data, 0xA5, jobs)
    out['chains'] = check_chains(b, setchg, data, jobs)
    if args.timing:
        out['timing'] = timing(b, setchg, jobs)
    if args.planted:
        out['planted'] = planted(setchg, data, jobs)
    problems = sum(len(out[k]['problems']) for k in
                   ('sizes', 'frames', 'responders', 'tickers', 'chains'))
    if args.planted:
        problems += sum(1 for v in out['planted'].values() if not v['caught'])
    out['ok'] = problems == 0
    (OUT / 'report.json').write_text(json.dumps(out, indent=1) + '\n')
    return out


def write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)


def summary(out: Dict) -> str:
    lines = ['s2menu1: %s' % ('ok' if out.get('ok') else 'PROBLEMS')]
    sz = out.get('sizes')
    if sz:
        lines.append('sizes: own %d B (%s): code %d of %d B, data %d of '
                     '%d B; MENUW %s-%s; %s' % (
            sz['own_total'], ', '.join(
                '%s %d' % kv for kv in sorted(sz['own'].items())),
            sz['code'], sz['budget'], sz['data'], sz['data_budget'],
            sz['extent'][0], sz['extent'][1], '; '.join(sz['problems'])
            or 'within its room'))
    for key in ('frames', 'responders', 'tickers', 'chains'):
        r = out.get(key)
        if r is None:
            continue
        info = {k: v for k, v in r.items() if k != 'problems'}
        lines.append('%s: %s, %d problems' % (key, info, len(r['problems'])))
        lines += ['  ' + x for x in r['problems'][:10]]
    if 'timing' in out:
        lines.append('timing (ms): %s' % json.dumps(out['timing']))
    for name, v in out.get('planted', {}).items():
        lines.append('planted %s (%s): %s by %s, %d problems, e.g. %s' % (
            name, v['what'], 'caught' if v['caught'] else 'NOT CAUGHT',
            v['check'], v['problems'], v['first'][:1]))
    return '\n'.join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--inc', type=Path)
    parser.add_argument('--capture', action='store_true',
                        help='the reference\'s call log again')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--timing', action='store_true')
    parser.add_argument('--planted', action='store_true')
    parser.add_argument('--all', action='store_true',
                        help='--capture --check --timing --planted')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args(argv)
    try:
        if args.inc:
            write_if_changed(args.inc, inc_text())
            return 0
        if args.all:
            args.capture = args.check = args.timing = args.planted = True
        if not (args.capture or args.check or args.timing or args.planted):
            parser.print_help()
            return 2
        out = report(args, args.jobs)
    except MenuError as error:
        print('s2menu1: %s' % error, file=sys.stderr)
        return 1
    print(summary(out))
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
