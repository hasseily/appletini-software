"""The model of upstream's memory at the end of a map's load (docs/LEVELS.md):
the level window after W_LoadSet, the column memory
after R_MakeLevelColumns and W_LevelDone's moreColumns and W_ZeroBank,
and the banks next to them, rebuilt from the release's level store and
DOOM1.WAD, never from a reference run. tools/native/wadconv.py converts
from it.

The release is read with our own readers (tools/v816/hdv.py, b1.py). Its
level store (upstream's tools/levelimg.py documents the format): a header
"DOOMST" and the set count, a 12-byte record a set (its entry list's
store offset, the entry count, the window banks, the disk, the image's
end in its last bank, a checksum), the entries (10 bytes: a lump number
or UNIT $FFFE, UNIT_RAW $FFFD, FILL $FFFF, songs $FFE0 up; a window bank
index | $80 or an absolute bank; the offset; a 24-bit store address; a
length), and the units' streams (a length word and B1). The last set is
the common set (its units load once, with the first map, into the first
window banks and stay); the sets 0-8 are the maps.

What W_LoadSet leaves (w_level65.s:271-440, :929-1003): the image banks
of the set (the common units, the map's units, zeros elsewhere: FILL), and
the directory entry of each lump of the set pointing at its window
address (filepos = the address - MM_WAD); every other lump of a window
bank points at the placeholder (unmap). The image is built here from the
lumps (wadconv.py's bytes: DOOM1.WAD's through maplumps.py, and the
release's own lumps GSVIEWn, GSFLATn, SGRIDn) at the addresses of the
set's lump entries, and checked equal to the decoded units: every unit
byte belongs to a lump of the set, every other image byte is 0.

The window banks (W_InitLevels, w_level65.s:139-209, on the 8 MB machine
the ref816 runs model): MM_WINDOW ($2A) to $3F, $0E, $0F, then from $40
past the store's banks up to MM_MUSBANK's bank ($6A); W_NEXTBANK gives
each one's successor; with 32 banks or more (RES_MIN) the title and
intermission picture sets stay at the window's end and the column memory
stops before them (picBases).

The column memory (r_data65.s:863-1197, :1732-1860; w_level65.s:507-610):
R_MakeLevelColumns zeroes COLDIR (MM_COLDIR, 256 entries of a 24-bit
table address and the width mask), starts at W_COLSTART (the image's
end; a full last bank: the next bank, zeroed), and makes the columns of
each side texture (top, middle, bottom, in side order) in two passes:
the hot textures (CM_COLD's bit clear) first, then the others. A
texture's table ((width mask + 1) x 4 bytes) and its composed columns
come from colAlloc: a cold block takes the first hole that fits; else
the block goes at colmem, moved to the next window bank (zeroed) when it
would end within OVERREAD bytes of its bank's end; a hot composed column
that would touch $0900-$1FFF of its bank's half starts at $2000 of that
half and the bytes skipped become a hole (16 holes at most kept). Each
column of a texture: a single patch's column (the patch's texels in
place), or for a texture whose patches overlap a composed column (the
texels of the one patch post covering the whole column in place, else
`height` bytes zeroed with each covering patch's posts drawn in), 0 with
a flag for none. Then W_LevelDone's moreColumns: for each switch pair
(switchlist) the other texture of a made one, then the three slime
frames when one is made, each only while colmem's window index is below
MORE_BANKS (22); then the window bank after colmem's zeroed (LV_ZB).

The memory is a set of 64 KB banks with a mask of the bytes the model
knows: the image banks, the zeroed banks, the release's resident banks
(the directory in bank $10 as the set leaves it) and its store from $40.
A read of a byte the model does not know fails, naming the address
(wadconv.py's tails: docs/LEVELS.md).
"""

import struct
import sys
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, \
    Set, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from v816 import b1, hdv  # noqa: E402
from native import maplumps as ML  # noqa: E402

ROOT = HERE.parent.parent
RELEASE = ROOT / 'build' / 'release' / 'doom-hd.hdv'
WAD_PATH = ROOT / 'build' / 'upstream' / 'data' / 'DOOM1.WAD'
LINKMAP = ROOT / 'build' / 'linkmap.json'

