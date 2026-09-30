"""Upstream's layout: a ref816 memory image to the canonical model and back.

    reader = Reader(memory)          # schema.py, from build/
    state = reader.read()            # canonical: globals, objects
    reader.problems                  # what could not be read: [] when sound
    reader.coverage                  # every byte of the game-state regions
    memory = Writer(reader).write(state, base)   # upstream's bytes again

The reader first finds every object (the level tables, the pool, the
thinker list, the zone blocks, the sector nodes), gives each its identity
(schema.KINDS), then decodes every field. A pointer becomes a canonical
reference R(kind, id, field) through an index of the objects and of the
constants pointers name (states, lumps, labelled constants, memmap
tables); one that names nothing is a problem ("raw pointer"), never a
value. Lists become sequences in their head field. Each byte of the
game-state regions (schema.regions) is claimed once: by a field, a list
link, a derived table (TP_BITS, GSTAMP, the flood lists) or a named
exclusion (schema.EXCLUSIONS).

`Placement` is where the objects were: the layout, which the canonical
model leaves out. The writer uses it to put a canonical state back at the
same addresses; a round trip poisons every claimed byte first, so a byte
the writer does not produce shows as a difference.
"""

import bisect
from array import array
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Set, \
    Tuple

from bridge import schema
from bridge.linkmap import Symbols
from bridge.memory import Memory
from bridge.fields import Array, Field, Fn, Int, R, Raw, Ref, Struct, Sub

FORMAT = 'bridge-canonical 1'
REMOVE_THING = 'p_think65.s:P_RemoveThingDelayed'
POISON = 0xa5


class Problem(Exception):
    pass


# ---- the schema, built once per link map ------------------------------------

class Schema:
    def __init__(self, symbols: Optional[Symbols] = None):
        self.symbols = symbols or Symbols()
        self.c = schema.Constants(self.symbols)
        self.structs = schema.build_structs(self.c)
        tc = self.structs['TC']
        slot = Struct('CMDSLOT', 8, [
            Field('cmd', 0, Sub(tc)),
            # ticcmd_t is 5 bytes; a slot of the ring is 8 (g_game65.s
            # cmds: "8 slots of 8 bytes")
            Field('spare', tc.size, Raw(8 - tc.size))])
        cmds_label = self.symbols.label('g_game65.s:cmds')
        count = self.symbols.constant('g_game65.s:CMDS')
        self.structs['CMDS'] = Struct('CMDS', cmds_label.size, [
            Field('slots', 0, Array(Sub(slot), count)),
            Field('pad', 8 * count, Raw(cmds_label.size - 8 * count),
                  'excluded', 'layout pad')])
        self.regions = schema.regions(self.c, self.symbols)
        self.functions: Dict[int, str] = {}
        for ref in schema.THINKER_FUNCTIONS:
            self.functions[self.symbols.address(ref)] = ref
        self.function_address = {v: k for k, v in self.functions.items()}
        self.zone = schema.zone(self.c)
        self.wad_entry = schema.wad_entry(self.c)
        self.state_base = self.symbols.address('info65.s:states')
        self.state_size = self.c['STATE_SIZE']
        self.state_count = self.c['CONST_NUMSTATES']
        # the fixed tables of memmap.inc (its addresses, not its counts)
        self.mm_tables = {name: value for name, value in
                          self.c.memmap.items() if value > 0xffff}


# ---- coverage ---------------------------------------------------------------

