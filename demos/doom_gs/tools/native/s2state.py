#!/usr/bin/env python3
"""Injection of milestone 11's reference cases into a native machine
(docs/SCREENS.md 6.2, part s2cap), and the read back.

A case of tools/native/s2cap.py (a frame or an event) gives, for one
screen of 1.6 (`s2layout.field_map()`), each upstream field by its symbol
at the case's start (PD0, or the carried STCACHE), encoded into its native
place: 'game' (milestones 9-10's places: llayout.G, the frame block, the
render inputs; the player at G_PLAYER through llayout.player_layout, read
only), 'card' (the tic-side block S2T_* at the build's S2T_BASE), 'state'
(the image's own state block, at its place in S2STATE: s2layout.SS_* and
the block's W address, request S2LAY-2), 'palst' (SS_PALST), 'bank'
(S2STATE's SS_*). Encodings: word, byte, sxbyte, flag, long, bytes, dropped,
gfx (the field map's; gfx: upstream's lump numbers as 2D store handles,
`gfx_handles()`). The screen goes into aux 0 $2000-$9FFF. Every byte the case
does not define keeps the run's fill ($A5 in one run, $5A in the other:
s2run.FILLS); the rows the case leaves undefined (X1, `Case.blank`) too.
With `poison=True` every screen byte the reference's frame marked (the
marks of each PDF and PDS dump: rows [DRY0, DRY1), bytes [DRB, DRE)) and
every SCB and palette byte it wrote (newColors and the wipe, from the
palette state at I_FinishUpdate's entry, and every one that changed) is
the fill too, so the native drawer must make all of them.

`read_back(machine, injection)` decodes every place back into upstream's
value and lists the differences; `poison_problems` checks the screen of a
poisoned injection. Fields whose native form belongs to a later part (the
HUD's text records, the automap's byte list, TINTPAL's place in S2PAL, the
level's records, the player's message as an id, the frame block's
AUTOMAP) are listed as deferred, with the reason, never guessed.

`keys_poke(names, table)` writes a ref816 --poke-file that puts a key
table (128 entries: a Doom key and a character, upstream's keyTable
format) and its names (8 bytes each, upstream's keyNames) into the
reference before its first frame, so upstream's own key setup page draws
the //e's (1.5.3). `apple2e_keys()` is part plinput's table
(tools/native/plkeys.py, SCREENS.md 2.4; request PLINPUT-6, applied in
wave 5's integration).

Usage:  python3 tools/native/s2state.py RUN [--frame K] [--screen stbar]
        (inject a case and read it back on the host; --a2vm on a2vm too)
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, rlayout as R, s2cap as C, \
    s2layout as S  # noqa: E402

Record = Tuple[int, int, int, bytes]    # s2run's: kind, bank, address, data
MAIN, AUX, LC, LC1 = 0, 1, 2, 3
SCREENS = ('stbar', 'hud', 'palettes', 'menus', 'automap', 'intermission',
           'finale')
SHR_LO, SHR_HI = 0x2000, 0xA000
PALETTE_LO, SCB_LO = 0x9E00, 0x9D00
NO_PALETTE_CHANGE = 100         # newpal's "no change" [R i_viigs65.s:66]
TINT_ROW = 384                  # [R i_viigs65.s:85]

# the fields whose native form a later part decides: (ref prefix, why)
DEFERRED = (
    ('frame.AUTOMAP', 'the frame block\'s AUTOMAP is set by the frame '
     'driver (milestone 10, request R7), not a 2D input'),
    ('weaponinfo.ammo', 'GTAB, milestone 10\'s static table'),
    ('GSVIEWn', 'the level\'s record LVC (milestone 9), loaded with the '
     'level'),
    ('LVG0 lines', 'the level\'s lines (milestone 9)'),
    ('LNMAP', 'the lines\' mapped bits (milestones 9-10)'),
    ('player.message', 'milestone 10\'s reference (a tag, the symbol\'s '
     'index in llayout.symbol_list(): requests R5, S2HUD-6); part s2hud\'s '
     'cases resolve it'),
    ('am_map65.s:AM_LISTS', 'the old list (the half not at AM_LB, AM_ON '
     'bytes) as native entries by band, A_ON and A_OB from it '
     '(s2amap.native_list, encode_state; request S2AMAP-1)'),
    ('i_viigs65.s:TINTPAL', 'its place in S2PAL is s2pal\'s'),
    # (request S2WI-7: not in the field map; named so that a field added
    # for it is deferred, not guessed)
    ('i_viigs65.s:NIBTAB', 'built from the picture on the screen, or the '
     'level\'s records: part s2pal\'s model (s2palmodel.build_nibtab)'),
)


class InjectError(Exception):
    pass


class Place(NamedTuple):
    """One field's native bytes: where, how, and upstream's value."""
    ref: str
    storage: str                # main, aux, lc (the card $C000-$FFFF)
    bank: int
    address: int
    enc: str
    size: int                   # native bytes
    value: Any                  # upstream's: an int, or bytes ('bytes')
    signed: bool = False


class Injection(NamedTuple):
    screen: str
    records: List[Record]
    places: List[Place]
    deferred: List[Tuple[str, str]]
    unfit: List[Tuple[str, int, str]]   # (ref, value, encoding)
    fill: int
    screen_bytes: Optional[bytes]       # what aux 0 $2000-$9FFF holds
    poisoned: Tuple[int, ...]           # screen offsets set to the fill


# ---------------------------------------------------------------------------
# Upstream's values from a case
# ---------------------------------------------------------------------------

_OFS: Optional[Dict[str, int]] = None


def offsets() -> Dict[str, int]:
    """offsets.inc's OFS_* (the player's fields)."""
    global _OFS
    if _OFS is None:
        # (each cache here is built whole, then published in one
        # assignment: the checks' job threads call these at once)
        ofs = {}
        path = C.ROOT / 'build' / 'upstream' / 'src' / 'iigs' / \
            'offsets.inc'
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] == '.equ' and \
                    parts[0].startswith('OFS_PL_'):
                ofs[parts[0]] = int(parts[2], 0)
        _OFS = ofs
    return _OFS


def upstream_address(ref: str) -> int:
    return C.sym(ref.split('(')[0])


def deferred_why(ref: str) -> Optional[str]:
    for prefix, why in DEFERRED:
        if ref.startswith(prefix):
            return why
    return None


def state_dump(case: C.Case) -> C.Dump:
    return case.before


def read_upstream(case: C.Case, ref: str, size: int) -> bytes:
    """`size` bytes of the upstream symbol `ref` at the case's start."""
    address = upstream_address(ref)
    if ref == 'i_viigs65.s:STCACHE':
        return case.carried('STCACHE')
    return state_dump(case).get(address, size)


