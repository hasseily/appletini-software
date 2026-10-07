"""The leaves of a layout manifest: a leaf is one value of an object, its
"path" and its encoding "enc"; `Leaf.width` is the number of byte planes
the encoding needs:

    int    {"bytes": n, "signed": b}: n planes, little-endian
    ref    {"codes": [...], "offset": b}: tag, id low, id high (and
           offset low, offset high when "offset")
    enum   one plane, the index
    raw    {"bytes": n}: n planes of bytes
    list   the head of a list: a ref (3 planes), or a handle when it
           carries "ranges" ("bytes", default 2)
    seq    start low, start high, length low, length high into a pool
    table  the base of an object table: no planes
    blob   length low, length high, then one address
    handle {"bytes": 1 or 2, "ranges": [...]}: one value of `bytes` planes
    sxbyte one plane, a signed byte
    bit    one plane, the base of a bitmap
"""

from typing import Any, Dict, Sequence


class Leaf:
    def __init__(self, path: Sequence[Any], enc: Dict[str, Any]):
        self.path = tuple(path)
        self.enc = dict(enc)

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
            return self.enc.get('bytes', 2) if 'ranges' in self.enc else 3
        if e == 'seq':
            return 4
        if e == 'table':
            return 0
        if e == 'blob':
            return 3
        if e == 'handle':
            return self.enc['bytes']
        if e in ('sxbyte', 'bit'):
            return 1
        raise ValueError(e)
