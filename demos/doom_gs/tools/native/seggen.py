#!/usr/bin/env python3
"""The seg loops of the native renderer (docs/RENDER.md): our own
generator of the 13 loops that upstream's R_RenderSegLoop takes for the
kinds of segs it draws most
(r_seg65.s:565-575, the loops of segvar.inc:27-247).

Usage:  python3 tools/native/seggen.py OUT/segloops.s

Each loop runs over the columns SD_X .. X2END - 1 of a seg with the same
rows, records, clips and spans as upstream's loop of that kind. A loop
is one of these flags (segvar.inc):

    ONE   a single sided line (its mid texture)
    TOP   a top wall of a two sided line
    BOT   a bottom wall
    MC    markceiling (the ceiling fill; a sky ceiling too)
    MF    markfloor (the floor fill)

and the kinds are 1 TOP | 2 BOT | 4 MC | 8 MF, or 16 ONE | the marks
(`KINDS`: the 13 that upstream gives a loop of their own; the others take
genColumn, rseg.s's genloop). What the template keeps of upstream's, and
why each is exact:

  - the rows are bytes, 0-169 (the clips + 1 are bytes, segvar.inc);
  - the edges step with STEP8E, bytes 1-3 only (rseg.inc), so an edge
    keeps its byte 0 as upstream's does; a column whose floor clip + 1 is
    0 (closed) goes to genColumn (gencol), which steps them with STEP32;
  - a tier calls texCol only when its column has none yet (upstream's
    C17 continuations and TIER's `cpx W_TCX` do the same);
  - the scale is not stepped here: far_fstep has each column's (rseg.s).

The output uses rseg.inc's macros and rseg.s's routines; it has no
self-modified byte (docs/RENDER.md: upstream's C17 patch is static here).
"""

import sys
from pathlib import Path
from typing import List, NamedTuple, Sequence


class Kind(NamedTuple):
    name: str
    one: bool
    top: bool
    bot: bool
    mc: bool
    mf: bool

    @property
    def number(self) -> int:
        """The kind as upstream's R_RenderSegLoop computes it."""
        k = (8 if self.mf else 0) + (4 if self.mc else 0)
        if self.one:
            return k + 16
        return k + (2 if self.bot else 0) + (1 if self.top else 0)


# The 13 loops of r_seg65.s (v04 there, v02 and v07 in segmore, the rest
# in segwalls): segvar.inc's flags for each.
KINDS = (
    Kind('v02', False, False, True, False, False),
    Kind('v04', False, False, False, True, False),
    Kind('v05', False, True, False, True, False),
    Kind('v06', False, False, True, True, False),
    Kind('v07', False, True, True, True, False),
    Kind('v08', False, False, False, False, True),
    Kind('v10', False, False, True, False, True),
    Kind('v12', False, False, False, True, True),
    Kind('v13', False, True, False, True, True),
    Kind('v14', False, False, True, True, True),
    Kind('v15', False, True, True, True, True),
    Kind('v20', True, False, False, True, False),
    Kind('v28', True, False, False, True, True),
)
VIEWHEIGHT = 168


