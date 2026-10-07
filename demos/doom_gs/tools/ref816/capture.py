"""Upstream's record replay (R_DrawLists) at chosen frames: the frame sets
of the record replay (SETS), the script that runs one (program_for) and the
choice of its frames from a run's log of R_DrawLists' calls (calls,
choose). tools/native/rendercap.py runs them.

    still-1 .. still-3   coverage/newgame.script, the first three frames
                         after the note "still" (standing in E1M1)
    demo-01 .. demo-11   coverage/title.script, eleven frames spread evenly
                         from the note "demo" to "demo-25s" (demo3, E1M7)
    e1m3-1               coverage/tour.script, the first frame after its
                         shot "e1m3" (a note "e1m3" is put after that line
                         of the script, which changes nothing of the run)
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import marks, run_script, script  # noqa: E402

ENTRY = 'r_list65.s:R_DrawLists'
FLUSH = 'r_list65.s:drawAllL'


class Selection(NamedTuple):
    key: str
    script: str
    start: str                  # the note after which frames are chosen
    end: Optional[str]          # and before which (None: the first `count`)
    count: int
    note_after: Optional[str]   # put "note START" after the line with this


SETS = (
    Selection('still', 'newgame', 'still', None, 3, None),
    Selection('demo', 'title', 'demo', 'demo-25s', 11, None),
    Selection('e1m3', 'tour', 'e1m3', None, 1, 'shot e1m3'),
)


# ---- the script and the choice of frames ----

def program_for(selection: Selection, symbols: script.Symbols) -> str:
    path = run_script.script_path(selection.script)
    text = path.read_text()
    if selection.note_after:
        lines = text.splitlines()
        found = [i for i, line in enumerate(lines)
                 if re.search(r'\b%s\b' % re.escape(selection.note_after),
                              line.split('#')[0])]
        if len(found) != 1:
            raise ValueError('%s: %d lines with "%s"' % (
                path.name, len(found), selection.note_after))
        lines.insert(found[0] + 1, 'note %s' % selection.start)
        text = '\n'.join(lines) + '\n'
    return script.compile_script(text, symbols, path.name)


class Hit(NamedTuple):
    hit: int                    # the call of R_DrawLists, from 1
    mark: marks.Entry
    flushes: int                # calls of drawAllL since the call before


def calls(log: Sequence[marks.Entry], entry: int, flush: int
          ) -> Tuple[List[Hit], Dict[str, int]]:
    """Every call of R_DrawLists in the log, and for each note the
    number of calls before it."""
    hits, before, flushes = [], {}, 0
    entry_name, flush_name = '%06X' % entry, '%06X' % flush
    for e in log:
        if e.kind == 'note':
            before[e.what] = len(hits)
        elif e.kind == 'mark' and e.what == flush_name:
            flushes += 1
        elif e.kind == 'mark' and e.what == entry_name:
            hits.append(Hit(len(hits) + 1, e, flushes))
            flushes = 0
    return hits, before


def choose(selection: Selection, hits: Sequence[Hit],
           before: Dict[str, int]) -> List[Hit]:
    """The frames of the selection. The last call of the run is never
    one: the run can end before it returns."""
    hits = hits[:-1]
    if selection.start not in before:
        raise ValueError('no note %s in the run' % selection.start)
    first = before[selection.start]
    if selection.end is None:
        chosen = list(hits[first:first + selection.count])
    else:
        if selection.end not in before:
            raise ValueError('no note %s in the run' % selection.end)
        inside = hits[first:before[selection.end]]
        n = len(inside)
        if n < selection.count:
            chosen = list(inside)
        else:
            chosen = [inside[round(i * (n - 1) / (selection.count - 1))]
                      for i in range(selection.count)]
    if len(chosen) < selection.count:
        raise ValueError('%s: %d frames, not %d' % (
            selection.key, len(chosen), selection.count))
    return chosen
