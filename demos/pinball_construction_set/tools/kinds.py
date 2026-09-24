#!/usr/bin/env python3
"""Part kinds: patches for the RUN.S part templates and the kind table.

The templates at the end of RUN.S carry each part's 7-byte bitmap header
in the original's HGR terms (bitmap address, y, x div 7, x mod 7, rows,
bytes). The port's records are (sprite directory entry, y, x lo, x hi,
rows, pixels) with a frame stride of 4 (one directory entry per frame),
so every template's `DA <bitmap>` and header line is rewritten. The
runtime's own small records (IBALL, HBALL, VBALL, DROPTXB, DROPTYB) and
the flipper frame tables (uniform frames, docs/DESIGN.md section 5) are
rewritten the same way.

    python3 tools/kinds.py UPSTREAM --parts build/parts.json --assets build/assets.inc \
        --patches build/kind_patches.json --out build/kinds.s
"""

import argparse
import json
import re
from pathlib import Path

import parts as partsmod

# template name -> sprite base name (gen_assets.py uses the same names)
SPRITE_BASE = {
    'LAUNCHER': 'launcher', 'LEFTFLIPPER': 'lflip', 'RIGHTFLIPPER': 'rflip',
    'BALL': 'ball', 'BMP1': 'bmp1', 'BMP2': 'bmp2', 'BMP3': 'bmp3', 'BMP4': 'bmp4',
    'BMP5': 'bmp5', 'BMP6': 'bmp6', 'LKICK': 'lkick', 'RKICK': 'rkick',
    'KICK1': 'kick1', 'KICK2': 'kick2', 'ROLL1': 'roll1', 'ROLL2': 'roll2', 'ROLL3': 'roll3',
    'TARG1': 'targ1', 'TARG2': 'targ2', 'TARG3': 'targ3', 'TARG4': 'targ4', 'TARG5': 'targ5',
    'TARG6': 'targ6', 'LFLIPPER2': 'lflip2', 'RFLIPPER2': 'rflip2',
    'LANE1': 'lane1', 'LANE2': 'lane2', 'LANE3': 'lane3',
    'GATE1': 'gate1', 'GATE2': 'gate2', 'GATE3': 'gate3', 'GATE4': 'gate4',
    'DROP1': 'drop1', 'DROP2': 'drop2', 'CATCH1': 'catch1', 'CATCH2': 'catch2',
    'SPIN1': 'spin1', 'MAG1': 'mag1',
}

# the runtime's own bitmap records: label -> (sprite, rows, pixels)
RUN_RECORDS = {
    'IBALL': ('ball_0', 5, 5), 'HBALL': ('ball_0', 5, 6), 'VBALL': ('ball_0', 6, 5),
    'DROPTXB': ('dropx_0', 3, 7), 'DROPTYB': ('dropy_0', 7, 7),
}

# flipper tables: uniform frames
FLIPPER_TABLES = {
    'FXDVERT': [0] * 16,
    'FXHEIGHT': [16] * 8 + [11] * 8,
    'FXLEN': [4] * 16,
    'FDDVERT': [0, 0, 0, 0, 0, 0, 0xFE, 0xFC, 0, 2, 1, 0, 0, 0, 0xFE, 0xFD],
}


# The upstream's FILLCOLOR is an even byte offset into PPAK.S CLRPATCH.
# Dividing it by two yields the HGR colour code below: 0/4 black, 1 green,
# 2 violet, 3/7 white, 5 orange, 6 blue. $10 is the invisible fill.
HGR_TO_PALETTE = {0: 0, 1: 10, 2: 14, 3: 4, 4: 0, 5: 7, 6: 12, 7: 4}


def hgr_fill_to_palette(fill):
    if fill == 0x10:
        return fill
    if fill & 1 or fill > 14:
        raise ValueError('unknown original HGR fill colour $%02X' % fill)
    return HGR_TO_PALETTE[fill // 2]


def read_assets_inc(path):
    ids = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r'\s*(SPR_[A-Z0-9_]+)\s*=\s*(\d+)', line)
        if m:
            ids[m.group(1)] = int(m.group(2))
    return ids


def sprite_id(ids, name):
    key = 'SPR_' + name.upper()
    if key not in ids:
        raise KeyError('sprite %s missing from assets.inc' % name)
    return ids[key]


