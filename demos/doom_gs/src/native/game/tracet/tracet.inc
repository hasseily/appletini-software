; game/tracet/tracet.inc: part tracet's places (milestone 10, docs/GAME.md
; 1.9, 2.4 row tracet, 4.4; docs/game-parts/tracet.md). GPL-2, the port's
; own. Included after ggame.inc.
;
; The trace's shared state is GW's GM_* (tracel.md R1, wave 2 as
; integrated): GM_TRACE (x, y, dx, dy), GM_TRLONG, GM_IVON, GM_IVM,
; GM_INVB, the intercepts ICPT/ICHAIN with GM_ICN, GM_ICLAST.
;
; SIDE1's constants of the trace (upstream's VT_* of bank $21, written by
; sideSetup, read by traceLines and thSide) are GW's GM_RR and GM_SIDE1
; (request R4); the walks' state is the part's scratch block SB_TRACET:
;
;   TT_RR    VT_RR: not 0 when the fast vertex sides are on (a byte)
;   TT_AX    the main axis (0: x, sub = X', main = Y'; 4: y, sub = Y',
;            main = X'): upstream's pair that vsPatch writes into the
;            SIDE1 sites tlP1, tlP2, gtP1, gtP2, thP (txa/sty for x,
;            tya/stx for y), natively a byte of data
;   TT_P1    VT_P1 = 2 SQ + 512 VJ (2)
;   TT_P2    VT_P2 = 4 SQ (2)
;   TT_CV    VT_CV = C - VJ SQ - VBV (2)
;   TT_CT    VT_CT = -VJ SQ - VBTH (2)
;   TT_OXC   VT_OXC = (x >> 16) + cx (2)
;   TT_OYC   VT_OYC = (y >> 16) + cy (2)
;   TT_SGN   VT_SGN's high byte: (DX ^ DY) >> 8 (only bit 7 is read)
;   TT_DYF   VT_DYF's high byte: (DY ^ VT_INVB) >> 8 (only bit 7 is read)
;   TT_S1    the first side ($80 side ^ inv for SIDE1 and vtxSlowR; 0, 1
;            for divlineSide)
;   TT_SEL   thSide's constants: 0 a vertex (TT_CV), 2 a thing (TT_CT)
;
; traceLines' walk (across lineCross and vtxSlowR): TT_POS the list's
; position (a word of the blockmap), TT_LN the line, TT_WIN, TT_WOK the
; window of BL_BUF (its first word; 0: none). traceThings' walk (across
; thFast, divlineSide, ivAxis, interceptVector3, addIntercept): TT_MO the
; mobj, TT_CR thFast's answer, TT_X1, TT_Y1 the diagonal's first corner
; (32 bits each); thFast keeps the second corner (x2, y2: 16 bits each)
; at TT_X1 across its first thSide. The two walks never run together
; (P_PathTraverse calls one, then the other), so they share bytes.

TT       = SB_TRACET
TT_NEED  = 13
        .assert SB_TRACET_SIZE >= TT_NEED, error, "tracet's scratch block"

