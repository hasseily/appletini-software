#!/usr/bin/env python3
"""The 2D store (part s2data; docs/SCREENS.md): every lump the 2D screens
draw, placed in RamWorks banks, with the handles table, written as the bank files GFX.n (the level
store's format: tools/native/lstore.py).

The lumps are the release's 2D lumps: every lump of the release's
directory named ST*, M_* or WI* outside the sprite and patch markers,
and TITLEPIC, HELP2, FLOOR4_8, GSSTAT, GSOVL. Their sources (F5):

- the Doom patches (ST*, M_*, WI*): DOOM1.WAD's, parsed and written
  again by this file's own code (header, the columns' offsets, the posts,
  the lump's zero pad to 4 bytes), each checked equal to the release's
  lump; the six patches upstream drew itself (M_ARUN, M_GAMMA, M_MOUSE,
  M_MSPEED, M_MMOVE, M_CTRLS: not in DOOM1.WAD) and the one it recoloured
  (WIURH0, RELEASE_PATCHES) from the release;
- STBAR: DOOM1.WAD's patch drawn into upstream's raw form, 320 x 32
  bytes row by row (V_DrawRaw's lump), checked equal to the release's;
- FLOOR4_8: DOOM1.WAD's flat, checked equal to the release's;
- the SHR pictures TITLEPIC, HELP2, WIMAP0 (pixels, SCBs, 16 palettes,
  pair tables [R i_viigs65.s:60-64]) and the palette records GSSTAT,
  GSOVL: upstream's build artifacts, from the release image through
  umodel.Release, read only (resident lumps from its memory, the others
  from the picture sets' units).

The handles: a lump's handle is its rank in the release's directory
among the 2D lumps, so the directory's runs stay consecutive (STTNUM0-9
are H_STTNUM0 + n, as upstream's lump numbers are). The handles table
GFXDIR is at GFX0's $0200, five arrays of GFX_NH bytes indexed by the
handle: the bank (GFXDIR_BK), the
address's low and high bytes (GFXDIR_LO, GFXDIR_HI), the length's low and
high bytes (GFXDIR_SZLO, GFXDIR_SZHI). The generated s2data.inc also
gives each lump's handle and place as constants (H_name, HBANK_name,
HADDR_name), and s2data.json maps the release's lump numbers to handles
(for the injection of upstream's lump numbers, SCREENS.md).

The places (SCREENS.md): GFX0-GFX3 (s2layout.GFX) first, then the
free parts of banks 103-108, in BINS' order; bank 125 only when those do
not hold the store (reported as over the budget). GSSTAT and GSOVL go to
part s2pal's places in S2PAL (s2layout.S2PAL_PLACES, FIXED), where PALW
reads them. The contracts of the
drawers: every lump in its bank's
$0200-$BFFF; a patch's every column at most 256 bytes and starting at
least the largest fetch buffer (FETCH) before $C000; a raw lump whole
rows of 320 bytes.

Usage (from demos/doom_gs):
    python3 tools/native/s2data.py              build into OUT, then check
    python3 tools/native/s2data.py --check      check OUT's files only
    python3 tools/native/s2data.py --check --report   and the bytes a bank
The checks: the sources (every lump equal to the release's, a picture
part by part), the places (the budget's banks, nothing meeting, the
contracts), the read-back (every lump through the handles table of the
bank files equal to the release's), the include (its constants equal
the table).
"""

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL  # noqa: E402
from native import lstore  # noqa: E402
from native import s2layout as L  # noqa: E402
from native import umodel as U  # noqa: E402

ROOT = HERE.parent.parent
OUT = ROOT / 'build' / 'native' / 'm11' / 's2data'
WAD = U.WAD_PATH

ROOM = LL.ROOM                  # $0200-$BFFF: what RAMRD reaches of a bank
COLUMN_LIMIT = 256              # a column's bytes the drawer holds at once
ROW = 320                       # a raw lump's row (pixels, one byte each)

# upstream's SHR picture [R i_viigs65.s:60-64]
PICTURE_SIZE = 36864
PICTURE_PIXELS = 32000
PICTURE_SCB = 32000
PICTURE_PALS = 32256
PICTURE_PAIRS = 32768
PICTURE_PARTS = (('pixels', 0, PICTURE_PIXELS),
                 ('SCBs', PICTURE_SCB, 200),
                 ('pad', PICTURE_SCB + 200, PICTURE_PALS - PICTURE_SCB - 200),
                 ('palettes', PICTURE_PALS, 512),
                 ('pairs', PICTURE_PAIRS, PICTURE_SIZE - PICTURE_PAIRS))

