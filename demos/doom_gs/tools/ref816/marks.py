"""The log of marks and notes that ref816 writes (--mark, --marks), and
the frame rate of the game between two notes.

A line is "mark ADDRESS CLOCK CYCLES INSTRUCTIONS" when the CPU reached a
marked address (the counts are those before the instruction there),
"note NAME CLOCK CYCLES INSTRUCTIONS" for a note of the input, and the
last one "end - CLOCK CYCLES INSTRUCTIONS" for the end of the run. The clock
is in master clocks of 14.31818 MHz, so seconds of machine time whatever
the CPU rate.

A frame of the game, here, is one pass of its main loop that drew the 3D
view: from one call of R_RenderPlayerView to the next, the tics run in
between included. Its cost is the instructions and cycles between the
two calls.
"""

import statistics
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


class Interval(NamedTuple):
    start: str          # the notes at its ends
    end: str
    seconds: float      # of machine time
    rendered: int       # 3D views drawn
    frames_per_second: float
    frames_measured: int        # whole frames inside the interval
    median_instructions: Optional[float]
    median_cycles: Optional[float]


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


def notes(entries: Sequence[Entry]) -> List[Entry]:
    return [e for e in entries if e.kind == 'note']


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


def interval(entries: Sequence[Entry], start: Entry, end: Entry,
             render: int) -> Interval:
    """The frames of the game between the notes `start` and `end`;
    `render` is the address of R_RenderPlayerView."""
    inside = [e for e in at(entries, render)
              if start.clock <= e.clock <= end.clock]
    seconds = (end.clock - start.clock) / MASTER_HZ
    instructions = [b.instructions - a.instructions
                    for a, b in zip(inside, inside[1:])]
    cycles = [b.cycles - a.cycles for a, b in zip(inside, inside[1:])]
    return Interval(
        start.what, end.what, seconds, len(inside),
        len(inside) / seconds if seconds else 0.0, len(cycles),
        statistics.median(instructions) if instructions else None,
        statistics.median(cycles) if cycles else None)


def intervals(entries: Sequence[Entry], render: int) -> List[Interval]:
    """An interval between each note and the next."""
    marked = notes(entries)
    return [interval(entries, a, b, render)
            for a, b in zip(marked, marked[1:])]
