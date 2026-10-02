; s2_lt.s: part s2lay's test image (docs/SCREENS.md 7.3): the smallest
; 2D image, linked in P2DW's room with MATHW and AUXW as every 2D image,
; for the test driver's checks (tests/test_m11_s2lay.py). Not part of
; the game.
;
;   s2t_nop     returns
;   s2t_echo    A, X, Y into the last three bytes of P2DW's state block
;               ($BFFD-$BFFF): the driver's registers reach the routine
;   s2t_stop    the stop code A in PL_STATUS, then BRK (a routine's stop)
;   s2t_wait    waits until the driver's stub has counted A VBL interrupts

        .setcpu "65C02"
        .include "s2.inc"

        .export s2t_nop, s2t_echo, s2t_stop, s2t_wait
        .import s2d_vbls

ECHO = P2DW_STATE_END - 3

        .segment "S2CODE"

s2t_nop:
        rts

s2t_echo:
        sta ECHO
        stx ECHO+1
        sty ECHO+2
        rts

s2t_stop:
        sta PL_STATUS
        brk
        .byte $00

s2t_wait:
:       cmp s2d_vbls
        beq :+
        bcs :-
:       rts