PICTURES = ('TITLEPIC', 'HELP2', 'WIMAP0')
RECORDS = ('GSSTAT', 'GSOVL')
RAWS = ('STBAR',)
FLATS = ('FLOOR4_8',)
FLAT_SIZE = 4096
PREFIXES = ('ST', 'M_', 'WI')
NAMED = PICTURES + RECORDS + FLATS
MARKERS = (('S_START', 'S_END'), ('P_START', 'P_END'))
# The patches of DOOM1.WAD whose release lump is not DOOM1.WAD's: taken
# from the release, each with what differs (check_sources verifies it:
# the WAD's bytes still differ, the posts are the same, only pixels
# change)
RELEASE_PATCHES = {
    'WIURH0': 'upstream recoloured the "you are here" arrow: 290 pixel '
              'bytes differ from DOOM1.WAD\'s, the posts are the same',
}

# the free parts of banks 103-108 (SCREENS.md): around SFX.1's room
# and S2VIEW's saved screen, s2layout's
SFX_ROOM = L.SFX_ROOM           # SFX.1 at $0200 (11,385 B; about 15 KB)
MENU_SAVE = L.S2VIEW_SAVE       # S2VIEW: the menu's saved screen
# The palette records at part s2pal's places in S2PAL (SCREENS.md): PALW
# reads them there, so the store
# writes them there, outside its packing; their handles name them.
FIXED = {'GSSTAT': 'S2P_GSSTAT', 'GSOVL': 'S2P_GSOVL'}
OVER_BUDGET = 125               # the next spare bank (SCREENS.md)

GFXDIR_ARRAYS = 5               # bank, address low, high, length low, high


class StoreError(Exception):
    pass


class Bin(NamedTuple):
    bank: int
    lo: int
    end: int
    what: str


class Lump(NamedTuple):
    name: str
    number: int                 # the release's lump number
    kind: str                   # patch, raw, flat, picture, record
    source: str                 # 'DOOM1.WAD' or 'release'
    data: bytes


class Place(NamedTuple):
    bank: int
    address: int
    size: int


# ---------------------------------------------------------------------------
# The release's lumps
# ---------------------------------------------------------------------------

def set_banks(rel: U.Release, setrec: U.SetRecord) -> Dict[int, bytearray]:
    """A set's units decoded into its window banks, keyed by the entry's
    bank byte (a window index | $80, or a bank): the same key the set's
    lump entries use."""
    banks: Dict[int, bytearray] = {}
    for e in setrec.entries:
        if e.lump not in (U.FILL, U.UNIT, U.UNIT_RAW):
            continue
        buf = banks.setdefault(e.bank, bytearray(U.BANK))
        if e.lump == U.FILL:
            n = e.length or U.BANK
            buf[e.offset:e.offset + n] = bytes(n)
        elif e.lump == U.UNIT:
            data = rel.unit(e.source, e.length)
            buf[e.offset:e.offset + len(data)] = data
        else:
            at = e.source - rel.store_base + 2
            data = rel.store[at:at + e.length - 2]
            buf[e.offset:e.offset + len(data)] = data
    return banks


class ReleaseLumps:
    """The release's lump bytes: a resident lump from its memory, any
    other from the first set whose entries place it."""

    def __init__(self, rel: U.Release):
        self.rel = rel
        self._sets: Dict[int, Dict[int, bytearray]] = {}

    def __call__(self, number: int) -> bytes:
        rel = self.rel
        if rel.resident(number):
            return rel.resident_bytes(number)
        size = rel.directory[number].size
        for k, setrec in enumerate(rel.sets):
            for e in setrec.entries:
                if e.lump != number:
                    continue
                if k not in self._sets:
                    self._sets[k] = set_banks(rel, setrec)
                if e.offset + size > U.BANK:
                    raise StoreError('%s crosses a window bank in set %d'
                                     % (rel.names[number], k + 1))
                buf = self._sets[k].get(e.bank)
                if buf is None:
                    raise StoreError('%s: set %d has no unit at bank $%02X'
                                     % (rel.names[number], k + 1, e.bank))
                return bytes(buf[e.offset:e.offset + size])
        raise StoreError('%s is neither resident nor in a set'
                         % rel.names[number])


def names_2d(rel: U.Release) -> List[int]:
    """The release's 2D lumps by number, in directory order."""
    inside = []
    for a, b in MARKERS:
        inside.append((rel.index(a), rel.index(b)))
    out = []
    for i, n in enumerate(rel.names):
        if any(a <= i <= b for a, b in inside):
            continue
        if n.startswith(PREFIXES) or n in NAMED:
            if rel.directory[i].size == 0:
                raise StoreError('%s is empty in the release' % n)
            out.append(i)
    return out


# ---------------------------------------------------------------------------
# Doom patches, our own reading and writing
# ---------------------------------------------------------------------------

class Post(NamedTuple):
    top: int
    pad0: int
    data: bytes
    pad1: int


class Patch(NamedTuple):
    width: int
    height: int
    left: int
    top: int
    columns: List[List[Post]]


