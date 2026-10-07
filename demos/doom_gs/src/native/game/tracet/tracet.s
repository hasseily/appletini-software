; game/tracet/tracet.s: part tracet of the game's tic code (docs/GAME.md:
; the trace): the block steps of a long trace
; with the fast vertex sides, and their setup. GPL-2: rewritten from
; upstream's p_trace65.s (traceLines:1142 with its macros SIDE1 and VSIDE
; and tlSlow1, tlSlow2; traceThings:1407; thFast, thSide; sideSetup:860
; with vsPatch:1806; longTrace:817), Doom8088: Apple IIgs Edition. Nothing
; here comes from upstream's cal_integer.s: the products are math.s's
; (umul16, mul8).
;
; The places (SIDE1's constants, the walks' state, the zero page) are
; tracet.inc's. Every routine is upstream's, with its quirks:
;
;   traceLines  P_BlockLinesIterator(x, y, PIT_AddLineIntercepts) of a
;               long trace with the fast sides (TT_RR not 0: part path
;               calls it then): GA_0-1 x, GA_2-3 y (signed words). Each
;               line of the block's list whose validcount is not
;               G_VALID is stamped with it first, then its two vertices'
;               sides come from SIDE1 (cst TT_CV, lim 2 VBV + 1), or,
;               where it cannot tell, from vtxSlowR (part tracel); a line
;               whose two sides differ goes to lineCross. Out: A = 1 and
;               C set (every line done, or the block off the map), A = 0
;               and C clear (the intercepts are full).
;               Upstream's count of the guard with the sides (G_IDT,
;               GSTAMP: p_trace65.s:1199-1213) is not here: the guard is
;               dead in the release (P_PathTraverse clears G_IDT before
;               every walk, p_path65.s:271, and the only other writer is
;               the guard, p_path65.s:612-614, 896).
;   traceThings P_BlockThingsIterator(x, y, PIT_AddThingIntercepts) of
;               P_PathTraverse: the same arguments and result. Each thing
;               of the block in its order: thFast (0 not crossed: the
;               next; 1 crossed; 2 cannot tell: divlineSide on the
;               diagonal's two ends, part tracel), then the diagonal's
;               frac (ivAxis, else interceptVector3) and, when it is not
;               behind (frac >= 0), the intercept ($8000 + the mobj's
;               slot). The diagonal: x1 = x - r, x2 = x + r; when
;               trace.dx ^ trace.dy > 0 (32 bits, signed) y1 = y + r, y2 =
;               y - r, else y1 = y - r, y2 = y + r: dl = (x1, y1, 2 r,
;               -+2 r).
;   thFast      the sides of the corners of thing TT_MO with SIDE1: A = 0
;               not crossed, 1 crossed, 2 cannot tell (TT_RR 0, a radius
;               with a fraction, an overflow, or SIDE1 cannot tell).
;   thSide      SIDE1 of a point: X' in GT_0-1, Y' in GT_2-3, TT_SEL 2 for
;               a thing's corner (cst TT_CT, lim VBTL + VBTH + 1: upstream's
;               thSide) or 0 for a line's vertex (cst TT_CV, lim 2 VBV + 1:
;               upstream's VSIDE, natively one copy of the code for both);
;               C clear and A = $80 (side ^ inv), or C set when this way
;               cannot tell.
;   sideSetup   A = P_PathTraverse's flags: GM_IVON = ivSetup's answer for
;               a shot (PT_ADDTHINGS), else 0; then SIDE1's constants of
;               the trace into the scratch block, TT_AX the main axis
;               (upstream's vsPatch: the pair of SIDE1 for the axis, data
;               here), GM_INVB, and TT_RR not 0; TT_RR = 0 for a short
;               trace, an axis trace, |DX| + |DY| > 2900 or a start at
;               $7FFF.f. Upstream's ptPatch (the branches of
;               P_PathTraverse's block loops, of the guard and of gBlockT
;               patched for the flags, PT_FLP) is not here: natively the
;               loops test the flags themselves (part path).
;   longTrace   C set (and A = 1) when a component of the trace is beyond
;               16 units, else C clear and A = 0.
;
; Every call of another routine is an FCALL (the placement may put them in
; different groups); the math and the object API are resident (jsr).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/tracet/tracet.inc"

        .export traceLines, traceThings, thFast, thSide, sideSetup
        .export longTrace
        .export TT_RR, TT_AX, TT_P1, TT_P2, TT_CV, TT_CT, TT_OXC, TT_OYC
        .export TT_SGN, TT_DYF
        .import ln_get, ln_dirty, mo_get, bl_get, bk_get, mul8, umul16
        .import fc_call, fc_unbuilt

