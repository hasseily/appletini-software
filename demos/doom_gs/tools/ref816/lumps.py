"""The lumps of DOOM1.WAD by name (read_wad), and the script of the
title loop to the end of its demo (demo_script, tools/native/rendercap.py's
title run).

The WAD is build/upstream/data/DOOM1.WAD (tools/fetch_upstream.py).
"""

import struct
import sys
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import make_image  # noqa: E402

WAD = make_image.BUILD / 'upstream' / 'data' / 'DOOM1.WAD'


def read_wad(path: Path = WAD) -> Dict[str, bytes]:
    """The lumps of a WAD by name (the first of each name)."""
    data = path.read_bytes()
    if data[:4] not in (b'IWAD', b'PWAD'):
        raise ValueError('%s is not a WAD' % path)
    count, directory = struct.unpack_from('<II', data, 4)
    lumps: Dict[str, bytes] = {}
    for i in range(count):
        position, size, name = struct.unpack_from('<II8s', data,
                                                  directory + 16 * i)
        name = name.rstrip(b'\0').decode('latin-1')
        lumps.setdefault(name, data[position:position + size])
    return lumps


def demo_script(map_number: int, limit_seconds: int = 3000) -> str:
    """A script of the title loop that plays the demo to its end: the
    title page, the demo in map `map_number`, its first tic (note
    "demo"), then the end of the playback (note "demo-end")."""
    return '\n'.join((
        '# The title loop to the end of its demo (tools/ref816/lumps.py).',
        'wait d_main65.s:pagedrawn == 1 within 90s   # the title page',
        'wait _g_demoplayback == 1 within 60s',
        'wait _g_gamestate == 0 within 10s       # GS_LEVEL',
        'wait _g_gamemap == %d within 1           # the demo\'s map'
        % map_number,
        'at +1t note demo',
        'wait _g_demoplayback == 0 within %ds   # its end' % limit_seconds,
        'note demo-end',
        'stop', ''))
