; game/missile/mstest.s: part missile's test routine (milestone 10,
; docs/GAME.md 2.4 "Arithmetic"; docs/game-parts/missile.md), test builds of
; the part's own image only (MS_TEST=1, part.mk). GPL-2, the port's own.
;
;   ms_bulk   halfMom on many inputs, for the part's random check against
;             upstream's halfMom on ref816 (tools/native/gparts/missile.py
;             --random): X:Y = the count; the inputs (8 bytes each: the
;             momentum, then the coordinate) from bank BULK_IN at $0200,
;             the results (the coordinate after, 4 bytes each) to bank
;             BULK_OUT at $0200. The "line" halfMom works on is GA_0-GA_7
;             (GC_MP pointed at it): the momentum at offset 0, the
;             coordinate at offset 4

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/missile/missile.inc"

.ifdef TESTBUILD
        .export ms_bulk
        .import far_get, far_put, fc_call, fc_unbuilt

        ; test-only code goes in the card's driver area, not the core
        .segment "DRIVER"
FC_HERE .set 0

BULK_IN  = 93                   ; (llayout.SPARE: test banks)
BULK_OUT = 94

ms_bulk:
        stx GT_5                ; the count
        sty GT_6
        lda #<$0200
        sta GA_10               ; the input's place, the output's
        sta GA_12
        lda #>$0200
        sta GA_11
        sta GA_13
@next:  lda GT_5
        ora GT_6
        bne :+
        rts
:       lda GT_5
        bne :+
        dec GT_6
:       dec GT_5
        lda #8                  ; the input to GA_0-7
        sta FA_N
        lda GA_10
        sta FA_SRC
        lda GA_11
        sta FA_SRC+1
        lda #<GA_0
        sta FA_DST
        stz FA_DST+1
        lda #BULK_IN
        sta FA_BANK
        jsr far_get
        lda #<GA_0              ; the line: GA_0-7
        sta GC_MP
        stz GC_MP+1
        ldx #4                  ; the coordinate += the momentum >> 1
        ldy #0
        FCALL halfMom
        lda #4                  ; GA_4-7 to the output
        sta FA_N
        lda #<GA_4
        sta FA_SRC
        stz FA_SRC+1
        lda GA_12
        sta FA_DST
        lda GA_13
        sta FA_DST+1
        lda #BULK_OUT
        sta FA_BANK
        jsr far_put
        clc
        lda GA_10
        adc #8
        sta GA_10
        bcc :+
        inc GA_11
:       clc
        lda GA_12
        adc #4
        sta GA_12
        bcc :+
        inc GA_13
:       jmp @next
.endif