BANK = 0x10000
# memmap.inc (MM_WAD, MM_WINDOW, MM_WINDOW_END, MM_MUSBANK, MM_COLDIR)
MM_WAD = 0x100000
MM_WAD_BANK = 0x10
MM_WINDOW, MM_WINDOW_END = 0x2A, 0x40
MM_MUSBANK_BANK = 0x6A
MM_COLDIR = 0x250000
COLDIR_SIZE = 0x400
STORE_BANK = 0x40
# the level store (levelimg.py's format)
SETREC, ENTRY = 12, 10
FILL, UNIT, UNIT_RAW = 0xFFFF, 0xFFFE, 0xFFFD
SONGS = 0xFFE0
TITLE_SET, INTER_SET = 10, 11          # 1-based set numbers
RES_MIN = 32
# r_data65.s, w_level65.s
OVERREAD = 128
CM_MAX = 16
MORE_BANKS = 22
NUMSW2 = 38
CM_COLD_BYTES = 33
# Doom's switch textures (p_switch.c alphSwitchList, episode 1 and the
# shareware's: off, on), in their order, and the slime's first frame
# (p_spec.c's animdefs: SLADRIP1-3)
SWITCH_NAMES = (
    'SW1BRCOM', 'SW2BRCOM', 'SW1BRN1', 'SW2BRN1', 'SW1BRN2', 'SW2BRN2',
    'SW1BRNGN', 'SW2BRNGN', 'SW1BROWN', 'SW2BROWN', 'SW1COMM', 'SW2COMM',
    'SW1COMP', 'SW2COMP', 'SW1DIRT', 'SW2DIRT', 'SW1EXIT', 'SW2EXIT',
    'SW1GRAY', 'SW2GRAY', 'SW1GRAY1', 'SW2GRAY1', 'SW1METAL', 'SW2METAL',
    'SW1PIPE', 'SW2PIPE', 'SW1SLAD', 'SW2SLAD', 'SW1STARG', 'SW2STARG',
    'SW1STON1', 'SW2STON1', 'SW1STON2', 'SW2STON2', 'SW1STONE', 'SW2STONE',
    'SW1STRTN', 'SW2STRTN')
SLIME_FIRST = 'SLADRIP1'
SKY_TEXTURE = 'SKY1'
NO_TEXTURE = 0xFFFF


class ModelError(Exception):
    pass


def u16(b: bytes, at: int = 0) -> int:
    return b[at] | b[at + 1] << 8


def s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


# ---------------------------------------------------------------------------
# The memory
# ---------------------------------------------------------------------------

class Memory:
    """24-bit memory of banks with a mask of the bytes the model knows."""

    def __init__(self):
        self.data: Dict[int, bytearray] = {}
        self.known: Dict[int, bytearray] = {}
        self.names: Dict[int, str] = {}

    def copy(self) -> 'Memory':
        m = Memory()
        m.data = {b: bytearray(d) for b, d in self.data.items()}
        m.known = {b: bytearray(k) for b, k in self.known.items()}
        m.names = dict(self.names)
        return m

    def define(self, bank: int, what: str, data: Optional[bytes] = None
               ) -> None:
        """Bank `bank` known whole: zeros, or `data` (64 KB)."""
        if data is not None and len(data) != BANK:
            raise ValueError('a bank is 64 KB')
        self.data[bank] = bytearray(data if data is not None else BANK)
        self.known[bank] = bytearray(b'\x01' * BANK)
        self.names[bank] = what

    def write(self, address: int, data: bytes, mark: bool = True) -> None:
        at = 0
        while at < len(data):
            a = (address + at) & 0xFFFFFF
            bank, off = a >> 16, a & 0xFFFF
            n = min(len(data) - at, BANK - off)
            if bank not in self.data:
                self.data[bank] = bytearray(BANK)
                self.known[bank] = bytearray(BANK)
            self.data[bank][off:off + n] = data[at:at + n]
            if mark:
                self.known[bank][off:off + n] = b'\x01' * n
            at += n

    def read(self, address: int, length: int) -> bytes:
        out = bytearray()
        at = 0
        while at < length:
            a = (address + at) & 0xFFFFFF
            bank, off = a >> 16, a & 0xFFFF
            n = min(length - at, BANK - off)
            known = self.known.get(bank)
            if known is None or known[off:off + n].count(1) != n:
                first = off if known is None else \
                    off + known[off:off + n].index(0)
                raise ModelError('$%02X:%04X is not in the model (bank %s)'
                                 % (bank, first, self.names.get(
                                     bank, 'unknown')))
            out += self.data[bank][off:off + n]
            at += n
        return bytes(out)

    def u16(self, address: int) -> int:
        return u16(self.read(address, 2))

# ---------------------------------------------------------------------------
# The release
# ---------------------------------------------------------------------------

class Entry(NamedTuple):
    lump: int           # a lump number, or FILL, UNIT, UNIT_RAW, a song
    bank: int           # the byte: a window index | $80, else a bank
    offset: int
    source: int         # the store address (24 bits)
    length: int


class SetRecord(NamedTuple):
    entries: List[Entry]
    banks: int          # window banks of the image
    disk: int
    end: int            # the image's end in its last bank (0: next bank)


class DirEntry(NamedTuple):
    name: str
    filepos: int
    size: int


