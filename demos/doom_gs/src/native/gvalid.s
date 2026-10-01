; gvalid.s: the game's validcount (milestone 9, stage C; docs/LEVELS.md
; 3.4; NATIVE.md 15.1 row 4).
;
;   gv_inc      validcount++ (G_VALID). The release build fixes upstream's
;               wrap: when the count wraps to 0 every stamp is cleared
;               (each sector's in its LVMAP record, each line's validcount
;               and r_validcount in LVG0) and the count becomes 1, so no
;               stamp of an earlier walk can equal a new count. Built with
;               -D VCWRAP_UPSTREAM (every lockstep and test build) it only
;               adds 1, as upstream does.
;
; The renderer's frame count (rframe.s, VALIDCOUNT of the frame block) is
; the renderer's own until milestone 10 joins the two: its wrap call is
; milestone 11's release frame (docs/LEVELS.md "Stage C as built").

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"

        .export gv_inc
.ifndef VCWRAP_UPSTREAM
        .export gv_clear
.endif
        .import g_put

        .segment "LOADW"

; ---------------------------------------------------------------------------
; gv_inc: validcount++. Changes A (and, at a wrap in the release build, X,
; Y, GC_T, GC_P, FA_*).
; ---------------------------------------------------------------------------
gv_inc:
        inc G_VALID
        bne @done
        inc G_VALID+1
.ifndef VCWRAP_UPSTREAM
        bne @done
        jsr gv_clear
        lda #1
        sta G_VALID
.endif
@done:  rts

.ifndef VCWRAP_UPSTREAM
; gv_clear: every sector's stamp (LVMAP) and every line's two stamps (LVG0)
; 0
gv_clear:
        stz GC_V                ; a zero word, twice
        stz GC_V+1
        stz GC_V+2
        stz GC_V+3
        lda #LVMAP
        sta FA_BANK
        lda #<(SECBASE + SEC_VALID)
        sta FA_DST
        lda #>(SECBASE + SEC_VALID)
        sta FA_DST+1
        lda LVCOUNT
        sta GC_T
        lda LVCOUNT+1
        sta GC_T+1
@sec:   lda GC_T
        ora GC_T+1
        beq @lines
        lda #<GC_V
        ldx #>GC_V
        ldy #2
        jsr g_put
        clc
        lda FA_DST
        adc #SEC_SIZE
        sta FA_DST
        bcc :+
        inc FA_DST+1
:       jsr t_dec
        bra @sec
@lines: lda #LVG0
        sta FA_BANK
        lda #<(LINE_BASE + LN_VALID)
        sta FA_DST
        lda #>(LINE_BASE + LN_VALID)
        sta FA_DST+1
        lda LVCOUNT2
        sta GC_T
        lda LVCOUNT2+1
        sta GC_T+1
@line:  lda GC_T
        ora GC_T+1
        beq @done
        lda #<GC_V
        ldx #>GC_V
        ldy #4
        jsr g_put
        clc
        lda FA_DST
        adc #LINE_SIZE
        sta FA_DST
        bcc :+
        inc FA_DST+1
:       jsr t_dec
        bra @line
@done:  rts
        .assert LN_RVALID = LN_VALID + 2, error, "the line's two stamps"

t_dec:  lda GC_T
        bne :+
        dec GC_T+1
:       dec GC_T
        rts
.endif