def hexline(label, data):
    return '%s HEX %s' % (label, ''.join('%02X' % b for b in data))


def find_label(lines, label):
    for i, line in enumerate(lines, 1):
        if line.startswith(label + ' ') or line == label:
            return i
    raise KeyError(label)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('upstream')
    ap.add_argument('--parts', required=True)
    ap.add_argument('--assets', required=True)
    ap.add_argument('--patches', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    parts = json.loads(Path(args.parts).read_text())['parts']
    ids = read_assets_inc(args.assets)
    run = partsmod.read_source(args.upstream, 'RUN.S')
    patches = []

    def patch(module, line, replace, end=None):
        p = {'module': module, 'line': line, 'expect': run[line - 1], 'replace': replace}
        if end:
            p['end'] = end
        patches.append(p)

    kind_rows = []
    for p in parts:
        name = p['name']
        line = find_label(run, name)
        if p['id'] != 3:
            # a polygon template: its fill byte is an HGR colour code; the
            # port's FILLCOLOR is a palette index
            assert run[line - 1].startswith(name + ' HEX '), (name, run[line - 1])
            data = bytes.fromhex(run[line - 1].split('HEX', 1)[1].split(';')[0].replace(',', '').strip())
            data = bytes([data[0], hgr_fill_to_palette(data[1])]) + data[2:]
            patch('RUN', line, hexline(name, data))
            kind_rows.append((name, p['objlen'], 3 + 2 * len(p['x']), 0, 0))
            continue
        base = SPRITE_BASE[name]
        spr0 = sprite_id(ids, base + '_0')
        w, h = p['box']
        # line+3: DA <bitmap>, line+4: header
        assert run[line + 2].startswith(' DA '), (name, run[line + 2])
        assert run[line + 3].startswith(' HEX '), (name, run[line + 3])
        patch('RUN', line + 3, ' DA spr_dir+%d' % (4 * spr0))
        header = [p['y0'], p['x0'] & 0xFF, p['x0'] >> 8, h, w, 4, p['time'], p['score']]
        patch('RUN', line + 4, hexline('', header))
        kind_rows.append((name, p['objlen'], 3 + 2 * len(p['x']), spr0, p['frames']))

    for label, (sprite, rows, pixels) in RUN_RECORDS.items():
        line = find_label(run, label)
        assert run[line - 1].endswith('DA *+7'), run[line - 1]
        patch('RUN', line, ['%s DA spr_dir+%d' % (label, 4 * sprite_id(ids, sprite)),
                            hexline('', [0, 0, 0, rows, pixels])], end=line + 2)

    for label, values in FLIPPER_TABLES.items():
        line = find_label(run, label)
        patch('RUN', line, [hexline(label, values[:8]), hexline('', values[8:])], end=line + 1)

    Path(args.patches).write_text(json.dumps(patches, indent=1))

    out = ['; Generated by tools/kinds.py. Do not edit.',
           '; The part kinds in the editor\'s kit order: template address, record',
           '; length, L-record offset, first sprite, frames.',
           '.setcpu "65C02"',
           '.export kind_tmpl_lo, kind_tmpl_hi, kind_len, kind_loff, kind_spr0, kind_frames, KIND_COUNT',
           '.import ' + ', '.join('RUN_' + r[0] for r in kind_rows),
           'KIND_COUNT = %d' % len(kind_rows),
           '.segment "RODATA"',
           'kind_tmpl_lo:']
    out += ['        .byte <RUN_%s' % r[0] for r in kind_rows]
    out.append('kind_tmpl_hi:')
    out += ['        .byte >RUN_%s' % r[0] for r in kind_rows]
    out.append('kind_len:')
    out.append('        .byte ' + ','.join(str(r[1]) for r in kind_rows))
    out.append('kind_loff:')
    out.append('        .byte ' + ','.join(str(r[2]) for r in kind_rows))
    out.append('kind_spr0:')
    out.append('        .byte ' + ','.join(str(r[3]) for r in kind_rows))
    out.append('kind_frames:')
    out.append('        .byte ' + ','.join(str(r[4]) for r in kind_rows))
    Path(args.out).write_text('\n'.join(out) + '\n')


if __name__ == '__main__':
    main()