def parse_patch(data: bytes) -> Patch:
    """A Doom patch: the header, each column's posts (top, the pad bytes
    and the pixels); the columns must follow the offsets table in order
    with nothing between them (DOOM1.WAD's 2D patches all do)."""
    w, h, left, top = struct.unpack_from('<HHhh', data, 0)
    if not (0 < w <= 320 and 0 < h <= 200) or len(data) < 8 + 4 * w:
        raise StoreError('not a patch')
    at = 8 + 4 * w
    columns = []
    for c in range(w):
        offset = struct.unpack_from('<I', data, 8 + 4 * c)[0]
        if offset != at:
            raise StoreError('column %d at %d, not %d' % (c, offset, at))
        posts = []
        while True:
            if at >= len(data):
                raise StoreError('column %d runs past the lump' % c)
            if data[at] == 0xFF:
                at += 1
                break
            n = data[at + 1]
            if at + n + 4 > len(data):
                raise StoreError('a post of column %d runs past the lump'
                                 % c)
            posts.append(Post(data[at], data[at + 2],
                              bytes(data[at + 3:at + 3 + n]),
                              data[at + 3 + n]))
            at += n + 4
        columns.append(posts)
    if any(data[at:]) or len(data) - at > 3:
        raise StoreError('%d bytes after the last column' % (len(data) - at))
    return Patch(w, h, left, top, columns)


def column_bytes(posts: List[Post]) -> bytes:
    out = bytearray()
    for p in posts:
        out += bytes((p.top, len(p.data), p.pad0)) + p.data + bytes((p.pad1,))
    return bytes(out + b'\xff')


def encode_patch(p: Patch) -> bytes:
    """The patch's bytes: the header, the columns' offsets (32 bits, low
    byte first), the columns in order, a zero pad to 4 bytes."""
    head = struct.pack('<HHhh', p.width, p.height, p.left, p.top)
    body = bytearray()
    offsets = bytearray()
    base = len(head) + 4 * p.width
    for posts in p.columns:
        offsets += struct.pack('<I', base + len(body))
        body += column_bytes(posts)
    out = head + bytes(offsets) + bytes(body)
    return out + bytes(-len(out) % 4)


def raw_of_patch(p: Patch) -> bytes:
    """V_DrawRaw's form of a patch at (0, 0): width x height bytes, row by
    row; every pixel must be covered."""
    w, h = p.width, p.height
    buf = bytearray(w * h)
    seen = bytearray(w * h)
    for x, posts in enumerate(p.columns):
        for post in posts:
            for i, v in enumerate(post.data):
                y = post.top + i
                if y >= h:
                    raise StoreError('a post below the raw\'s rows')
                buf[y * w + x] = v
                seen[y * w + x] = 1
    if not all(seen):
        raise StoreError('%d pixels of the raw not covered'
                         % seen.count(0))
    return bytes(buf)


def patch_columns(data: bytes) -> List[Tuple[int, int]]:
    """Each column's (offset, bytes) as the drawer reads it: the offset's
    low word, the posts to the $FF."""
    w = struct.unpack_from('<H', data, 0)[0]
    out = []
    for c in range(w):
        offset = struct.unpack_from('<H', data, 8 + 4 * c)[0]
        p = offset
        while p < len(data) and data[p] != 0xFF:
            p += data[p + 1] + 4
        out.append((offset, p + 1 - offset))
    return out


# ---------------------------------------------------------------------------
# The lumps
# ---------------------------------------------------------------------------

def read_wad(path: Path = WAD) -> Dict[str, bytes]:
    from ref816 import lumps
    return lumps.read_wad(path)


def picture_parts(data: bytes) -> Dict[str, bytes]:
    if len(data) != PICTURE_SIZE:
        raise StoreError('a picture of %d bytes' % len(data))
    return {n: data[a:a + k] for n, a, k in PICTURE_PARTS}


def picture_bytes(parts: Dict[str, bytes]) -> bytes:
    out = b''.join(parts[n] for n, _, _ in PICTURE_PARTS)
    if len(out) != PICTURE_SIZE:
        raise StoreError('a picture assembled to %d bytes' % len(out))
    return out


def make_lumps(rel: U.Release, wad: Dict[str, bytes],
               release: Optional[ReleaseLumps] = None) -> List[Lump]:
    """Every 2D lump of the store, in handle order, from its source."""
    release = release or ReleaseLumps(rel)
    numbers = names_2d(rel)
    pictures = {rel.names[i]: picture_parts(release(i)) for i in numbers
                if rel.names[i] in PICTURES}
    out = []
    for i in numbers:
        name = rel.names[i]
        if name in PICTURES:
            out.append(Lump(name, i, 'picture', 'release',
                            picture_bytes(pictures[name])))
        elif name in RECORDS:
            out.append(Lump(name, i, 'record', 'release', release(i)))
        elif name in RAWS:
            out.append(Lump(name, i, 'raw', 'DOOM1.WAD',
                            raw_of_patch(parse_patch(wad[name]))))
        elif name in FLATS:
            data = wad[name]
            if len(data) != FLAT_SIZE:
                raise StoreError('%s is %d bytes' % (name, len(data)))
            out.append(Lump(name, i, 'flat', 'DOOM1.WAD', data))
        elif name in wad and name not in RELEASE_PATCHES:
            out.append(Lump(name, i, 'patch', 'DOOM1.WAD',
                            encode_patch(parse_patch(wad[name]))))
        else:
            data = release(i)
            parse_patch(data)
            out.append(Lump(name, i, 'patch', 'release', data))
    return out


