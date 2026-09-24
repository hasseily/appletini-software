#!/usr/bin/env python3
"""Screen layout: patches for the editor's and the wiring kit's records.

The upstream keeps its rectangles (6 bytes: top, left div 7, left mod 7,
height-1, width div 7, width mod 7) and bitmap records (data pointer, y,
x div 7, x mod 7, rows, bytes) as HEX data. The port's rectangles are
(top, x lo, x hi, height-1, width lo, width hi) and its bitmap records
(sprite directory entry, y, x lo, x hi, rows, pixels). This tool rewrites
every such record, keeps the original geometry of the parts menu and of
the wiring kit, and lays the editor's tool strip out anew in the wider
panel (x 258..319): two columns of 24x14 icons and eight paint swatches.

    python3 tools/layout.py UPSTREAM --assets build/assets.inc \
        --patches build/layout_patches.json --data build/layout_data.s
"""

import argparse
import json
import re
from pathlib import Path

import parts as partsmod

TABLE_W = 154
SCREEN_W = 320
PANEL_X = 154
TOOL_X = 264

# the editor's tool strip: (box label, icon label, sprite, handler)
TOOLS = [
    ('HANDB', 'ICONHAND', 'tool_hand', 'INITHAND'),
    ('POINTERB', 'ICONPOINTER', 'tool_pointer', 'INITPOINTER'),
    ('SCISSORB', 'ICONSCISSOR', 'tool_scissor', 'INITSCISSOR'),
    ('HAMMERB', 'ICONHAMMER', 'tool_hammer', 'INITHAMMER'),
    ('BRUSHB', 'ICONBRUSH', 'tool_brush', 'INITBRUSH'),
    ('PLAYB', 'ICONPLAY', 'tool_play', 'PLAY'),
    ('MAGNB', 'ICONMAGN', 'tool_magnifier', 'MAGPAINT'),
    ('WORLDB', 'ICONWORLD', 'tool_world', 'SETWORLD'),
    ('WIREB', 'ICONWIRE', 'tool_wire', 'WIREKIT'),
    ('DISKB', 'ICONDISK', 'tool_disk', 'DISKIO'),
]
SWATCHES = [
    ('WHITEB', 'SWWHITE', 'swatch_W', 'WHITE'),
    ('REDB', 'SWRED', 'swatch_R', 'RED'),
    ('ORANGEB', 'SWORANGE', 'swatch_O', 'ORANGE'),
    ('YELLOWB', 'SWYELLOW', 'swatch_Y', 'YELLOW'),
    ('GREENB', 'SWGREEN', 'swatch_G', 'GREEN'),
    ('BLUEB', 'SWBLUE', 'swatch_B', 'BLUE'),
    ('CYANB', 'SWCYAN', 'swatch_C', 'CYAN'),
    ('VIOLETB', 'SWVIOLET', 'swatch_V', 'VIOLET'),
]
ICON_W, ICON_H, ICON_PITCH = 24, 14, 17
SWATCH_W, SWATCH_H, SWATCH_PITCH = 12, 8, 11


def read_sizes(assets_dir):
    """sprite name -> (w, h) from the text-art files (derived ones too)."""
    sizes = {}
    for path in sorted(Path(assets_dir).glob('*.txt')):
        for line in path.read_text().splitlines():
            m = re.match(r'sprite\s+(\S+)\s+(\d+)\s+(\d+)', line)
            if m:
                sizes[m.group(1)] = (int(m.group(2)), int(m.group(3)))
            m = re.match(r'derive\s+(\S+)\s*=\s*\S+\s+(\S+)', line)
            if m and m.group(2) in sizes:
                sizes[m.group(1)] = sizes[m.group(2)]
    return sizes


def read_ids(path):
    ids = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r'\s*SPR_([A-Z0-9_]+)\s*=\s*(\d+)', line)
        if m:
            ids[m.group(1).lower()] = int(m.group(2))
    return ids


def hexline(label, data):
    return '%s HEX %s' % (label, ''.join('%02X' % b for b in data))


def rect_bytes(top, x, height, width):
    """A port rectangle record: right edge = x + width (inclusive)."""
    return [top, x & 0xFF, x >> 8, height - 1, width & 0xFF, width >> 8]


def convert_rect(data):
    """Original rectangle bytes -> port bytes (same geometry)."""
    top, ld7, lm7, h1, wd7, wm7 = data
    x = ld7 * 7 + lm7
    w = wd7 * 7 + wm7
    return rect_bytes(top, x, h1 + 1, w)


