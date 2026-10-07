; game/tracel/tracel.s: part tracel of the game's tic code (docs/GAME.md:
; the trace and its intercepts): the intercepts of the lines a
; trace crosses. GPL-2: rewritten from upstream's p_trace65.s
; (PIT_AddLineIntercepts:985, divlineSide:152, interceptVector3:242 with
; ivB, ivSlow, ivTest and its fixedDiv and fdLoop, ivProd, ivAxis,
; addIntercept:744, icInsert:778, lineCross, vtxSlow, gOf, smul, vsC,
; ivSetup:1875), Doom8088: Apple IIgs Edition. Nothing here comes from
; upstream's cal_integer.s: fixedDiv is p_trace65.s's own long division
; (p_trace65.s:398-541, 686-742), mirrored step by step, and the products
; are math.s's (mul32, fixmul, umul16, umul16lo).
;
; The places (the trace, the intercepts, the zero page) are tracel.inc's.
; Every routine is upstream's, with its quirks:
;
;   PIT_AddLineIntercepts  ITTAB's callback (part geom's convention): the
;               line in GA_0-1. The sides of the line's two vertices
;               against the trace (vtxSlow: divlineSide) for a long
;               trace, else of the trace's two ends against the line
;               (P_PointOnLineSide, part geom); crossed: lineCross. Out:
;               C clear when the intercepts are full (stop), else set.
;   divlineSide  P_PointOnDivlineSide(TL_PX, TL_PY, the trace): A = 0, 1
;               (the axis cases first; then the signs; then the products
;               of the whole parts (y >> 8)(dx >> 16) >= (dy >> 16)(x >> 8),
;               signed, as upstream's SIDEPROD). Changes TL_PX, TL_PY.
;   interceptVector3  TL_F = P_InterceptVector3(trace, dl): num = a + b,
;               den = c - d (a, b: SIDEPROD; c, d: ivProd), then ivTest;
;               an axis dl skips its two products as upstream does.
;   ivTest      TL_F from num TL_A and den TL_B: 0 when one is 0, -1 when
;               their signs differ, else fixedDiv.
;   fixedDiv    (in ivTest) upstream's FixedDiv: both negated when num < 0;
;               the guard "b < 2^30 and a < b" takes the fast loop (16
;               bits of a 2^16 / b, unsigned compares: upstream's fdLoop);
;               else b is shifted while b < a (signed), ibit with it (16
;               bits: 0 after 16 shifts), the bits of ch with signed
;               compares, then the 16 bits of cl the same way: upstream's
;               results, its wraps for operands of 2^30 and more included.
;               One input upstream never returns from: b shifted to 0
;               while it is below a (it loops forever, p_trace65.s:430-438);
;               natively the result is $7FFFFFFF (C's FixedDiv for an
;               overflow of one sign) and GT_DIV0 counts it, the port's
;               rule for its own divides (GAME.md).
;   ivProd      M_R = FixedMul(trace.d, dl.o >> 8) (X the axis: 0 trace.dx
;               and dl.dy, 4 trace.dy and dl.dx): in a shot (TL_IVON) with
;               dl.o in whole units in -4096..4095 the one product M (n << 3)
;               (ivSetup's M = d >> 11), else fixmul (upstream's ivSlow:
;               FixedMul or FixedMul3216, the same value).
;   ivAxis      the frac of an axis or 45-degree dl in a shot without its
;               products (upstream's tests, then ivTest on 256 N, 256 D):
;               C set and TL_F, or C clear (not decided).
;   lineCross   A:X a line: its dl, ivAxis or interceptVector3, and the
;               intercept when frac >= 0. Out: A = 0 (C clear) when the
;               intercepts are full, else 1 (C set).
;   vtxSlow     A:X a line, Y a vertex (LN_V1X or LN_V2X): divlineSide of
;               the vertex. vtxSlowR: the same as $80 side ^ TL_INVB.
;   addIntercept  the intercept (frac TL_F, what A:X: a line, or $8000 + a
;               mobj slot) at the list's end and into the by-frac chain.
;               Out: C clear when the list is full (64).
;   icInsert    A an entry: into the chain after every entry whose frac is
;               below or equal to its own (the search from TL_ICLAST when
;               that one's frac is not above), TL_ICLAST = A.
;   ivSetup     M of each trace delta into TL_IVM (dy first, then dx) when
;               its 11 low bits are 0 and its high word is in -2048..2047.
;               Out: A = 1 both, 0 not (TL_IVON is sideSetup's).
;   gOf         A:X = ceil(f / 256) - 256 (f != 0), 0 for 0: f in A:X.
;   smul        M_R = M_A M_B, signed 16 x 16.
;   vsC         TL_VCV = C - VBV - VJ SQ, TL_VCT = -VJ SQ - VBTH of SIDE1
;               (part tracet's sideSetup) from TL_VSQ, TL_VAX, TL_VG.
;   vtxSlowL, lineCrossL, icInsertL: upstream's long-call wrappers have
;               no native code: their callers FCALL vtxSlow, lineCross,
;               icInsert.
;
; Every call between the part's routines is an FCALL (the placement may
; put them in different groups); the math is resident (jsr).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/tracel/tracel.inc"

        .export PIT_AddLineIntercepts, divlineSide, interceptVector3
        .export addIntercept, icInsert, ivSetup, ivTest, ivProd, ivAxis
        .export lineCross, vtxSlow, vtxSlowR
        .export gOf, smul, vsC
        .export TL_TRACE, TL_TRLONG, TL_ICN, TL_ICLAST, TL_IVON, TL_IVM
        .export TL_INVB, TL_LD, TL_S1
        .import ln_get, mul32, fixmul, umul16, umul16lo
        .import fc_call, fc_unbuilt

VJ      = 23                    ; SIDE1's constants (p_trace65.s:30-50)
VBV     = 5
VBTH    = 21

; ===========================================================================
; PIT_AddLineIntercepts
; ===========================================================================
        ROUTINE PIT_AddLineIntercepts
        lda GA_0                        ; the line
        sta TL_LD
        lda GA_1
        sta TL_LD+1
        lda TL_TRLONG
        beq @short
        lda TL_LD                       ; a long trace: the vertices'
        ldx TL_LD+1                     ;   sides against it
        ldy #LN_V1X
        FCALL vtxSlow
        sta TL_S1
        lda TL_LD
        ldx TL_LD+1
        ldy #LN_V2X
        FCALL vtxSlow
        bra @cmp
@short: ldx #7                          ; s1 = P_PointOnLineSide(trace.x,
:       lda TR_X,x                      ;   trace.y, ld)
        sta GA_X,x
        dex
        bpl :-
        lda TL_LD
        ldx TL_LD+1
        FCALL P_PointOnLineSide
        sta TL_S1
        clc                             ; s2: of trace.x + trace.dx,
        ldx #0                          ;   trace.y + trace.dy
        ldy #4
:       lda TR_X,x
        adc TR_DX,x
        sta GA_X,x
        inx
        dey
        bne :-
        clc
        ldy #4
:       lda TR_X,x
        adc TR_DX,x
        sta GA_X,x
        inx
        dey
        bne :-
        lda TL_LD
        ldx TL_LD+1
        FCALL P_PointOnLineSide
@cmp:   cmp TL_S1                       ; s1 == s2: not crossed
        beq @on
        lda TL_LD
        ldx TL_LD+1
        FCALL lineCross                 ; (C: 0 full)
        rts
@on:    sec
        rts

; ===========================================================================
; divlineSide: A = P_PointOnDivlineSide(TL_PX, TL_PY, the trace)
; ===========================================================================
        ROUTINE divlineSide
        lda TR_DX
        ora TR_DX+1
        ora TR_DX+2
        ora TR_DX+3
        bne @dxnz
        lda TR_X                        ; dx 0: line->x < x ?
        cmp TL_PX
        lda TR_X+1
        sbc TL_PX+1
        lda TR_X+2
        sbc TL_PX+2
        lda TR_X+3
        sbc TL_PX+3
        bvc :+
        eor #$80
:       bmi @dyneg
        lda TR_DY+3                     ; x <= line->x: dy > 0
        bmi @r0
        ora TR_DY+2
        ora TR_DY+1
        ora TR_DY
        beq @r0
        bra @r1
@dyneg: lda TR_DY+3                     ; dy < 0
        bmi @r1
        bra @r0
@dxnz:  lda TR_DY
        ora TR_DY+1
        ora TR_DY+2
        ora TR_DY+3
        bne @gen
        lda TR_Y                        ; dy 0: line->y < y ?
        cmp TL_PY
        lda TR_Y+1
        sbc TL_PY+1
        lda TR_Y+2
        sbc TL_PY+2
        lda TR_Y+3
        sbc TL_PY+3
        bvc :+
        eor #$80
:       bmi @dxpos
        lda TR_DX+3                     ; y <= line->y: dx < 0
        bmi @r1
        bra @r0
@dxpos: lda TR_DX+3                     ; dx > 0
        bmi @r0
        ora TR_DX+2
        ora TR_DX+1
        ora TR_DX
        beq @r0
        bra @r1
@r0:    lda #0
        rts
@r1:    lda #1
        rts
@gen:   sec                             ; x -= line->x, y -= line->y
        ldx #0
        ldy #4
:       lda TL_PX,x
        sbc TR_X,x
        sta TL_PX,x
        inx
        dey
        bne :-
        sec
        ldy #4
:       lda TL_PX,x
        sbc TR_X,x
        sta TL_PX,x
        inx
        dey
        bne :-
        lda TR_DY+3                     ; the signs differ: (dy ^ x) < 0
        eor TR_DX+3
        eor TL_PX+3
        eor TL_PY+3
        bpl @prod
        lda TR_DY+3
        eor TL_PX+3
        bmi @r1
        bra @r0
@prod:  SIDEPROD TL_PY, TR_DX           ; left = (y >> 8) (dx >> 16)
        ldx #3
:       lda M_R,x
        sta TL_A,x
        dex
        bpl :-
        SIDEPROD TL_PX, TR_DY           ; right = (dy >> 16) (x >> 8)
        clc                             ; left >= right: right - left - 1
        lda M_R                         ;   < 0
        sbc TL_A
        lda M_R+1
        sbc TL_A+1
        lda M_R+2
        sbc TL_A+2
        lda M_R+3
        sbc TL_A+3
        bvc :+
        eor #$80
:       jmi @r1
        jmp @r0

; ===========================================================================
; interceptVector3: TL_F = P_InterceptVector3(the trace, dl)
; ===========================================================================
        ROUTINE interceptVector3
        lda TL_DY                       ; dl.dy == 0: a = c = 0
        ora TL_DY+1
        ora TL_DY+2
        ora TL_DY+3
        bne @a
        lda TL_DX
        ora TL_DX+1
        ora TL_DX+2
        ora TL_DX+3
        bne @b
        stz TL_F                        ; dl.dx == 0 too: 0
        stz TL_F+1
        stz TL_F+2
        stz TL_F+3
        rts
@a:     sec                             ; a = (dl.dy >> 16) ((dl.x -
        ldx #0                          ;   trace.x) >> 8)
        ldy #4
:       lda TL_X1,x
        sbc TR_X,x
        sta TL_D,x
        inx
        dey
        bne :-
        SIDEPROD TL_D, TL_DY
        ldx #3
:       lda M_R,x
        sta TL_A,x
        dex
        bpl :-
        ldx #0                          ; c = FixedMul(trace.dx, dl.dy >> 8)
        FCALL ivProd
        ldx #3
:       lda M_R,x
        sta TL_B,x
        dex
        bpl :-
        lda TL_DX                       ; dl.dx == 0: b = d = 0
        ora TL_DX+1
        ora TL_DX+2
        ora TL_DX+3
        bne @b
        FCALL ivTest
        rts
@b:     sec                             ; b = (dl.dx >> 16) ((trace.y -
        ldx #0                          ;   dl.y) >> 8)
        ldy #4
:       lda TR_Y,x
        sbc TL_Y1,x
        sta TL_D,x
        inx
        dey
        bne :-
        SIDEPROD TL_D, TL_DX
        lda TL_DY                       ; num = a + b (dl.dy == 0: b)
        ora TL_DY+1
        ora TL_DY+2
        ora TL_DY+3
        bne @sum
        ldx #3
:       lda M_R,x
        sta TL_A,x
        dex
        bpl :-
        bra @d
@sum:   clc
        ldx #0
        ldy #4
:       lda TL_A,x
        adc M_R,x
        sta TL_A,x
        inx
        dey
        bne :-
@d:     ldx #4                          ; d = FixedMul(trace.dy, dl.dx >> 8)
        FCALL ivProd
        lda TL_DY                       ; den = c - d (dl.dy == 0: -d)
        ora TL_DY+1
        ora TL_DY+2
        ora TL_DY+3
        bne @dif
        sec
        ldx #0
        ldy #4
:       lda #0
        sbc M_R,x
        sta TL_B,x
        inx
        dey
        bne :-
        bra @test
@dif:   sec
        ldx #0
        ldy #4
:       lda TL_B,x
        sbc M_R,x
        sta TL_B,x
        inx
        dey
        bne :-
@test:  FCALL ivTest
        rts

; ===========================================================================
; ivTest: TL_F from num TL_A, den TL_B: the guards, then fixedDiv
; ===========================================================================
        ROUTINE ivTest
        lda TL_A                        ; num == 0 || den == 0: 0
        ora TL_A+1
        ora TL_A+2
        ora TL_A+3
        beq @zero
        lda TL_B
        ora TL_B+1
        ora TL_B+2
        ora TL_B+3
        bne @signs
@zero:  stz TL_F
        stz TL_F+1
        stz TL_F+2
        stz TL_F+3
        rts
@signs: lda TL_A+3                      ; (num ^ den) < 0: -1
        eor TL_B+3
        bpl @div
        lda #$FF
        sta TL_F
        sta TL_F+1
        sta TL_F+2
        sta TL_F+3
        rts
        ; fixedDiv (p_trace65.s:405-541): a < 0: a = -a, b = -b
@div:   bit TL_A+3
        bpl @pos
        sec
        ldx #0
        ldy #4
:       lda #0
        sbc TL_A,x
        sta TL_A,x
        inx
        dey
        bne :-
        sec
        ldx #0
        ldy #4
:       lda #0
        sbc TL_B,x
        sta TL_B,x
        inx
        dey
        bne :-
        ; the guard: 0 <= a < b < 2^30 (unsigned): ch = 0 and the fast
        ; loop (fdLoop) makes cl from 2a
@pos:   lda TL_B+3
        cmp #$40
        bcs @slow
        lda TL_A
        cmp TL_B
        lda TL_A+1
        sbc TL_B+1
        lda TL_A+2
        sbc TL_B+2
        lda TL_A+3
        sbc TL_B+3
        bcs @slow
        stz TL_CH
        stz TL_CH+1
        asl TL_A                        ; 2a
        rol TL_A+1
        rol TL_A+2
        rol TL_A+3
        lda #1                          ; cl: 16 bits above a start bit
        sta TL_F
        stz TL_F+1
@ubit:  lda TL_A                        ; a >= b (unsigned): a -= b, the
        sec                             ;   bit 1
        sbc TL_B
        sta TL_D
        lda TL_A+1
        sbc TL_B+1
        sta TL_D+1
        lda TL_A+2
        sbc TL_B+2
        sta TL_D+2
        lda TL_A+3
        sbc TL_B+3
        bcc @u0
        sta TL_A+3
        lda TL_D
        sta TL_A
        lda TL_D+1
        sta TL_A+1
        lda TL_D+2
        sta TL_A+2
@u0:    rol TL_F                        ; (C: the bit)
        rol TL_F+1
        bcs @done                       ; the start bit out: 16 bits
        asl TL_A                        ; a <<= 1
        rol TL_A+1
        rol TL_A+2
        rol TL_A+3
        bra @ubit
@done:  lda TL_CH                       ; (ch << 16) | cl
        sta TL_F+2
        lda TL_CH+1
        sta TL_F+3
        rts
        ; while (b < a) { b <<= 1; ibit <<= 1; } (signed; ibit 16 bits)
@slow:  lda #1
        sta TL_IB
        stz TL_IB+1
@shift: lda TL_B
        cmp TL_A
        lda TL_B+1
        sbc TL_A+1
        lda TL_B+2
        sbc TL_A+2
        lda TL_B+3
        sbc TL_A+3
        bvc :+
        eor #$80
:       bpl @chs
        lda TL_B                        ; b == 0 below a: upstream never
        ora TL_B+1                      ;   returns (the port's result,
        ora TL_B+2                      ;   counted)
        ora TL_B+3
        beq @hang
        asl TL_B
        rol TL_B+1
        rol TL_B+2
        rol TL_B+3
        asl TL_IB
        rol TL_IB+1
        bra @shift
@hang:  lda #$FF
        sta TL_F
        sta TL_F+1
        sta TL_F+2
        lda #$7F
        sta TL_F+3
        inc GT_DIV0
        bne :+
        inc GT_DIV0+1
:       rts
        ; the bits of ch, then of cl, in TL_F (16 bits): signed compares
@chs:   stz TL_F
        stz TL_F+1
        lda TL_IB
        ora TL_IB+1
        bne @sbit
        stz TL_CH                       ; ibit 0 (16 shifts or more): ch 0
        stz TL_CH+1
        bra @cl
@sbit:  jsr @step                       ; C: the bit (a changed)
        rol TL_F
        rol TL_F+1                      ; (never a 1 out: at most 16 bits)
        asl TL_A                        ; a <<= 1
        rol TL_A+1
        rol TL_A+2
        rol TL_A+3
        lsr TL_IB+1                     ; the next bit of ch
        ror TL_IB
        lda TL_IB
        ora TL_IB+1
        bne @sbit
        lda TL_F                        ; ch done
        sta TL_CH
        lda TL_F+1
        sta TL_CH+1
@cl:    lda #1                          ; cl: 16 bits above a start bit
        sta TL_F
        stz TL_F+1
@cbit:  jsr @step
        rol TL_F
        rol TL_F+1
        jcs @done
        asl TL_A
        rol TL_A+1
        rol TL_A+2
        rol TL_A+3
        bra @cbit
        ; @step: a >= b (signed): a -= b and C set, else C clear
@step:  sec
        lda TL_A
        sbc TL_B
        sta TL_D
        lda TL_A+1
        sbc TL_B+1
        sta TL_D+1
        lda TL_A+2
        sbc TL_B+2
        sta TL_D+2
        lda TL_A+3
        sbc TL_B+3
        sta TL_D+3
        bvc :+
        eor #$80
:       bpl @ge
        clc
        rts
@ge:    lda TL_D
        sta TL_A
        lda TL_D+1
        sta TL_A+1
        lda TL_D+2
        sta TL_A+2
        lda TL_D+3
        sta TL_A+3
        sec
        rts

; ===========================================================================
; ivProd: M_R = FixedMul(trace.d, dl.o >> 8); X the axis (0: trace.dx and
; dl.dy, 4: trace.dy and dl.dx)
; ===========================================================================
        ROUTINE ivProd
        txa                             ; Y = 4 - X: dl.o
        eor #4
        tay
        lda TL_IVON                     ; a shot, dl.o in whole units, n =
        beq @slow                       ;   dl.o >> 16 in -4096..4095
        lda TL_DX,y
        ora TL_DX+1,y
        bne @slow
        lda TL_DX+3,y
        clc
        adc #$10
        cmp #$20
        bcs @slow
        lda TL_DX+2,y                   ; M_B = n << 3
        asl a
        sta M_B
        lda TL_DX+3,y
        rol a
        asl M_B
        rol a
        asl M_B
        rol a
        sta M_B+1
        lda TL_IVM,x                    ; M_A = ML
        sta M_A
        lda TL_IVM+1,x
        sta M_A+1
        lda TL_IVM+2,x                  ; the correction C = (MH & MB) +
        and M_B                         ;   (MB < 0 ? ML : 0)
        sta TL_D
        lda TL_IVM+3,x
        and M_B+1
        sta TL_D+1
        bit M_B+1
        bpl :+
        clc
        lda TL_D
        adc M_A
        sta TL_D
        lda TL_D+1
        adc M_A+1
        sta TL_D+1
:       jsr umul16                      ; M_R = ML MB, unsigned
        sec                             ; the high word - C
        lda M_R+2
        sbc TL_D
        sta M_R+2
        lda M_R+3
        sbc TL_D+1
        sta M_R+3
        rts
@slow:  lda TR_DX,x                     ; fixmul(trace.d, dl.o >> 8)
        sta M_A
        lda TR_DX+1,x
        sta M_A+1
        lda TR_DX+2,x
        sta M_A+2
        lda TR_DX+3,x
        sta M_A+3
        lda TL_DX+1,y
        sta M_B
        lda TL_DX+2,y
        sta M_B+1
        lda TL_DX+3,y
        sta M_B+2
        asl a
        lda #0
        bcc :+
        lda #$FF
:       sta M_B+3
        jmp fixmul

; ===========================================================================
; ivAxis: an axis or 45-degree dl of a shot: C set and TL_F, or C clear
; ===========================================================================
        ROUTINE ivAxis
        lda TL_IVON                     ; a shot
        jeq @no
        lda TL_DX+2                     ; X = 0: vertical (m = dl.dy), 4:
        ora TL_DX+3                     ;   horizontal (m = dl.dx)
        bne @dxh
        ldx #0
        lda TL_DY+2
        ldy TL_DY+3
        bra @m
@dxh:   lda TL_DY+2
        ora TL_DY+3
        jne @diag
        ldx #4
        lda TL_DX+2
        ldy TL_DX+3
@m:     clc                             ; |m| <= 2047: m + 2047 < 4095
        adc #<2047                      ;   (16 bits, unsigned)
        sta TL_D
        tya
        adc #>2047
        cmp #>4095
        bcc @mok
        jne @no
        lda TL_D                        ; (the high byte $0F: the low
        cmp #<4095                      ;   byte below $FF)
        jcs @no
@mok:   sec                             ; dl.o - trace.o
        lda TL_X1,x
        sbc TR_X,x
        sta TL_D
        lda TL_X1+1,x
        sbc TR_X+1,x
        sta TL_D+1
        lda TL_X1+2,x
        sbc TR_X+2,x
        sta TL_A+2
        lda TL_X1+3,x
        sbc TR_X+3,x
        sta TL_A+3
        cpx #4                          ; rounded up for y
        bne @rnd
        clc
        lda TL_D
        adc #$FF
        lda TL_D+1
        adc #0
        sta TL_D+1
        bcc @rnd
        inc TL_A+2
        bne @rnd
        inc TL_A+3
@rnd:   stz TL_A                        ; to 256
        lda TL_D+1
        sta TL_A+1
        lda TR_DX,x                     ; 256 D: trace.dx or trace.dy
        sta TL_B
        lda TR_DX+1,x
        sta TL_B+1
        lda TR_DX+2,x
        sta TL_B+2
        lda TR_DX+3,x
        sta TL_B+3
@sgn:   lda TL_B+3                      ; two signs: |256 N| < 2^28
        eor TL_A+3
        bpl @one
        lda TL_A+3
        clc
        adc #$10
        cmp #$20
        bcs @no
        bra @five
@one:   sec                             ; one sign: N - D has the sign of
        lda TL_A                        ;   -D and is not 0
        sbc TL_B
        sta TL_D
        lda TL_A+1
        sbc TL_B+1
        sta TL_D+1
        lda TL_A+2
        sbc TL_B+2
        sta TL_D+2
        lda TL_A+3
        sbc TL_B+3
        sta TL_D+3
        eor TL_B+3
        bpl @no
        lda TL_D+2
        ora TL_D+3
        bne @five
        lda TL_D
        ora TL_D+1
        beq @no
@five:  FCALL ivTest                    ; the zeros, the signs, fixedDiv
        sec
        rts
@no:    clc
        rts
@diag:  lda TL_DX                       ; 45 degrees: whole units, |p| =
        ora TL_DX+1                     ;   |q| <= 1023
        ora TL_DY
        ora TL_DY+1
        bne @no
        lda TL_DX+2                     ; |p| (16 bits) in TL_D
        ldx TL_DX+3
        jsr @abs
        cpx #>1024
        bcs @no
        sta TL_D
        stx TL_D+1
        lda TL_DY+2                     ; |q| == |p|
        ldx TL_DY+3
        jsr @abs
        cmp TL_D
        bne @no
        cpx TL_D+1
        bne @no
        sec                             ; F_x = (dl.x - trace.x) rounded
        lda TL_X1                       ;   down to 256 (TL_A)
        sbc TR_X
        lda TL_X1+1
        sbc TR_X+1
        sta TL_A+1
        lda TL_X1+2
        sbc TR_X+2
        sta TL_A+2
        lda TL_X1+3
        sbc TR_X+3
        sta TL_A+3
        stz TL_A
        sec                             ; F_y = (trace.y - dl.y) the same
        lda TR_Y                        ;   (TL_D)
        sbc TL_Y1
        lda TR_Y+1
        sbc TL_Y1+1
        sta TL_D+1
        lda TR_Y+2
        sbc TL_Y1+2
        sta TL_D+2
        lda TR_Y+3
        sbc TL_Y1+3
        sta TL_D+3
        stz TL_D
        lda TL_DX+3                     ; p, q of one sign: 256 N = F_x +
        eor TL_DY+3                     ;   F_y, 256 D = trace.dx - trace.dy
        bmi @two
        clc
        ldx #0
        ldy #4
:       lda TL_A,x
        adc TL_D,x
        sta TL_A,x
        inx
        dey
        bne :-
        sec
        ldx #0
        ldy #4
:       lda TR_DX,x
        sbc TR_DY,x
        sta TL_B,x
        inx
        dey
        bne :-
        jmp @sgn
@two:   sec                             ; two signs: 256 N = F_y - F_x,
        ldx #0                          ;   256 D = -trace.dx - trace.dy
        ldy #4
:       lda TL_D,x
        sbc TL_A,x
        sta TL_A,x
        inx
        dey
        bne :-
        sec
        ldx #0
        ldy #4
:       lda #0
        sbc TR_DX,x
        sta TL_B,x
        inx
        dey
        bne :-
        sec
        ldx #0
        ldy #4
:       lda TL_B,x
        sbc TR_DY,x
        sta TL_B,x
        inx
        dey
        bne :-
        jmp @sgn
@abs:   cpx #$80                        ; A:X = |A:X| (16 bits; -32768
        bcc :+                          ;   stays $8000)
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
; lineCross: A:X a line crossed by the trace: its intercept
; ===========================================================================
        ROUTINE lineCross
        sta TL_LD
        stx TL_LD+1
        jsr ln_get                      ; GC_LP: the line
        stz TL_X1                       ; dl: v1 and the deltas, whole
        stz TL_X1+1                     ;   units
        stz TL_Y1
        stz TL_Y1+1
        stz TL_DX
        stz TL_DX+1
        stz TL_DY
        stz TL_DY+1
        ldy #LN_V1X
        lda (GC_LP),y
        sta TL_X1+2
        iny
        lda (GC_LP),y
        sta TL_X1+3
        iny
        lda (GC_LP),y
        sta TL_Y1+2
        iny
        lda (GC_LP),y
        sta TL_Y1+3
        ldy #LN_DX
        lda (GC_LP),y
        sta TL_DX+2
        iny
        lda (GC_LP),y
        sta TL_DX+3
        ldy #LN_DY
        lda (GC_LP),y
        sta TL_DY+2
        iny
        lda (GC_LP),y
        sta TL_DY+3
        FCALL ivAxis                    ; an axis line of a shot
        bcs :+
        FCALL interceptVector3
:       lda TL_F+3                      ; frac < 0: behind the source
        bmi @one
        lda TL_LD                       ; (a line: bit 15 clear)
        ldx TL_LD+1
        FCALL addIntercept
        bcs @one
        lda #0                          ; full
        rts
@one:   lda #1
        sec
        rts

; ===========================================================================
; vtxSlow: A = divlineSide of vertex Y (LN_V1X, LN_V2X) of line A:X
; ===========================================================================
        ROUTINE vtxSlow
        phy
        jsr ln_get
        ply
        stz TL_PX
        stz TL_PX+1
        stz TL_PY
        stz TL_PY+1
        lda (GC_LP),y
        sta TL_PX+2
        iny
        lda (GC_LP),y
        sta TL_PX+3
        iny
        lda (GC_LP),y
        sta TL_PY+2
        iny
        lda (GC_LP),y
        sta TL_PY+3
        FCALL divlineSide
        rts

        ROUTINE vtxSlowR
        FCALL vtxSlow                   ; $80 side ^ TL_INVB
        lsr a
        lda #0
        ror a
        eor TL_INVB
        rts

; ===========================================================================
; addIntercept: frac TL_F, what A:X; C clear when the list is full
; ===========================================================================
        ROUTINE addIntercept
        ldy TL_ICN                      ; 64 already: full
        cpy #MAXINTERCEPTS
        bcc :+
        clc
        rts
:       pha
        phx
        tya
        ICPTR TL_P1
        ldy #5                          ; frac, what
        pla
        sta (TL_P1),y
        dey
        pla
        sta (TL_P1),y
        dey
:       lda TL_F,y
        sta (TL_P1),y
        dey
        bpl :-
        lda TL_ICN                      ; the next, and into the chain
        inc TL_ICN
        FCALL icInsert
        sec
        rts

; ===========================================================================
; icInsert: entry A into the by-frac chain
; ===========================================================================
        ROUTINE icInsert
        sta TL_NEW
        ICPTR TL_P1
        ldx TL_ICLAST                   ; from the last one put in when its
        cpx #IC_HEAD                    ;   frac is not above
        beq @walk
        txa
        ICPTR TL_P2
        FRACLT TL_P1, TL_P2
        bpl @from
        ldx #IC_HEAD
        bra @walk
@from:  ldx TL_ICLAST
@walk:  stx TL_PREV                     ; X: the link
        lda ICHAIN,x
        bmi @end                        ; (the end)
        tax                             ; its frac below the next one's:
        ICPTR TL_P2                     ;   here
        FRACLT TL_P1, TL_P2
        bpl @walk2
        txa
        bra @end
@walk2: bra @walk
@end:   ldx TL_NEW                      ; A: the next ($FF none)
        sta ICHAIN,x
        stx TL_ICLAST
        txa
        ldx TL_PREV
        sta ICHAIN,x
        rts

; ===========================================================================
; ivSetup: M = d >> 11 of each trace delta (dy, then dx) into TL_IVM
; ===========================================================================
        ROUTINE ivSetup
        ldx #4
@axis:  lda TR_DX,x                     ; the low 11 bits 0?
        bne @no
        lda TR_DX+1,x
        and #$07
        bne @no
        lda TR_DX+3,x                   ; H in -2048..2047?
        clc
        adc #$08
        cmp #$10
        bcs @no
        lda TR_DX+1,x                   ; ML = (H << 5) | (L >> 11): L >> 11
        lsr a                           ;   first
        lsr a
        lsr a
        sta TL_IVM,x
        lda TR_DX+2,x                   ; H << 5: its low byte in TL_IVM+1,
        sta TL_IVM+1,x                  ;   its high byte in A
        lda TR_DX+3,x
        ldy #5
:       asl TL_IVM+1,x
        rol a
        dey
        bne :-
        pha
        lda TL_IVM+1,x
        ora TL_IVM,x
        sta TL_IVM,x
        pla
        sta TL_IVM+1,x
        lda TR_DX+3,x                   ; MH: H's sign
        asl a
        lda #0
        bcc :+
        lda #$FF
:       sta TL_IVM+2,x
        sta TL_IVM+3,x
        dex
        dex
        dex
        dex
        bpl @axis
        lda #1
        rts
@no:    lda #0
        rts

; ===========================================================================
; gOf: A:X = ceil(f / 256) - 256 for f = A:X not 0, else 0
; ===========================================================================
        ROUTINE gOf
        cmp #0
        bne :+
        cpx #0
        beq @zero
:       sec                             ; v = (f - 1) >> 8
        sbc #1
        txa
        sbc #0
        cmp #$FF                        ; v - 255: 0 for v = 255, else
        beq @zero2                      ;   $FF00 + v + 1
        inc a
        ldx #$FF
        rts
@zero2: lda #0
@zero:  tax
        rts

; ===========================================================================
; smul: M_R = M_A M_B, signed 16 x 16
; ===========================================================================
        ROUTINE smul
        jsr umul16                      ; unsigned, then minus b << 16 for
        bit M_A+1                       ;   a < 0 and a << 16 for b < 0
        bpl :+
        sec
        lda M_R+2
        sbc M_B
        sta M_R+2
        lda M_R+3
        sbc M_B+1
        sta M_R+3
:       bit M_B+1
        bpl :+
        sec
        lda M_R+2
        sbc M_A
        sta M_R+2
        lda M_R+3
        sbc M_A+1
        sta M_R+3
:       rts

; ===========================================================================
; vsC: VT_CV and VT_CT of SIDE1 (tracet's sideSetup)
; ===========================================================================
        ROUTINE vsC
        lda TL_VAX                      ; g_sub SQ, rounded: + bit 15 of
        eor #4                          ;   its low word
        tax
        lda TL_VG,x
        sta M_A
        lda TL_VG+1,x
        sta M_A+1
        lda TL_VSQ
        sta M_B
        lda TL_VSQ+1
        sta M_B+1
        FCALL smul
        lda M_R+1
        asl a
        lda M_R+2
        adc #0
        sta TL_VCV
        lda M_R+3
        adc #0
        sta TL_VCV+1
        ldx TL_VAX                      ; ((g_main + 272) >> 5) - that - 8 -
        clc                             ;   VBV (16 bits)
        lda TL_VG,x
        adc #<272
        sta TL_VCT
        lda TL_VG+1,x
        adc #>272
        ldy #5
:       lsr a
        ror TL_VCT
        dey
        bne :-
        sta TL_VCT+1
        sec
        lda TL_VCT
        sbc TL_VCV
        sta TL_VCV
        lda TL_VCT+1
        sbc TL_VCV+1
        sta TL_VCV+1
        sec
        lda TL_VCV
        sbc #8 + VBV
        sta TL_VCV
        lda TL_VCV+1
        sbc #0
        sta TL_VCV+1
        lda TL_VSQ                      ; VJ SQ, the low word
        sta M_A
        lda TL_VSQ+1
        sta M_A+1
        lda #VJ
        sta M_B
        stz M_B+1
        jsr umul16lo
        lda M_R                         ; VT_CT = -VJ SQ - VBTH
        eor #$FF
        sec
        sbc #VBTH - 1
        sta TL_VCT
        lda M_R+1
        eor #$FF
        sbc #0
        sta TL_VCT+1
        lda M_R                         ; VT_CV = C - VBV - VJ SQ
        eor #$FF
        sec
        adc TL_VCV
        sta TL_VCV
        lda M_R+1
        eor #$FF
        adc TL_VCV+1
        sta TL_VCV+1
        rts