; SIDE1's constants live from sideSetup to the trace's last block step,
; across the early traversal's traverser calls (part path), and path reads
; TT_RR (upstream's VT_RR): GW's GM_RR and GM_SIDE1 (15), never overlaid
; (request R4, wave 3 as integrated)
TT_RR    = GM_RR
TT_AX    = GM_SIDE1 + 0
TT_P1    = GM_SIDE1 + 1
TT_P2    = GM_SIDE1 + 3
TT_CV    = GM_SIDE1 + 5
TT_CT    = GM_SIDE1 + 7         ; (2 bytes after TT_CV: thSide's TT_CV,y)
TT_OXC   = GM_SIDE1 + 9
TT_OYC   = GM_SIDE1 + 11
TT_SGN   = GM_SIDE1 + 13
TT_DYF   = GM_SIDE1 + 14
TT_S1    = TT + 0
TT_POS   = TT + 1               ; traceLines (2)
TT_LN    = TT + 3               ; (2)
TT_WIN   = TT + 5               ; (2)
TT_WOK   = TT + 7
TT_MO    = TT + 1               ; traceThings (2)
TT_X1    = TT + 3               ; (4)
TT_Y1    = TT + 7               ; (4)
TT_CR    = TT + 11
TT_X2    = TT + 3               ; thFast (2, inside TT_X1)
TT_Y2    = TT + 5               ; (2)
TT_SEL   = TT + 12              ; thSide: 0 a vertex, 2 a thing's corner

; The trace (GW, shared)
TR_X     = GM_TRACE + 0
TR_Y     = GM_TRACE + 4
TR_DX    = GM_TRACE + 8
TR_DY    = GM_TRACE + 12

; SIDE1's constants (p_trace65.s:49-56)
VRN     = 2040                  ; |X'|, |Y'| up to this
VJ      = 23                    ; V2 = 256 VJ
VBV     = 5                     ; L cannot tell: -5..5 for vertices,
VBTH    = 21                    ;   -21..13 for the corners of things
VBTL    = 13

; The zero page (GAME.md 4.4): SIDE1's point in GT_0-GT_3 (X', Y'), its
; temporaries in GT_4-GT_12 (no API call and no FCALL while they live);
; sideSetup's in GT_0-GT_9 before its first FCALL and GA_0-GA_9 as vsC's
; arguments (SQ in GA_0-1, which vsC and gOf leave as they are).

SX      = GT_0                  ; X' (2)
SY      = GT_2                  ; Y' (2)
S_N1    = GT_4                  ; the byte offsets of the quarter
S_N2    = GT_6                  ;   squares (2 each)
S_M1    = GT_8                  ; the middle bits of the first (2)
S_L     = GT_10                 ; L (2)

; TT_INRANGE out: GT_0..1 = the block of (GA_0..1, GA_2..3), or to out
; when it is off the map (0 <= x < width, 0 <= y < height, signed words:
; upstream's tests at p_trace65.s:1142-1149, 1407-1414). The same as part
; geom's INRANGE (giter.s), which is local to its module.
.macro TT_INRANGE out
        lda GA_1                        ; x
        jmi out
        lda GA_0
        cmp G_BMW
        lda GA_1
        sbc G_BMW+1
        jcs out
        lda GA_3                        ; y
        jmi out
        lda GA_2
        cmp G_BMH
        lda GA_3
        sbc G_BMH+1
        jcs out
        lda GA_2                        ; y width + x (both below 256)
        ldy G_BMW
        jsr mul8
        clc
        lda M_R
        adc GA_0
        sta GT_0
        lda M_R+1
        adc #0
        sta GT_1
.endmacro

; SIDE1 fail: the side of the point (X', Y') = (SX, SY) for SIDE1
; (p_trace65.s:1059-1113), with the constant cst and the limit lim of
; TT_SEL (0: a vertex, TT_CV and 2 VBV + 1, upstream's VSIDE; 2: a thing's
; corner, TT_CT and VBTL + VBTH + 1, upstream's thSide): A = $80 (side ^
; inv) and C clear, or to fail when this way cannot tell (C is the
; caller's). The sign test of the
; C code first: when (dy ^ dx ^ x ^ y) < 0, the side is (dy ^ x) < 0, bit
; 7 of X' ^ TT_DYF. Else, for |X'|, |Y'| <= VRN, L + lim / 2 = 8 main -
; (mid(sq(n1)) - mid(sq(n2))) - cst, n1 = (2 sub + TT_P1) / 2, n2 = n1 -
; TT_P2 / 2, mid(sq(n)) the bits 8..23 of the quarter square floor(n n /
; 4) (upstream's SQMID, from its tables SQL, SQH: here bits 10..25 of n n
; through umul16); the side is bit 15 of it unless it is below lim
; (unsigned), when this way cannot tell. 16-bit arithmetic throughout, as
; upstream's. Changes A, X, Y, GT_4-GT_11, the math's operands.
.macro SIDE1 fail
        .local diff, sgn, prod, xok, yok, done
        lda SY+1                        ; (dy ^ dx ^ x ^ y) < 0?
        eor TT_SGN
        bmi diff
        lda SX+1
        bmi sgn
        bra prod
diff:   lda SX+1
        bmi prod
sgn:    eor TT_DYF                      ; the side of the C code
        and #$80
        clc
        jmp done
prod:   clc                             ; |X'| <= VRN: X' + VRN < 2 VRN + 1
        lda SX
        adc #<VRN
        tax
        lda SX+1
        adc #>VRN
        cmp #>(2 * VRN + 1)
        bcc xok
        jne fail
        cpx #<(2 * VRN + 1)
        jcs fail
xok:    clc                             ; the same for Y'
        lda SY
        adc #<VRN
        tax
        lda SY+1
        adc #>VRN
        cmp #>(2 * VRN + 1)
        bcc yok
        jne fail
        cpx #<(2 * VRN + 1)
        jcs fail
yok:    lda TT_AX                       ; sub: X' (x) or Y' (y)
        lsr a
        tax                             ; (0, 2)
        lda SX,x                        ; n1 offset = 2 sub + TT_P1
        asl a
        sta S_N1
        lda SX+1,x
        rol a
        sta S_N1+1
        clc
        lda S_N1
        adc TT_P1
        sta S_N1
        lda S_N1+1
        adc TT_P1+1
        sta S_N1+1
        sec                             ; n2 offset = that - TT_P2
        lda S_N1
        sbc TT_P2
        sta S_N2
        lda S_N1+1
        sbc TT_P2+1
        sta S_N2+1
        txa                             ; main: the other one, 8 main
        eor #2                          ;   into S_L
        tax
        lda SX,x
        asl a
        sta S_L
        lda SX+1,x
        rol a
        asl S_L
        rol a
        asl S_L
        rol a
        sta S_L+1
        lda S_N1+1                      ; mid(sq(n1))
        lsr a
        sta M_A+1
        sta M_B+1
        lda S_N1
        ror a
        sta M_A
        sta M_B
        jsr umul16
        lda M_R+3                       ; bits 10..25 of n n
        lsr a
        ror M_R+2
        ror M_R+1
        lsr a
        ror M_R+2
        ror M_R+1
        lda M_R+1
        sta S_M1
        lda M_R+2
        sta S_M1+1
        lda S_N2+1                      ; mid(sq(n2))
        lsr a
        sta M_A+1
        sta M_B+1
        lda S_N2
        ror a
        sta M_A
        sta M_B
        jsr umul16
        lda M_R+3
        lsr a
        ror M_R+2
        ror M_R+1
        lsr a
        ror M_R+2
        ror M_R+1
        sec                             ; MB = mid1 - mid2; L + lim / 2 =
        lda S_M1                        ;   8 main - MB - cst
        sbc M_R+1
        sta S_M1
        lda S_M1+1
        sbc M_R+2
        sta S_M1+1
        sec
        lda S_L
        sbc S_M1
        sta S_L
        lda S_L+1
        sbc S_M1+1
        sta S_L+1
        ldy TT_SEL                      ; - cst
        sec
        lda S_L
        sbc TT_CV,y
        tax
        lda S_L+1
        sbc TT_CV+1,y
        bne :+                          ; below lim (unsigned): cannot tell
        txa
        cmp s1_lim,y
        jcc fail
        lda #0                          ; (the high byte: 0)
:       and #$80                        ; the side: bit 15
        clc
done:
.endmacro
