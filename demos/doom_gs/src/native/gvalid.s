; gvalid.s: validcount (docs/LEVELS.md; one count for the game and the
; renderer, docs/GAME.md).
;
;   gv_inc      validcount++. Upstream has one validcount, which the game's
;               walks and the renderer's frame setup both raise: natively
;               it is the frame block's VALIDCOUNT, G_VALID its name in the
;               game core, and the renderer's nr_setup calls gv_inc too
;               (this file is linked into the render images, -D GV_RENDER).
;               Upstream's wrap is not kept: when the count wraps to 0
;               every stamp is cleared (each sector's in its LVMAP record,
;               each line's validcount and r_validcount in LVG0) and the
;               count becomes 1, so no stamp of an earlier walk can equal a
;               new count. The game's and the load image's clear is the
;               object API's go_stamps0 (gobj.s: the line and sector caches
;               are flushed and emptied first, so no cached record keeps an
;               old stamp). The renderer's (-D GV_RENDER) is its own:
;               nr_setup runs before the walk fetches any sector, and the
;               game's caches are flushed at the end of every tic phase
;               (go_flush), so nothing holds a stamp to flush; it writes
;               the zeros in one RAMWRT window a bank, as far.s's
;               far_vclear does, with the far layer's zero page (FA_*).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"            ; (G_VALID: the frame block's VALIDCOUNT)

        .export gv_inc
.ifndef GV_RENDER
        .export gv_clear
        .import go_stamps0
        .segment "LOADW"
.else
        .segment "RENDERW"
.endif

; ---------------------------------------------------------------------------
; gv_inc: validcount++. Changes A (and, at a wrap, X, Y and: the game's,
; GC_T, GC_P, the API's temporaries, FA_*; the renderer's, FA_*).
; ---------------------------------------------------------------------------
gv_inc:
        inc G_VALID
        bne @done
        inc G_VALID+1
        bne @done
        jsr gv_clear
        lda #1
        sta G_VALID
@done:  rts

.ifndef GV_RENDER
; gv_clear: the caches flushed and emptied, then every sector's stamp
; (LVMAP) and every line's two stamps (LVG0) 0 (the object API's
; go_stamps0: no far access of a cached kind outside gobj.s)
gv_clear:
        jmp go_stamps0
.else
; gv_clear (the renderer's): every sector's stamp (LVMAP SECBASE +
; SEC_VALID, LVCOUNT records of SEC_SIZE) and every line's two stamps
; (LVG0 LINE_BASE + LN_VALID, LVCOUNT2 records of LINE_SIZE) 0, as
; go_stamps0 writes them. Changes A, X, Y, FA_*.
        .assert LN_RVALID = LN_VALID + 2, error, "the line's two stamps"
gv_clear:
        lda #LVMAP              ; the sectors
        ldx #<(SECBASE + SEC_VALID)
        ldy #>(SECBASE + SEC_VALID)
        jsr @base
        lda LVCOUNT
        sta FA_SRC
        lda LVCOUNT+1
        sta FA_SRC+1
        ldx #SEC_SIZE
        lda #2 - 1
        jsr @zeros
        lda #LVG0               ; the lines
        ldx #<(LINE_BASE + LN_VALID)
        ldy #>(LINE_BASE + LN_VALID)
        jsr @base
        lda LVCOUNT2
        sta FA_SRC
        lda LVCOUNT2+1
        sta FA_SRC+1
        ldx #LINE_SIZE
        lda #4 - 1
        ; fall through
; FA_SRC records of FA_BANK from FA_DST, X bytes apart: the first A + 1
; bytes of each 0, in one RAMWRT window
@zeros: sta FA_N
        lda FA_BANK
        sta RWBANK
        sta RAMWRTON
@rec:   lda FA_SRC
        ora FA_SRC+1
        beq @end
        ldy FA_N
        lda #0
:       sta (FA_DST),y
        dey
        bpl :-
        txa
        clc
        adc FA_DST
        sta FA_DST
        bcc :+
        inc FA_DST+1
:       lda FA_SRC
        bne :+
        dec FA_SRC+1
:       dec FA_SRC
        bra @rec
@end:   sta RAMWRTOFF
        stz RWBANK
        rts
; FA_BANK = A, FA_DST = Y:X
@base:  sta FA_BANK
        stx FA_DST
        sty FA_DST+1
        rts
.endif
