"""The bridge's acceptance checks on dumps (tools/bridge/README.md).

For each dump (dumps.py: a G_Ticker entry with its tic's footprint):

    read        upstream's reader finds every object and decodes it with
                no problem and 0 raw pointers
    coverage    every byte of the game-state regions is claimed once, by
                a field, a list link, a derived table or a named exclusion
    liveness    no byte of a "dead" exclusion (schema.DEAD_EXCLUSIONS) is
                read by the tic before the tic writes it (the dump's
                reads.img), but the named overreads (schema.OVERREADS)
    writes      every byte the tic writes outside the game-state regions
                is code, the stack, a direct page, or data of a unit that
                is not game logic
    upstream    upstream -> canonical (through JSON) -> upstream at the
                reader's placement, every claimed byte poisoned first:
                0 differing bytes in the regions, 0 bytes written outside
    port        upstream -> canonical -> port (native-v1) -> canonical:
                equal, and through a2vm's memory when a2vm is given

Across dumps: the tables derived at a level load (bank $21, the respawn
copy) are equal in the dumps of one level load. Over a sweep (dumps.py
--sweep): the liveness check on the game units' data.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bridge import canonical, identity, schema
from bridge.layout import Manifest, native_v1
from bridge.memory import Memory
from bridge.port import PortReader, PortWriter, through_a2vm
from bridge.upstream import Reader, Schema, Writer

try:                                    # tools/ on the path (bridge.py)
    from ref816 import refimage
except ImportError:                     # pragma: no cover
    refimage = None

DEAD = {'excl:' + name for name in schema.DEAD_EXCLUSIONS}


def overread_addresses(sch: Schema) -> Dict[int, str]:
    out = {}
    for (unit, label), (offset, why) in schema.OVERREADS.items():
        out[sch.symbols.address('%s:%s' % (unit, label)) + offset] = why
    return out


def label_of(sch: Schema, address: int) -> str:
    f = sch.symbols.fragment_at(address)
    if f is None:
        return '$%06X' % address
    for lb in f.labels:
        if lb.address <= address < lb.address + lb.size:
            return '%s+%d' % (lb.ref, address - lb.address)
    return '%s %s $%06X' % (f.unit, f.section, address)


def section_of(sch: Schema, address: int) -> str:
    """The link map's section whose range holds the address (the stack
    section has no fragments)."""
    for name, s in sch.symbols.sections.items():
        if s['first'] <= address <= s['last'] and name == 'stack':
            return name
    return ''


def image_bytes_of(path: Path) -> Iterable[Tuple[int, int]]:
    """(address, value) of each byte of a ref816 image's records."""
    for address, data in refimage.read(path).records:
        for i, value in enumerate(data):
            yield address + i, value


def liveness(owner_of, reads: Path, sch: Schema,
             overreads: Dict[int, str]) -> List[str]:
    """Bytes of dead exclusions that the tic read before writing them."""
    found: Dict[str, int] = {}
    for address, _ in image_bytes_of(reads):
        owner = owner_of(address)
        if owner in DEAD and address not in overreads:
            key = '%s (%s)' % (label_of(sch, address), owner[5:])
            found[key] = found.get(key, 0) + 1
    return sorted(found)


def outside_writes(reader: Reader, writes: Path, sch: Schema
                   ) -> Tuple[Dict[str, int], List[str]]:
    """What the tic wrote outside the game-state regions, by place; and
    the bytes that are none of code, stack, direct page or the data of a
    unit that is not game logic."""
    places: Dict[str, int] = {}
    unknown: List[str] = []
    for address, _ in image_bytes_of(writes):
        if reader.coverage.region_of(address) >= 0:
            continue
        f = sch.symbols.fragment_at(address)
        section = section_of(sch, address)
        if section == 'stack':
            place = 'stack'
        elif f is None:
            place = None
        elif f.section in ('ztiny', 'registers'):
            place = 'direct page'
        elif f.kind == 'text':
            place = 'code (%s)' % f.section
        elif f.kind in ('bss', 'data') and not schema.is_game_unit(f.unit):
            place = 'data of %s' % f.unit
        else:
            place = None
        if place is None:
            if len(unknown) < 20:
                unknown.append('$%06X (%s)' % (address, label_of(sch,
                                                                  address)))
            continue
        places[place] = places.get(place, 0) + 1
    return places, unknown


def upstream_roundtrip(reader: Reader, state: Dict[str, Any],
                       memory: Memory) -> Tuple[int, int, List[str]]:
    """(differing bytes in the regions, bytes changed outside them,
    the first differences)."""
    again = canonical.roundtrip_json(state)
    out = Writer(reader).write(again, memory, poison=True)
    diff, first = 0, []
    for start, end in reader.coverage.spans(lambda o: o != '(none)'):
        a, b = memory.read(start, end - start), out.read(start, end - start)
        if a != b:
            for i in range(end - start):
                if a[i] != b[i]:
                    diff += 1
                    if len(first) < 8:
                        first.append('$%06X %s: $%02X, wrote $%02X' % (
                            start + i, reader.coverage.claimed(start + i),
                            a[i], b[i]))
    outside = 0
    for bank, data in out.banks.items():
        orig = memory.banks.get(bank)
        if orig is None:
            orig = bytes(len(data))
        if data == orig:
            continue
        for i in range(len(data)):
            if data[i] != orig[i] and \
                    reader.coverage.region_of(bank << 16 | i) < 0:
                outside += 1
    return diff, outside, first


