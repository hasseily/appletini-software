#!/usr/bin/env python3
"""Read the part templates of the upstream RUN.S and describe them.

The parts library at the end of RUN.S (POLY .. MAG1) is the editor's kit:
each template is an object record (id, fill colour, vertices) followed, for
library objects, by the L-record (bitmap header, stride, TIME mask,
score/noise byte, RUN/INIT/HIT vectors). This module parses those records,
the flipper frame tables (FXDVERT/FXHEIGHT/FDDVERT/FHEIGHT/FFRAMEn/SFRAMEn)
and EDIT.S's OBJLEN table, and returns them as Python data. It is used by
the asset brief (`--brief`), the kind table generator and the tests.

    python3 tools/parts.py UPSTREAM --json build/parts.json
    python3 tools/parts.py UPSTREAM --brief          # text for the artists
"""

import argparse
import json
import re
from pathlib import Path

# Frames per part (from the bitmap block sizes of the original: every part's
# frames are consecutive blocks of L-record byte 7 bytes; the flippers use
# the FXLEN table). Verified against the RUN.S behaviour routines.
FRAMES = {
    'LAUNCHER': 6, 'LEFTFLIPPER': 8, 'RIGHTFLIPPER': 8, 'BALL': 1,
    'BMP1': 2, 'BMP2': 2, 'BMP3': 2, 'BMP4': 2, 'BMP5': 2, 'BMP6': 2,
    'LKICK': 2, 'RKICK': 2, 'KICK1': 3, 'KICK2': 3,
    'ROLL1': 2, 'ROLL2': 2, 'ROLL3': 2,
    'TARG1': 2, 'TARG2': 2, 'TARG3': 2, 'TARG4': 2, 'TARG5': 2, 'TARG6': 2,
    'LFLIPPER2': 8, 'RFLIPPER2': 8,
    'LANE1': 1, 'LANE2': 1, 'LANE3': 1,
    'GATE1': 1, 'GATE2': 1, 'GATE3': 1, 'GATE4': 1,
    'DROP1': 1, 'DROP2': 1, 'CATCH1': 1, 'CATCH2': 5, 'SPIN1': 3, 'MAG1': 1,
}

# The editor's kit order (EDIT.S OBJADDRLO/HI and OBJLEN, 43 entries).
KIT_ORDER = [
    'POLY', 'LAUNCHER', 'LEFTFLIPPER', 'RIGHTFLIPPER', 'BALL',
    'BMP1', 'BMP2', 'BMP3', 'BMP4', 'BMP5', 'BMP6',
    'LKICK', 'RKICK', 'KICK1', 'KICK2', 'ROLL1', 'ROLL2', 'ROLL3',
    'TARG1', 'TARG2', 'TARG3', 'TARG4', 'TARG5', 'TARG6',
    'LFLIPPER2', 'RFLIPPER2', 'POLY1', 'POLY2', 'POLY3', 'POLY4',
    'LANE1', 'LANE2', 'LANE3', 'GATE1', 'GATE2', 'GATE3', 'GATE4',
    'DROP1', 'DROP2', 'CATCH1', 'CATCH2', 'SPIN1', 'MAG1',
]

# Sprite box rows above the L-record y for the flippers: their raised
# frames reach above the rest position (cumulative FXDVERT plus FDDVERT).
HOT_Y = {'LEFTFLIPPER': 4, 'RIGHTFLIPPER': 4, 'LFLIPPER2': 3, 'RFLIPPER2': 3}
# Sprite boxes (width, height) that differ from the original HGR byte box.
BOX = {'LEFTFLIPPER': (20, 16), 'RIGHTFLIPPER': (20, 16),
       'LFLIPPER2': (14, 11), 'RFLIPPER2': (14, 11),
       'LKICK': (22, 27), 'RKICK': (22, 27), 'BALL': (5, 5)}


def hex_bytes(arg):
    return bytes.fromhex(arg.replace(',', ''))


def read_source(upstream, name):
    for sub in ('source_disc1', 'source_disc2', ''):
        p = Path(upstream) / sub / name
        if p.exists():
            return p.read_text().splitlines()
    raise FileNotFoundError(name)


def parse_templates(lines):
    """Return the templates in source order as dicts."""
    start = next(i for i, l in enumerate(lines) if 'PINBALL PARTS LIBRARY' in l)
    parts = []
    cur = None
    for line in lines[start + 1:]:
        if line.startswith('*'):
            continue
        if line[0] != ' ':
            label, op, arg = (line.split(None, 2) + [''])[:3]
            cur = {'name': label, 'bytes': [], 'words': []}
            parts.append(cur)
        else:
            op, arg = (line.split(None, 1) + [''])[:2]
        arg = arg.split(';')[0].strip()
        if op == 'HEX':
            cur['bytes'].append(hex_bytes(arg))
        elif op == 'DA':
            cur['words'].append(arg)
    out = []
    for p in parts:
        data = b''.join(p['bytes'])
        objid, fill, n = data[0], data[1], data[2]
        xs = list(data[3:3 + n])
        ys = list(data[3 + n:3 + 2 * n])
        rec = {'name': p['name'], 'id': objid, 'fill': fill, 'x': xs, 'y': ys}
        if objid == 3:
            l = data[3 + 2 * n:3 + 2 * n + 8]
            rec.update({
                'bitmap': p['words'][0],
                'y0': l[0], 'x0': l[1] * 7 + l[2], 'h': l[3], 'wbytes': l[4],
                'stride': l[5], 'time': l[6], 'score': l[7],
                'run': p['words'][1], 'init': p['words'][2], 'hit': p['words'][3],
                'extra': list(data[3 + 2 * n + 8:]),
            })
        out.append(rec)
    return out


