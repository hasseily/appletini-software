#!/usr/bin/env python3
"""The HUD's texts of the screens' first half (docs/SCREENS.md, part
s2hud): the message ids' text table, the maps' titles and the font
table that src/native/s2_hu.s (P2DW) draws from, generated as ca65 data.

The message ids are the game's: natively `player.message` is a
reference to a symbol, its id the index of the symbol in
`llayout.symbol_list()` (every rodata label of the link map, sorted:
the list the bridge's manifest numbers symbols with [R llayout.py
symbol_list, bridge/layout.py native_v1]), so the HUD's table and the
game agree by construction. The table holds the **message
symbols**: the labels referenced as `.word0 NAME` (an immediate's or a
table's address) in the units of upstream's sources that store a value
into `player.message` (`sta`/`stx` of `OFS_PL_MESSAGE`: am_map65.s,
m_cheat65.s, m_menu65.s, p_doors65.s, p_inter65.s), and whose bytes in
the release start with a NUL-terminated string of 1 to 34 printable
characters (HU_MAXLINELENGTH [R hu_stuff65.s:17]). The rule takes a few
labels that are never messages (`keyNames`, whose first name is "A", and
the menu strings `txComma`, `txControls`, `txNone`, `txPress`): harmless.

The titles are upstream's `mapNames` table [R hu_stuff65.s:55-68], read
from the release's memory; each is a table entry with the id
$FE00 + map (its key in the bank table KEY_TITLE + map) (HU_Start's `strcpy(title, mapnames[gamemap - 1])`
[R hu_stuff65.s:100-117]). The font is `STCFN033`..`STCFN095`
(HU_FONTSTART '!' to HU_FONTEND '_' [R hu_stuff65.s:18-19]): each
glyph's place in the 2D store (part s2data's `s2data.json`) and its
width (the patch's, from DOOM1.WAD; upstream reads `patch->width`
[R hu_stuff65.s:175-176]).

The texts live in RamWorks (S2STATE's SS_HUDMSG, a bank file HUDTXT.1;
SCREENS.md: P2DW's room has no place for them), each line's text fetched
when its id changes; P2DW keeps the font table only.

Usage:  python3 tools/native/s2msgs.py --inc OUT/s2msgs.inc (the font)
        python3 tools/native/s2msgs.py --bank OUT/HUDTXT.1
        python3 tools/native/s2msgs.py --hud-inc OUT/s2hud.inc
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, rlayout as R, s2layout as S  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
UPSTREAM = BUILD / 'upstream' / 'src' / 'iigs'
S2DATA_JSON = BUILD / 'native' / 'm11' / 's2data' / 's2data.json'
FORMAT = 's2msgs 1'

HU_MAXLINELENGTH = 34           # [R hu_stuff65.s:17]
FONT_LO, FONT_HI = 0x21, 0x5F   # '!' .. '_' [R hu_stuff65.s:18-19]
NMAPS = 9                       # mapNames [R hu_stuff65.s:55-68]
TITLE_ID = 0xFE00               # a title's id: TITLE_ID + map
TEST_ID = 0x00E6                # the messages' ids are below it
NONE_ID = 0xFFFF                # "no line" (hu_start: the empty text)
# the bank table (SS_HUDMSG): an index of 256 words (the entry's address
# in the bank, 0: none) by key, then the entries: the text padded to 35
# bytes and its length (36 bytes: P_TITLE/P_MESSAGE's TL_TEXT and TL_LEN's
# low byte). A message's key is its id (below TEST_ID), a title's
# KEY_TITLE + map
KEY_TITLE = 0xF0
ENTRY = 36
# the table's place in S2STATE (s2layout's)
SS_HUDMSG, SS_HUDMSG_SIZE = S.SS['SS_HUDMSG'], S.SS_SIZE['SS_HUDMSG']
# a unit stores a message: `sta`/`stx` (not `stz`) of OFS_PL_MESSAGE
STORE_RE = re.compile(r'^\s*(?:[\w$]+:)?\s*st[ax]\s+.*OFS_PL_MESSAGE',
                      re.M)
WORD0_RE = re.compile(r'\.word0\s+([A-Za-z_]\w*)')


class S2MsgsError(Exception):
    pass


class Entry(NamedTuple):
    id: int
    name: str                   # unit:label or title N
    text: bytes


# ---------------------------------------------------------------------------
# The release's labels and memory
# ---------------------------------------------------------------------------

_MEM = None


def memory():
    global _MEM
    if _MEM is None:
        from ref816 import refimage, title
        if not title.MEMORY.exists():
            raise S2MsgsError('%s is missing: run python3 '
                              'tools/ref816/make_image.py' % title.MEMORY)
        _MEM = refimage.load(refimage.read(title.MEMORY))
    return _MEM


_LABELS: Optional[Dict[str, Tuple[int, int]]] = None


def rodata_labels() -> Dict[str, Tuple[int, int]]:
    """Every rodata label of the link map: unit:label -> (address, its
    extent: the bytes to the next label of its fragment or the
    fragment's end)."""
    global _LABELS
    if _LABELS is None:
        from bridge.linkmap import Symbols
        out = {}
        for f in Symbols().fragments:
            if f.kind != 'rodata':
                continue
            labels = sorted(f.labels, key=lambda lb: lb.address)
            for k, lb in enumerate(labels):
                end = labels[k + 1].address if k + 1 < len(labels) \
                    else f.address + f.size
                out[lb.ref] = (lb.address, end - lb.address)
        _LABELS = out
    return _LABELS


def string_of(ref: str) -> Optional[bytes]:
    """The string the label's bytes start with, when it is 1 to
    HU_MAXLINELENGTH printable characters and its NUL lies within the
    label's extent, else None."""
    address, extent = rodata_labels()[ref]
    data = memory().get(address, min(extent, HU_MAXLINELENGTH + 1))
    end = data.find(0)
    if end < 1:
        return None
    text = data[:end]
    if not all(0x20 <= c < 0x7F for c in text):
        return None
    return bytes(text)


def symbol_ids() -> Dict[str, int]:
    """The game's numbering of symbols: the index in
    llayout.symbol_list()."""
    return {s: k for k, s in enumerate(LL.symbol_list())}


def by_address() -> Dict[int, str]:
    """A rodata label's address (24 bits) -> unit:label."""
    return {a: ref for ref, (a, _) in rodata_labels().items()}


# ---------------------------------------------------------------------------
# The message symbols, the titles, the font
# ---------------------------------------------------------------------------

def message_units(upstream: Path = UPSTREAM) -> List[str]:
    out = []
    for p in sorted(upstream.glob('*.s')):
        if p.name == 'cal_integer.s':       # (never read: ground rules)
            continue
        if STORE_RE.search(p.read_text(errors='replace')):
            out.append(p.name)
    return out


def resolve(unit: str, name: str) -> Optional[str]:
    """A label referenced in `unit`: its own, else the one public label
    of that name (strGameSaved is g_game65.s's, referenced by
    m_menu65.s)."""
    labels = rodata_labels()
    if '%s:%s' % (unit, name) in labels:
        return '%s:%s' % (unit, name)
    found = [r for r in labels if r.split(':', 1)[1] == name]
    return found[0] if len(found) == 1 else None


def message_symbols(upstream: Path = UPSTREAM) -> List[Entry]:
    """The message symbols (the module's rule), by id."""
    ids = symbol_ids()
    refs = set()
    for unit in message_units(upstream):
        text = (upstream / unit).read_text(errors='replace')
        for name in WORD0_RE.findall(text):
            ref = resolve(unit, name)
            if ref is not None and string_of(ref) is not None:
                refs.add(ref)
    out = []
    for ref in refs:
        if ref not in ids:
            raise S2MsgsError('%s is not in llayout.symbol_list()' % ref)
        out.append(Entry(ids[ref], ref, string_of(ref)))
    return sorted(out)


def titles() -> List[Entry]:
    """upstream's mapNames: NMAPS pointers (word0, word2 each) to the
    titles [R hu_stuff65.s:64-68]."""
    address, extent = rodata_labels()['hu_stuff65.s:mapNames']
    if extent != 4 * NMAPS:
        raise S2MsgsError('mapNames holds %d bytes, not %d' % (extent,
                                                              4 * NMAPS))
    table = memory().get(address, extent)
    names = by_address()
    out = []
    for k in range(NMAPS):
        ptr = int.from_bytes(table[4 * k:4 * k + 2], 'little') | \
            table[4 * k + 2] << 16
        ref = names.get(ptr)
        text = string_of(ref) if ref else None
        if text is None:
            raise S2MsgsError('mapNames[%d] names no title string' % k)
        out.append(Entry(TITLE_ID + k + 1, ref, text))
    return out


class Glyph(NamedTuple):
    char: int
    name: str
    bank: int
    address: int
    width: int
    height: int
    top: int


def font(s2data_json: Path = S2DATA_JSON) -> List[Glyph]:
    """'!'..'_': each glyph's place in the 2D store and its patch's
    width, height and top offset (DOOM1.WAD's)."""
    from native import s2data as D
    if not s2data_json.exists():
        raise S2MsgsError('%s is missing: run make -C src/native -f m11.mk '
                          'part P=s2data' % s2data_json)
    lumps = {x['name']: x for x in json.loads(s2data_json.read_text())[
        'lumps']}
    wad = D.read_wad()
    out = []
    for c in range(FONT_LO, FONT_HI + 1):
        name = 'STCFN%03d' % c
        if name not in lumps or name not in wad:
            raise S2MsgsError('%s is not in the 2D store or the WAD' % name)
        p = D.parse_patch(wad[name])
        x = lumps[name]
        out.append(Glyph(c, name, x['bank'], x['address'], p.width, p.height,
                         p.top))
    return out


def entries() -> List[Entry]:
    out = message_symbols() + titles()
    ids = [e.id for e in out]
    if len(set(ids)) != len(ids) or NONE_ID in ids:
        raise S2MsgsError('the ids are not distinct')
    big = [e for e in out if TEST_ID <= e.id < TITLE_ID]
    if big:
        raise S2MsgsError('the message %s has the id $%04X: the bank '
                          'table keys messages below $%02X' % (
                              big[0].name, big[0].id, TEST_ID))
    return out


def key_of(ident: int) -> int:
    if ident >= TITLE_ID:
        return KEY_TITLE + ident - TITLE_ID
    return ident


def bank_table() -> bytes:
    """SS_HUDMSG's bytes: the index, then the entries."""
    index = bytearray(512)
    data = bytearray()
    for e in entries():
        k = key_of(e.id)
        at = SS_HUDMSG + 512 + len(data)
        index[2 * k:2 * k + 2] = at.to_bytes(2, 'little')
        data += e.text.ljust(ENTRY - 1, b'\0') + bytes([len(e.text)])
    out = bytes(index + data)
    if len(out) > SS_HUDMSG_SIZE:
        raise S2MsgsError('the table holds %d bytes, its room %d' % (
            len(out), SS_HUDMSG_SIZE))
    return out


def bank_file() -> bytes:
    """The table as a bank file (LEVELS.md's A2DM format, lstore's) for
    S2STATE at SS_HUDMSG."""
    from native import lstore
    return lstore.bank_file([(S.S2STATE, SS_HUDMSG, bank_table())])


# ---------------------------------------------------------------------------
# The ca65 data
# ---------------------------------------------------------------------------

def _bytes(data: Sequence[int]) -> List[str]:
    return ['        .byte %s' % ', '.join('$%02X' % b for b in
                                         data[k:k + 12])
            for k in range(0, len(data), 12)]


def table_text() -> str:
    """hu_fbank, hu_flo, hu_fhi, hu_fwid: the font's glyphs, indexed by the
    character less '!'."""
    lines = ['; Generated by tools/native/s2msgs.py (part s2hud, '
             'docs/SCREENS.md).', '; Do not edit. %s' % FORMAT, '']
    gs = font()
    for label, values in (('hu_fbank', [g.bank for g in gs]),
                          ('hu_flo', [g.address & 0xFF for g in gs]),
                          ('hu_fhi', [g.address >> 8 for g in gs]),
                          ('hu_fwid', [g.width for g in gs])):
        lines.append('%s:' % label)
        lines += _bytes(values)
    return '\n'.join(lines) + '\n'


def hud_inc_text() -> str:
    """The places s2_hu.s and s2t_hu.s need beyond s2.inc and rlayout.inc:
    the game's (read only). P_TXTTEXT, P_MSGFILL, P_MAPFILL and SS_HUDMSG
    are s2.inc's."""
    pl = dict((p[0], at) for p, _, at in LL.player_layout())
    if 'message' not in pl:
        raise S2MsgsError('the player has no message field')
    rows = [
        ('HU_PLMSG', LL.G['G_PLAYER'] + pl['message'],
         'player.message: tag (0 NULL), id low, id high, offset (2)'),
        ('HU_SHOWMSG', LL.G['G_SHOWMSG'], 'showMessages (a word)'),
        ('HU_KEEP', LL.G['G_MSGKEEP'],
         '_g_message_dontfuckwithme (a word)'),
        ('HU_GAMEMAP', LL.G['G_GAMEMAP'], 'gamemap (a word)'),
        ('HU_AUTOMAP', R.FRAME['AUTOMAP'],
         'the frame block\'s AUTOMAP: bit 0 AM_ACTIVE'),
        ('HU_VIEWTOP', R.FRAME['VIEWTOP'],
         'the frame block\'s VIEWTOP'),
    ]
    lines = ['; Generated by tools/native/s2msgs.py --hud-inc (part '
             's2hud). Do not edit.', '']
    for name, value, why in rows:
        lines.append('%-15s = $%04X ; %s' % (name, value, why))
    lines += ['HU_TITLE_ID     = $%04X' % TITLE_ID,
              'HU_NONE_ID      = $%04X' % NONE_ID,
              'HU_KEY_TITLE    = $%02X' % KEY_TITLE,
              'HU_KEY_END      = $%02X ; (the end of the messages\' keys)'
              % KEY_TITLE]
    return '\n'.join(lines) + '\n'


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--inc', type=Path)
    parser.add_argument('--hud-inc', type=Path)
    parser.add_argument('--bank', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.inc:
            write_atomic(args.inc, table_text())
        if args.bank:
            data = bank_file()
            if not args.bank.exists() or args.bank.read_bytes() != data:
                args.bank.parent.mkdir(parents=True, exist_ok=True)
                tmp = args.bank.with_name(args.bank.name + '.tmp')
                tmp.write_bytes(data)
                tmp.replace(args.bank)
        if args.hud_inc:
            write_atomic(args.hud_inc, hud_inc_text())
    except S2MsgsError as error:
        print('s2msgs: %s' % error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
