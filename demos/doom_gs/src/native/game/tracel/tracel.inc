; game/tracel/tracel.inc: part tracel's places (docs/GAME.md: the trace
; and its intercepts). GPL-2, the port's own. Included after ggame.inc.
;
; The trace's state. Upstream keeps it in near and bank $3F scratch of
; p_trace65.s and p_path65.s (_g_trace, TR_LONG, intercept_p, IC_LAST,
; IV_ON, IV_ML, IV_MH, VT_INVB), written by P_PathTraverse (part path)
; and sideSetup (part tracet) and read by this part, tracet, path and the
; traversers (attack: the trace's point at a frac). It is shared tic
; scratch, as geom's GM_* are: glayout.TIC_GW_FIELDS's GM_TRACE ..
; GM_INVB in GW, never overlaid:
;
;   TL_TRACE    _g_trace: x, y, dx, dy (fixed_t each)
;   TL_TRLONG   TR_LONG: 1 a long trace (longTrace), else 0
;   TL_ICN      the intercepts so far: (intercept_p - intercepts) / 10
;   TL_ICLAST   IC_LAST: the last intercept put into the by-frac chain
;               (its index), or MAXINTERCEPTS (the chain's head)
;   TL_IVON     IV_ON: not 0 when ivProd may take its fast path (a shot:
;               sideSetup stores ivSetup's answer)
;   TL_IVM      IV_ML, IV_MH: M = d >> 11 of each trace delta, ivSetup's,
;               upstream's layout: + 0 ML of dx (2), + 2 MH of dx (2: 0 or
;               $FFFF), + 4 ML of dy, + 6 MH of dy
;   TL_INVB     VT_INVB's bit 15 as a byte ($80 or 0: sideSetup's)
;
; The intercepts themselves are llayout's ICPT (64 entries of 6 bytes:
; frac (4), what (2: a line, or $8000 + a mobj slot)) and ICHAIN (the
; by-frac chain: the next entry's index after each entry, $FF none; the
; head at ICHAIN + MAXINTERCEPTS), GAME.md.
;
; The part's own bytes kept across its calls: TL_LD (the line of
; PIT_AddLineIntercepts and lineCross), TL_S1 (the first side).

TL       = SB_TRACEL
TL_NEED  = 3
        .assert SB_TRACEL_SIZE >= TL_NEED, error, "tracel's scratch block"

TL_TRACE  = GM_TRACE
TR_X      = TL_TRACE + 0
TR_Y      = TL_TRACE + 4
TR_DX     = TL_TRACE + 8
TR_DY     = TL_TRACE + 12
TL_TRLONG = GM_TRLONG
TL_ICN    = GM_ICN
TL_ICLAST = GM_ICLAST
TL_IVON   = GM_IVON
TL_IVM    = GM_IVM               ; (8 bytes)
TL_INVB   = GM_INVB
TL_LD     = TL + 0              ; the line (2)
TL_S1     = TL + 2              ; the first side

IC_HEAD   = MAXINTERCEPTS       ; the chain's head: ICHAIN + 64
IC_NONE   = $FF                 ; no next entry

; The zero page of the part's routines (GAME.md: the arguments GA_*,
; the temporaries GT_0-GT_6 that no runtime routine uses, and GT_7-GT_18
; inside a routine that makes no API call and no FCALL while they live):
;
;   TL_X1 .. TL_DY  the divline dl of interceptVector3 and ivAxis
;                   (upstream's TC_X1, TC_Y1, TC_DX, TC_DY): GA_0-GA_15
;   TL_PX, TL_PY    divlineSide's point (TC_X, TC_Y): GA_0-GA_7
;   TL_F            a frac (TC_T: interceptVector3's, ivAxis's, ivTest's
;                   result; addIntercept's input): GA_16-GA_19
;   TL_A, TL_B      ivTest's num and den (TC_A, TC_B): GT_0-GT_7
;   TL_IB, TL_CH    fixedDiv's ibit and ch: GT_8-GT_11
;   TL_D            fixedDiv's a - b: GT_12-GT_15
;   TL_P1, TL_P2    icInsert's entry pointers: GT_0-GT_3
;   TL_NEW, TL_PREV icInsert's new entry and the link before it: GT_4, GT_5
;   vsC's arguments: TL_VSQ (SQ, 2), TL_VAX (the axis: 0 x, 4 y), TL_VG
;                   (g of y at + 0, g of x at + 4); its results TL_VCV
;                   (VT_CV), TL_VCT (VT_CT)

TL_X1   = GA_0
TL_Y1   = GA_4
TL_DX   = GA_8
TL_DY   = GA_12
TL_PX   = GA_0
TL_PY   = GA_4
TL_F    = GA_16
TL_A    = GT_0
TL_B    = GT_4
TL_IB   = GT_8
TL_CH   = GT_10
TL_D    = GT_12
TL_P1   = GT_0
TL_P2   = GT_2
TL_NEW  = GT_4
TL_PREV = GT_5
TL_VSQ  = GA_0
TL_VAX  = GA_2
TL_VG   = GA_4
TL_VCV  = GA_16
TL_VCT  = GA_18

; SIDEPROD pa, pb: M_R = the low 32 bits of (pa >> 8) (pb >> 16), pa, pb
; fixed_t at pa and pb (arithmetic shifts): the signed 24 x 16 product of
; upstream's SIDEPROD (p_trace65.s), with mul32 on the sign-extended
; operands. Changes A, X, Y, M_A, M_B, the math's temporaries.
.macro SIDEPROD pa, pb
        lda pa+1
        sta M_A
        lda pa+2
        sta M_A+1
        lda pa+3
        sta M_A+2
        asl a                           ; (byte 3's sign)
        lda #0
        bcc :+
        lda #$FF
:       sta M_A+3
        lda pb+2
        sta M_B
        lda pb+3
        sta M_B+1
        asl a
        lda #0
        bcc :+
        lda #$FF
:       sta M_B+2
        sta M_B+3
        jsr mul32
.endmacro

; ICPTR p: the pointer p (zero page, 2) = ICPT + 6 A (A an entry, 0-63).
; Changes A.
.macro ICPTR p
        asl a                           ; 2 i (i < 64)
        sta p
        asl a                           ; 4 i
        clc
        adc p
        sta p
        lda #0
        adc #>ICPT
        sta p+1
        clc
        lda p
        adc #<ICPT
        sta p
        bcc :+
        inc p+1
:
.endmacro

; FRACLT p, q: N set when the frac at (p) is below the frac at (q)
; (signed 32 bits). Changes A, Y.
.macro FRACLT p, q
        ldy #0
        lda (p),y
        cmp (q),y
        iny
        lda (p),y
        sbc (q),y
        iny
        lda (p),y
        sbc (q),y
        iny
        lda (p),y
        sbc (q),y
        bvc :+
        eor #$80
:
.endmacro
