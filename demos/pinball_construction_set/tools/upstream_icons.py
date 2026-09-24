#!/usr/bin/env python3
"""Print the upstream 1-bit icons and cursors (EDIT.S, WIRE.S, DISK.S) as text art.

Bitmap records are `LABEL DA *+7` followed by HEX lines: y, x div 7, x mod 7,
height, width in bytes, then height*width HGR bytes (bit 0 = leftmost pixel).
"""
import sys
from pathlib import Path

def records(lines):
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith(' ') and not line.startswith('*'):
            parts = line.split(None, 2)
            if len(parts) >= 3 and parts[1] == 'DA' and parts[2].split(';')[0].strip() == '*+7':
                data = b''
                j = i + 1
                while j < len(lines) and lines[j].startswith(' HEX'):
                    data += bytes.fromhex(lines[j].split(None, 1)[1].split(';')[0].replace(',', '').strip())
                    j += 1
                y, xd, xm, h, w = data[:5]
                bits = data[5:5 + h * w]
                rows = []
                for r in range(h):
                    row = ''
                    for b in range(w):
                        v = bits[r * w + b]
                        row += ''.join('#' if v >> k & 1 else '.' for k in range(7))
                    rows.append(row)
                yield parts[0], (xd * 7 + xm, y), rows
                i = j
                continue
        i += 1

for f in sys.argv[1:]:
    for name, pos, rows in records(Path(f).read_text().splitlines()):
        print('%s %dx%d at %s' % (name, len(rows[0]), len(rows), pos))
        print('\n'.join(rows))
        print()