class Release:
    """The release image: its resident memory, its directory, its level
    store's sets and units."""

    def __init__(self, path: Path = RELEASE):
        image = hdv.load(str(path))
        self.image = image
        self.store_base, self.store = image.level_store()
        if self.store_base != STORE_BANK << 16 or \
                self.store[:6] != b'DOOMST':
            raise ModelError('the release\'s store is not at $40:0000')
        self.store_banks = image.store_banks
        self.memory = Memory()
        for seg in image.segments:
            if seg.address >> 16 >= STORE_BANK or seg.flags:
                continue
            self.memory.write(seg.address, seg.data)
        for bank in list(self.memory.data):
            self.memory.names[bank] = 'release'
        # the directory of the resident WAD (MM_WAD: "IWAD", the count,
        # the directory's offset; 16 bytes an entry: filepos, size words,
        # name)
        head = self.memory.read(MM_WAD, 12)
        ident, count, _, start = struct.unpack('<4shhi', head)
        if ident != b'IWAD':
            raise ModelError('no IWAD at MM_WAD')
        self.directory: List[DirEntry] = []
        for i in range(count):
            e = self.memory.read(MM_WAD + start + 16 * i, 16)
            pos, size, zero, raw = struct.unpack('<IHH8s', e)
            self.directory.append(DirEntry(ML.name8(raw), pos, size))
        self.dir_start = start
        self.placeholder_pos = 12 + 16 * count     # LV_PLACE
        self.names = [e.name for e in self.directory]
        nsets = u16(self.store, 6)
        self.sets: List[SetRecord] = []
        for k in range(nsets):
            off, cnt, nb, disk, end, _ = struct.unpack_from(
                '<IHBBHH', self.store, 8 + SETREC * k)
            ents = []
            for e in range(cnt):
                at = off + ENTRY * e
                lump, bank, offset = struct.unpack_from('<HBH', self.store,
                                                        at)
                src = int.from_bytes(self.store[at + 5:at + 8], 'little')
                length = u16(self.store, at + 8)
                ents.append(Entry(lump, bank, offset, src, length))
            self.sets.append(SetRecord(ents, nb, disk, end))
        self.common = len(self.sets) - 1
        self._units: Dict[int, bytes] = {}

    # -- lumps
    def index(self, name: str) -> int:
        """W_GetNumForName: the first lump of the name."""
        if name not in self.names:
            raise ModelError('no lump %s' % name)
        return self.names.index(name)

    def unit(self, source: int, length: int) -> bytes:
        """A unit's bytes: its stream at the store address (a length word,
        then B1)."""
        if source not in self._units:
            at = source - self.store_base
            size = u16(self.store, at) or BANK
            self._units[source] = b1.decode(
                self.store[at + 2:at + length], size)
        return self._units[source]

    def map_set(self, gamemap: int) -> SetRecord:
        return self.sets[gamemap - 1]

    def resident(self, lump: int) -> bool:
        e = self.directory[lump]
        return e.filepos != self.placeholder_pos and e.size > 0

    def resident_bytes(self, lump: int) -> bytes:
        e = self.directory[lump]
        return self.memory.read(MM_WAD + e.filepos, e.size)

    def table(self, symbol: str, length: int) -> bytes:
        """Bytes of the release's memory by a symbol of the link map."""
        return self.memory.read(symbol_address(symbol), length)


_SYMBOLS = None


def symbols():
    """The link map's symbols (tools/bridge/linkmap.py), once."""
    global _SYMBOLS
    if _SYMBOLS is None:
        from bridge import linkmap as blink
        _SYMBOLS = blink.Symbols()
    return _SYMBOLS


def symbol_address(name: str) -> int:
    return symbols().address(name)


# ---------------------------------------------------------------------------
# The machine's window (W_InitLevels, picBases)
# ---------------------------------------------------------------------------

class Window(NamedTuple):
    banks: List[int]                    # LV_WIN
    next: Dict[int, int]                # W_NEXTBANK (0: none)
    pict: int                           # LV_PICT: the picture sets' first

    def index(self, bank: int) -> Optional[int]:
        return self.banks.index(bank) if bank in self.banks else None


def window(rel: Release) -> Window:
    banks = list(range(MM_WINDOW, MM_WINDOW_END)) + [0x0E, 0x0F] + \
        list(range(STORE_BANK + rel.store_banks, MM_MUSBANK_BANK))
    nxt = {b: 0 for b in range(256)}
    for a, b in zip(banks, banks[1:]):
        nxt[a] = b
    pict = len(banks)
    if len(banks) >= RES_MIN:
        inter = rel.sets[INTER_SET - 1].banks
        title = rel.sets[TITLE_SET - 1].banks
        pici = len(banks) - inter
        pict = pici - title
        nxt[banks[pict - 1]] = 0
    return Window(banks, nxt, pict)


