"""Addresses of the game as places of its link map (build/linkmap.json,
written by tools/v816/imgmatch.py): the section fragment that holds an
address, its source file, and the nearest label at or below it.

The unit cal_integer.s is the vendor's runtime, whose licence keeps
anything derived from it out of the repository. Its places have no
section, file or label of their own: all of them are VENDOR, so that a
report written outside build/ names none of its code.

Banks get a short description from the link map too: the data sections
placed in them and the fixed data addresses of the game's memory map (the MM_
equates of upstream's memmap.inc, which every unit that includes it
carries), with the ranges that the memory map gives as bank numbers.
"""

import bisect
from typing import Dict, List, NamedTuple, Optional, Tuple

VENDOR_UNIT = 'cal_integer.s'
VENDOR = 'vendor runtime'
OUTSIDE = 'outside the image'
# Bank ranges of the memory map, as (first, last or end, what it is, end
# exclusive).
BANK_RANGES = (('MM_ZONE_FIRST', 'MM_ZONE_LAST', 'zone', False),
               ('MM_WINDOW', 'MM_WINDOW_END', 'level window', True))


class Place(NamedTuple):
    section: str            # the linker section, VENDOR or OUTSIDE
    unit: str               # the source file, VENDOR or OUTSIDE
    label: Optional[str]    # the nearest label at or below, if any
    offset: int             # from the label (or the fragment's start)
    address: int

    def __str__(self) -> str:
        if self.unit == OUTSIDE:
            return '$%06X (%s)' % (self.address, OUTSIDE)
        if self.unit == VENDOR:
            return VENDOR
        return '%s+%d' % (self.function, self.offset)

    @property
    def function(self) -> str:
        """The place without its offset: "unit:label", or VENDOR."""
        if self.unit in (VENDOR, OUTSIDE):
            return self.unit
        return '%s:%s' % (self.unit, self.label or '(%s)' % self.section)


class CodeMap:
    def __init__(self, linkmap: Dict):
        game = linkmap['game']
        self.fragments = sorted(
            (f for f in game['fragments']
             if f['address'] is not None and f['size'] > 0),
            key=lambda f: f['address'])
        self.starts = [f['address'] for f in self.fragments]
        # Labels of each fragment: their addresses in order, and a name
        # for each (the first in name order, where several share an
        # address, so that places are stable).
        self.labels: List[Tuple[List[int], List[str]]] = []
        for fragment in self.fragments:
            by_address: Dict[int, str] = {}
            for name in sorted(fragment['labels']):
                by_address.setdefault(fragment['labels'][name], name)
            ordered = sorted(by_address.items())
            self.labels.append(([a for a, _ in ordered],
                                [n for _, n in ordered]))
        self.sections = game['sections']
        # Data sections only: the code sections interleave in banks
        # $03-$05, and a bank's code is better told by its places.
        code = {f['section'] for f in self.fragments if f['kind'] == 'text'}
        self.data_sections = {name: span for name, span
                              in game['sections'].items()
                              if name not in code}
        # The memory map's equates come from an include: every unit that
        # includes it has them, where a label of one unit that happens
        # to start with MM_ is in that unit only.
        seen: Dict[str, List[int]] = {}
        for labels in game['units'].values():
            for name, value in labels.items():
                if name.startswith('MM_') and isinstance(value, int):
                    seen.setdefault(name, []).append(value)
        self.equates = {name: values[0] for name, values in seen.items()
                        if len(values) > 1 and len(set(values)) == 1}

    def place(self, address: int) -> Place:
        i = bisect.bisect_right(self.starts, address) - 1
        if i < 0 or address >= self.starts[i] + self.fragments[i]['size']:
            return Place(OUTSIDE, OUTSIDE, None, 0, address)
        fragment = self.fragments[i]
        if fragment['unit'] == VENDOR_UNIT:
            return Place(VENDOR, VENDOR, None, 0, address)
        addresses, names = self.labels[i]
        j = bisect.bisect_right(addresses, address) - 1
        if j < 0:
            return Place(fragment['section'], fragment['unit'], None,
                         address - fragment['address'], address)
        return Place(fragment['section'], fragment['unit'], names[j],
                     address - addresses[j], address)

    def bank(self, bank: int) -> str:
        """What the memory map puts in `bank`, from the link map."""
        parts = []
        for first, last, what, exclusive in BANK_RANGES:
            if first in self.equates and last in self.equates:
                end = self.equates[last] + (0 if exclusive else 1)
                if self.equates[first] <= bank < end:
                    parts.append(what)
        parts += sorted(name for name, span in self.data_sections.items()
                        if span['first'] >> 16 <= bank <= span['last'] >> 16)
        parts += sorted(name for name, value in self.equates.items()
                        if value > 0xffff and value >> 16 == bank and
                        not name.endswith('_END'))
        return ', '.join(parts)
