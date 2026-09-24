; Doom for the Appletini -- the renderer's arithmetic (docs/DESIGN.md
; sections 5 and 7).
;
; Everything tools/refrender.py computes is an exact integer operation;
; these are the 65C02 versions the rest of the renderer builds on.
;
;   umul        m_r = m_a * m_b, unsigned; m_a has mul_na bytes, m_b mul_nb
;               (1..4 each), m_r gets mul_na + mul_nb bytes. Quarter
;               squares: a*b = sqr[a+b] - nsqr[a-b+255] (mul_sqr, mul_nsqr
;               of tables.s), one 8x8 product per byte pair, zero bytes
;               skipped. The table bases are self-modified per byte of
;               m_a, which is why the tables must sit on page boundaries
;               (the RRODATA start in src/doom.cfg; asserted below).
;   smul        the same, signed (two's complement operands and result)
;   udiv        d_n (32 bits) / d_d (32 bits): quotient in d_n, remainder
;               in d_r; leading zero bytes of the dividend are skipped
;   sdiv        truncating toward zero (div_trunc); d_n, d_d signed 32
;   fine_sin    A/X = fine angle (12 bits used) -> s_val, Q14
;   sin_bam     s_ang (BAM16) -> s_val: the fine sine interpolated with the
;               angle's low 4 bits, s0 + ((s1 - s0) * f >> 4)
;   cos_bam     sin_bam(s_ang + ANG90)
;   point_to_angle  pa_x, pa_y (24-bit signed sub-units) -> pa_r (BAM16),
;               Doom's octants and tantoangle; slope = (small << 10) / big
;               by a 10-step division (small <= big)
;   tan_fine    A/X = fine index 0..2047 -> t0..t2 (24-bit signed, 12
;               fraction bits)

.include "kernel.inc"
.include "rdefs.inc"
.include "rmul.inc"
.import shr4tab, shl4tab

.assert <mul_sqr_lo = 0 && <mul_sqr_hi = 0 && <mul_nsqr_lo = 0 && <mul_nsqr_hi = 0, lderror, "mul tables must be page aligned (RRODATA start in doom.cfg)"

.segment "KZP": zeropage
mi:         .res 1              ; umul: index of the m_a byte
mj:         .res 1              ; umul: index of the m_b byte
mlen:       .res 1              ; umul: result bytes
mneg:       .res 1              ; smul/sdiv: result sign
mplo:       .res 1              ; umul: the 8x8 product
fs_q:       .res 1              ; fine_sin
fs_hi:      .res 1
fs_i:       .res 2              ; sin_bam
fs_f:       .res 1
fs_s0:      .res 2
fs_p:       .res 2
mphi:       .res 1

; ---------------------------------------------------------------------------
; RHICODE: umul patches its own table operands
.segment "RHICODE"

umul:
        ; clear the result
        lda     mul_na
        clc
        adc     mul_nb
        sta     mlen
        tax
        lda     #0
:       dex
        sta     m_r,x
        bne     :-
        stz     mi
@ia:    ldx     mi
        lda     m_a,x
        beq     @nexti
        sta     @s1+1
        sta     @s2+1
        sta     @s3+1
        sta     @s4+1
        stz     mj
@jb:    ldx     mj
        lda     m_b,x
        beq     @nextj
        tay
        eor     #$FF
        tax
        sec
@s1:    lda     mul_sqr_lo,y
@s3:    sbc     mul_nsqr_lo,x
        sta     mplo
@s2:    lda     mul_sqr_hi,y
@s4:    sbc     mul_nsqr_hi,x
        sta     mphi
        lda     mi
        clc
        adc     mj
        tax
        lda     mplo
        clc
        adc     m_r,x
        sta     m_r,x
        inx
        lda     mphi
        adc     m_r,x
        sta     m_r,x
        bcc     @nextj
@carry: inx
        inc     m_r,x
        beq     @carry
@nextj: inc     mj
        lda     mj
        cmp     mul_nb
        bne     @jb
@nexti: inc     mi
        lda     mi
        cmp     mul_na
        bne     @ia
        rts

.segment "RCODE"

; smul: signed m_a (mul_na bytes) * m_b (mul_nb bytes) -> m_r (na + nb bytes)
smul:
        stz     mneg
        ldx     mul_na
        lda     m_a-1,x
        bpl     :+
        ldy     #0
        jsr     neg_a
        lda     #$80
        sta     mneg
:       ldx     mul_nb
        lda     m_b-1,x
        bpl     :+
        jsr     neg_b
        lda     mneg
        eor     #$80
        sta     mneg
:       jsr     umul
        bit     mneg
        bpl     :+
        ldx     #0
        ldy     mlen
        sec
@n:     lda     #0
        sbc     m_r,x
        sta     m_r,x
        inx
        dey
        bne     @n
:       rts

; neg_a / neg_b: negate m_a (mul_na bytes) / m_b (mul_nb bytes)
neg_a:  ldx     #0
        ldy     mul_na
        sec
:       lda     #0
        sbc     m_a,x
        sta     m_a,x
        inx
        dey
        bne     :-
        rts
neg_b:  ldx     #0
        ldy     mul_nb
        sec
:       lda     #0
        sbc     m_b,x
        sta     m_b,x
        inx
        dey
        bne     :-
        rts

; neg_n: negate d_n (32 bits)
neg_n:  sec
        lda     #0
        sbc     d_n
        sta     d_n
        lda     #0
        sbc     d_n+1
        sta     d_n+1
        lda     #0
        sbc     d_n+2
        sta     d_n+2
        lda     #0
        sbc     d_n+3
        sta     d_n+3
        rts

; ---------------------------------------------------------------------------
; udiv: d_n / d_d (unsigned 32) -> d_n quotient, d_r remainder
udiv:
        stz     d_r
        stz     d_r+1
        stz     d_r+2
        stz     d_r+3
        ldx     #32
        ; leading zero bytes of the dividend shift in nothing but zeros
@skip:  lda     d_n+3
        bne     @loop
        lda     d_n+2
        sta     d_n+3
        lda     d_n+1
        sta     d_n+2
        lda     d_n
        sta     d_n+1
        stz     d_n
        txa
        sec
        sbc     #8
        tax
        bne     @skip
        rts                             ; the dividend was 0
@loop:  asl     d_n
        rol     d_n+1
        rol     d_n+2
        rol     d_n+3
        rol     d_r
        rol     d_r+1
        rol     d_r+2
        rol     d_r+3
        sec
        lda     d_r
        sbc     d_d
        sta     t4
        lda     d_r+1
        sbc     d_d+1
        sta     t5
        lda     d_r+2
        sbc     d_d+2
        tay
        lda     d_r+3
        sbc     d_d+3
        bcc     @no
        sta     d_r+3
        sty     d_r+2
        lda     t5
        sta     d_r+1
        lda     t4
        sta     d_r
        inc     d_n
@no:    dex
        bne     @loop
        rts

; sdiv: d_n / d_d (signed 32), truncating toward zero -> d_n
sdiv:
        stz     mneg
        lda     d_n+3
        bpl     :+
        jsr     neg_n
        lda     #$80
        sta     mneg
:       lda     d_d+3
        bpl     :+
        sec
        lda     #0
        sbc     d_d
        sta     d_d
        lda     #0
        sbc     d_d+1
        sta     d_d+1
        lda     #0
        sbc     d_d+2
        sta     d_d+2
        lda     #0
        sbc     d_d+3
        sta     d_d+3
        lda     mneg
        eor     #$80
        sta     mneg
:       jsr     udiv
        bit     mneg
        bpl     :+
        jmp     neg_n
:       rts

; ---------------------------------------------------------------------------
; the sines: in RHICODE (the table loads patch their own high byte)
.segment "RHICODE"

; fine_sin: A (lo) / X (hi) = fine angle (12 bits used) -> s_val (Q14,
; signed). Quadrant q = bits 10-11, i = bits 0-9: q 0 sin[i], 1 sin[1024 - i],
; 2 -sin[i], 3 -sin[1024 - i] (the quarter wave has 1025 entries).
; Keeps t0..t3.
fine_sin:
        tay                             ; i low byte
        txa
        and     #$0F
        lsr     a
        lsr     a                       ; q
        sta     fs_q
        txa
        and     #3                      ; i high bits
        lsr     fs_q
        bcc     @even
        ; 1024 - i
        sta     fs_hi
        tya
        eor     #$FF
        clc
        adc     #1
        tay
        lda     #4
        sbc     fs_hi                   ; borrow from the low byte: 4 - hi - (lo != 0)
        bcs     @even                   ; (always: <= 4)
@even:  tax
        clc
        adc     #>finesine_lo
        sta     @lo+2
        txa
        clc
        adc     #>finesine_hi
        sta     @hi+2
@lo:    lda     finesine_lo & $FF,y
        sta     s_val
@hi:    lda     finesine_hi & $FF,y
        ldy     fs_q                    ; quadrants 2, 3 (now 1): negative
        beq     :+
        eor     #$FF
        sta     s_val+1
        lda     s_val
        eor     #$FF
        clc
        adc     #1
        sta     s_val
        bcc     :++
        inc     s_val+1
        rts
:       sta     s_val+1
:       rts

; cos_bam: s_ang + ANG90, then sin_bam
cos_bam:
        clc
        lda     s_ang+1
        adc     #>ANG90
        sta     s_ang+1
        ; fall through

; sin_bam: s_ang -> s_val = s0 + ((s1 - s0) * f >> 4), f = s_ang & 15,
; s0/s1 the fine sines of s_ang >> 4 and the next. Keeps t0..t3.
sin_bam:
        ldx     s_ang+1
        lda     shl4tab,x
        ldy     s_ang
        ora     shr4tab,y
        sta     fs_i                    ; fine index, low byte
        lda     shr4tab,x
        sta     fs_i+1                  ; high nibble
        tax
        lda     s_ang
        and     #15
        bne     @interp
        lda     fs_i
        jmp     fine_sin
@interp:
        sta     fs_f
        lda     fs_i
        jsr     fine_sin
        lda     s_val
        sta     fs_s0
        lda     s_val+1
        sta     fs_s0+1
        lda     fs_i
        clc
        adc     #1
        ldx     fs_i+1
        bcc     :+
        inx
:       jsr     fine_sin
        ; d = s1 - s0 (|d| < 32)
        sec
        lda     s_val
        sbc     fs_s0
        tax                             ; d, low byte (the magnitude fits it)
        lda     s_val+1
        sbc     fs_s0+1
        bmi     @neg
        ; p = d * f >> 4 (d >= 0): quarter squares, 16-bit product
        txa
        jsr     @mul
        ; >> 4
        tax
        lda     shr4tab,x
        ldx     fs_p+1
        ora     shl4tab,x
        clc
        adc     fs_s0
        sta     s_val
        lda     fs_s0+1
        adc     #0
        sta     s_val+1
        rts
@neg:   ; d < 0: p = -(|d| * f), p >> 4 = -((|d| * f + 15) >> 4)
        txa
        eor     #$FF
        inc     a
        jsr     @mul
        clc
        adc     #15
        tax
        lda     fs_p+1
        adc     #0
        tay
        lda     shr4tab,x
        ora     shl4tab,y               ; (|p| + 15) >> 4 (< 256)
        sta     fs_p
        sec
        lda     fs_s0
        sbc     fs_p
        sta     s_val
        lda     fs_s0+1
        sbc     #0
        sta     s_val+1
        rts
; @mul: A = |d| (< 32) -> A = low byte of |d| * f, fs_p+1 its high byte
@mul:   sta     ms1
        sta     ms3
        eor     #$FF
        sta     ms2
        sta     ms4
        ldy     fs_f
        sec
        lda     (ms1),y
        sbc     (ms2),y
        tax
        lda     (ms3),y
        sbc     (ms4),y
        sta     fs_p+1
        txa
        rts

; ---------------------------------------------------------------------------
; tan_fine: A (lo) / X (hi) = fine index 0..2047 -> t0..t2, 12 fraction bits:
; a >= 1024: tan_pos[a - 1024]; else -tan_pos[1023 - a]
tan_fine:
        cpx     #4
        bcc     @neg
        sta     p0                      ; a - 1024: hi - 4
        txa
        sec
        sbc     #4
        jsr     @fetch
        rts
@neg:   ; 1023 - a
        eor     #$FF
        sta     p0
        txa
        eor     #$03
        jsr     @fetch
        sec
        lda     #0
        sbc     t0
        sta     t0
        lda     #0
        sbc     t1
        sta     t1
        lda     #0
        sbc     t2
        sta     t2
        rts
@fetch: ; A = index hi (0..3), p0 = index lo -> t0..t2
        tax
        ldy     p0
        txa
        clc
        adc     #>finetangent_lo
        sta     p0+1
        lda     #<finetangent_lo
        sta     p0
        lda     (p0),y
        sta     t0
        txa
        clc
        adc     #>finetangent_mid
        sta     p0+1
        lda     #<finetangent_mid
        sta     p0
        lda     (p0),y
        sta     t1
        txa
        clc
        adc     #>finetangent_hi
        sta     p0+1
        lda     #<finetangent_hi
        sta     p0
        lda     (p0),y
        sta     t2
        rts

; ---------------------------------------------------------------------------
; point_to_angle: pa_x, pa_y (24-bit signed) -> pa_r (BAM16)
.segment "KZP": zeropage
pa_ax:      .res 3              ; |x|
pa_ay:      .res 3              ; |y|
pa_oct:     .res 1              ; bit 0: x < 0, bit 1: y < 0
pa_q:       .res 2              ; the slope / tantoangle value

.segment "RCODE"
point_to_angle:
        stz     pa_oct
        lda     pa_x
        ora     pa_x+1
        ora     pa_x+2
        bne     :+
        lda     pa_y
        ora     pa_y+1
        ora     pa_y+2
        bne     :+
        stz     pa_r
        stz     pa_r+1
        rts
:       ; |x|, |y| and the octant bits
        ldx     #2
:       lda     pa_x,x
        sta     pa_ax,x
        lda     pa_y,x
        sta     pa_ay,x
        dex
        bpl     :-
        bit     pa_x+2
        bpl     :+
        sec
        lda     #0
        sbc     pa_ax
        sta     pa_ax
        lda     #0
        sbc     pa_ax+1
        sta     pa_ax+1
        lda     #0
        sbc     pa_ax+2
        sta     pa_ax+2
        lda     #1
        sta     pa_oct
:       bit     pa_y+2
        bpl     :+
        sec
        lda     #0
        sbc     pa_ay
        sta     pa_ay
        lda     #0
        sbc     pa_ay+1
        sta     pa_ay+1
        lda     #0
        sbc     pa_ay+2
        sta     pa_ay+2
        lda     pa_oct
        ora     #2
        sta     pa_oct
:       ; x > y ?  (|x| - |y| - 1 >= 0 <=> |x| > |y|)
        clc
        lda     pa_ax
        sbc     pa_ay
        lda     pa_ax+1
        sbc     pa_ay+1
        lda     pa_ax+2
        sbc     pa_ay+2
        bcc     @xley
        ; x > y: slope(y, x)
        ldx     #pa_ay
        ldy     #pa_ax
        jsr     pa_slope
        lda     pa_oct
        asl     a
        tax
        jmp     (@gt,x)
@xley:  ; x <= y: slope(x, y)
        ldx     #pa_ax
        ldy     #pa_ay
        jsr     pa_slope
        lda     pa_oct
        asl     a
        tax
        jmp     (@le,x)
@gt:    .word   @gt_pp, @gt_np, @gt_pn, @gt_nn
@le:    .word   @le_pp, @le_np, @le_pn, @le_nn
; x >= 0, y >= 0, x > y: ta
@gt_pp: lda     pa_q
        sta     pa_r
        lda     pa_q+1
        sta     pa_r+1
        rts
; x >= 0, y >= 0: ANG90 - 1 - ta
@le_pp: lda     #<(ANG90 - 1)
        ldx     #>(ANG90 - 1)
        bra     @sub
; x >= 0, y < 0, x > y: -ta
@gt_pn: lda     #0
        tax
        bra     @sub
; x >= 0, y < 0: ANG270 + ta
@le_pn: lda     #<ANG270
        ldx     #>ANG270
        bra     @add
; x < 0, y >= 0, x > y: ANG180 - 1 - ta
@gt_np: lda     #<(ANG180 - 1)
        ldx     #>(ANG180 - 1)
        bra     @sub
; x < 0, y >= 0: ANG90 + ta
@le_np: lda     #<ANG90
        ldx     #>ANG90
        bra     @add
; x < 0, y < 0, x > y: ANG180 + ta
@gt_nn: lda     #<ANG180
        ldx     #>ANG180
        bra     @add
; x < 0, y < 0: ANG270 - 1 - ta
@le_nn: lda     #<(ANG270 - 1)
        ldx     #>(ANG270 - 1)
        ; fall through
@sub:   sec
        sbc     pa_q
        sta     pa_r
        txa
        sbc     pa_q+1
        sta     pa_r+1
        rts
@add:   clc
        adc     pa_q
        sta     pa_r
        txa
        adc     pa_q+1
        sta     pa_r+1
        rts

; pa_slope: X = zp address of num, Y = zp address of den (3 bytes each,
; num <= den, den > 0) -> pa_q = tantoangle[min((num << 10) / den, 1024)]
pa_slope:
        ; r = num (t0..t2), d = den (t3..t5)
        lda     0,x
        sta     t0
        lda     1,x
        sta     t1
        lda     2,x
        sta     t2
        lda     0,y
        sta     t3
        lda     1,y
        sta     t4
        lda     2,y
        sta     t5
        ; num == den: slope 1024
        lda     t0
        cmp     t3
        bne     @div
        lda     t1
        cmp     t4
        bne     @div
        lda     t2
        cmp     t5
        bne     @div
        lda     #<1024
        ldx     #>1024
        bra     @look
@div:   ; ten quotient bits, each the carry of the trial subtraction
        stz     pa_q
        stz     pa_q+1
        ldx     #10
        lda     t5
        bne     @bit
        ; den < 2^16 (the common case): a 16-bit remainder, bit 16 in C
@b16:   asl     t0
        rol     t1
        bcs     @s16                    ; past 16 bits: >= den
        lda     t0
        cmp     t3
        lda     t1
        sbc     t4
        bcc     @n16
@s16:   lda     t0
        sbc     t3
        sta     t0
        lda     t1
        sbc     t4
        sta     t1
        sec
@n16:   rol     pa_q
        rol     pa_q+1
        dex
        bne     @b16
        bra     @got
        ; r < d, so r << 1 fits 24 bits
@bit:   asl     t0
        rol     t1
        rol     t2
        lda     t0
        sec
        sbc     t3
        tay
        lda     t1
        sbc     t4
        sta     t6
        lda     t2
        sbc     t5
        bcc     @no
        sta     t2
        lda     t6
        sta     t1
        sty     t0
@no:    rol     pa_q
        rol     pa_q+1
        dex
        bne     @bit
@got:   lda     pa_q
        ldx     pa_q+1
@look:  ; pa_q = tantoangle[X:A]
        tay
        txa
        clc
        adc     #>tantoangle_lo
        sta     p0+1
        lda     #<tantoangle_lo
        sta     p0
        lda     (p0),y
        sta     pa_q
        txa
        clc
        adc     #>tantoangle_hi
        sta     p0+1
        lda     #<tantoangle_hi
        sta     p0
        lda     (p0),y
        sta     pa_q+1
        rts
