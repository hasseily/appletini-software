#!/usr/bin/env python3
"""Turn a replay capture into what the native replay reads.

Usage:  python3 tools/native/loader.py CAPTURE_DIR OUT.img
                [--screen FILE] [--bank-base N] [--batch-bytes N]
                [--build DIR]

A capture directory is tools/ref816/capture.py's (manifest.json and its
"before" files: records, COLW, screen, spans and covered ranges, weapon
skip, colormaps, fuzz table, texels), or tools/native/synth.py's, which
has the same files. This tool is the stand-in for everything that runs
before the replay in the game: the level loader (colormaps, fuzz table,
texels in RamWorks) and the bucket pass (records into W by column). It
places each item where docs/MEMORY_MAP.md section 8 says, and writes an
a2vm image (tools/a2vm/README.md, "--image") with the replay and its test
driver (build/native/obj/test.*, src/native/Makefile):

  main       $0200 the driver's batch table; $0400-$07FF and
             $2000-$5FFF the colormaps (level L of A at page CMPA[L], of
             B at CMPB[L]); CMPA, CMPB, TEXLO, TEXHI (the build's table
             ranges only: never $0878-$087F, MEMORY_MAP rule 8);
             $0F00-$13FF the fill spans, $1400-$167F the covered
             ranges (CVREC: the covering record's W address), $1800-$197F
             the weapon skip, each split from upstream's words into one
             byte a column
  card       $D000-$FFFF (bank 2 at $D000): the build's test.lc
  aux 0      $0200-$03FF the fuzz and overlay drawers, $0800-$0BFF their
             tables with the capture's FUZZ_DARKEN, $2000-$9FFF the screen
  aux B..B+3 the texels: each texture record's 128 bytes, copied to a
             bank by the record's original bank (the Nth original bank
             to bank B + N mod 4), a K_TEXC chain in its K_TEX's bank; the
             records' sources are rewritten to the copies
  aux B+4    the records: batches of whole columns of at most 8,192 bytes
             (K_NEXT dropped), each with its column tables (COLLO, COLHI)

The records keep upstream's format (lists.inc); only the texel sources
change, and a K_FUZZ record a later record of its column paints over or
next to becomes the port's K_FUZZNOW (mark_fuzz: the replay draws it in
place instead of queueing it). A record the replay cannot draw safely
(check_record) is refused.
With a fill byte (the harness), every other byte of the machine is set to
it. B is --bank-base (1 for a2vm; the card packs one frame after
another).
"""

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from native import layout as L  # noqa: E402
from ref816 import lists, refimage  # noqa: E402

BUILD = ROOT / 'build'
LINKMAP = BUILD / 'linkmap.json'
OBJ = BUILD / 'native' / 'obj'
WINDOW = lists.TEXEL_SPAN               # 128 bytes a texture record


class LoadError(ValueError):
    pass


# ---------------------------------------------------------------------------
# the capture
# ---------------------------------------------------------------------------

class Capture(NamedTuple):
    directory: Path
    manifest: Dict
    memory: refimage.Memory     # every "before" file at its address
    units: Dict                 # the link map's units


def read_manifest(directory: Path) -> Dict:
    return json.loads((Path(directory) / 'manifest.json').read_text())


def load_units(linkmap: Path = LINKMAP) -> Dict:
    return json.loads(Path(linkmap).read_text())['game']['units']


def read_capture(directory, units: Optional[Dict] = None) -> Capture:
    directory = Path(directory)
    manifest = read_manifest(directory)
    memory = refimage.Memory()
    for f in manifest['files']:
        if f['when'] != 'before' or f['name'] == 'context':
            continue
        data = (directory / f['file']).read_bytes()
        if f['format'] == 'raw':
            memory.put(f['address'], data)
        else:
            refimage.load(refimage.parse(data), memory)
    return Capture(directory, manifest, memory,
                   units if units is not None else load_units())


def file_address(capture: Capture, name: str) -> int:
    for f in capture.manifest['files']:
        if f['name'] == name:
            return f['address']
    raise LoadError('%s: no file %r in the manifest'
                    % (capture.directory, name))


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------

