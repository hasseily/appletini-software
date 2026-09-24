; Doom for the Appletini -- the two address spaces (docs/DESIGN.md section 4).
;
;   RENDER  $0200-$BFFF is main memory: RAMRD and RAMWRT off.
;   GAME    $0200-$BFFF is RamWorks bank 1: $C073 = 1, RAMRD and RAMWRT on.
;
; Both spaces share the main zero page, the stack (page 1) and the main
; language card, where all of this code runs: the language card does not
; move with RAMRD, so the switch can be made from here and the caller's
; next instruction comes from the other space. kspace says which space is
; current (SPACE_RENDER 0, SPACE_GAME 1): the far-access routines and
; set_palette read it to leave the machine as they found it.
;
; space_game and space_render keep A, X, Y and P. call_game (RENDER space
; only) runs the GAME routine at kcall with A, X, Y passed in and the
; callee's A, X, Y and P passed back, and returns in RENDER space. The
; switch is three soft-switch writes and one zero-page write; each $Cxxx
; access takes the 1 MHz path on the vTW (about 73 CPU cycles in TURBO in
; tools/a2sim.py's accounting).

.include "kernel.inc"

.segment "KCODE"

space_game:
        php
        pha
        lda     #GAME_BANK
        sta     RAMWORKS
        sta     RAMRDON
        sta     RAMWRTON
        sta     kspace                  ; SPACE_GAME = GAME_BANK = 1
        pla
        plp
        rts

space_render:
        php
        pha
        sta     RAMRDOFF
        sta     RAMWRTOFF
        lda     #SPACE_RENDER
        sta     kspace
        pla
        plp
        rts

call_game:
        jsr     space_game
        jsr     @go
        jmp     space_render
@go:    jmp     (kcall)
