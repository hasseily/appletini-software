# SPDX-License-Identifier: GPL-2.0-only
"""Static Apple/SHR/SuperSprite previews, not the capture-stream renderer."""
import struct
import zlib
from pathlib import Path


def decode_shr(bank):
    if len(bank) != 0x8000:
        raise ValueError('SHR preview needs AUX $2000-$9FFF (32768 bytes)')
    if bytes(b & 0x7f for b in bank[0x7dfc:0x7e00]) in (b'SHR4', b'3200'):
        raise ValueError('SHR4/3200 preview is not implemented; use a raw memory dump')
    scbs = bank[0x7d00:0x7dc8]
    width = 640 if any(s & 0x80 for s in scbs) else 320
    palettes = []
    for p in range(16):
        palette = []
        for i in range(16):
            off = 0x7e00 + 32 * p + 2 * i
            value = int.from_bytes(bank[off:off + 2], 'little')
            # Match apple_cycle_renderer.c's 0..240 component scale.
            palette.append(bytes(((value >> 8 & 15) * 16,
                                  (value >> 4 & 15) * 16, (value & 15) * 16)))
        palettes.append(palette)
    rows = []
    for y, scb in enumerate(scbs):
        palette, row = palettes[scb & 15], bytearray()
        previous = bytes(3)
        for byte in bank[y * 160:(y + 1) * 160]:
            if scb & 0x80:
                for shift, base in ((6, 8), (4, 12), (2, 0), (0, 4)):
                    row.extend(palette[base + ((byte >> shift) & 3)])
            else:
                for pixel in (byte >> 4, byte & 15):
                    color = previous if scb & 0x20 and pixel == 0 else palette[pixel]
                    row.extend(color * (width // 320))
                    previous = color
        rows.append(bytes(row))
    return width, rows


def frame_png(machine):
    if machine.slot7 == 'supersprite':
        from supersprite_video import decode
        width, rows = decode(machine.card_read('supersprite-vram', 0, 16384),
                             machine.card_read('supersprite-regs', 0, 8))
        source = 'supersprite-memory-preview-uncomposited'
        display_width, display_height = 560, 384
    elif machine.get('newvideo') & 0xc0 == 0xc0:
        width, rows = decode_shr(machine.read('aux0', 0x2000, 0x8000))
        if machine.get('newvideo') & 0x20:
            rows = [bytes(value for i in range(0, len(row), 3)
                          for value in [((77 * row[i] + 150 * row[i + 1] + 29 * row[i + 2]) >> 8)] * 3)
                    for row in rows]
        source = 'aux-memory-preview'
        display_width, display_height = 640, 400
    else:
        from legacy_video import decode
        width, rows = decode(machine.read('main', 0, 65536),
                             machine.read('aux0', 0, 65536), machine.state()['switches'],
                             dhires=bool(machine.get('dhires')),
                             flash=bool((machine.get('ticks') // (machine.get('frame_ticks') * 16)) & 1),
                             video_rom=machine.video_rom)
        source = ('apple-rgb-memory-preview' if machine.video_rom else
                  'apple-rgb-memory-preview-fallback-font')
        display_width, display_height = 560, 384
    height = len(rows)

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data)))

    png = (b'\x89PNG\r\n\x1a\n' +
           chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
           chunk(b'IDAT', zlib.compress(b''.join(b'\0' + row for row in rows))) +
           chunk(b'IEND', b''))
    return png, {'width': width, 'height': height,
            'display_width': display_width, 'display_height': display_height,
            'source': source, 'capture_stream_faithful': False}


def screenshot(machine, path):
    png, info = frame_png(machine)
    path = Path(path).expanduser()
    path.write_bytes(png)
    return {'path': str(path.resolve()), **info}
