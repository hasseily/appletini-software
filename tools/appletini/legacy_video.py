# SPDX-License-Identifier: GPL-2.0-only
"""Static Apple //e RGB preview, using the production Appletini RGB paths.

Addressing, RGB cells and palette follow apple_cycle_renderer.c and
appletini_ntsc.c in appletini-one at 1a3e8d38 (GPLv2, derived from AppleWin).
The enhanced //e character ROM mapping follows appletini_csbits.c (AppleWin
NTSC_CharSet.cpp, William S Simms 2010-2011, Tom Charlesworth 2016, GPLv2).

This decodes current memory, not capture records: no raster changes, analog
composite filtering, border, A2Li weave/history, or Video-7 MIX state. It uses
the board's RGB color mode, which differs from its composite/idealized modes.
An optional supplied 4096-byte character ROM gives exact enhanced //e glyphs;
otherwise the repository's hand-drawn launcher font supplies readable text.
"""
from functools import lru_cache
from pathlib import Path


PALETTE = tuple(bytes.fromhex(value) for value in (
    '000000', '930b7c', '1f35d3', 'bb36ff',
    '00760c', '7e7e7e', '07a8e1', '9dacff',
    '624c00', 'f9561d', '7e7e7e', 'ff81ec',
    '43c800', 'dccd16', '5df785', 'ffffff'))
_HGR = tuple(PALETTE[i] for i in (0, 15, 6, 9, 12, 3)) + (bytes.fromhex('808080'),)
_BW = (PALETTE[0], PALETTE[15])


def text_address(y, page2=False):
    """Visible scanline y's first text/lores byte (forty adjacent columns)."""
    row = y // 8
    return (0x800 if page2 else 0x400) + (row & 7) * 128 + (row >> 3) * 40


def hires_address(y, page2=False):
    return ((0x4000 if page2 else 0x2000) + (y & 7) * 1024 +
            ((y >> 3) & 7) * 128 + (y >> 6) * 40)


@lru_cache(maxsize=1)
def _fallback_font():
    # This existing demo asset is generated from the original glyphs in
    # demos/appletini_demos/tools/gen_hgr_assets.py; bit 0 is the left pixel.
    path = Path(__file__).resolve().parents[2] / 'demos/fatdog_magic/assets/font7x8.bin'
    font = path.read_bytes()
    if len(font) != 96 * 8:
        raise ValueError('the bundled launcher font must contain 96 eight-row glyphs')
    # Fill punctuation absent in the original launcher, rather than silently
    # rendering it as whitespace. These simple glyphs are original here.
    font = bytearray(font)
    extra = {
        '"': (0x14, 0x14, 0x14, 0, 0, 0, 0, 0),
        '#': (0x14, 0x14, 0x3e, 0x14, 0x3e, 0x14, 0x14, 0),
        '$': (8, 0x3e, 0x0a, 0x1c, 0x28, 0x3e, 8, 0),
        '%': (0x26, 0x16, 8, 8, 0x34, 0x32, 0, 0),
        '&': (0x0c, 0x12, 0x0a, 4, 0x2a, 0x12, 0x2c, 0),
        '*': (0, 0x2a, 0x1c, 0x3e, 0x1c, 0x2a, 0, 0),
        ';': (0, 8, 8, 0, 8, 8, 4, 0),
        '<': (0x10, 8, 4, 2, 4, 8, 0x10, 0),
        '>': (4, 8, 0x10, 0x20, 0x10, 8, 4, 0),
        '@': (0x1c, 0x22, 0x2a, 0x3a, 0x1a, 2, 0x3c, 0),
        '\\': (1, 2, 4, 8, 0x10, 0x20, 0x40, 0),
        '^': (8, 0x14, 0x22, 0, 0, 0, 0, 0),
        '_': (0, 0, 0, 0, 0, 0, 0x3f, 0),
        '`': (4, 8, 0x10, 0, 0, 0, 0, 0),
        '{': (0x18, 4, 4, 2, 4, 4, 0x18, 0),
        '|': (8, 8, 8, 8, 8, 8, 8, 0),
        '}': (6, 8, 8, 0x10, 8, 8, 6, 0),
        '~': (0, 0, 0x16, 0x29, 0, 0, 0, 0),
    }
    for char, rows in extra.items():
        off = (ord(char) - 32) * 8
        font[off:off + 8] = bytes(rows)
    return bytes(font)


@lru_cache(maxsize=4)
def _glyph_rows(video_rom, altchar):
    if video_rom is not None:
        if len(video_rom) != 4096:
            raise ValueError('enhanced //e character ROM must be exactly 4096 bytes')
        return tuple(bytes(video_rom[((ch if altchar or ch >= 128 else ch & 63) * 8) + y]
                           ^ 0x7f for ch in range(256)) for y in range(8))
    font = _fallback_font()
    rows = []
    for y in range(8):
        line = bytearray()
        for ch in range(256):
            code = ch & (63 if not altchar and ch < 128 else 127)
            if code < 32:
                code += 64
            # A visible box identifies MouseText requiring a real font ROM.
            if altchar and 0x40 <= ch < 0x60:
                bits = 0x7f if y in (0, 7) else 0x41
            else:
                bits = font[(code - 32) * 8 + y]
                if ch < 128:
                    bits ^= 0x7f
            line.append(bits & 127)
        rows.append(bytes(line))
    return tuple(rows)


