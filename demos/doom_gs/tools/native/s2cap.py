#!/usr/bin/env python3
"""The release's symbols and code for the screens' parts: the link map
of the reference build (ref816's make_image.py), its symbols' addresses
and the release's memory at its entry, each loaded once."""

import json
import sys
from pathlib import Path
from typing import Dict, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ref816 import make_image, refimage, script, title  # noqa: E402

ROOT = make_image.ROOT           # (the tree's, also from a scratch copy)

_LINKMAP: Optional[Dict] = None


def linkmap() -> Dict:
    global _LINKMAP
    if _LINKMAP is None:
        with open(str(make_image.LINKMAP)) as handle:
            _LINKMAP = json.load(handle)
    return _LINKMAP


_SYMBOLS: Optional[script.Symbols] = None


def symbols() -> script.Symbols:
    global _SYMBOLS
    if _SYMBOLS is None:
        _SYMBOLS = script.Symbols(linkmap())
    return _SYMBOLS


_SYMS: Dict[str, int] = {}


def sym(name: str) -> int:
    if name not in _SYMS:
        _SYMS[name] = symbols().address(name)
    return _SYMS[name]


_CODE: Optional[refimage.Memory] = None


def code() -> refimage.Memory:
    """The release's memory at its entry (the game's code)."""
    global _CODE
    if _CODE is None:
        _CODE = refimage.load(refimage.read(title.MEMORY))
    return _CODE
