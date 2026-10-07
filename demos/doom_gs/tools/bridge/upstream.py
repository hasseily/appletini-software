"""Upstream's structures, built once per link map: `Schema().structs`
(schema.py's structures with offsets.inc's offsets) and `Schema().c`
(the include files' constants)."""

from typing import Optional

from bridge import schema
from bridge.linkmap import Symbols


class Schema:
    def __init__(self, symbols: Optional[Symbols] = None):
        self.symbols = symbols or Symbols()
        self.c = schema.Constants(self.symbols)
        self.structs = schema.build_structs(self.c)
