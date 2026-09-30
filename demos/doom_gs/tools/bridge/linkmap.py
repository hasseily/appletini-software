"""Symbols of upstream's game from build/linkmap.json (tools/v816).

`Symbols` gives the address of `unit:label` (or a label that only one
unit has), the data fragments with their labels and the size of each
label (up to the next label of its fragment, or the fragment's end), and
the exact label of an address. An address is never matched to the
nearest label: a lookup is exact or it fails.
"""

import bisect
import json
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
LINKMAP = BUILD / 'linkmap.json'
UPSTREAM = BUILD / 'upstream' / 'src' / 'iigs'

# Label prefixes of the include files' constants, which the link map
# keeps with each unit that includes them: not addresses.
CONSTANT_PREFIXES = ('CONST_', 'OFS_', 'SIZEOF_', 'MM_')


class Label(NamedTuple):
    unit: str
    name: str
    address: int
    size: int           # to the next label of its fragment, or its end
    section: str
    kind: str           # the fragment's kind: bss, data, rodata, text

    @property
    def ref(self) -> str:
        return '%s:%s' % (self.unit, self.name)


class Fragment(NamedTuple):
    unit: str
    section: str
    kind: str
    address: int
    size: int
    labels: Tuple[Label, ...]


class SymbolError(KeyError):
    pass


class Symbols:
    def __init__(self, linkmap: Optional[Dict] = None,
                 path: Path = LINKMAP):
        if linkmap is None:
            linkmap = json.loads(Path(path).read_text())
        game = linkmap['game']
        self.units: Dict[str, Dict[str, int]] = game['units']
        self.sections = game['sections']
        self.fragments: List[Fragment] = []
        by_address: Dict[int, List[Label]] = {}
        for f in game['fragments']:
            if f['address'] is None or not f['size']:
                continue
            items = sorted(f['labels'].items(), key=lambda kv: kv[1])
            labels = []
            for i, (name, value) in enumerate(items):
                end = items[i + 1][1] if i + 1 < len(items) else \
                    f['address'] + f['size']
                label = Label(f['unit'], name, value, end - value,
                              f['section'], f['kind'])
                labels.append(label)
                by_address.setdefault(value, []).append(label)
            self.fragments.append(Fragment(
                f['unit'], f['section'], f['kind'], f['address'], f['size'],
                tuple(labels)))
        self.fragments.sort(key=lambda f: f.address)
        self._starts = [f.address for f in self.fragments]
        self.by_address = by_address

    def __getitem__(self, ref: str) -> int:
        return self.address(ref)

    def address(self, ref: str) -> int:
        """`unit:label` or a label that one unit alone has."""
        unit, _, name = ref.rpartition(':')
        if unit:
            value = self.units.get(unit, {}).get(name)
            if not isinstance(value, int):
                raise SymbolError('%s has no label %s' % (unit, name))
            return value
        found = {labels[name] for labels in self.units.values()
                 if isinstance(labels.get(name), int)}
        if len(found) != 1:
            raise SymbolError('%s: %d values' % (name, len(found)))
        return found.pop()

    def constant(self, name: str) -> int:
        return self.address(name)

    def label(self, ref: str) -> Label:
        """The label `unit:label` with its size (data or code)."""
        address = self.address(ref)
        unit, _, name = ref.rpartition(':')
        for label in self.by_address.get(address, []):
            if label.name == name and (not unit or label.unit == unit):
                return label
        raise SymbolError('%s is not a label of a placed fragment' % ref)

    def fragment_at(self, address: int) -> Optional[Fragment]:
        """The fragment holding the address (fragments do not overlap)."""
        i = bisect.bisect_right(self._starts, address) - 1
        if i >= 0:
            f = self.fragments[i]
            if f.address <= address < f.address + f.size:
                return f
        return None

    def exact(self, address: int) -> List[Label]:
        """The labels at exactly this address (never the nearest)."""
        return list(self.by_address.get(address, []))

    def data_fragments(self, units=None) -> Iterator[Fragment]:
        for f in self.fragments:
            if f.kind in ('bss', 'data') and (units is None or
                                              f.unit in units):
                yield f
