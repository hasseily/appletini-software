"""The game's form of DOOM1.WAD's lumps (docs/LEVELS.md):
our own transforms of the map lumps, TEXTURE1 and PNAMES into the form
upstream's P_SetupLevel and R_InitTextures read, written from the format
that upstream's build tool documents (build/upstream/tools/wadtool.py
describes the form; none of its code runs here).

The forms, all little endian:

    THINGS    8 bytes a thing: x, y, type (words), angle / 45, options
              (bytes); the things of types 2, 3, 4 (other players'
              starts), 11 (deathmatch starts) and those with the "not in
              single player" option (16) are left out
    LINEDEFS  15 bytes a line: v1.x, v1.y, v2.x, v2.y (the coordinates in
              place of the vertex numbers), the two sides (words, $FFFF
              none), flags, special, tag (their low bytes)
    SIDEDEFS  7 bytes a side: textureoffset (a word), rowoffset (its low
              byte), the top, bottom and middle textures (TEXTURE1
              numbers, 0 for "-" or an unknown name) and the sector (low
              bytes). The sides are packed: a line with a special keeps
              sides of its own, the other lines share every identical
              side, numbered in the order the lines (front, then back)
              first use them
    SEGS      18 bytes a seg: v1.x, v1.y, v2.x, v2.y, offset, angle +
              $4000, the packed side, the line (words), the front sector
              and the back sector (bytes, -1: none or not two-sided)
    SSECTORS  1 byte a subsector: its seg count (the first seg is the sum
              of the counts before; the WAD's must be in that order)
    NODES     DOOM1.WAD's, unchanged
    SECTORS   12 bytes a sector: floor and ceiling heights, floor and
              ceiling flat numbers (words: the map's flat numbering,
              -2 the sky), light, special (low bytes), tag (a word)
    REJECT    DOOM1.WAD's, unchanged
    BLOCKMAP  the header (origin, columns, rows), then an offset a block,
              then the lists: each list as 0, its lines, -1; the lists
              stored longest first (equal lengths: the higher block
              first), a list that is the end of one stored before it
              pointing into that one (its leading word is then the line
              before, not a 0: lineBlocks skips a list's first word)
    TEXTURE1  the count, an offset a texture, then each texture as its
              name (8), width, height, patch count (words), and each patch
              as originx, originy, patch number (words)
    PNAMES    DOOM1.WAD's with the names upper case

The flat numbers of a map are not in any WAD (upstream's build lists them
per map): `flat_numbers` pairs DOOM1.WAD's sector flat names with the
release's game SECTORS lump and fails unless the pairing is one to one.
"""

import struct
from typing import Dict, List, Sequence, Tuple

ML_NAMES = ('THINGS', 'LINEDEFS', 'SIDEDEFS', 'VERTEXES', 'SEGS',
            'SSECTORS', 'NODES', 'SECTORS', 'REJECT', 'BLOCKMAP')
# the game's map lumps after the map name lump (p_setup65.s ML_*: no
# VERTEXES, upstream's build removes it)
GAME_ML = ('THINGS', 'LINEDEFS', 'SIDEDEFS', 'SEGS', 'SSECTORS', 'NODES',
           'SECTORS', 'REJECT', 'BLOCKMAP')
NO_INDEX = 0xFFFF
ML_TWOSIDED = 4
MTF_NOTSINGLE = 16
LEFT_OUT_TYPES = (2, 3, 4, 11)
SKY_FLAT = 'F_SKY1'
SKY_NUMBER = -2


class LumpError(ValueError):
    pass


def name8(raw: bytes) -> str:
    return raw.split(b'\0', 1)[0].decode('latin-1').upper()


def read_wad(data: bytes) -> List[Tuple[str, bytes]]:
    """The lumps of a WAD file, (name upper case, bytes), in order."""
    ident, count, start = struct.unpack_from('<4sii', data, 0)
    if ident not in (b'IWAD', b'PWAD'):
        raise LumpError('not a WAD file')
    out = []
    for i in range(count):
        pos, size, raw = struct.unpack_from('<ii8s', data, start + 16 * i)
        out.append((name8(raw), bytes(data[pos:pos + size])))
    return out


def low(v: int) -> int:
    """The low byte of v as a signed byte (the game's int8 fields)."""
    v &= 0xFF
    return v - 256 if v >= 128 else v


# ---------------------------------------------------------------------------
# Textures
# ---------------------------------------------------------------------------

