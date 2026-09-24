; Doom for the Appletini -- the game's 32-bit work area and its operations
; (docs/DESIGN.md section 9).
;
; W is 256 bytes of four-byte slots (named in gwork.inc). The operations
; take slot offsets in X (the destination or left operand) and Y (the
; source or right operand):
;
;   w_mov   W[X] = W[Y]             w_add   W[X] += W[Y]
;   w_sub   W[X] -= W[Y]            w_neg   W[X] = -W[X]
;   w_abs   W[X] = |W[X]|           w_zero  W[X] = 0
;   w_cmp   A = sign(W[X] - W[Y]) signed: $FF, 0 or 1, with N and Z set
;           accordingly (bmi: less, beq: equal)
;   w_sign  A = sign(W[X]) the same way
;   w_ldi   W[X] = the 4 bytes that follow the JSR (execution resumes after)
;   w_fix   W[X] = (A low, Y high) << 16          (FIX of an int16)
;   w_sext  W[X] = (A low, Y high) sign-extended
;   w_sar8  W[X] = W[Y] >> 8 (arithmetic)
;   w_hi    A = low, X = high byte of W[X] >> 16 (the map-unit part)
;   w_ldo / w_sto     W[X] <-> the 4 bytes at (gmo)+Y  (a mobj's field)
;   w_ldp / w_stp     W[X] <-> the 4 bytes at (gpt)+Y
;   w_fixo, w_fixp, w_fixl  W[X] = FIX(the int16 at (gmo)/(gpt)/(gli)+Y)
;   w_sextl           W[X] = the int16 at (gli)+Y sign-extended
;   w_add3  W[X] = W[Y] + W[A]      w_sub3  W[X] = W[Y] - W[A]
;   w_tst   Z set iff W[X] == 0
;   w_mul   W_FR = FixedMul(W[X], W[Y])   w_div   W_FR = FixedDiv(W[X], W[Y])
;
; Each keeps the game's zero page; w_mul and w_div clobber what fx_mul and
; fx_div do (fixed.s). The C names of the core's fixed_t globals are slots
; of W, exported here.

.include "gmacros.inc"
.include "gwork.inc"
.import fx_mul, fx_div

.export w_mov, w_add, w_sub, w_neg, w_abs, w_zero, w_cmp, w_sign, w_ldi, w_fix
.export w_sext, w_sar8, w_hi, w_ldo, w_sto, w_ldp, w_stp, w_fixo, w_fixp, w_fixl
.export w_sextl, w_mul, w_div, w_tst, w_add3, w_sub3
.export _trace = W + W_TRACE
.export _opentop = W + W_OPENTOP, _openbottom = W + W_OPENBOTTOM
.export _openrange = W + W_OPENRANGE, _lowfloor = W + W_LOWFLOOR
.export _tmbbox = W + W_TMBBOX, _tmx = W + W_TMX, _tmy = W + W_TMY
.export _tmfloorz = W + W_TMFLOORZ, _tmceilingz = W + W_TMCEILINGZ
.export _tmdropoffz = W + W_TMDROPOFFZ
.export _attackrange = W + W_ATTACKRANGE, _aimslope = W + W_AIMSLOPE
.export _topslope = W + W_TOPSLOPE, _bottomslope = W + W_BOTTOMSLOPE

.segment "BSS"
W:      .res W_SIZE

.segment "CODE"

w_mov:  lda     W,y
        sta     W,x
        lda     W+1,y
        sta     W+1,x
        lda     W+2,y
        sta     W+2,x
        lda     W+3,y
        sta     W+3,x
        rts

w_add:  clc
        lda     W,x
        adc     W,y
        sta     W,x
        lda     W+1,x
        adc     W+1,y
        sta     W+1,x
        lda     W+2,x
        adc     W+2,y
        sta     W+2,x
        lda     W+3,x
        adc     W+3,y
        sta     W+3,x
        rts

w_sub:  sec
        lda     W,x
        sbc     W,y
        sta     W,x
        lda     W+1,x
        sbc     W+1,y
        sta     W+1,x
        lda     W+2,x
        sbc     W+2,y
        sta     W+2,x
        lda     W+3,x
        sbc     W+3,y
        sta     W+3,x
        rts

w_add3: pha
        jsr     w_mov
        ply
        bra     w_add

w_sub3: pha
        jsr     w_mov
        ply
        bra     w_sub

w_abs:  lda     W+3,x
        bpl     w_rts
w_neg:  sec
        lda     #0
        sbc     W,x
        sta     W,x
        lda     #0
        sbc     W+1,x
        sta     W+1,x
        lda     #0
        sbc     W+2,x
        sta     W+2,x
        lda     #0
        sbc     W+3,x
        sta     W+3,x
w_rts:  rts

w_zero: stz     W,x
        stz     W+1,x
        stz     W+2,x
        stz     W+3,x
        rts

w_cmp:  lda     W+3,x
        cmp     W+3,y
        bne     @top
        lda     W+2,x
        cmp     W+2,y
        bne     @u
        lda     W+1,x
        cmp     W+1,y
        bne     @u
        lda     W,x
        cmp     W,y
        bne     @u
        lda     #0
        rts
@u:     bcc     @lt
@gt:    lda     #1
        rts
@top:   sec
        sbc     W+3,y
        bvc     :+
        eor     #$80
:       bpl     @gt
@lt:    lda     #$FF
        rts

w_sign: lda     W+3,x
        bmi     @neg
        ora     W+2,x
        ora     W+1,x
        ora     W,x
        beq     @z
        lda     #1
        rts
@neg:   lda     #$FF
        rts
@z:     rts                             ; A = 0, Z set

; Z set iff W[X] == 0 (A destroyed)
w_tst:  lda     W,x
        ora     W+1,x
        ora     W+2,x
        ora     W+3,x
        rts

; W[X] = the dword after the JSR
w_ldi:  pla
        sta     tmp1
        pla
        sta     tmp2
        ldy     #1
        lda     (tmp1),y
        sta     W,x
        iny
        lda     (tmp1),y
        sta     W+1,x
        iny
        lda     (tmp1),y
        sta     W+2,x
        iny
        lda     (tmp1),y
        sta     W+3,x
        ; return past the data
        clc
        lda     tmp1
        adc     #4
        tay
        lda     tmp2
        adc     #0
        pha
        phy
        rts

w_fix:  stz     W,x
        stz     W+1,x
        sta     W+2,x
        tya
        sta     W+3,x
        rts

w_sext: sta     W,x
        tya
        sta     W+1,x
        and     #$80
        beq     :+
        lda     #$FF
:       sta     W+2,x
        sta     W+3,x
        rts

w_sar8: lda     W+1,y
        sta     W,x
        lda     W+2,y
        sta     W+1,x
        lda     W+3,y
        sta     W+2,x
        and     #$80
        beq     :+
        lda     #$FF
:       sta     W+3,x
        rts

w_hi:   lda     W+3,x
        pha
        lda     W+2,x
        plx
        rts

w_ldo:  lda     (gmo),y
        sta     W,x
        iny
        lda     (gmo),y
        sta     W+1,x
        iny
        lda     (gmo),y
        sta     W+2,x
        iny
        lda     (gmo),y
        sta     W+3,x
        rts

w_sto:  lda     W,x
        sta     (gmo),y
        iny
        lda     W+1,x
        sta     (gmo),y
        iny
        lda     W+2,x
        sta     (gmo),y
        iny
        lda     W+3,x
        sta     (gmo),y
        rts

w_ldp:  lda     (gpt),y
        sta     W,x
        iny
        lda     (gpt),y
        sta     W+1,x
        iny
        lda     (gpt),y
        sta     W+2,x
        iny
        lda     (gpt),y
        sta     W+3,x
        rts

w_stp:  lda     W,x
        sta     (gpt),y
        iny
        lda     W+1,x
        sta     (gpt),y
        iny
        lda     W+2,x
        sta     (gpt),y
        iny
        lda     W+3,x
        sta     (gpt),y
        rts

w_fixo: stz     W,x
        stz     W+1,x
        lda     (gmo),y
        sta     W+2,x
        iny
        lda     (gmo),y
        sta     W+3,x
        rts

w_fixp: stz     W,x
        stz     W+1,x
        lda     (gpt),y
        sta     W+2,x
        iny
        lda     (gpt),y
        sta     W+3,x
        rts

w_fixl: stz     W,x
        stz     W+1,x
        lda     (gli),y
        sta     W+2,x
        iny
        lda     (gli),y
        sta     W+3,x
        rts

w_sextl:
        lda     (gli),y
        sta     W,x
        iny
        lda     (gli),y
        sta     W+1,x
        and     #$80
        beq     :+
        lda     #$FF
:       sta     W+2,x
        sta     W+3,x
        rts

; W_FR = FixedMul(W[X], W[Y]) / FixedDiv(W[X], W[Y])
w_mul:  jsr     w_operands
        jmp     fx_mul
w_div:  jsr     w_operands
        jmp     fx_div
w_operands:
        lda     W,x
        sta     W+W_FA
        lda     W+1,x
        sta     W+W_FA+1
        lda     W+2,x
        sta     W+W_FA+2
        lda     W+3,x
        sta     W+W_FA+3
        lda     W,y
        sta     W+W_FB
        lda     W+1,y
        sta     W+W_FB+1
        lda     W+2,y
        sta     W+W_FB+2
        lda     W+3,y
        sta     W+W_FB+3
        rts