def loop(k: Kind) -> List[str]:
    """One loop (segvar.inc's template with k's flags)."""
    o = []

    def op(text: str, comment: str = '') -> None:
        o.append(('        %-24s; %s' % (text, comment)).rstrip()
                 if comment else '        ' + text)

    def label(name: str) -> None:
        o.append('%s:' % name)

    label(k.name)
    op('ldx SD_X')
    label('@col')
    op('lda FLOORCLIP,x', 'the floor clip + 1')
    op('bne @open')
    op('jsr gencol', 'closed: genColumn')
    op('jmp @next')
    label('@open')
    op('sta FC')
    op('dec a')
    op('sta FCR')
    op('lda CEILCLIP,x', 'the ceiling clip + 1')
    op('sta CT')
    if k.mc or k.top or k.one:
        op('STEP8E TF, TS', 'yl = max(the top edge, ct), at most 169')
        op('bmi @r1', '(above row 0: ct)')
        op('bne @r2', '(row 256 or more: 169)')
        op('lda TF+2')
        op('cmp CT')
        op('bcc @r1')
        op('cmp #%d' % (VIEWHEIGHT + 2))
        op('bcc @r3')
        label('@r2')
        op('lda #%d' % (VIEWHEIGHT + 1))
        op('bra @r3')
        label('@r1')
        op('lda CT')
        label('@r3')
        op('sta YL')
        if k.bot and k.mc and not k.top and not k.one:
            op('sta DCROW', 'yl stays here: drawbot takes YL')
    if k.mf or k.bot or k.one:
        op('STEP8E BF, BS', 'yh + 1 = min(the bottom edge, fc)')
        op('bmi @r4', '(above row 0: -1)')
        op('bne @r5', '(row 256 or more: fc)')
        op('lda BF+2')
        op('cmp FC')
        op('bcs @r5')
        op('inc a')
        op('bra @r6')
        label('@r4')
        op('lda #0')
        op('bra @r6')
        label('@r5')
        op('lda FC')
        label('@r6')
        op('sta YH1')
    if k.mc:
        op('lda YL', 'the ceiling: rows ct .. min(yl, fc) - 1')
        op('cmp FC')
        op('bcc @r7')
        op('lda FCR')
        label('@r7')
        op('sta CB1')
        op('cmp CT')
        op('beq @r73')
        op('bcc @r73')
        op('jsr ceilfill')
        label('@r73')
        cc1 = 'CB1'
    else:
        cc1 = 'CT'
    if k.mf:
        op('lda %s' % cc1, 'the floor: rows max(yh + 1, cc) .. fc - 1')
        op('cmp YH1')
        op('bcs @r9')
        op('lda YH1')
        op('dec a')
        label('@r9')
        op('sta FT')
        op('inc a')
        op('cmp FC')
        op('bcs @r93')
        op('jsr floorfill')
        label('@r93')
        vfc = 'FT'
    else:
        vfc = 'FCR'
    if k.one:
        op('lda YH1', 'the mid wall: rows yl .. yh')
        op('clc')
        op('sbc YL')
        op('beq @r11')
        op('bcc @r11')
        op('sta DCCOUNT')
        op('jsr drawmid')
        label('@r11')
        op('lda #%d' % (VIEWHEIGHT + 1), 'closed: ceiling clip 168,')
        op('sta CEILCLIP,x', '  floor clip -1')
        op('stz FLOORCLIP,x')
    else:
        if k.top:
            op('STEP8E PH, PHS', 'the top wall: rows yl .. mid')
            op('bmi @r13', '(above row 0: no rows)')
            op('bne @r121', '(row 256 or more: fc)')
            op('lda PH+2')
            op('cmp %s' % vfc)
            op('bcc @r12')
            label('@r121')
            op('lda %s' % vfc)
            label('@r12')
            op('sta MID1')
            op('sec')
            op('sbc YL')
            op('beq @r13')
            op('bcc @r13')
            op('sta DCCOUNT')
            op('jsr drawtop')
            op('lda MID1')
            op('bra @r14')
            label('@r13')
            op('lda YL')
            label('@r14')
            op('sta CC1', 'cc + 1')
            cc1r = 'CC1'
        elif k.mc:
            cc1r = 'DCROW' if k.bot else 'YL'
        else:
            cc1r = 'CT'
        if k.bot:
            op('STEP8E PL, PLS', 'the bottom wall: rows mid .. yh')
            op('bmi @r15', '(above row 0: cc + 1)')
            op('bne @r151', '(row 256 or more: 169)')
            op('lda PL+2')
            op('cmp %s' % cc1r)
            op('bcs @r16')
            label('@r15')
            op('lda %s' % cc1r)
            op('bra @r16')
            label('@r151')
            op('lda #%d' % (VIEWHEIGHT + 1))
            label('@r16')
            op('sta MID')
            op('lda YH1')
            op('clc')
            op('sbc MID')
            op('beq @r17')
            op('bcc @r17')
            op('sta DCCOUNT')
            op('lda MID', 'the tier takes its row from YL')
            op('sta YL')
            op('jsr drawbot')
            op('lda MID', 'fc + 1 = mid + 1')
            op('inc a')
            op('bra @r18')
            label('@r17')
            op('lda YH1')
            label('@r18')
            op('sta FC1')
            fc1r = 'FC1'
        elif k.mf:
            fc1r = 'YH1'
        else:
            fc1r = 'FC'
        if k.mc or k.mf:
            op('lda %s' % cc1r, 'solid when fc <= cc + 1')
            op('inc a')
            op('cmp %s' % fc1r)
            op('bcc @r20')
            op('jsr solidcol')
            label('@r20')
        op('lda %s' % fc1r, 'the new clips + 1')
        op('sta FLOORCLIP,x')
        op('lda %s' % cc1r)
        op('sta CEILCLIP,x')
    label('@next')
    op('inx')
    op('cpx X2END')
    op('bcs @done')
    op('jmp @col')
    label('@done')
    op('jmp segdone')
    return o


def source(kinds: Sequence[Kind] = KINDS) -> str:
    head = [
        '; segloops.s: the 13 seg loops of the native renderer, generated by',
        '; tools/native/seggen.py (docs/RENDER.md). Do not edit.',
        '; A GPL-2 derivative of upstream\'s segvar.inc (the same rows, '
        'records,',
        '; clips and spans).',
        '',
        '        .setcpu "65C02"',
        '        .include "rlayout.inc"',
        '        .include "rseg.inc"',
        '',
        '        .import gencol, segdone, ceilfill, floorfill, solidcol',
        '        .import drawmid, drawtop, drawbot',
        '        .export %s' % ', '.join(k.name for k in kinds),
        '',
        '        .segment "RENDERW"',
        '']
    body = []
    for k in kinds:
        body.append('; %s: kind %d (%s)' % (k.name, k.number, ', '.join(
            f for f, v in zip(('ONE', 'TOP', 'BOT', 'MC', 'MF'),
                              (k.one, k.top, k.bot, k.mc, k.mf)) if v)))
        body += loop(k)
        body.append('')
    return '\n'.join(head + body) + '\n'


def main(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        print('usage: seggen.py OUT/segloops.s', file=sys.stderr)
        return 2
    names = [k.name for k in KINDS]
    if names != ['v%02d' % k.number for k in KINDS]:
        print('seggen: a loop is not named after its kind', file=sys.stderr)
        return 1
    Path(argv[0]).parent.mkdir(parents=True, exist_ok=True)
    Path(argv[0]).write_text(source())
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
