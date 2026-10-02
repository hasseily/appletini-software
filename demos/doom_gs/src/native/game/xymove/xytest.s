; game/xymove/xytest.s: part xymove's test routine (milestone 10, docs/GAME.md
; 2.4 "Arithmetic"; docs/game-parts/xymove.md), test builds of the part's
; own image only (part.mk: XY_TEST=1). GPL-2, the port's own.
;
;   xy_bulk   one of the part's arithmetic helpers on many inputs, for its
;             random check against upstream's on ref816 (tools/native/
;             gparts/xymove.py --random): A = the helper (0 friction, 1
;             bestMul, 2 labs), X:Y = the count; the inputs from bank
;             BULK_IN at $0200 (friction, labs: the value, 4 bytes;
;             bestMul: the momentum, then bestslidefrac, 4 bytes each), the
;             results (4 bytes each) to bank BULK_OUT at $0200
;
; Its state is the scratch block's bytes after XY_END and XY_HIT (no game
; routine runs: the helpers keep to GA_0-3, GT_0-1, the math block). The
; machine is fresh: mt_init first, as the boot and nl_setup do.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/xymove/xymove.inc"

.ifdef TESTBUILD
        .export xy_bulk
        .import far_get, far_put, fc_call, fc_unbuilt, mt_init

        ; test-only code goes in the card's driver area, not the core
        .segment "DRIVER"
FC_HERE .set 0

BULK_IN  = 93                   ; (llayout.SPARE: test banks)
BULK_OUT = 94

XB_MODE = XY_HIT                ; the helper
XB_IN   = XY_END                ; (2) the input's place
XB_OUT  = XY_END + 2            ; (2) the output's place
XB_N    = XY_END + 4            ; (2) the count left
        .assert XY_END + 6 <= SB_XYMOVE + SB_XYMOVE_SIZE, error, "xy_bulk's bytes"

xy_bulk:
        sta XB_MODE
        stx XB_N
        sty XB_N+1
        jsr mt_init             ; the products' square pointers (a fresh
        lda #<$0200             ;   machine: the boot's mt_init)
        sta XB_IN
        sta XB_OUT
        lda #>$0200
        sta XB_IN+1
        sta XB_OUT+1
@next:  lda XB_N
        ora XB_N+1
        bne :+
        rts
:       lda XB_N
        bne :+
        dec XB_N+1
:       dec XB_N
        lda #4                  ; the input to GA_0-3
        jsr xb_in
        lda XB_MODE
        cmp #1
        bne :+
        lda #<XY_BEST           ; bestMul: bestslidefrac after it
        sta FA_DST
        lda #>XY_BEST
        sta FA_DST+1
        lda #4
        sta FA_N
        jsr xb_get
:       lda XB_MODE
        beq @fr
        cmp #1
        beq @bm
        FCALL labs
        bra @out
@fr:    FCALL friction
        bra @out
@bm:    FCALL bestMul
@out:   lda #4                  ; GA_0-3 to the output
        sta FA_N
        lda #<GA_0
        sta FA_SRC
        stz FA_SRC+1
        lda XB_OUT
        sta FA_DST
        lda XB_OUT+1
        sta FA_DST+1
        lda #BULK_OUT
        sta FA_BANK
        jsr far_put
        clc
        lda XB_OUT
        adc #4
        sta XB_OUT
        bcc :+
        inc XB_OUT+1
:       jmp @next

; xb_in: GA_0-3 = the next 4 input bytes
xb_in:  sta FA_N
        lda #<GA_0
        sta FA_DST
        stz FA_DST+1
; xb_get: FA_N bytes at FA_DST = the next input bytes
xb_get: lda XB_IN
        sta FA_SRC
        lda XB_IN+1
        sta FA_SRC+1
        lda #BULK_IN
        sta FA_BANK
        clc
        lda XB_IN
        adc FA_N
        sta XB_IN
        bcc :+
        inc XB_IN+1
:       jmp far_get
.endif