@lru_cache(maxsize=1024)
def _text_line(data, glyphs, flash, double):
    result = bytearray()
    for char in data:
        dots = glyphs[char] ^ (0x7f if flash and char & 0xc0 == 0x40 else 0)
        for x in range(7):
            result.extend(_BW[(dots >> x) & 1] * (2 if double else 1))
    return bytes(result)


@lru_cache(maxsize=1024)
def _lores_line(main, aux, shift):
    if not aux:
        return b''.join(PALETTE[(v >> shift) & 15] * 14 for v in main)
    out = bytearray()
    for a, m in zip(aux, main):
        a = (a >> shift) & 15
        # Production DLORES rotates AUX nibbles by one bit. MAIN is direct.
        out.extend(PALETTE[((a << 1) | (a >> 3)) & 15] * 7)
        out.extend(PALETTE[(m >> shift) & 15] * 7)
    return bytes(out)


@lru_cache(maxsize=1024)
def _hgr_line(data, mono):
    out = bytearray()
    if mono:
        previous = 0
        for byte in data:
            bits = sum(3 << (2 * i) for i in range(7) if byte & (1 << i))
            if byte & 128:
                bits = (bits << 1) | previous
            out.extend(b''.join(_BW[(bits >> i) & 1] for i in range(14)))
            previous = (bits >> 13) & 1
        return bytes(out)
    # Exactly the production step_hgr_rgb pair decoding, including its
    # neighboring-bit black/white override and high-bit palette changes.
    for x in range(0, 40, 2):
        a, b = data[x:x + 2]
        previous = data[x - 1] if x else 0
        following = data[x + 2] if x < 38 else 0
        packed = ((previous & 127) | ((a & 127) << 7) |
                  ((b & 127) << 14) | ((following & 127) << 21))
        colors = packed >> 7
        for i in range(14):
            high = (a if i < 7 else b) & 128
            color = _HGR[(1 + (colors & 3)) if high else (6 - (colors & 3))]
            window = (packed >> i) & 0x1c0
            if window not in (0x140, 0x80):
                color = _BW[bool(window & 0x80)]
            out.extend(color * 2)
            if i & 1:
                colors >>= 2
    return bytes(out)


@lru_cache(maxsize=1024)
def _dhgr_line(main, aux):
    out = bytearray()
    for x in range(0, 40, 2):
        bits = ((aux[x] & 127) | ((main[x] & 127) << 7) |
                ((aux[x + 1] & 127) << 14) | ((main[x + 1] & 127) << 21))
        for _ in range(7):
            nibble = bits & 15
            out.extend(PALETTE[((nibble & 7) << 1) | (nibble >> 3)] * 4)
            bits >>= 4
    return bytes(out)


def decode(main, aux, switches, *, dhires=False, flash=False, video_rom=None):
    """Return (560, list_of_192_RGB_rows) for current MAIN/AUX0 and switches.

    Switch keys match Machine.state()['switches']: text, mixed, hires, col80,
    page2, store80, altchar. `flash` selects the current flashing-text phase.
    Video reads always use MAIN/AUX0, independent of CPU RAMRD/RAMWRT/bank.
    With 80STORE enabled, PAGE2 does not change the displayed page or bank.
    """
    if len(main) != 65536 or len(aux) != 65536:
        raise ValueError('legacy preview needs exactly 65536 bytes each of MAIN and AUX0')
    main, aux = memoryview(main), memoryview(aux)
    font = _glyph_rows(bytes(video_rom) if video_rom is not None else None,
                       bool(switches.get('altchar')))
    page2 = bool(switches.get('page2') and not switches.get('store80'))
    col80, hires = bool(switches.get('col80')), bool(switches.get('hires'))
    text, mixed = bool(switches.get('text')), bool(switches.get('mixed'))
    flash = bool(flash and not switches.get('altchar'))
    rows = []
    for y in range(192):
        is_text = text or (mixed and y >= 160)
        addr = (text_address if is_text or not hires else hires_address)(y, page2)
        m = bytes(main[addr:addr + 40])
        a = bytes(aux[addr:addr + 40]) if col80 else b''
        if is_text:
            data = bytes(v for pair in zip(a, m) for v in pair) if col80 else m
            row = _text_line(data, font[y & 7], flash, not col80)
        elif not hires:
            # Firmware selects DLORES whenever 80COL is set, even if DHIRES=0.
            row = _lores_line(m, a, y & 4)
        elif col80 and dhires:
            row = _dhgr_line(m, a)
        else:
            row = _hgr_line(m, bool(dhires and not col80))
        rows.append(row)
    return 560, rows