# ---------------------------------------------------------------------------
# The level window of a map (W_LoadSet)
# ---------------------------------------------------------------------------

class Placed(NamedTuple):
    address: int        # its window address (24 bits)
    size: int


def entry_address(e: Entry, win: Window) -> int:
    if e.bank & 0x80:
        return win.banks[e.bank & 0x7F] << 16 | e.offset
    return e.bank << 16 | e.offset


def decoded_image(rel: Release, gamemap: int, win: Window
                  ) -> Dict[int, bytearray]:
    """The image banks as W_LoadSet writes them from the store: the
    common set's units (its first load), then the map's units and FILLs.
    Songs are skipped (they go outside the image)."""
    banks: Dict[int, bytearray] = {}
    rec = rel.map_set(gamemap)
    for k in range(max(rec.banks, rel.sets[rel.common].banks)):
        banks[win.banks[k]] = bytearray(BANK)
    for setrec in (rel.sets[rel.common], rec):
        for e in setrec.entries:
            if e.lump >= SONGS and e.lump not in (FILL, UNIT, UNIT_RAW):
                continue
            a = entry_address(e, win)
            bank, off = a >> 16, a & 0xFFFF
            if e.lump == FILL:
                n = e.length or BANK
                banks[bank][off:off + n] = bytes(n)
            elif e.lump == UNIT:
                data = rel.unit(e.source, e.length)
                banks[bank][off:off + len(data)] = data
            elif e.lump == UNIT_RAW:
                at = e.source - rel.store_base + 2
                data = rel.store[at:at + e.length - 2]
                banks[bank][off:off + len(data)] = data
    return banks


class Image(NamedTuple):
    banks: Dict[int, bytearray]         # bank -> its 64 KB
    lumps: Dict[int, Placed]            # the set's lumps at their addresses
    colstart: int                       # W_COLSTART (24 bits)
    zeroed_first: Optional[int]         # a bank W_LoadSet zeroed (a full
                                        #   last image bank)


def lump_image(rel: Release, gamemap: int, win: Window,
               lump_bytes: Callable[[int], bytes]) -> Image:
    """The image banks from the lumps: each lump of the set's lump
    entries at its address (lump_bytes(i): its bytes), zeros elsewhere."""
    rec = rel.map_set(gamemap)
    nb = rec.banks
    banks: Dict[int, bytearray] = {}
    for k in range(max(nb, rel.sets[rel.common].banks)):
        banks[win.banks[k]] = bytearray(BANK)
    placed: Dict[int, Placed] = {}
    for e in rec.entries:
        if e.lump >= SONGS:
            continue
        a = entry_address(e, win)
        size = rel.directory[e.lump].size
        placed[e.lump] = Placed(a, size)
        if not size:
            continue                    # a marker lump: only its address
        data = lump_bytes(e.lump)
        if len(data) != size:
            raise ModelError('lump %d (%s): %d bytes, the directory says %d'
                             % (e.lump, rel.names[e.lump], len(data), size))
        bank, off = a >> 16, a & 0xFFFF
        if off + size > BANK:
            raise ModelError('lump %d crosses its bank' % e.lump)
        banks[bank][off:off + size] = data
    last = win.banks[nb - 1]
    if rec.end:
        colstart = last << 16 | rec.end
        zeroed = None
    else:
        zeroed = win.banks[nb]
        colstart = zeroed << 16
    return Image(banks, placed, colstart, zeroed)


def check_image(rel: Release, gamemap: int, win: Window, image: Image
                ) -> int:
    """The lump image against the decoded units: every byte equal. The
    bytes compared."""
    decoded = decoded_image(rel, gamemap, win)
    n = 0
    for bank, data in decoded.items():
        mine = image.banks.get(bank)
        if mine is None:
            raise ModelError('bank $%02X is not in the lump image' % bank)
        if mine != data:
            at = next(i for i in range(BANK) if mine[i] != data[i])
            raise ModelError('E1M%d: the lump image differs from the '
                             'store\'s units at $%02X:%04X' % (
                                 gamemap, bank, at))
        n += BANK
    return n


# ---------------------------------------------------------------------------
# The column memory (R_MakeLevelColumns, R_MakeTextureColumns, colAlloc,
# W_LevelDone)
# ---------------------------------------------------------------------------

class Hole(NamedTuple):
    start: int
    end: int
    bank: int


