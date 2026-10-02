; s2_nib.s: the nibble tables, gamma and a picture's palettes
; (docs/SCREENS.md 1.3, 1.5.7; part s2pal, docs/m11-parts/s2pal.md). The
; shared object s2_nib, linked into MENUW, WIW, FINW and PALW (4.1's size
; table). Written from upstream's src/iigs/i_viigs65.s: buildNibtab,
; gammaColor, drawPicture's palette part (its rows, its palettes with
; gamma, its nibble tables) [R i_viigs65.s:565-610, :705-736,
; :1226-1295].
;
; The 16 nibble tables (upstream's NIBTAB) are S2NIB in bank S2PAL
; (S2P_NIB + palette * $400): a 1 KB table is built in W at s2_nbuf (the
; image's: 4 pages, then the 256 pair bytes at s2_nbuf + $400) and put
; there; the drawers fetch them into their slots.
;
;   s2_nibtab   A = the palette: its table from the pairs at s2_nbuf +
;               $400 (the left pixel's even and odd rows, the right
;               pixel's), into S2NIB; the text cache invalid
;   s2_gamma    the colour S2P_A (a word, $0RGB) through the gamma table
;               of GAMMA (the render input, 0-4)
;   s2_picpal   drawPicture's palette part: A, X = the picture's lump
;               (upstream's picturenum); S2_PBANK:S2_PADDR = its bytes
;               from offset 32,000 (200 SCBs, at +256 its 16 palettes, at
;               +768 its 16 x 256 pairs; within the bank's $0200-$BFFF).
;               Nothing when it is the picture on the screen; else its
;               rows, its palettes with gamma (pictureColors' at the
;               finish: PS_PALCOUNT), its 16 nibble tables
;
; Zero page S2P_A .. S2P_F and FA_*; A, X, Y changed.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2pal.inc"

        .export s2_nibtab, s2_gamma, s2_picpal
        .import s2_palst, s2_nbuf, far_get, far_put

PST     = s2_palst
TAB     = s2_nbuf
PAIRS   = s2_nbuf + $400

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; s2_nibtab: buildNibtab [R i_viigs65.s:705-736].
; ---------------------------------------------------------------------------
s2_nibtab:
        pha
        ldx #0
:       lda PAIRS,x
        and #$F0
        sta TAB,x
        lda PAIRS,x
        asl a
        asl a
        asl a
        asl a
        sta TAB+$100,x
        lda PAIRS,x
        and #$0F
        sta TAB+$200,x
        lda PAIRS,x
        lsr a
        lsr a
        lsr a
        lsr a
        sta TAB+$300,x
        inx
        bne :-
        pla                     ; S2P_NIB + palette * $400
        asl a
        asl a
        clc
        adc #>S2P_NIB
        sta FA_DST+1
        lda #<S2P_NIB
        sta FA_DST
        lda #<TAB
        sta FA_SRC
        lda #>TAB
        sta FA_SRC+1
        lda #S2PAL
        sta FA_BANK
        stz FA_N
        ldx #4
:       jsr far_put
        inc FA_SRC+1
        inc FA_DST+1
        dex
        bne :-
        lda #1                  ; textInvalidate
        sta PST+PS_TXTINV
        rts

; ---------------------------------------------------------------------------
; s2_gamma: gammaColor [R i_viigs65.s:565-610]: each 4-bit channel of
; S2P_A through gammatab's row GAMMA; bits 12-15 cleared.
; ---------------------------------------------------------------------------
s2_gamma:
        lda GAMMA
        asl a
        asl a
        asl a
        asl a
        sta S2P_D               ; the row
        lda S2P_A               ; blue
        and #$0F
        ora S2P_D
        tax
        lda gammatab,x
        sta S2P_E
        lda S2P_A               ; green
        lsr a
        lsr a
        lsr a
        lsr a
        ora S2P_D
        tax
        lda gammatab,x
        asl a
        asl a
        asl a
        asl a
        ora S2P_E
        sta S2P_A
        lda S2P_A+1             ; red
        and #$0F
        ora S2P_D
        tax
        lda gammatab,x
        sta S2P_A+1
        rts

; ---------------------------------------------------------------------------
; s2_picpal: drawPicture's palette part [R i_viigs65.s:1241-1294].
; ---------------------------------------------------------------------------
s2_picpal:
        cmp PST+PS_PICTURE
        bne :+
        cpx PST+PS_PICTURE+1
        bne :+
        rts                     ; the picture on the screen
:       sta PST+PS_PICTURE
        stx PST+PS_PICTURE+1
        lda S2_PBANK            ; its SCBs: the rows' palettes
        sta FA_BANK
        lda S2_PADDR
        sta FA_SRC
        lda S2_PADDR+1
        sta FA_SRC+1
        lda #<(PST+PS_SCB)
        sta FA_DST
        lda #>(PST+PS_SCB)
        sta FA_DST+1
        lda #200
        sta FA_N
        jsr far_get
        inc FA_SRC+1            ; its 16 palettes (+256)
        lda #<(PST+PS_PALETTE)
        sta FA_DST
        sta S2P_B
        lda #>(PST+PS_PALETTE)
        sta FA_DST+1
        sta S2P_B+1
        stz FA_N
        jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        jsr far_get
        ldx #0                  ; with gamma: 256 colours at S2P_B
@pal:   lda (S2P_B)
        sta S2P_A
        ldy #1
        lda (S2P_B),y
        sta S2P_A+1
        phx
        jsr s2_gamma
        plx
        lda S2P_A
        sta (S2P_B)
        ldy #1
        lda S2P_A+1
        sta (S2P_B),y
        inc S2P_B
        inc S2P_B
        bne :+
        inc S2P_B+1
:       inx
        bne @pal
        lda S2_PADDR            ; S2P_B: the pairs (+768)
        sta S2P_B
        lda S2_PADDR+1
        clc
        adc #3
        sta S2P_B+1
        lda #1
        sta PST+PS_SCBCHANGED
        sta PST+PS_PALCOUNT
        stz S2P_F               ; its 16 nibble tables
@nib:   lda S2_PBANK
        sta FA_BANK
        lda S2P_B
        sta FA_SRC
        lda S2P_B+1
        sta FA_SRC+1
        lda #<PAIRS
        sta FA_DST
        lda #>PAIRS
        sta FA_DST+1
        stz FA_N
        jsr far_get
        inc S2P_B+1
        lda S2P_F
        jsr s2_nibtab
        inc S2P_F
        lda S2P_F
        cmp #16
        bne @nib
        rts

        .segment "S2RODATA"

; gammatab [R i_viigs65.s:178-182]
gammatab:
        .byte 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15
        .byte 0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 12, 13, 14, 15
        .byte 0, 2, 4, 5, 6, 7, 8, 9, 10, 10, 11, 12, 13, 14, 14, 15
        .byte 0, 3, 4, 5, 7, 8, 8, 9, 10, 11, 12, 12, 13, 14, 14, 15
        .byte 0, 3, 5, 6, 7, 8, 9, 10, 11, 11, 12, 13, 13, 14, 14, 15
