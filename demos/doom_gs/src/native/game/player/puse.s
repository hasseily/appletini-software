; game/player/puse.s: part player's use of lines (milestone 10, docs/GAME.md
; 2.2 TRVTAB, 2.4; docs/game-parts/player.md). A GPL-2 derivative of
; upstream's p_use65.s (P_UseLines with times64 and useRun,
; PTR_UseTraverse, PTR_NoWayTraverse).
;
;   P_UseLines         (the player) the trace from the player's mobj to 64
;                      units ahead (USERANGE): P_PathTraverse with the lines
;                      and PTR_UseTraverse; when it went through every
;                      intercept, again with PTR_NoWayTraverse, and when that
;                      one stops, the sound noway from the player
;   PTR_UseTraverse    (TRVTAB, GA_0 the intercept) a special line: used
;                      from its front side (P_UseSpecialLine), the trace
;                      stops; another line: the trace goes on through an
;                      opening (openrange > 0), else noway and it stops
;   PTR_NoWayTraverse  (TRVTAB) C clear (stop: noway) for a line that blocks
;                      the player: not special, and ML_BLOCKING, closed,
;                      too high (z + 24 < openbottom) or too low (opentop <
;                      z + height); else C set
;   times64            M_R = 64 M_R (the low 32 bits)
;
; A traverser returns C set and A = 1 to go on, C clear and A = 0 to stop.
; useArg and lineArg have no code (the player's mobj handle is PY_THING,
; the intercept's line PY_LINE); useRun is pu_run, a local subroutine of
; P_UseLines (request R2: INLINED).
;
; Every routine changes A, X, Y, GT_*, GA_*, the math's block and what its
; callees change.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/player/player.inc"

        .export P_UseLines, PTR_UseTraverse, PTR_NoWayTraverse, times64
        .import mo_get, ln_get, finesine, finecosine, S_StartSound
        .import fc_call, fc_unbuilt

; ===========================================================================
; P_UseLines
; ===========================================================================
        ROUTINE P_UseLines
        lda PLR + PL_MO                 ; usething = player->mo
        sta PY_THING
        ldx PLR + PL_MO + 1
        stx PY_THING + 1
        jsr mo_get
        ldy #TH_X + 7                   ; x1, y1
        ldx #7
:       lda (GC_MP),y
        sta PY_X1,x
        dey
        dex
        bpl :-
        ldy #TH_ANG + 1                 ; an = angle >> 19
        lda (GC_MP),y
        sta PY_LINE + 1
        dey
        lda (GC_MP),y
        lsr PY_LINE + 1
        ror a
        lsr PY_LINE + 1
        ror a
        lsr PY_LINE + 1
        ror a
        sta PY_LINE
        sta M_A                         ; x2 = x1 + 64 finecosine(an)
        lda PY_LINE + 1
        sta M_A + 1
        jsr finecosine
        FCALL times64
        clc
        ldx #0
:       lda PY_X1,x
        adc M_R,x
        sta PY_X2,x
        inx
        txa
        eor #4
        bne :-
        lda PY_LINE                     ; y2 = y1 + 64 finesine(an)
        sta M_A
        lda PY_LINE + 1
        sta M_A + 1
        jsr finesine
        FCALL times64
        clc
        ldx #0
:       lda PY_Y1,x
        adc M_R,x
        sta PY_Y2,x
        inx
        txa
        eor #4
        bne :-
        lda #TRVTAB_PTR_UseTraverse     ; a line to use
        jsr pu_run
        cmp #0
        beq @done
        lda #TRVTAB_PTR_NoWayTraverse   ; none: a line in the way
        jsr pu_run
        cmp #0
        bne @done
        lda #UC_SFX_NOWAY
        ldx PY_THING
        ldy PY_THING + 1
        jsr S_StartSound
@done:  rts

; pu_run (upstream's useRun): A = P_PathTraverse(x1, y1, x2, y2,
; PT_ADDLINES, the traverser A: TRVTAB's number)
pu_run: sta GA_17
        lda #UC_PT_ADDLINES
        sta GA_16
        ldx #15
:       lda PY_X1,x
        sta GA_0,x
        dex
        bpl :-
        FCALL P_PathTraverse
        rts

; ===========================================================================
; times64: M_R = 64 M_R (fixed_t, the low 32 bits)
; ===========================================================================
        ROUTINE times64
        ldx #6
:       asl M_R
        rol M_R + 1
        rol M_R + 2
        rol M_R + 3
        dex
        bne :-
        rts

; ===========================================================================
; PTR_UseTraverse (TRVTAB): GA_0 the intercept
; ===========================================================================
        ROUTINE PTR_UseTraverse
        jsr pu_line
        ldy #LN_SPECIAL
        lda (GC_LP),y
        bne @special
        lda PY_LINE                     ; openrange <= 0: noway
        ldx PY_LINE + 1
        FCALL P_LineOpening
        lda GM_OPENRANGE + 3
        bmi @noway
        ora GM_OPENRANGE + 2
        ora GM_OPENRANGE + 1
        ora GM_OPENRANGE
        bne @on
@noway: lda #UC_SFX_NOWAY
        ldx PY_THING
        ldy PY_THING + 1
        jsr S_StartSound
        lda #0
        clc
        rts
@on:    lda #1
        sec
        rts
@special:
        lda PY_THING                    ; not the back side: used
        ldx PY_THING + 1
        jsr mo_get
        ldy #TH_X + 7                   ; (GA_X, GA_Y)
        ldx #7
:       lda (GC_MP),y
        sta GA_X,x
        dey
        dex
        bpl :-
        lda PY_LINE
        ldx PY_LINE + 1
        FCALL P_PointOnLineSide
        cmp #1
        beq @stop
        lda PY_THING                    ; P_UseSpecialLine(usething, line)
        sta GA_0
        lda PY_THING + 1
        sta GA_1
        lda PY_LINE
        sta GA_2
        lda PY_LINE + 1
        sta GA_3
        FCALL P_UseSpecialLine
@stop:  lda #0
        clc
        rts

; pu_line (upstream's lineArg): PY_LINE = the line of the intercept GA_0
; (ICPT + 6 GA_0: frac 4, what 2), into the line cache (GC_LP)
pu_line:
        lda GA_0
        asl a
        sta GT_0
        asl a
        clc
        adc GT_0
        sta GT_0
        lda #0
        adc #>ICPT
        sta GT_1
        clc
        lda GT_0
        adc #<ICPT
        sta GT_0
        bcc :+
        inc GT_1
:       ldy #4
        lda (GT_0),y
        sta PY_LINE
        iny
        lda (GT_0),y
        sta PY_LINE + 1
        tax
        lda PY_LINE
        jmp ln_get

; ===========================================================================
; PTR_NoWayTraverse (TRVTAB): GA_0 the intercept
; ===========================================================================
        ROUTINE PTR_NoWayTraverse
        jsr pn_line
        ldy #LN_SPECIAL                 ; a special line: go on
        lda (GC_LP),y
        jne @true
        ldy #LN_FLAGS                   ; always blocking
        lda (GC_LP),y
        and #UC_ML_BLOCKING
        jne @false
        lda PY_LINE                     ; no opening
        ldx PY_LINE + 1
        FCALL P_LineOpening
        lda GM_OPENRANGE + 3
        jmi @false
        ora GM_OPENRANGE + 2
        ora GM_OPENRANGE + 1
        ora GM_OPENRANGE
        jeq @false
        lda PY_THING                    ; too high: z + 24 < openbottom
        ldx PY_THING + 1
        jsr mo_get
        ldy #TH_Z
        lda (GC_MP),y
        sta GT_0
        iny
        lda (GC_MP),y
        sta GT_1
        iny
        clc
        lda (GC_MP),y
        adc #24
        sta GT_2
        iny
        lda (GC_MP),y
        adc #0
        sta GT_3
        sec
        lda GT_0
        sbc GM_OPENBOT
        lda GT_1
        sbc GM_OPENBOT + 1
        lda GT_2
        sbc GM_OPENBOT + 2
        lda GT_3
        sbc GM_OPENBOT + 3
        bvc :+
        eor #$80
:       jmi @false
        clc                             ; too low: opentop < z + height
        ldy #TH_Z
        lda (GC_MP),y
        ldy #PO_B + MB_HEIGHT
        adc (GC_MP),y
        sta GT_0
        ldy #TH_Z + 1
        lda (GC_MP),y
        ldy #PO_B + MB_HEIGHT + 1
        adc (GC_MP),y
        sta GT_1
        ldy #TH_Z + 2
        lda (GC_MP),y
        ldy #PO_B + MB_HEIGHT + 2
        adc (GC_MP),y
        sta GT_2
        ldy #TH_Z + 3
        lda (GC_MP),y
        ldy #PO_B + MB_HEIGHT + 3
        adc (GC_MP),y
        sta GT_3
        sec
        lda GM_OPENTOP
        sbc GT_0
        lda GM_OPENTOP + 1
        sbc GT_1
        lda GM_OPENTOP + 2
        sbc GT_2
        lda GM_OPENTOP + 3
        sbc GT_3
        bvc :+
        eor #$80
:       bmi @false
@true:  lda #1
        sec
        rts
@false: lda #0
        clc
        rts

; pn_line: pu_line in this routine's group
pn_line:
        lda GA_0
        asl a
        sta GT_0
        asl a
        clc
        adc GT_0
        sta GT_0
        lda #0
        adc #>ICPT
        sta GT_1
        clc
        lda GT_0
        adc #<ICPT
        sta GT_0
        bcc :+
        inc GT_1
:       ldy #4
        lda (GT_0),y
        sta PY_LINE
        iny
        lda (GT_0),y
        sta PY_LINE + 1
        tax
        lda PY_LINE
        jmp ln_get
