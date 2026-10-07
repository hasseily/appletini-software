; game/path/path.s: part path of the game's tic code (docs/GAME.md: the
; trace, TRVTAB): P_PathTraverse,
; the walk of a trace through the block map, and P_TraverseIntercepts.
; GPL-2: rewritten from upstream's p_path65.s (P_PathTraverse:186,
; ptBody:226, offLine:436, fromOrigin:450, axisStep:474, a1Shr7:566, the
; traversal traverse:578, early:594, traverseTo:772 with callTrav:816,
; ptStuck:832), Doom8088: Apple IIgs Edition. Nothing here comes from
; upstream's cal_integer.s: the products and the divide are the native math's
; (umul16 for _Mul16, udiv32 for _UDivMod32, approxdiv, fixmul3216,
; aproxdist).
;
; The places (the walk's state in the scratch block, the trace) are
; path.inc's. Every routine is upstream's, with its quirks:
;
;   P_PathTraverse  GA_0-3 x1, GA_4-7 y1, GA_8-11 x2, GA_12-15 y2 (fixed_t),
;               GA_16 the flags (UC_PT_ADDLINES, UC_PT_ADDTHINGS), GA_17
;               the traverser (its TRVTAB number). Out: A = 1 and C set
;               (true), A = 0 and C clear (false). Upstream keeps the
;               caller's _Dp[8-15] around a shot's walk (its traversers'
;               own state): natively that state is the traversers' own
;               (their scratch blocks), so nothing is kept here.
;   ptBody      the walk: validcount++ (gv_inc), the intercepts emptied
;               (GM_ICN 0, the chain's head none, GM_ICLAST the head), the
;               start moved off a block line (offLine), the trace into
;               GM_TRACE, TR_LONG (longTrace), the fast sides (sideSetup,
;               with the flags in A), K for the early traversal, the ends'
;               blocks (fromOrigin), the steps (axisStep x, then y), then
;               the blocks: the lines (traceLines when GM_RR is not 0, else
;               P_BlockLinesIterator with PIT_AddLineIntercepts), the
;               things (traceThings), the early traversal (when K is not
;               0), the last block's test, the step (y's intercept, then
;               x's, else ptStuck), at most 64 steps; then the traversal of
;               every intercept up to FRACUNIT. Upstream's dead guard
;               (guardL and the rest, p_path65.s:612-614: "no guard
;               (decision 34)") and its state (G_IDT, PT_OK) are not here;
;               upstream's ptPatch (the flags' branches patched in place)
;               is a test of PT_FLAGS here.
;   offLine     X = the axis (0 x, 4 y): when the coordinate GA_0 + X is on
;               a block line ((v - origin) & (MAPBLOCKSIZE - 1) == 0, 23
;               bits), + FRACUNIT (the high word, 16 bits).
;   fromOrigin  X = the axis, GT_0-3 = v: GT_0-3 = v - origin; A (low), X
;               (high) = (v - origin) >> 23, arithmetic (bits 23..30 and
;               the sign).
;   axisStep    X = the axis a (0 x, 4 y), b the other: the step of a
;               (PT_MXS + X / 2), b's step (PT_XSTEP + b) and b's intercept
;               (PT_XI + b), as upstream:
;                 at2 > at1: step 1,  partial = -((a1 >> 7) & $FFFF)
;                            bstep = FixedApproxDiv(b2 - b1, a2 - a1)
;                 at2 < at1: step -1, partial = (a1 >> 7) & $FFFF
;                            bstep = FixedApproxDiv(b2 - b1, a1 - a2)
;                 both:      bintercept = (b1 >> 7) + FixedMul3216(bstep,
;                            partial)
;                 else:      step 0, bstep = 256 FRACUNIT, bintercept =
;                            (b1 >> 7) + bstep
;               with a1, b1 the start from the origin (a2 - a1 = the
;               trace's delta).
;   a1Shr7      GT_0-3 = a: A (low), X (high) = (a >> 7) & $FFFF.
;   early       the early traversal: M = max(|mapx - xt1|, |mapy - yt1|)
;               (words); when M - 2 > 0, traverseTo up to min((M - 2) K
;               - 1, FRACUNIT). Out: C clear when the traverser said false.
;   traverseTo  P_TraverseIntercepts up to PT_LIM: the first intercept of
;               the by-frac chain (the nearest; of equal fracs the first
;               put in) while its frac is not above PT_LIM (signed): off
;               the chain (GM_ICLAST the head when it was the last one
;               put in), the traverser (TRVTAB, PT_TRAV) with the
;               intercept's index in GA_0, then its frac INT32_MAX. Out: C
;               clear when the traverser said false (C clear), else C set.
;               Upstream's callTrav (jml [PT_JMP]) is the DCALL here.
;   ptStuck     no step: when the traverser ran in this step, A = 2 (the
;               next step as usual); else this block's things (the
;               intercepts after PT_IP0) are copied 63 - count times (a
;               forward copy repeats them) and put into the chain
;               (icInsert), A = 1 (the traversal), or A = 0 (false) when
;               they do not fit in MAXINTERCEPTS.
;
; The traverser's convention (TRVTAB): GA_0 the intercept's index (ICPT +
; 6 GA_0: frac 4, what 2); C set on return to go on, clear to stop.
;
; Every call of another routine is an FCALL (the placement may put them in
; different groups); the math, gv_inc and the dispatch are resident (jsr).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/path/path.inc"

        .export P_PathTraverse, ptBody, traverseTo, ptStuck, offLine
        .export axisStep, early, fromOrigin, a1Shr7
        .import gv_inc, aproxdist, udiv32, umul16, approxdiv, fixmul3216
        .import fc_call, fc_unbuilt, dc_call, TRVTAB

; ===========================================================================
; P_PathTraverse
; ===========================================================================
        ROUTINE P_PathTraverse
        lda GA_16                       ; the flags, the traverser
        sta PT_FLAGS
        lda GA_17
        sta PT_TRAV
        FCALL ptBody                    ; (A and C its result)
        rts

; ===========================================================================
; ptBody: the walk (GA_0-15 the ends; PT_FLAGS, PT_TRAV)
; ===========================================================================
        ROUTINE ptBody
        jsr gv_inc                      ; validcount++
        stz GM_ICN                      ; intercept_p = intercepts
        lda #$FF                        ; (none by frac)
        sta ICHAIN + IC_HEAD
        lda #IC_HEAD
        sta GM_ICLAST

        ldx #0                          ; do not start exactly on a block
        FCALL offLine                   ;   line: + FRACUNIT
        ldx #4
        FCALL offLine

        ldx #7                          ; the trace: x1, y1
:       lda GA_0,x
        sta PT_TRX,x
        dex
        bpl :-
        ldx #0                          ; dx = x2 - x1, then dy = y2 - y1
        sec
:       lda GA_8,x
        sbc GA_0,x
        sta PT_TRDX,x
        inx
        txa
        eor #4
        bne :-
        sec
:       lda GA_8,x
        sbc GA_0,x
        sta PT_TRDX,x
        inx
        txa
        eor #8
        bne :-
        FCALL longTrace                 ; TR_LONG: the lines test the ends
        lda #0
        rol a
        sta GM_TRLONG
        lda PT_FLAGS                    ; the vertex sides of the trace
        FCALL sideSetup

        ; K = 128 FRACUNIT / L for the early traversal, L a length >= the
        ; trace: P_AproxDistance (>= the true length) rounded up; 0 for a
        ; trace of 128 units or less
        stz PT_K
        stz PT_K+1
        ldx #3
:       lda PT_TRDX,x
        sta M_A,x
        lda PT_TRDY,x
        sta M_B,x
        dex
        bpl :-
        jsr aproxdist
        clc                             ; L = the whole part + 1 (16 bits)
        lda M_R+2
        adc #1
        sta M_B
        lda M_R+3
        adc #0
        sta M_B+1
        bne @div                        ; L < 129 (unsigned): none
        lda M_B
        cmp #129
        bcc @ends
@div:   stz M_B+2                       ; $800000 / L
        stz M_B+3
        stz M_A
        stz M_A+1
        lda #$80
        sta M_A+2
        stz M_A+3
        jsr udiv32
        lda M_R
        sta PT_K
        lda M_R+1
        sta PT_K+1

        ; the ends' blocks: xt1, yt1 (the trace's start), xt2, yt2 (the
        ; start + the delta: x2, y2)
@ends:  ldy #0                          ; Y: the block's word (0 xt1, 2
@end:   sty GT_5                        ;   yt1, 4 xt2, 6 yt2)
        tya
        and #2
        asl a
        tax                             ; X: its axis (0, 4)
        phx
        ldy #0                          ; GT_0-3: the start's coordinate