# ---------------------------------------------------------------------------
# Native places
# ---------------------------------------------------------------------------

def g_width(name: str) -> int:
    """A milestone 10 global's bytes (the distance to the next, at most
    4)."""
    at = LL.G[name]
    after = sorted(a for a in LL.G.values() if a > at)
    return min(4, (after[0] - at) if after else 2)


def native_place(f: S.Field, build: str = 'test'
                 ) -> Tuple[str, int, int]:
    """(storage, bank, address) of a field's native first byte."""
    name, _, k = f.place.partition('+')
    k = int(k) if k else 0
    if f.kind == 'game':
        where = S.resolve_game(f.place)
        if where is None or where[0] != 'main':
            raise InjectError('%s: no main place' % f.ref)
        return 'main', 0, where[1]
    if f.kind == 'card':
        base = S.BUILDS[build].s2t_base
        return 'lc', 0, base + S.S2T[name] + k
    if f.kind == 'state':
        image = S.SCREEN_IMAGE[f.screen]
        block, w = S.OWN_STATE[image]
        at = S.state_places(image)[name] + k
        return 'aux', S.S2STATE, S.SS[block] + at - w
    if f.kind == 'palst':
        return 'aux', S.S2STATE, S.SS['SS_PALST'] + \
            S.palst_places()[name] + k
    if f.kind == 'bank':
        if name in S.SS:
            return 'aux', S.S2STATE, S.SS[name] + k
    raise InjectError('%s: no native place for %s %s' % (f.ref, f.kind,
                                                       f.place))


_GFX: Optional[Dict[int, int]] = None


def gfx_handles() -> Dict[int, int]:
    """The release's lump number -> its 2D store handle (part s2data's
    handles_of; request S2DATA-4); $FFFF -> $FF."""
    global _GFX
    if _GFX is None:
        from native import s2data as D, umodel as U
        gfx = dict(D.handles_of(U.Release()))
        if 0xFF in gfx.values():
            raise InjectError('handle $FF is a lump\'s, not "none"')
        gfx[0xFFFF] = 0xFF
        _GFX = gfx
    return _GFX


