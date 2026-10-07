; game/xymove/slide.s: part xymove's wall slide (docs/GAME.md, TRVTAB). A
; GPL-2
; derivative of upstream's p_mobj65.s (slideMove with stairstep, corners,
; slideTrace, bestMul, addCoord, bobClip, labs; PTR_SlideTraverse with
; blocking; hitSlideLine), Doom8088: Apple IIgs Edition. The products, the
; angles and the distance are the native math's (fixmul, fixmulang, pta3,
; aproxdist, finesine, finecosine).
;
;   slideMove   A:X = the mobj (P_SlideMove: upstream's AP). At most two
;               turns (hitcount 3): bestslidefrac FRACUNIT + 1, three traces
;               (P_PathTraverse with PT_ADDLINES and PTR_SlideTraverse) from
;               the leading corner, the trailing x with the leading y, the
;               leading x with the trailing y (a corner leads on an axis when
;               the momentum is > 0 there: pos + radius, else pos - radius;
;               the trailing one the other way), each to itself + the
;               momentum. Nothing hit, or the move up to the wall refused,
;               or the turns spent: the stairstep (P_TryMove(x, y + momy),
;               else P_TryMove(x + momx, y)). Else bestslidefrac - $800: when
;               > 0, P_TryMove(x + FixedMul(momx, it), y + FixedMul(momy,
;               it)); then the rest $F800 - it (at most FRACUNIT; <= 0 the
;               end); tmxmove, tmymove = FixedMul(momx, momy, rest);
;               hitSlideLine; momx, momy = them; the player's momx, momy
;               clipped to them (bobClip: when |player's| > |tm|, signed);
;               P_TryMove(x + tmxmove, y + tmymove), refused: again
;   PTR_SlideTraverse  TRVTAB's (GA_0 the intercept's index: ICPT + 6 GA_0,
;               frac 4, what 2): a thing is upstream's I_Error. A one-sided
;               line blocks unless the mobj is on its back side
;               (P_PointOnLineSide 1); a two-sided one when openrange <
;               height, opentop - z < height or openbottom - z > 24.0
;               (P_LineOpening; signed). A blocking line nearer than the
;               best (frac < bestslidefrac, signed) becomes the best. C set
;               (A = 1) to go on, C clear (A = 0) after a blocking line
;   hitSlideLine  tmxmove, tmymove along bestslideline: a horizontal line
;               (dy 0) tmymove 0, a vertical one (dx 0) tmxmove 0; else
;               lineangle (R_PointToAngle3(dx << 16, dy << 16), + ANG180 on
;               the side 1), deltaangle = moveangle + 10 - lineangle (+
;               ANG180, xor, when above it), newlen = FixedMulAngle(
;               P_AproxDistance(tm), finecosine(deltaangle >> 19)), tmxmove
;               = FixedMulAngle(newlen, finecosine(lineangle >> 19)),
;               tmymove the same with finesine
;   bestMul     GA_0-3 = FixedMul(GA_0-3, bestslidefrac); changes the math
;               block
;   labs        GA_0-3 = labs(GA_0-3) (-2^31 stays itself)
;
; Every record through the object API (mo_get, ln_get); what lives across a
; call is the scratch block's (xymove.inc). A routine changes A, X, Y,
; GA_*, GT_*, the math block, the API's temporaries and what its callees
; change. Each routine has its own local helpers: the placement may put the
; routines in different groups (gplace.inc).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/xymove/xymove.inc"

        .export slideMove, PTR_SlideTraverse, hitSlideLine, bestMul, labs
        .import mo_get, mo_dirty, ln_get, I_Error
        .import fixmul, fixmulang, pta3, aproxdist, finesine, finecosine
        .import fc_call, fc_unbuilt

; ===========================================================================
; slideMove
; ===========================================================================
        ROUTINE slideMove
        sta XY_MO
        stx XY_MO+1
        lda #3                          ; hitcount
        sta XY_HIT
@retry: dec XY_HIT                      ; do not loop forever
        bne :+
        jmp stair
:       lda #1                          ; bestslidefrac = FRACUNIT + 1
        sta XY_BEST
        sta XY_BEST+2
        stz XY_BEST+1
        stz XY_BEST+3
        lda #0                          ; the three traces: lead x, lead y
        FCALL slideTrace
        lda #1                          ; trail x, lead y
        FCALL slideTrace
        lda #2                          ; lead x, trail y
        FCALL slideTrace
        lda XY_BEST                     ; nothing hit: the stairstep
        cmp #1
        bne @hit
        lda XY_BEST+2
        cmp #1
        bne @hit
        lda XY_BEST+1
        ora XY_BEST+3
        bne @hit
        jmp stair

@hit:   sec                             ; bestslidefrac -= $800
        lda XY_BEST
        sbc #0
        sta XY_BEST
        lda XY_BEST+1
        sbc #8
        sta XY_BEST+1
        lda XY_BEST+2
        sbc #0
        sta XY_BEST+2
        lda XY_BEST+3
        sbc #0
        sta XY_BEST+3
        bmi @rest                       ; > 0: move up to the wall
        ora XY_BEST+2
        ora XY_BEST+1
        ora XY_BEST
        beq @rest
        jsr sm_mo                       ; GT_0-3 = FixedMul(momy, frac)
        ldy #LN_C + MC_MOMY
        jsr sm_ld4
        FCALL bestMul
        ldx #3
:       lda GA_0,x
        sta GT_0,x
        dex
        bpl :-
        jsr sm_mo                       ; GT_4-7 = FixedMul(momx, frac)
        ldy #LN_C + MC_MOMX
        jsr sm_ld4
        FCALL bestMul
        ldx #3
:       lda GA_0,x
        sta GT_4,x
        dex
        bpl :-
        jsr sm_mo                       ; P_TryMove(mo, x + them, y + them)
        ldy #TH_X
        ldx #0
        clc
:       lda (GC_MP),y
        adc GT_4,x
        sta GA_2,x
        iny
        inx
        txa
        eor #4
        bne :-                          ; (eor leaves the carry)
        ldx #0
        clc
:       lda (GC_MP),y
        adc GT_0,x
        sta GA_6,x
        iny
        inx
        txa
        eor #4
        bne :-
        jsr sm_try
        bcs @rest
        jmp stair

        ; the rest of the move: $F800 - frac, at most FRACUNIT
@rest:  sec
        lda #0
        sbc XY_BEST
        sta XY_BEST
        lda #$F8
        sbc XY_BEST+1
        sta XY_BEST+1
        lda #0
        sbc XY_BEST+2
        sta XY_BEST+2
        lda #0
        sbc XY_BEST+3
        sta XY_BEST+3
        bmi @end                        ; < 0: done
        bne @unit                       ; above FRACUNIT: FRACUNIT
        lda XY_BEST+2
        cmp #2
        bcs @unit
        cmp #1
        bne @zero
        lda XY_BEST
        ora XY_BEST+1
        beq @tm
@unit:  stz XY_BEST
        stz XY_BEST+1
        lda #1
        sta XY_BEST+2
        stz XY_BEST+3
        bra @tm
@zero:  lda XY_BEST                     ; 0: done
        ora XY_BEST+1
        bne @tm
@end:   rts

@tm:    jsr sm_mo                       ; tmxmove, tmymove
        ldy #LN_C + MC_MOMX
        jsr sm_ld4
        FCALL bestMul
        ldx #3
:       lda GA_0,x
        sta XY_TM,x
        dex
        bpl :-
        jsr sm_mo
        ldy #LN_C + MC_MOMY
        jsr sm_ld4
        FCALL bestMul
        ldx #3
:       lda GA_0,x
        sta XY_TM+4,x
        dex
        bpl :-
        FCALL hitSlideLine              ; clip the moves
        jsr sm_mo                       ; momx, momy = tmxmove, tmymove
        ldy #LN_C + MC_MOMX
        ldx #0
:       lda XY_TM,x
        sta (GC_MP),y
        iny
        inx
        cpx #8
        bne :-
        lda #D_C
        jsr mo_dirty
        lda XY_MO                       ; the player's: the bobbing too
        cmp G_PLAYER + PL_MO
        bne @again
        lda XY_MO+1
        cmp G_PLAYER + PL_MO + 1
        bne @again
        ldx #0
        FCALL bobClip
        ldx #4
        FCALL bobClip
@again: jsr sm_mo                       ; P_TryMove(mo, x + tmxmove,
        ldy #TH_X                       ;   y + tmymove), refused: again
        ldx #0
        clc
:       lda (GC_MP),y
        adc XY_TM,x
        sta GA_2,x
        iny
        inx
        txa
        eor #4
        bne :-
        clc
:       lda (GC_MP),y
        adc XY_TM,x
        sta GA_2,x
        iny
        inx
        txa
        eor #8
        bne :-
        jsr sm_try
        bcs :+
        jmp @retry
:       rts

; stair (stairstep): if (!P_TryMove(mo, x, y + momy)) P_TryMove(mo, x +
; momx, y)
stair:  jsr sm_mo
        ldy #TH_X                       ; x
        ldx #GA_2
        jsr sm_ld4x
        ldy #TH_Y                       ; y + momy
        ldx #LN_C + MC_MOMY
        jsr sm_add
        jsr sm_try
        bcs @r
        jsr sm_mo
        ldy #TH_Y                       ; y
        ldx #GA_6
        jsr sm_ld4x
        ldy #TH_X                       ; x + momx
        ldx #LN_C + MC_MOMX
        jsr sm_add0
        jmp sm_try
@r:     rts

; sm_add: GA_6-9 = the line's 4 bytes at Y + its 4 bytes at X; sm_add0:
; GA_2-5 the same
sm_add: lda #GA_6
        bra :+
sm_add0:
        lda #GA_2
:       sta GT_8                        ; the destination
        stx GT_9                        ; the second offset
        lda #4
        sta GT_10
        clc
@add:   phy
        lda (GC_MP),y
        ldy GT_9
        adc (GC_MP),y
        ldx GT_8
        sta 0,x
        inc GT_8
        inc GT_9
        ply
        iny
        dec GT_10
        bne @add
        rts

; sm_try: P_TryMove(XY_MO, GA_2-5, GA_6-9); C set when it moved
sm_try: lda XY_MO
        sta GA_0
        lda XY_MO+1
        sta GA_1
        FCALL P_TryMove
        rts

; sm_mo: GC_MP = the line of the mobj XY_MO
sm_mo:  lda XY_MO
        ldx XY_MO+1
        jmp mo_get

; sm_ld4: GA_0-3 = the line's 4 bytes at Y; sm_ld4x: the zero page's 4
; bytes at X = them
sm_ld4: ldx #GA_0
sm_ld4x:
        lda (GC_MP),y
        sta 0,x
        iny
        lda (GC_MP),y
        sta 1,x
        iny
        lda (GC_MP),y
        sta 2,x
        iny
        lda (GC_MP),y
        sta 3,x
        rts

; ===========================================================================
; bestMul: GA_0-3 = FixedMul(GA_0-3, bestslidefrac)
; ===========================================================================
        ROUTINE bestMul
        ldx #3
:       lda GA_0,x
        sta M_A,x
        lda XY_BEST,x
        sta M_B,x
        dex
        bpl :-
        jsr fixmul
        ldx #3
:       lda M_R,x
        sta GA_0,x
        dex
        bpl :-
        rts

; ===========================================================================
; labs: GA_0-3 = labs(GA_0-3)
; ===========================================================================
        ROUTINE labs
        bit GA_3
        bpl @r
        sec
        lda #0
        sbc GA_0
        sta GA_0
        lda #0
        sbc GA_1
        sta GA_1
        lda #0
        sbc GA_2
        sta GA_2
        lda #0
        sbc GA_3
        sta GA_3
@r:     rts

; ===========================================================================
; slideTrace (with corners): A = 0 the leading corner, 1 the trailing x with
; the leading y, 2 the leading x with the trailing y: P_PathTraverse(it,
; it + the momentum, PT_ADDLINES, PTR_SlideTraverse) for the mobj XY_MO
; ===========================================================================
        ROUTINE slideTrace
        sta GT_0
        lda XY_MO
        ldx XY_MO+1
        jsr mo_get
        ldy #LN_B + MB_RADIUS + 3       ; GT_4-7 = the radius
        ldx #3
:       lda (GC_MP),y
        sta GT_4,x
        dey
        dex
        bpl :-
        lda GT_0
        and #1
        sta GT_1
        ldx #0
        jsr corner
        lda GT_0
        lsr a
        sta GT_1
        ldx #4
        jsr corner
        lda #UC_PT_ADDLINES
        sta GA_16
        lda #TRVTAB_PTR_SlideTraverse
        sta GA_17
        FCALL P_PathTraverse
        rts

; corner: X = the axis (0 x, 4 y), GT_1 = 1 for the trailing side: GA_0 + X
; = pos + radius (GT_4-7) when the momentum there is > 0 for the leading
; side (<= 0 for the trailing), else pos - radius; GA_8 + X = it + the
; momentum
corner: txa
        clc
        adc #LN_C + MC_MOMX + 3
        tay
        lda (GC_MP),y                   ; > 0: not negative, not 0
        bmi @le
        dey
        ora (GC_MP),y
        dey
        ora (GC_MP),y
        dey
        ora (GC_MP),y
        beq @le
        lda #0
        bra :+
@le:    lda #1
:       eor GT_1
        sta GT_2                        ; 0: + radius, 1: - radius
        txa
        clc
        adc #TH_X
        tay
        lda GT_2
        bne @sub
        clc
        lda (GC_MP),y
        adc GT_4
        sta GA_0,x
        iny
        lda (GC_MP),y
        adc GT_5
        sta GA_1,x
        iny
        lda (GC_MP),y
        adc GT_6
        sta GA_2,x
        iny
        lda (GC_MP),y
        adc GT_7
        sta GA_3,x
        bra @end
@sub:   sec
        lda (GC_MP),y
        sbc GT_4
        sta GA_0,x
        iny
        lda (GC_MP),y
        sbc GT_5
        sta GA_1,x
        iny
        lda (GC_MP),y
        sbc GT_6
        sta GA_2,x
        iny
        lda (GC_MP),y
        sbc GT_7
        sta GA_3,x
@end:   txa                             ; GA_8 + X = it + the momentum
        clc
        adc #LN_C + MC_MOMX
        tay
        clc
        lda GA_0,x
        adc (GC_MP),y
        sta GA_8,x
        iny
        lda GA_1,x
        adc (GC_MP),y
        sta GA_9,x
        iny
        lda GA_2,x
        adc (GC_MP),y
        sta GA_10,x
        iny
        lda GA_3,x
        adc (GC_MP),y
        sta GA_11,x
        rts

; ===========================================================================
; bobClip: X = 0 x, 4 y: when labs(the player's momentum) > labs(tm)
; (signed), the player's momentum = tm
; ===========================================================================
        ROUTINE bobClip
        phx
        ldy #0                          ; GT_0-3 = labs(the player's)
:       lda G_PLAYER + PL_MOMX,x
        sta GA_0,y
        inx
        iny
        cpy #4
        bne :-
        FCALL labs
        ldx #3
:       lda GA_0,x
        sta GT_0,x
        dex
        bpl :-
        plx
        phx
        ldy #0                          ; GA_0-3 = labs(tm)
:       lda XY_TM,x
        sta GA_0,y
        inx
        iny
        cpy #4
        bne :-
        FCALL labs
        ldx #0                          ; labs(tm) < labs(the player's)
        ldy #4
        sec
:       lda GA_0,x
        sbc GT_0,x
        inx
        dey
        bne :-
        bvc :+
        eor #$80
:       plx
        ora #0
        bpl @no
        ldy #4
:       lda XY_TM,x
        sta G_PLAYER + PL_MOMX,x
        inx
        dey
        bne :-
@no:    rts

; ===========================================================================
; PTR_SlideTraverse (TRVTAB)
; ===========================================================================
        ROUTINE PTR_SlideTraverse
        lda GA_0                        ; the intercept: ICPT + 6 GA_0
        asl a
        adc GA_0                        ; (3 GA_0 < 192: C clear)
        stz GT_1
        asl a
        rol GT_1
        clc
        adc #<ICPT
        sta GT_0
        lda GT_1
        adc #>ICPT
        sta GT_1
        ldy #5                          ; what: a thing is not a line
        lda (GT_0),y
        bpl :+
        jmp I_Error
:       sta XY_LI+1                     ; li = in->d.line
        dey
        lda (GT_0),y
        sta XY_LI
:       dey                             ; its frac
        lda (GT_0),y
        sta XY_FRAC,y
        cpy #0
        bne :-
        lda XY_LI
        ldx XY_LI+1
        jsr ln_get
        ldy #LN_FLAGS
        lda (GC_LP),y
        and #<ML_TWOSIDED
        bne @two
        ; one sided: blocks, unless from the back side
        jsr pt_mo                       ; P_PointOnLineSide(slidemo's x, y,
        ldy #TH_X + 7                   ;   li)
        ldx #7
:       lda (GC_MP),y
        sta GA_X,x
        dey
        dex
        bpl :-
        lda XY_LI
        ldx XY_LI+1
        FCALL P_PointOnLineSide
        cmp #0
        beq pt_block
        sec
        lda #1
        rts

        ; two sided: blocks if the mobj does not fit in the opening
@two:   lda XY_LI                       ; P_LineOpening(li)
        ldx XY_LI+1
        FCALL P_LineOpening
        jsr pt_mo
        ldx #3                          ; openrange < height
:       lda GM_OPENRANGE,x
        sta GT_0,x
        dex
        bpl :-
        ldy #LN_B + MB_HEIGHT
        ldx #GT_4
        jsr pt_ld4
        jsr pt_slt
        bmi pt_block
        ldx #0                          ; opentop - z < height
        jsr pt_z
        jsr pt_slt
        bmi pt_block
        ldx #GM_OPENBOT - GM_OPENTOP    ; 24.0 < openbottom - z
        jsr pt_z
        ldx #3
:       lda GT_0,x
        sta GT_4,x
        dex
        bpl :-
        stz GT_0
        stz GT_1
        lda #24
        sta GT_2
        stz GT_3
        jsr pt_slt
        bmi pt_block
        sec                             ; does not block
        lda #1
        rts

; pt_block (blocking): the nearest blocking line so far (frac < best,
; signed) is the best; then stop
pt_block:
        ldx #0
        ldy #4
        sec
:       lda XY_FRAC,x
        sbc XY_BEST,x
        inx
        dey
        bne :-
        bvc :+
        eor #$80
:       ora #0
        bpl @stop
        ldx #3
:       lda XY_FRAC,x
        sta XY_BEST,x
        dex
        bpl :-
        lda XY_LI
        sta XY_LINE
        lda XY_LI+1
        sta XY_LINE+1
@stop:  clc
        lda #0
        rts

; pt_z: GT_0-3 = GM_OPENTOP + X (0 opentop, 4 openbottom) - the mobj's z
        .assert GM_OPENBOT = GM_OPENTOP + 4, error, "opentop, openbottom"
pt_z:   ldy #TH_Z
        sec
        lda GM_OPENTOP,x
        sbc (GC_MP),y
        sta GT_0
        iny
        lda GM_OPENTOP+1,x
        sbc (GC_MP),y
        sta GT_1
        iny
        lda GM_OPENTOP+2,x
        sbc (GC_MP),y
        sta GT_2
        iny
        lda GM_OPENTOP+3,x
        sbc (GC_MP),y
        sta GT_3
        rts

; pt_slt: N set when GT_0-3 < GT_4-7 (signed)
pt_slt: ldx #0
        ldy #4
        sec
:       lda GT_0,x
        sbc GT_4,x
        inx
        dey
        bne :-
        bvc :+
        eor #$80
:       ora #0
        rts

; pt_mo: GC_MP = the line of slidemo
pt_mo:  lda XY_MO
        ldx XY_MO+1
        jmp mo_get

; pt_ld4: the zero page's 4 bytes at X = the line's 4 bytes at Y
pt_ld4: lda (GC_MP),y
        sta 0,x
        iny
        lda (GC_MP),y
        sta 1,x
        iny
        lda (GC_MP),y
        sta 2,x
        iny
        lda (GC_MP),y
        sta 3,x
        rts

; ===========================================================================
; hitSlideLine: tmxmove, tmymove along bestslideline
; ===========================================================================
HS_LA   = GT_0                          ; (4) lineangle
HS_DA   = GT_4                          ; (4) deltaangle
HS_LEN  = GT_8                          ; (4) movelen, then newlen

        ROUTINE hitSlideLine
        lda XY_LINE
        ldx XY_LINE+1
        jsr ln_get
        ldy #LN_DY                      ; a horizontal line: no more y move
        lda (GC_LP),y
        iny
        ora (GC_LP),y
        bne :+
        stz XY_TM+4
        stz XY_TM+5
        stz XY_TM+6
        stz XY_TM+7
        rts
:       ldy #LN_DX                      ; a vertical line: no more x move
        lda (GC_LP),y
        iny
        ora (GC_LP),y
        bne :+
        stz XY_TM
        stz XY_TM+1
        stz XY_TM+2
        stz XY_TM+3
        rts
:       lda XY_MO                       ; side = P_PointOnLineSide(x, y,
        ldx XY_MO+1                     ;   ld)
        jsr mo_get
        ldy #TH_X + 7
        ldx #7
:       lda (GC_MP),y
        sta GA_X,x
        dey
        dex
        bpl :-
        lda XY_LINE
        ldx XY_LINE+1
        FCALL P_PointOnLineSide
        pha
        lda XY_LINE                     ; lineangle = R_PointToAngle3(dx <<
        ldx XY_LINE+1                   ;   16, dy << 16)
        jsr ln_get
        stz M_A
        stz M_A+1
        stz M_B
        stz M_B+1
        ldy #LN_DX
        lda (GC_LP),y
        sta M_A+2
        iny
        lda (GC_LP),y
        sta M_A+3
        ldy #LN_DY
        lda (GC_LP),y
        sta M_B+2
        iny
        lda (GC_LP),y
        sta M_B+3
        jsr pta3
        ldx #3
:       lda M_R,x
        sta HS_LA,x
        dex
        bpl :-
        pla                             ; side 1: + ANG180
        cmp #1
        bne :+
        lda HS_LA+3
        eor #$80
        sta HS_LA+3
:       jsr hs_tm                       ; moveangle = R_PointToAngle3(tm)
        jsr pta3
        clc                             ; deltaangle = moveangle + 10 -
        lda M_R                         ;   lineangle
        adc #10
        sta HS_DA
        lda M_R+1
        adc #0
        sta HS_DA+1
        lda M_R+2
        adc #0
        sta HS_DA+2
        lda M_R+3
        adc #0
        sta HS_DA+3
        sec
        ldx #0
        ldy #4
:       lda HS_DA,x
        sbc HS_LA,x
        sta HS_DA,x
        inx
        dey
        bne :-
        jsr hs_tm                       ; movelen = P_AproxDistance(tm)
        jsr aproxdist
        ldx #3
:       lda M_R,x
        sta HS_LEN,x
        dex
        bpl :-
        lda HS_DA+3                     ; deltaangle > ANG180: + ANG180
        cmp #$80
        bcc @len
        bne @flip
        lda HS_DA+2
        ora HS_DA+1
        ora HS_DA
        beq @len
@flip:  lda HS_DA+3
        eor #$80
        sta HS_DA+3
@len:   ldx #HS_DA                      ; newlen = FixedMulAngle(movelen,
        jsr hs_fine                     ;   finecosine(deltaangle >> 19))
        jsr finecosine
        jsr hs_mul
        ldx #3
:       lda M_R,x
        sta HS_LEN,x
        dex
        bpl :-
        ldx #HS_LA                      ; tmxmove = FixedMulAngle(newlen,
        jsr hs_fine                     ;   finecosine(lineangle >> 19))
        jsr finecosine
        jsr hs_mul
        ldx #3
:       lda M_R,x
        sta XY_TM,x
        dex
        bpl :-
        ldx #HS_LA                      ; tmymove = FixedMulAngle(newlen,
        jsr hs_fine                     ;   finesine(lineangle >> 19))
        jsr finesine
        jsr hs_mul
        ldx #3
:       lda M_R,x
        sta XY_TM+4,x
        dex
        bpl :-
        rts

; hs_tm: M_A, M_B = tmxmove, tmymove
hs_tm:  ldx #7
:       lda XY_TM,x
        sta M_A,x
        dex
        bpl :-
        rts

; hs_fine: M_A = (the angle at zero page X) >> 19 (its high word >> 3)
hs_fine:
        lda 3,x
        sta M_A+1
        lda 2,x
        lsr M_A+1
        ror a
        lsr M_A+1
        ror a
        lsr M_A+1
        ror a
        sta M_A
        rts

; hs_mul: M_R = FixedMulAngle(HS_LEN, M_R)
hs_mul: ldx #3
:       lda M_R,x
        sta M_B,x
        lda HS_LEN,x
        sta M_A,x
        dex
        bpl :-
        jmp fixmulang
