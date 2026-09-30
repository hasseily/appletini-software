"""The port's layout manifest, and the first native layout (native-v1).

A manifest says where the port keeps each canonical value; the bridge's
port reader and writer (port.py) follow it and know nothing else of the
port, so a change of the port's layout is a change of its manifest. The
format, "bridge-port-layout 1", is JSON (tools/bridge/README.md has an
example):

    format, name, note
    symbols   ["unit:label", ...]: the labelled constants a reference can
              name (its id is the index here)
    tables    ["MM_...", ...]: the fixed tables a reference can name
    lists     {name: {"elements": [kind, ...], "prev": bool}}: each list
              of schema.LISTS; its elements carry "@NAME.next" (and
              "@NAME.prev") leaves
    pools     {name: {"capacity": n, "codes": [...], "planes": [...],
              "count": [...]}}: shared arrays of references for "seq"
              leaves (a sector's flood lists)
    kinds     {kind: {"capacity": n, "count": [planes], "leaves": [...]}}
    globals   {"leaves": [...]}

A leaf is one value of an object (or of the globals): its "path" (field
names and array indexes into the canonical object, the global's name
first for a global), its encoding "enc" and the addresses of its "planes".
An object with identity i keeps byte k of a leaf at planes[k] + i: each
byte of each field is an array ("byte plane") of `capacity` bytes, the
layout native-verification.md section 4.3 proposes. Encodings:

    int    {"bytes": n, "signed": b}: n planes, little-endian
    ref    {"codes": [[kind, field], ...], "offset": b}: planes tag, id
           low, id high (and offset low, offset high when "offset"): tag 0
           is NULL, tag i the reference codes[i - 1] (field null: the
           object itself); the id of a symbol or a table is its index in
           "symbols" or "tables"
    enum   {"values": [null, "unit:label", ...]}: one plane, the index
    raw    {"bytes": n}: n planes of bytes
    list   {"list": name, "codes": [...]}: the head of a list: a ref (3
           planes) to its first element; each element's "@name.next" ref
           names the next, "@name.prev" the one before
    seq    {"pool": name}: planes start low, start high, length low,
           length high into the pool's arrays
    table  {"kind": k}: the base of an object table: no planes (the port
           addresses its tables itself)
    blob   {"max": n}: planes length low, length high, then one address:
           the n bytes (a lump such as BLOCKMAP)

A leaf may have "when": [field, value]: it exists only in objects whose
field has that value (the fields of a sector node that is not free).

An address is "main:XXXX" or "aux:BB:XXXX" (RamWorks bank BB, as $C073
names it); memory.port_address reads them.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bridge import schema
from bridge.memory import MAIN, port_address, port_text
from bridge.fields import Array, Fn, Int, Raw, Ref, Struct, Sub

FORMAT = 'bridge-port-layout 1'

# Link fields of upstream's structures that are the port's own lists'
# links (schema.LISTS): the port keeps "@list.next"/"@list.prev" instead.
LINK_FIELDS = {('MO', 'snext'), ('MO', 'sprev'), ('MO', 'bnext'),
               ('MO', 'bprev'), ('SN', 'm_tnext'), ('SN', 'm_tprev'),
               ('SN', 'm_snext'), ('SN', 'm_sprev')}
# Head fields: the canonical value is the list.
HEAD_FIELDS = {('MO', 'touching_sectorlist'): 'thing_nodes',
               ('SEC', 'thinglist'): 'sector_things',
               ('SEC', 'touching_thinglist'): 'sector_nodes'}
GLOBAL_LISTS = {'p_think65.s:_g_thinkerclasscap': 'thinkers',
                'p_map65.s:_s_sector_list': 'sector_list',
                'p_map65.s:SN_FREE': 'sn_free'}
# Fields a pointer may name inside an object (what upstream does:
# button_t.soundorg = &sector->soundorg, p_switch65.s; scroll_t's
# &sides[i].textureoffset, p_spec65.s).
ADDRESSABLE = [('sector', 'soundorg'), ('side', 'textureoffset')]


class Leaf:
    def __init__(self, path: Sequence[Any], enc: Dict[str, Any],
                 planes: Sequence[int] = (), when=None):
        self.path = tuple(path)
        self.enc = dict(enc)
        self.planes = list(planes)
        self.when = tuple(when) if when else None

    @property
    def width(self) -> int:
        """The number of planes the encoding needs."""
        e = self.enc['enc']
        if e == 'int':
            return self.enc['bytes']
        if e == 'ref':
            return 5 if self.enc.get('offset') else 3
        if e == 'enum':
            return 1
        if e == 'raw':
            return self.enc['bytes']
        if e == 'list':
            return 3
        if e == 'seq':
            return 4
        if e == 'table':
            return 0
        if e == 'blob':
            return 3
        raise ValueError(e)

    def to_json(self) -> Dict[str, Any]:
        out = {'path': list(self.path), 'enc': self.enc,
               'planes': [port_text(p) for p in self.planes]}
        if self.when:
            out['when'] = list(self.when)
        return out

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> 'Leaf':
        return cls(d['path'], d['enc'], [port_address(p) for p in
                                         d['planes']], d.get('when'))


class Manifest:
    def __init__(self, data: Dict[str, Any]):
        if data.get('format') != FORMAT:
            raise ValueError('not a %s manifest' % FORMAT)
        self.data = data
        self.name = data['name']
        self.symbols = list(data['symbols'])
        self.symbol_of = {s: i for i, s in enumerate(self.symbols)}
        self.tables = list(data['tables'])
        self.table_of = {s: i for i, s in enumerate(self.tables)}
        self.lists = data['lists']
        self.pools = {k: dict(v, planes=[port_address(p) for p in
                                         v['planes']],
                              count=[port_address(p) for p in v['count']])
                      for k, v in data['pools'].items()}
        self.kinds = {}
        for kind, k in data['kinds'].items():
            self.kinds[kind] = {
                'capacity': k['capacity'],
                'count': [port_address(p) for p in k['count']],
                'leaves': [Leaf.from_json(x) for x in k['leaves']]}
        self.globals = [Leaf.from_json(x) for x in data['globals']['leaves']]

    @classmethod
    def load(cls, path: Path) -> 'Manifest':
        return cls(json.loads(Path(path).read_text()))

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.data, indent=1) + '\n')


# ---- the canonical fields of each kind, from the schema --------------------

def ref_codes(targets: Sequence[str]) -> List[Tuple[str, Optional[str]]]:
    out = []
    for kind in targets:
        out.append((kind, None))
        out += [(k, f) for k, f in ADDRESSABLE if k == kind]
    return out


def list_leaf(path: Tuple[Any, ...], name: str) -> Leaf:
    return Leaf(path, {'enc': 'list', 'list': name, 'codes': [
        [k, None] for k in schema.LISTS[name].elements]})


def leaves_of_type(path: Tuple[Any, ...], t: Any) -> List[Leaf]:
    if isinstance(t, Int):
        return [Leaf(path, {'enc': 'int', 'bytes': t.size,
                            'signed': t.signed})]
    if isinstance(t, Ref):
        codes = ref_codes(t.targets)
        return [Leaf(path, {'enc': 'ref', 'codes': [list(c) for c in codes],
                            'offset': any(k in schema.BYTE_KINDS
                                          for k in t.targets)})]
    if isinstance(t, Fn):
        return [Leaf(path, {'enc': 'enum', 'values': [None] + sorted(
            schema.THINKER_FUNCTIONS)})]
    if isinstance(t, Raw):
        return [Leaf(path, {'enc': 'raw', 'bytes': t.size})]
    if isinstance(t, Array):
        out = []
        for i in range(t.count):
            out += leaves_of_type(path + (i,), t.elem)
        return out
    if isinstance(t, Sub):
        return leaves_of_struct(path, t.struct)
    raise TypeError(t)


def leaves_of_struct(path: Tuple[Any, ...], st: Struct) -> List[Leaf]:
    out = []
    for f in st.fields:
        if f.cls == 'excluded':
            continue
        if f.cls == 'thinker':
            out += leaves_of_type(path + ('function',), Fn())
            continue
        if f.cls == 'list':
            name = HEAD_FIELDS.get((st.name, f.name))
            if name:
                out.append(list_leaf(path + (f.name,), name))
            elif (st.name, f.name) not in LINK_FIELDS:
                raise ValueError('%s.%s: a list field the port layout does '
                                 'not know' % (st.name, f.name))
            continue
        out += leaves_of_type(path + (f.name,), f.type)
    return out


def kind_leaves(kind: str, structs: Dict[str, Struct]) -> List[Leaf]:
    """The canonical fields of a kind (upstream.Reader's objects)."""
    k = schema.KINDS[kind]
    if kind == 'removed':
        return leaves_of_type(('function',), Fn())
    if kind == 'blocklink':
        return [list_leaf(('things',), 'block_things')]
    if kind == 'linebuf':
        return leaves_of_type(('line',), Ref(('line',)))
    if kind in ('blockmap', 'reject'):
        return [Leaf(('bytes',), {'enc': 'blob', 'max': 16384}),
                Leaf(('lump',), {'enc': 'int', 'bytes': 2,
                                 'signed': False})]
    out = leaves_of_struct((), structs[k.struct])
    if kind == 'mobj':
        out.append(Leaf(('free',), {'enc': 'int', 'bytes': 1,
                                    'signed': False}))
        for leaf in out:
            if leaf.path == ('touching_sectorlist',):
                leaf.when = ('free', 0)
    if kind == 'secnode':
        for leaf in out:
            leaf.when = ('free', 0)
        out.append(Leaf(('free',), {'enc': 'int', 'bytes': 1,
                                    'signed': False}))
    if kind == 'line':
        out.append(Leaf(('gstamp',), {'enc': 'int', 'bytes': 2,
                                      'signed': False}))
    if kind == 'sector':
        out.append(Leaf(('flood',), {'enc': 'seq', 'pool': 'flood'}))
        out.append(Leaf(('flood_sb',), {'enc': 'seq', 'pool': 'flood'}))
    return out


def global_leaves(structs: Dict[str, Struct]) -> List[Leaf]:
    out = []
    for unit, labels in list(schema.GLOBALS.items()) + list(
            schema.EXTERNAL_GLOBALS.items()):
        for label, text in labels.items():
            name = '%s:%s' % (unit, label)
            if text.startswith('cache:'):
                text = text[6:]
            if text.startswith('object:'):
                continue
            if text.startswith('list:'):
                out.append(list_leaf((name,), GLOBAL_LISTS[name]))
                continue
            if text.startswith('table:'):
                out.append(Leaf((name,), {'enc': 'table',
                                          'kind': text[6:]}))
                continue
            if text in structs:
                out += leaves_of_struct((name,), structs[text])
            else:
                out += leaves_of_type((name,), schema.field_type(text,
                                                                 structs))
    return out


# ---- native-v1: the first native layout -------------------------------------

# Capacities. Where upstream has a limit the port keeps it; the rest are
# the port's own choice, above the largest level of DOOM1.WAD's episode 1
# (measured on the coverage dumps: tools/bridge/README.md).
def capacities(c) -> Dict[str, Tuple[int, str]]:
    mm = c.memmap
    return {
        'mobj': (c.local('p_spawn65.s', 'TP_MAX'), 'TP_MAX (p_spawn65.s)'),
        'zmobj': (64, 'port choice (upstream: the zone)'),
        'sector': (c.local('p_sight65.s', 'SEC_MAX'),
                   'SEC_MAX (p_sight65.s: a seg keeps a byte)'),
        'line': ((mm['MM_VIEWSAVE'] - mm['MM_GSTAMP']) // 2,
                 'GSTAMP words (memmap.inc)'),
        'side': (2048, 'port choice (E1: 805)'),
        'subsector': (c.local('p_sight65.s', 'SS_MAX'),
                      'SS_MAX (p_sight65.s)'),
        'seg': (mm['MM_SEGVTX_MAX'], 'MM_SEGVTX_MAX (memmap.inc)'),
        'node': (c.local('p_sight65.s', 'NODE_MAX'),
                 'NODE_MAX (p_sight65.s)'),
        'blocklink': (4096, 'port choice (E1: 2,912 blocks)'),
        'linebuf': (4096, 'port choice (E1: 1,719)'),
        'secnode': (1024, 'port choice (E1: 448)'),
        'plat': (64, 'port choice'), 'door': (64, 'port choice'),
        'floor': (64, 'port choice'), 'lightflash': (64, 'port choice'),
        'strobe': (64, 'port choice'), 'glow': (64, 'port choice'),
        'scroll': (64, 'port choice'), 'removed': (64, 'port choice'),
        'player': (1, 'one player'),
        'button': (c['CONST_MAXBUTTONS'], 'MAXBUTTONS (offsets.inc)'),
        'blockmap': (1, 'the level\'s lump'),
        'reject': (1, 'the level\'s lump'),
    }


FLOOD_POOL = 8192       # entries: port choice (E1 sums of linecount: 4,000)
MAIN_GLOBALS = (0x1a80, 0x2000)   # MEMORY_MAP.md 3.3: hot game globals
AUX_FIRST_BANK = 0x40
AUX_SPAN = (0x0200, 0xc000)       # of each aux bank: RAMRD/RAMWRT pages


class Allocator:
    def __init__(self, bank: int):
        self.bank = bank
        self.at = AUX_SPAN[0]

    def take(self, size: int) -> int:
        if size > AUX_SPAN[1] - AUX_SPAN[0]:
            raise ValueError('%d bytes do not fit a bank' % size)
        if self.at + size > AUX_SPAN[1]:
            self.bank += 1
            self.at = AUX_SPAN[0]
        address = self.bank << 16 | self.at
        self.at += size
        return address


def native_v1(structs: Dict[str, Struct], constants, symbols) -> Manifest:
    """The first native layout: every kind as byte planes (structure of
    arrays) in RamWorks banks from $40, the globals in main $1A80-$1FFF.
    A stand-in for the manifest the port's build will write."""
    caps = capacities(constants)
    kinds_json: Dict[str, Any] = {}
    lists_json = {name: {'elements': list(d.elements),
                         'prev': d.prev is not None}
                  for name, d in schema.LISTS.items()}
    alloc = Allocator(AUX_FIRST_BANK)
    all_kinds = [k for k in schema.KINDS if k not in
                 ('state', 'lump', 'symbol', 'table')]
    for kind in all_kinds:
        cap, why = caps[kind]
        leaves = kind_leaves(kind, structs)
        for name, d in schema.LISTS.items():
            if kind in d.elements:
                enc = {'enc': 'ref', 'codes': [[k, None] for k in
                                               d.elements], 'offset': False}
                leaves.append(Leaf(('@%s.next' % name,), enc))
                if d.prev is not None:
                    leaves.append(Leaf(('@%s.prev' % name,), enc))
        count = [alloc.take(1), alloc.take(1)]
        for leaf in leaves:
            if leaf.enc['enc'] == 'blob':
                leaf.planes = [alloc.take(cap), alloc.take(cap),
                               alloc.take(leaf.enc['max'])]
            else:
                leaf.planes = [alloc.take(cap) for _ in range(leaf.width)]
        kinds_json[kind] = {'capacity': cap, 'why': why,
                            'count': [port_text(p) for p in count],
                            'leaves': [x.to_json() for x in leaves]}
    pool = {'capacity': FLOOD_POOL, 'codes': [['sector', None]],
            'count': [port_text(alloc.take(1)), port_text(alloc.take(1))],
            'planes': [port_text(alloc.take(FLOOD_POOL)) for _ in range(3)]}
    gl = global_leaves(structs)
    at = MAIN | MAIN_GLOBALS[0]
    for leaf in gl:
        leaf.planes = []
        for _ in range(leaf.width):
            if at >= (MAIN | MAIN_GLOBALS[1]):
                leaf.planes.append(alloc.take(1))
            else:
                leaf.planes.append(at)
                at += 1
    symbol_list = sorted(lb.ref for f in symbols.fragments
                         if f.kind == 'rodata' for lb in f.labels)
    data = {
        'format': FORMAT, 'name': 'native-v1',
        'note': 'The first native layout of the game state (bridge v1): '
                'structure of arrays, one byte plane per byte of each '
                'field, in RamWorks banks from $%02X; the globals in main '
                '$%04X-$%04X. Generated by tools/bridge/layout.py until '
                'the port\'s build writes its own.' % (
                    AUX_FIRST_BANK, MAIN_GLOBALS[0], MAIN_GLOBALS[1] - 1),
        'symbols': symbol_list,
        'tables': list(n for n in constants.memmap
                       if constants.memmap[n] > 0xffff),
        'lists': lists_json,
        'pools': {'flood': pool},
        'kinds': kinds_json,
        'globals': {'leaves': [x.to_json() for x in gl]},
        'banks': [AUX_FIRST_BANK, alloc.bank],
    }
    return Manifest(data)