def gfx_encode(words: Sequence[int]) -> Tuple[bytes, bool]:
    h = gfx_handles()
    return bytes(h.get(w, 0xFF) for w in words), all(w in h for w in words)


def gfx_decode(data: bytes) -> Tuple[int, ...]:
    back = {v: k for k, v in gfx_handles().items()}
    return tuple(back.get(b, -1) for b in data)


_READY: Optional[Tuple[int, int, int]] = None
READY_NONE = 0xFD               # W_READY's NULL: st_init's (S2STBAR-1)


def ready_places() -> Tuple[int, int, int]:
    """readysrc's pointers (16-bit): &ammo[0], &largeammo,
    &_g_fps_framerate (request S2STBAR-1); NULL (before the first
    ST_createWidgets) is READY_NONE."""
    global _READY
    if _READY is None:
        ammo = C.sym('g_game65.s:_g_player') + offsets()['OFS_PL_AMMO']
        _READY = (ammo & 0xFFFF, C.sym('st_stuff65.s:largeammo') & 0xFFFF,
                  C.sym('_g_fps_framerate') & 0xFFFF)
    return _READY


def readysrc_code(ptr: int) -> Optional[int]:
    """W_READY's value pointer as ST_READY's byte, or None."""
    ammo, large, fps = ready_places()
    if ptr == 0:
        return READY_NONE
    if ptr == large:
        return 0xFE
    if ptr == fps:
        return 0xFF
    k = (ptr - ammo) & 0xFFFF
    return k // 2 if k % 2 == 0 and k // 2 < READY_NONE else None


def readysrc_ptr(code: int) -> int:
    ammo, large, fps = ready_places()
    return {READY_NONE: 0, 0xFE: large, 0xFF: fps}.get(
        code, (ammo + 2 * code) & 0xFFFF)


_MSGS: Optional[Dict[bytes, int]] = None


def msgid_of(raw: bytes) -> Optional[int]:
    """An hu_textline's (39 bytes: y, the text, its length) message id:
    s2msgs's table (the first id of a text), $FFFF for the empty line,
    None for a text the table lacks (request S2HUD-6)."""
    global _MSGS
    from native import s2hud as H, s2msgs as MS
    if _MSGS is None:
        msgs: Dict[bytes, int] = {}
        for e in MS.entries():
            if e.id < MS.TEST_ID:
                msgs.setdefault(e.text, e.id)
        _MSGS = msgs
    n = raw[H.TL_LEN] | raw[H.TL_LEN + 1] << 8
    if not n:
        return MS.NONE_ID
    text = bytes(raw[H.TL_TEXT:H.TL_TEXT + min(n, H.TL_LEN - H.TL_TEXT)])
    return _MSGS.get(text)


def encode(value: int, enc: str, size: int) -> Tuple[bytes, bool]:
    """(the native bytes, whether the value fits the encoding)."""
    if enc == 'readysrc':       # value: W_READY's pointer
        code = readysrc_code(value)
        return bytes([0 if code is None else code]), code is not None
    if enc == 'msgid':          # value: the id (msgid_of)
        return bytes([value & 0xFF, value >> 8 & 0xFF]), True
    if enc == 'word':
        return (value & 0xFFFF).to_bytes(2, 'little'), True
    if enc == 'long':
        return (value & 0xFFFFFFFF).to_bytes(4, 'little'), True
    if enc == 'byte':
        return bytes([value & 0xFF]), 0 <= value < 0x100
    if enc == 'sxbyte':
        s = value - 0x10000 if value & 0x8000 else value
        return bytes([s & 0xFF]), -128 <= s < 128
    if enc == 'flag':           # 0 or 256 natively 0 or 1 (S2PAL-5)
        return bytes([1 if value else 0]), value in (0, 256)
    raise InjectError('no encoding %s' % enc)


def decode(data: bytes, enc: str) -> int:
    if enc == 'readysrc':
        return readysrc_ptr(data[0])
    if enc == 'flag':
        return 256 if data[0] else 0
    if enc == 'sxbyte':
        v = data[0]
        return (v - 256) & 0xFFFF if v & 0x80 else v
    return int.from_bytes(data, 'little')


