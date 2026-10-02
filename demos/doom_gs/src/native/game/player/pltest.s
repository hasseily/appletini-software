; game/player/pltest.s: part player's test routine (milestone 10,
; docs/GAME.md 2.4 "Arithmetic"; docs/game-parts/player.md), test builds
; only. GPL-2, the port's own.
;
;   pl_bulk   one of the part's arithmetic helpers on many inputs, for the
;             random checks against upstream's helpers on ref816
;             (tools/native/gparts/player.py --random): A = the mode, X:Y =
;             the count; the inputs from bank BULK_IN at $0200, the outputs
;             to bank BULK_OUT at $0200, one record after the other:
;               0 thrustMul    in M_R (4), PY_T (4)   out M_R (4)
;               1 fixedSquare  in momx (4)            out M_R (4) (X = 0)
;               2 times64      in M_R (4)             out M_R (4)
;               3 hurt32       in A:X (2), leveltime (4)
;                              out C (1), GA_0-7 (8)

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/player/player.inc"

.ifdef TESTBUILD
        .export pl_bulk
        .import far_get, far_put, fc_call, fc_unbuilt, mt_init

        ; test-only code goes in the card's driver area, not the core
        .segment "DRIVER"
FC_HERE .set 0

BULK_IN  = 93                   ; (llayout.SPARE: test banks)
BULK_OUT = 94

pl_bulk:
        pha                     ; the products' pointers (a routine-mode
        jsr mt_init             ;   run has them from its state)
        pla
        sta bk_mode             ; the mode (the helpers change GT_*: the
        stx bk_n                ;   loop's state is in the driver's area)
        sty bk_n+1
        lda #<$0200
        sta bk_in               ; the input's place, the output's
        sta bk_out
        lda #>$0200
        sta bk_in+1
        sta bk_out+1
@next:  lda bk_n
        ora bk_n+1
        bne :+
        rts
:       lda bk_n
        bne :+
        dec bk_n+1
:       dec bk_n
        ldx bk_mode             ; the input to GA_0..
        lda in_size,x
        sta FA_N
        lda bk_in
        sta FA_SRC
        lda bk_in+1
        sta FA_SRC+1
        lda #<GA_0
        sta FA_DST
        stz FA_DST+1
        lda #BULK_IN
        sta FA_BANK
        jsr far_get
        lda bk_mode
        beq @thrust
        cmp #1
        beq @square
        cmp #2
        beq @times
        lda GA_2                ; hurt32: leveltime, A:X the damage
        sta G_LEVELTIME
        lda GA_3
        sta G_LEVELTIME+1
        lda GA_4
        sta G_LEVELTIME+2
        lda GA_5
        sta G_LEVELTIME+3
        lda GA_0
        ldx GA_1
        FCALL hurt32
        lda #0
        rol a
        sta GA_8
        lda #<GA_0
        bra @out
@thrust:
        ldx #3
:       lda GA_0,x
        sta M_R,x
        lda GA_4,x
        sta PY_T,x
        dex
        bpl :-
        FCALL thrustMul
        bra @mr
@square:
        ldx #3
:       lda GA_0,x
        sta PLR + PL_MOMX,x
        dex
        bpl :-
        ldx #0
        FCALL fixedSquare
        bra @mr
@times: ldx #3
:       lda GA_0,x
        sta M_R,x
        dex
        bpl :-
        FCALL times64
@mr:    lda #<M_R
@out:   sta FA_SRC              ; the result to the output
        stz FA_SRC+1
        ldx bk_mode
        lda out_size,x
        sta FA_N
        lda bk_out
        sta FA_DST
        lda bk_out+1
        sta FA_DST+1
        lda #BULK_OUT
        sta FA_BANK
        jsr far_put
        ldx bk_mode
        clc
        lda bk_in
        adc in_size,x
        sta bk_in
        bcc :+
        inc bk_in+1
:       clc
        lda bk_out
        adc out_size,x
        sta bk_out
        bcc :+
        inc bk_out+1
:       jmp @next

in_size:  .byte 8, 4, 4, 6
out_size: .byte 4, 4, 4, 9
bk_mode:  .res 1
bk_n:     .res 2
bk_in:    .res 2
bk_out:   .res 2
.endif
