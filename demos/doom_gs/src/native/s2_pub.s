; s2_pub.s: the publish of a band (docs/SCREENS.md, the bands and the
; publish). A shared object, linked alone into AMAPW and with s2_draw.s into
; the other 2D images. Written from upstream's showDirty
; (src/iigs/i_viigs65.s): the marked bytes of each row go to the screen, and
; the marks are cleared; natively the screen is aux 0, written by CPU stores
; in one RAMWRT window a band (docs/MEMORY_MAP.md's rules), and the bytes
; come from the band in W.
;
;   s2_publish  the band's marked bytes (S2_DRY0 .. S2_DRY1 - 1, DRB ..
;               DRE - 1 of each) to aux 0 $2000 + (S2_Y0 + row) * 160,
;               then the marks cleared. Before the frame's first band,
;               s2_begin (the palettes and SCBs, upstream's order)
;               once, recorded in s2_begun. A band with no mark publishes
;               nothing and does not count as the first.
;   s2_mul160   A * 160 in A (low) and X (high); A <= 255. Changes S2_M.
;
; Inside the window every store reaches aux 0 but zero page's: the loop
; keeps its pointers in zero page and clears the marks after the window.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"

        .export s2_publish, s2_mul160
        .import s2_begin, s2_begun, s2_marks

DRB  = s2_marks
DRE  = s2_marks + $40

        .segment "S2CODE"

s2_mul160:
        sta S2_M                ; A * 5 * 32
        stz S2_M+1
        asl a
        rol S2_M+1
        asl a
        rol S2_M+1
        clc
        adc S2_M
        bcc :+
        inc S2_M+1
:       ldx #5
:       asl a
        rol S2_M+1
        dex
        bne :-
        ldx S2_M+1
        rts

s2_publish:
        lda S2_DRY1
        beq @done
        lda s2_begun            ; the frame's first band: s2_begin
        bne :+
        jsr s2_begin
        lda #1
        sta s2_begun
:       lda S2_DRY0             ; the band's row
        jsr s2_mul160
        clc
        adc S2_BAND
        sta S2_COLP
        txa
        adc S2_BAND+1
        sta S2_COLP+1
        lda S2_DRY0             ; the screen's row
        clc
        adc S2_Y0
        jsr s2_mul160
        sta S2_DEST
        txa
        clc
        adc #>SHR
        sta S2_DEST+1
        ldx S2_DRY0
        sta RAMWRTON
@row:   ldy DRE,x
        beq @next
        sty S2_CNT
        ldy DRB,x
@byte:  lda (S2_COLP),y
        sta (S2_DEST),y
        iny
        cpy S2_CNT
        bcc @byte
@next:  clc
        lda S2_COLP
        adc #160
        sta S2_COLP
        bcc :+
        inc S2_COLP+1
:       clc
        lda S2_DEST
        adc #160
        sta S2_DEST
        bcc :+
        inc S2_DEST+1
:       inx
        cpx S2_DRY1
        bcc @row
        sta RAMWRTOFF
        ldx S2_DRY0             ; the marks cleared
:       stz DRE,x
        inx
        cpx S2_DRY1
        bcc :-
        stz S2_DRY0
        stz S2_DRY1
@done:  rts
