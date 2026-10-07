"""The 2D images' builds (src/native/m11.mk, play.mk): a build's labels,
segments and MEMORY areas (lrun.load_build and the link's map), and its
stored pages as records in its code bank (s2layout.image_banks(), at W's
addresses)."""

import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import lrun, s2layout as S  # noqa: E402


class Build(NamedTuple):
    obj: Path
    name: str
    image: str                  # s2layout's image whose room it uses
    labels: Dict[str, int]
    segments: Dict[str, Tuple[int, int]]
    areas: Dict[str, Tuple[int, str]]   # MEMORY area: (start, file suffix)


def load_build(obj: Path, name: str, image: str) -> Build:
    b = lrun.load_build(obj, name)
    areas = {}
    cfg = (obj / (name + '.cfg')).read_text()
    for m in re.finditer(r'^\s*(\w+):\s*start = \$([0-9A-F]+), size = '
                         r'\$[0-9A-F]+,(?: type = \w+,)? file = '
                         r'"%O\.(\w+)"', cfg, re.M):
        areas[m.group(1)] = (int(m.group(2), 16), m.group(3))
    return Build(obj, name, image, b.labels, b.segments, areas)


Record = Tuple[int, int, int, bytes]


def area_bytes(b: Build, area: str) -> bytes:
    path = b.obj / ('%s.%s' % (b.name, b.areas[area][1]))
    return path.read_bytes() if path.exists() else b''


def stored_extent(b: Build) -> Tuple[int, int]:
    """The image's stored bytes [lo, end): MATHW and AUXW from $6000, then
    its room's segments."""
    ends = [b.segments[s][1] + 1 for s in ('MATHW', 'AUXW') +
            S.IMG_SEGMENTS if s in b.segments]
    return S.MATHW_LO, max(ends)


def image_bank(b: Build) -> int:
    return S.image_banks()[b.image]


def image_records(b: Build, bank: Optional[int] = None) -> List[Record]:
    """The image's stored pages in its code bank at W's addresses."""
    bank = image_bank(b) if bank is None else bank
    out = []
    for area in ('W', 'IMG'):
        data = area_bytes(b, area)
        if data:
            out.append((1, bank, b.areas[area][0], data))
    return out


def runs_of(lo: int, end: int) -> List[Tuple[int, int]]:
    """far_pload's runs for [lo, end): (first page, count) pieces of at
    most 255 pages."""
    first, count = S.page_run(lo, end)
    out = []
    while count:
        n = min(count, 255)
        out.append((first, n))
        first, count = first + n, count - n
    return out