# ---------------------------------------------------------------------------
# The places
# ---------------------------------------------------------------------------

def fetch_bytes() -> int:
    """The largest fetch buffer of a 2D image (s2layout's runtime ranges):
    the drawer refills it from a column's start."""
    sizes = [hi - lo for im in L.IMAGES for lo, hi, what in im.runtime
             if 'fetch buffer' in what]
    return max(sizes)


def _page_up(a: int) -> int:
    return (a + 0xFF) & ~0xFF


def bins() -> List[Bin]:
    """The store's places in order: GFX0-GFX3 whole, then the free parts
    of banks 103-108 (SCREENS.md): SFX past SFX.1's room, the code
    banks below MATHW, S2VIEW around the menu's saved screen, the code
    banks above their image's room, S2STATE past its blocks. Bank 106
    (S2PAL) is part s2pal's but for FIXED's places (fixed_bins)."""
    out = [Bin(b, ROOM[0], ROOM[1], 'GFX%d' % k)
           for k, b in enumerate(L.GFX)]
    out.append(Bin(L.SFX, SFX_ROOM[1], ROOM[1], 'S2SFX past SFX.1'))
    placed = L.image_banks()
    code = [(L.S2CODE0, 'S2CODE0'), (L.S2CODE1, 'S2CODE1')]
    for bank, name in code:
        out.append(Bin(bank, ROOM[0], L.MATHW_LO, name + ' below MATHW'))
    out.append(Bin(L.S2VIEW, ROOM[0], MENU_SAVE[0],
                   'S2VIEW below the saved screen'))
    out.append(Bin(L.S2VIEW, MENU_SAVE[1], ROOM[1],
                   'S2VIEW above the saved screen'))
    for bank, name in code:
        rooms = [L.IMAGE[n].stored for n, b in placed.items() if b == bank]
        top = _page_up(max(hi for _, hi in rooms)) if rooms else L.MATHW_LO
        out.append(Bin(bank, top, ROOM[1], name + ' above its image'))
    ss_end = max(L.SS[k] + L.SS_SIZE[k] for k in L.SS)
    out.append(Bin(L.S2STATE, _page_up(ss_end), ROOM[1],
                   'S2STATE past its blocks'))
    return out


def fixed_bins() -> List[Bin]:
    """The places of FIXED's lumps in S2PAL, each exactly its lump."""
    return [Bin(L.S2PAL, L.S2PAL_AT[p], L.S2PAL_AT[p] + L.S2PAL_SIZE[p],
                '%s at S2PAL\'s %s' % (n, p)) for n, p in FIXED.items()]


def over_bin() -> Bin:
    return Bin(OVER_BUDGET, ROOM[0], ROOM[1],
               'bank %d (over the budget)' % OVER_BUDGET)


def reserved() -> List[Tuple[int, int, int, str]]:
    """What the other users of banks 103-108 hold: (bank, lo, end,
    whose)."""
    out = [(L.SFX, SFX_ROOM[0], SFX_ROOM[1], 'SFX.1'),
           (L.S2VIEW, MENU_SAVE[0], MENU_SAVE[1], 'the menu\'s saved screen')]
    at = ROOM[0]
    for b in sorted(fixed_bins(), key=lambda b: b.lo):
        if at < b.lo:
            out.append((L.S2PAL, at, b.lo, 'S2PAL (part s2pal)'))
        at = b.end
    if at < ROOM[1]:
        out.append((L.S2PAL, at, ROOM[1], 'S2PAL (part s2pal)'))
    for name, bank in L.image_banks().items():
        if bank in (L.S2CODE0, L.S2CODE1):
            lo, hi = L.IMAGE[name].stored
            out.append((bank, L.MATHW_LO, hi, 'MATHW and %s' % name))
    out.append((L.S2STATE, ROOM[0],
                max(L.SS[k] + L.SS_SIZE[k] for k in L.SS), 'the state'))
    return out


def fits(lump: Lump, address: int, end: int, fetch: int) -> bool:
    """The lump at address, inside [.., end), meets the contracts."""
    if address + len(lump.data) > end:
        return False
    if lump.kind == 'patch':
        last = max(o for o, _ in patch_columns(lump.data))
        if address + last + fetch > ROOM[1]:
            return False
    return True


class Store(NamedTuple):
    lumps: List[Lump]
    places: Dict[str, Place]
    directory: Place
    used: Dict[Tuple[int, int], int]    # (bank, lo) of a bin -> its next