class Rec(NamedTuple):
    column: int
    origin: int                 # its address in upstream's records bank
    kind: int
    data: bytes                 # upstream's bytes (the kind first)
    texels: int                 # K_TEX, K_TEXC: the 24-bit texel address
    chain: int                  # K_TEX, K_TEXC: the K_TEX's origin


def check_record(kind: int, data: bytes) -> Optional[str]:
    """What is wrong with a record the replay cannot draw safely, or None.

    Upstream's producers guarantee these (drawcol.s: "DC_COUNT (number of
    rows, > 0)"; r_sprite65.s fzCol clamps a shadow to rows 1-166; an
    automap pixel is in the view), and the native replay relies on them: a
    texture record without rows would make the gather copy 256 texels below
    its stage place, a shadow of no rows would draw 256, a shadow on row 0
    or 167 would read outside the view."""
    a = data[L.FIELDS['R_ROW']]
    if kind in (L.K_TEX, L.K_TEXC, L.K_FILL):
        e = data[L.FIELDS['R_END']]
        if not a < e <= L.VIEW_ROWS:
            return 'rows %d .. %d (R_ROW < R_END <= %d)' % (a, e,
                                                           L.VIEW_ROWS)
    elif kind == L.K_FUZZ:
        count = data[L.FIELDS['R_COUNT']]
        if count == 0 or a < 1 or a + count > L.VIEW_ROWS - 1:
            return 'a shadow of %d rows from row %d (rows 1-%d, at least ' \
                'one)' % (count, a, L.VIEW_ROWS - 2)
    elif kind == L.K_OVL:
        if a >= L.VIEW_ROWS:
            return 'an automap pixel on row %d' % a
    return None


def columns(capture: Capture) -> List[List[Rec]]:
    """Each column's records in list order, K_NEXT dropped. Raises
    LoadError for a record check_record refuses."""
    lay = lists.layout(capture.units)
    out: List[List[Rec]] = [[] for _ in range(lay.columns)]
    chain = -1
    for r in lists.walk(capture.memory.get, lay):
        kind = r.data[0]
        origin = lay.recbase + (r.page << 8) + r.offset
        if kind == L.K_NEXT:
            continue
        problem = check_record(kind, r.data)
        if problem:
            raise LoadError('column %d: the %s at $%06X: %s' % (
                r.column, L.KIND_NAMES[kind], origin, problem))
        if kind == L.K_TEX:
            chain = origin
        elif kind == L.K_TEXC and (not out[r.column] or chain < 0 or
                                   out[r.column][-1].kind not in
                                   (L.K_TEX, L.K_TEXC)):
            raise LoadError('column %d: a K_TEXC at $%06X does not follow '
                            'its chain' % (r.column, origin))
        out[r.column].append(Rec(r.column, origin, kind, bytes(r.data),
                                 r.texels, chain))
    return out


def rows_of(r: Rec) -> Tuple[int, int]:
    """The rows [first, end) a record paints, before any covered-range
    cut."""
    a = r.data[L.FIELDS['R_ROW']]
    if r.kind == L.K_FUZZ:
        return a, a + r.data[L.FIELDS['R_COUNT']]
    if r.kind == L.K_OVL:
        return a, a + 1
    return a, r.data[L.FIELDS['R_END']]


def mark_fuzz(cols: List[List[Rec]]) -> List[List[Rec]]:
    """The bucket pass's mark for the fuzz queue (layout.py K_FUZZNOW): a
    K_FUZZ record is written into W as K_FUZZNOW, to be drawn in place,
    when a later record of its column paints any row from row - 1 to row +
    count, the rows it reads and writes. The replay draws every other
    K_FUZZ after the strip's columns, in order, so it must not meet a
    later record that changes what it reads or that it would overwrite.
    Later fuzz records count too: the queue may be full when one comes,
    and then it is drawn in place, before the queued ones. (Two fuzz
    records conflict exactly when either's rows touch the other's
    neighbourhood, so each order of an unmarked pair is right.) The Rec's
    kind stays K_FUZZ, upstream's; only its first byte changes."""
    out = []
    for column in cols:
        new = []
        for i, r in enumerate(column):
            if r.kind == L.K_FUZZ:
                a, e = rows_of(r)
                if any(x0 <= e and x1 >= a
                       for x0, x1 in (rows_of(x) for x in column[i + 1:])):
                    r = r._replace(data=bytes([L.K_FUZZNOW]) + r.data[1:])
            new.append(r)
        out.append(new)
    return out


