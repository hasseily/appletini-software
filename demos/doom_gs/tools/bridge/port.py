"""The port's layout: a canonical state to the port's memory and back,
following a layout manifest (layout.py).

    memory = PortWriter(manifest).write(state)       # memory.PortMemory
    state = PortReader(manifest).read(memory)

The writer refuses what the layout cannot hold (more objects than a
kind's capacity, an identity that is not a slot, a reference the leaf's
codes do not name, a value no leaf holds: a field, a global or a kind
the layout lacks) with a PortError; it never drops a value silently.
The reader decodes each kind's slots 0 to count - 1 and walks the lists
from their heads through the elements' "@list.next" leaves, checking the
"@list.prev" leaves on the way.
"""

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from bridge import identity, schema
from bridge.layout import Leaf, Manifest
from bridge.memory import PortMemory
from bridge.fields import R


class PortError(ValueError):
    pass


def get_path(obj: Any, path: Sequence[Any]) -> Any:
    for p in path:
        obj = obj[p]
    return obj


def set_path(obj: Dict[str, Any], path: Sequence[Any], value: Any,
             templates: Dict[Tuple[Any, ...], str]) -> None:
    """Set obj[path] = value, making the dicts and lists on the way (an
    int after a name makes a list)."""
    for i, p in enumerate(path[:-1]):
        nxt = path[i + 1]
        if isinstance(obj, list):
            while len(obj) <= p:
                obj.append(None)
            if obj[p] is None:
                obj[p] = [] if isinstance(nxt, int) else {}
            obj = obj[p]
        else:
            if p not in obj:
                obj[p] = [] if isinstance(nxt, int) else {}
            obj = obj[p]
    last = path[-1]
    if isinstance(obj, list):
        while len(obj) <= last:
            obj.append(None)
    obj[last] = value


def handle_null(enc: Dict[str, Any]) -> int:
    return enc.get('null', (1 << (8 * enc.get('bytes', 2))) - 1)


def handle_decode(enc: Dict[str, Any], v: int, where: str) -> Optional[R]:
    """A handle's value as a reference (layout.py: "handle")."""
    if v == handle_null(enc):
        return None
    for r in enc['ranges']:
        if r['lo'] <= v < r['lo'] + r['n']:
            if 'id' in r:
                return R(r['kind'], r['id'], v - r['lo'])
            return R(r['kind'], v - r['lo'], r.get('field'))
    raise PortError('%s: handle $%X names nothing' % (where, v))


def handle_encode(enc: Dict[str, Any], ref: Optional[R], where: str) -> int:
    if ref is None:
        return handle_null(enc)
    for r in enc['ranges']:
        if r['kind'] != ref.kind:
            continue
        if 'id' in r:
            if ref.id == r['id'] and isinstance(ref.field, int) and \
                    0 <= ref.field < r['n']:
                return r['lo'] + ref.field
        elif ref.field == r.get('field') and isinstance(ref.id, int) and \
                0 <= ref.id < r['n']:
            return r['lo'] + ref.id
    raise PortError('%s: the layout cannot name %r' % (where, ref))


class _Codec:
    def __init__(self, manifest: Manifest):
        self.mf = manifest

    def pool_leaf(self, pool: Dict[str, Any]) -> Leaf:
        """The encoding of a pool's elements: a handle, or a ref of its
        codes."""
        if 'enc' in pool:
            return Leaf(('pool',), pool['enc'], pool['planes'])
        return Leaf(('pool',), {'enc': 'ref', 'codes': pool['codes']},
                    pool['planes'])

    def ref_parts(self, leaf: Leaf, ref: Optional[R]) -> Tuple[int, int,
                                                               int]:
        if ref is None:
            return 0, 0, 0
        key = [ref.kind, ref.field if ref.kind not in schema.BYTE_KINDS
               else None]
        codes = leaf.enc['codes']
        if key not in codes:
            raise PortError('%s: the layout cannot name %r' % (
                '.'.join(map(str, leaf.path)), ref))
        tag = codes.index(key) + 1
        ident = ref.id
        if ref.kind == 'symbol':
            ident = self.mf.symbol_of.get(ref.id)
        elif ref.kind == 'table':
            ident = self.mf.table_of.get(ref.id)
        if not isinstance(ident, int) or not 0 <= ident < 0x10000:
            raise PortError('%s: identity %r does not fit' % (
                '.'.join(map(str, leaf.path)), ref.id))
        offset = ref.field if ref.kind in schema.BYTE_KINDS else 0
        if offset and not leaf.enc.get('offset'):
            raise PortError('%s: %r needs an offset' % (
                '.'.join(map(str, leaf.path)), ref))
        return tag, ident, offset or 0

    def ref_from(self, leaf: Leaf, tag: int, ident: int,
                 offset: int) -> Optional[R]:
        if tag == 0:
            return None
        codes = leaf.enc['codes']
        if tag > len(codes):
            raise PortError('%s: tag %d' % ('.'.join(map(str, leaf.path)),
                                            tag))
        kind, field = codes[tag - 1]
        if kind == 'symbol':
            ident = self.mf.symbols[ident]
        elif kind == 'table':
            ident = self.mf.tables[ident]
        if kind in schema.BYTE_KINDS:
            field = offset
        return R(kind, ident, field)