def directory_bytes(lumps: Sequence[Lump], places: Dict[str, Place]
                    ) -> bytes:
    n = len(lumps)
    arrays = [bytearray(n) for _ in range(GFXDIR_ARRAYS)]
    for h, lump in enumerate(lumps):
        p = places[lump.name]
        arrays[0][h] = p.bank
        arrays[1][h] = p.address & 0xFF
        arrays[2][h] = p.address >> 8
        arrays[3][h] = p.size & 0xFF
        arrays[4][h] = p.size >> 8
    return b''.join(bytes(a) for a in arrays)


def place(lumps: List[Lump], bin_list: Optional[List[Bin]] = None
          ) -> Store:
    """The handles table at GFX0's start, then the pictures, then the
    other lumps from the largest, each at the first bin it fits; bank
    125 when none."""
    if len(lumps) > 256:
        raise StoreError('%d handles: an index register holds 256'
                         % len(lumps))
    bin_list = list(bin_list or bins()) + [over_bin()]
    fetch = fetch_bytes()
    at = {(b.bank, b.lo): b.lo for b in bin_list}
    first = bin_list[0]
    dir_size = GFXDIR_ARRAYS * len(lumps)
    directory = Place(first.bank, first.lo, dir_size)
    at[(first.bank, first.lo)] += dir_size
    places: Dict[str, Place] = {}
    fixed = {b.what.split()[0]: b for b in fixed_bins()}
    for lump in lumps:
        b = fixed.get(lump.name)
        if b is None:
            continue
        if len(lump.data) != b.end - b.lo:
            raise StoreError('%s: %d bytes, its place in S2PAL %d' % (
                lump.name, len(lump.data), b.end - b.lo))
        places[lump.name] = Place(b.bank, b.lo, len(lump.data))
    order = sorted((m for m in lumps if m.name not in fixed),
                   key=lambda m: (m.kind != 'picture', -len(m.data),
                                  m.number))
    for lump in order:
        for b in bin_list:
            a = at[(b.bank, b.lo)]
            if fits(lump, a, b.end, fetch):
                places[lump.name] = Place(b.bank, a, len(lump.data))
                at[(b.bank, b.lo)] = a + len(lump.data)
                break
        else:
            raise StoreError('%s fits no bank' % lump.name)
    return Store(lumps, places, directory, at)


# ---------------------------------------------------------------------------
# The files
# ---------------------------------------------------------------------------

def bank_images(store: Store) -> Dict[int, Dict[int, bytes]]:
    """Each bank's runs: {bank: {address: bytes}}, a run a bin."""
    runs: Dict[int, Dict[int, bytearray]] = {}
    items = [(store.directory, directory_bytes(store.lumps, store.places))]
    items += [(store.places[m.name], m.data) for m in store.lumps]
    for p, data in sorted(items, key=lambda x: (x[0].bank, x[0].address)):
        bank = runs.setdefault(p.bank, {})
        for a, run in bank.items():
            if a + len(run) == p.address:
                run += data
                break
        else:
            bank[p.address] = bytearray(data)
    return {b: {a: bytes(r) for a, r in sorted(rs.items())}
            for b, rs in runs.items()}


def segments(store: Store) -> List[Tuple[int, int, bytes]]:
    return [(b, a, r) for b, rs in sorted(bank_images(store).items())
            for a, r in rs.items()]


def bank_files(store: Store) -> Dict[str, bytes]:
    segs = segments(store)
    out = {}
    k = 0
    while segs:
        chunk, segs = segs[:LL.BANKFILE_MAX_SEGS], \
            segs[LL.BANKFILE_MAX_SEGS:]
        k += 1
        out['GFX.%d' % k] = lstore.bank_file(chunk)
    return out


def symbol(name: str) -> str:
    s = ''.join(c if c.isalnum() else '_' for c in name.upper())
    return s


def include_text(store: Store) -> str:
    d = store.directory
    n = len(store.lumps)
    lines = ['; s2data.inc: the 2D store\'s places (generated by '
             'tools/native/s2data.py;', '; docs/SCREENS.md). '
             'Do not edit.', '',
             'GFX_NH = %d' % n,
             'GFXDIR_BANK = %d' % d.bank,
             'GFXDIR = $%04X' % d.address]
    for k, what in enumerate(('BK', 'LO', 'HI', 'SZLO', 'SZHI')):
        lines.append('GFXDIR_%s = $%04X' % (what, d.address + k * n))
    lines += ['GFX_FETCH = %d' % fetch_bytes(),
              'PIC_SIZE = %d' % PICTURE_SIZE,
              'PIC_SCB = %d' % PICTURE_SCB,
              'PIC_PALS = %d' % PICTURE_PALS,
              'PIC_PAIRS = %d' % PICTURE_PAIRS, '']
    seen: Dict[str, str] = {}
    for h, lump in enumerate(store.lumps):
        p = store.places[lump.name]
        s = symbol(lump.name)
        if seen.setdefault(s, lump.name) != lump.name:
            raise StoreError('%s and %s are both H_%s' % (seen[s], lump.name,
                                                          s))
        lines.append('H_%s = %d' % (s, h))
        lines.append('HBANK_%s = %d' % (s, p.bank))
        lines.append('HADDR_%s = $%04X' % (s, p.address))
    return '\n'.join(lines) + '\n'