def parse_table(lines, label, count=None):
    """Bytes of the HEX lines that follow a label (continuation lines too)."""
    i = next(i for i, l in enumerate(lines) if l.startswith(label + ' '))
    data = b''
    for line in lines[i:]:
        if line.startswith('*') or (not line.startswith(' ') and not line.startswith(label + ' ')):
            break
        op, arg = (line.split(None, 2)[1:] + [''])[:2] if not line.startswith(' ') else (line.split(None, 1) + [''])[:2]
        if op == 'HEX':
            data += hex_bytes(arg.split(';')[0].strip())
    return data


def parse_objlen(edit_lines):
    return list(parse_table(edit_lines, 'OBJLEN'))


def flipper_frames(run_lines):
    """Silhouettes of the 8 frames of both flippers, from the hit tables.

    Returns {'big': [frame...], 'small': [...]}, each frame a dict with
    top (rows relative to the rest y), rows: list of (xmin, xmax) pairs
    inclusive, relative to the left edge X[3].
    """
    fxdvert = parse_table(run_lines, 'FXDVERT')
    fddvert = parse_table(run_lines, 'FDDVERT')
    fheight = parse_table(run_lines, 'FHEIGHT')

    def signed(b):
        return b - 256 if b > 127 else b

    out = {}
    for kind, base, prefix in (('big', 0, 'FFRAME'), ('small', 8, 'SFRAME')):
        frames = []
        cum = 0
        for n in range(8):
            if n > 0:
                cum += signed(fxdvert[base + n])
            top = cum + signed(fddvert[base + n])
            rows = fheight[base + n] + 1
            pairs = parse_table(run_lines, '%s%d' % (prefix, n + 1))
            pts = [(pairs[2 * r], pairs[2 * r + 1]) for r in range(rows)]
            frames.append({'top': top, 'rows': pts, 'cum': cum})
        out[kind] = frames
    return out


def silhouette(frame, width, rows_range):
    """ASCII picture of a flipper frame inside its sprite box."""
    lines = []
    for row in range(rows_range[0], rows_range[1] + 1):
        r = row - frame['top']
        if 0 <= r < len(frame['rows']):
            a, b = frame['rows'][r]
            lines.append(''.join('#' if a <= x <= b else '.' for x in range(width)))
        else:
            lines.append('.' * width)
    return lines


def describe(parts, edit_lines, run_lines):
    objlen = parse_objlen(edit_lines)
    by_name = {p['name']: p for p in parts}
    flip = flipper_frames(run_lines)
    result = []
    for kind, name in enumerate(KIT_ORDER):
        p = dict(by_name[name])
        p['kind'] = kind
        p['objlen'] = objlen[kind]
        if p['id'] == 3:
            w, h = BOX.get(name, (p['wbytes'] * 7, p['h']))
            p['box'] = [w, h]
            p['hoty'] = HOT_Y.get(name, 0)
            p['frames'] = FRAMES[name]
            # polygon relative to the sprite box origin (x0, y0 - hoty)
            ox, oy = p['x0'], p['y0'] - p['hoty']
            p['poly_rel'] = [[x - ox, y - oy] for x, y in zip(p['x'], p['y'])]
        result.append(p)
    return result, flip


def brief(parts, flip):
    out = []
    for p in parts:
        if p['id'] != 3:
            out.append('%s (kind %d): polygon only, x %s y %s' % (p['name'], p['kind'], p['x'], p['y']))
            continue
        w, h = p['box']
        out.append('%s (kind %d): box %dx%d at (%d,%d), hot y %d, frames %d, TIME $%02X, score/noise $%02X'
                   % (p['name'], p['kind'], w, h, p['x0'], p['y0'] - p['hoty'], p['hoty'], p['frames'], p['time'], p['score']))
        out.append('  collision polygon (box coordinates): ' + ' '.join('(%d,%d)' % tuple(v) for v in p['poly_rel']))
        out.append('  ' + ' / '.join(('%s' % x) for x in (p['run'], p['init'], p['hit'])))
    for kind, name, width in (('big', 'LEFTFLIPPER', 20), ('small', 'LFLIPPER2', 14)):
        rows_range = (-HOT_Y[name], BOX[name][1] - HOT_Y[name] - 1)
        out.append('')
        out.append('%s flipper collision silhouettes per frame (rows %d..%d relative to the rest y, columns from the left edge):'
                   % (name, rows_range[0], rows_range[1]))
        frames = flip[kind]
        for r_i, row in enumerate(range(rows_range[0], rows_range[1] + 1)):
            cells = []
            for f in frames:
                cells.append(silhouette(f, width, rows_range)[r_i])
            out.append('%4d  ' % row + '  '.join(cells))
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('upstream')
    ap.add_argument('--json')
    ap.add_argument('--brief', action='store_true')
    args = ap.parse_args()
    run_lines = read_source(args.upstream, 'RUN.S')
    edit_lines = read_source(args.upstream, 'EDIT.S')
    parts, flip = describe(parse_templates(run_lines), edit_lines, run_lines)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({'parts': parts, 'flippers': flip}, indent=1))
    if args.brief:
        print(brief(parts, flip))


if __name__ == '__main__':
    main()