; ===========================================================================
; traceLines: the lines of block (GA_0-1, GA_2-3) with the fast sides
; ===========================================================================
        ROUTINE traceLines
        TT_INRANGE tlTrue
        clc                             ; the list's place: the word at 4 +
        lda GT_0                        ;   block
        adc #4
        pha
        lda GT_1
        adc #0
        tax
        pla
        jsr bl_get
        clc                             ; its first line: the word after
        lda BL_BUF                      ;   the list's 0
        adc #1
        sta TT_POS
        lda BL_BUF+1
        adc #0
        sta TT_POS+1
        stz TT_WOK                      ; (no window)
tlLoop: lda TT_WOK                      ; the position in the window
        beq tlFetch                     ;   (TT_WIN its first, 128 words)?
        sec
        lda TT_POS
        sbc TT_WIN
        tax
        lda TT_POS+1
        sbc TT_WIN+1
        bne tlFetch
        cpx #128
        bcs tlFetch
        txa
        asl a
        tay
        bra tlRead
tlFetch:
        lda TT_POS
        sta TT_WIN
        ldx TT_POS+1
        stx TT_WIN+1
        jsr bl_get
        lda #1
        sta TT_WOK
        ldy #0
tlRead: lda BL_BUF+1,y                  ; $FFFF: the list's end
        tax
        lda BL_BUF,y
        cmp #$FF
        bne tlLine
        cpx #$FF
        jeq tlTrue
tlLine: sta TT_LN
        stx TT_LN+1
        jsr ln_get
        ldy #LN_VALID                   ; checked already
        lda (GC_LP),y
        cmp G_VALID
        bne tlNew
        iny
        lda (GC_LP),y
        cmp G_VALID+1
        beq tlNext
tlNew:  ldy #LN_VALID                   ; its stamp, before its sides
        lda G_VALID
        sta (GC_LP),y
        iny
        lda G_VALID+1
        sta (GC_LP),y
        jsr ln_dirty
        ldy #LN_V1X                     ; s1: SIDE1, or vtxSlowR
        jsr tlSide
        bcc :+
        lda TT_LN
        ldx TT_LN+1
        ldy #LN_V1X
        FCALL vtxSlowR
:       sta TT_S1
        lda TT_LN                       ; (the line again: GC_LP)
        ldx TT_LN+1
        jsr ln_get
        ldy #LN_V2X                     ; s2
        jsr tlSide
        bcc :+
        lda TT_LN
        ldx TT_LN+1
        ldy #LN_V2X
        FCALL vtxSlowR
:       cmp TT_S1                       ; s1 == s2: not crossed
        beq tlNext
        lda TT_LN                       ; the intercept
        ldx TT_LN+1
        FCALL lineCross
        stz TT_WOK                      ; (the window: fetched again)
        cmp #0
        beq tlFalse                     ; full
tlNext: inc TT_POS
        jne tlLoop
        inc TT_POS+1
        jmp tlLoop
tlTrue: lda #1
        sec
        rts
tlFalse:
        lda #0
        clc
        rts

