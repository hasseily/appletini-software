"""The level load's static tables on the host, as upstream's groupLines
and P_InitFlood make them (p_setup65.s:259-404, :742-1102). lstore.py
writes them into each map's LVG1:

    line tables  per sector, its lines (each line in its front sector's,
                 then its back sector's when that differs, in line order;
                 the tables in sector order)
    flood        per sector, the other sectors of its two-sided lines with
                 two sectors: the lines walked from the last to the first;
                 for each, the back into the front's list then the front
                 into the back's; without ML_SOUNDBLOCK appended up from
                 the first entry, with it put down from the end
"""

import struct
import sys
from pathlib import Path
from typing import List, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import maplumps as ML  # noqa: E402

ML_TWOSIDED, ML_SOUNDBLOCK = 4, 64
NO_INDEX = 0xFFFF


class DeriveError(Exception):
    pass


# ---------------------------------------------------------------------------
# GROUP (groupLines)
# ---------------------------------------------------------------------------

class Group:
    def __init__(self, game: ML.GameMap):
        lines = game.lines
        sides = game.sides
        nsec = len(game.lumps['SECTORS']) // 12
        tables: List[List[int]] = [[] for _ in range(nsec)]
        for i, ln in enumerate(lines):
            front = sides[ln[4]][5] & 0xFF
            back = sides[ln[5]][5] & 0xFF if ln[5] != NO_INDEX else None
            tables[front].append(i)
            if back is not None and back != front:
                tables[back].append(i)
        self.tables = tables
        self.entries = sum(len(t) for t in tables)


# ---------------------------------------------------------------------------
# FLOOD (P_InitFlood)
# ---------------------------------------------------------------------------

class Flood:
    def __init__(self, game: ML.GameMap, group: Group):
        lines, sides = game.lines, game.sides
        nsec = len(group.tables)
        self.free: List[List[int]] = [[] for _ in range(nsec)]
        self.block: List[List[int]] = [[] for _ in range(nsec)]   # fill
        for i in range(len(lines) - 1, -1, -1):
            ln = lines[i]
            if ln[5] == NO_INDEX:
                continue
            front = sides[ln[4]][5] & 0xFF
            back = sides[ln[5]][5] & 0xFF
            if front == back or not ln[6] & ML_TWOSIDED:
                continue
            target = self.block if ln[6] & ML_SOUNDBLOCK else self.free
            target[front].append(back)
            target[back].append(front)
        self.rooms = [len(t) for t in group.tables]
        for s in range(nsec):
            if len(self.free[s]) + len(self.block[s]) > self.rooms[s]:
                raise DeriveError('sector %d: its flood entries pass its '
                                  'room' % s)

    def layout(self) -> Tuple[bytes, bytes]:
        """FLIDX (8 bytes a sector: first, end of the free part, first of
        the block part, end) and the entries (a byte each), the rooms in
        sector order."""
        idx = bytearray()
        ent = bytearray()
        for s in range(len(self.rooms)):
            first = len(ent)
            room = self.rooms[s]
            region = bytearray(room)
            for k, other in enumerate(self.free[s]):
                region[k] = other
            for k, other in enumerate(self.block[s]):
                region[room - 1 - k] = other
            ent += region
            idx += struct.pack('<HHHH', first, first + len(self.free[s]),
                               first + room - len(self.block[s]),
                               first + room)
        return bytes(idx), bytes(ent)
