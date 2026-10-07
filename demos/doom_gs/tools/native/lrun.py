#!/usr/bin/env python3
"""The level load's build (docs/LEVELS.md): the
link of src/native/level.mk (lcard) read back, the load phase's image
in bank LCODE, and the store's bank files lstore.py wrote.
"""

import json
import sys
from pathlib import Path
from typing import List, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, lstore, render_check as RC  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
LEVELS = BUILD / 'native' / 'levels'
OBJ = LEVELS / 'obj'
A2VM = BUILD / 'a2vm' / 'a2vm'


class RunError(Exception):
    pass


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------

def load_build(obj: Path, name: str) -> RC.Build:
    return RC.load_build(obj, name)


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

def store_files() -> List[Path]:
    meta = json.loads((lstore.STORE / 'store.json').read_text())
    return [lstore.STORE / n for n in sorted(meta['files'])]


def load_image(b: RC.Build) -> List[Tuple[int, int, int, bytes]]:
    """The load phase's image in bank LCODE at W's addresses: MATHW and
    AUXW from $6000, LOADW from $6600."""
    w = (b.obj / ('%s.w' % b.name)).read_bytes()
    lw = (b.obj / ('%s.lw' % b.name)).read_bytes()
    start, end = b.segments['LOADW']
    if start != LL.LW_CODE or end >= LL.LW_CODE_END:
        raise RunError('LOADW at $%04X-$%04X' % (start, end))
    return [(1, LL.LCODE, 0x6000, w), (1, LL.LCODE, LL.LW_CODE, lw)]