def icon_record(label, sprite, x, y, ids, sizes):
    w, h = sizes.get(sprite, (8, 8))
    return ['%s DA spr_dir+%d' % (label, 4 * ids[sprite.lower()]),
            hexline('', [y, x & 0xFF, x >> 8, h, w])]


class Patcher:
    def __init__(self, module, lines):
        self.module = module
        self.lines = lines
        self.patches = []

    def find(self, label):
        for i, line in enumerate(self.lines, 1):
            if line.startswith(label + ' ') or line == label:
                return i
        raise KeyError('%s: %s' % (self.module, label))

    def add(self, line, replace, end=None):
        p = {'module': self.module, 'line': line, 'expect': self.lines[line - 1], 'replace': replace}
        if end:
            p['end'] = end
        self.patches.append(p)

    def hex_data(self, line):
        return bytes.fromhex(self.lines[line - 1].split('HEX', 1)[1].split(';')[0].replace(',', '').strip())

    def convert_rect_label(self, label):
        line = self.find(label)
        self.add(line, hexline(label, convert_rect(self.hex_data(line))))

    def record_block_end(self, line):
        """Last line of a `LABEL DA *+7` record (its HEX lines follow)."""
        end = line
        while end < len(self.lines) and self.lines[end].startswith(' HEX'):
            end += 1
        return end


def edit_patches(edit, ids, sizes):
    p = Patcher('EDIT', edit)
    # regions
    p.add(p.find('TABLEB'), hexline('TABLEB', rect_bytes(0, 0, 192, TABLE_W - 1)))
    p.add(p.find('KITB'), hexline('KITB', rect_bytes(0, PANEL_X, 192, SCREEN_W - 1 - PANEL_X)))
    p.add(p.find('TOOLB'), hexline('TOOLB', rect_bytes(0, TOOL_X, 192, SCREEN_W - 1 - TOOL_X)))
    # the tool strip: two columns
    icon_records = []
    boxes = {}
    for i, (box, icon, sprite, _) in enumerate(TOOLS):
        col, row = i % 2, i // 2
        x = TOOL_X + 2 + col * 28
        y = 2 + row * ICON_PITCH
        boxes[box] = rect_bytes(y - 2, x - 2, ICON_H + 4, ICON_W + 3)
        icon_records += icon_record(icon, sprite, x, y, ids, sizes)
    sw_y0 = 2 + 5 * ICON_PITCH + 2
    for i, (box, icon, sprite, _) in enumerate(SWATCHES):
        col, row = i % 2, i // 2
        x = TOOL_X + 8 + col * 28
        y = sw_y0 + row * SWATCH_PITCH
        boxes[box] = rect_bytes(y - 1, x - 2, SWATCH_H + 2, SWATCH_W + 3)
        icon_records += icon_record(icon, sprite, x, y, ids, sizes)
    for box in ('HANDB', 'POINTERB', 'SCISSORB', 'HAMMERB', 'BRUSHB', 'WHITEB', 'GREENB', 'REDB',
                'VIOLETB', 'PLAYB', 'MAGNB', 'WORLDB', 'WIREB', 'DISKB'):
        p.add(p.find(box), hexline(box, boxes[box]))
    line = p.find('BLUEB')
    p.add(line, [hexline('BLUEB', boxes['BLUEB']), hexline('ORANGEB', boxes['ORANGEB']),
                 hexline('YELLOWB', boxes['YELLOWB']), hexline('CYANB', boxes['CYANB'])])
    # the command menu
    line = p.find('CMDMENU')
    end = line
    while not edit[end - 1].startswith(' HEX 00'):
        end += 1
    menu = []
    for i, (box, _, _, handler) in enumerate(TOOLS + SWATCHES):
        menu.append(('CMDMENU DA %s' if i == 0 else ' DA %s') % box)
        menu.append(' DA %s' % handler)
    menu.append(' HEX 0000')
    p.add(line, menu, end=end)
    # the parts menu boxes keep their geometry
    for name in partsmod.KIT_ORDER:
        label = {'LEFTFLIPPER': 'LFLIPB', 'RIGHTFLIPPER': 'RFLIPB', 'LFLIPPER2': 'LFLIP2B',
                 'RFLIPPER2': 'RFLIP2B', 'SPIN1': 'SPINB', 'MAG1': 'MGNTB'}.get(name, name + 'B')
        p.convert_rect_label(label)
    # ICONS: tool icons, swatches, POLYICON, then the parts (unchanged lines)
    line = p.find('ICONS')
    entries = ['ICONS DA %s' % TOOLS[0][1]] + [' DA %s' % t[1] for t in TOOLS[1:]] + [' DA %s' % s[1] for s in SWATCHES]
    # the original's 15 icon lines (HAND .. DISK) end before ' DA POLYICON'
    end = line
    while edit[end].strip() != 'DA POLYICON':
        end += 1
    p.add(line, entries, end=end)
    # the count in SETUP: 2 * (18 + 1 + 38)
    n_parts = sum(1 for part in partsmod.KIT_ORDER if not part.startswith('POLY'))
    count = 2 * (len(TOOLS) + len(SWATCHES) + 1 + n_parts)
    for i, l in enumerate(edit, 1):
        if l.strip() == 'CPY #108':
            p.add(i, ' CPY #%d' % count)
            break
    else:
        raise KeyError('CPY #108')
    # the icon records WHITEPAINT..POLYICON become the new records
    first = p.find('WHITEPAINT')
    last = p.record_block_end(p.find('POLYICON'))
    records = icon_records + icon_record('POLYICON', 'poly_icon', 166, 25, ids, sizes)
    p.add(first, records, end=last)
    # cursors: the record only names the sprite
    for label, sprite in (('HAND', 'cur_hand'), ('POINTER', 'cur_pointer'), ('SCISSOR', 'cur_scissor'),
                          ('HAMMER', 'cur_hammer'), ('BRUSH', 'cur_brush')):
        line = p.find(label)
        p.add(line, icon_record(label, sprite, 0, 0, ids, sizes), end=p.record_block_end(line))
    # the world screen's sliders
    for i, label in enumerate(('SLIDE1', 'SLIDE2', 'SLIDE3', 'SLIDE4')):
        line = p.find(label)
        data = p.hex_data(line + 1)             # y, xdiv7, xmod7, rows, bytes
        x = data[1] * 7 + data[2]
        rec = icon_record(label, 'slide_scale', x, data[0], ids, sizes)
        if i < 3:
            p.add(line, rec, end=line + 1)
        else:
            p.add(line, rec, end=p.record_block_end(p.find('SLIDEBITS')))
    for label in ('SL1B', 'SL2B', 'SL3B', 'SL4B'):
        p.convert_rect_label(label)
    return p.patches


