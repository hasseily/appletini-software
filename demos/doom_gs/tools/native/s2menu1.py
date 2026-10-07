#!/usr/bin/env python3
"""The menu's generated include (`--inc OUT`, gen/s2menu1.inc): what
src/native/s2_menu.s and src/native/s2_mvid.s read beyond s2.inc and
rlayout.inc: the game's places (read only), the message
symbols' ids (llayout.symbol_list()), the menu's sounds, MENUW's places
(s2layout's), the patches of upstream's `lumpNames` [R m_menu65.s:161-213]
and the font `STCFN033`-`STCFN095` with each patch's place in the 2D store
(s2data.json) and its header (read from the store's own bytes, GFX.1), and
the skulls' box that `M_Init` computes [R m_menu65.s:613-635].

Usage:  python3 tools/native/s2menu1.py --inc OUT/s2menu1.inc
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

# the game's places the menu reads and writes (read only)
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

def _runtime(what: str) -> int:
    return next(lo for lo, _, w in S.IMAGE['MENUW'].runtime if w == what)


# MENUW's places (s2layout's MENUW): PALST
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
ROOM_END = S.IMAGE['MENUW'].stored[1]       # $A500

# the zero page of the menu ($80-$AF, SCREENS.md's S2M_*)
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
             'docs/SCREENS.md). Do not edit.', '',
             '; the game\'s places (read only)',
             'SM_PLMSG        = $%04X ; player.message: tag (1 a symbol), '
             'id (2), offset (2)' % (LL.G['G_PLAYER'] + pl['message'])]
    for name, g, why in GAME_PLACES:
        lines.append('%-15s = $%04X ; %s' % (name, LL.G[g], why))
    from native import glayout as GL
    lines += ['SM_GA           = $%02X   ; sc_start\'s arguments (GAME.md, '
              'glayout GA_RANGE)' % GL.GA_RANGE[0]]
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
    # REQ_* are s2.inc's)
    lines += ['', '; MENUW\'s places (s2layout\'s MENUW)']
    for name, at, why in MENUW_PLACES:
        lines.append('%-15s = $%04X ; %s' % (name, at, why))
    lines += ['S2M_AMEMSTOP    = $%02X ; PL_STATUS: the save failed'
              % AMEM_STOP,
              'S2M_BANDROWS    = %d' % BAND_ROWS,
              'S2M_FBPAGES     = %d' % FBPAGES,
              'S2M_ROOM_END    = $%04X' % ROOM_END,
              '', '; the menu\'s zero page ($80-$AF, SCREENS.md)']
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



def write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--inc', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        write_if_changed(args.inc, inc_text())
    except MenuError as error:
        print('s2menu1: %s' % error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