class PortWriter(_Codec):
    def check(self, state: Dict[str, Any]) -> None:
        """Every value of the state has a leaf to hold it: a kind the
        layout lacks, or a global, a field or an element no leaf holds
        (or one whose `when` does not hold), would be dropped. A None
        in a list (the reader's filler, "sub.y.0") holds nothing."""
        if not isinstance(state, dict) or not isinstance(
                state.get('globals'), dict) or not isinstance(
                state.get('objects'), dict):
            raise PortError('not a canonical state: no globals or objects')
        bad: List[str] = []
        for kind in sorted(state['objects'], key=str):
            if kind not in self.mf.kinds and state['objects'][kind]:
                bad.append('%s: a kind the layout lacks' % kind)
        for kind, spec in self.mf.kinds.items():
            table = state['objects'].get(kind, {})
            if not isinstance(table, dict):
                bad.append('%s: not a table of objects' % kind)
                continue
            for ident, o in sorted(table.items(), key=lambda i: str(i[0])):
                where = '%s[%s]' % (kind, ident)
                if not isinstance(o, dict):
                    bad.append('%s: not an object' % where)
                    continue
                held = {lf.path for lf in spec['leaves']
                        if not lf.path[0].startswith('@') and not (
                            lf.when and o.get(lf.when[0]) != lf.when[1])}
                self.unheld(o, (), held, where, bad)
        self.unheld(state['globals'], (), {lf.path for lf in self.mf.globals},
                    'globals', bad)
        if bad:
            raise PortError('the layout cannot hold the state: %s%s' % (
                '; '.join(bad[:8]), '; and %d more' % (len(bad) - 8)
                if len(bad) > 8 else ''))

    @staticmethod
    def unheld(value: Any, path: Tuple[Any, ...], held: Set[Tuple[Any, ...]],
               where: str, bad: List[str]) -> None:
        """Adds to `bad` each value under `path` that no leaf of `held`
        holds."""
        if path in held:
            return
        n = len(path)
        if any(len(p) > n and p[:n] == path for p in held):
            if isinstance(value, dict):
                for k, v in value.items():
                    PortWriter.unheld(v, path + (k,), held, where, bad)
                return
            if isinstance(value, list):
                for i, v in enumerate(value):
                    PortWriter.unheld(v, path + (i,), held, where, bad)
                return
        if value is None and path and isinstance(path[-1], int):
            return
        bad.append('%s.%s: no leaf holds it' % (where, '.'.join(
            map(str, path))))

    def write(self, state: Dict[str, Any],
              memory: Optional[PortMemory] = None) -> PortMemory:
        """Raises PortError, before writing anything, for a state with a
        value no leaf holds (`check`); the encoders refuse the rest."""
        self.check(state)
        self.m = memory if memory is not None else PortMemory()
        self.pool_fill: Dict[str, int] = {n: 0 for n in self.mf.pools}
        objects = state['objects']
        heads: List[Tuple[str, List[R]]] = []
        for kind, spec in self.mf.kinds.items():
            table = objects.get(kind, {})
            ids = sorted(table)
            if ids != list(range(len(ids))):
                raise PortError('%s: identities are not 0 to %d' % (
                    kind, len(ids) - 1))
            if len(ids) > spec['capacity']:
                raise PortError('%s: %d objects, capacity %d' % (
                    kind, len(ids), spec['capacity']))
            if isinstance(spec['count'], int):
                if len(ids) > spec['count']:
                    raise PortError('%s: %d objects, the layout holds %d'
                                    % (kind, len(ids), spec['count']))
            else:
                self.put(spec['count'], 0, len(ids))
            for ident in ids:
                o = table[ident]
                for leaf in spec['leaves']:
                    if leaf.path[0].startswith('@'):
                        continue        # the lists write their links
                    if leaf.when and o.get(leaf.when[0]) != leaf.when[1]:
                        continue
                    try:
                        value = get_path(o, leaf.path)
                    except (KeyError, IndexError, TypeError):
                        raise PortError('%s[%s]: no %s' % (
                            kind, ident, '.'.join(map(str, leaf.path))))
                    if leaf.enc['enc'] == 'list':
                        heads.append((leaf.enc['list'], value))
                    self.encode(leaf, ident, value)
        for leaf in self.mf.globals:
            name = leaf.path[0]
            if name not in state['globals']:
                raise PortError('no global %s' % name)
            value = get_path(state['globals'], leaf.path)
            if leaf.enc['enc'] == 'list':
                heads.append((leaf.enc['list'], value))
            self.encode(leaf, 0, value)
        for name, seq in heads:
            self.write_links(name, seq)
        for name, pool in self.mf.pools.items():
            self.put(pool['count'], 0, self.pool_fill[name])
        return self.m

    def put(self, planes: Sequence[int], index: int, value: int) -> None:
        for k, p in enumerate(planes):
            self.m.put(p + index, value >> (8 * k), 1)

    def encode(self, leaf: Leaf, index: int, value: Any) -> None:
        e = leaf.enc['enc']
        planes = leaf.planes
        where = '.'.join(map(str, leaf.path))
        if e == 'bit':                  # a bitmap: the object's index
            bit = leaf.enc['value']
            if value not in (0, bit):
                raise PortError('%s: %r is not 0 or %d' % (where, value,
                                                           bit))
            at = planes[0] + (index >> 3)
            old = self.m.u8(at)
            mask = 1 << (index & 7)
            self.m.put(at, (old | mask) if value else (old & ~mask), 1)
            return
        index *= leaf.stride            # records of `stride` bytes
        if e == 'handle':
            self.put(planes, index, handle_encode(leaf.enc, value, where))
            return
        if e == 'sxbyte':
            if not isinstance(value, int) or not -128 <= value < 128:
                raise PortError('%s: %r does not fit a signed byte' % (
                    where, value))
            self.put(planes, index, value & 0xff)
            return
        if e == 'list' and 'ranges' in leaf.enc:
            first = value[0] if value else None
            self.put(planes, index, handle_encode(leaf.enc, first, where))
            return
        if e == 'int':
            n = leaf.enc['bytes']
            if not isinstance(value, int):
                raise PortError('%s: %r is not a number' % (where, value))
            lo = -(1 << (8 * n - 1)) if leaf.enc['signed'] else 0
            if not lo <= value < lo + (1 << (8 * n)):
                raise PortError('%s: %d does not fit %d bytes' % (
                    where, value, n))
            self.put(planes, index, value & ((1 << (8 * n)) - 1))
        elif e == 'ref':
            tag, ident, offset = self.ref_parts(leaf, value)
            self.put(planes[:1], index, tag)
            self.put(planes[1:3], index, ident)
            if leaf.enc.get('offset'):
                self.put(planes[3:5], index, offset)
        elif e == 'enum':
            values = leaf.enc['values']
            if value not in values:
                raise PortError('%s: %r is not a value of the enum'
                                % (where, value))
            self.put(planes, index, values.index(value))
        elif e == 'raw':
            data = bytes.fromhex(value)
            if len(data) != leaf.enc['bytes']:
                raise PortError('%s: %d bytes' % (where, len(data)))
            for k, b in enumerate(data):
                self.m.put(planes[k] + index, b, 1)
        elif e == 'list':
            first = value[0] if value else None
            tag, ident, _ = self.ref_parts(leaf, first)
            self.put(planes[:1], index, tag)
            self.put(planes[1:3], index, ident)
        elif e == 'seq':
            pool = self.mf.pools[leaf.enc['pool']]
            start = self.pool_fill[leaf.enc['pool']]
            if start + len(value) > pool['capacity']:
                raise PortError('%s: the pool %s is full' % (
                    where, leaf.enc['pool']))
            pleaf = self.pool_leaf(pool)
            for k, ref in enumerate(value):
                if 'enc' in pool:
                    self.put(pool['planes'], start + k, handle_encode(
                        pool['enc'], ref, where))
                    continue
                tag, ident, _ = self.ref_parts(pleaf, ref)
                self.put(pool['planes'][:1], start + k, tag)
                self.put(pool['planes'][1:3], start + k, ident)
            self.pool_fill[leaf.enc['pool']] = start + len(value)
            self.put(planes[:2], index, start)
            self.put(planes[2:4], index, start + len(value)
                     if leaf.enc.get('form') == 'end' else len(value))
        elif e == 'table':
            if value != R(leaf.enc['kind'], 0, None):
                raise PortError('%s: %r is not the table %s' % (
                    where, value, leaf.enc['kind']))
        elif e == 'blob':
            data = bytes.fromhex(value)
            if len(data) > leaf.enc['max']:
                raise PortError('%s: %d bytes, at most %d' % (
                    where, len(data), leaf.enc['max']))
            self.put(planes[:2], index, len(data))
            self.m.write(planes[2], data)
        else:
            raise PortError('%s: encoding %s' % (where, e))

    def link_leaf(self, kind: str, name: str) -> Optional[Leaf]:
        for leaf in self.mf.kinds[kind]['leaves']:
            if leaf.path == (name,):
                return leaf
        return None

    def write_links(self, name: str, seq: List[R]) -> None:
        prev_on = self.mf.lists[name]['prev']
        for i, ref in enumerate(seq):
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            leaf = self.link_leaf(ref.kind, '@%s.next' % name)
            if leaf is None:
                raise PortError('%s: %s has no link of list %s' % (
                    ref, ref.kind, name))
            self.encode(leaf, ref.id, nxt)
            if prev_on:
                self.encode(self.link_leaf(ref.kind, '@%s.prev' % name),
                            ref.id, seq[i - 1] if i else None)


