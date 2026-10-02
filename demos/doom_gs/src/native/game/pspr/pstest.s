; game/pspr/pstest.s: part pspr's test routine (milestone 10, docs/GAME.md
; 2.4 "Arithmetic"; docs/game-parts/pspr.md), test builds only. GPL-2, the
; port's own.
;
;   ps_bulk   signExt4 (A = 0) or signExt0 (A = 1) on many inputs, for the
;             part's random check against upstream's helpers on ref816
;             (tools/native/gparts/pspr.py --random): X:Y = the count; the
;             inputs (a word each) from bank BULK_IN at $0200, the results
;             (4 bytes each: M_B, or M_A) to bank BULK_OUT at $0200

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/pspr/pspr.inc"

.ifdef TESTBUILD
        .export ps_bulk
        .import far_get, far_put, fc_call, fc_unbuilt

        ; test-only code goes in the card's driver area, not the core
        .segment "DRIVER"
FC_HERE .set 0

BULK_IN  = 93                   ; (llayout.SPARE: test banks)
BULK_OUT = 94

ps_bulk:
        sta GT_6                ; the mode
        stx GT_4                ; the count
        sty GT_5
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
        lda #2                  ; the input to GA_0-1
        sta FA_N
        lda GT_0
        sta FA_SRC
        lda GT_1
        sta FA_SRC+1
        lda #<GA_0
        sta FA_DST
        stz FA_DST+1
        lda #BULK_IN
        sta FA_BANK
        jsr far_get
        lda GA_0
        ldx GA_1
        ldy GT_6
        bne @s0
        FCALL signExt4
        lda #<M_B
        bra @out
@s0:    FCALL signExt0
        lda #<M_A
@out:   sta FA_SRC              ; the result to the output
        stz FA_SRC+1
        lda #4
        sta FA_N
        lda GT_2
        sta FA_DST
        lda GT_3
        sta FA_DST+1
        lda #BULK_OUT
        sta FA_BANK
        jsr far_put
        clc
        lda GT_0
        adc #2
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