def player_places(case: C.Case, fields: Sequence[str]) -> List[Place]:
    """The player's fields of the field map (llayout.player_layout: the
    native offsets; offsets.inc: upstream's), ints only; mo and attacker
    are references (handles), compared as null or not: a handle is the
    injected stand-in 0 (the player's mobj) or 1 (another), $FFFF null,
    until milestone 10's mobj table is part of a case."""
    pl = C.sym('g_game65.s:_g_player')
    before = state_dump(case)
    ofs = offsets()
    out: List[Place] = []
    for path, enc, at in player_layout():
        if path[0] not in fields:
            continue
        key = 'OFS_PL_' + path[0].upper()
        up = ofs[key] + (2 * path[1] if len(path) > 1 else 0)
        ref = 'player.' + '.'.join(str(x) for x in path)
        if enc['enc'] == 'int':
            n = enc['bytes']
            v = int.from_bytes(before.get(pl + up, n), 'little')
            out.append(Place(ref, 'main', 0, LL.G['G_PLAYER'] + at,
                             'int', n, v, enc.get('signed', False)))
        elif enc['enc'] == 'handle':
            ptr = int.from_bytes(before.get(pl + up, 4), 'little')
            mo = int.from_bytes(before.get(pl + ofs['OFS_PL_MO'], 4),
                                'little')
            handle = LL.NO_HANDLE if ptr == 0 else (0 if ptr == mo else 1)
            out.append(Place(ref, 'main', 0, LL.G['G_PLAYER'] + at,
                             'handle', 2, handle))
    return out


_FIELDS: Dict[str, List[S.Field]] = {}
_PLACES: Dict[Tuple[str, str], Tuple[str, int, int]] = {}


def screen_fields(screen: str) -> List[S.Field]:
    if screen not in SCREENS:
        raise InjectError('no screen %s (one of %s)' % (screen,
                                                       ', '.join(SCREENS)))
    if screen not in _FIELDS:
        _FIELDS[screen] = [f for f in S.field_map() if f.screen == screen]
    return _FIELDS[screen]


def native_place_cached(f: S.Field, build: str) -> Tuple[str, int, int]:
    key = (f.ref + '|' + f.place + '|' + f.screen, build)
    if key not in _PLACES:
        _PLACES[key] = native_place(f, build)
    return _PLACES[key]


_PLAYER: Optional[List[Tuple[Tuple, Dict, int]]] = None


def player_layout() -> List[Tuple[Tuple, Dict, int]]:
    global _PLAYER
    if _PLAYER is None:
        _PLAYER = LL.player_layout()
    return _PLAYER


def places_of(case: C.Case, screen: str, build: str = 'test'
              ) -> Tuple[List[Place], List[Tuple[str, str]],
                         List[Tuple[str, int, str]]]:
    places: List[Place] = []
    deferred: List[Tuple[str, str]] = []
    unfit: List[Tuple[str, int, str]] = []
    player = []
    for f in screen_fields(screen):
        why = deferred_why(f.ref) or deferred_why(f.place)
        if why:
            deferred.append((f.ref, why))
            continue
        if f.enc == 'dropped':
            continue
        if f.enc == 'player':
            player.append(f.place.split('.', 1)[1])
            continue
        if f.enc == 'table':
            deferred.append((f.ref, 'a static table'))
            continue
        storage, bank, address = native_place_cached(f, build)
        if f.enc == 'game':             # milestone 10's own width
            n = g_width(f.place)
            v = int.from_bytes(read_upstream(case, f.ref, n), 'little')
            places.append(Place(f.ref, storage, bank, address, 'int', n, v))
        elif f.enc == 'gfx':
            raw = read_upstream(case, f.ref, f.size)
            words = tuple(int.from_bytes(raw[k:k + 2], 'little')
                          for k in range(0, f.size, 2))
            if not gfx_encode(words)[1]:
                unfit.append((f.ref, words[0] if len(words) == 1 else
                              int.from_bytes(raw, 'little'), 'gfx'))
                continue
            places.append(Place(f.ref, storage, bank, address, 'gfx',
                                f.native, words))
        elif f.enc == 'msgid':
            ident = msgid_of(read_upstream(case, f.ref, f.size))
            if ident is None:
                unfit.append((f.ref, int.from_bytes(read_upstream(
                    case, f.ref, f.size), 'little'), 'msgid'))
                continue
            places.append(Place(f.ref, storage, bank, address, 'msgid',
                                f.native, ident))
        elif f.enc == 'bytes':
            if f.native != f.size:
                deferred.append((f.ref, 'a native form of %d bytes for %d '
                                 '(its part\'s)' % (f.native, f.size)))
                continue
            places.append(Place(f.ref, storage, bank, address, 'bytes',
                                f.size, read_upstream(case, f.ref, f.size)))
        else:
            enc = f.enc
            v = int.from_bytes(read_upstream(case, f.ref, f.size), 'little')
            _, fits = encode(v, enc, f.native)
            if not fits:
                unfit.append((f.ref, v, enc))
                continue
            places.append(Place(f.ref, storage, bank, address, enc,
                                f.native, v))
    if player:
        places += player_places(case, player)
    return places, deferred, unfit


