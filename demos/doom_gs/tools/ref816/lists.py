"""The column records of upstream's 3D view, decoded from memory.

Upstream's src/iigs/lists.inc lays them out: each frame the walls,
floors, ceilings, sprites, masked walls and shadows become records in
the list of their column, in bank RECBANK ($1D), and R_DrawLists
(src/iigs/r_list65.s) draws them. The list of column c starts at
offset 0 of page COLPAGE(c): c for c < 9, c + $17 up to column 113,
c + $2E after. A full page goes on in an extra page (a K_NEXT record);
the extra pages are XP_FIRST..$FF. COLW holds the end of each list:
the page << 8 | the offset.

All constants come from the link map (symbols of r_list65.s), so this
module holds no address of its own.
"""

from typing import Callable, Dict, Iterator, List, NamedTuple, Sequence, \
    Tuple

UNIT = 'r_list65.s'
KINDS = ('K_TEX', 'K_FILL', 'K_TEXC', 'K_FUZZ', 'K_OVL', 'K_NEXT')
SIZES = {'K_TEX': 'TEX_SIZE', 'K_FILL': 'FILL_SIZE', 'K_TEXC': 'TEXC_SIZE',
         'K_FUZZ': 'FUZZ_SIZE', 'K_OVL': 'OVL_SIZE', 'K_NEXT': 'NEXT_SIZE'}
# The bytes a texture record's texels may be read from: the drawers index
# them with the texel position, 7 bits (lists.inc, R_TI: 0..127).
TEXEL_SPAN = 128
PAGE = 0x100


class DecodeError(ValueError):
    pass


class Layout(NamedTuple):
    recbase: int
    xp_first: int
    colw: int
    xpnext: int
    columns: int
    kinds: Dict[int, str]        # kind byte -> name
    sizes: Dict[str, int]
    fields: Dict[str, int]       # R_* offsets


def layout(units: Dict) -> Layout:
    """The layout from the link map's units (linkmap['game']['units'])."""
    u = units[UNIT]
    fields = {name: u[name] for name in u
              if name.startswith('R_') and isinstance(u[name], int) and
              u[name] < 16}
    return Layout(recbase=u['RECBASE'], xp_first=u['XP_FIRST'],
                  colw=u['COLW'], xpnext=u['XPNEXT'],
                  columns=u['CONST_VIEWWIDTH'],
                  kinds={u[k]: k for k in KINDS},
                  sizes={k: u[SIZES[k]] for k in KINDS}, fields=fields)


def colpage(column: int) -> int:
    """COLPAGE of lists.inc: the first page of the list of a column."""
    page = column
    if page >= 9:
        page += 0x17
        if page >= 0x89:
            page += 0x17
    return page


def record_pages(lay: Layout) -> List[Tuple[int, int]]:
    """The pages the lists can use, as runs (first page, count)."""
    pages = sorted(set(colpage(c) for c in range(lay.columns)) |
                   set(range(lay.xp_first, 0x100)))
    runs: List[Tuple[int, int]] = []
    for page in pages:
        if runs and runs[-1][0] + runs[-1][1] == page:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((page, 1))
    return runs


class Record(NamedTuple):
    column: int
    page: int
    offset: int
    kind: str
    data: bytes                  # the record's bytes, the kind first
    texels: int                  # K_TEX, K_TEXC: the 24-bit texel address

    def field(self, lay: Layout, name: str, size: int = 1) -> int:
        at = lay.fields[name]
        return int.from_bytes(self.data[at:at + size], 'little')


def walk(read: Callable[[int, int], bytes], lay: Layout
         ) -> Iterator[Record]:
    """Every record of every column in list order (K_NEXT included),
    read through `read(address, length)`."""
    base = lay.recbase
    for column in range(lay.columns):
        end = int.from_bytes(read(lay.colw + 2 * column, 2), 'little')
        page, offset = colpage(column), 0
        bank = None
        steps = 0
        while (page << 8 | offset) != end:
            steps += 1
            if steps > 0x10000 or offset >= PAGE:
                raise DecodeError('column %d: the list does not reach its '
                                  'end $%04X' % (column, end))
            kind_byte = read(base + (page << 8) + offset, 1)[0]
            kind = lay.kinds.get(kind_byte)
            if kind is None:
                raise DecodeError('column %d: a record of unknown kind %d at '
                                  '$%02X%02X' % (column, kind_byte, page,
                                                 offset))
            size = lay.sizes[kind]
            data = read(base + (page << 8) + offset, size)
            texels = 0
            if kind == 'K_TEX':
                at = lay.fields['R_SRC']
                texels = int.from_bytes(data[at:at + 3], 'little')
                bank = texels >> 16
            elif kind == 'K_TEXC':
                if bank is None:
                    raise DecodeError('column %d: a K_TEXC with no K_TEX '
                                      'before it' % column)
                at = lay.fields['R_TCSRC']
                texels = bank << 16 | int.from_bytes(data[at:at + 2],
                                                     'little')
            yield Record(column, page, offset, kind, data, texels)
            if kind == 'K_NEXT':
                page, offset = data[lay.fields['R_PAGE']], 0
            else:
                offset += size


def texel_ranges(records: Sequence[Record]) -> List[Tuple[int, int]]:
    """The bytes the texture records may read texels from, merged:
    (address, length) in address order."""
    spans = sorted((r.texels, r.texels + TEXEL_SPAN) for r in records
                   if r.kind in ('K_TEX', 'K_TEXC'))
    return merge(spans)


def merge(spans: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """(start, end) spans, merged, as (address, length) runs that do not
    cross a bank."""
    out: List[Tuple[int, int]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][0] + out[-1][1]:
            first = out[-1][0]
            out[-1] = (first, max(end, first + out[-1][1]) - first)
        else:
            out.append((start, end - start))
    split: List[Tuple[int, int]] = []
    for start, length in out:
        while length:
            count = min(length, 0x10000 - (start & 0xffff))
            split.append((start, count))
            start, length = start + count, length - count
    return split


def summary(records: Sequence[Record], lay: Layout) -> Dict[str, int]:
    counts = {kind: 0 for kind in KINDS}
    for r in records:
        counts[r.kind] += 1
    counts['records'] = sum(counts[k] for k in KINDS if k != 'K_NEXT')
    counts['bytes'] = sum(len(r.data) for r in records)
    return counts