# ---------------------------------------------------------------------------
# the texels
# ---------------------------------------------------------------------------

class Texels(NamedTuple):
    banks: Dict[int, bytearray]         # bank -> its 64 KB
    where: Dict[int, Tuple[int, int]]   # record origin -> (bank, address)
    used: Dict[int, int]                # bank -> bytes placed


def place_texels(capture: Capture, cols: List[List[Rec]],
                 bank_base: int) -> Texels:
    """Each texture record's 128 bytes into banks bank_base + 0..3."""
    chains = [r for c in cols for r in c if r.kind == L.K_TEX]
    originals = sorted(set(r.texels >> 16 for r in chains))
    bank_of_original = {b: bank_base + i % L.TEXEL_BANKS
                        for i, b in enumerate(originals)}
    chain_bank = {r.origin: bank_of_original[r.texels >> 16]
                  for r in chains}
    banks: Dict[int, bytearray] = {}
    free: Dict[int, int] = {}
    copies: Dict[Tuple[int, int], int] = {}
    where: Dict[int, Tuple[int, int]] = {}
    for column in cols:
        for r in column:
            if r.kind not in (L.K_TEX, L.K_TEXC):
                continue
            bank = chain_bank[r.chain]
            key = (bank, r.texels)
            if key not in copies:
                at = free.get(bank, L.BANK_ROOM[0])
                if at + WINDOW > L.BANK_ROOM[1]:
                    raise LoadError('the texels of bank %d do not fit '
                                    '$%04X-$%04X' % ((bank,) + L.BANK_ROOM))
                data = banks.setdefault(bank, bytearray(0x10000))
                data[at:at + WINDOW] = capture.memory.get(r.texels, WINDOW)
                copies[key] = at
                free[bank] = at + WINDOW
            where[r.origin] = (bank, copies[key])
    used = {b: free[b] - L.BANK_ROOM[0] for b in free}
    return Texels(banks, where, used)


def rewrite(r: Rec, texels: Texels) -> bytes:
    data = bytearray(r.data)
    if r.kind in (L.K_TEX, L.K_TEXC):
        bank, address = texels.where[r.origin]
        if r.kind == L.K_TEX:
            at = L.FIELDS['R_SRC']
            data[at:at + 3] = bytes((address & 0xff, address >> 8, bank))
        else:
            at = L.FIELDS['R_TCSRC']
            data[at:at + 2] = bytes((address & 0xff, address >> 8))
    return bytes(data)


# ---------------------------------------------------------------------------
# batches
# ---------------------------------------------------------------------------

class Batch(NamedTuple):
    first: int                  # the first column
    end: int                    # the column after the last
    records: bytes              # W from RECBUF
    col_tables: bytes           # COLLO (161) then COLHI (161)


def make_batches(cols: List[List[Rec]], texels: Texels,
                 batch_bytes: int = L.RECBUF_SIZE
                 ) -> Tuple[List[Batch], Dict[int, int]]:
    """Batches of whole columns; also each record's W address by origin."""
    sizes = [sum(len(r.data) for r in c) for c in cols]
    batches: List[Batch] = []
    w_address: Dict[int, int] = {}
    c = 0
    while c < len(cols):
        first, total = c, 0
        while c < len(cols) and total + sizes[c] <= batch_bytes:
            total += sizes[c]
            c += 1
        if c == first:
            raise LoadError('column %d alone has %d bytes of records, more '
                            'than a batch of %d' % (c, sizes[c],
                                                    batch_bytes))
        data = bytearray()
        starts = [L.RECBUF] * (len(cols) + 1)
        for column in range(first, c):
            starts[column] = L.RECBUF + len(data)
            for r in cols[column]:
                w_address[r.origin] = L.RECBUF + len(data)
                data += rewrite(r, texels)
        starts[c] = L.RECBUF + len(data)
        tables = bytes(s & 0xff for s in starts) + bytes(s >> 8
                                                         for s in starts)
        batches.append(Batch(first, c, bytes(data), tables))
    if len(batches) > L.MAX_BATCHES:
        raise LoadError('%d batches: the driver takes %d'
                        % (len(batches), L.MAX_BATCHES))
    return batches, w_address


