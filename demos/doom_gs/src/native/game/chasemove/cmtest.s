; game/chasemove/cmtest.s: part chasemove's test routine (milestone 10,
; docs/GAME.md 2.4 "Arithmetic"; docs/game-parts/chasemove.md), test
; builds of the part's own image only (part.mk: CM_TEST=1). GPL-2, the
; port's own.
;
;   cm_bulk   the part's arithmetic helpers on many inputs, for their random
;             checks against upstream's on ref816 (tools/native/gparts/
;             chasemove.py --random): A = the helper (0 umul16x, 1 mulSpeed,
;             2 times32), X:Y = the count; the inputs (12 bytes each: w0,
;             w1 4 bytes each, a byte k, 3 spare) from bank BULK_IN at
;             $0200, the results (4 bytes each) to bank BULK_OUT at $0200:
;               0  M_A = w0's low word, M_B = w1's: cm_umul16x's M_R
;               1  M_A = w0 (the speed), GT_0-3 = w1 (the coordinate), A =
;                  k (the speeds index 0-15): cm_mulspeed's GT_0-3
;               2  M_R = w0: cm_times32's M_R
;             The machine is fresh: mt_init first, as the boot does.
;             The helpers are local code of pMove's and PIT_AvoidDropoff's
;             groups: called through fc_call with those groups (the
;             build's gplace.inc)

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

.ifdef TESTBUILD
        .export cm_bulk
        .import far_get, far_put, fc_call, fc_unbuilt, mt_init
        .import cm_umul16x, cm_mulspeed, cm_times32

        ; test-only code goes in the card's driver area, not the core
        .segment "DRIVER"
FC_HERE .set 0

BULK_IN  = 93                   ; (llayout.SPARE: test banks)
BULK_OUT = 94
REC      = 12

; the driver's state (the helpers change GT_*, the math block, A, X, Y)
B_IN    = GA_12                 ; (2) the input's place
B_OUT   = GA_14                 ; (2) the output's
B_N     = GA_16                 ; (2) the count left
B_MODE  = GA_18                 ; (1) the helper

; GCALL target, group: a call of a group's local code
.macro GCALL target, grp
  .if grp = 0
        jsr target
  .else
        jsr fc_call
        .byte grp
        .word target
  .endif
.endmacro

cm_bulk:
        sta B_MODE
        stx B_N
        sty B_N+1
        jsr mt_init             ; the products' square pointers (a fresh
                                ;   machine: the boot's mt_init)
        lda #<$0200
        sta B_IN
        sta B_OUT
        lda #>$0200
        sta B_IN+1
        sta B_OUT+1
@next:  lda B_N
        ora B_N+1
        bne :+
        rts
:       lda B_N
        bne :+
        dec B_N+1
:       dec B_N
        lda #REC                        ; the record to GA_0-11
        sta FA_N
        lda B_IN
        sta FA_SRC
        lda B_IN+1
        sta FA_SRC+1
        lda #<GA_0
        sta FA_DST
        stz FA_DST+1
        lda #BULK_IN
        sta FA_BANK
        jsr far_get
        lda B_MODE
        beq @umul
        cmp #1
        beq @mul
        ldx #3                          ; 2: times32
:       lda GA_0,x
        sta M_R,x
        dex
        bpl :-
        GCALL cm_times32, GP_PIT_AvoidDropoff_G
        bra @res
@umul:  lda GA_0                        ; 0: umul16x
        sta M_A
        lda GA_1
        sta M_A+1
        lda GA_4
        sta M_B
        lda GA_5
        sta M_B+1
        GCALL cm_umul16x, GP_pMove_G
@res:   ldx #3
:       lda M_R,x
        sta GA_0,x
        dex
        bpl :-
        bra @put
@mul:   ldx #3                          ; 1: mulSpeed
:       lda GA_0,x
        sta M_A,x
        lda GA_4,x
        sta GT_0,x
        dex
        bpl :-
        lda GA_8
        GCALL cm_mulspeed, GP_pMove_G
        ldx #3
:       lda GT_0,x
        sta GA_0,x
        dex
        bpl :-
@put:   lda #4                          ; GA_0-3 to the output
        sta FA_N
        lda #<GA_0
        sta FA_SRC
        stz FA_SRC+1
        lda B_OUT
        sta FA_DST
        lda B_OUT+1
        sta FA_DST+1
        lda #BULK_OUT
        sta FA_BANK
        jsr far_put
        clc
        lda B_IN
        adc #REC
        sta B_IN
        bcc :+
        inc B_IN+1
:       clc
        lda B_OUT
        adc #4
        sta B_OUT
        bcc :+
        inc B_OUT+1
:       jmp @next
.endif