def manifest(store: Store) -> Dict:
    out = {'version': 1, 'handles': len(store.lumps),
           'directory': list(store.directory), 'fetch': fetch_bytes(),
           'lumps': []}
    for h, lump in enumerate(store.lumps):
        p = store.places[lump.name]
        out['lumps'].append({
            'handle': h, 'name': lump.name, 'lump': lump.number,
            'kind': lump.kind, 'source': lump.source, 'bank': p.bank,
            'address': p.address, 'size': p.size,
            'sha256': hashlib.sha256(lump.data).hexdigest()})
    return out


def usage(store: Store) -> List[Tuple[Bin, int]]:
    """Each bin's bytes used (the handles table counted in GFX0's)."""
    items = [store.directory] + list(store.places.values())
    out = []
    for b in bins() + fixed_bins() + [over_bin()]:
        used = sum(p.size for p in items if p.bank == b.bank and
                   b.lo <= p.address < b.end)
        if used or b.bank != OVER_BUDGET:
            out.append((b, used))
    return out


def report(store: Store) -> str:
    lines = ['The 2D store: %d lumps, %d bytes, the handles table %d B '
             '(bank %d $%04X)' % (len(store.lumps),
                                  sum(len(m.data) for m in store.lumps),
                                  store.directory.size, store.directory.bank,
                                  store.directory.address)]
    kinds: Dict[Tuple[str, str], List[int]] = {}
    for m in store.lumps:
        kinds.setdefault((m.kind, m.source), []).append(len(m.data))
    for (kind, source), sizes in sorted(kinds.items()):
        lines.append('  %-8s from %-9s %4d lumps %8d B' % (
            kind, source, len(sizes), sum(sizes)))
    lines.append('bank  place                              room        used'
                 '      free')
    for b, used in usage(store):
        lines.append('%4d  %-30s $%04X-$%04X %6d B  %6d B' % (
            b.bank, b.what, b.lo, b.end - 1, used, b.end - b.lo - used))
    banks: Dict[int, int] = {}
    for b, used in usage(store):
        banks[b.bank] = banks.get(b.bank, 0) + used
    lines.append('by bank: ' + ', '.join('%d %d B' % (b, n)
                                         for b, n in sorted(banks.items())))
    over = banks.get(OVER_BUDGET, 0)
    lines.append('budget (GFX0-GFX3 and the free parts of 103-108): %s' % (
        'met' if not over else 'NOT met: %d B in bank %d' % (over,
                                                            OVER_BUDGET)))
    return '\n'.join(lines)


def write(store: Store, out: Path = OUT) -> Dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, data in bank_files(store).items():
        (out / name).write_bytes(data)
        written[name] = out / name
    for name, text in (('s2data.inc', include_text(store)),
                       ('s2data.json', json.dumps(manifest(store),
                                                  indent=1) + '\n'),
                       ('s2data.lst', report(store) + '\n')):
        (out / name).write_text(text)
        written[name] = out / name
    return written


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def check_sources(lumps: Sequence[Lump], rel: U.Release,
                  wad: Dict[str, bytes]) -> List[str]:
    """Every lump equal to the release's (a picture part by part), a
    WAD-made one also from DOOM1.WAD's lump of the name; the set is the
    release's 2D lumps in directory order."""
    out = []
    release = ReleaseLumps(rel)
    want = names_2d(rel)
    if [m.number for m in lumps] != want:
        out.append('the lumps are not the release\'s 2D lumps in order')
    for m in lumps:
        if rel.names[m.number] != m.name:
            out.append('%s: lump %d is %s' % (m.name, m.number,
                                              rel.names[m.number]))
            continue
        ref = release(m.number)
        if m.data == ref:
            pass
        elif m.kind == 'picture' and len(m.data) == len(ref):
            for part, a, k in PICTURE_PARTS:
                if m.data[a:a + k] != ref[a:a + k]:
                    out.append('%s: the %s ($%04X-$%04X) differ from the '
                               'release\'s' % (m.name, part, a, a + k - 1))
        else:
            diff = next((k for k in range(min(len(m.data), len(ref)))
                         if m.data[k] != ref[k]), min(len(m.data), len(ref)))
            out.append('%s (%s): %d bytes, the release\'s %d; the first '
                       'difference at byte %d' % (m.name, m.kind,
                                                  len(m.data), len(ref),
                                                  diff))
        if m.source == 'DOOM1.WAD' and m.name not in wad:
            out.append('%s: not in DOOM1.WAD' % m.name)
        if m.source == 'release' and m.kind == 'patch' and m.name in wad:
            out += check_release_patch(m, wad[m.name])
    return out


