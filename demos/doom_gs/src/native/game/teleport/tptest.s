; game/teleport/tptest.s: part teleport's test routine (milestone 10,
; docs/GAME.md 2.4 "Arithmetic"; docs/game-parts/teleport.md), test builds
; of the part's own image only (part.mk: TP_TEST=1). GPL-2, the port's own.
;
;   tp_bulk   times20 on many inputs, for the part's random check against
;             upstream's times20 on ref816 (tools/native/gparts/teleport.py
;             --random): X:Y = the count; the inputs (4 bytes each) from
;             bank BULK_IN at $0200, the results (4 bytes each) to bank
;             BULK_OUT at $0200

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

.ifdef TESTBUILD
        .export tp_bulk
        .import far_get, far_put, fc_call, fc_unbuilt

        ; test-only code goes in the card's driver area, not the core
        .segment "DRIVER"
FC_HERE .set 0

BULK_IN  = 93                   ; (llayout.SPARE: test banks)
BULK_OUT = 94

tp_bulk:
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
        lda #4                  ; the input to GA_0-3
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
        lda GT_4                ; (times20 changes GT_0-3: kept on the
        pha                     ;   stack)
        lda GT_5
        pha
        lda GT_0
        pha
        lda GT_1
        pha
        lda GT_2
        pha
        lda GT_3
        pha
        FCALL times20
        pla
        sta GT_3
        pla
        sta GT_2
        pla
        sta GT_1
        pla
        sta GT_0
        pla
        sta GT_5
        pla
        sta GT_4
        lda #4                  ; GA_0-3 to the output
        sta FA_N
        lda #<GA_0
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
        adc #4
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
