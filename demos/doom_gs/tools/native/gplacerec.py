"""The tic build's group files (tools/native/playdisk.py's frame slot and
'A2Li' rules): group_files."""

from pathlib import Path
from typing import Dict, Tuple


def group_files(b) -> Dict[int, Tuple[Path, int, int]]:
    """group -> (file, slot address, bytes) of a tic build's groups (its
    GGRPn segments and the glue's: every G memory area with a file)."""
    out: Dict[int, Tuple[Path, int, int]] = {}
    for p in sorted(b.obj.glob('%s.g*' % b.name)):
        try:
            n = int(p.suffix[2:])
        except ValueError:
            continue
        data = p.read_bytes()
        if not data:
            continue
        lo = None
        seg = b.segments.get('GGRP%d' % n)
        if seg is not None:
            lo = seg[0]
            size = min(len(data), seg[1] + 1 - seg[0])
        else:
            size = len(data)
        out[n] = (p, lo if lo is not None else -1, size)
    return out