:       lda PT_TRX,x
        sta GT_0,y
        inx
        iny
        cpy #4
        bne :-
        plx
        lda GT_5
        cmp #4
        bcc @org
        phx                             ; the end's: + the delta
        ldy #0
        clc
:       lda GT_0,y
        adc PT_TRDX,x
        sta GT_0,y
        inx
        iny
        tya
        eor #4
        bne :-
        plx
@org:   FCALL fromOrigin
        ldy GT_5
        sta PT_XT1,y
        txa
        sta PT_XT1+1,y
        iny
        iny
        cpy #8
        bne @end

        ; the steps: x (ystep, yintercept), then y (xstep, xintercept)
        ldx #0
        FCALL axisStep
        ldx #4
        FCALL axisStep

        ; the blocks along the trace
        ldx #3                          ; mapx, mapy
:       lda PT_XT1,x
        sta PT_MX,x
        dex
        bpl :-
        stz PT_COUNT
@step:  stz PT_RAN                      ; (the traverser in this step)
        lda PT_FLAGS                    ; PT_ADDLINES
        and #UC_PT_ADDLINES
        beq @things
        jsr @block
        lda GM_RR                       ; with the fast sides: traceLines
        beq @iter
        FCALL traceLines
        bra @lines
@iter:  lda #ITTAB_PIT_AddLineIntercepts
        sta GA_4                        ; P_BlockLinesIterator(mapx, mapy,
        FCALL P_BlockLinesIterator      ;   PIT_AddLineIntercepts)