def place_bytes(p: Place) -> bytes:
    if p.enc == 'bytes':
        return p.value
    if p.enc == 'gfx':
        return gfx_encode(p.value)[0]
    if p.enc in ('int', 'handle'):
        return (p.value & ((1 << 8 * p.size) - 1)).to_bytes(p.size, 'little')
    return encode(p.value, p.enc, p.size)[0]


# ---------------------------------------------------------------------------
# The screen and its poison
# ---------------------------------------------------------------------------

def marked(case: C.Case) -> List[int]:
    """The screen offsets (from $2000) the reference's frame wrote: each
    PDF's and PDS's marks, the SCBs and palettes newColors and the wipe
    wrote (from the palette state at I_FinishUpdate's entry), and every
    byte of $9D00-$9FFF that changed."""
    sym = C.symbols()
    drb = sym.address('i_viigs65.s:DRB')
    dre = drb + 200
    y0 = sym.address('i_viigs65.s:DRY0')
    y1 = sym.address('i_viigs65.s:DRY1')
    out = set()
    for d in case.dumps:
        kind = d.point.split(':')[0]
        if kind not in ('PDF', 'PDS'):
            continue
        r0, r1 = d.word(y0), d.word(y1)
        for y in range(r0, min(r1, 200)):
            b, e = d.get(drb + y, 1)[0], d.get(dre + y, 1)[0]
            if e:
                out.update(range(y * 160 + b, y * 160 + e))
        if kind == 'PDF':
            if d.word(sym.address('i_viigs65.s:scbchanged')):
                out.update(range(SCB_LO - SHR_LO, SCB_LO - SHR_LO + 200))
            lc = d.word(sym.address('i_viigs65.s:levelcopy'))
            npal = d.word(sym.address('i_viigs65.s:newpal'))
            if lc or npal != NO_PALETTE_CHANGE:
                out.update(range(PALETTE_LO - SHR_LO,
                                 PALETTE_LO - SHR_LO + TINT_ROW))
            if d.word(sym.address('i_viigs65.s:palettecount')):
                out.update(range(PALETTE_LO - SHR_LO, SHR_HI - SHR_LO))
    before, after = case.screen_before, case.screen_after
    for o in range(SCB_LO - SHR_LO, SHR_HI - SHR_LO):
        if before[o] != after[o]:
            out.add(o)
    return sorted(out)


def screen_image(case: C.Case, fill: int, poison: bool
                 ) -> Tuple[bytes, Tuple[int, ...]]:
    data = bytearray(case.screen_before)
    for o in case.blank_offsets():
        data[o] = fill
    hit: Tuple[int, ...] = ()
    if poison:
        hit = tuple(marked(case))
        for o in hit:
            data[o] = fill
    return bytes(data), hit


# ---------------------------------------------------------------------------
# The injection and the read back
# ---------------------------------------------------------------------------

def inject(case: C.Case, screen: str, fill: int, poison: bool = False,
           build: str = 'test', with_screen: bool = True) -> Injection:
    places, deferred, unfit = places_of(case, screen, build)
    records: List[Record] = []
    for p in places:
        data = place_bytes(p)
        kind = {'main': MAIN, 'aux': AUX, 'lc': LC}[p.storage]
        records.append((kind, p.bank, p.address, data))
    if screen == 'palettes':
        # PS_BEGUN has no upstream counterpart: s2_finish leaves it 0 at
        # every frame's end, so a frame starts with it 0 (request S2WI-7;
        # left the fill, s2_publish would skip s2_begin)
        records.append((AUX, S.S2STATE, S.SS['SS_PALST'] +
                        S.palst_places()['PS_BEGUN'], bytes(1)))
    shown, hit = None, ()
    if with_screen:
        shown, hit = screen_image(case, fill, poison)
        records.append((AUX, 0, SHR_LO, shown))
    return Injection(screen, records, places, deferred, unfit, fill, shown,
                     hit)