; tlSide: VSIDE (p_trace65.s:1115-1129) for the vertex at Y (LN_V1X,
; LN_V2X) of the line at GC_LP: Y' = vy - TT_OYC, X' = vx - TT_OXC (a
; signed overflow: cannot tell), then SIDE1 with TT_CV. Out: C clear and A
; = $80 (side ^ inv), or C set.
tlSide: sec
        lda (GC_LP),y
        sbc TT_OXC
        sta SX
        iny
        lda (GC_LP),y
        sbc TT_OXC+1
        sta SX+1
        jvs tlNo
        iny
        sec
        lda (GC_LP),y
        sbc TT_OYC
        sta SY
        iny
        lda (GC_LP),y
        sbc TT_OYC+1
        sta SY+1
        jvs tlNo
        stz TT_SEL                      ; SIDE1 with TT_CV
        FCALL thSide
        rts
tlNo:   sec
        rts

; ===========================================================================
; traceThings: the things of block (GA_0-1, GA_2-3)
; ===========================================================================
        ROUTINE traceThings
        TT_INRANGE ttTrue
        lda GT_0                        ; the block's first thing
        ldx GT_1
        jsr bk_get
ttThing:
        sta TT_MO
        stx TT_MO+1
        cpx #$FF                        ; none: the end
        jeq ttTrue
        FCALL thFast                    ; 0 not crossed, 1 crossed, 2
        cmp #1                          ;   cannot tell
        jcc ttNext
        and #1
        sta TT_CR
        lda TT_MO                       ; the diagonal dl: x (GA_0), y
        ldx TT_MO+1                     ;   (GA_4), the radius (GT_0)
        jsr mo_get
        ldy #3
:       lda (GC_MP),y                   ; (TH_X = 0)
        sta GA_0,y
        dey
        bpl :-
        ldx #3
        ldy #TH_Y + 3
:       lda (GC_MP),y
        sta GA_4,x
        dey
        dex
        bpl :-
        ldx #3
        ldy #2 * MO_SIZE + MB_RADIUS + 3
:       lda (GC_MP),y
        sta GT_0,x
        dey
        dex
        bpl :-
        lda GT_0                        ; dl.dx = 2 radius (GA_8)
        asl a
        sta GA_8
        lda GT_1
        rol a
        sta GA_9
        lda GT_2
        rol a
        sta GA_10
        lda GT_3
        rol a
        sta GA_11
        sec                             ; x1 = x - radius
        ldx #0
        ldy #4
:       lda GA_0,x
        sbc GT_0,x
        sta GA_0,x
        inx
        dey
        bne :-
        lda TR_DX+3                     ; trace.dx ^ trace.dy > 0 (32 bits,
        eor TR_DY+3                     ;   signed)?
        bmi ttNeg
        bne ttPos
        lda TR_DX+2
        eor TR_DY+2
        bne ttPos
        lda TR_DX+1
        eor TR_DY+1
        bne ttPos
        lda TR_DX
        eor TR_DY
        beq ttNeg
ttPos:  clc                             ; yes: y1 = y + radius, dl.dy =
        ldx #0                          ;   -dl.dx
        ldy #4
:       lda GA_4,x
        adc GT_0,x
        sta GA_4,x
        inx
        dey
        bne :-
        sec
        ldx #0
        ldy #4
:       lda #0
        sbc GA_8,x
        sta GA_12,x
        inx
        dey
        bne :-
        bra ttDl
ttNeg:  sec                             ; no: y1 = y - radius, dl.dy = dl.dx
        ldx #0
        ldy #4
:       lda GA_4,x
        sbc GT_0,x
        sta GA_4,x
        inx
        dey
        bne :-
        ldx #3
:       lda GA_8,x
        sta GA_12,x
        dex
        bpl :-
ttDl:   ldx #7                          ; x1, y1 kept across divlineSide
:       lda GA_0,x
        sta TT_X1,x
        dex
        bpl :-
        lda TT_CR                       ; crossed (thFast)?
        bne ttCross
        FCALL divlineSide               ; s1 = P_PointOnDivlineSide(x1, y1)
        sta TT_S1
        clc                             ; s2: of x1 + dl.dx, y1 + dl.dy
        ldx #0
        ldy #4
:       lda TT_X1,x
        adc GA_8,x
        sta GA_0,x
        inx
        dey
        bne :-
        clc
        ldx #0
        ldy #4