class Columns:
    """The column memory's allocator and the texture columns."""

    def __init__(self, mem: Memory, win: Window, colstart: int,
                 cold: bytes, textures: Sequence[ML.Texture],
                 patch_lump: Callable[[int], int],
                 lump_address: Callable[[int], int]):
        self.mem = mem
        self.win = win
        self.colmem = colstart
        self.cold = cold
        self.textures = textures
        self.patch_lump = patch_lump        # PNAMES number -> lump
        self.lump_address = lump_address    # lump -> its address
        self.holes: List[List[int]] = []    # [start, end, bank]
        self.lost_holes: List[Tuple[int, int, int]] = []
        self.passno = 0
        self.made: List[int] = []
        self.loaded: Set[int] = set()       # R_GetTexture since Z_FreeTags
        self.lv_zb = 0
        self.blocks: List[Tuple[int, int, str]] = []    # (address, size,
                                                        #   what), in order
        mem.write(MM_COLDIR, bytes(COLDIR_SIZE))
        mem.names[MM_COLDIR >> 16] = 'COLDIR'

    # -- textures
    def is_cold(self, t: int) -> bool:
        """cmBit: CM_COLD's bit t (a 16-bit read: texture 255's bit is in
        the byte after the table, also cold)."""
        byte = self.cold[t >> 3] if (t >> 3) < len(self.cold) else 0xFF
        return bool(byte >> (t & 7) & 1)

    def coldir(self, t: int) -> Tuple[int, int]:
        e = self.mem.read(MM_COLDIR + 4 * t, 4)
        return e[0] | e[1] << 8 | e[2] << 16, e[3]

    def made_t(self, t: int) -> bool:
        """madeT: COLDIR's high word not 0 (a number of 256 or more: no)."""
        if not 0 <= t < 256:
            return False
        return u16(self.mem.read(MM_COLDIR + 4 * t + 2, 2)) != 0

    def widthmask(self, t: int) -> int:
        w = self.textures[t].width
        a = 1
        while True:
            a = (a << 1) & 0xFFFF
            if a == w or s16(a - w) < 0:
                continue
            break
        return ((a >> 1) - 1) & 0xFFFF

    def patch_width(self, lump: int) -> int:
        return self.mem.u16(self.lump_address(lump))

    def overlapped(self, t: int) -> bool:
        ps = self.textures[t].patches
        spans = [(ox, s16(ox + self.patch_width(self.patch_lump(p))))
                 for ox, oy, p in ps]
        for j in range(len(spans)):
            l1, r1 = spans[j]
            for k in range(j + 1, len(spans)):
                l2, r2 = spans[k]
                if s16(l2 - r1) < 0 and s16(l1 - r2) < 0:
                    return True
        return False

    # -- the allocator
    def zero_bank(self, bank: int) -> None:
        """W_ZeroBank: the bank zeroed, unless LV_ZB says it is (then
        LV_ZB 0)."""
        if bank == self.lv_zb:
            self.lv_zb = 0
            return
        self.mem.define(bank, 'column memory (zeroed)')

    def alloc(self, size: int, hot: bool, what: str) -> int:
        if not hot:
            for h in self.holes:
                if h[1] - h[0] >= size:
                    a = h[2] << 16 | h[0]
                    h[0] += size
                    self.blocks.append((a, size, what))
                    return a
        lo = self.colmem & 0xFFFF
        if lo + size > 0xFFFF or lo + size + OVERREAD > 0xFFFF:
            bank = self.win.next.get(self.colmem >> 16, 0)
            if not bank:
                raise ModelError('R_ColumnAlloc: the wall textures of the '
                                 'level fill the level window')
            self.colmem = bank << 16
            self.zero_bank(bank)
        if hot:
            lo = self.colmem & 0xFFFF
            if (lo & 0x7FFF) < 0x2000 and (lo & 0x7FFF) + size >= 0x0901:
                end = (lo & 0x8000) | 0x2000
                hole = [lo, end, self.colmem >> 16]
                if len(self.holes) < CM_MAX:
                    self.holes.append(hole)
                else:
                    self.lost_holes.append(tuple(hole))
                self.colmem = (self.colmem & 0xFF0000) | end
        a = self.colmem
        self.colmem = (self.colmem & 0xFF0000) | ((a + size) & 0xFFFF)
        self.blocks.append((a, size, what))
        return a

    # -- R_GetTexture, R_MakeTextureColumns
    def get_texture(self, t: int) -> None:
        self.loaded.add(t)

    def make(self, t: int) -> None:
        self.get_texture(t)
        tex = self.textures[t]
        wm = self.widthmask(t)
        width = wm + 1
        table = self.alloc(4 * width, False, 'table %d' % t)
        over = self.overlapped(t)
        for xc in range(width):
            src = 0
            if over:
                src = self.composed(t, xc)
            else:
                pnum, x = -1, xc
                if len(tex.patches) == 1:
                    pnum = self.patch_lump(tex.patches[0][2])
                else:
                    for ox, oy, p in tex.patches:
                        x = s16(xc - ox)
                        if x < 0:
                            continue
                        lump = self.patch_lump(p)
                        if s16(x - self.patch_width(lump)) >= 0:
                            continue
                        pnum = lump
                        break
                    else:
                        x = xc
                if pnum >= 0:
                    # src = patch + columnofs[x] + 3: columnofs + 3 (16
                    # bits), then the patch's address with the carry into
                    # its bank
                    a = self.lump_address(pnum)
                    colofs = self.mem.u16(
                        (a & 0xFF0000) + ((a & 0xFFFF) + ((8 + 4 * x)
                                                         & 0xFFFF)))
                    low = (a & 0xFFFF) + ((colofs + 3) & 0xFFFF)
                    src = ((a & 0xFF0000) + low) & 0xFFFFFF
            if src:
                entry = struct.pack('<HH', src & 0xFFFF, src >> 16)
            else:
                entry = struct.pack('<HH', 0, 0x0100)
            self.mem.write(table + 4 * xc, entry)
        self.mem.write(MM_COLDIR + 4 * t, struct.pack(
            '<HH', table & 0xFFFF, (wm << 8 & 0xFF00) | (table >> 16)))
        self.made.append(t)

    def patch_column(self, ox: int, p: int, xc: int) -> Optional[int]:
        x = s16(xc - ox)
        if x < 0:
            return None
        lump = self.patch_lump(p)
        a = self.lump_address(lump)
        if s16(x - self.mem.u16(a)) >= 0:
            return None
        colofs = self.mem.u16((a & 0xFF0000) +
                              ((a & 0xFFFF) + ((8 + 4 * x) & 0xFFFF)))
        low = (a & 0xFFFF) + colofs
        return ((a & 0xFF0000) + (low & 0x10000) + (low & 0xFFFF)) & 0xFFFFFF

    def composed(self, t: int, xc: int) -> int:
        tex = self.textures[t]
        height = tex.height
        covers, only, onlyy = 0, 0, 0
        for ox, oy, p in tex.patches:
            col = self.patch_column(ox, p, xc)
            if col is None:
                continue
            covers += 1
            only, onlyy = col, oy
        if covers == 1 and onlyy == 0:
            head = self.mem.read(only, 2)
            if head[0] == 0 and s16(head[1] - height) >= 0 and \
                    self.mem.read(only + head[1] + 4, 1)[0] == 0xFF:
                return (only + 3) & 0xFFFFFF
        a = self.alloc(height, not self.is_cold(t),
                       'column %d:%d' % (t, xc))
        self.mem.write(a, bytes(height))
        for ox, oy, p in tex.patches:
            col = self.patch_column(ox, p, xc)
            if col is None:
                continue
            self.draw_column(col, a, oy, height)
        return a

    def draw_column(self, col: int, dest: int, originy: int,
                    height: int) -> None:
        at = col
        while True:
            head = self.mem.read(at, 2)
            if head[0] == 0xFF:
                return
            position = s16(originy + head[0])
            count = head[1]
            if position < 0:
                count = s16(count + position)
                position = 0
            if s16(position + count - height) > 0:
                count = s16(height - position)
            if count > 0:
                self.mem.write((dest + position) & 0xFFFFFF,
                               self.mem.read(at + 3, count))
            at = (at + head[1] + 4) & 0xFFFFFF

    # -- R_MakeLevelColumns
    def level(self, sides: Sequence[Tuple[int, int, int]]) -> None:
        """sides: each side's (top, middle, bottom) texture numbers (as the
        game's sign-extended bytes). sideColumns: a texture not 0 whose
        COLDIR entry is all 0, in pass 1 only the hot ones."""
        self.holes = []
        self.passno = 1
        while True:
            for top, mid, bottom in sides:
                for t in (top, mid, bottom):
                    if t == 0:
                        continue
                    if not 0 < t < 256:
                        raise ModelError('a side texture %d outside 1-255'
                                         % t)
                    if self.mem.read(MM_COLDIR + 4 * t, 4) != bytes(4):
                        continue
                    if self.passno == 1 and self.is_cold(t):
                        continue
                    self.make(t)
            if self.passno == 0:
                break
            self.passno = 0

    # -- W_LevelDone
    def more(self, switchlist: Sequence[int], basepic: int) -> None:
        def make_t(t: int) -> None:
            if self.made_t(t) or not 0 <= t < 256:
                return
            index = self.win.index(self.colmem >> 16)
            if index is None or index >= MORE_BANKS:
                return
            self.make(t)
        for i in range(0, NUMSW2, 2):
            off, on = switchlist[i], switchlist[i + 1]
            if self.made_t(off):
                make_t(on)
            if self.made_t(on):
                make_t(off)
        if basepic < 254:
            if any(self.made_t(basepic + k) for k in range(3)):
                for k in range(3):
                    make_t(basepic + k)

    def done(self) -> Optional[int]:
        """W_LevelDone's end: the bank after colmem's zeroed (LV_ZB)."""
        bank = self.win.next.get(self.colmem >> 16, 0)
        if bank:
            self.zero_bank(bank)
            self.lv_zb = bank
            return bank
        return None