class Host:
    """A host machine for the read back: main, the card and the RamWorks
    banks, every byte the fill until a record writes it (as s2run's
    poisoned machines)."""

    def __init__(self, fill: int):
        self.fill = fill
        self.main = bytearray([fill]) * 0x10000
        self.lc = bytearray([fill]) * 0x4000
        self.aux: Dict[int, bytearray] = {}

    def bank(self, b: int) -> bytearray:
        if b not in self.aux:
            self.aux[b] = bytearray([self.fill]) * 0x10000
        return self.aux[b]

    def put(self, kind: int, bank: int, address: int, data: bytes) -> None:
        if kind == MAIN:
            self.main[address:address + len(data)] = data
        elif kind == AUX:
            self.bank(bank)[address:address + len(data)] = data
        elif kind == LC:
            self.lc[address - 0xC000:address - 0xC000 + len(data)] = data
        else:
            raise InjectError('a record of kind %d' % kind)

    def get(self, storage: str, bank: int, address: int, n: int) -> bytes:
        if storage == 'main':
            return bytes(self.main[address:address + n])
        if storage == 'aux':
            return bytes(self.bank(bank)[address:address + n])
        return bytes(self.lc[address - 0xC000:address - 0xC000 + n])


def host_of(inj: Injection) -> Host:
    h = Host(inj.fill)
    for rec in inj.records:
        h.put(*rec)
    return h


def snapshot_getter(machine) -> Any:
    """A read function over an s2run.Machine (an a2vm snapshot)."""
    def get(storage: str, bank: int, address: int, n: int) -> bytes:
        if storage == 'main':
            return bytes(machine.main[address:address + n])
        if storage == 'aux':
            return bytes(machine.storage('aux', bank)[address:address + n])
        return bytes(machine.lc[address - 0xC000:address - 0xC000 + n])
    return get


def read_back(get, inj: Injection) -> List[str]:
    """Every place decoded back from the machine (get(storage, bank,
    address, n)) and compared with upstream's value; the differences."""
    out: List[str] = []
    for p in inj.places:
        data = get(p.storage, p.bank, p.address, p.size)
        if p.enc == 'bytes':
            got: Any = data
        elif p.enc == 'gfx':
            got = gfx_decode(data)
        elif p.enc in ('int', 'handle'):
            got = int.from_bytes(data, 'little')
        else:
            got = decode(data, p.enc)
            if p.enc == 'byte':
                got &= 0xFF
        want = p.value
        if p.enc == 'sxbyte':
            want &= 0xFFFF
        if got != want:
            out.append('%s: $%s read back for $%s (%s at %s %02X:%04X)' % (
                p.ref, _hex(got), _hex(want), p.enc, p.storage, p.bank,
                p.address))
    if inj.screen_bytes is not None:
        shown = get('aux', 0, SHR_LO, SHR_HI - SHR_LO)
        if shown != inj.screen_bytes:
            n = sum(1 for x, y in zip(shown, inj.screen_bytes) if x != y)
            out.append('the screen: %d bytes differ' % n)
    return out


def _hex(v: Any) -> str:
    if isinstance(v, tuple):
        return ','.join('%X' % x for x in v)
    return v.hex() if isinstance(v, (bytes, bytearray)) else '%X' % v


def poison_problems(get, case: C.Case, inj: Injection,
                    hit: Optional[set] = None) -> List[str]:
    """A poisoned injection's screen: every marked byte and every
    undefined row the fill, every other byte the case's screen (the marks
    computed here from the case, not taken from the injection)."""
    shown = get('aux', 0, SHR_LO, SHR_HI - SHR_LO)
    want = case.screen_before
    if hit is None:
        hit = set(marked(case)) | set(case.blank_offsets())
    expect = bytearray(want)
    for o in hit:
        expect[o] = inj.fill
    if shown == bytes(expect):
        return []
    out = []
    bad = [o for o in sorted(hit) if shown[o] != inj.fill]
    if bad:
        out.append('%d marked or undefined bytes are not the fill (first '
                   '$%04X)' % (len(bad), SHR_LO + bad[0]))
    wrong = [o for o in range(len(want)) if o not in hit and
             shown[o] != want[o]]
    if wrong:
        out.append('%d other bytes are not the case\'s (first $%04X)'
                   % (len(wrong), SHR_LO + wrong[0]))
    return out