# ---------------------------------------------------------------------------
# the stage (a model of the replay's gather, for the report and the checks)
# ---------------------------------------------------------------------------

def stage_need(data: bytes, csf: int, csi: int) -> Tuple[str, int]:
    """How the gather places a texture record's texels in the stage
    (src/native/replay.s gather_texture): ('rows', n), ('span', count)
    or ('all', 128), with its stage bytes. An 'all' whose rows reach at
    most 128 texels is a wrap (texel_copies): it takes 128 bytes of the
    stage but copies fewer."""
    a, e = data[L.FIELDS['R_ROW']], data[L.FIELDS['R_END']]
    tf, ti = data[L.FIELDS['R_TF']], data[L.FIELDS['R_TI']]
    n = e - a
    if csi >= 2:
        return ('rows', n) if n <= 128 else ('all', 128)
    count = n * csi + ((tf + n * csf) >> 8) + 2
    count = (count + 3) & ~3
    if count > 128 or ti + count > 128:
        return ('all', 128)
    return ('span', count)


def texel_copies(data: bytes, csf: int, csi: int) -> List[Tuple[int, int]]:
    """The texel runs the replay copies for a texture record (src/native/
    replay.s gather_texture, run_one), as (first texel, count): one run
    for 'rows' (n texels, one a row, stepped), 'span' and 'all'; two for
    a wrap, a span that passes texel 127 (speed wave 2): the draw's texel
    wraps at 128, so [TI & ~3, 128) and [0, TI + count - 128 rounded up
    to 4), both at the stage place + their first texel. A wrap from
    texel 0-3 copies all 128."""
    mode, count = stage_need(data, csf, csi)
    if mode == 'rows':
        return [(0, count)]
    ti = data[L.FIELDS['R_TI']]
    if mode == 'span':
        return [(ti, count)]
    a, e = data[L.FIELDS['R_ROW']], data[L.FIELDS['R_END']]
    tf, n = data[L.FIELDS['R_TF']], e - a
    reach = (n * csi + ((tf + n * csf) >> 8) + 2 + 3) & ~3
    if csi >= 2 or reach > 128 or ti < 4:
        return [(0, 128)]
    return [(0, (ti + reach - 128 + 3) & ~3), (ti & ~3, 128 - (ti & ~3))]


