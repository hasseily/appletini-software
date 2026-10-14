"""Original 7x8 fonts and text-tile animation; no Apple ROM data is used."""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

# Hand-drawn 5x7 glyphs. Bit 4 is the left edge of each source row.
FONT = {
    'A': [14,17,17,31,17,17,17], 'B': [30,17,17,30,17,17,30],
    'C': [14,17,16,16,16,17,14], 'D': [30,17,17,17,17,17,30],
    'E': [31,16,16,30,16,16,31], 'F': [31,16,16,30,16,16,16],
    'G': [14,17,16,23,17,17,15], 'H': [17,17,17,31,17,17,17],
    'I': [14,4,4,4,4,4,14], 'J': [7,2,2,2,18,18,12],
    'K': [17,18,20,24,20,18,17], 'L': [16,16,16,16,16,16,31],
    'M': [17,27,21,21,17,17,17], 'N': [17,25,21,19,17,17,17],
    'O': [14,17,17,17,17,17,14], 'P': [30,17,17,30,16,16,16],
    'Q': [14,17,17,17,21,18,13], 'R': [30,17,17,30,20,18,17],
    'S': [15,16,16,14,1,1,30], 'T': [31,4,4,4,4,4,4],
    'U': [17,17,17,17,17,17,14], 'V': [17,17,17,17,17,10,4],
    'W': [17,17,17,21,21,21,10], 'X': [17,17,10,4,10,17,17],
    'Y': [17,17,10,4,4,4,4], 'Z': [31,1,2,4,8,16,31],
    '0': [14,17,19,21,25,17,14], '1': [4,12,4,4,4,4,14],
    '2': [14,17,1,2,4,8,31], '3': [30,1,1,14,1,1,30],
    '4': [2,6,10,18,31,2,2], '5': [31,16,16,30,1,1,30],
    '6': [14,16,16,30,17,17,14], '7': [31,1,2,4,8,8,8],
    '8': [14,17,17,14,17,17,14], '9': [14,17,17,15,1,1,14],
    ' ': [0]*7, '.': [0,0,0,0,0,12,12], ',': [0,0,0,0,4,4,8],
    ':': [0,12,12,0,12,12,0], '-': [0,0,0,31,0,0,0],
    '/': [1,1,2,4,8,16,16], '!': [4,4,4,4,4,0,4],
    '?': [14,17,1,2,4,0,4], '+': [0,4,4,31,4,4,0],
    '=': [0,0,31,0,31,0,0], '*': [0,21,14,31,14,21,0],
    '(': [2,4,8,8,8,4,2], ')': [8,4,2,2,2,4,8],
    '[': [14,8,8,8,8,8,14], ']': [14,2,2,2,2,2,14],
    '<': [1,2,4,8,4,2,1], '>': [16,8,4,2,4,8,16],
    '_': [0,0,0,0,0,0,31], '#': [10,31,10,10,31,10,0],
    '@': [14,17,23,21,23,16,14], "'": [4,4,8,0,0,0,0],
}
BAYER = ((0,8,2,10), (12,4,14,6), (3,11,1,9), (15,7,13,5))
SCENES = ('PHASE TUNNEL', 'CHROME CITY', 'TYPE INVADERS')
DESCRIPTIONS = ('32 NEW SHADE TILES','A CITY MADE OF TEXT','ORIGINAL FONT ART')
FRAMES = 8
ROWS = 18
COLS = 40


