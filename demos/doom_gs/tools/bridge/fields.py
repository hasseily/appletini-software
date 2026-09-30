"""Field types, structures and the canonical values of the bridge.

A structure (`Struct`) is a list of fields that tile its size exactly:
every byte of a record belongs to one field. A field has a type:

    Int(size, signed)   a number of 1, 2 or 4 bytes, little-endian
    Ref(targets)        a far pointer: 24 bits and a pad byte that must be
                        0; its value is a canonical reference to one of
                        the object kinds `targets` (never a raw address)
    Fn()                a thinker function: 24 bits, one of the declared
                        functions (schema.THINKER_FUNCTIONS) or none
    Array(elem, n)      n values of a type
    Sub(struct)         a structure inside a structure
    Raw(size)           bytes that are not numbers or pointers (names)

and a class that says what the bridge does with it:

    state     canonical, compared
    cache     canonical, round-tripped; a comparison may skip it (an
              upstream cache whose result-neutrality routine tests check)
    table     the base address of an object table: canonical as the
              reference to the table's first object (layout)
    list      a link of a list: not decoded alone; the list machinery
              claims it (upstream.py)
    thinker   the thinker header (links, function, byte 11)
    excluded  not canonical: the reason is the field's `why` and the
              exclusion's name (schema.EXCLUSIONS)

A canonical reference (`R`) names an object by kind and identity, and a
field of it when the pointer points inside the object: R('mobj', 12,
'snext'), R('sector', 3, 'thinglist'), R('lump', 1011, 305).
"""

import json
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple, \
    Union


class Int(NamedTuple):
    size: int
    signed: bool

    @property
    def length(self) -> int:
        return self.size


class Ref(NamedTuple):
    targets: Tuple[str, ...]

    @property
    def length(self) -> int:
        return 4


class Fn(NamedTuple):
    @property
    def length(self) -> int:
        return 3


class Raw(NamedTuple):
    size: int

    @property
    def length(self) -> int:
        return self.size


class Array(NamedTuple):
    elem: Any
    count: int

    @property
    def length(self) -> int:
        return self.elem.length * self.count


class Sub(NamedTuple):
    struct: Any

    @property
    def length(self) -> int:
        return self.struct.size


I8, U8 = Int(1, True), Int(1, False)
I16, U16 = Int(2, True), Int(2, False)
I32, U32 = Int(4, True), Int(4, False)
FIXED = I32
ANGLE = U32


def spec(text: str, targets: Dict[str, Tuple[str, ...]] = None):
    """A type from a short spec: i8 u8 i16 u16 i32 u32 fixed angle, raw:N,
    ref:K1|K2, fn, with *N for arrays (`i16*6`)."""
    base, star, count = text.partition('*')
    if base.startswith('ref:'):
        t = Ref(tuple(base[4:].split('|')))
    elif base.startswith('raw:'):
        t = Raw(int(base[4:]))
    elif base == 'fn':
        t = Fn()
    else:
        t = {'i8': I8, 'u8': U8, 'i16': I16, 'u16': U16, 'i32': I32,
             'u32': U32, 'fixed': FIXED, 'angle': ANGLE}[base]
    return Array(t, int(count)) if star else t


class Field(NamedTuple):
    name: str
    offset: int
    type: Any
    cls: str = 'state'
    why: str = ''          # the exclusion's name for class excluded

    @property
    def end(self) -> int:
        return self.offset + self.type.length


class StructError(ValueError):
    pass


class Struct:
    def __init__(self, name: str, size: int, fields: Sequence[Field],
                 source: str = ''):
        self.name = name
        self.size = size
        self.fields = list(fields)
        self.source = source
        self.by_name = {f.name: f for f in self.fields}
        at = 0
        for f in self.fields:
            if f.offset != at:
                raise StructError('%s: %s at %d, expected %d'
                                  % (name, f.name, f.offset, at))
            at = f.end
        if at != size:
            raise StructError('%s: fields end at %d, size %d'
                              % (name, at, size))

    def field_at(self, offset: int) -> Optional[Field]:
        for f in self.fields:
            if f.offset <= offset < f.end:
                return f
        return None

    def __repr__(self) -> str:
        return 'Struct(%s, %d)' % (self.name, self.size)


class R(NamedTuple):
    """A canonical reference: kind, identity, and a field (a name, or a
    byte offset for byte arrays such as lumps), None for the object."""
    kind: str
    id: Any
    field: Any = None

    def __repr__(self) -> str:
        return '@%s[%s]%s' % (self.kind, self.id,
                              '' if self.field is None else
                              '.%s' % (self.field,))


# ---- JSON form of canonical values ----

def to_json(value: Any) -> Any:
    if isinstance(value, R):
        return {'ref': [value.kind, value.id, value.field]}
    if isinstance(value, dict):
        return {str(k): to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    return value


def from_json(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {'ref'}:
            kind, ident, field = value['ref']
            return R(kind, ident, field)
        return {k: from_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_json(v) for v in value]
    return value


def dumps(value: Any) -> str:
    return json.dumps(to_json(value), indent=1, sort_keys=True)


Value = Union[int, str, None, R, List[Any], Dict[str, Any]]