class PortReader(_Codec):
    def read(self, memory: PortMemory) -> Dict[str, Any]:
        self.m = memory
        self.problems: List[str] = []
        objects: Dict[str, Dict[int, Dict[str, Any]]] = {}
        self.counts: Dict[str, int] = {}
        heads: List[Tuple[Dict, Tuple[Any, ...], str, Optional[R]]] = []
        for kind, spec in self.mf.kinds.items():
            n = spec['count'] if isinstance(spec['count'], int) else \
                self.get(spec['count'], 0)
            if n > spec['capacity']:
                raise PortError('%s: count %d, capacity %d' % (
                    kind, n, spec['capacity']))
            self.counts[kind] = n
            if not n:
                continue
            table = objects[kind] = {}
            for ident in range(n):
                o: Dict[str, Any] = {}
                whens = [lf for lf in spec['leaves'] if lf.when]
                plain = [lf for lf in spec['leaves'] if not lf.when]
                for leaf in plain + whens:
                    if leaf.path[0].startswith('@'):
                        continue
                    if leaf.when and o.get(leaf.when[0]) != leaf.when[1]:
                        continue
                    value = self.decode(leaf, ident)
                    if leaf.enc['enc'] == 'list':
                        heads.append((o, leaf.path, leaf.enc['list'], value))
                    set_path(o, leaf.path, value, {})
                table[ident] = o
        gl: Dict[str, Any] = {}
        for leaf in self.mf.globals:
            value = self.decode(leaf, 0)
            if leaf.enc['enc'] == 'list':
                heads.append((gl, leaf.path, leaf.enc['list'], value))
            set_path(gl, leaf.path, value, {})
        for owner, path, name, first in heads:
            set_path(owner, path, self.walk(name, first), {})
        # the port numbers these kinds by its slots: the canonical rules
        # number them from the lists (identity.py)
        return identity.renumber({'format': 'bridge-canonical 1',
                                  'globals': gl, 'objects': objects})

    def get(self, planes: Sequence[int], index: int) -> int:
        v = 0
        for k, p in enumerate(planes):
            v |= self.m.u8(p + index) << (8 * k)
        return v

    def decode(self, leaf: Leaf, index: int) -> Any:
        e = leaf.enc['enc']
        planes = leaf.planes
        where = '.'.join(map(str, leaf.path))
        if e == 'bit':                  # a bitmap: the object's index
            byte = self.m.u8(planes[0] + (index >> 3))
            return leaf.enc['value'] if byte >> (index & 7) & 1 else 0
        index *= leaf.stride            # records of `stride` bytes
        if e == 'int':
            v = self.get(planes, index)
            n = leaf.enc['bytes']
            if leaf.enc['signed'] and v >> (8 * n - 1):
                v -= 1 << (8 * n)
            return v
        if e == 'handle' or (e == 'list' and 'ranges' in leaf.enc):
            return handle_decode(leaf.enc, self.get(planes, index), where)
        if e == 'sxbyte':
            v = self.get(planes, index)
            return v - 256 if v & 0x80 else v
        if e in ('ref', 'list'):
            tag = self.get(planes[:1], index)
            ident = self.get(planes[1:3], index)
            offset = self.get(planes[3:5], index) if leaf.enc.get(
                'offset') else 0
            return self.ref_from(leaf, tag, ident, offset)
        if e == 'enum':
            values = leaf.enc['values']
            i = self.get(planes, index)
            if i >= len(values):
                raise PortError('%s: enum %d' % (leaf.path, i))
            return values[i]
        if e == 'raw':
            return bytes(self.m.u8(p + index) for p in planes).hex()
        if e == 'seq':
            pool = self.mf.pools[leaf.enc['pool']]
            start = self.get(planes[:2], index)
            n = self.get(planes[2:4], index)
            if leaf.enc.get('form') == 'end':
                if n < start:
                    raise PortError('%s: a sequence from %d to %d' % (
                        where, start, n))
                n -= start
            if start + n > pool['capacity']:
                raise PortError('%s: a sequence past the pool %s' % (
                    where, leaf.enc['pool']))
            if 'enc' in pool:
                return [handle_decode(pool['enc'], self.get(pool['planes'],
                                                            k), where)
                        for k in range(start, start + n)]
            pleaf = self.pool_leaf(pool)
            return [self.ref_from(pleaf, self.get(pool['planes'][:1], k),
                                  self.get(pool['planes'][1:3], k), 0)
                    for k in range(start, start + n)]
        if e == 'table':
            return R(leaf.enc['kind'], 0, None)
        if e == 'blob':
            n = self.get(planes[:2], index)
            if n > leaf.enc['max']:
                raise PortError('%s: %d bytes, at most %d' % (
                    where, n, leaf.enc['max']))
            return self.m.read(planes[2], n).hex()
        raise PortError('encoding %s' % e)

    def walk(self, name: str, first: Optional[R]) -> List[R]:
        seq: List[R] = []
        seen = set()
        prev_on = self.mf.lists[name]['prev']
        ref = first
        prev = None
        while ref is not None:
            key = (ref.kind, ref.id)
            if key in seen or len(seq) > 100000:
                raise PortError('list %s loops at %r' % (name, ref))
            seen.add(key)
            if ref.id >= self.counts.get(ref.kind, 0):
                raise PortError('list %s: %r is past its table' % (name,
                                                                   ref))
            seq.append(ref)
            spec = self.mf.kinds[ref.kind]
            links = {lf.path[0]: lf for lf in spec['leaves']
                     if lf.path[0].startswith('@%s.' % name)}
            if prev_on:
                got = self.decode(links['@%s.prev' % name], ref.id)
                if got != prev:
                    raise PortError('list %s: %r has prev %r, not %r' % (
                        name, ref, got, prev))
            prev = ref
            ref = self.decode(links['@%s.next' % name], ref.id)
        return seq