# ---------------------------------------------------------------------------
# The whole model of a map's load
# ---------------------------------------------------------------------------

class GameData(NamedTuple):
    """What the model takes from DOOM1.WAD and the release, shared by the
    maps."""
    rel: Release
    wad: List[Tuple[str, bytes]]
    tex1: bytes                         # the game's TEXTURE1
    pnames: bytes
    textures: List[ML.Texture]
    tex_names: List[str]
    patch_names: List[str]
    switchlist: List[int]
    sw_idx: bytes                       # SW_IDX (256)
    basepic: int
    cold: bytes                         # CM_COLD
    wad_by_name: Dict[str, bytes]       # DOOM1.WAD, the last of a name


def texture_number(names: Sequence[str], name: str) -> int:
    """R_CheckTextureNumForName: 0 for '-', the first of the name; none:
    I_Error (a stop here)."""
    if name.startswith('-'):
        return 0
    if name not in names:
        raise ModelError('texture %s is not in TEXTURE1' % name)
    return names.index(name)


def game_data(rel: Optional[Release] = None, wad_path: Path = WAD_PATH
              ) -> GameData:
    rel = rel or Release()
    wad = ML.read_wad(Path(wad_path).read_bytes())
    by_name = {}
    for name, data in wad:
        by_name[name] = data            # (the last of a name)
    tex1 = ML.texture1(by_name['TEXTURE1'])
    pn = ML.pnames(by_name['PNAMES'])
    textures = ML.textures(tex1)
    names = [t.name for t in textures]
    switchlist = [texture_number(names, n) for n in SWITCH_NAMES]
    sw_idx = bytearray(256)
    for i in range(NUMSW2 - 1, -1, -1):
        t = switchlist[i]
        if t < 256:
            sw_idx[t] = (2 * i + 1) & 0xFF
    basepic = texture_number(names, SLIME_FIRST)
    cold = rel.table('r_data65.s:CM_COLD', CM_COLD_BYTES)
    return GameData(rel, wad, tex1, pn, textures, names,
                    ML.patch_names(pn), switchlist, bytes(sw_idx), basepic,
                    cold, by_name)


