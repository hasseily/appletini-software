#!/usr/bin/env python3
"""Lumps of DOOM1.WAD placed in the game's WAD on ref816 (--wad, --lump),
so that the title loop plays DEMO1 or DEMO2 instead of DEMO3.

Usage:  python3 tools/ref816/lumps.py DEMO1 [--entry DEMO3] [--dest 7E0000]
        python3 tools/ref816/lumps.py DEMO1 --play [--limit SECONDS]

The release keeps a resident WAD in RAM at MM_WAD ($10:0000; upstream's
w_wad65.s uses each lump in place at MM_WAD + its offset) whose directory
names DEMO3 only, with the lumps M_DOOM and TEXTURE1 after it, so a longer
demo cannot be written over it. The machine's --lump NAME:DEST:FILE
(tools/ref816/inject.h) puts a lump's bytes at DEST and points the
directory entry NAME there. The title loop asks for "demo3" by name
(d_main65.s), so DEMO1 placed under the entry DEMO3 plays in its place.

The default DEST is $7E:0000. In 8 MB mode upstream's level loader takes
its window banks below MM_MUSBANK ($6A) and the songs follow from there
(w_level65.s, memmap.inc); at the end of all four coverage scripts banks
$79-$7F hold nothing but the two bytes of the loader's memory probe at
$bb:8000 (measured with --dump-ram). The machine refuses a place that is
not zero, and a lump across a bank. tests/test_ref816_lump.py checks that
DEMO3 placed at $7E:0000 under its own entry gives the same run, mark for
mark, as the release's own.

--play runs the title loop with the lump to the demo's end (demo_script)
and prints the run's report, with the demo's header and the game tics
from its first to its end marker (_g_gametic at the first G_Ticker after
the note "demo", less the tic before the note, and at the call of
G_CheckDemoStatus).

The WAD is build/upstream/data/DOOM1.WAD (tools/fetch_upstream.py).
"""

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import dumps, make_image, run_script, script, \
    title  # noqa: E402

WAD = make_image.BUILD / 'upstream' / 'data' / 'DOOM1.WAD'
OUT = make_image.OUT_DIR / 'lumps'
ENTRY = 'DEMO3'                 # the directory entry the title loop plays
DEST = 0x7e0000
WAD_SYMBOL = 'MM_WAD'
# A demo lump: version, skill, episode, map, then the options (13 bytes
# in all for version 1.9: deathmatch, respawn, fast, nomonsters,
# consoleplayer, 4 players), 4 bytes a tic, and 0x80 at the end.
DEMO_HEADER = 13
DEMO_TIC = 4
DEMO_END = 0x80


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


def demo_info(lump: bytes) -> Dict[str, int]:
    """Skill, episode, map and tics of a demo lump (version 1.9)."""
    if len(lump) < DEMO_HEADER + 1 or lump[-1] != DEMO_END:
        raise ValueError('not a demo lump of version 1.9')
    return {'version': lump[0], 'skill': lump[1], 'episode': lump[2],
            'map': lump[3],
            'tics': (len(lump) - DEMO_HEADER - 1) // DEMO_TIC}


def wad_address(symbols: script.Symbols) -> int:
    return symbols.address(WAD_SYMBOL)


def options(name: str, symbols: script.Symbols, entry: str = ENTRY,
            dest: int = DEST, out: Path = OUT,
            wad: Path = WAD) -> List[str]:
    """The machine's options that place lump `name` of the WAD at `dest`
    under the directory entry `entry` (the lump is written to OUT)."""
    lump = read_wad(wad)[name]
    out.mkdir(parents=True, exist_ok=True)
    path = out / (name + '.lmp')
    path.write_bytes(lump)
    return ['--wad', '%06X' % wad_address(symbols),
            '--lump', '%s:%06X:%s' % (entry, dest, path)]


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


def play(name: str, limit_seconds: int = 3000, dest: int = DEST,
         runs: Path = run_script.RUNS) -> Dict:
    """Run the title loop with lump `name` (a demo) placed as DEMO3, to
    the demo's end; the run's report with the demo's header and the
    gametic at the end."""
    with open(str(make_image.LINKMAP)) as handle:
        symbols = script.Symbols(json.load(handle))
    lump = read_wad()[name]
    info = demo_info(lump)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ('play-%s.script' % name.lower())
    path.write_text(demo_script(info['map'], limit_seconds))
    stream = OUT / ('play-%s.stream' % name.lower())
    extra = options(name, symbols, dest=dest) + ['--dump-stream',
                                                 str(stream)]
    # _g_gametic at the first G_Ticker after the note "demo" and when the
    # demo reader meets the end marker.
    for routine in ('G_Ticker', 'G_CheckDemoStatus'):
        extra += ['--dump-at', dumps.resolve(
            'pc=%s,after=demo,hits=1,ranges=_g_gametic:4' % routine,
            symbols)]
    report = run_script.run(path, limit_seconds=limit_seconds + 120,
                            runs=runs, extra=extra,
                            name='play-' + name.lower())
    ticks = [int.from_bytes(d.data, 'little')
             for d in dumps.Stream(stream).dumps]
    stream.unlink()
    report['demo'] = info
    if len(ticks) == 2:
        # the note comes after the demo's first tic has run
        report['gametic'] = {'first': ticks[0] - 1, 'end': ticks[1],
                             'tics': ticks[1] - ticks[0] + 1}
    else:
        report['problems'].append('the demo did not reach its end marker')
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('lump')
    parser.add_argument('--entry', default=ENTRY)
    parser.add_argument('--dest', type=lambda t: int(t, 16), default=DEST)
    parser.add_argument('--play', action='store_true')
    parser.add_argument('--limit', type=int, default=3000)
    arguments = parser.parse_args(argv)
    if not WAD.exists():
        print('%s is missing: run python3 tools/fetch_upstream.py' % WAD,
              file=sys.stderr)
        return 1
    if not arguments.play:
        with open(str(make_image.LINKMAP)) as handle:
            symbols = script.Symbols(json.load(handle))
        print(' '.join(options(arguments.lump, symbols, arguments.entry,
                               arguments.dest)))
        return 0
    title.build_machine()
    title.ensure_image()
    report = play(arguments.lump, arguments.limit, arguments.dest)
    print(run_script.summary(report))
    print('  demo: %s; gametic: %s' % (report['demo'],
                                        report.get('gametic')))
    return 1 if report['problems'] else 0


if __name__ == '__main__':
    sys.exit(main())