# ---- through a2vm -----------------------------------------------------------

NICE = ['nice', '-n', '10']
A2VM_TIMEOUT = 120      # seconds; a dump takes well under one


def through_a2vm(memory: PortMemory, a2vm: Path, rom: Path,
                 work: Path) -> PortMemory:
    """Load the port memory into a2vm as an --image and dump a2vm's RAM
    with a bus script (tools/a2vm/README.md): the memory a2vm holds,
    read back, so the layout's addresses are checked against the
    machine's own map (main and the RamWorks banks). The files in `work`
    are deleted after (a dump is 8.4 MB)."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    image = work / 'state.a2vmimg'
    image.write_bytes(memory.image_bytes())
    dump = work / 'dump'
    script = work / 'bus.txt'
    script.write_text('dump %s\n' % dump)
    raw = Path(str(dump) + '.ram')
    try:
        # a batch run (check --a2vm: one a dump): under nice, as the
        # ground rules ask
        # and bounded (the ground rules): the bus script ends the run
        # after one dump, the timeout if it does not
        try:
            result = subprocess.run(NICE + [str(a2vm), '--rom', str(rom),
                                            '--image', str(image),
                                            '--bus-script', str(script)],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    universal_newlines=True,
                                    timeout=A2VM_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise PortError('a2vm did not finish in %d s' % A2VM_TIMEOUT)
        if result.returncode:
            raise PortError('a2vm failed: ' + result.stderr)
        if not raw.exists():
            raw = dump
        return PortMemory.from_snapshot(raw)
    finally:
        for path in (image, script, raw, dump):
            if path.exists():
                path.unlink()
        try:
            work.rmdir()
        except OSError:
            pass