def texture1(raw: bytes) -> bytes:
    count = struct.unpack_from('<i', raw, 0)[0]
    offsets = struct.unpack_from('<%di' % count, raw, 4)
    out = bytearray(4 + 4 * count)
    struct.pack_into('<i', out, 0, count)
    starts = []
    for off in offsets:
        name = raw[off:off + 8]
        width, height = struct.unpack_from('<hh', raw, off + 12)
        npatches = struct.unpack_from('<h', raw, off + 20)[0]
        starts.append(len(out))
        out += name + struct.pack('<hhh', width, height, npatches)
        at = off + 22
        for _ in range(npatches):
            ox, oy, patch = struct.unpack_from('<hhh', raw, at)
            out += struct.pack('<hhh', ox, oy, patch)
            at += 10
    struct.pack_into('<%di' % count, out, 4, *starts)
    return bytes(out)


def pnames(raw: bytes) -> bytes:
    out = bytearray(raw)
    for i in range(4, len(out)):
        if 0x61 <= out[i] <= 0x7A:
            out[i] -= 0x20
    return bytes(out)


class Texture:
    def __init__(self, name: str, width: int, height: int,
                 patches: Sequence[Tuple[int, int, int]]):
        self.name = name
        self.width = width
        self.height = height
        self.patches = list(patches)        # (originx, originy, PNAMES no.)


def textures(game_tex1: bytes) -> List[Texture]:
    """The textures of the game's TEXTURE1 (texture1's form)."""
    count = struct.unpack_from('<i', game_tex1, 0)[0]
    out = []
    for off in struct.unpack_from('<%di' % count, game_tex1, 4):
        name = name8(game_tex1[off:off + 8])
        width, height, n = struct.unpack_from('<hhh', game_tex1, off + 8)
        patches = [struct.unpack_from('<hhh', game_tex1, off + 14 + 6 * k)
                   for k in range(n)]
        out.append(Texture(name, width, height, patches))
    return out


def patch_names(game_pnames: bytes) -> List[str]:
    count = struct.unpack_from('<i', game_pnames, 0)[0]
    return [name8(game_pnames[4 + 8 * i:12 + 8 * i]) for i in range(count)]


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------

def map_lumps(wad: Sequence[Tuple[str, bytes]], gamemap: int
              ) -> Dict[str, bytes]:
    """DOOM1.WAD's lumps of map E1M<gamemap>, by name."""
    names = [n for n, _ in wad]
    marker = 'E1M%d' % gamemap
    if names.count(marker) != 1:
        raise LumpError('%d lumps %s' % (names.count(marker), marker))
    base = names.index(marker)
    out = {}
    for k, want in enumerate(ML_NAMES):
        name, data = wad[base + 1 + k]
        if name != want:
            raise LumpError('%s: lump %d is %s, not %s' % (marker, k + 1,
                                                           name, want))
        out[want] = data
    return out