:       lda TT_Y1,x
        adc GA_12,x
        sta GA_4,x
        inx
        dey
        bne :-
        FCALL divlineSide
        cmp TT_S1                       ; s1 == s2: not crossed
        beq ttNext
        ldx #7                          ; dl again
:       lda TT_X1,x
        sta GA_0,x
        dex
        bpl :-
ttCross:
        FCALL ivAxis                    ; a shot: the diagonal without its
        bcs :+                          ;   products
        FCALL interceptVector3          ; frac
:       lda GA_19                       ; frac < 0: behind the source
        bmi ttNext
        lda TT_MO                       ; a thing: $8000 + its slot
        ldx TT_MO+1
        pha
        txa
        ora #$80
        tax
        pla
        FCALL addIntercept
        bcs ttNext
        lda #0                          ; full: false
        clc
        rts
ttNext: lda TT_MO                       ; the next thing: its bnext
        ldx TT_MO+1
        jsr mo_get
        ldy #MO_SIZE + MA_BNEXT
        lda (GC_MP),y
        pha
        iny
        lda (GC_MP),y
        tax
        pla
        jmp ttThing
ttTrue: lda #1
        sec
        rts

; ===========================================================================
; thFast: the sides of the corners of thing TT_MO: A = 0, 1, 2
; ===========================================================================
        ROUTINE thFast
        lda TT_RR                       ; for a whole radius R: the high
        beq thUnk                       ;   words of the corners are those
        lda TT_MO                       ;   of the center +- R
        ldx TT_MO+1
        jsr mo_get
        ldy #2 * MO_SIZE + MB_RADIUS
        lda (GC_MP),y
        iny
        ora (GC_MP),y
        bne thUnk
        iny
        lda (GC_MP),y
        sta GT_4                        ; R (GT_4-5)
        iny
        lda (GC_MP),y
        sta GT_5
        sec                             ; (y - trace.y) >> 16 in SY
        ldy #TH_Y
        lda (GC_MP),y
        sbc TR_Y
        iny
        lda (GC_MP),y
        sbc TR_Y+1
        iny
        lda (GC_MP),y
        sbc TR_Y+2
        sta SY
        iny
        lda (GC_MP),y
        sbc TR_Y+3
        sta SY+1
        bvs thUnk
        sec                             ; (x - trace.x) >> 16 in SX
        ldy #TH_X
        lda (GC_MP),y
        sbc TR_X
        iny
        lda (GC_MP),y
        sbc TR_X+1
        iny
        lda (GC_MP),y
        sbc TR_X+2
        sta SX
        iny
        lda (GC_MP),y
        sbc TR_X+3
        sta SX+1
        bvc thSides
thUnk:  lda #2                          ; this way cannot tell
        rts
thSides:
        lda TR_DX+3                     ; y1 = y + R when (dx ^ dy) > 0,
        eor TR_DY+3                     ;   else y - R; y2 the other one
        bmi thNeg
        bne thPos
        lda TR_DX+2
        eor TR_DY+2
        bne thPos
        lda TR_DX+1
        eor TR_DY+1
        bne thPos
        lda TR_DX
        eor TR_DY
        beq thNeg
thPos:  sec                             ; y2 = y - R, y1 = y + R
        lda SY
        sbc GT_4
        sta TT_Y2
        lda SY+1
        sbc GT_5
        sta TT_Y2+1
        clc
        lda SY
        adc GT_4
        sta SY
        lda SY+1
        adc GT_5
        sta SY+1
        bra thX
thNeg:  clc                             ; y2 = y + R, y1 = y - R
        lda SY
        adc GT_4
        sta TT_Y2
        lda SY+1
        adc GT_5
        sta TT_Y2+1
        sec
        lda SY
        sbc GT_4
        sta SY
        lda SY+1
        sbc GT_5
        sta SY+1
