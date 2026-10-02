; game/movers/mvtest.s: part movers' test routine (milestone 10,
; docs/GAME.md 2.4 "Arithmetic"; docs/game-parts/movers.md), test builds of
; the part's own image only (part.mk: MV_TEST=1). GPL-2, the port's own.
;
;   mv_bulk   mulExt on many inputs, for the part's random check against
;             upstream's mulExt on ref816 (tools/native/gparts/movers.py
;             --random): X:Y = the count; the inputs (6 bytes each: the
;             32-bit value, then the word) from bank BULK_IN at $0200, the
;             results (4 bytes each) to bank BULK_OUT at $0200. The
;             machine is fresh: mt_init first, as the boot does

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

.ifdef TESTBUILD
        .export mv_bulk
        .import far_get, far_put, fc_call, fc_unbuilt, mt_init

        ; test-only code goes in the card's driver area, not the core
        .segment "DRIVER"
FC_HERE .set 0

BULK_IN  = 93                   ; (llayout.SPARE: test banks)
BULK_OUT = 94

mv_bulk:
        stx GT_4                ; the count
        sty GT_5
        jsr mt_init             ; (a machine with no game: the math's
                                ;   square pointers, as the boot does)
        lda #<$0200
        sta GT_0                ; the input's place, the output's
        sta GT_2
        lda #>$0200
        sta GT_1
        sta GT_3
@next:  lda GT_4
        ora GT_5
        bne :+
        rts
:       lda GT_4
        bne :+
        dec GT_5
:       dec GT_4
        lda #6                  ; the input to GT_8-13
        sta FA_N
        lda GT_0
        sta FA_SRC
        lda GT_1
        sta FA_SRC+1
        lda #<GT_8
        sta FA_DST
        stz FA_DST+1
        lda #BULK_IN
        sta FA_BANK
        jsr far_get
        ldx #3
:       lda GT_8,x
        sta M_A,x
        dex
        bpl :-
        lda GT_12
        ldx GT_13
        FCALL mulExt            ; (changes no GT_0-5)
        lda #4                  ; M_R to the output
        sta FA_N
        lda #<M_R
        sta FA_SRC
        stz FA_SRC+1
        lda GT_2
        sta FA_DST
        lda GT_3
        sta FA_DST+1
        lda #BULK_OUT
        sta FA_BANK
        jsr far_put
        clc
        lda GT_0
        adc #6
        sta GT_0
        bcc :+
        inc GT_1
:       clc
        lda GT_2
        adc #4
        sta GT_2
        bcc :+
        inc GT_3
:       jmp @next
.endif
