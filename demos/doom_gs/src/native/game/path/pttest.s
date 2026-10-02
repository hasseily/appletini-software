; game/path/pttest.s: part path's test routines (milestone 10, docs/GAME.md
; 2.4 "Arithmetic", 3.5; docs/game-parts/path.md), test builds only, in the
; driver's area, and only in the part's own checkpoint image (part.mk's
; PT_TEST=1, which tools/native/gparts/path.py passes). GPL-2, the port's
; own.
;
;   pt_bulk     a1Shr7 on many inputs, for its random check against
;               upstream's a1Shr7 on ref816 (path.py --random): X:Y = the
;               count; the inputs (4 bytes each) from bank BULK_IN at
;               $0200, the results (2 bytes each) to bank BULK_OUT at $0200
;   pt_rec_trv  the recording traverser with TRVTAB's convention (GA_0 the
;               intercept's index): grec.s's gt_record_trv, which takes
;               GA_0 since wave 4's integration (request R2). The harness
;               puts pt_rec_trv in TRVTAB's harness entry (path.py)

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/path/path.inc"

.ifdef TESTBUILD
        .export pt_bulk, pt_rec_trv
        .import far_get, far_put, fc_call, fc_unbuilt, gt_record_trv

        ; test-only code goes in the card's driver area, not the core (wave
        ; 1 as integrated: the core's room is the game's)
        .segment "DRIVER"
FC_HERE .set 0

BULK_IN  = 93                   ; (llayout.SPARE: test banks)
BULK_OUT = 94

pt_rec_trv:
        jmp gt_record_trv

pt_bulk:
        stx GT_4                ; the count
        sty GT_5
        lda #<$0200
        sta GT_6                ; the input's place (GT_6, GA_18), the
        sta GA_16               ;   output's (GA_16-17)
        lda #>$0200
        sta GA_18
        sta GA_17
@next:  lda GT_4
        ora GT_5
        bne :+
        rts
:       lda GT_4
        bne :+
        dec GT_5
:       dec GT_4
        lda #4                  ; the input to GT_0-3
        sta FA_N
        lda GT_6
        sta FA_SRC
        lda GA_18
        sta FA_SRC+1
        lda #<GT_0
        sta FA_DST
        stz FA_DST+1
        lda #BULK_IN
        sta FA_BANK
        jsr far_get
        FCALL a1Shr7
        sta GA_0                ; A:X to the output
        stx GA_1
        lda #2
        sta FA_N
        lda #<GA_0
        sta FA_SRC
        stz FA_SRC+1
        lda GA_16
        sta FA_DST
        lda GA_17
        sta FA_DST+1
        lda #BULK_OUT
        sta FA_BANK
        jsr far_put
        clc
        lda GT_6
        adc #4
        sta GT_6
        bcc :+
        inc GA_18
:       clc
        lda GA_16
        adc #2
        sta GA_16
        bcc :+
        inc GA_17
:       jmp @next
.endif