class Load(NamedTuple):
    """A map's load as upstream leaves it at the end of W_LevelDone."""
    gamemap: int
    mem: Memory
    win: Window
    image: Image
    game: ML.GameMap
    lump_addr: Dict[int, int]           # every lump's address (placeholder
                                        #   for those not in memory)
    lump_size: Dict[int, int]
    placeholder: int
    columns: Columns
    made_load: List[int]                # R_MakeLevelColumns' textures
    made_more: List[int]                # moreColumns'
    zeroed: List[int]                   # banks zeroed, in order
    lv_zb: Optional[int]
    flat_numbers: Dict[str, int]


def release_lump(rel: Release, gamemap: int, win: Window, lump: int
                 ) -> bytes:
    """A lump of the map's set as the release's units hold it."""
    for e in rel.map_set(gamemap).entries:
        if e.lump == lump:
            a = entry_address(e, win)
            break
    else:
        raise ModelError('lump %d is not in the set of E1M%d' % (lump,
                                                                gamemap))
    size = rel.directory[lump].size
    banks = decoded_image(rel, gamemap, win)
    return bytes(banks[a >> 16][a & 0xFFFF:(a & 0xFFFF) + size])


# The lumps of a set that are upstream's own build artifacts, not
# DOOM1.WAD's (docs/LEVELS.md): taken from the release's units
RELEASE_LUMPS = ('GSVIEW', 'GSFLAT', 'SGRID')


def lump_source(gd: GameData, game: ML.GameMap, gamemap: int,
                release_bytes: Callable[[int], bytes]
                ) -> Callable[[int], bytes]:
    """lump_bytes for lump_image: the map's own lumps in the game's form
    (maplumps.py), the release's build artifacts, DOOM1.WAD's bytes for
    the rest (patches, sprites; the last lump of a name)."""
    rel = gd.rel
    marker = rel.index('E1M%d' % gamemap)

    def get(lump: int) -> bytes:
        if marker < lump <= marker + len(ML.GAME_ML):
            name = ML.GAME_ML[lump - marker - 1]
            if rel.names[lump] != name:
                raise ModelError('lump %d is %s, not %s' % (
                    lump, rel.names[lump], name))
            return game.lumps[name]
        name = rel.names[lump]
        if name.startswith(RELEASE_LUMPS):
            return release_bytes(lump)
        if name not in gd.wad_by_name:
            raise ModelError('lump %s is not in DOOM1.WAD' % name)
        return gd.wad_by_name[name]
    return get


