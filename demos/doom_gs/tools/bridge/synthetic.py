"""Synthetic states for the bridge's tests: a dump changed the way upstream
would change it, for the cases the coverage dumps do not meet (a mobj in
the zone when the pool is full, with or without a thinker; a special
waiting for its removal).

Each change follows upstream's own code: a zone block is carved from a
free block as z_zone65.s tryMalloc does (the size in paragraphs with the
header, the rest a new free block), a thinker joins the end of the list
as P_AddThinker does, a thing joins the head of a sector's list as
P_SetThingPosition does (sprev: the address of the link that points to
it).
"""

from typing import Optional, Tuple

from bridge.memory import Memory
from bridge.upstream import Reader

def free_block(reader: Reader, size: int) -> Tuple[int, int]:
    """The first free zone block with room for `size` bytes and a rest of
    at least one paragraph."""
    for a, bsize, tag, user in reader.blocks:
        if user == 0 and bsize >= size + reader.s.zone.header:
            return a, bsize
    raise ValueError('no free zone block of %d bytes' % size)


def zone_alloc(memory: Memory, reader: Reader, request: int, tag: int,
               user: Optional[int] = None) -> int:
    """A new zone block for `request` bytes (tag, user as z_zone65.s:
    user 2 is "no user"); returns its payload address. The reader must
    have walked the zone of this memory (Reader.locate)."""
    zn = reader.s.zone
    user = zn.no_user if user is None else user
    p = zn.header
    size = ((request + p - 1) & ~(p - 1)) + p
    a, bsize = free_block(reader, size)
    seg = a >> 4                    # a segment is the address >> 4
    nxt = memory.u16(a + zn.next)
    prev = memory.u16(a + zn.prev)
    rest = a + size
    rest_seg = rest >> 4
    memory.put(a + zn.size, size, 4)
    memory.put(a + zn.tag, tag, 2)
    memory.put(a + zn.user, user, 4)
    memory.put(a + zn.next, rest_seg, 2)
    memory.put(a + zn.prev, prev, 2)
    memory.put(rest + zn.size, bsize - size, 4)
    memory.put(rest + zn.tag, 0, 2)
    memory.put(rest + zn.user, 0, 4)
    memory.put(rest + zn.next, nxt, 2)
    memory.put(rest + zn.prev, seg, 2)
    memory.put((nxt << 4) + zn.prev, rest_seg, 2)
    memory.write(a + p, bytes(request))
    return a + p


def append_thinker(memory: Memory, reader: Reader, address: int) -> None:
    """P_AddThinker: at the end of the list."""
    c = reader.c
    cap = reader.sym.address('p_think65.s:_g_thinkerclasscap')
    nxt, prev = c['OFS_TH_NEXT'], c['OFS_TH_PREV']
    last = memory.u32(cap + prev) & 0xffffff
    memory.put(last + nxt, address, 4)
    memory.put(address + nxt, cap, 4)
    memory.put(address + prev, last, 4)
    memory.put(cap + prev, address, 4)


def live_slot(memory: Memory, reader: Reader, skip: int = 0) -> int:
    """A pool slot that is not free (the `skip`+1-th)."""
    free = reader.free_slots()
    live = [i for i in range(reader.placement.tables['mobj'].count)
            if i not in free]
    return live[skip]


def zone_mobj(memory: Memory, reader: Reader, slot: int,
              function: str = None, nosector: bool = True) -> int:
    """A copy of pool slot `slot` in a new zone block (PU_LEVEL, no user):
    MF_POOLED off, MF_NOBLOCKMAP on, and MF_NOSECTOR on unless `nosector`
    is False; no sector nodes, no target or last enemy; the thinker
    function `function` ("unit:label") or none."""
    c = reader.c
    pool = reader.placement.tables['mobj']
    size = reader.structs['MO'].size
    source = pool.base + slot * pool.stride
    a = zone_alloc(memory, reader, size, reader.s.zone.level)
    memory.write(a, memory.read(source, size))
    flags = memory.u32(a + c['OFS_MO_FLAGS'])
    flags &= ~(c['CONST_MF_POOLED_HI'] << 16)
    flags |= c['CONST_MF_NOBLOCKMAP']
    if nosector:
        flags |= c['CONST_MF_NOSECTOR']
    else:
        flags &= ~c['CONST_MF_NOSECTOR']
    memory.put(a + c['OFS_MO_FLAGS'], flags, 4)
    for field in ('OFS_MO_TOUCHING_SECTORLIST', 'OFS_MO_TARGET',
                  'OFS_MO_LASTENEMY', 'OFS_MO_SNEXT', 'OFS_MO_SPREV',
                  'OFS_MO_BNEXT', 'OFS_MO_BPREV'):
        memory.put(a + c[field], 0, 4)
    fn = reader.s.function_address[function] if function else 0
    memory.put(a + c['OFS_TH_FUNCTION'], fn, 4)
    memory.put(a + c['OFS_TH_PREV'], 0, 4)
    memory.put(a + c['OFS_TH_NEXT'], 0, 4)
    if function:
        append_thinker(memory, reader, a)
    return a


def push_sector_thing(memory: Memory, reader: Reader, sector: int,
                      address: int) -> None:
    """P_SetThingPosition's sector link: the thing at the head of the
    sector's list."""
    c = reader.c
    secs = reader.placement.tables['sector']
    head = secs.base + sector * secs.stride + c['OFS_SEC_THINGLIST']
    first = memory.u32(head) & 0xffffff
    memory.put(address + c['OFS_MO_SNEXT'], first, 4)
    memory.put(address + c['OFS_MO_SPREV'], head, 4)
    if first:
        memory.put(first + c['OFS_MO_SPREV'], address + c['OFS_MO_SNEXT'], 4)
    memory.put(head, address, 4)


def remove_thinker(memory: Memory, reader: Reader, address: int) -> None:
    """P_RemoveThinker: the function becomes P_RemoveThinkerDelayed."""
    fn = reader.s.function_address['p_think65.s:P_RemoveThinkerDelayed']
    memory.put(address + reader.c['OFS_TH_FUNCTION'], fn, 3)
