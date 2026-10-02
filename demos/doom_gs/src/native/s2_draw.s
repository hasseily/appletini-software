; s2_draw.s: the 2D drawers into a band (docs/SCREENS.md 1.2, 1.4; part
; s2draw, docs/m11-parts/s2draw.md). A shared object, linked into every
; 2D image that draws (P2DW, MENUW, WIW, FINW). Written from upstream's
; src/iigs/patch65.s (IIGS_DrawPatch, markPatch, capPost) and
; src/iigs/i_viigs65.s (V_DrawPatchNotScaled, V_DrawRaw's drawRawData and
; pairByte, V_DrawBackground, markRect, markRows, rectOffset and
; copyToBuffer), with upstream's back buffer replaced by a band of rows in
; W and its far data by RamWorks through far_get.
;
;   s2_patch    IIGS_DrawPatch: the patch at S2_PBANK:S2_PADDR (Doom's
;               format) at S2_X, S2_Y, its rectangle marked (markPatch),
;               every pixel by upstream's nibble rule, clipped to 320 x
;               200 as upstream and to the band's rows; with S2_CAP's bit
;               7, each byte written also into CAPVAL and CAPMSK (capPost)
;   s2_vpatch   V_DrawPatchNotScaled: S2_X, S2_Y less the patch's offsets,
;               then s2_patch
;   s2_raw      drawRawData of whole rows: the rows S2_RY0 .. S2_RY1 - 1
;               of 8-bit pixel pairs (320 a row) from S2_PBANK:S2_PADDR,
;               each pair through pairByte; the rows marked whole
;   s2_back     V_DrawBackground: the 64 x 64 flat at S2_PBANK:S2_PADDR
;               tiled over the band's rows, marked whole
;   s2_rect     copyToBuffer by rows (I_RestoreStatusRect's copy, a
;               picture's pixels): the rows S2_RY0 .. S2_RY1 - 1, bytes
;               S2_RB0 .. S2_RB1, from S2_PBANK:S2_PADDR + row * 160, and
;               their mark (markVP)
;   s2_mark     markRect: A = the first row, X = the row after the last,
;               S2_MB0 .. S2_MB1 the bytes, clipped to the band
;   s2_markp    markPatch alone: the rectangle of S2_X, S2_Y (the offsets
;               applied), S2_W, S2_H clipped to the screen, then marked
;               (s2_mark); nothing drawn (part s2stbar's marking pass,
;               request S2STBAR-5)
;   s2_unmark   the band's marks cleared
;
; The patch's columns come from RamWorks: each column's offset by a
; far_get of 2 bytes, its posts through the fetch buffer, refilled from the
; column when the 256 bytes from its start are not in it (a column of a 2D
; patch is at most 256 bytes: tools/native/s2draw.py checks every one).
; A source lies in its bank's $0200-$BFFF (a RAMRD window reaches nothing
; else), a patch's last column the fetch buffer's size before $C000. As
; upstream, a post off the screen (row >= 200, or negative) ends its
; column.
;
; The zero page S2_* (the arguments, the band's state and the
; temporaries, $48-$77) is s2layout.py's (S2_ZP, in s2.inc). The band:
; S2_BAND is the W address of its first row, which is the screen row
; S2_Y0; it holds the rows S2_Y0 .. S2_Y1 - 1 (at most 64), 160 bytes a
; row. Every drawer clips to those rows, as upstream's clips to 200.
;
; The image provides, by exported symbols (its places are s2layout.py's
; DRAW_PLACES, IMAGE_MARKS, IMAGE_FBUF, IMAGE_FBPAGES in s2.inc):
;
;   s2_marks    a page: DRB +$00, DRE +$40 (upstream's marks of each band
;               row: the first byte, the last + 1, DRE 0: none), ROWL +$80,
;               ROWR +$C0 (each band row's nibble table page in W for the
;               left and the right pixel of a byte: upstream's
;               iigs_rowpageL/R, the palette's slot instead of NIBTAB;
;               pairByte reads ROWL for the left pixel and ROWR for the
;               right, upstream's rowbase and rowbase + $200)
;   s2_fbuf     the fetch buffer (page aligned) and s2_fbpages its pages
;               (at least 2)
;   s2_begun    a byte: s2_begin has run in this frame (s2_pub.s; PALST's
;               PS_BEGUN in the images that keep PALST)
;   s2_begin    the palettes and SCBs before the frame's first band
;               (part s2pal; s2_beginstub.s in the test images)
;
; The inner loops patch their own operands (the row table, the nibble
; table's page, the mask): W is RAM and loaded every frame.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"

        .export s2_patch, s2_vpatch, s2_raw, s2_back, s2_rect, s2_mark
        .export s2_unmark, s2_markp
        .import far_get, s2_mul160, s2_marks, s2_fbuf
        .importzp s2_fbpages

DRB  = s2_marks
DRE  = s2_marks + $40
ROWL = s2_marks + $80
ROWR = s2_marks + $C0

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; fetch: FA_N bytes (0: 256) of the source at the offset S2_O to FA_DST.
; Changes A, Y.
; ---------------------------------------------------------------------------
fetch:
        clc
        lda S2_O
        adc S2_PADDR
        sta FA_SRC
        lda S2_O+1
        adc S2_PADDR+1
        sta FA_SRC+1
        lda S2_PBANK
        sta FA_BANK
        jmp far_get

; header: the patch's width, height, left and top offsets
header:
        stz S2_O
        stz S2_O+1
        lda #S2_W
        sta FA_DST
        stz FA_DST+1
        lda #8
        sta FA_N
        bra fetch

; ---------------------------------------------------------------------------
; s2_vpatch, s2_patch
; ---------------------------------------------------------------------------
s2_vpatch:
        jsr header
        ldx #2                  ; S2_Y, then S2_X, less the offsets
:       sec
        lda S2_X,x
        sbc S2_LOFS,x
        sta S2_X,x
        lda S2_X+1,x
        sbc S2_LOFS+1,x
        sta S2_X+1,x
        dex
        dex
        bpl :-
        bra draw
s2_patch:
        jsr header
draw:
        jsr markpatch
        lda #$C0                ; the fetch buffer holds nothing
        sta S2_BLO+1
        stz S2_COL
        stz S2_COL+1
        bra column
nextcol:
        inc S2_COL
        bne column
        inc S2_COL+1
column:
        lda S2_COL              ; each column
        cmp S2_W
        lda S2_COL+1
        sbc S2_W+1
        bcc :+
        rts
:       clc                     ; x = S2_X + col: drawn if 0 <= x < 320
        lda S2_X
        adc S2_COL
        sta S2_LEFT
        lda S2_X+1
        adc S2_COL+1
        beq @lo
        cmp #1
        bne nextcol
        lda S2_LEFT
        cmp #$40
        bcs nextcol
        sec                     ; (x's ninth bit)
        bra @half
@lo:    clc
@half:  ror S2_LEFT             ; the byte; C = the pixel's side
        lda #$0F                ; the left pixel keeps the right nibble
        ldx #<ROWL
        bcc :+
        lda #$F0                ; the right pixel keeps the left nibble
        ldx #<ROWR
:       sta S2_MASK
        sta mk+1
        stx S2_RT
        lda S2_COL+1            ; the column's offset: columnofs[col]'s
        sta S2_O+1              ;   low word, at 8 + 4 * col
        lda S2_COL
        asl a
        rol S2_O+1
        asl a
        rol S2_O+1
        clc
        adc #8
        sta S2_O
        bcc :+
        inc S2_O+1
:       lda #S2_COLP
        sta FA_DST
        stz FA_DST+1
        lda #2
        sta FA_N
        jsr fetch
        sec                     ; its 256 bytes in the fetch buffer?
        lda S2_COLP
        sbc S2_BLO
        tax
        lda S2_COLP+1
        sbc S2_BLO+1
        bcc @fill
        cmp #<(s2_fbpages - 1)
        bcc @in
@fill:  lda S2_COLP             ; no: the buffer from the column on
        sta S2_BLO
        sta S2_O
        lda S2_COLP+1
        sta S2_BLO+1
        sta S2_O+1
        stz FA_DST
        lda #>s2_fbuf
        sta FA_DST+1
        stz FA_N
        ldx #<s2_fbpages
:       jsr fetch
        inc S2_O+1
        inc FA_DST+1
        dex
        bne :-
        txa                     ; (A:X = 0)
@in:    stx S2_COLP
        clc
        adc #>s2_fbuf
        sta S2_COLP+1

post:   lda (S2_COLP)           ; each post: topdelta, length, pad, data
        cmp #$FF
        bne :+
        jmp nextcol
:       clc                     ; row = topdelta + y: drawn if < 200
        adc S2_Y
        sta S2_ROW
        lda #0                  ; (upstream: the column ends at a post
        adc S2_Y+1              ;   off the screen)
        bne @col
        lda S2_ROW
        cmp #200
        bcs @col
        ldy #1                  ; the end: min(row + length, the band's)
        lda (S2_COLP),y
        clc
        adc S2_ROW
        bcs :+
        cmp S2_Y1
        bcc :++
:       lda S2_Y1
:       sta S2_CNT
        lda S2_ROW              ; the start: max(row, the band's)
        cmp S2_Y0
        bcs :+
        lda S2_Y0
:       cmp S2_CNT
        bcc :+
        jmp skip
@col:   jmp nextcol
:       tax
        eor #$FF                ; the count: end - start
        sec
        adc S2_CNT
        sta S2_CNT
        txa                     ; the first data: 3 + start - row
        sec
        sbc S2_ROW
        clc
        adc #3
        sta S2_T
        txa                     ; the band row
        sec
        sbc S2_Y0
        pha
        jsr s2_mul160
        clc
        adc S2_BAND
        sta S2_DEST
        txa
        adc S2_BAND+1
        sta S2_DEST+1
        clc
        lda S2_DEST
        adc S2_LEFT
        sta S2_DEST
        bcc :+
        inc S2_DEST+1
:       pla                     ; the row table, less the first data's
        clc                     ;   index (upstream's NTP)
        adc S2_RT
        sec
        sbc S2_T
        sta rt+1
        lda #>ROWL
        sbc #0
        sta rt+2
        ldy S2_T
pixel:
rt:     lda $FF00,y             ; the row's nibble table page
        sta nt+2
        lda (S2_COLP),y         ; the colour
        tax
nt:     lda $FF00,x             ; its nibble
        sta S2_T
        lda (S2_DEST)
mk:     and #$0F
        ora S2_T
        sta (S2_DEST)
        bit S2_CAP
        bmi capture
next:   clc                     ; the next row
        lda S2_DEST
        adc #160
        sta S2_DEST
        bcc :+
        inc S2_DEST+1
:       iny
        dec S2_CNT
        bne pixel

skip:   ldy #1                  ; the next post: + length + 4
        lda (S2_COLP),y
        clc
        adc #4
        bcc :+
        inc S2_COLP+1
:       clc
        adc S2_COLP
        sta S2_COLP
        bcc :+
        inc S2_COLP+1
:       jmp post

; capPost's byte: CAPVAL = CAPVAL & mask | nibble, CAPMSK |= ~mask
capture:
        clc
        lda S2_DEST
        adc S2_CAPD
        sta S2_CP
        lda S2_DEST+1
        adc S2_CAPD+1
        sta S2_CP+1
        lda (S2_CP)
        and S2_MASK
        ora S2_T
        sta (S2_CP)
        clc
        lda S2_CP
        adc S2_CAPM
        sta S2_CP
        lda S2_CP+1
        adc S2_CAPM+1
        sta S2_CP+1
        lda S2_MASK
        eor #$FF
        ora (S2_CP)
        sta (S2_CP)
        bra next

; markPatch: x .. x + w - 1, y .. y + h - 1 clipped to the screen
s2_markp:
markpatch:
        lda S2_X                ; the first byte: max(x, 0) / 2, none
        ldx S2_X+1              ;   from 320
        bpl :+
        lda #0
        tax
:       cpx #2
        bcs @none
        cpx #1
        bne :+
        cmp #$40
        bcs @none
:       cpx #1
        ror a
        sta S2_MB0
        clc                     ; the last: min(x + w - 1, 319) / 2,
        lda S2_X                ;   none below 0 or the first
        adc S2_W
        tay
        lda S2_X+1
        adc S2_W+1
        tax
        tya
        sec
        sbc #1
        bcs :+
        dex
:       cpx #$80
        bcs @none
        cpx #2
        bcs @max
        cpx #1
        bne @half
        cmp #$40
        bcc @half
@max:   lda #<319
        ldx #1
@half:  cpx #1
        ror a
        cmp S2_MB0
        bcc @none
        sta S2_MB1
        clc                     ; the rows: max(y, 0) .. min(y + h, 200)
        lda S2_Y
        adc S2_H
        tay
        lda S2_Y+1
        adc S2_H+1
        bmi @none
        bne @200
        tya
        beq @none
        cmp #200
        bcc :+
@200:   lda #200
:       tax
        lda S2_Y+1
        bmi @zero
        bne @none
        lda S2_Y
        bra s2_mark
@zero:  lda #0
        bra s2_mark
@none:  rts

; ---------------------------------------------------------------------------
; s2_mark: markRect of the rows A .. X - 1, bytes S2_MB0 .. S2_MB1, in the
; band's rows only
; ---------------------------------------------------------------------------
s2_mark:
        cmp S2_Y0
        bcs :+
        lda S2_Y0
:       cpx S2_Y1
        bcc :+
        ldx S2_Y1
:       stx S2_CNT
        cmp S2_CNT
        bcs @done
        sec
        sbc S2_Y0
        tay                     ; the band rows Y .. S2_CNT - 1
        txa
        sec
        sbc S2_Y0
        sta S2_CNT
        lda S2_DRY1             ; the rows with marks grow
        bne @grow
        sty S2_DRY0
        lda S2_CNT
        sta S2_DRY1
        bra @rows
@grow:  cpy S2_DRY0
        bcs :+
        sty S2_DRY0
:       lda S2_CNT
        cmp S2_DRY1
        bcc @rows
        sta S2_DRY1
@rows:  ldx S2_MB1
        inx
@row:   lda DRE,y
        bne @old
        lda S2_MB0
        sta DRB,y
        txa
        sta DRE,y
        bra @next
@old:   lda S2_MB0
        cmp DRB,y
        bcs :+
        sta DRB,y
:       txa
        cmp DRE,y
        bcc @next
        sta DRE,y
@next:  iny
        cpy S2_CNT
        bcc @row
@done:  rts

s2_unmark:
        ldx #$3F
:       stz DRE,x
        dex
        bpl :-
        stz S2_DRY0
        stz S2_DRY1
        rts

; ---------------------------------------------------------------------------
; pairs: S2_CNT bytes at S2_DEST from the pixel pairs at S2_COLP (pairByte:
; ROWL's table of the band row X for the left pixel, ROWR's for the right)
; ---------------------------------------------------------------------------
pairs:
        lda ROWL,x
        sta pl+2
        lda ROWR,x
        sta pr+2
        ldy #0
pairl:  lda (S2_COLP)
        tax
pl:     lda $FF00,x
        sta S2_M
        inc S2_COLP
        bne :+
        inc S2_COLP+1
:       lda (S2_COLP)
        tax
pr:     lda $FF00,x
        ora S2_M
        sta (S2_DEST),y
        inc S2_COLP
        bne :+
        inc S2_COLP+1
:       iny
        cpy S2_CNT
        bne pairl
        rts

; rowdest: S2_DEST = the band row A's first byte
rowdest:
        jsr s2_mul160
        clc
        adc S2_BAND
        sta S2_DEST
        txa
        adc S2_BAND+1
        sta S2_DEST+1
        rts

; ---------------------------------------------------------------------------
; s2_raw: drawRawData of whole rows: the rows S2_RY0 .. S2_RY1 - 1 from the
; lump's 320 pixels a row (upstream's offset S2_RY0 * 320, length
; (S2_RY1 - S2_RY0) * 320: the status bar and the full screens), then
; markRows(S2_RY0, S2_RY1)
; ---------------------------------------------------------------------------
s2_raw:
        lda S2_RY0              ; the rows in the band
        cmp S2_Y0
        bcs :+
        lda S2_Y0
:       sta S2_ROW
@row:   lda S2_ROW
        cmp S2_RY1
        bcs @end
        cmp S2_Y1
        bcs @end
        sec                     ; its 320 bytes at (row - S2_RY0) * 320
        sbc S2_RY0
        jsr s2_mul160
        asl a
        sta S2_O
        txa
        rol a
        sta S2_O+1
        stz FA_DST
        lda #>s2_fbuf
        sta FA_DST+1
        sta S2_COLP+1
        stz S2_COLP
        stz FA_N
        jsr fetch
        inc S2_O+1
        inc FA_DST+1
        lda #64
        sta FA_N
        jsr fetch
        lda S2_ROW              ; through pairByte into the band's row
        sec
        sbc S2_Y0
        pha
        jsr rowdest
        lda #160
        sta S2_CNT
        plx
        jsr pairs
        inc S2_ROW
        bra @row
@end:   lda S2_RY0
        ldx S2_RY1
whole:  stz S2_MB0
        ldy #159
        sty S2_MB1
        jmp s2_mark

; ---------------------------------------------------------------------------
; s2_back: V_DrawBackground in the band's rows
; ---------------------------------------------------------------------------
s2_back:
        stz S2_ROW              ; the band row
@row:   lda S2_ROW
        clc
        adc S2_Y0
        cmp S2_Y1
        bcs @end
        and #63                 ; the flat's row (y & 63) * 64
        sta S2_O+1
        lda #0
        lsr S2_O+1
        ror a
        lsr S2_O+1
        ror a
        sta S2_O
        stz FA_DST
        lda #>s2_fbuf
        sta FA_DST+1
        lda #64
        sta FA_N
        jsr fetch
        stz S2_COLP             ; its 32 bytes at the buffer's second page
        lda #>s2_fbuf
        sta S2_COLP+1
        stz S2_DEST
        inc a
        sta S2_DEST+1
        lda #32
        sta S2_CNT
        ldx S2_ROW
        jsr pairs
        lda S2_ROW              ; 5 times in the row
        jsr rowdest
        ldx #0
        ldy #0
:       lda s2_fbuf+$100,x
        sta (S2_DEST),y
        inx
        txa
        and #31
        tax
        iny
        cpy #160
        bne :-
        inc S2_ROW
        bra @row
@end:   lda S2_Y0
        ldx S2_Y1
        bra whole

; ---------------------------------------------------------------------------
; s2_rect: copyToBuffer, a row at a time, then markVP
; ---------------------------------------------------------------------------
s2_rect:
        lda S2_RB1
        cmp S2_RB0
        bcc @none
        lda S2_RY0              ; the rows in the band
        cmp S2_Y0
        bcs :+
        lda S2_Y0
:       sta S2_ROW
@row:   lda S2_ROW
        cmp S2_RY1
        bcs @mark
        cmp S2_Y1
        bcs @mark
        jsr s2_mul160           ; the source: row * 160 + b0
        clc
        adc S2_RB0
        sta S2_O
        txa
        adc #0
        sta S2_O+1
        lda S2_ROW              ; the band's byte
        sec
        sbc S2_Y0
        jsr rowdest
        clc
        lda S2_DEST
        adc S2_RB0
        sta FA_DST
        lda S2_DEST+1
        adc #0
        sta FA_DST+1
        lda S2_RB1
        sec
        sbc S2_RB0
        inc a
        sta FA_N
        jsr fetch
        inc S2_ROW
        bra @row
@mark:  lda S2_RB0
        sta S2_MB0
        lda S2_RB1
        sta S2_MB1
        lda S2_RY0
        ldx S2_RY1
        jmp s2_mark
@none:  rts