def wire_patches(wire, ids, sizes):
    p = Patcher('WIRE', wire)
    p.add(p.find('TABLEB'), hexline('TABLEB', rect_bytes(0, 0, 192, TABLE_W - 1)))
    p.add(p.find('KITB'), hexline('KITB', rect_bytes(0, PANEL_X, 192, SCREEN_W - 1 - PANEL_X)))
    p.add(p.find('TOOLB'), hexline('TOOLB', rect_bytes(0, 252, 192, SCREEN_W - 1 - 252)))
    for label in ('HANDB', 'PLIERB', 'DRIVERB', 'QUITB', 'ANDB', 'ANDBOX', 'SCOREB', 'SCBOX',
                  'BMULTBOX', 'NOTEB', 'NBOX') + tuple('SCBOX%d' % i for i in range(1, 16)) \
            + tuple('NBOX%d' % i for i in range(1, 8)):
        p.convert_rect_label(label)
    for label, sprite, x, y in (('HAND', 'wire_hand', 260, 2), ('PLIER', 'wire_plier', 258, 18),
                                ('SCREWDRIVER', 'wire_screwdriver', 266, 37),
                                ('ANDGATE', 'wire_andgate', 160, 0), ('NOTE', 'wire_note', 168, 0)):
        line = p.find(label)
        p.add(line, icon_record(label, sprite, x, y, ids, sizes), end=p.record_block_end(line))
    return p.patches


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('upstream')
    ap.add_argument('--assets', required=True, help='build/assets.inc (sprite ids)')
    ap.add_argument('--art', default='assets', help='the text-art directory (sprite sizes)')
    ap.add_argument('--patches', required=True)
    ap.add_argument('--data', required=True)
    args = ap.parse_args()
    ids = read_ids(args.assets)
    sizes = read_sizes(args.art)
    edit = partsmod.read_source(args.upstream, 'EDIT.S')
    wire = partsmod.read_source(args.upstream, 'WIRE.S')
    patches = edit_patches(edit, ids, sizes) + wire_patches(wire, ids, sizes)
    Path(args.patches).write_text(json.dumps(patches, indent=1))
    Path(args.data).write_text('; Generated by tools/layout.py. Do not edit.\n'
                               '; (all layout data lives in the patched modules)\n'
                               '.setcpu "65C02"\n')


if __name__ == '__main__':
    main()