def same_posts(a: Patch, b: Patch) -> bool:
    """The same header and posts (tops, lengths), pixels aside."""
    return a[:4] == b[:4] and [[(p.top, len(p.data)) for p in c]
                               for c in a.columns] == \
        [[(p.top, len(p.data)) for p in c] for c in b.columns]


def check_release_patch(m: Lump, wad_lump: bytes) -> List[str]:
    """A patch of DOOM1.WAD taken from the release: declared, its WAD
    form still different, its posts the WAD's."""
    if m.name not in RELEASE_PATCHES:
        return ['%s: in DOOM1.WAD but taken from the release' % m.name]
    ours = encode_patch(parse_patch(wad_lump))
    if ours == m.data:
        return ['%s: declared in RELEASE_PATCHES but DOOM1.WAD\'s is the '
                'release\'s' % m.name]
    if not same_posts(parse_patch(wad_lump), parse_patch(m.data)):
        return ['%s: the release\'s posts are not DOOM1.WAD\'s' % m.name]
    return []


def check_places(store: Store) -> List[str]:
    """Every lump inside its bank's $0200-$BFFF and inside one bin of the
    budget (or bank 125, reported), no two places meeting, none in
    another user's part of banks 103-108; the drawers' contracts."""
    out = []
    fetch = fetch_bytes()
    bl = bins() + fixed_bins() + [over_bin()]
    for b in fixed_bins():
        name = b.what.split()[0]
        p = store.places.get(name)
        if p is None or (p.bank, p.address) != (b.bank, b.lo):
            out.append('%s is not at bank %d $%04X (S2PAL\'s place)' % (
                name, b.bank, b.lo))
    items = [('GFXDIR', store.directory)] + [
        (m.name, store.places[m.name]) for m in store.lumps]
    if store.directory.bank != L.GFX[0] or \
            store.directory.address != ROOM[0]:
        out.append('the handles table is not at GFX0\'s $%04X' % ROOM[0])
    for name, p in items:
        end = p.address + p.size
        if p.address < ROOM[0] or end > ROOM[1]:
            out.append('%s at bank %d $%04X-$%04X: outside $%04X-$%04X '
                       '(across the bank\'s end)' % (
                           name, p.bank, p.address, end - 1, ROOM[0],
                           ROOM[1] - 1))
        if not any(b.bank == p.bank and b.lo <= p.address and end <= b.end
                   for b in bl):
            out.append('%s at bank %d $%04X-$%04X: in no place of the '
                       'store' % (name, p.bank, p.address, end - 1))
        for bank, lo, hi, whose in reserved():
            if bank == p.bank and p.address < hi and lo < end:
                out.append('%s at bank %d $%04X-$%04X meets %s' % (
                    name, p.bank, p.address, end - 1, whose))
    spans = sorted((p.bank, p.address, p.address + p.size, n)
                   for n, p in items)
    for a, b in zip(spans, spans[1:]):
        if a[0] == b[0] and b[1] < a[2]:
            out.append('%s and %s meet in bank %d' % (a[3], b[3], a[0]))
    for m in store.lumps:
        p = store.places[m.name]
        if p.size != len(m.data):
            out.append('%s: placed %d bytes of %d' % (m.name, p.size,
                                                      len(m.data)))
        if m.kind == 'patch':
            cols = patch_columns(m.data)
            longest = max(k for _, k in cols)
            if longest > COLUMN_LIMIT:
                out.append('%s: a column of %d bytes' % (m.name, longest))
            last = max(o for o, _ in cols)
            if p.address + last + fetch > ROOM[1]:
                out.append('%s: a column at $%04X, less than %d bytes '
                           'before $%04X' % (m.name, p.address + last, fetch,
                                             ROOM[1]))
        if m.kind == 'raw' and (len(m.data) % ROW or
                                len(m.data) > ROOM[1] - ROOM[0]):
            out.append('%s: a raw lump of %d bytes' % (m.name, len(m.data)))
        if m.kind == 'picture' and len(m.data) != PICTURE_SIZE:
            out.append('%s: a picture of %d bytes' % (m.name, len(m.data)))
    return out


def read_back(files: Dict[str, bytes]) -> Dict[int, bytearray]:
    """The banks as the boot leaves them: each file's segments copied."""
    banks: Dict[int, bytearray] = {}
    for name in sorted(files, key=lambda n: int(n.split('.')[1])):
        for bank, address, data in lstore.read_bank_file(files[name]):
            buf = banks.setdefault(bank, bytearray(U.BANK))
            buf[address:address + len(data)] = data
    return banks


