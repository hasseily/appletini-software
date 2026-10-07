#!/usr/bin/env python3
"""Part s2amap (docs/SCREENS.md): the automap's full mode, the
image AMAPW (src/native/s2_am.s, s2_amline.s). Writes the generated
include s2amap.inc: the places the native code reads beyond s2.inc,
upstream's automap keys, playerArrow, doorColors and the line colours,
read from the release and the game's layout.

Usage:  python3 tools/native/s2amap.py --inc OUT
"""

import argparse
import struct
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, rlayout as R, s2layout as S  # noqa: E402

# ---------------------------------------------------------------------------
# Upstream's automap (am_map65.s)
# ---------------------------------------------------------------------------

PW_ALLMAP = 4
# the line drawer's colours (am_map65.s COLOR_*), by the native index
COLOURS = (('WALL', 23), ('FCHG', 55), ('CCHG', 215), ('CLSD', 208),
           ('RDOR', 175), ('BDOR', 204), ('YDOR', 231), ('TELE', 119),
           ('SECR', 252), ('UNSN', 104))

# S2STATE's SS_AMSEG holds the frame's clipped lines (8 bytes a line:
# 1,520 lines and the arrow's 7)
SEG_SIZE = 8
SEG_MAX = S.SS_SIZE['SS_AMSEG'] // SEG_SIZE


# ---------------------------------------------------------------------------
# The release: symbols, constants
# ---------------------------------------------------------------------------

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
        ('AM_GPLAYER', LL.G['G_PLAYER'], 'the player (the game\'s)'),
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
             'SCREENS.md). Do not edit.', '']
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


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--inc', type=Path, required=True)
    args = ap.parse_args(argv)
    write_inc(args.inc)
    return 0


if __name__ == '__main__':
    sys.exit(main())