@lines: cmp #0
        jeq @false                      ; early out: the intercepts full
@things:
        lda GM_ICN                      ; (ptStuck: this block's things)
        sta PT_IP0
        lda PT_FLAGS                    ; PT_ADDTHINGS
        and #UC_PT_ADDTHINGS
        beq @early
        jsr @block
        FCALL traceThings
        cmp #0
        jeq @false
@early: lda PT_K                        ; the early traversal
        ora PT_K+1
        beq @last
        FCALL early
        jcc @false                      ; the traverser said false
@last:  ldx #3                          ; the last block?
:       lda PT_MX,x
        cmp PT_XT2,x
        bne @ystep
        dex
        bpl :-
        bra @trav
@ystep: ldx #4                          ; (yintercept >> FRACBITS) == mapy:
        ldy #2                          ;   yintercept += ystep, mapx +=
        jsr @onit                       ;   mapxstep
        beq @move
        ldx #0                          ; (xintercept >> FRACBITS) == mapx:
        ldy #0                          ;   xintercept += xstep, mapy +=
        jsr @onit                       ;   mapystep
        beq @move
        FCALL ptStuck                   ; no step (A: 0 false, 1 the
        cmp #1                          ;   traversal, 2 on)
        jcc @false
        jeq @trav
        bra @count
@move:  tya                             ; the other map coordinate
        eor #2
        tay
        lda #4
        sta GT_0
        clc
:       lda PT_XI,x
        adc PT_XSTEP,x
        sta PT_XI,x
        inx
        dec GT_0
        bne :-
        clc
        lda PT_MX,y
        adc PT_MXS,y
        sta PT_MX,y
        lda PT_MX+1,y
        adc PT_MXS+1,y
        sta PT_MX+1,y
@count: inc PT_COUNT                    ; for (count = 0; count < 64;
        lda PT_COUNT                    ;   count++)
        cmp #MAXSTEPS
        jcc @step

        ; the traversal: every intercept up to FRACUNIT
@trav:  stz PT_LIM
        stz PT_LIM+1
        lda #1
        sta PT_LIM+2
        stz PT_LIM+3
        FCALL traverseTo
        lda #0
        bcc :+
        lda #1
:       rts
@false: lda #0
        clc
        rts

; @onit: Z set when the whole part of PT_XI + X (x's or y's intercept)
; equals PT_MX + Y (mapx or mapy)
@onit:  lda PT_XI+2,x
        cmp PT_MX,y
        bne :+
        lda PT_XI+3,x
        cmp PT_MX+1,y
:       rts

; @block: GA_0-1 mapx, GA_2-3 mapy (a block step's arguments)
@block: ldx #3
:       lda PT_MX,x
        sta GA_0,x
        dex
        bpl :-
        rts

; ===========================================================================
; offLine: X = the axis; GA_0 + X += FRACUNIT when on a block line
; ===========================================================================
        ROUTINE offLine
        lda GA_0,x                      ; (v - origin) & $7FFFFF == 0: the
        cmp G_BMORGX,x                  ;   low word equal (no borrow), and
        bne @r                          ;   bits 16..22 of the difference
        lda GA_1,x
        cmp G_BMORGX+1,x
        bne @r
        sec
        lda GA_2,x
        sbc G_BMORGX+2,x
        and #$7F
        bne @r
        inc GA_2,x                      ; the high word + 1 (16 bits)
        bne @r
        inc GA_3,x
@r:     rts

; ===========================================================================
; fromOrigin: X = the axis; GT_0-3 -= the origin; A, X = it >> 23
; ===========================================================================
        ROUTINE fromOrigin
        ldy #0
        sec
:       lda GT_0,y
        sbc G_BMORGX,x
        sta GT_0,y
        inx
        iny
        tya
        eor #4
        bne :-
        lda GT_2                        ; bits 23..30, and the sign
        asl a
        lda GT_3
        rol a
        ldx #0
        bcc :+
        dex
:       rts

; ===========================================================================
; axisStep: X = the axis a (0 x, 4 y)
; ===========================================================================
        ROUTINE axisStep
        stx GT_4                        ; a
        txa
        eor #4
        sta GT_5                        ; b, the other
        txa
        lsr a
        tay                             ; Y = X / 2: a's words
        sec                             ; at2 - at1, signed
        lda PT_XT2,y
        sbc PT_XT1,y
        sta GT_6
        lda PT_XT2+1,y
        sbc PT_XT1+1,y
        bvc :+
        eor #$80                        ; (the sign N ^ V; not 0)
        ora #1
:       bmi @neg
        ora GT_6
        jeq @zero
        lda #1                          ; at2 > at1: step 1
        ldx #0
        bra @set
@neg:   lda #$FF                        ; at2 < at1: step -1
        tax
@set:   sta PT_MXS,y
        txa
        sta PT_MXS+1,y
        sta GT_6                        ; (the sign: 0, $FF)
        ldx GT_4                        ; (a1 >> 7) & $FFFF: the partial of
        jsr @from                       ;   a step -1, minus it of a step 1
        FCALL a1Shr7
        bit GT_6
        bmi :+
        eor #$FF
        clc
        adc #1
        pha
        txa
        eor #$FF
        adc #0
        tax
        pla
:       sta GT_0
        stx GT_1
        ldx GT_4                        ; a2 - a1 = dx, or a1 - a2
        ldy #0
:       lda PT_TRDX,x
        sta M_B,y
        inx
        iny
        cpy #4
        bne :-
        bit GT_6
        bpl @div
        ldx #0
        sec
:       lda #0
        sbc M_B,x
        sta M_B,x
        inx
        txa
        eor #4
        bne :-
@div:   ldx GT_5                        ; bstep = FixedApproxDiv(b2 - b1,
        ldy #0                          ;   M_B)
:       lda PT_TRDX,x
        sta M_A,y
        inx
        iny
        cpy #4
        bne :-
        jsr approxdiv
        ldx GT_5                        ; into b's step, and FixedMul3216(
        ldy #0                          ;   bstep, partial)
:       lda M_R,y
        sta PT_XSTEP,x
        sta M_A,y
        inx
        iny
        cpy #4
        bne :-
        lda GT_0
        sta M_B
        lda GT_1
        sta M_B+1
        jsr fixmul3216
        bra @int
@zero:  lda #0                          ; at2 == at1: step 0
        sta PT_MXS,y
        sta PT_MXS+1,y
        ldx GT_5                        ; bstep = 256 FRACUNIT, and so the
        sta PT_XSTEP,x                  ;   product
        sta PT_XSTEP+1,x
        sta PT_XSTEP+2,x
        sta M_R
        sta M_R+1
        sta M_R+2
        inc a
        sta PT_XSTEP+3,x
        sta M_R+3
@int:   ldx GT_5                        ; bintercept = (b1 >> 7) + M_R, b1
        jsr @from                       ;   the start from the origin
        lda GT_0                        ; >> 7 (arithmetic): GT_1-4
        asl a
        rol GT_1
        rol GT_2
        rol GT_3
        lda #0
        bcc :+
        lda #$FF
:       sta GT_4
        ldx GT_5
        ldy #0
        clc
:       lda GT_1,y
        adc M_R,y
        sta PT_XI,x
        inx
        iny
        tya
        eor #4
        bne :-
        rts

; @from: GT_0-3 = the trace's start on axis X (0, 4) - the origin
@from:  ldy #0
        sec
:       lda PT_TRX,x
        sbc G_BMORGX,x
        sta GT_0,y
        inx
        iny
        tya
        eor #4
        bne :-
        rts

; ===========================================================================
; a1Shr7: A (low), X (high) = (GT_0-3 >> 7) & $FFFF: bits 7..22
; ===========================================================================
        ROUTINE a1Shr7
        lda GT_1                        ; bits 15..22
        asl a
        lda GT_2
        rol a
        tax
        lda GT_0                        ; bits 7..14
        asl a
        lda GT_1
        rol a
        rts

; ===========================================================================
; early: the intercepts that no later block can come before
; ===========================================================================
        ROUTINE early
        ldx #0                          ; |mapx - xt1| (a word)
        jsr @abs
        ldx #2                          ; |mapy - yt1|
        jsr @abs
        lda GT_2                        ; M: y's when not below x's
        cmp GT_0                        ;   (unsigned)
        lda GT_3
        sbc GT_1
        bcs :+
        lda GT_0
        sta GT_2
        lda GT_1
        sta GT_3
:       sec                             ; M - 2 > 0 (a word: not 0, bit
        lda GT_2                        ;   15 clear)?
        sbc #2
        sta M_A
        lda GT_3
        sbc #0
        sta M_A+1
        bmi @none
        ora M_A
        beq @none
        lda PT_K                        ; T = (M - 2) K (unsigned 16 x 16)
        sta M_B
        lda PT_K+1
        sta M_B+1
        jsr umul16
        ldx #0                          ; up to T - 1
        clc
:       lda M_R,x
        sbc #0
        sta PT_LIM,x
        inx
        txa
        eor #4
        bne :-
        lda PT_LIM+3                    ; but not above FRACUNIT, the end of
        bne @cap                        ;   P_TraverseIntercepts (when the
        lda PT_LIM+2                    ;   walk misses the last block)
        beq @go
        cmp #1
        bne @cap
        lda PT_LIM
        ora PT_LIM+1
        beq @go
@cap:   stz PT_LIM
        stz PT_LIM+1
        lda #1
        sta PT_LIM+2
        stz PT_LIM+3
@go:    FCALL traverseTo
        rts
@none:  sec
        rts

; @abs: GT_0 + X = |PT_MX + X - PT_XT1 + X| (a word, X = 0 x, 2 y)
@abs:   sec
        lda PT_MX,x
        sbc PT_XT1,x
        sta GT_0,x
        lda PT_MX+1,x
        sbc PT_XT1+1,x
        sta GT_1,x
        bpl :+
        sec
        lda #0
        sbc GT_0,x
        sta GT_0,x
        lda #0
        sbc GT_1,x
        sta GT_1,x
:       rts

; ===========================================================================
; traverseTo: the traverser for each intercept with frac <= PT_LIM
; ===========================================================================
        ROUTINE traverseTo
@next:  lda ICHAIN + IC_HEAD            ; the first one
        bmi @done
        tax
        jsr @ptr
        ldy #0                          ; frac > the limit (signed): all
        lda PT_LIM                      ;   done
        cmp (GT_0),y
        iny
        lda PT_LIM+1
        sbc (GT_0),y
        iny
        lda PT_LIM+2
        sbc (GT_0),y
        iny
        lda PT_LIM+3
        sbc (GT_0),y
        bvc :+
        eor #$80
:       bmi @done
        lda ICHAIN,x                    ; off the chain (GM_ICLAST: the
        sta ICHAIN + IC_HEAD            ;   head when it was the last one
        cpx GM_ICLAST                   ;   put in)
        bne :+
        lda #IC_HEAD
        sta GM_ICLAST
:       lda #1                          ; (ptStuck: the traverser ran)
        sta PT_RAN
        stx PT_IN
        stx GA_0                        ; trav(in): TRVTAB
        lda PT_TRAV
        DCALL TRVTAB
        bcc @r                          ; false
        ldx PT_IN                       ; in->frac = INT32_MAX
        jsr @ptr
        ldy #3
        lda #$7F
        sta (GT_0),y
        lda #$FF
:       dey
        sta (GT_0),y
        bne :-
        bra @next
@done:  sec
@r:     rts

; @ptr: GT_0-1 = ICPT + 6 X (X kept)
@ptr:   txa
        asl a
        sta GT_0
        asl a
        clc
        adc GT_0
        ldy #>ICPT
        bcc :+
        iny
:       clc
        adc #<ICPT
        sta GT_0
        bcc :+
        iny
:       sty GT_1
        rts

; ===========================================================================
; ptStuck: no step of the walk: A = 0 false, 1 the traversal, 2 on
; ===========================================================================
PT_SI   = PT_IN                         ; (the copies' index and end: the
PT_SE   = PT_LIM                        ;   traversal's places, not live)
        ROUTINE ptStuck
        lda PT_RAN                      ; the traverser ran: the next step
        beq :+                          ;   as usual
        lda #2
        rts
:       sec                             ; n: this block's things
        lda GM_ICN
        sbc PT_IP0
        jeq @one
        sta GT_0
        sec                             ; 63 - count more steps, n each
        lda #MAXSTEPS - 1
        sbc PT_COUNT
        jeq @one
        tax
        stz GT_2                        ; their count (16 bits)
        stz GT_3
@mul:   clc
        lda GT_2
        adc GT_0
        sta GT_2
        bcc :+
        inc GT_3
:       dex
        bne @mul
        clc                             ; the end: above MAXINTERCEPTS:
        lda GT_2                        ;   false (they do not fit)
        adc GM_ICN
        sta PT_SE
        lda GT_3
        adc #0
        jne @zero
        lda PT_SE
        cmp #MAXINTERCEPTS + 1
        jcs @zero
        jsr @ptr                        ; the copy, forward (it repeats the
        sta GT_5                        ;   n intercepts), up to the end's
        stx GT_6                        ;   entry
        lda PT_IP0
        jsr @ptr
        sta GT_0
        stx GT_1
        lda GM_ICN
        jsr @ptr
        sta GT_2
        stx GT_3
@copy:  lda (GT_0)
        sta (GT_2)
        inc GT_0
        bne :+
        inc GT_1
:       inc GT_2
        bne :+
        inc GT_3
:       lda GT_2
        cmp GT_5
        lda GT_3
        sbc GT_6
        bcc @copy
        lda GM_ICN                      ; the copies into the chain by frac
        sta PT_SI
@ins:   lda PT_SI
        FCALL icInsert
        inc PT_SI
        lda PT_SI
        cmp PT_SE
        bcc @ins
        sta GM_ICN
@one:   lda #1
        rts
@zero:  lda #0
        rts

; @ptr: A (low), X (high) = ICPT + 6 A (A up to MAXINTERCEPTS: 4 A can
; pass a byte)
@ptr:   asl a
        sta GT_4
        ldx #>ICPT
        asl a
        bcc :+
        inx
:       clc
        adc GT_4
        bcc :+
        inx
:       clc
        adc #<ICPT
        bcc :+
        inx
:       rts
