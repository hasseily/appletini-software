"""The reference machine's files: build/ref816/ref816 (make -C
tools/ref816) and the release's memory.img and disk.hdv (make_image.py),
built when they are missing.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import make_image  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = make_image.OUT_DIR
MACHINE = OUT / 'ref816'
MEMORY = OUT / 'memory.img'
DISK = OUT / 'disk.hdv'


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
