#!/usr/bin/env python3
"""Generate the row blocks and tables of the native replay.

Usage:  python3 tools/native/rowgen.py OUTDIR

Writes, for src/native/replay.s to include (ca65, cc65 2.18):

  OUTDIR/layout.inc   every address and constant of tools/native/layout.py
  OUTDIR/restore.inc  the card runner's PRIVATE copy descriptors
  OUTDIR/rows.s       the segments below

This is our own generator, written from the pixel semantics of the records
(docs/NATIVE.md 5.1; upstream's tools/gendraw.py is not used). Segments:

  TEXBLK   texture row pairs at $D000, 36 bytes a pair of rows 2p, 2p+1:

             even row (15 bytes)          odd row (21 bytes)
             tya                          lda fr
             adc si2                      adc sf2
             and #$7F                     sta fr
             tay                          tya
             lda (src),y                  adc si1
             sta cma                      and #$7F
             lda (cma)                    tay
             sta $2000+160*row,x          lda (src),y
                                          sta cmb
                                          lda (cmb)
                                          sta $2000+160*row,x

           Y is the texel (7 bits), fr the fraction, X the column, carry
           clear. An odd row steps the position exactly by the record's
           step (sf2 is twice the fraction step, si1 the whole step, and
           the even row before it added si2 = the whole step plus the
           rounded carry of twice the fraction): the two rows of a pair
           advance the position by exactly twice the step, and an even
           row takes the rounded half way, as upstream's pair image does.
           Even rows read colormap A (cma), odd rows B (cmb); each
           pointer's low byte is set to the texel, so (cma) is the entry.
           Row 168 is the landing: RTS. The exit row of a record is
           patched to RTS and restored.
  FILLE    fill blocks of the even rows at $DC00, 3 bytes a row:
           sta $2000+160*row,x; landing RTS at $DCFC
  FILLO    the same for the odd rows at $DD00; landing at $DDFC
  MAINTAB  main $0800-$0BFF: CMPA and CMPB (the colormap page of each
           light level), TEXLO and TEXHI (the entry of each row's block)
  AUXTAB   aux bank 0 $0800-$0BFF: FUZZDARK (zero: the loader puts each
           frame's table there), ROWLO, FZDIR, ROWHI

Standard library only.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import layout as L  # noqa: E402


def texture_blocks():
    out = ['; ---- texture row pairs (%d bytes a pair) ----' % L.PAIR_BYTES,
           '.segment "TEXBLK"']
    for pair in range(L.VIEW_ROWS // 2):
        even, odd = 2 * pair, 2 * pair + 1
        out += [
            'tex_row_%d:' % even,
            '        tya',
            '        adc     si2',
            '        and     #$7F',
            '        tay',
            '        lda     (src),y',
            '        sta     cma',
            '        lda     (cma)',
            '        sta     $%04X,x' % L.row_address(even),
            'tex_row_%d:' % odd,
            '        lda     fr',
            '        adc     sf2',
            '        sta     fr',
            '        tya',
            '        adc     si1',
            '        and     #$7F',
            '        tay',
            '        lda     (src),y',
            '        sta     cmb',
            '        lda     (cmb)',
            '        sta     $%04X,x' % L.row_address(odd),
        ]
    out += ['tex_row_%d:' % L.VIEW_ROWS, '        rts', '']
    for row in range(L.VIEW_ROWS + 1):
        out.append('.assert tex_row_%d = $%04X, error, "row block %d"'
                   % (row, L.tex_entry(row), row))
    return out


def fill_blocks(segment, base, parity):
    out = ['; ---- fill blocks of the %s rows ----' % segment[-1:],
           '.segment "%s"' % segment]
    for row in range(parity, L.VIEW_ROWS, 2):
        out.append('        sta     $%04X,x         ; row %d'
                   % (L.row_address(row), row))
    out += ['        rts                     ; landing',
            '.assert * = $%04X, error, "fill landing"'
            % (base + L.FILL_LAND + 1), '']
    return out


def byte_lines(values, per_line=16):
    values = list(values)
    return ['        .byte   ' + ', '.join('$%02X' % v for v in
                                           values[i:i + per_line])
            for i in range(0, len(values), per_line)]


def main_tables():
    out = ['; ---- main $0800-$0BFF ----', '.segment "MAINTAB"',
           'cmpa:']
    out += byte_lines(L.cmap_page_a(level) for level in range(L.CMAP_LEVELS))
    out.append('cmpb:')
    out += byte_lines(L.cmap_page_b(level) for level in range(L.CMAP_LEVELS))
    out += ['        .res    %d' % (L.TEXLO - L.CMPA - 2 * L.CMAP_LEVELS),
            'texlo:']
    rows = ['tex_row_%d' % row for row in range(L.VIEW_ROWS + 1)]
    for i in range(0, len(rows), 8):
        out.append('        .lobytes ' + ', '.join(rows[i:i + 8]))
    out += ['        .res    %d' % (L.TEXHI - L.TEXLO - L.VIEW_ROWS - 1),
            'texhi:']
    for i in range(0, len(rows), 8):
        out.append('        .hibytes ' + ', '.join(rows[i:i + 8]))
    out += ['        .res    %d' % (L.MAIN_TABLES_END - L.TEXHI -
                                  L.VIEW_ROWS - 1),
            '.assert cmpa = $%04X, error, "CMPA"' % L.CMPA,
            '.assert cmpb = $%04X, error, "CMPB"' % L.CMPB,
            '.assert texlo = $%04X, error, "TEXLO"' % L.TEXLO,
            '.assert texhi = $%04X, error, "TEXHI"' % L.TEXHI, '']
    return out


def aux_tables():
    rows = range(200)
    out = ['; ---- aux bank 0 $0800-$0BFF ----', '.segment "AUXTAB"',
           '        .res    256             ; FUZZDARK: the loader\'s',
           'rowlo:']
    out += byte_lines(L.row_address(r) & 0xff for r in rows)
    out.append('fzdir:')
    out += byte_lines(L.FUZZ_DIR)
    out += ['        .res    %d' % (L.ROWHI - L.FZDIR - len(L.FUZZ_DIR)),
            'rowhi:']
    out += byte_lines(L.row_address(r) >> 8 for r in rows)
    out += ['        .res    %d' % (L.AUX_TABLES_END - L.ROWHI - 200),
            '.assert rowlo = $%04X, error, "ROWLO"' % L.ROWLO,
            '.assert fzdir = $%04X, error, "FZDIR"' % L.FZDIR,
            '.assert rowhi = $%04X, error, "ROWHI"' % L.ROWHI, '']
    return out


def rows_text():
    lines = ['; Generated by tools/native/rowgen.py. Do not edit.', '']
    lines += texture_blocks()
    lines += fill_blocks('FILLE', L.FILLE, 0)
    lines += fill_blocks('FILLO', L.FILLO, 1)
    lines += main_tables()
    lines += aux_tables()
    return '\n'.join(lines) + '\n'


def write_if_changed(path, text):
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.splitlines()[2], file=sys.stderr)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    write_if_changed(out / 'layout.inc', L.include_text())
    write_if_changed(out / 'rows.s', rows_text())
    write_if_changed(out / 'restore.inc', L.restore_include())
    return 0


if __name__ == '__main__':
    sys.exit(main())
