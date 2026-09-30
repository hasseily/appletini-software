#!/usr/bin/env python3
"""Log every call of upstream's math routines in the coverage runs.

Usage:  python3 tools/native/mathcap.py [SCRIPT...] [--jobs N]

Runs each coverage script (default: newgame, title, tour, viewsize) on
ref816's machine through build/native/math/mathref (tools/native/mathref.c,
built by `make -C tools/native`), with the spec of tools/native/mathdefs.py,
into build/native/math/captures/SCRIPT/: a log a routine (NAME.bin), the
entry state of its first call (NAME.entry), the RAM at the run's end
(base.ram), and summary.txt. The scripts are compiled as
tools/ref816/run_script.py compiles them; the release image and its disk
are those of tools/ref816 (build/ref816/memory.img, disk.hdv), read only.

The vendor divides are logged for their inputs only: the port's divides are
checked against C semantics, never against the vendor's results.

At most 2 runs at a time (--jobs), under nice.
"""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import mathdefs  # noqa: E402
from ref816 import run_script, script, title  # noqa: E402

MATHREF = mathdefs.MATH / 'mathref'
CAPTURES = mathdefs.MATH / 'captures'
SCRIPTS = ('newgame', 'title', 'tour', 'viewsize')
LIMIT_SECONDS = 900


def build_tool() -> None:
    subprocess.run(['nice', '-n', '10', 'make', '-s', '-C', str(HERE)],
                   check=True)


def capture(name: str, out: Path = CAPTURES) -> Path:
    """Run one script; returns its directory."""
    path = run_script.script_path(name)
    symbols = script.Symbols(json.loads(mathdefs.LINKMAP.read_text()))
    program = script.compile_script(path.read_text(), symbols, path.name)
    directory = out / path.stem
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob('*'):
        old.unlink()
    (directory / 'input.txt').write_text(program)
    (directory / 'spec.txt').write_text(mathdefs.capture_spec())
    command = ['nice', '-n', '10', str(MATHREF), 'capture',
               str(title.MEMORY), str(title.DISK),
               str(directory / 'input.txt'),
               str(script.frames(LIMIT_SECONDS)),
               str(directory / 'spec.txt'), str(directory)]
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode:
        raise RuntimeError('mathref capture %s: %s%s' % (
            name, result.stderr, (directory / 'summary.txt').read_text()
            if (directory / 'summary.txt').exists() else ''))
    return directory


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('scripts', nargs='*', default=list(SCRIPTS))
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args(argv)
    if not (title.MEMORY.exists() and title.DISK.exists()):
        print('build/ref816 has no memory.img or disk.hdv: run '
              'python3 tools/ref816/make_image.py first', file=sys.stderr)
        return 1
    build_tool()
    with ThreadPoolExecutor(max_workers=max(1, min(args.jobs, 2))) as pool:
        for directory in pool.map(capture, args.scripts):
            print(directory)
            print((directory / 'summary.txt').read_text())
    return 0


if __name__ == '__main__':
    sys.exit(main())
