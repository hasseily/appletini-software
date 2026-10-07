"""Symbols of upstream's game from build/linkmap.json (tools/v816).

`Symbols` gives the address of `unit:label` (or a label that only one
unit has), the fragments with their labels, and each label with its size
(up to the next label of its fragment, or the fragment's end).
"""

import json
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
LINKMAP = BUILD / 'linkmap.json'
UPSTREAM = BUILD / 'upstream' / 'src' / 'iigs'


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
        self.by_address = by_address

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

    def label(self, ref: str) -> Label:
        """The label `unit:label` with its size (data or code)."""
        address = self.address(ref)
        unit, _, name = ref.rpartition(':')
        for label in self.by_address.get(address, []):
            if label.name == name and (not unit or label.unit == unit):
                return label
        raise SymbolError('%s is not a label of a placed fragment' % ref)