class Coverage:
    """An owner for each byte of the game-state regions."""

    def __init__(self, regions: Iterable[schema.Region]):
        self.regions = sorted(regions, key=lambda r: r.start)
        self.starts = [r.start for r in self.regions]
        self.owners: List[str] = ['(none)']
        self.owner_ids: Dict[str, int] = {}
        self.maps = [array('H', bytes(2 * (r.end - r.start)))
                     for r in self.regions]
        self.double: List[str] = []

    def owner(self, name: str) -> int:
        i = self.owner_ids.get(name)
        if i is None:
            i = self.owner_ids[name] = len(self.owners)
            self.owners.append(name)
        return i

    def region_of(self, address: int) -> int:
        i = bisect.bisect_right(self.starts, address) - 1
        if i >= 0 and address < self.regions[i].end:
            return i
        return -1

    def claim(self, address: int, length: int, owner: str,
              what: str = '') -> None:
        o = self.owner(owner)
        end = address + length
        while address < end:
            i = self.region_of(address)
            if i < 0:
                # outside the regions: find the next region start
                j = bisect.bisect_right(self.starts, address)
                if j >= len(self.starts) or self.starts[j] >= end:
                    return
                address = self.starts[j]
                continue
            r = self.regions[i]
            stop = min(end, r.end)
            m = self.maps[i]
            for a in range(address - r.start, stop - r.start):
                if m[a]:
                    if len(self.double) < 20:
                        self.double.append('$%06X: %s and %s %s' % (
                            r.start + a, self.owners[m[a]], owner, what))
                    else:
                        self.double.append('')
                else:
                    m[a] = o
            address = stop

    def claimed(self, address: int) -> str:
        i = self.region_of(address)
        if i < 0:
            return ''
        o = self.maps[i][address - self.regions[i].start]
        return self.owners[o] if o else ''

    def unclaimed(self) -> List[Tuple[int, int, str]]:
        """(start, end, region) of every run of unclaimed bytes."""
        out = []
        for r, m in zip(self.regions, self.maps):
            a = 0
            n = r.end - r.start
            while a < n:
                if m[a]:
                    a += 1
                    continue
                b = a
                while b < n and not m[b]:
                    b += 1
                out.append((r.start + a, r.start + b, r.name))
                a = b
        return out

    def totals(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for m in self.maps:
            for o in m:
                name = self.owners[o]
                counts[name] = counts.get(name, 0) + 1
        return counts

    def spans(self, predicate) -> List[Tuple[int, int]]:
        """(start, end) runs of bytes whose owner passes `predicate`."""
        out = []
        for r, m in zip(self.regions, self.maps):
            a, n = 0, r.end - r.start
            while a < n:
                if not predicate(self.owners[m[a]]):
                    a += 1
                    continue
                b = a
                while b < n and predicate(self.owners[m[b]]):
                    b += 1
                out.append((r.start + a, r.start + b))
                a = b
        return out


def is_field_owner(name: str) -> bool:
    """Owners whose bytes the writer produces (not exclusions)."""
    return not name.startswith('excl:') and name != '(none)'


# ---- placement --------------------------------------------------------------

class Table(NamedTuple):
    kind: str
    base: int
    count: int
    stride: int


class Placement:
    """Where upstream keeps each object: the layout the canonical model
    leaves out."""

    def __init__(self):
        self.tables: Dict[str, Table] = {}
        self.objects: Dict[Tuple[str, Any], int] = {}   # singletons
        self.lumps: Dict[int, Tuple[int, int]] = {}      # lump: (addr, size)
        self.flood: Dict[int, Tuple[int, int, int, int]] = {}
        self.fl_bank = 0

    def address(self, kind: str, ident: Any) -> int:
        t = self.tables.get(kind)
        if t is not None:
            if not 0 <= ident < t.count and not (ident == 0 and
                                                 t.count == 0):
                raise Problem('%s %s is outside its table' % (kind, ident))
            return t.base + ident * t.stride
        a = self.objects.get((kind, ident))
        if a is None:
            raise Problem('no %s %s in the placement' % (kind, ident))
        return a


class Extent(NamedTuple):
    start: int
    end: int
    kind: str
    ident: Any          # for a table: None (the index comes from stride)
    stride: int
    struct: Optional[Struct]


# ---- the reader -------------------------------------------------------------

def mobj_like(kind: str) -> bool:
    return kind in ('mobj', 'zmobj')


class Reader:
    def __init__(self, memory: Memory, sch: Optional[Schema] = None):
        self.m = memory
        self.s = sch or Schema()
        self.sym = self.s.symbols
        self.c = self.s.c
        self.structs = self.s.structs
        self.problems: List[str] = []
        self.raw_pointers: List[str] = []
        self.placement = Placement()
        self.coverage = Coverage(self.s.regions)
        self.extents: List[Extent] = []
        self.objects: Dict[str, Dict[Any, Dict[str, Any]]] = {}
        self.globals: Dict[str, Any] = {}
        self.list_of: Dict[Tuple[str, int], Tuple[str, Any]] = {}
        self.on_list: Dict[str, Set[Tuple[str, Any]]] = {}
        self.stats: Dict[str, Any] = {}
        self.cache_globals: Set[str] = set()
        self.block_used: Dict[int, int] = {}

    # -- small helpers --
    def problem(self, text: str) -> None:
        if len(self.problems) < 200:
            self.problems.append(text)

    def ptr(self, address: int) -> int:
        return self.m.u32(address) & 0xffffff

    def g(self, ref: str) -> int:
        return self.sym.address(ref)

    # -- the whole read --
    def read(self) -> Dict[str, Any]:
        self.locate()
        self.coverage = Coverage(self.s.regions + self.lump_regions())
        self.claim_zone()
        self.index()
        self.decode_globals()
        self.decode_objects()
        self.walk_lists()
        self.dead_links()
        self.derived_tables()
        self.region_exclusions()
        self.check_coverage()
        return {'format': FORMAT, 'globals': self.globals,
                'objects': self.objects}

    # ---- locating the objects ----
    def locate(self) -> None:
        p = self.placement
        g = self.g
        sizes = self.structs
        tables = [
            ('sector', 'p_setup65.s:_g_sectors', 'p_setup65.s:_g_numsectors',
             sizes['SEC'].size),
            ('line', 'p_setup65.s:_g_lines', 'p_setup65.s:_g_numlines',
             sizes['LINE'].size),
            ('side', 'p_setup65.s:_g_sides', 'p_setup65.s:numsides',
             sizes['SIDE'].size),
            ('subsector', 'p_setup65.s:_g_subsectors',
             'p_setup65.s:numsubsectors', sizes['SUB'].size),
            ('node', 'p_setup65.s:nodes', 'p_setup65.s:numnodes',
             sizes['NODE'].size),
            ('mobj', 'p_setup65.s:_g_thingPool',
             'p_setup65.s:_g_thingPoolSize', sizes['MO'].size),
        ]
        for kind, base, count, stride in tables:
            p.tables[kind] = Table(kind, self.ptr(g(base)),
                                   self.m.u16(g(count)), stride)
        # segs: in place; their count from the subsectors (the SEGS lump
        # has no count of its own in memory)
        sub = p.tables['subsector']
        nsegs = 0
        for i in range(sub.count):
            a = sub.base + i * sub.stride
            nsegs = max(nsegs, self.m.u16(a + self.c['OFS_SUB_FIRSTLINE']) +
                        self.m.sint(a + self.c['OFS_SUB_NUMLINES'], 2))
        p.tables['seg'] = Table('seg', self.ptr(g('p_setup65.s:_g_segs')),
                                nsegs, sizes['SEG'].size)
        bw = self.m.u16(g('p_setup65.s:_g_bmapwidth'))
        bh = self.m.u16(g('p_setup65.s:_g_bmapheight'))
        p.tables['blocklink'] = Table(
            'blocklink', self.ptr(g('p_setup65.s:_g_blocklinks')), bw * bh, 4)
        buttons = self.sym.label('p_switch65.s:_g_buttonlist')
        p.tables['button'] = Table('button', buttons.address,
                                   buttons.size // sizes['BTN'].size,
                                   sizes['BTN'].size)
        p.tables['player'] = Table('player', g('g_game65.s:_g_player'), 1,
                                   sizes['PL'].size)
        self.read_wad()
        # the lumps in place: BLOCKMAP and REJECT as byte objects
        for kind, ref in (('blockmap', 'p_setup65.s:_g_blockmaplump'),
                          ('reject', 'p_setup65.s:_g_rejectmatrix')):
            base = self.ptr(g(ref))
            lump = self.lump_at(base, exact=True)
            if lump is None:
                self.problem('%s: no lump starts at $%06X' % (kind, base))
                size = 0
            else:
                size = p.lumps[lump][1]
            p.tables[kind] = Table(kind, base, size, 1)
        self.walk_zone()
        self.find_linebuf()
        self.walk_thinkers()
        self.find_zone_mobjs()
        self.find_secnodes()

    def lump_regions(self) -> List[schema.Region]:
        """The level's lumps that upstream uses in place (SEGS, NODES,
        BLOCKMAP, REJECT): game-state regions of this dump, each the extent
        of its lump in the WAD directory."""
        out = []
        for kind in ('seg', 'node', 'blockmap', 'reject'):
            t = self.placement.tables[kind]
            lump = self.lump_at(t.base, exact=True)
            if lump is None:
                self.problem('the %s table at $%06X is not a resident lump'
                             % (kind, t.base))
                continue
            address, size = self.placement.lumps[lump]
            out.append(schema.Region('lump %s' % kind, address,
                                     address + size,
                                     'the WAD directory (fileinfo), lump %d'
                                     % lump))
        return out

    def read_wad(self) -> None:
        p = self.placement
        fileinfo = self.ptr(self.g('w_wad65.s:fileinfo'))
        count = self.m.u16(self.g('w_wad65.s:numlumps'))
        wad = self.c['MM_WAD']
        self.lump_starts: List[Tuple[int, int, int]] = []
        starts: Dict[int, int] = {}
        fi_pos, fi_size, entry = self.s.wad_entry
        for i in range(count):
            e = fileinfo + entry * i
            pos, size = self.m.u32(e + fi_pos), self.m.u32(e + fi_size)
            address = (wad + pos) & 0xffffff
            p.lumps[i] = (address, size)
            if size:
                starts[address] = starts.get(address, 0) + 1
        # A lump that is not resident has upstream's placeholder filepos,
        # which several lumps share (tools/levelimg.py); only lumps with a
        # start of their own name the bytes they cover.
        for i, (address, size) in p.lumps.items():
            if size and starts[address] == 1:
                self.lump_starts.append((address, address + size, i))
        self.lump_starts.sort()
        self.stats['resident_lumps'] = len(self.lump_starts)
        self.stats['lumps'] = count

    def lump_at(self, address: int, exact: bool = False) -> Optional[int]:
        """The resident lump holding the address (starting there when
        `exact`); None when none or several do."""
        found = [i for a, e, i in self.lump_starts
                 if a <= address < e and (not exact or a == address)]
        return found[0] if len(found) == 1 else None

    # -- the zone --
    def walk_zone(self) -> None:
        z = self.sym.units['z_zone65.s']
        sentinel = self.m.u16(z['SENTINEL'])
        first = self.c['MM_ZONE_FIRST'] << 16
        end = (self.c['MM_ZONE_LAST'] + 1) << 16
        zn = self.s.zone
        blocks = []
        seg = self.m.u16((sentinel << 4) + zn.next)
        prev = sentinel
        seen = set()
        while seg != sentinel and len(blocks) < 20000:
            a = seg << 4
            if a in seen or not first <= a < end:
                self.problem('zone: a block at $%06X is outside the zone '
                             'or seen twice' % a)
                break
            seen.add(a)
            size = self.m.u32(a + zn.size)
            tag = self.m.u16(a + zn.tag)
            user = self.m.u32(a + zn.user)
            if self.m.u16(a + zn.prev) != prev:
                self.problem('zone: block $%06X has a wrong back link' % a)
            blocks.append((a, size, tag, user))
            prev = seg
            seg = self.m.u16(a + zn.next)
        # the blocks tile the zone
        at = first
        for a, size, tag, user in blocks:
            if a != at:
                self.problem('zone: a gap from $%06X to $%06X' % (at, a))
            at = a + size
        if at != end:
            self.problem('zone: the blocks end at $%06X' % at)
        self.blocks = blocks
        self.block_owner: Dict[int, str] = {}     # block address: owner
        self.block_starts = [b[0] for b in blocks]
        self.stats['zone_blocks'] = len(blocks)

    def block_of(self, address: int) -> Optional[Tuple[int, int, int, int]]:
        i = bisect.bisect_right(self.block_starts, address) - 1
        if i >= 0:
            b = self.blocks[i]
            if b[0] <= address < b[0] + b[1]:
                return b
        return None

    def own_block(self, payload: int, length: int, owner: str) -> None:
        """The zone block whose payload starts at `payload` holds an
        object of `length` bytes."""
        b = self.block_of(payload)
        head = self.s.zone.header
        if b is None or b[0] + head != payload:
            self.problem('%s at $%06X is not the start of a zone block'
                         % (owner, payload))
            return
        if b[0] in self.block_owner:
            if self.block_owner[b[0]] != owner:
                self.problem('zone block $%06X is %s and %s' % (
                    b[0], self.block_owner[b[0]], owner))
            return
        if length > b[1] - head:
            self.problem('%s at $%06X: %d bytes in a block of %d' % (
                owner, payload, length, b[1] - head))
        self.block_owner[b[0]] = owner
        self.block_used[b[0]] = length

    def find_linebuf(self) -> None:
        p = self.placement
        secs = p.tables['sector']
        lines_off = self.c['OFS_SEC_LINES']
        count_off = self.c['OFS_SEC_LINECOUNT']
        starts = []
        total = 0
        for i in range(secs.count):
            a = secs.base + i * secs.stride
            starts.append(self.ptr(a + lines_off))
            total += self.m.sint(a + count_off, 2)
        base = min(starts) if starts else 0
        p.tables['linebuf'] = Table('linebuf', base, total, 4)

    # -- the thinker list --
    def walk_thinkers(self) -> None:
        p = self.placement
        cap = self.g('p_think65.s:_g_thinkerclasscap')
        pool = p.tables['mobj']
        pool_end = pool.base + pool.count * pool.stride
        self.thinkers: List[Tuple[int, str, Optional[str]]] = []
        seen = set()
        next_off = self.c['OFS_TH_NEXT']
        fn_off = self.c['OFS_TH_FUNCTION']
        a = self.ptr(cap + next_off)
        while a != cap:
            if a in seen or len(self.thinkers) > 10000 or a == 0:
                self.problem('thinkers: the list does not come back to its '
                             'head')
                break
            seen.add(a)
            fn = self.ptr(a + fn_off)
            name = self.s.functions.get(fn)
            if fn and name is None:
                self.problem('thinker $%06X: function $%06X is not a '
                             'declared thinker function' % (a, fn))
            kind = schema.THINKER_FUNCTIONS.get(name) if name else None
            if kind is None:
                self.problem('thinker $%06X has no function' % a)
                kind = 'removed'
            if kind == 'mobj':
                if pool.base <= a < pool_end and \
                        (a - pool.base) % pool.stride == 0:
                    kind = 'mobj'
                else:
                    kind = 'zmobj'
            self.thinkers.append((a, kind, name))
            a = self.ptr(a + next_off)
        rank: Dict[str, int] = {}
        self.thinker_ids: Dict[int, Tuple[str, Any]] = {}
        for a, kind, _ in self.thinkers:
            if kind == 'mobj':
                ident = (a - pool.base) // pool.stride
            else:
                ident = rank.get(kind, 0)
                rank[kind] = ident + 1
                p.objects[(kind, ident)] = a
                struct = self.structs[schema.KINDS[kind].struct]
                self.own_block(a, struct.size, 'thinker:' + kind)
            self.thinker_ids[a] = (kind, ident)
        self.stats['thinkers'] = len(self.thinkers)

    # -- sector nodes --
    def find_secnodes(self) -> None:
        """Every node reachable from the lists, numbered in the order of
        first reach: the mobjs' lists (pool slots that are not free, then
        zone mobjs), the sectors' lists, _s_sector_list, then the free
        list (identity.py applies the same rule to a canonical state)."""
        p = self.placement
        c = self.c
        order: List[int] = []
        seen: Set[int] = set()

        def walk(head: int, next_off: int) -> None:
            a = self.ptr(head)
            steps = 0
            while a and steps < 100000:
                steps += 1
                if a not in seen:
                    seen.add(a)
                    order.append(a)
                a = self.ptr(a + next_off)

        tnext = c['OFS_SN_M_TNEXT']
        snext = c['OFS_SN_M_SNEXT']
        for a in self.mobj_addresses(live_only=True):
            walk(a + c['OFS_MO_TOUCHING_SECTORLIST'], tnext)
        secs = p.tables['sector']
        for i in range(secs.count):
            walk(secs.base + i * secs.stride + c['OFS_SEC_TOUCHING_THINGLIST'],
                 snext)
        walk(self.g('p_map65.s:_s_sector_list'), tnext)
        walk(self.g('p_map65.s:SN_FREE'), tnext)
        size = self.structs['SN'].size
        pool_count = self.sym.constant('p_map65.s:SN_POOL')
        for i, a in enumerate(order):
            p.objects[('secnode', i)] = a
        # each node sits in a pool block of SN_POOL nodes
        pools: Dict[int, int] = {}
        head = self.s.zone.header
        for a in order:
            b = self.block_of(a)
            if b is None or (a - b[0] - head) % size or \
                    a - b[0] - head >= pool_count * size:
                self.problem('secnode $%06X is not in a node pool' % a)
                continue
            pools[b[0]] = pools.get(b[0], 0) + 1
        for b, n in pools.items():
            self.own_block(b + head, pool_count * size, 'secnode pool')
            if n != pool_count:
                self.problem('the node pool at $%06X has %d nodes on lists, '
                             'not %d' % (b, n, pool_count))
        self.secnodes = order
        self.stats['secnodes'] = len(order)

    def mobj_addresses(self, live_only: bool = False) -> List[int]:
        """Pool slots (all, or those not free), then zone mobjs so far."""
        p = self.placement
        pool = p.tables['mobj']
        out = []
        free = self.free_slots()
        for i in range(pool.count):
            if live_only and i in free:
                continue
            out.append(pool.base + i * pool.stride)
        zone = sorted((ident, a) for (kind, ident), a in p.objects.items()
                      if kind == 'zmobj')
        return out + [a for _, a in zone]

    def free_slots(self) -> Set[int]:
        if not hasattr(self, '_free'):
            pool = self.placement.tables['mobj']
            bits = self.sym.constant('p_spawn65.s:TP_BITS')
            self._free = {i for i in range(pool.count)
                          if self.m.u8(bits + (i >> 3)) >> (i & 7) & 1}
            # TP_BITS: bit i & 15 of word i >> 4, little-endian words: bit
            # i & 7 of byte i >> 3
        return self._free

    # -- zone mobjs with no thinker --
    def find_zone_mobjs(self) -> None:
        """Zone mobjs that are not on the thinker list (a mobj whose state
        never ends has no function, p_spawn65.s P_SpawnMobj). They are the
        PU_LEVEL blocks with no user that no table starts and that look like
        a mobj (a type, a state of states[], MF_POOLED off: a node pool does
        not, its pointers are zone addresses); a block claimed twice is a
        problem (own_block). Their ranks follow the thinker-list zone mobjs,
        in the order of first reach: the sectors' thing lists, then the
        blocks' chains; then any left in address order (none reachable)."""
        p = self.placement
        size = self.structs['MO'].size
        known = {a for (k, _), a in p.objects.items()}
        candidates = []
        zn = self.s.zone
        for a, bsize, tag, user in self.blocks:
            if a in self.block_owner or tag != zn.level or \
                    user != zn.no_user:
                continue
            payload = a + zn.header
            if payload in known:
                continue
            if self.table_block(payload):
                continue
            if bsize - zn.header >= size and self.looks_like_mobj(payload):
                candidates.append(payload)
        if not candidates:
            self.zone_orphans = 0
            return
        cset = set(candidates)
        order: List[int] = []
        c = self.c

        def chain(head: int, next_off: int) -> None:
            a = self.ptr(head)
            steps = 0
            while a and steps < 100000:
                steps += 1
                if a in cset and a not in order:
                    order.append(a)
                a = self.ptr(a + next_off)

        secs = p.tables['sector']
        for i in range(secs.count):
            chain(secs.base + i * secs.stride + c['OFS_SEC_THINGLIST'],
                  c['OFS_MO_SNEXT'])
        blocks = p.tables['blocklink']
        for i in range(blocks.count):
            chain(blocks.base + 4 * i, c['OFS_MO_BNEXT'])
        orphans = [a for a in candidates if a not in order]
        self.zone_orphans = len(orphans)
        rank = sum(1 for (k, _) in p.objects if k == 'zmobj')
        for a in order + orphans:
            p.objects[('zmobj', rank)] = a
            self.own_block(a, size, 'thinker:zmobj')
            rank += 1

    def looks_like_mobj(self, a: int) -> bool:
        c = self.c
        t = self.m.sint(a + c['OFS_MO_TYPE'], 2)
        st = self.ptr(a + c['OFS_MO_STATE'])
        flags_hi = self.m.u16(a + c['OFS_MO_FLAGS'] + 2)
        return (0 <= t < c['CONST_NUMMOBJTYPES'] and
                not flags_hi & c['CONST_MF_POOLED_HI'] and
                self.s.state_base <= st < self.s.state_base +
                self.s.state_count * self.s.state_size)

    def table_block(self, payload: int) -> bool:
        for t in self.placement.tables.values():
            if t.base == payload:
                return True
        return False

    def claim_zone(self) -> None:
        """Owners of the zone blocks that the tables start, and the
        exclusions of the others."""
        p = self.placement
        zone_tables = ('sector', 'line', 'side', 'subsector', 'blocklink',
                       'mobj', 'linebuf')
        for kind in zone_tables:
            t = p.tables[kind]
            if t.count:
                self.own_block(t.base, t.count * t.stride, 'table:' + kind)
        cov = self.coverage
        used = self.block_used
        zn = self.s.zone
        h = zn.header
        for a, size, tag, user in self.blocks:
            cov.claim(a, h, 'excl:zone header')
            owner = self.block_owner.get(a)
            if owner == 'thinker:removed':
                n = used.get(a, 0)
                cov.claim(a + h + n, size - h - n, 'excl:removed thinker')
                continue
            if owner is not None:
                n = used.get(a, 0)
                if size - h > n and self.ends_with_byte(owner):
                    cov.claim(a + h + n, 1, 'excl:overread')
                    n += 1
                if size - h > n:
                    cov.claim(a + h + n, size - h - n, 'excl:zone slack')
                continue
            if user == 0:
                why = 'zone free'
            elif tag == zn.static:
                why = 'zone static'
            elif tag == zn.cache:
                why = 'zone cache'
            elif tag == zn.level and user != zn.no_user:
                why = 'zone textures'
            else:
                self.problem('zone block $%06X (%d bytes, tag %d, user '
                             '$%06X) has no owner' % (a, size, tag, user))
                continue
            cov.claim(a + h, size - h, 'excl:' + why)

    def ends_with_byte(self, owner: str) -> bool:
        """The object of a block owner ends with a 1-byte field."""
        if not owner.startswith('thinker:'):
            return False
        struct = schema.KINDS[owner[8:]].struct
        last = self.structs[struct].fields[-1]
        return last.type.length == 1 and last.cls != 'thinker'

    # ---- the index of pointer targets ----
    def index(self) -> None:
        p = self.placement
        ext = []
        struct_of = {k: (self.structs[v.struct] if v.struct else None)
                     for k, v in schema.KINDS.items()}
        for kind, t in p.tables.items():
            if t.count:
                ext.append(Extent(t.base, t.base + t.count * t.stride, kind,
                                  None, t.stride, struct_of[kind]))
        for (kind, ident), a in p.objects.items():
            st = struct_of[kind]
            ext.append(Extent(a, a + st.size, kind, ident, 0, st))
        ext.sort()
        for x, y in zip(ext, ext[1:]):
            if x.end > y.start:
                self.problem('%s and %s overlap at $%06X' % (
                    x.kind, y.kind, y.start))
        self.extents = ext
        self.extent_starts = [e.start for e in ext]
        self.table_by_address: Dict[int, str] = {}
        for name, value in self.s.mm_tables.items():
            self.table_by_address.setdefault(value, name)

    def classify(self, address: int, targets: Tuple[str, ...]
                 ) -> Tuple[Optional[R], str]:
        """(reference, '') or (None, why not)."""
        if address == 0:
            return None, ''
        i = bisect.bisect_right(self.extent_starts, address) - 1
        if i >= 0:
            e = self.extents[i]
            if e.start <= address < e.end:
                if e.ident is None:
                    ident, off = divmod(address - e.start, e.stride)
                else:
                    ident, off = e.ident, address - e.start
                if e.kind in schema.BYTE_KINDS:
                    return self.check(R(e.kind, 0, address - e.start),
                                      targets)
                if off == 0:
                    return self.check(R(e.kind, ident, None), targets)
                if e.struct is None:
                    return None, 'inside %s %d' % (e.kind, ident)
                f = e.struct.field_at(off)
                if f is None or f.offset != off:
                    return None, 'inside a field of %s %d' % (e.kind, ident)
                return self.check(R(e.kind, ident, f.name), targets)
        sb = self.s.state_base
        if sb <= address < sb + self.s.state_count * self.s.state_size:
            n, off = divmod(address - sb, self.s.state_size)
            if off:
                return None, 'inside state %d' % n
            return self.check(R('state', n, None), targets)
        if address in self.table_by_address:
            return self.check(R('table', self.table_by_address[address], 0),
                              targets)
        # (the vendor runtime has no rodata; it stays out all the same)
        labels = [lb for lb in self.sym.exact(address)
                  if lb.kind == 'rodata' and lb.unit != 'cal_integer.s']
        if labels:
            return self.check(R('symbol', labels[0].ref, 0), targets)
        lump = self.lump_at(address)
        if lump is not None:
            return self.check(R('lump', lump,
                                address - self.placement.lumps[lump][0]),
                              targets)
        return None, 'names no object'

    @staticmethod
    def check(ref: R, targets: Tuple[str, ...]) -> Tuple[Optional[R], str]:
        if ref.kind not in targets:
            return None, 'a %s, not %s' % (ref.kind, '|'.join(targets)
                                           or 'NULL')
        return ref, ''

    def ref_address(self, ref: R) -> int:
        """The address of a reference, from the placement."""
        p = self.placement
        if ref.kind == 'state':
            return self.s.state_base + ref.id * self.s.state_size
        if ref.kind == 'table':
            return self.s.mm_tables[ref.id] + ref.field
        if ref.kind == 'symbol':
            return self.sym.address(ref.id) + ref.field
        if ref.kind == 'lump':
            return p.lumps[ref.id][0] + ref.field
        base = p.address(ref.kind, ref.id)
        if ref.field is None:
            return base
        if ref.kind in schema.BYTE_KINDS:
            return base + ref.field
        struct = self.structs[schema.KINDS[ref.kind].struct]
        return base + struct.by_name[ref.field].offset

    # ---- decoding fields ----
    def decode_value(self, t: Any, address: int, where: str) -> Any:
        if isinstance(t, Int):
            return self.m.sint(address, t.size) if t.signed else \
                self.m.uint(address, t.size)
        if isinstance(t, Ref):
            value = self.m.u32(address)
            if value >> 24:
                self.problem('%s: pad byte $%02X' % (where, value >> 24))
            ref, why = self.classify(value & 0xffffff, t.targets)
            if why:
                self.raw_pointers.append('%s = $%06X: %s' % (
                    where, value & 0xffffff, why))
            return ref
        if isinstance(t, Fn):
            a = self.m.uint(address, 3)
            if a == 0:
                return None
            name = self.s.functions.get(a)
            if name is None:
                self.problem('%s: $%06X is not a declared thinker '
                             'function' % (where, a))
            return name
        if isinstance(t, Raw):
            return self.m.read(address, t.size).hex()
        if isinstance(t, Array):
            n = t.elem.length
            return [self.decode_value(t.elem, address + i * n,
                                      '%s[%d]' % (where, i))
                    for i in range(t.count)]
        if isinstance(t, Sub):
            return self.decode_struct(t.struct, address, where, '')
        raise TypeError(t)

    def decode_struct(self, st: Struct, address: int, where: str,
                      owner: str, kind: str = '') -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in st.fields:
            fa = address + f.offset
            name = '%s.%s' % (where, f.name)
            if f.cls == 'list':
                continue            # the lists claim and decode these
            if f.cls == 'excluded':
                self.coverage.claim(fa, f.type.length, 'excl:' + f.why, name)
                continue
            if f.cls == 'thinker':
                self.decode_thinker(f.type.struct, fa, name, owner, kind,
                                    out)
                continue
            if owner:
                self.coverage.claim(fa, f.type.length, owner, name)
            out[f.name] = self.decode_value(f.type, fa, name)
        return out

    def decode_thinker(self, th: Struct, address: int, where: str,
                       owner: str, kind: str, out: Dict[str, Any]) -> None:
        fn = th.by_name['function']
        cache = th.by_name['kindcache']
        self.coverage.claim(address + fn.offset, 3, owner, where)
        out['function'] = self.decode_value(fn.type, address + fn.offset,
                                            where + '.function')
        if kind in ('mobj', 'zmobj'):
            self.coverage.claim(address + cache.offset, 1, 'excl:kindcache',
                                where)
        else:
            self.coverage.claim(address + cache.offset, 1, owner, where)
            if self.m.u8(address + cache.offset):
                self.problem('%s: byte 11 of a special is $%02X, not 0'
                             % (where, self.m.u8(address + cache.offset)))

    def decode_objects(self) -> None:
        p = self.placement
        c = self.c
        objs = self.objects
        struct_kinds = [k for k, v in schema.KINDS.items() if v.struct]
        free = self.free_slots()
        for kind in struct_kinds:
            st = self.structs[schema.KINDS[kind].struct]
            if kind == 'removed':
                continue
            t = p.tables.get(kind)
            if t is not None:
                items = [(i, t.base + i * t.stride) for i in range(t.count)]
            else:
                items = sorted((ident, a) for (k, ident), a in
                               p.objects.items() if k == kind)
            if not items:
                continue
            table = objs.setdefault(kind, {})
            for ident, a in items:
                where = '%s[%s]' % (kind, ident)
                if kind == 'secnode' and self.is_free_node(a):
                    table[ident] = self.decode_free_node(st, a, where)
                    continue
                o = self.decode_struct(st, a, where, 'field:' + kind, kind)
                if kind == 'mobj':
                    o['free'] = int(ident in free)
                elif kind == 'secnode':
                    o['free'] = 0
                table[ident] = o
        # removed specials: the header only
        th = self.structs['TH']
        for (kind, ident), a in p.objects.items():
            if kind != 'removed':
                continue
            o = {}
            self.decode_thinker(th, a, 'removed[%d]' % ident,
                                'field:removed', 'removed', o)
            objs.setdefault('removed', {})[ident] = o
        # the line tables, the block chains' heads: pointer arrays
        lb = p.tables['linebuf']
        objs['linebuf'] = {}
        for i in range(lb.count):
            a = lb.base + 4 * i
            self.coverage.claim(a, 4, 'field:linebuf')
            objs['linebuf'][i] = {'line': self.decode_value(
                Ref(('line',)), a, 'linebuf[%d]' % i)}
        # the lumps in place, as bytes
        for kind in ('blockmap', 'reject'):
            t = p.tables[kind]
            self.coverage.claim(t.base, t.count, 'field:' + kind)
            objs[kind] = {0: {'bytes': self.m.read(t.base, t.count).hex(),
                              'lump': self.lump_at(t.base, exact=True)}}
        self.stats['objects'] = {k: len(v) for k, v in objs.items()}

    def is_free_node(self, a: int) -> bool:
        if not hasattr(self, '_free_nodes'):
            nodes = set()
            n = self.ptr(self.g('p_map65.s:SN_FREE'))
            while n and n not in nodes:
                nodes.add(n)
                n = self.ptr(n + self.c['OFS_SN_M_TNEXT'])
            self._free_nodes = nodes
        return a in self._free_nodes

    def decode_free_node(self, st: Struct, a: int, where: str
                         ) -> Dict[str, Any]:
        for f in st.fields:
            if f.name == 'm_tnext':
                continue            # the free list claims it
            self.coverage.claim(a + f.offset, f.type.length,
                                'excl:dead secnode', where)
        return {'free': 1}

    # ---- globals ----
    def decode_globals(self) -> None:
        for f in self.sym.data_fragments():
            if not schema.is_game_unit(f.unit):
                continue
            if f.labels and f.labels[0].address > f.address:
                self.coverage.claim(f.address, f.labels[0].address -
                                    f.address, 'excl:layout pad')
            wanted = schema.GLOBALS.get(f.unit, {})
            excluded = schema.UNIT_EXCLUSIONS.get(f.unit, {})
            for label in f.labels:
                name = label.ref
                text = wanted.get(label.name)
                if text is None:
                    why = next((k for k, v in excluded.items()
                                if label.name in v), 'scratch')
                    self.coverage.claim(label.address, label.size,
                                        'excl:' + why, name)
                    continue
                self.decode_global(label, text)
        self.decode_external()

    def decode_external(self) -> None:
        for unit, labels in schema.EXTERNAL_GLOBALS.items():
            for name, text in labels.items():
                self.decode_global(self.sym.label('%s:%s' % (unit, name)),
                                   text)

    def decode_global(self, label, text: str) -> None:
        name = label.ref
        cls = 'state'
        if text.startswith('cache:'):
            cls, text = 'cache', text[6:]
        if text.startswith('object:') or text.startswith('list:'):
            return                  # decoded with the objects or lists
        if text.startswith('table:'):
            kind = text[6:]
            self.coverage.claim(label.address, 4, 'field:global', name)
            value = self.m.u32(label.address)
            t = self.placement.tables[kind]
            if value >> 24 or (value & 0xffffff) != t.base:
                self.problem('%s: $%08X is not the base of %s' % (
                    name, value, kind))
            self.globals[name] = R(kind, 0, None)
            self.check_size(label, 4)
            return
        if text in self.structs:
            t = Sub(self.structs[text])
        else:
            t = schema.field_type(text, self.structs)
        self.check_size(label, t.length)
        if isinstance(t, Sub):
            self.globals[name] = self.decode_struct(
                t.struct, label.address, name, 'field:global')
        else:
            self.coverage.claim(label.address, t.length, 'field:global',
                                name)
            self.globals[name] = self.decode_value(t, label.address, name)
        if cls == 'cache':
            self.cache_globals.add(name)

    def check_size(self, label, size: int) -> None:
        if label.size != size:
            self.problem('%s: %d bytes in the link map, %d in the schema'
                         % (label.ref, label.size, size))

    # ---- lists ----
    def walk_lists(self) -> None:
        p = self.placement
        c = self.c
        g = self.g
        objs = self.objects
        self.list_claims: Set[Tuple[int, str]] = set()
        # the thinker list: a ring through its head
        cap = g('p_think65.s:_g_thinkerclasscap')
        th_prev, th_fn = c['OFS_TH_PREV'], c['OFS_TH_FUNCTION']
        links = th_fn           # prev and next: the bytes before function
        seq = []
        self.coverage.claim(cap, links, 'list:thinkers', 'thinker cap links')
        prev = cap
        for a, kind, _ in self.thinkers:
            ident = self.thinker_ids[a]
            if self.ptr(a + th_prev) != prev:
                self.problem('thinker $%06X: prev $%06X, expected $%06X'
                             % (a, self.ptr(a + th_prev), prev))
            self.coverage.claim(a, links, 'list:thinkers', 'thinker links')
            self.on_list.setdefault('thinkers', set()).add(ident)
            seq.append(R(ident[0], ident[1], None))
            prev = a
        if self.ptr(cap + th_prev) != prev:
            self.problem('the thinker cap\'s prev is not the last thinker')
        # the cap's function: 0 (P_InitThinkers leaves it)
        fn_size = c['SIZEOF_TH'] - th_fn
        self.coverage.claim(cap + th_fn, fn_size, 'field:global',
                            'thinker cap')
        if self.m.uint(cap + th_fn, fn_size):
            self.problem('the thinker cap\'s function is not 0')
        self.globals['p_think65.s:_g_thinkerclasscap'] = seq
        # sector things, sector nodes
        secs = p.tables['sector']
        for i in range(secs.count):
            a = secs.base + i * secs.stride
            o = objs['sector'][i]
            o['thinglist'] = self.walk(
                'sector_things', a + c['OFS_SEC_THINGLIST'], 'sector[%d]' % i,
                ('mobj', 'zmobj'), c['OFS_MO_SNEXT'], c['OFS_MO_SPREV'],
                'cell', 'snext', 'sprev')
            o['touching_thinglist'] = self.walk(
                'sector_nodes', a + c['OFS_SEC_TOUCHING_THINGLIST'],
                'sector[%d]' % i, ('secnode',), c['OFS_SN_M_SNEXT'],
                c['OFS_SN_M_SPREV'], 'node', 'm_snext', 'm_sprev')
        blocks = p.tables['blocklink']
        objs['blocklink'] = {}
        for i in range(blocks.count):
            objs['blocklink'][i] = {'things': self.walk(
                'block_things', blocks.base + 4 * i, 'blocklink[%d]' % i,
                ('mobj', 'zmobj'), c['OFS_MO_BNEXT'], c['OFS_MO_BPREV'],
                'cell', 'bnext', 'bprev')}
        free = self.free_slots()
        for kind in ('mobj', 'zmobj'):
            for ident, o in objs.get(kind, {}).items():
                if kind == 'mobj' and ident in free:
                    continue
                a = p.address(kind, ident)
                o['touching_sectorlist'] = self.walk(
                    'thing_nodes', a + c['OFS_MO_TOUCHING_SECTORLIST'],
                    '%s[%s]' % (kind, ident), ('secnode',),
                    c['OFS_SN_M_TNEXT'], c['OFS_SN_M_TPREV'], 'node',
                    'm_tnext', 'm_tprev')
        self.globals['p_map65.s:_s_sector_list'] = self.walk(
            'sector_list', g('p_map65.s:_s_sector_list'), '_s_sector_list',
            ('secnode',), c['OFS_SN_M_TNEXT'], c['OFS_SN_M_TPREV'], 'node',
            'm_tnext', 'm_tprev')
        self.globals['p_map65.s:SN_FREE'] = self.walk(
            'sn_free', g('p_map65.s:SN_FREE'), 'SN_FREE', ('secnode',),
            c['OFS_SN_M_TNEXT'], None, '', 'm_tnext', None)

    def walk(self, name: str, head: int, where: str, kinds: Tuple[str, ...],
             next_off: int, prev_off: Optional[int], style: str,
             next_name: str, prev_name: Optional[str]) -> List[R]:
        self.coverage.claim(head, 4, 'list:' + name, where + ' head')
        if self.m.u8(head + 3):
            self.problem('%s: pad byte of the list head' % where)
        seq: List[R] = []
        prev = head if style == 'cell' else 0
        a = self.ptr(head)
        seen = set()
        while a:
            if a in seen or len(seq) > 100000:
                self.problem('%s: the list %s loops' % (where, name))
                break
            seen.add(a)
            ref, why = self.classify(a, kinds)
            if ref is None or ref.field is not None:
                self.problem('%s: the list %s reaches $%06X (%s)'
                             % (where, name, a, why or 'inside an object'))
                break
            key = (ref.kind, ref.id)
            if (a, name) in self.list_claims:
                self.problem('%s: %s %s is on two %s lists' % (
                    where, ref.kind, ref.id, name))
                break
            self.list_claims.add((a, name))
            owner = self.list_of.get((a, next_name))
            if owner is not None:
                self.problem('%s %s is on the lists of %s and %s' % (
                    ref.kind, ref.id, owner, where))
            self.list_of[(a, next_name)] = (name, where)
            self.on_list.setdefault(name, set()).add(key)
            self.coverage.claim(a + next_off, 4, 'list:' + name, where)
            if self.m.u8(a + next_off + 3):
                self.problem('%s: pad byte of a %s link' % (where, name))
            if prev_off is not None:
                self.coverage.claim(a + prev_off, 4, 'list:' + name, where)
                got = self.m.u32(a + prev_off)
                if got != prev:
                    self.problem('%s: %s %s has %s $%06X, expected $%06X'
                                 % (where, ref.kind, ref.id, prev_name, got,
                                    prev))
            seq.append(ref)
            prev = a + next_off if style == 'cell' else a
            a = self.ptr(a + next_off)
        return seq

    def dead_links(self) -> None:
        """Link fields that no list claimed: dead only where the schema
        says the object is off that list."""
        p = self.placement
        c = self.c
        free = self.free_slots()
        nosector = c['CONST_MF_NOSECTOR']
        noblock = c['CONST_MF_NOBLOCKMAP']
        for kind in ('mobj', 'zmobj'):
            for ident, o in self.objects.get(kind, {}).items():
                a = p.address(kind, ident)
                # a mobj waiting for its removal (P_RemoveMobj: out of the
                # blocks and sectors, its nodes deleted) is off its lists
                is_free = (kind == 'mobj' and ident in free) or \
                    o['function'] == REMOVE_THING
                on_thinkers = (kind, ident) in self.on_list.get('thinkers',
                                                                set())
                flags = o['flags']
                checks = [
                    (c['OFS_TH_PREV'], c['OFS_TH_FUNCTION'], 'thinker',
                     not on_thinkers and
                     (is_free or o['function'] is None)),
                    (c['OFS_MO_SNEXT'], 4, 'snext', is_free or
                     flags & nosector),
                    (c['OFS_MO_SPREV'], 4, 'sprev', is_free or
                     flags & nosector),
                    (c['OFS_MO_BNEXT'], 4, 'bnext', is_free or
                     flags & noblock),
                    (c['OFS_MO_BPREV'], 4, 'bprev', is_free or
                     flags & noblock),
                    (c['OFS_MO_TOUCHING_SECTORLIST'], 4, 'touching',
                     is_free)]
                for off, n, what, dead in checks:
                    if self.coverage.claimed(a + off):
                        continue
                    if dead:
                        self.coverage.claim(a + off, n, 'excl:dead link',
                                            '%s[%s].%s' % (kind, ident,
                                                           what))
                    else:
                        self.problem('%s %s: its %s link is on no list' % (
                            kind, ident, what))
        for ident, a in enumerate(self.secnodes):
            if self.is_free_node(a):
                continue
            for off, what in ((c['OFS_SN_M_TNEXT'], 'm_tnext'),
                              (c['OFS_SN_M_TPREV'], 'm_tprev'),
                              (c['OFS_SN_M_SNEXT'], 'm_snext'),
                              (c['OFS_SN_M_SPREV'], 'm_sprev')):
                if not self.coverage.claimed(a + off):
                    self.problem('secnode %d: its %s link is on no list'
                                 % (ident, what))

    # ---- tables derived from the objects ----
    def derived_tables(self) -> None:
        p = self.placement
        c = self.c
        cov = self.coverage
        # TP_BITS and TP_MASK (p_spawn65.s)
        bits = self.sym.constant('p_spawn65.s:TP_BITS')
        mask = self.sym.constant('p_spawn65.s:TP_MASK')
        tp_max = self.sym.constant('p_spawn65.s:TP_MAX')
        pool = p.tables['mobj']
        used = (pool.count + 15) // 16 * 2
        cov.claim(bits, used, 'derived:TP_BITS')
        for i in range(pool.count, used * 8):
            if self.m.u8(bits + (i >> 3)) >> (i & 7) & 1:
                self.problem('TP_BITS: bit %d past the pool is set' % i)
        cov.claim(bits + used, tp_max // 8 - used, 'excl:tp unused')
        cov.claim(mask, 32, 'derived:TP_MASK')
        for k in range(16):
            if self.m.u16(mask + 2 * k) != 1 << k:
                self.problem('TP_MASK[%d] is not 1 << %d' % (k, k))
        # GSTAMP: a word a line (p_path65.s)
        gstamp = c['MM_GSTAMP']
        lines = p.tables['line']
        for i in range(lines.count):
            self.objects['line'][i]['gstamp'] = self.m.u16(gstamp + 2 * i)
        cov.claim(gstamp, 2 * lines.count, 'field:line')
        cov.claim(gstamp + 2 * lines.count,
                  c['MM_VIEWSAVE'] - gstamp - 2 * lines.count, 'excl:no line')
        self.read_flood()

    def read_flood(self) -> None:
        """P_InitFlood's lists (p_pspr65.s): at FL_IDX + s, for the sector
        at offset s of its bank: first, end of the entries without
        ML_SOUNDBLOCK, first with it, end; an entry of FL_ENT is the other
        sector's offset."""
        p = self.placement
        c = self.c
        cov = self.coverage
        idx = c['MM_FL_IDX']
        ent = c['MM_FL_ENT']
        secs = p.tables['sector']
        bank = secs.base & 0xff0000
        p.fl_bank = bank
        used_entries: List[Tuple[int, int]] = []
        for i in range(secs.count):
            s = (secs.base + i * secs.stride) & 0xffff
            at = (idx & 0xff0000) | ((idx + s) & 0xffff)
            words = [self.m.u16(at + 2 * k) for k in range(4)]
            cov.claim(at, 8, 'derived:flood index', 'sector[%d]' % i)
            first, end_a, first_b, end = words
            p.flood[i] = tuple(words)
            if not first <= end_a <= first_b <= end:
                self.problem('sector %d: flood index %s out of order'
                             % (i, words))
                continue
            o = self.objects['sector'][i]
            o['flood'] = self.flood_part(ent, first, end_a, bank, i)
            o['flood_sb'] = self.flood_part(ent, first_b, end, bank, i)
            used_entries += [(first, end_a), (first_b, end)]
        for a, b in used_entries:
            cov.claim(ent + a, b - a, 'derived:flood entries')
        for start, stop, region in self.coverage.unclaimed():
            if region in ('flood entries', 'flood index'):
                cov.claim(start, stop - start, 'excl:' + (
                    'flood room' if region == 'flood entries'
                    else 'no sector'))

    def flood_part(self, ent: int, a: int, b: int, bank: int,
                   sector: int) -> List[R]:
        out = []
        for off in range(a, b, 2):
            value = self.m.u16(ent + off)
            ref, why = self.classify(bank | value, ('sector',))
            if ref is None or ref.field is not None:
                self.raw_pointers.append('sector[%d].flood = $%04X: %s'
                                         % (sector, value, why))
                continue
            out.append(ref)
        return out

    # ---- region exclusions and the check ----
    def region_exclusions(self) -> None:
        cov = self.coverage
        for start, end in schema.bank21_scratch(self.c):
            cov.claim(start, end - start, 'excl:trace scratch')
        for start, end, region in cov.unclaimed():
            if region in ('sight hints', 'guard counts', 'level tables',
                          'respawn copy'):
                cov.claim(start, end - start, 'excl:' + region)

    def check_coverage(self) -> None:
        cov = self.coverage
        for start, end, region in cov.unclaimed():
            what = self.sym.fragment_at(start)
            self.problem('%d bytes of %s at $%06X are neither a field nor '
                         'an exclusion%s' % (
                             end - start, region, start,
                             ' (%s)' % what.unit if what else ''))
        if cov.double:
            self.problem('%d bytes claimed twice: %s' % (
                len(cov.double), '; '.join(d for d in cov.double[:5] if d)))


# ---- the writer -------------------------------------------------------------

class Writer:
    """A canonical state into upstream's layout, at the placement of a
    reader, over a base memory (which keeps the excluded bytes)."""

    def __init__(self, reader: Reader):
        self.r = reader
        self.s = reader.s
        self.p = reader.placement
        self.c = reader.c

    def write(self, state: Dict[str, Any], base: Memory,
              poison: bool = True) -> Memory:
        """Raises Problem, before writing anything, for a state the
        placement cannot hold (`check`)."""
        self.check(state)
        m = base.copy()
        if poison:
            for start, end in self.r.coverage.spans(is_field_owner):
                m.write(start, bytes([POISON]) * (end - start))
        self.m = m
        self.write_globals(state['globals'])
        self.write_objects(state['objects'])
        self.write_lists(state)
        self.write_derived(state['objects'])
        return m

    # -- what the placement can hold --
    # Per kind, the entries of an object besides its structure's fields
    # (the reader's lists and derived tables); a free mobj has no node list.
    EXTRA = {'mobj': ('free', 'touching_sectorlist'),
             'zmobj': ('touching_sectorlist',),
             'secnode': ('free',),
             'sector': ('thinglist', 'touching_thinglist', 'flood',
                        'flood_sb'),
             'line': ('gstamp',)}
    LIST_GLOBALS = ('p_think65.s:_g_thinkerclasscap',
                    'p_map65.s:_s_sector_list', 'p_map65.s:SN_FREE')

    def object_keys(self, kind: str, o: Dict[str, Any]) -> Set[str]:
        """The entries an object of `kind` has in a canonical state: the
        ones the reader produces."""
        fixed = {'linebuf': {'line'}, 'blockmap': {'bytes', 'lump'},
                 'reject': {'bytes', 'lump'}, 'blocklink': {'things'},
                 'removed': {'function'}}
        if kind in fixed:
            return fixed[kind]
        if kind == 'secnode' and o.get('free'):
            return {'free'}
        keys = self.struct_keys(self.r.structs[schema.KINDS[kind].struct])
        keys.update(self.EXTRA.get(kind, ()))
        if kind == 'mobj' and o.get('free'):
            keys.discard('touching_sectorlist')
        return keys

    @staticmethod
    def struct_keys(st: Struct) -> Set[str]:
        return {'function' if f.cls == 'thinker' else f.name
                for f in st.fields if f.cls not in ('list', 'excluded')}

    def check(self, state: Dict[str, Any]) -> None:
        """Every global and every object of the placement, no other, each
        with every field of the schema and no other, each value of its
        type. The writer keeps the base's placement (its zone blocks,
        its flood rooms), so an object the base lacks or has more of
        cannot be written."""
        bad: List[str] = []
        if not isinstance(state, dict) or not isinstance(
                state.get('globals'), dict) or not isinstance(
                state.get('objects'), dict):
            raise Problem('not a canonical state: no globals or objects')
        self.check_keys('globals', set(state['globals']),
                        set(self.r.globals), bad)
        for name, value in state['globals'].items():
            if name in self.r.globals:
                self.check_global(name, value, bad)
        objs = state['objects']
        self.check_keys('object kinds', set(objs), set(self.r.objects), bad)
        for kind, table in objs.items():
            base = self.r.objects.get(kind)
            if base is None:
                continue
            if not isinstance(table, dict):
                bad.append('%s: not a table of objects' % kind)
                continue
            self.check_keys('%s objects' % kind, set(table), set(base), bad)
            for ident, o in table.items():
                if ident not in base:
                    continue
                where = '%s[%s]' % (kind, ident)
                if not isinstance(o, dict):
                    bad.append('%s: not an object' % where)
                    continue
                self.check_keys(where, set(o), self.object_keys(kind, o),
                                bad)
                self.check_object(kind, o, base[ident], where, bad)
        if bad:
            raise Problem('the state cannot be written at this placement: '
                          '%s%s' % ('; '.join(bad[:8]), '; and %d more' % (
                              len(bad) - 8) if len(bad) > 8 else ''))

    @staticmethod
    def check_keys(where: str, got: Set, want: Set, bad: List[str]) -> None:
        missing = sorted(want - got, key=str)
        extra = sorted(got - want, key=str)
        if missing:
            bad.append('%s: missing %s' % (where, ', '.join(
                map(str, missing[:6])) + (' ...' if len(missing) > 6
                                          else '')))
        if extra:
            bad.append('%s: not in the placement or the schema: %s' % (
                where, ', '.join(map(str, extra[:6])) + (
                    ' ...' if len(extra) > 6 else '')))

    def check_global(self, name: str, value: Any, bad: List[str]) -> None:
        if name in self.LIST_GLOBALS:
            self.check_list(name, value, bad)
            return
        unit, _, label = name.partition(':')
        text = schema.GLOBALS.get(unit, {}).get(label)
        if text is None:
            text = schema.EXTERNAL_GLOBALS[unit][label]
        if text.startswith('cache:'):
            text = text[6:]
        if text.startswith('table:'):
            if value != R(text[6:], 0, None):
                bad.append('%s: %r, not the base of %s (the placement\'s)'
                           % (name, value, text[6:]))
            return
        if text in self.r.structs:
            t = Sub(self.r.structs[text])
        else:
            t = schema.field_type(text, self.r.structs)
        self.check_value(t, value, name, bad)

    def check_object(self, kind: str, o: Dict[str, Any], base: Dict[str, Any],
                     where: str, bad: List[str]) -> None:
        if kind == 'linebuf':
            if 'line' in o:
                self.check_value(Ref(('line',)), o['line'], where, bad)
            return
        if kind in ('blockmap', 'reject'):
            if o.get('lump') != base['lump'] or not isinstance(
                    o.get('bytes'), str) or len(o['bytes']) != len(
                    base['bytes']):
                bad.append('%s: another lump or length than the '
                           'placement\'s' % where)
            else:
                try:
                    bytes.fromhex(o['bytes'])
                except ValueError:
                    bad.append('%s.bytes: not hexadecimal' % where)
            return
        if kind == 'blocklink':
            self.check_list(where + '.things', o.get('things'), bad)
            return
        if 'free' in o and o['free'] not in (0, 1):
            bad.append('%s.free: %r, not 0 or 1' % (where, o['free']))
        for name in ('thinglist', 'touching_thinglist', 'flood', 'flood_sb',
                     'touching_sectorlist'):
            if name in o:
                self.check_list('%s.%s' % (where, name), o[name], bad)
        if 'gstamp' in o:
            self.check_value(Int(2, False), o['gstamp'], where + '.gstamp',
                             bad)
        if kind == 'secnode' and o.get('free'):
            return
        st = self.r.structs[schema.KINDS[kind].struct]
        if kind == 'removed':
            self.check_value(Fn(), o.get('function'), where + '.function',
                             bad)
            return
        self.check_struct(st, o, where, bad)

    def check_struct(self, st: Struct, o: Dict[str, Any], where: str,
                     bad: List[str]) -> None:
        for f in st.fields:
            if f.cls in ('list', 'excluded'):
                continue
            if f.cls == 'thinker':
                if 'function' in o:
                    self.check_value(f.type.struct.by_name['function'].type,
                                     o['function'], where + '.function', bad)
                continue
            if f.name in o:
                self.check_value(f.type, o[f.name],
                                 '%s.%s' % (where, f.name), bad)

    def check_list(self, where: str, value: Any, bad: List[str]) -> None:
        if not isinstance(value, list) or not all(
                isinstance(r, R) and r.field is None for r in value):
            bad.append('%s: not a list of objects' % where)
            return
        for r in value:
            try:
                self.ref_value(r)
            except Problem as e:
                bad.append('%s: %s' % (where, e))
                return

    def check_value(self, t: Any, value: Any, where: str,
                    bad: List[str]) -> None:
        if isinstance(t, Int):
            lo, hi = ((-(1 << (8 * t.size - 1)), 1 << (8 * t.size - 1))
                      if t.signed else (0, 1 << (8 * t.size)))
            if isinstance(value, bool) or not isinstance(value, int) or \
                    not lo <= value < hi:
                bad.append('%s: %r is not an %s%d' % (
                    where, value, 'i' if t.signed else 'u', 8 * t.size))
        elif isinstance(t, Ref):
            if value is not None:
                if not isinstance(value, R):
                    bad.append('%s: %r is not a reference' % (where, value))
                    return
                try:
                    self.ref_value(value)
                except Problem as e:
                    bad.append('%s: %s' % (where, e))
        elif isinstance(t, Fn):
            if value is not None and value not in self.s.function_address:
                bad.append('%s: %r is not a declared thinker function'
                           % (where, value))
        elif isinstance(t, Raw):
            try:
                ok = isinstance(value, str) and \
                    len(bytes.fromhex(value)) == t.size
            except ValueError:
                ok = False
            if not ok:
                bad.append('%s: not %d bytes in hexadecimal' % (where,
                                                                 t.size))
        elif isinstance(t, Array):
            if not isinstance(value, list) or len(value) != t.count:
                bad.append('%s: not a list of %d' % (where, t.count))
                return
            for i, v in enumerate(value):
                self.check_value(t.elem, v, '%s[%d]' % (where, i), bad)
        elif isinstance(t, Sub):
            if not isinstance(value, dict):
                bad.append('%s: not a structure' % where)
                return
            self.check_keys(where, set(value), self.struct_keys(t.struct),
                            bad)
            self.check_struct(t.struct, value, where, bad)
        else:
            raise TypeError(t)

    # -- values --
    def ref_value(self, ref: Optional[R]) -> int:
        if ref is None:
            return 0
        try:
            return self.r.ref_address(ref)
        except (KeyError, IndexError, TypeError, AttributeError):
            raise Problem('%r names nothing in the placement' % (ref,))

    def encode(self, t: Any, address: int, value: Any) -> None:
        m = self.m
        if isinstance(t, Int):
            m.put(address, value, t.size)
        elif isinstance(t, Ref):
            m.put(address, self.ref_value(value), 4)
        elif isinstance(t, Fn):
            m.put(address, self.s.function_address[value] if value else 0, 3)
        elif isinstance(t, Raw):
            m.write(address, bytes.fromhex(value))
        elif isinstance(t, Array):
            n = t.elem.length
            for i, v in enumerate(value):
                self.encode(t.elem, address + i * n, v)
        elif isinstance(t, Sub):
            self.encode_struct(t.struct, address, value)
        else:
            raise TypeError(t)

    def encode_struct(self, st: Struct, address: int, o: Dict[str, Any],
                      kind: str = '') -> None:
        for f in st.fields:
            if f.cls in ('list', 'excluded'):
                continue
            if f.cls == 'thinker':
                fn = f.type.struct.by_name['function']
                self.encode(fn.type, address + f.offset + fn.offset,
                            o['function'])
                if kind not in ('mobj', 'zmobj'):
                    self.m.put(address + f.offset + fn.offset + 3, 0, 1)
                continue
            if f.name in o:
                self.encode(f.type, address + f.offset, o[f.name])

    def write_globals(self, gl: Dict[str, Any]) -> None:
        sym = self.s.symbols
        for unit, labels in list(schema.GLOBALS.items()) + list(
                schema.EXTERNAL_GLOBALS.items()):
            for name, text in labels.items():
                ref = '%s:%s' % (unit, name)
                if text.startswith('cache:'):
                    text = text[6:]
                if text.startswith(('object:', 'list:')):
                    continue
                address = sym.address(ref)
                value = gl.get(ref)
                if text.startswith('table:'):
                    self.m.put(address, self.p.tables[text[6:]].base, 4)
                    continue
                if text in self.r.structs:
                    self.encode_struct(self.r.structs[text], address, value)
                else:
                    self.encode(schema.field_type(text, self.r.structs),
                                address, value)
        cap = sym.address('p_think65.s:_g_thinkerclasscap')
        fn = self.c['OFS_TH_FUNCTION']
        self.m.put(cap + fn, 0, self.c['SIZEOF_TH'] - fn)

    def write_objects(self, objs: Dict[str, Dict[Any, Dict]]) -> None:
        for kind, table in objs.items():
            k = schema.KINDS[kind]
            if kind == 'linebuf':
                base = self.p.tables['linebuf'].base
                for i, o in table.items():
                    self.m.put(base + 4 * i, self.ref_value(o['line']), 4)
                continue
            if kind in ('blockmap', 'reject'):
                self.m.write(self.p.tables[kind].base,
                             bytes.fromhex(table[0]['bytes']))
                continue
            if kind == 'blocklink' or k.struct is None:
                continue
            st = self.r.structs[k.struct]
            for ident, o in table.items():
                a = self.p.address(kind, ident)
                if kind == 'secnode' and o.get('free'):
                    continue
                if kind == 'removed':
                    th = st
                    fn = th.by_name['function']
                    self.encode(fn.type, a + fn.offset, o['function'])
                    self.m.put(a + fn.offset + 3, 0, 1)
                    continue
                self.encode_struct(st, a, o, kind)

    def write_lists(self, state: Dict[str, Any]) -> None:
        c = self.c
        gl = state['globals']
        objs = state['objects']
        sym = self.s.symbols
        cap = sym.address('p_think65.s:_g_thinkerclasscap')
        seq = [self.ref_value(r) for r in gl['p_think65.s:_g_thinkerclasscap']]
        ring = [cap] + seq + [cap]
        for i in range(1, len(ring) - 1):
            self.m.put(ring[i] + c['OFS_TH_PREV'], ring[i - 1], 4)
            self.m.put(ring[i] + c['OFS_TH_NEXT'], ring[i + 1], 4)
        self.m.put(cap + c['OFS_TH_PREV'], ring[-2], 4)
        self.m.put(cap + c['OFS_TH_NEXT'], ring[1], 4)
        p = self.p
        secs = p.tables['sector']
        for i, o in objs.get('sector', {}).items():
            a = secs.base + i * secs.stride
            self.chain(a + c['OFS_SEC_THINGLIST'], o['thinglist'],
                       c['OFS_MO_SNEXT'], c['OFS_MO_SPREV'], 'cell')
            self.chain(a + c['OFS_SEC_TOUCHING_THINGLIST'],
                       o['touching_thinglist'], c['OFS_SN_M_SNEXT'],
                       c['OFS_SN_M_SPREV'], 'node')
        blocks = p.tables['blocklink']
        for i, o in objs.get('blocklink', {}).items():
            self.chain(blocks.base + 4 * i, o['things'], c['OFS_MO_BNEXT'],
                       c['OFS_MO_BPREV'], 'cell')
        for kind in ('mobj', 'zmobj'):
            for ident, o in objs.get(kind, {}).items():
                if 'touching_sectorlist' not in o:
                    continue
                a = p.address(kind, ident)
                self.chain(a + c['OFS_MO_TOUCHING_SECTORLIST'],
                           o['touching_sectorlist'], c['OFS_SN_M_TNEXT'],
                           c['OFS_SN_M_TPREV'], 'node')
        self.chain(sym.address('p_map65.s:_s_sector_list'),
                   gl['p_map65.s:_s_sector_list'], c['OFS_SN_M_TNEXT'],
                   c['OFS_SN_M_TPREV'], 'node')
        self.chain(sym.address('p_map65.s:SN_FREE'), gl['p_map65.s:SN_FREE'],
                   c['OFS_SN_M_TNEXT'], None, '')

    def chain(self, head: int, seq: List[R], next_off: int,
              prev_off: Optional[int], style: str) -> None:
        addresses = [self.ref_value(r) for r in seq]
        self.m.put(head, addresses[0] if addresses else 0, 4)
        prev = head if style == 'cell' else 0
        for i, a in enumerate(addresses):
            nxt = addresses[i + 1] if i + 1 < len(addresses) else 0
            self.m.put(a + next_off, nxt, 4)
            if prev_off is not None:
                self.m.put(a + prev_off, prev, 4)
            prev = a + next_off if style == 'cell' else a

    def write_derived(self, objs: Dict[str, Dict[Any, Dict]]) -> None:
        c = self.c
        sym = self.s.symbols
        bits = sym.constant('p_spawn65.s:TP_BITS')
        mask = sym.constant('p_spawn65.s:TP_MASK')
        pool = self.p.tables['mobj']
        used = (pool.count + 15) // 16 * 2
        data = bytearray(used)
        for i, o in objs.get('mobj', {}).items():
            if o.get('free'):
                data[i >> 3] |= 1 << (i & 7)
        self.m.write(bits, bytes(data))
        for k in range(16):
            self.m.put(mask + 2 * k, 1 << k, 2)
        gstamp = c['MM_GSTAMP']
        for i, o in objs.get('line', {}).items():
            self.m.put(gstamp + 2 * i, o['gstamp'], 2)
        idx = c['MM_FL_IDX']
        ent = c['MM_FL_ENT']
        secs = self.p.tables['sector']
        for i, o in objs.get('sector', {}).items():
            s = (secs.base + i * secs.stride) & 0xffff
            at = (idx & 0xff0000) | ((idx + s) & 0xffff)
            first, end_a, first_b, end = self.p.flood[i]
            # the room comes from the placement; the entries from the lists
            if len(o['flood']) != (end_a - first) // 2 or \
                    len(o['flood_sb']) != (end - first_b) // 2:
                # a different list length needs a new room layout
                first, end_a, first_b, end = self.new_room(i, o)
            for k, w in enumerate((first, end_a, first_b, end)):
                self.m.put(at + 2 * k, w, 2)
            for k, ref in enumerate(o['flood']):
                self.m.put(ent + first + 2 * k, self.ref_value(ref) & 0xffff,
                           2)
            for k, ref in enumerate(o['flood_sb']):
                self.m.put(ent + first_b + 2 * k,
                           self.ref_value(ref) & 0xffff, 2)

    def new_room(self, i: int, o: Dict[str, Any]) -> Tuple[int, int, int,
                                                           int]:
        raise Problem('sector %d: its flood lists changed length; the '
                      'writer keeps upstream\'s room (P_InitFlood) and '
                      'cannot move it' % i)
