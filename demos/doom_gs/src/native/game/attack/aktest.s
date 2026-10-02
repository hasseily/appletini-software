; game/attack/aktest.s: part attack's test routine (milestone 10,
; docs/GAME.md 2.4 "Arithmetic"; docs/game-parts/attack.md), test builds
; only, in the driver's area, and only in the part's own image (part.mk's
; AK_TEST=1, which tools/native/gparts/attack.py passes). GPL-2, the
; port's own.
;
;   ak_bulk   rangeMul (A = 0) or mul3 (A = 1) on many inputs, for their
;             random checks against upstream's helpers on ref816
;             (attack.py --random): X:Y = the count; each input (12 bytes:
;             v, attackrange, aimslope) from bank BULK_IN at $0200, each
;             result (M_R, 4 bytes) to bank BULK_OUT at $0200

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/attack/attack.inc"

.ifdef TESTBUILD
        .export ak_bulk
        .import far_get, far_put, fc_call, fc_unbuilt, mt_init

        ; test-only code goes in the card's driver area, not the core (wave
        ; 1 as integrated: the core's room is the game's)
        .segment "DRIVER"
FC_HERE .set 0

BULK_IN  = 93                   ; (llayout.SPARE: test banks)
BULK_OUT = 94

ak_bulk:
        sta GT_6                ; the mode
        phx
        phy
        jsr mt_init             ; (a machine with no game: the math's
        ply                     ;   pointers' high bytes)
        plx
        stx GT_4                ; the count
        sty GT_5
        lda #<$0200
        sta GA_16               ; the input's place (GA_16-17), the
        sta GA_18               ;   output's (GA_18-19)
        lda #>$0200
        sta GA_17
        sta GA_19
@next:  lda GT_4
        ora GT_5
        bne :+
        rts
:       lda GT_4
        bne :+
        dec GT_5
:       dec GT_4
        lda #12                 ; the input to GA_0-11
        sta FA_N
        lda GA_16
        sta FA_SRC
        lda GA_17
        sta FA_SRC+1
        lda #<GA_0
        sta FA_DST
        stz FA_DST+1
        lda #BULK_IN
        sta FA_BANK
        jsr far_get
        ldx #3
:       lda GA_0,x
        sta M_B,x
        lda GA_4,x
        sta AK_RANGE,x
        lda GA_8,x
        sta AK_AIM,x
        dex
        bpl :-
        lda GT_6
        bne @m3
        FCALL rangeMul
        bra @out
@m3:    FCALL mul3
@out:   lda #4                  ; M_R to the output
        sta FA_N
        lda #<M_R
        sta FA_SRC
        stz FA_SRC+1
        lda GA_18
        sta FA_DST
        lda GA_19
        sta FA_DST+1
        lda #BULK_OUT
        sta FA_BANK
        jsr far_put
        clc
        lda GA_16
        adc #12
        sta GA_16
        bcc :+
        inc GA_17
:       clc
        lda GA_18
        adc #4
        sta GA_18
        bcc :+
        inc GA_19
:       jmp @next
.endif
