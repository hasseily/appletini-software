# SPDX-License-Identifier: GPL-2.0-only
"""Static SuperSprite VRAM preview matching Appletini's software renderer.

The reference is appletini-one/ps_sources/frontend/supersprite_vdp.c and
hdl/apple/supersprite_card.sv. This models the current card renderer: text
occupies x=0..239 with a 16-pixel right border, and Graphics II uses three
complete pattern/color banks (the lower R3/R4 address-mask bits are ignored).
Those details differ from a general TMS9918A implementation.

There is no raster timing, display history or status-register mutation here.
A blanked display produces its backdrop; the firmware instead retains its
previous rendered frame. Mixed modes are rejected rather than guessed. RGB
black can be keyed by the caller when composing the SuperSprite overlay.
"""

from __future__ import annotations


WIDTH, HEIGHT = 256, 192

# RGB values used by the Appletini SuperSprite frontend. Background color
# zero selects the backdrop; sprite color zero leaves the underlying pixel.
PALETTE = tuple(bytes(rgb) for rgb in (
    (0x00, 0x00, 0x00), (0x00, 0x00, 0x00), (0x21, 0xC8, 0x42),
    (0x5E, 0xDC, 0x78), (0x54, 0x55, 0xED), (0x7D, 0x76, 0xFC),
    (0xD4, 0x52, 0x4D), (0x42, 0xEB, 0xF5), (0xFC, 0x55, 0x54),
    (0xFF, 0x79, 0x78), (0xD4, 0xC1, 0x54), (0xE6, 0xCE, 0x80),
    (0x21, 0xB0, 0x3B), (0xC9, 0x5B, 0xBA), (0xCC, 0xCC, 0xCC),
    (0xFF, 0xFF, 0xFF),
))


def _sprites(vram: bytes, regs: bytes, pixels: list[bytearray]) -> None:
    attributes = (regs[5] & 0x7F) * 128
    patterns = (regs[6] & 7) * 2048
    size = 16 if regs[1] & 2 else 8
    scale = 2 if regs[1] & 1 else 1
    extent = size * scale
    sprites = []
    for index in range(32):
        start = attributes + index * 4
        y, x, pattern, flags = vram[start:start + 4]
        if y == 0xD0:
            break
        top = y + 1 - (256 if y >= 0xE0 else 0)
        left = x - (32 if flags & 0x80 else 0)
        sprites.append((left, top, pattern & (0xFC if size == 16 else 0xFF), flags & 15))
    for y, row in enumerate(pixels):
        # Admission is by vertical extent, even for transparent, horizontally
        # clipped or pattern-empty sprites. Only the first four can draw.
        visible = [sprite for sprite in sprites if sprite[1] <= y < sprite[1] + extent][:4]
        for left, top, pattern, color in reversed(visible):
            if not color:
                continue
            py = (y - top) // scale
            for x in range(max(0, left), min(WIDTH, left + extent)):
                px = (x - left) // scale
                offset = pattern * 8 + py + (16 if px >= 8 else 0)
                if vram[(patterns + offset) & 0x3FFF] & (0x80 >> (px & 7)):
                    row[x] = color


def decode(vram: bytes, regs: bytes) -> tuple[int, list[bytes]]:
    """Return ``(256, [192 RGB rows of 768 bytes])`` without altering inputs.

    Supports the current Appletini Graphics I, Graphics II, text and
    multicolor render paths, plus 8/16-pixel sprites and magnification.
    ``ValueError`` identifies incorrect input sizes or mixed display modes.
    """
    if len(vram) != 16384:
        raise ValueError("SuperSprite preview needs exactly 16384 VRAM bytes")
    if len(regs) != 8:
        raise ValueError("SuperSprite preview needs exactly 8 VDP registers")
    text = bool(regs[1] & 0x10)
    multicolor = bool(regs[1] & 0x08)
    graphics2 = bool(regs[0] & 0x02)
    if text + multicolor + graphics2 > 1:
        raise ValueError("mixed SuperSprite/TMS9918 display modes are not supported")
    backdrop = regs[7] & 15
    pixels = [bytearray([backdrop]) * WIDTH for _ in range(HEIGHT)]
    if regs[1] & 0x40:
        names = (regs[2] & 15) * 1024
        patterns = (regs[4] & (4 if graphics2 else 7)) * 2048
        colors = (regs[3] & (0x80 if graphics2 else 0xFF)) * 64
        columns = 40 if text else 32
        cell_width = 6 if text else 8
        for y, row in enumerate(pixels):
            for column in range(columns):
                name = vram[names + (y // 8) * columns + column]
                offset = name * 8 + (y & 7)
                if graphics2:
                    offset += (y // 64) * 2048
                if multicolor:
                    pair = vram[(patterns + name * 8 + ((y // 4) & 7)) & 0x3FFF]
                    left, right = (pair >> 4) or backdrop, (pair & 15) or backdrop
                    start = column * 8
                    row[start:start + 8] = bytes([left]) * 4 + bytes([right]) * 4
                    continue
                bits = vram[(patterns + offset) & 0x3FFF]
                pair = regs[7] if text else vram[(colors + (offset if graphics2 else name // 8)) & 0x3FFF]
                foreground, background = (pair >> 4) or backdrop, (pair & 15) or backdrop
                start = column * cell_width
                for bit in range(cell_width):
                    row[start + bit] = foreground if bits & (0x80 >> bit) else background
        if not text:
            _sprites(vram, regs, pixels)
    return WIDTH, [b"".join(PALETTE[color] for color in row) for row in pixels]