def stage_plan(batch: Batch) -> Dict[str, int]:
    """Strips and stage bytes of one batch, as the replay makes them: whole
    columns while the texels and a 2-byte pointer each fit the 16 KB. And
    its fuzz records: queued (the first FQMAX K_FUZZ of a strip), drawn in
    place because the queue was full, or marked K_FUZZNOW."""
    room = L.STAGE_END - L.STAGE
    tables = batch.col_tables
    column_needs = []
    modes = {'rows': 0, 'span': 0, 'all': 0, 'wrap': 0, 'copy_bytes': 0}
    fuzz = {'fuzz_queued': 0, 'fuzz_full': 0, 'fuzz_now': 0}
    csf = csi = 0
    for c in range(batch.first, batch.end):
        start = (tables[c] | tables[len(tables) // 2 + c] << 8) - L.RECBUF
        end = (tables[c + 1] | tables[len(tables) // 2 + c + 1] << 8) - \
            L.RECBUF
        need, at, queued = 0, start, 0
        while at < end:
            kind = batch.records[at]
            data = batch.records[at:at + L.SIZES[kind]]
            if kind == L.K_TEX:
                csf, csi = data[L.FIELDS['R_SF']], data[L.FIELDS['R_SI']]
            if kind in (L.K_TEX, L.K_TEXC):
                mode, count = stage_need(data, csf, csi)
                modes[mode] += 1
                runs = texel_copies(data, csf, csi)
                modes['wrap'] += len(runs) == 2
                modes['copy_bytes'] += sum(k for _, k in runs)
                need += count + 2
            queued += kind == L.K_FUZZ
            fuzz['fuzz_now'] += kind == L.K_FUZZNOW
            at += L.SIZES[kind]
        column_needs.append((need, queued))
    strips, used, total, in_queue = 1, 0, 0, 0
    for need, queued in column_needs:
        if need > room:
            raise LoadError('a column needs %d stage bytes, more than the '
                            'stage' % need)
        if used + need > room:
            strips, used, in_queue = strips + 1, 0, 0
        used += need
        total += need
        take = min(queued, L.FQMAX - in_queue)
        in_queue += take
        fuzz['fuzz_queued'] += take
        fuzz['fuzz_full'] += queued - take
    return dict(strips=strips, stage_bytes=total, **modes, **fuzz)


def copy_groups(package: 'Package') -> List[int]:
    """The groups of copy descriptors the replay runs for a frame (src/
    native/replay.s queue, run_descriptors), as the number of texel banks
    each copies from: a group runs when MAXDESC descriptors are queued and
    at each strip's end; a column that does not fit the stage is rolled
    back to its start (what already ran stays run) and starts the next
    strip."""
    room = L.STAGE_END - L.STAGE
    groups: List[int] = []
    for batch in package.batches:
        tables = batch.col_tables
        half = len(tables) // 2
        queue: List[int] = []
        used = 0
        csf = csi = bank = 0
        c = batch.first
        while c < batch.end:
            start = (tables[c] | tables[half + c] << 8) - L.RECBUF
            end = (tables[c + 1] | tables[half + c + 1] << 8) - L.RECBUF
            keep, at, fits = len(queue), start, True
            column_used = used
            while at < end:
                kind = batch.records[at]
                data = batch.records[at:at + L.SIZES[kind]]
                if kind == L.K_TEX:
                    csf, csi = data[L.FIELDS['R_SF']], data[L.FIELDS['R_SI']]
                    bank = data[L.FIELDS['R_SRC'] + 2]
                if kind in (L.K_TEX, L.K_TEXC):
                    need = stage_need(data, csf, csi)[1] + 2
                    if column_used + need > room:
                        fits = False
                        break
                    column_used += need
                    queue.append(bank)
                    if len(queue) == L.MAXDESC:
                        groups.append(len(set(queue)))
                        queue, keep = [], 0
                at += L.SIZES[kind]
            if fits:
                used = column_used
                c += 1
                continue
            queue = queue[:keep]        # the strip ends before column c
            if queue:
                groups.append(len(set(queue)))
            queue, used = [], 0
        if queue:
            groups.append(len(set(queue)))
    return groups


# ---------------------------------------------------------------------------
# the other state
# ---------------------------------------------------------------------------

def split_words(data: bytes, count: int = L.COLUMNS) -> Tuple[bytes, bytes]:
    """Byte 2c and byte 2c + 1 of each column, as two arrays."""
    return (bytes(data[2 * c] for c in range(count)),
            bytes(data[2 * c + 1] for c in range(count)))


class State(NamedTuple):
    spans: bytes                # main FSTOP .. FSSTB, 1,280 bytes
    covered: bytes              # main CVFIRST .. CVRECHI, 640 bytes
    weapon: Tuple[bytes, bytes, bytes]  # WCLIP, WPREV, WTMP
    cuts: int                   # columns with a covered-range cut


def convert_state(capture: Capture, cols: List[List[Rec]],
                  w_address: Dict[int, int]) -> State:
    u = capture.units['r_list65.s']
    lay = lists.layout(capture.units)
    mem = capture.memory
    span = bytearray()
    for name in ('FS_ROW', 'FS_EVEN', 'FS_ODD', 'FS_STAMP'):
        top, bottom = split_words(mem.get(u[name], 2 * L.COLUMNS))
        span += top + bottom
    first, end = split_words(mem.get(u['CV_ROW'], 2 * L.COLUMNS))
    rec_lo, rec_hi, cuts = bytearray(L.COLUMNS), bytearray(L.COLUMNS), 0
    for c in range(L.COLUMNS):
        if end[c] and first[c] < end[c]:
            origin = lay.recbase + mem.word(u['CV_REC'] + 2 * c)
            if origin not in w_address or \
                    not any(r.origin == origin for r in cols[c]):
                raise LoadError('column %d: the covering record $%06X is '
                                'not in its list' % (c, origin))
            rec_lo[c], rec_hi[c] = (w_address[origin] & 0xff,
                                    w_address[origin] >> 8)
            cuts += 1
    covered = bytes(first) + bytes(end) + bytes(rec_lo) + bytes(rec_hi)
    wclip = split_words(mem.get(u['WCLIP'], 2 * L.COLUMNS))[0]
    wprev = mem.get(u['WPREV'], L.WPREV_SIZE)
    wtmp = split_words(mem.get(u['WTMP'], 2 * L.COLUMNS))[0]
    return State(bytes(span), covered, (wclip, wprev, wtmp), cuts)


def screen_stores(cols: List[List[Rec]], state: State,
                  w_address: Dict[int, int]) -> int:
    """The screen stores upstream's R_DrawLists makes for these records: the
    rows of each texture and fill record left after the covered-range cut
    (cutTex, cutFill of r_list65.s: a record before the covering one loses
    the rows it has in the range when it starts or ends in it, all of them
    when it is inside it, none when it spans it), the rows of each shadow,
    one store an automap pixel. The native replay stores each screen byte
    it draws once, so its count of SHR writes must equal this: a cut not
    made, or made one row off, shows here even when a later record paints
    the same pixels."""
    covered = state.covered
    n = 0
    for c, recs in enumerate(cols):
        c0, c1 = covered[c], covered[L.COLUMNS + c]
        on = c1 != 0 and c0 < c1
        cover = covered[2 * L.COLUMNS + c] | covered[3 * L.COLUMNS + c] << 8
        for r in recs:
            if on and w_address[r.origin] == cover:
                on = False
            if r.kind in (L.K_TEX, L.K_TEXC, L.K_FILL):
                a, e = r.data[1], r.data[2]
                if not on or e <= c0 or a >= c1:
                    n += e - a              # clear of the range
                elif a >= c0:
                    n += e - c1 if e > c1 else 0    # starts in it
                else:
                    n += e - a if e > c1 else c0 - a
            elif r.kind == L.K_FUZZ:
                n += r.data[L.FIELDS['R_COUNT']]
            else:
                n += 1
    return n


def colormap_pages(capture: Capture) -> Dict[int, bytes]:
    """Main page -> its 256 bytes, both colormaps, all 34 levels."""
    maps = capture.units['drawcol.s']
    a, b = maps['iigs_shrcmapA'], maps['iigs_shrcmapB']
    pages = {}
    for level in range(L.CMAP_LEVELS):
        pages[L.cmap_page_a(level)] = capture.memory.get(a + 256 * level, 256)
        pages[L.cmap_page_b(level)] = capture.memory.get(b + 256 * level, 256)
    return pages


def fuzz_table(capture: Capture) -> bytes:
    address = capture.units['i_viigs65.s']['FUZZ_DARKEN']
    if not any(f['name'] == 'fuzz' for f in capture.manifest['files']):
        raise LoadError('%s has no fuzz.bin: capture it again with '
                        'tools/ref816/capture.py' % capture.directory)
    return capture.memory.get(address, 256)


def screen_bytes(capture: Capture) -> bytes:
    return capture.memory.get(file_address(capture, 'screen'),
                              L.SCREEN_SIZE)


# ---------------------------------------------------------------------------
# the package
# ---------------------------------------------------------------------------

class Build(NamedTuple):
    lc: bytes                   # $D000-$FFFF
    main_tables: bytes          # $0800-$0BFF
    aux_code: bytes             # aux 0 $0200-
    aux_tables: bytes           # aux 0 $0800-$0BFF
    labels: Dict[str, int]
    lc_segments: Tuple[Tuple[int, int], ...] = ()   # [start, end) in the card


def read_segments(path: Path) -> List[Tuple[str, int, int]]:
    """(name, start, size) of each segment of an ld65 map."""
    out = []
    text = Path(path).read_text()
    part = text.split('Segment list:', 1)[1]
    for line in part.splitlines()[4:]:
        fields = line.split()
        if len(fields) != 5 or len(fields[1]) != 6:
            break
        out.append((fields[0], int(fields[1], 16), int(fields[3], 16)))
    return out


def table_pieces(image: bytes, base: int, ranges) -> List[Tuple[int, bytes]]:
    """(address, bytes) of the table ranges of a table image at base."""
    return [(start, bytes(image[start - base:end - base]))
            for start, end in ranges]


def read_labels(path: Path) -> Dict[str, int]:
    labels = {}
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == 'al':
            labels[parts[2].lstrip('.')] = int(parts[1], 16)
    return labels


def read_build(obj: Path = OBJ, name: str = 'test') -> Build:
    obj = Path(obj)
    paths = [obj / (name + suffix) for suffix in
             ('.lc', '.main0800', '.aux0200', '.aux0800', '.lbl', '.map')]
    for path in paths:
        if not path.exists():
            raise LoadError('%s is missing: run make -C src/native' % path)
    lc_segments = tuple(sorted(
        (start, start + size) for _, start, size in read_segments(paths[5])
        if start >= 0xD000 and size))
    return Build(paths[0].read_bytes(), paths[1].read_bytes(),
                 paths[2].read_bytes(), paths[3].read_bytes(),
                 read_labels(paths[4]), lc_segments)


class Package(NamedTuple):
    name: str
    batches: List[Batch]
    texels: Texels
    state: State
    records_bank: int
    image: bytes                # the a2vm image
    counts: Dict[str, int]


class ImageWriter:
    """A2VMIMG1 records (tools/a2vm/main.c load_image)."""

    MAIN, AUX, LC, LC1 = 0, 1, 2, 3

    def __init__(self):
        self.data = bytearray(b'A2VMIMG1')

    def add(self, kind: int, bank: int, address: int, data: bytes) -> None:
        if not data:
            return
        limit = 0xe000 if kind == self.LC1 else 0x10000
        if address + len(data) > limit:
            raise LoadError('an image record at $%04X runs past its memory'
                            % address)
        self.data += struct.pack('<BBHI', kind, bank, address, len(data))
        self.data += data


def driver_table(batches: List[Batch], records_bank: int,
                 addresses: List[Tuple[int, int]]) -> bytes:
    table = bytearray((len(batches), records_bank))
    for batch, (records_at, tables_at) in zip(batches, addresses):
        table += struct.pack('<BBHHH', batch.first, batch.end,
                             len(batch.records), records_at, tables_at)
    return bytes(table)


def filled_card(build: Build, fill: int) -> bytes:
    """The build's $D000-$FFFF with every byte outside its segments set to
    fill (ld65 fills them with zero)."""
    lc = bytearray([fill]) * len(build.lc)
    if not build.lc_segments:
        raise LoadError('the build has no segment list (its .map)')
    for start, end in build.lc_segments:
        lc[start - 0xD000:end - 0xD000] = build.lc[start - 0xD000:
                                                   end - 0xD000]
    return bytes(lc)


def build_package(capture: Capture, build: Build,
                  screen: Optional[bytes] = None, bank_base: int = 1,
                  batch_bytes: int = L.RECBUF_SIZE,
                  fill: Optional[int] = None,
                  cols: Optional[List[List[Rec]]] = None) -> Package:
    """The a2vm image of a frame. With fill (a byte), every byte of the
    machine the frame and the build do not define is set to it: all of
    main $0000-$BFFF, the card's two parts outside the build's segments,
    every aux bank (tools/native/replay_check.py runs the captured and the
    poisoned screen with different fills, so a stray store of any constant
    changes a byte in one of them). Without, those bytes are left to a2vm
    (zero) and the image stays small (tools/native/disk.py). cols: each
    column's records instead of the capture's lists (tools/native/
    render_replay.py: the native front end's), their texels read from the
    capture's memory at their Rec.texels."""
    cols = mark_fuzz(columns(capture) if cols is None else cols)
    texels = place_texels(capture, cols, bank_base)
    batches, w_address = make_batches(cols, texels, batch_bytes)
    state = convert_state(capture, cols, w_address)
    records_bank = bank_base + L.RECORDS_BANK

    # the records bank: each batch's records, then its column tables
    bank = bytearray(0x10000)
    at = L.BANK_ROOM[0]
    addresses = []
    for batch in batches:
        records_at = at
        bank[at:at + len(batch.records)] = batch.records
        at += len(batch.records)
        tables_at = at
        bank[at:at + len(batch.col_tables)] = batch.col_tables
        at += len(batch.col_tables)
        if at > L.BANK_ROOM[1]:
            raise LoadError('the records do not fit their bank')
        addresses.append((records_at, tables_at))

    if screen is None:
        screen = screen_bytes(capture)
        # Upstream's drawers read the bank $01 buffer (the shadow drawer),
        # the native ones the screen: the frame must have them equal.
        buffer = capture.memory.get(file_address(capture, 'buffer'),
                                    L.PIXELS)
        if buffer != screen[:L.PIXELS]:
            raise LoadError('%s: the drawers\' buffer differs from the '
                            'screen; the native replay has one screen'
                            % capture.directory)
    if len(screen) != L.SCREEN_SIZE:
        raise LoadError('a screen is %d bytes' % L.SCREEN_SIZE)
    aux_tables = bytearray(build.aux_tables)
    aux_tables[L.FUZZDARK - L.AUX_TABLES:L.FUZZDARK - L.AUX_TABLES + 256] = \
        fuzz_table(capture)

    w = ImageWriter()
    if fill is not None:
        pattern = bytes([fill]) * 0x10000
        w.add(w.MAIN, 0, 0, pattern[:0xC000])
        w.add(w.LC1, 0, 0xD000, pattern[:0x1000])
        for number in range(128):
            w.add(w.AUX, number, 0, pattern)
        w.add(w.LC, 0, 0xD000, filled_card(build, fill))
    else:
        w.add(w.LC, 0, 0xD000, build.lc)
    w.add(w.MAIN, 0, L.DRVDATA, driver_table(batches, records_bank,
                                             addresses))
    for address, data in table_pieces(build.main_tables, L.MAIN_TABLES,
                                      L.MAIN_TABLE_RANGES):
        w.add(w.MAIN, 0, address, data)
    for page, data in sorted(colormap_pages(capture).items()):
        w.add(w.MAIN, 0, page << 8, data)
    w.add(w.MAIN, 0, L.FSTOP, state.spans)
    w.add(w.MAIN, 0, L.CVFIRST, state.covered)
    w.add(w.MAIN, 0, L.WCLIP, state.weapon[0])
    w.add(w.MAIN, 0, L.WPREV, state.weapon[1])
    w.add(w.MAIN, 0, L.WTMP, state.weapon[2])
    w.add(w.AUX, 0, L.AUXCODE, build.aux_code)
    for address, data in table_pieces(aux_tables, L.AUX_TABLES,
                                      L.AUX_TABLE_RANGES):
        w.add(w.AUX, 0, address, data)
    w.add(w.AUX, 0, L.SCREEN, screen)
    for number, data in sorted(texels.banks.items()):
        first = L.BANK_ROOM[0]
        w.add(w.AUX, number, first,
              bytes(data[first:first + texels.used[number]]))
    w.add(w.AUX, records_bank, L.BANK_ROOM[0],
          bytes(bank[L.BANK_ROOM[0]:at]))

    counts = {L.KIND_NAMES[k]: 0 for k in L.KIND_NAMES if k != L.K_NEXT}
    for c in cols:
        for r in c:
            counts[L.KIND_NAMES[r.kind]] += 1
    counts['bytes'] = sum(len(b.records) for b in batches)
    counts['batches'] = len(batches)
    counts['cuts'] = state.cuts
    counts['texel_bytes'] = sum(texels.used.values())
    counts['texel_banks'] = len(texels.banks)
    counts['screen_stores'] = screen_stores(cols, state, w_address)
    plans = [stage_plan(b) for b in batches]
    for key in ('strips', 'stage_bytes', 'rows', 'span', 'all', 'wrap',
                'copy_bytes', 'fuzz_queued', 'fuzz_full', 'fuzz_now'):
        counts[key] = sum(plan[key] for plan in plans)
    return Package(capture.directory.name, batches, texels, state,
                   records_bank, bytes(w.data), counts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('capture', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--screen', type=Path,
                        help='32 KB for aux 0 $2000-$9FFF instead of the '
                        'captured screen')
    parser.add_argument('--bank-base', type=int, default=1)
    parser.add_argument('--batch-bytes', type=int, default=L.RECBUF_SIZE)
    parser.add_argument('--build', type=Path, default=OBJ)
    args = parser.parse_args(argv)
    try:
        capture = read_capture(args.capture)
        package = build_package(
            capture, read_build(args.build),
            args.screen.read_bytes() if args.screen else None,
            args.bank_base, args.batch_bytes)
    except (LoadError, lists.DecodeError) as error:
        print('loader: %s' % error, file=sys.stderr)
        return 1
    args.out.write_bytes(package.image)
    print('%s: %s' % (package.name, ', '.join(
        '%s %d' % item for item in package.counts.items())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