def check_dump(directory: Path, sch: Schema, manifest: Manifest,
               a2vm: Optional[Tuple[Path, Path, Path]] = None
               ) -> Dict[str, Any]:
    info = json.loads((directory / 'dump.json').read_text())
    memory = Memory.from_image(directory / 'entry.img')
    reader = Reader(memory, sch)
    state = reader.read()
    result: Dict[str, Any] = {'name': directory.name, 'info': info}
    result['problems'] = list(reader.problems)
    result['raw_pointers'] = list(reader.raw_pointers)
    totals = reader.coverage.totals()
    result['unclaimed'] = totals.get('(none)', 0)
    result['claimed_twice'] = len(reader.coverage.double)
    result['bytes'] = sum(totals.values())
    result['by_owner'] = dict(sorted(totals.items()))
    result['counts'] = canonical.counts(state)
    result['identities'] = canonical.diff(state, identity.renumber(state))
    result['functions'] = sorted({o.get('function') for kind in state[
        'objects'].values() for o in kind.values() if 'function' in o},
        key=str)
    result['zone_mobjs_without_thinker'] = getattr(reader, 'zone_orphans', 0)
    overreads = overread_addresses(sch)
    reads = directory / 'reads.img'
    result['liveness'] = liveness(reader.coverage.claimed, reads, sch,
                                  overreads) if reads.exists() else None
    writes = directory / 'writes.img'
    if writes.exists():
        places, unknown = outside_writes(reader, writes, sch)
        result['outside_writes'] = places
        result['outside_unknown'] = unknown
    diff, outside, first = upstream_roundtrip(reader, state, memory)
    result['upstream_roundtrip'] = {'differing': diff, 'outside': outside,
                                    'first': first}
    port_memory = PortWriter(manifest).write(state)
    back = PortReader(manifest).read(port_memory)
    result['port_roundtrip'] = canonical.diff(
        canonical.roundtrip_json(state), canonical.roundtrip_json(back))
    if a2vm is not None:
        binary, rom, work = a2vm
        loaded = through_a2vm(port_memory, binary, rom, work / directory.name)
        again = PortReader(manifest).read(loaded)
        result['a2vm_roundtrip'] = canonical.diff(
            canonical.roundtrip_json(state), canonical.roundtrip_json(again))
    result['level_tables'] = {}
    for name in ('level tables', 'respawn copy'):
        h = hashlib.sha256()
        for start, end in reader.coverage.spans(
                lambda o, n=name: o == 'excl:' + n):
            h.update(memory.read(start, end - start))
        result['level_tables'][name] = h.hexdigest()
    result['ok'] = passed(result)
    return result


def passed(result: Dict[str, Any]) -> bool:
    return (not result['problems'] and not result['raw_pointers'] and
            not result['unclaimed'] and not result['claimed_twice'] and
            not result.get('liveness') and
            not result.get('outside_unknown') and
            result['upstream_roundtrip']['differing'] == 0 and
            result['upstream_roundtrip']['outside'] == 0 and
            not result['port_roundtrip'] and not result['identities'] and
            not result.get('a2vm_roundtrip'))


def constancy(results: Sequence[Dict[str, Any]]) -> Tuple[List[str], int]:
    """The tables derived at a level load must agree across the dumps of
    one load (same set, same map, leveltime rising): the differences, and
    the number of pairs compared."""
    problems = []
    groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for r in results:
        info = r['info']
        if info.get('gamestate') != 0:
            continue
        groups.setdefault((info['set'], info['gamemap']), []).append(r)
    compared = 0
    for group in groups.values():
        group.sort(key=lambda r: r['info']['gametic'])
        for a, b in zip(group, group[1:]):
            if b['info']['leveltime'] <= a['info']['leveltime']:
                continue            # another load of the same map
            compared += 1
            for name, value in a['level_tables'].items():
                if b['level_tables'].get(name) != value:
                    problems.append('%s and %s: %s differ' % (
                        a['name'], b['name'], name))
    return problems, compared


def global_owners(sch: Schema) -> Dict[int, str]:
    """The owner of each byte of the game units' data that does not
    depend on a dump: dead exclusions only (for the sweep)."""
    out: Dict[int, str] = {}
    cmds = sch.structs['CMDS']
    for f in sch.symbols.data_fragments():
        if not schema.is_game_unit(f.unit):
            continue
        if f.labels and f.labels[0].address > f.address:
            for a in range(f.address, f.labels[0].address):
                out[a] = 'excl:layout pad'
        wanted = schema.GLOBALS.get(f.unit, {})
        excluded = schema.UNIT_EXCLUSIONS.get(f.unit, {})
        for label in f.labels:
            if label.name in wanted:
                if wanted[label.name] == 'CMDS':
                    pad = cmds.by_name['pad']
                    for a in range(pad.offset, pad.end):
                        out[label.address + a] = 'excl:layout pad'
                continue
            why = next((k for k, v in excluded.items() if label.name in v),
                       'scratch')
            for a in range(label.address, label.address + label.size):
                out[a] = 'excl:' + why
    for start, end in schema.bank21_scratch(sch.c):
        for a in range(start, end):
            out[a] = 'excl:trace scratch'
    return out


def check_sweep(directories: Sequence[Path], sch: Schema
                ) -> Tuple[int, List[str]]:
    """(tics checked, violations) of the liveness check on the game units'
    data over a sweep's footprints."""
    owners = global_owners(sch)
    overreads = overread_addresses(sch)
    found: Dict[str, List[str]] = {}
    for d in directories:
        for v in liveness(lambda a: owners.get(a, ''), d / 'reads.img', sch,
                          overreads):
            found.setdefault(v, []).append(d.name)
    return len(directories), ['%s: %d tics (%s)' % (k, len(v), ', '.join(
        v[:3])) for k, v in sorted(found.items())]


def manifest_for(sch: Schema) -> Manifest:
    return native_v1(sch.structs, sch.c, sch.symbols)
