#!/usr/bin/env python3
"""Boot the release image on ref816 to its title screen, and report.

Usage:  python3 tools/ref816/title.py [--frames N]

Builds the machine (make -C tools/ref816), writes build/ref816/memory.img
with make_image.py when it is missing, runs the game until video frame N
(default 2400: 40 seconds of machine time; the game spends about 30
seconds on its tables and sounds, and the title comes at about 35), and
writes the screen at that frame to build/ref816/shots/title.png. Then it
prints the picture's statistics and the rate of the game clock: the
count of I_GetTime (tmSteps of src/iigs/i_doc65.s, found in the link
map) at two frames, over the machine time between them.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import make_image, shot  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = make_image.OUT_DIR
MACHINE = OUT / 'ref816'
MEMORY = OUT / 'memory.img'
DISK = OUT / 'disk.hdv'
SHOTS = OUT / 'shots'
TITLE_FRAME = 2400
# Two frames after the clock starts (at about 26 s) and before the
# first level load, which stops nothing but is a long stretch of code.
CLOCK_FRAMES = (2400, 3600)


def build_machine() -> Path:
    """Build build/ref816/ref816 with make; return its path."""
    result = subprocess.run(['make', '-C', str(HERE), str(MACHINE)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True)
    if result.returncode:
        raise RuntimeError('make failed:\n' + result.stdout)
    return MACHINE


def ensure_image() -> None:
    """Write memory.img and disk.hdv when they are missing."""
    if not (MEMORY.exists() and DISK.exists()):
        if make_image.main([]):
            raise RuntimeError('make_image.py failed')


def symbol(unit: str, name: str,
           linkmap: Path = make_image.LINKMAP) -> int:
    """The address of label `name` of the game's source `unit`."""
    with open(str(linkmap)) as handle:
        return json.load(handle)['game']['units'][unit][name]


def run_image(image: Path, options: Sequence[str],
              disk: Path = DISK) -> Dict:
    """Run the machine on `image` with `options` and return its final
    state (JSON)."""
    command = [str(MACHINE), str(image), '--disk', str(disk)]
    result = subprocess.run(command + list(options), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode:
        raise RuntimeError('ref816 failed: ' + result.stderr)
    return json.loads(result.stdout)


def run(frames: int, shot_frames: Iterable[int] = (),
        peeks: Iterable[Tuple[int, int]] = (), input_file: Optional[Path] = None,
        shot_dir: Optional[Path] = None, image_dir: Path = OUT,
        options: Sequence[str] = ()) -> Dict:
    """Run the game to `frames` from the memory.img and disk.hdv in
    `image_dir` and return the final state (JSON). `options` go to the
    machine as they are."""
    command = ['--frames', str(frames)]
    for frame in shot_frames:
        command += ['--shot-frame', str(frame)]
    if shot_dir is not None:
        command += ['--shot-dir', str(shot_dir)]
    for address, length in peeks:
        command += ['--peek', '%06X:%d' % (address, length)]
    if input_file is not None:
        command += ['--input', str(input_file)]
    return run_image(image_dir / 'memory.img', command + list(options),
                     image_dir / 'disk.hdv')


def peeked(state: Dict, address: int) -> int:
    """The little-endian number that --peek gave for `address`."""
    return int.from_bytes(bytes.fromhex(state['peek']['%06X' % address]),
                          'little')


def tic_rate(frames: Sequence[int] = CLOCK_FRAMES) -> float:
    """Game tics per second of machine time between two frames."""
    counter = symbol('i_doc65.s', 'tmSteps')
    first, last = (run(frame, peeks=[(counter, 4)]) for frame in frames)
    return ((peeked(last, counter) - peeked(first, counter)) /
            (last['seconds'] - first['seconds']))


def title_picture(frame: int = TITLE_FRAME) -> Tuple[Path, shot.Stats]:
    """Write shots/title.png of the screen at `frame`."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OUT)) as scratch:
        run(frame + 1, shot_frames=[frame], shot_dir=Path(scratch))
        dump = Path(scratch) / ('frame-%06d.shr' % frame)
        picture = shot.render(dump.read_bytes())
    target = SHOTS / 'title.png'
    target.write_bytes(shot.png(picture))
    return target, shot.stats(picture)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=TITLE_FRAME)
    arguments = parser.parse_args(argv)
    build_machine()
    ensure_image()
    target, info = title_picture(arguments.frames)
    print('%s: %dx%d, %d colours, commonest %.1f%%' % (
        target, info.width, info.height, info.colours,
        100 * info.commonest_share))
    print('game clock: %.3f tics per second of machine time' % tic_rate())
    return 0


if __name__ == '__main__':
    sys.exit(main())