# ---------------------------------------------------------------------------
# The //e key names and table poked into ref816 (1.5.3, 6.2)
# ---------------------------------------------------------------------------

KEY = {'SPEED': 0, 'USE': 1, 'FIRE': 2, 'STRAFELEFT': 3, 'STRAFERIGHT': 4,
       'UP': 5, 'DOWN': 6, 'LEFT': 7, 'RIGHT': 8, 'ESCAPE': 9, 'MAP': 10,
       'ZOOMOUT': 11, 'ZOOMIN': 12, 'WEAPONDOWN': 13, 'WEAPONUP': 14,
       'STRAFE': 15, 'WEAPON1': 16}     # [R keys.inc:5-21]
NOKEY = 0xFF                            # [R i_iigs65.s:44]
NAME_SIZE, KEYS = 8, 128


def apple2e_keys() -> Tuple[List[str], List[Tuple[int, int]]]:
    """The //e's 128 codes after the fold to upper case: their names (at
    most 7 characters, 1.5.3) and (Doom key, character) with 2.4's
    defaults, the four pseudo-keys in the folded lower-case codes ($70
    mouse 2, $71 mouse 1, $72 Open Apple, $73 Solid Apple): part plinput's
    table (tools/native/plkeys.py; request PLINPUT-6). The characters are
    upstream's (letters, digits and the menu keys only)."""
    from native import plkeys
    names, table = plkeys.names(), plkeys.table()
    for n in names:
        if len(n) > NAME_SIZE - 1:
            raise InjectError('the key name %s is longer than 7' % n)
    return names, table


def keys_poke(names: Sequence[str], table: Sequence[Tuple[int, int]],
              point: Optional[str] = None) -> str:
    """A ref816 --poke-file: keyNames (8 bytes a name, upstream's
    m_menu65.s:keyNames) and keyTable (128 words, the Doom key low and the
    character high, i_iigs65.s:keyTable) at the main loop's first call
    of display (after the boot filled keyTable, before any page draws)."""
    if len(names) != KEYS or len(table) != KEYS:
        raise InjectError('a key table of %d names, %d entries'
                          % (len(names), len(table)))
    nm = bytearray()
    for n in names:
        raw = n.encode('ascii')
        if len(raw) > NAME_SIZE - 1:
            raise InjectError('the key name %s is longer than 7' % n)
        nm += raw + bytes(NAME_SIZE - len(raw))
    tb = bytearray()
    for k, ch in table:
        tb += bytes([k & 0xFF, ch & 0xFF])
    if point is None:
        point = 'pc=%06X,hits=1' % C.sym('d_main65.s:displayCall')
    lines = ['# the //e key names and table (tools/native/s2state.py)']
    for label, data in (('m_menu65.s:keyNames', nm),
                        ('i_iigs65.s:keyTable', tb)):
        at = C.sym(label)
        for off in range(0, len(data), 64):
            lines.append('%s %06X %s' % (point, at + off,
                                         data[off:off + 64].hex()))
    return '\n'.join(lines) + '\n'


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run')
    parser.add_argument('--frame', type=int, default=0)
    parser.add_argument('--screen', default='stbar')
    parser.add_argument('--root', type=Path, default=C.CASES)
    parser.add_argument('--poison', action='store_true')
    a = parser.parse_args(argv)
    rc = C.RunCases(a.root / a.run)
    case = rc.frame(a.frame)
    for fill in (0xA5, 0x5A):
        inj = inject(case, a.screen, fill, a.poison)
        h = host_of(inj)
        diff = read_back(h.get, inj)
        print('fill %02X: %d places, %d deferred, %d unfit, %d differences'
              % (fill, len(inj.places), len(inj.deferred), len(inj.unfit),
                 len(diff)))
        for line in diff[:10]:
            print('  ' + line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