thX:    clc                             ; x2 = x + R, x1 = x - R
        lda SX
        adc GT_4
        sta TT_X2
        lda SX+1
        adc GT_5
        sta TT_X2+1
        sec
        lda SX
        sbc GT_4
        sta SX
        lda SX+1
        sbc GT_5
        sta SX+1
        lda #2                          ; SIDE1 with TT_CT
        sta TT_SEL
        FCALL thSide                    ; s1
        jcs thUnk
        sta TT_S1
        lda TT_X2                       ; s2
        sta SX
        lda TT_X2+1
        sta SX+1
        lda TT_Y2
        sta SY
        lda TT_Y2+1
        sta SY+1
        FCALL thSide
        jcs thUnk
        eor TT_S1                       ; $80 or 0: 1 or 0
        asl a
        lda #0
        rol a
        rts

; ===========================================================================
; thSide: SIDE1 of a point (X' GT_0-1, Y' GT_2-3; TT_SEL 0 a vertex, 2
; a thing's corner)
; ===========================================================================
        ROUTINE thSide
        SIDE1 thNo
        rts
thNo:   sec
        rts
s1_lim: .byte 2 * VBV + 1, 0, VBTL + VBTH + 1   ; (TT_SEL 0, 2)

; ===========================================================================
; sideSetup: A = the flags; GM_IVON, then SIDE1's constants of the trace
; ===========================================================================
        ROUTINE sideSetup
        and #UC_PT_ADDTHINGS            ; the shots (with things): M of the
        beq :+                          ;   products of interceptVector3
        FCALL ivSetup
:       sta GM_IVON
        lda GM_TRLONG                   ; (the short traces:
        jeq ssNone                      ;   P_PointOnLineSide)
        lda TR_DX
        ora TR_DX+1
        ora TR_DX+2
        ora TR_DX+3
        jeq ssNone
        lda TR_DY
        ora TR_DY+1
        ora TR_DY+2
        ora TR_DY+3
        jeq ssNone
        lda TR_DX+2                     ; |DX| (GT_0-1) + |DY| (GT_2-3)
        ldx TR_DX+3                     ;   <= 2900
        jsr ssAbs
        sta GT_0
        stx GT_1
        cmp #<2901
        txa
        sbc #>2901
        jcs ssNone
        lda TR_DY+2
        ldx TR_DY+3
        jsr ssAbs
        sta GT_2
        stx GT_3
        clc                             ; (|DX| <= 2900: no carry)
        adc GT_0
        tay
        txa
        adc GT_1
        tax
        cpy #<2901
        txa
        sbc #>2901
        jcs ssNone
        lda TR_X                        ; TT_OXC, TT_OYC (none at $7FFF
        ora TR_X+1                      ;   with a fraction)
        cmp #1                          ; (C: the fraction not 0)
        lda TR_X+2
        adc #0
        tax
        lda TR_X+3
        adc #0
        jvs ssNone
        stx TT_OXC
        sta TT_OXC+1
        lda TR_Y
        ora TR_Y+1
        cmp #1
        lda TR_Y+2
        adc #0
        tax
        lda TR_Y+3
        adc #0
        jvs ssNone
        stx TT_OYC
        sta TT_OYC+1
        lda TR_DX+3                     ; TT_SGN
        eor TR_DY+3
        sta TT_SGN
        stz TT_AX                       ; the main axis: 0 x (|DX| >=
        lda GT_0                        ;   |DY|), 4 y; the major one in
        sta GT_4                        ;   GT_4-5, the minor one in GT_6-7
        lda GT_1
        sta GT_5
        lda GT_2
        sta GT_6
        lda GT_3
        sta GT_7
        lda GT_0                        ; |DY| > |DX|: y
        cmp GT_2
        lda GT_1
        sbc GT_3
        bcs :+
        lda #4
        sta TT_AX
        lda GT_2
        sta GT_4
        lda GT_3
        sta GT_5
        lda GT_0
        sta GT_6
        lda GT_1
        sta GT_7
:       lda #8                          ; floor(4096 minor / major): 13
        sta GT_8                        ;   steps of a long division, the
        stz GT_9                        ;   bits into GT_8-9 above a start
ssDiv:  lda GT_6                        ;   bit that ends them
        cmp GT_4
        lda GT_7
        sbc GT_5
        bcc :+                          ; minor >= major: - major (C set)
        sta GT_7
        lda GT_6
        sbc GT_4
        sta GT_6
        sec
:       rol GT_8
        rol GT_9
        bcs ssQ
        asl GT_6
        rol GT_7
        bra ssDiv
ssQ:    clc                             ; SQ = round(2048 minor / major)
        lda GT_8                        ;   in GA_0-1, negative for dx ^ dy
        adc #1                          ;   < 0
        sta GA_0
        lda GT_9
        adc #0
        lsr a
        sta GA_1
        ror GA_0
        lda TT_SGN
        bpl :+
        sec
        lda #0
        sbc GA_0
        sta GA_0
        lda #0
        sbc GA_1
        sta GA_1
:       lda TT_AX                       ; vsC's axis
        sta GA_2
        lda TR_Y                        ; g of y (GA_4-5) and of x (GA_8-9)
        ldx TR_Y+1
        FCALL gOf
        sta GA_4
        stx GA_5
        lda TR_X
        ldx TR_X+1
        FCALL gOf
        sta GA_8
        stx GA_9
        FCALL vsC                       ; VT_CV, VT_CT
        lda GA_16
        sta TT_CV
        lda GA_17
        sta TT_CV+1
        lda GA_18
        sta TT_CT
        lda GA_19
        sta TT_CT+1
        lda GA_0                        ; TT_P1 = 2 SQ + 512 VJ, TT_P2 =
        asl a                           ;   4 SQ
        sta TT_P1
        tax
        lda GA_1
        rol a
        tay
        txa
        asl a
        sta TT_P2
        tya
        rol a
        sta TT_P2+1
        tya
        clc
        adc #>(512 * VJ)
        sta TT_P1+1
        lda TT_AX                       ; GM_INVB: bit 7 of ~DX for x, of DY
        bne :+                          ;   for y
        lda TR_DX+3
        eor #$80
        bra :++
:       lda TR_DY+3
:       and #$80
        sta GM_INVB
        eor TR_DY+3                     ; TT_DYF
        sta TT_DYF
        lda #1                          ; the fast sides on
        sta TT_RR
        rts
ssNone: stz TT_RR
        rts

; ssAbs: A:X = |A:X| (16 bits; -32768 stays $8000)
ssAbs:  cpx #$80
        bcc :+
        eor #$FF
        clc
        adc #1
        pha
        txa
        eor #$FF
        adc #0
        tax
        pla
:       rts

; ===========================================================================
; longTrace: C set when a component of the trace is beyond 16 units
; ===========================================================================
        ROUTINE longTrace
        lda #0                          ; FRACUNIT*16 < dx
        cmp TR_DX
        lda #0
        sbc TR_DX+1
        lda #$10
        sbc TR_DX+2
        lda #0
        sbc TR_DX+3
        bvc :+
        eor #$80
:       bmi ltYes
        lda #0                          ; FRACUNIT*16 < dy
        cmp TR_DY
        lda #0
        sbc TR_DY+1
        lda #$10
        sbc TR_DY+2
        lda #0
        sbc TR_DY+3
        bvc :+
        eor #$80
:       bmi ltYes
        lda TR_DX                       ; dx < -FRACUNIT*16
        cmp #0
        lda TR_DX+1
        sbc #0
        lda TR_DX+2
        sbc #$F0
        lda TR_DX+3
        sbc #$FF
        bvc :+
        eor #$80
:       bmi ltYes
        lda TR_DY                       ; dy < -FRACUNIT*16
        cmp #0
        lda TR_DY+1
        sbc #0
        lda TR_DY+2
        sbc #$F0
        lda TR_DY+3
        sbc #$FF
        bvc :+
        eor #$80
:       bmi ltYes
        lda #0
        clc
        rts
ltYes:  lda #1
        sec
        rts
