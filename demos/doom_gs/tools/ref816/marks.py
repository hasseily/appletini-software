"""The log of marks and notes that ref816 writes (--mark, --marks).

A line is "mark ADDRESS CLOCK CYCLES INSTRUCTIONS" when the CPU reached a
marked address (the counts are those before the instruction there),
"note NAME CLOCK CYCLES INSTRUCTIONS" for a note of the input, and the
last one "end - CLOCK CYCLES INSTRUCTIONS" for the end of the run. The clock
is in master clocks of 14.31818 MHz, so seconds of machine time whatever
the CPU rate.
"""

from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence

MASTER_HZ = 14318180


class Entry(NamedTuple):
    kind: str           # 'mark', 'note' or 'end'
    what: str           # the address (hex) or the note's name
    clock: int
    cycles: int
    instructions: int

    @property
    def seconds(self) -> float:
        return self.clock / MASTER_HZ


def parse(text: str) -> List[Entry]:
    entries = []
    for number, line in enumerate(text.splitlines(), 1):
        words = line.split()
        if len(words) != 5 or words[0] not in ('mark', 'note', 'end'):
            raise ValueError('line %d of the marks: %r' % (number, line))
        entries.append(Entry(words[0], words[1],
                             *(int(word) for word in words[2:])))
    return entries


def read(path: Path) -> List[Entry]:
    return parse(path.read_text())


def at(entries: Sequence[Entry], address: int) -> List[Entry]:
    """The marks of `address`."""
    name = '%06X' % address
    return [e for e in entries if e.kind == 'mark' and e.what == name]


def longest_gap(entries: Sequence[Entry], address: int
                ) -> Optional[Dict[str, float]]:
    """The most CPU cycles between two marks of `address`, or from the
    last one to the end of the run, as {'cycles', 'seconds', 'from'}
    (the machine time of its start); None with no mark. A stuck game
    stops passing through its main loop. Cycles, not seconds, because
    what keeps the loop away for long, a level load, is work for the
    CPU."""
    marks = at(entries, address)
    if not marks:
        return None
    ends = marks + [entries[-1]]
    gaps = [(b.cycles - a.cycles, b.seconds - a.seconds, a.seconds)
            for a, b in zip(ends, ends[1:])]
    cycles, seconds, start = max(gaps, default=(0, 0.0, ends[0].seconds))
    return {'cycles': cycles, 'seconds': seconds, 'from': start}