def check_read_back(files: Dict[str, bytes], lumps: Sequence[Lump],
                    rel: U.Release) -> List[str]:
    """Every lump read back from the bank files through the handles table
    the files hold equals its source: the release's lump."""
    out = []
    banks = read_back(files)
    gfx0 = banks.get(L.GFX[0])
    if gfx0 is None:
        return ['no segment in GFX0 (bank %d)' % L.GFX[0]]
    n = len(lumps)
    at = ROOM[0]
    arrays = [gfx0[at + k * n:at + (k + 1) * n] for k in range(GFXDIR_ARRAYS)]
    release = ReleaseLumps(rel)
    for h, m in enumerate(lumps):
        bank = arrays[0][h]
        address = arrays[1][h] | arrays[2][h] << 8
        size = arrays[3][h] | arrays[4][h] << 8
        if bank not in banks:
            out.append('%s (handle %d): bank %d has no segment' % (
                m.name, h, bank))
            continue
        data = bytes(banks[bank][address:address + size])
        ref = release(m.number)
        if data != ref:
            out.append('%s (handle %d): read back at bank %d $%04X, %d B, '
                       'not the release\'s %d B' % (m.name, h, bank, address,
                                                   size, len(ref)))
    return out


def check_include(text: str, files: Dict[str, bytes],
                  lumps: Sequence[Lump]) -> List[str]:
    """s2data.inc's handles and places equal the handles table the bank
    files hold."""
    values: Dict[str, int] = {}
    for line in text.splitlines():
        if '=' in line and not line.startswith(';'):
            k, v = (x.strip() for x in line.split('=', 1))
            values[k] = int(v[1:], 16) if v.startswith('$') else int(v)
    banks = read_back(files)
    n = len(lumps)
    out = []
    if values.get('GFX_NH') != n or values.get('GFXDIR_BANK') != L.GFX[0] \
            or values.get('GFXDIR') != ROOM[0]:
        out.append('s2data.inc: GFX_NH, GFXDIR_BANK or GFXDIR wrong')
        return out
    table = banks.get(L.GFX[0], bytearray(U.BANK))
    for h, m in enumerate(lumps):
        s = symbol(m.name)
        bank = table[ROOM[0] + h]
        address = table[ROOM[0] + n + h] | table[ROOM[0] + 2 * n + h] << 8
        if (values.get('H_' + s), values.get('HBANK_' + s),
                values.get('HADDR_' + s)) != (h, bank, address):
            out.append('s2data.inc: %s is not handle %d at bank %d $%04X'
                       % (m.name, h, bank, address))
    return out


def load_files(out: Path = OUT) -> Dict[str, bytes]:
    files = {p.name: p.read_bytes() for p in sorted(out.glob('GFX.*'))
             if p.suffix[1:].isdigit()}
    if not files:
        raise StoreError('no GFX.n in %s' % out)
    return files


def checkpoint(store: Store, files: Dict[str, bytes], rel: U.Release,
               wad: Dict[str, bytes], include: Optional[str] = None
               ) -> Dict[str, List[str]]:
    """The checkpoint's checks, by name: their problems."""
    out = {'sources': check_sources(store.lumps, rel, wad),
           'places': check_places(store),
           'read-back': check_read_back(files, store.lumps, rel)}
    if include is not None:
        out['include'] = check_include(include, files, store.lumps)
    return out


def store_of_manifest(out: Path, rel: U.Release, wad: Dict[str, bytes]
                      ) -> Store:
    """The store a build wrote, its lumps made again from the sources and
    its places from the manifest."""
    man = json.loads((out / 's2data.json').read_text())
    lumps = make_lumps(rel, wad)
    places = {e['name']: Place(e['bank'], e['address'], e['size'])
              for e in man['lumps']}
    directory = Place(*man['directory'])
    for m in lumps:
        if m.name not in places:
            raise StoreError('%s is not in the manifest' % m.name)
    return Store(lumps, places, directory, {})


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--check', action='store_true',
                        help='check the files of --out only')
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args(argv)
    for path in (WAD, U.RELEASE):
        if not path.exists():
            print('%s is missing: run python3 tools/fetch_upstream.py first'
                  % path, file=sys.stderr)
            return 2
    rel = U.Release()
    wad = read_wad()
    try:
        if args.check:
            store = store_of_manifest(args.out, rel, wad)
        else:
            store = place(make_lumps(rel, wad))
            write(store, args.out)
        files = load_files(args.out)
        result = checkpoint(store, files, rel, wad,
                            (args.out / 's2data.inc').read_text())
    except (StoreError, U.ModelError, lstore.StoreError) as error:
        print('s2data: %s' % error, file=sys.stderr)
        return 1
    if args.report or not args.check:
        print(report(store))
    bad = 0
    for name, problems in result.items():
        print('%-9s %s' % (name, 'OK' if not problems else
                           '%d problems' % len(problems)))
        for p in problems[:20]:
            print('    ' + p)
        bad += len(problems)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