def font_rows(character: str, style: int) -> list[int]:
    source = FONT.get(character.upper(), FONT['?'])
    rows = []
    for y, row in enumerate(source):
        bits = sum(((row >> (4-x)) & 1) << (x+1) for x in range(5))
        if style == 1:
            bits |= bits << 1               # block face
        if style == 2:
            bits = bits << ((6-y)//3)       # slanted face
        rows.append(bits & 127)
    return rows + [0]


def mosaic(n: int) -> list[int]:
    return [((7 if n & (1 if y < 4 else 4) else 0) |
             (120 if n & (2 if y < 4 else 8) else 0)) for y in range(8)]


def tiles(scene: int) -> list[list[int]]:
    if scene == 0:
        # A 32-level dither ramp gives each text cell its own shade.
        return [[sum((1 << x) if BAYER[y % 4][x % 4] < n/2 else 0
                     for x in range(7)) for y in range(8)] for n in range(32)]
    if scene == 1:
        return [
            [0]*8, [0,0,0,8,28,8,0,0], [127]*8,
            [127,65,65,127,65,65,127,127],
            [127,0,54,54,0,54,54,127], [127,0,0,0,0,0,0,127],
            [127,0,34,34,0,34,34,127], [8,8,8,8,127,127,127,127],
            [0,0,0,0,0,0,0,127], [0,0,0,127,0,0,127,0],
            [0,0,127,0,0,127,0,0], [0,127,0,0,127,0,0,0],
            [0,0,0,0,96,112,120,124], [0,0,0,0,3,7,15,31],
            [0,0,0,127,127,127,54,0], [0,0,0,0,0,8,0,0],
        ] + [mosaic(n) for n in range(16)]
    # Mosaic cells plus an original eight-frame creature set.
    aliens = [
        [20,62,127,107,127,62,20,34], [20,62,127,107,127,62,34,65],
        [8,28,62,107,127,85,20,34], [8,28,62,107,127,85,34,65],
        [0,28,62,127,85,127,34,20], [0,28,62,127,85,127,65,34],
        [0,8,28,62,127,62,28,8], [0,0,8,28,62,28,8,0],
    ]
    return [mosaic(n) for n in range(16)] + aliens + [
        [0,0,0,8,28,8,0,0], [0,0,0,0,8,0,0,0],
        [127,1,1,1,1,1,1,127], [127,64,64,64,64,64,64,127],
        [127,0,0,0,0,0,0,0], [0,0,0,0,0,0,0,127],
        [8]*8, [0,0,0,0,127,0,0,0],
    ]


def make_rom(scene: int) -> bytes:
    rom = bytearray([255]*4096)
    for code in range(128, 256):
        rows = tiles(scene)[code-128] if code < 160 else font_rows(chr(code & 127), scene)
        rom[code*8:code*8+8] = bytes(v ^ 255 for v in rows)
    for code in range(64):
        char = chr(code + 64 if code < 32 else code)
        rom[code*8:code*8+8] = bytes(v ^ 127 ^ 255 for v in font_rows(char, scene))
    # Give the alternate-set tile positions defined shapes too.
    for n, rows in enumerate(tiles(scene)):
        rom[(64+n)*8:(65+n)*8] = bytes(v ^ 255 for v in rows)
    # PAL Accurate uses the raw ROM path; duplicate the used 2 KB bank.
    rom[2048:] = rom[:2048]
    return bytes(rom)


def text(frame: bytearray, row: int, col: int, message: str) -> None:
    for x, ch in enumerate(message):
        if 0 <= col+x < 40:
            frame[row*40+col+x] = ord(ch.upper()) | 128


def frame(scene: int, tick: int) -> bytes:
    out = bytearray([160]*720)
    if scene == 0:
        for y in range(18):
            for x in range(40):
                dx, dy = (x-19.5)*0.55, (y-8.5)
                radius = math.hypot(dx, dy)
                angle = math.atan2(dy, dx)
                val = 0.5 + 0.34*math.sin(radius*.72-tick*math.pi/4+angle*2)
                val += 0.15*math.sin(x*.28+y*.5+tick*math.pi/4)
                out[y*40+x] = 128+max(0, min(31, round(val*31)))
        # A black strip uses ordinary text inside the tile picture.
        for y in (8,9):
            out[y*40:y*40+40] = bytes([160]*40)
        text(out,8,7,'YOUR CHARACTERS. YOUR WORLD.')
        text(out,9,10,'4096 BYTES / ONE FRAME')
    elif scene == 1:
        out[:] = bytes([128]*720)
        for x in range(40):
            if (x*13+tick*3) % 17 < 2:
                out[((x*7) % 7)*40+x] = 129 if tick % 2 else 143
        # A scrolling skyline; every building consists of character cells.
        for x in range(40):
            world = (x+tick*5) % 40
            building = world//4
            height = 4 + ((building*7+3) % 8)
            for y in range(14-height,14):
                if world % 4 == 3:
                    out[y*40+x] = 130
                elif y == 14-height:
                    out[y*40+x] = 135 if world%4==1 else 130
                else:
                    out[y*40+x] = 132 if (y+building+tick)%3 else 134
            for y in range(14,18):
                out[y*40+x] = 137+(x+y+tick)%3 if y%2 else 128
        ship_x = 3+tick*4
        out[3*40+ship_x:3*40+ship_x+4] = bytes((141,142,142,140))
    else:
        out[:] = bytes([128]*720)
        # Render GLYPH as giant solid text cells in a slanted-font scene.
        for letter, ch in enumerate('GLYPH'):
            for y, bits in enumerate(FONT[ch]):
                for x in range(5):
                    if bits & (1 << (4-x)):
                        out[(y+1)*40+letter*7+x+3] = 143
        for y in range(9,12):
            for x in range(2,39,4):
                out[y*40+(x+tick%2)] = 144+((y+tick)%6)
        text(out,13,1,'ABCDEFGHIJKLMNOPQRSTUVWXYZ  0123456789')
        text(out,15,5,'TEXT MODE HAS LEARNED NEW TRICKS!')
        text(out,17,4,'FONT: ORIGINAL 5X7 SLANTED LETTERS')
    return bytes(out)


def render(rom: bytes, screen: bytes, scale: int = 2):
    from PIL import Image
    image = Image.new('RGB', (280,192), (9,13,20))
    px = image.load()
    for cell, code in enumerate(screen):
        x0, y0 = cell%40*7, cell//40*8
        address = code*8 if code>=128 else (code & 63)*8
        for y in range(8):
            bits = rom[address+y] ^ 255
            for x in range(7):
                if bits & (1<<x):
                    px[x0+x,y0+y] = (179,239,235)
    return image.resize((280*scale,192*scale), Image.Resampling.NEAREST)


def generate(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    metadata = {'format':'AGLY v1', 'rom_bytes':4096, 'frame_bytes':720,
                'frames_per_scene':FRAMES, 'scenes':[]}
    declarations = []
    for n, name in enumerate(SCENES):
        rom = make_rom(n)
        data = b''.join(frame(n,t) for t in range(FRAMES))
        (output/f'font{n}.rom').write_bytes(rom)
        (output/f'scene{n}.bin').write_bytes(data)
        declarations.extend((f'rom{n}: !binary "font{n}.rom"',
                             f'frames{n}: !binary "scene{n}.bin"'))
        crc = zlib.crc32(rom)
        metadata['scenes'].append({'name':name,'crc32':f'{crc:08x}'})
        animation=[]
        for tick in range(FRAMES):
            full = bytearray([160]*960)
            text(full,0,0,'APPLETINI GLYPH LAB      AGLY API V1')
            text(full,1,0,f'{n+1}/3 {name} - {DESCRIPTIONS[n]}')
            full[3*40:21*40] = frame(n,tick)
            text(full,22,0,'1-3 SCENE  SPACE PAUSE  A AUTO  Q QUIT')
            text(full,23,0,'AUTO    4096B FONT / 512B CHUNKS / CRC32')
            animation.append(render(rom, full, 3))
        animation[2].save(output/f'preview{n}.png')
        animation[0].save(output/f'preview{n}.gif',save_all=True,
                          append_images=animation[1:],duration=67,loop=0)
    declarations.extend(('rom_lo: !byte <rom0,<rom1,<rom2',
                         'rom_hi: !byte >rom0,>rom1,>rom2',
                         'frames_lo: !byte <frames0,<frames1,<frames2',
                         'frames_hi: !byte >frames0,>frames1,>frames2',
                         'crc_table: !byte '+','.join(str(v) for n in range(3)
                         for v in struct.pack('<I',zlib.crc32(make_rom(n))))))
    (output/'assets.a65').write_text('\n'.join(declarations)+'\n',encoding='utf8')
    return metadata