def things(raw: bytes) -> bytes:
    out = bytearray()
    for i in range(len(raw) // 10):
        x, y, angle, kind, options = struct.unpack_from('<hhhhh', raw, 10 * i)
        if kind in LEFT_OUT_TYPES or options & MTF_NOTSINGLE:
            continue
        out += struct.pack('<hhhbb', x, y, kind, low(angle // 45),
                           low(options))
    return bytes(out)


def vertexes(raw: bytes) -> List[Tuple[int, int]]:
    return [struct.unpack_from('<hh', raw, 4 * i)
            for i in range(len(raw) // 4)]


Line = List[int]        # v1x, v1y, v2x, v2y, side0, side1, flags, special,
Side = Tuple[int, ...]  #   tag; textureoffset, rowoffset, top, bottom, mid,
                        #   sector


def lines_of(raw: bytes, verts: Sequence[Tuple[int, int]]) -> List[Line]:
    out = []
    for i in range(len(raw) // 14):
        v1, v2, flags, special, tag, s0, s1 = struct.unpack_from(
            '<HHhhhHH', raw, 14 * i)
        out.append([verts[v1][0], verts[v1][1], verts[v2][0], verts[v2][1],
                    s0, s1, low(flags), low(special), low(tag)])
    return out


def sides_of(raw: bytes, tex_names: Sequence[str]) -> List[Side]:
    first = {}
    for i, n in enumerate(tex_names):
        first.setdefault(n, i)

    def number(field: bytes) -> int:
        return low(first.get(name8(field), 0))
    out = []
    for i in range(len(raw) // 30):
        at = 30 * i
        toff, roff = struct.unpack_from('<hh', raw, at)
        sector = struct.unpack_from('<h', raw, at + 28)[0]
        out.append((toff, low(roff), number(raw[at + 4:at + 12]),
                    number(raw[at + 12:at + 20]), number(raw[at + 20:at + 28]),
                    low(sector)))
    return out


def pack_sides(lines: List[Line], sides: Sequence[Side]
               ) -> Tuple[List[Line], List[Side]]:
    """The packed sides and the lines renumbered to them."""
    packed: List[Side] = []
    shared: Dict[Side, int] = {}

    def number(side: Side, own: bool) -> int:
        if own:
            packed.append(side)
            return len(packed) - 1
        if side not in shared:
            packed.append(side)
            shared[side] = len(packed) - 1
        return shared[side]
    out = []
    for ln in lines:
        ln = list(ln)
        own = ln[7] != 0
        ln[4] = number(sides[ln[4]], own)
        ln[5] = number(sides[ln[5]], own) if ln[5] != NO_INDEX else NO_INDEX
        out.append(ln)
    return out, packed


def pack_lines(lines: Sequence[Line]) -> bytes:
    return b''.join(struct.pack('<hhhhHHbbb', *ln) for ln in lines)


def pack_side_list(sides: Sequence[Side]) -> bytes:
    return b''.join(struct.pack('<hbbbbb', *s) for s in sides)


def segs(raw: bytes, verts, lines: Sequence[Line], sides: Sequence[Side]
         ) -> bytes:
    out = bytearray()
    for i in range(len(raw) // 12):
        v1, v2, angle, line, side, offset = struct.unpack_from(
            '<HHhHhh', raw, 12 * i)
        ln = lines[line]
        sidenum = ln[4 + side]
        front = sides[sidenum][5]
        back = -1
        if ln[6] & ML_TWOSIDED:
            other = ln[4 + (side ^ 1)]
            if other != NO_INDEX:
                back = sides[other][5]
        out += struct.pack('<hhhhhHHHbb', verts[v1][0], verts[v1][1],
                           verts[v2][0], verts[v2][1], offset,
                           (angle + 0x4000) & 0xFFFF, sidenum, line,
                           front, back)
    return bytes(out)


def ssectors(raw: bytes) -> bytes:
    out = bytearray()
    first = 0
    for i in range(len(raw) // 4):
        count, start = struct.unpack_from('<hh', raw, 4 * i)
        if start != first:
            raise LumpError('subsector %d: its segs do not follow the '
                            'last one\'s' % i)
        if not 0 < count < 256:
            raise LumpError('subsector %d: %d segs' % (i, count))
        first += count
        out.append(count)
    return bytes(out)


def sector_flats(raw: bytes) -> List[Tuple[str, str]]:
    return [(name8(raw[26 * i + 4:26 * i + 12]),
             name8(raw[26 * i + 12:26 * i + 20]))
            for i in range(len(raw) // 26)]


def sectors(raw: bytes, numbers: Dict[str, int]) -> bytes:
    out = bytearray()
    for i in range(len(raw) // 26):
        at = 26 * i
        floor, ceiling = struct.unpack_from('<hh', raw, at)
        fpic, cpic = sector_flats(raw[at:at + 26])[0]
        light, special, tag = struct.unpack_from('<hhh', raw, at + 20)
        for name in (fpic, cpic):
            if name not in numbers:
                raise LumpError('sector %d: flat %s has no number' % (i,
                                                                      name))
        out += struct.pack('<hhhhbbh', floor, ceiling, numbers[fpic],
                           numbers[cpic], low(light), low(special), tag)
    return bytes(out)


def blockmap(raw: bytes) -> bytes:
    orgx, orgy, cols, rows = struct.unpack_from('<hhhh', raw, 0)
    n = cols * rows
    offsets = list(struct.unpack_from('<%dH' % n, raw, 8))
    lists = []
    for block, off in enumerate(offsets):
        at = 2 * off + 2                # (past the list's leading 0)
        items = []
        while True:
            v = struct.unpack_from('<h', raw, at)[0]
            if v == -1:
                break
            items.append(v)
            at += 2
        lists.append(items)
    out = bytearray(struct.pack('<hhhh', orgx, orgy, cols, rows))
    out += b'\xff\xff' * n
    stored: List[Tuple[List[int], int]] = []
    new = [0] * n
    for block in sorted(range(n), key=lambda b: (-len(lists[b]), -b)):
        items = lists[block]
        where = None
        for prev, at in stored:
            if len(prev) >= len(items) and \
                    prev[len(prev) - len(items):] == items:
                where = at + len(prev) - len(items)
                break
        if where is None:
            where = len(out) // 2
            out += struct.pack('<h', 0)
            out += b''.join(struct.pack('<h', v) for v in items)
            out += struct.pack('<h', -1)
            stored.append((items, where))
        new[block] = where
    struct.pack_into('<%dH' % n, out, 8, *new)
    return bytes(out)


def flat_numbers(wad_sectors: bytes, game_sectors: bytes) -> Dict[str, int]:
    """The map's flat numbering: each flat name of DOOM1.WAD's sectors
    with the number the release's game SECTORS lump gives it, checked one
    to one (and the sky -2)."""
    names = sector_flats(wad_sectors)
    if len(game_sectors) != 12 * len(names):
        raise LumpError('the game SECTORS has %d bytes for %d sectors'
                        % (len(game_sectors), len(names)))
    out: Dict[str, int] = {}
    for i, (fpic, cpic) in enumerate(names):
        fnum, cnum = struct.unpack_from('<hh', game_sectors, 12 * i + 4)
        for name, num in ((fpic, fnum), (cpic, cnum)):
            if out.setdefault(name, num) != num:
                raise LumpError('flat %s has numbers %d and %d'
                                % (name, out[name], num))
    if len(set(out.values())) != len(out):
        raise LumpError('two flats share a number')
    if SKY_FLAT in out and out[SKY_FLAT] != SKY_NUMBER:
        raise LumpError('the sky has the number %d' % out[SKY_FLAT])
    if any(v < 0 for k, v in out.items() if k != SKY_FLAT):
        raise LumpError('a flat other than the sky has a negative number')
    return out


class GameMap:
    """A map in the game's form, and its parts as lists."""

    def __init__(self, wad: Sequence[Tuple[str, bytes]], gamemap: int,
                 tex_names: Sequence[str], numbers: Dict[str, int]):
        raw = map_lumps(wad, gamemap)
        self.gamemap = gamemap
        verts = vertexes(raw['VERTEXES'])
        lines = lines_of(raw['LINEDEFS'], verts)
        sides = sides_of(raw['SIDEDEFS'], tex_names)
        self.lines, self.sides = pack_sides(lines, sides)
        self.lumps = {
            'THINGS': things(raw['THINGS']),
            'LINEDEFS': pack_lines(self.lines),
            'SIDEDEFS': pack_side_list(self.sides),
            'SEGS': segs(raw['SEGS'], verts, self.lines, self.sides),
            'SSECTORS': ssectors(raw['SSECTORS']),
            'NODES': raw['NODES'],
            'SECTORS': sectors(raw['SECTORS'], numbers),
            'REJECT': raw['REJECT'],
            'BLOCKMAP': blockmap(raw['BLOCKMAP']),
        }
        self.raw = raw

    # the parts the converter reads, decoded from the game's form
    def seg_list(self) -> List[Dict[str, int]]:
        d = self.lumps['SEGS']
        out = []
        for i in range(len(d) // 18):
            v = struct.unpack_from('<hhhhhHHHbb', d, 18 * i)
            out.append({'v1': (v[0], v[1]), 'v2': (v[2], v[3]),
                        'offset': v[4], 'angle': v[5], 'sidenum': v[6],
                        'linenum': v[7], 'front': v[8] & 0xFF,
                        'back': v[9] & 0xFF})
        return out

    def subsector_list(self) -> List[Tuple[int, int]]:
        out, first = [], 0
        for count in self.lumps['SSECTORS']:
            out.append((count, first))
            first += count
        return out

    def node_list(self) -> List[Tuple[int, ...]]:
        d = self.lumps['NODES']
        return [struct.unpack_from('<hhhh8hHH', d, 28 * i)
                for i in range(len(d) // 28)]

    def sector_list(self) -> List[Tuple[int, ...]]:
        d = self.lumps['SECTORS']
        return [struct.unpack_from('<hhhhbbh', d, 12 * i)
                for i in range(len(d) // 12)]

    def thing_list(self) -> List[Tuple[int, ...]]:
        d = self.lumps['THINGS']
        return [struct.unpack_from('<hhhbb', d, 8 * i)
                for i in range(len(d) // 8)]
