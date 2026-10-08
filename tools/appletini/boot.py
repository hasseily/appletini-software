# SPDX-License-Identifier: GPL-2.0-only
"""Load supplied SmartPort firmware; ROM bytes are not redistributed here."""
import hashlib
from pathlib import Path
import re


def _load(path, size):
    path = Path(path).expanduser().resolve()
    if path.stat().st_size > 32768:
        raise ValueError('SmartPort firmware file is too large: %s' % path)
    data = path.read_bytes()
    if path.suffix.lower() == '.mem':
        try:
            text = data.decode('ascii')
        except UnicodeDecodeError as exc:
            raise ValueError('SmartPort .mem must be ASCII hexadecimal bytes') from exc
        # The target's readmemh files have one byte per line; comments are
        # accepted, but address directives and unknown tokens are rejected.
        text = re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S)
        tokens = text.split()
        if any(not re.fullmatch(r'[0-9a-fA-F]{2}', token) for token in tokens):
            raise ValueError('SmartPort .mem must contain two-digit hexadecimal bytes')
        data = bytes(int(token, 16) for token in tokens)
    if len(data) != size:
        raise ValueError('%s must contain exactly %d firmware bytes' % (path, size))
    return data, {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': size}


def load_roms(slot_rom_path=None, c8_rom_path=None):
    """Return (C700 bytes, C800 bytes, provenance); .mem and binary supported.

    Defaults use the neighboring appletini-one hardware checkout. Missing
    files fail explicitly: boot cannot silently fall back to service traps.
    """
    target = Path(__file__).resolve().parents[3] / 'appletini-one/hdl/apple'
    slot = slot_rom_path or target / 'smartport_a2retronet_style_c700.mem'
    c8 = c8_rom_path or target / 'smartport_a2retronet_style_c800.mem'
    first, first_info = _load(slot, 256)
    second, second_info = _load(c8, 2048)
    return first, second, {'slot7_rom': first_info, 'slot7_c8_rom': second_info,
                           'firmware_execution': True, 'prodos_mli_traps': False}