def map_sides(game: ML.GameMap) -> List[Tuple[int, int, int]]:
    """Each packed side's (top, middle, bottom) as the game's sign-extended
    bytes."""
    return [(s[2], s[4], s[3]) for s in game.sides]


def load(gd: GameData, gamemap: int) -> Load:
    rel = gd.rel
    win = window(rel)
    # the flat numbering from the release's SECTORS
    rel_sectors = release_lump(rel, gamemap, win,
                               rel.index('E1M%d' % gamemap) + 7)
    numbers = ML.flat_numbers(ML.map_lumps(gd.wad, gamemap)['SECTORS'],
                              rel_sectors)
    game = ML.GameMap(gd.wad, gamemap, gd.tex_names, numbers)
    decoded = decoded_image(rel, gamemap, win)

    def release_bytes(lump: int) -> bytes:
        for e in rel.map_set(gamemap).entries:
            if e.lump == lump:
                a = entry_address(e, win)
                size = rel.directory[lump].size
                return bytes(decoded[a >> 16][a & 0xFFFF:(a & 0xFFFF) + size])
        raise ModelError('lump %d is not in the set' % lump)
    image = lump_image(rel, gamemap, win,
                       lump_source(gd, game, gamemap, release_bytes))
    check_image(rel, gamemap, win, image)
    # the memory: the release's resident banks, the store, the image
    mem = rel.memory.copy()
    for k in range(rel.store_banks):
        bank = STORE_BANK + k
        data = rel.store[k * BANK:(k + 1) * BANK]
        mem.write(bank << 16, data)
        mem.names[bank] = 'level store'
    for bank, data in image.banks.items():
        mem.define(bank, 'level window (image)', bytes(data))
    # the directory as the set leaves it (only filepos changes)
    lump_addr: Dict[int, int] = {}
    lump_size: Dict[int, int] = {}
    placeholder = MM_WAD + rel.placeholder_pos
    for i, e in enumerate(rel.directory):
        lump_size[i] = e.size
        lump_addr[i] = (MM_WAD + e.filepos) & 0xFFFFFF
    for lump, p in image.lumps.items():
        lump_addr[lump] = p.address
        mem.write(MM_WAD + rel.dir_start + 16 * lump, struct.pack(
            '<HH', p.address & 0xFFFF, ((p.address >> 16) - MM_WAD_BANK)
            & 0xFFFF))
    # the column memory
    zeroed = []
    if image.zeroed_first is not None:
        mem.define(image.zeroed_first, 'column memory (zeroed)')
        zeroed.append(image.zeroed_first)

    def patch_lump(p: int) -> int:
        return rel.index(gd.patch_names[p])
    cols = Columns(mem, win, image.colstart, gd.cold, gd.textures,
                   patch_lump, lambda lump: lump_addr[lump])
    original_zero = cols.zero_bank

    def zero_bank(bank: int) -> None:
        zeroed.append(bank)
        original_zero(bank)
    cols.zero_bank = zero_bank
    # P_LoadTexture of each side's middle, top, bottom (and a switch's
    # other texture): what R_GetTexture loads (textures[], TXMP)
    for top, mid, bottom in map_sides(game):
        for t in (mid, top, bottom):
            cols.get_texture(t)
            if 0 <= t < 256 and gd.sw_idx[t]:
                k = gd.sw_idx[t] - 1
                cols.get_texture(gd.switchlist[(k >> 1) ^ 1])
    cols.level(map_sides(game))
    made_load = list(cols.made)
    cols.more(gd.switchlist, gd.basepic)
    made_more = cols.made[len(made_load):]
    lv_zb = cols.done()
    return Load(gamemap, mem, win, image, game, lump_addr, lump_size,
                placeholder, cols, made_load, made_more, zeroed, lv_zb,
                numbers)


# ---------------------------------------------------------------------------
# The bytes a run-time allocation can change
# ---------------------------------------------------------------------------

def free_parts(ld: Load) -> List[Tuple[int, int]]:
    """The bytes a run-time allocation can change at the end of the load:
    each kept hole's free part, and colmem to its bank's end (24-bit
    [start, end) ranges)."""
    out = []
    for start, end, bank in ld.columns.holes:
        if end > start:
            out.append((bank << 16 | start, bank << 16 | end))
    cm = ld.columns.colmem
    out.append((cm, (cm & 0xFF0000) + BANK))
    return out
