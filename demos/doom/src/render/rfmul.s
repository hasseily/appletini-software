; Doom for the Appletini -- the renderer's fast multiplies and divisions
; (docs/DESIGN.md section 7).
;
; The general umul/smul of rmath.s loop over the bytes; the renderer's hot
; products have fixed shapes, so each gets an unrolled routine that makes
; only the result bytes its caller uses:
;
;   8x8 by quarter squares: a*b = sqr[a+b] - nsqr[b-a+255] (tables.s
;   mul_sqr, mul_nsqr, 512 entries, page aligned). Four zero-page pointers
;   ms1..ms4 point at sqr_lo + a, nsqr_lo + (255 - a), sqr_hi + a,
;   nsqr_hi + (255 - a) (their high bytes never change, the low bytes are
;   a and ~a), so a product is ldy b / lda (ms1),y / sbc (ms2),y and the
;   same for the high byte: about 50 cycles with its accumulation. A zero
;   byte of either operand skips its products (small magnitudes are
;   common: heights, sign-extended values).
;
;   mulu_A_B_R   m_r[0..R-1] = the low R bytes of m_a[0..A-1] * m_b[0..B-1]
;   muls_A_B_R   the same, signed operands (two's complement): magnitudes
;                multiplied, the result negated (exact modulo 2^(8R))
;
;   div_scale    (d_n (3 bytes, num) << 6) / d_d (3 bytes, den) -> d_n (3
;                bytes), for R_ScaleFromGlobalAngle: the quotient is known
;                to be < 2^22, so 22 quotient bits, and whole bytes of
;                leading zeros are skipped first
;   div_step     d_n (24-bit signed) / A (1..159) truncating -> d_n
;
; mul_init sets the pointers' high bytes (render_frame, every frame: the
; zero page is shared with the kernel's start-up only, but it is cheap).

.include "kernel.inc"
.include "rdefs.inc"
.macpack longbranch
.include "rmul.inc"

.ifdef BANKED_GAME
.segment "RZP": zeropage
.else
.segment "KZP": zeropage
.endif
ms1:        .res 2
ms2:        .res 2
ms3:        .res 2
ms4:        .res 2
mfneg:      .res 1
dq:         .res 3              ; div_scale: dividend bits / quotient
drm:        .res 3              ; div_scale: remainder

.segment "RLCHI"

; the seg loop's tables (read by main-memory code; here for the room)
shr4tab:                        ; v >> 4
        .repeat 256, i
        .byte   i >> 4
        .endrepeat
shl4tab:                        ; (v << 4) & $F0
        .repeat 256, i
        .byte   (i << 4) & $F0
        .endrepeat
bitlen:                         ; the number of bits of v
        .byte   0
        .repeat 255, i
        .byte   .max(1, .min(8, 1 + (((i + 1) >= 2) + ((i + 1) >= 4) + ((i + 1) >= 8) + ((i + 1) >= 16) + ((i + 1) >= 32) + ((i + 1) >= 64) + ((i + 1) >= 128))))
        .endrepeat
sar4tab:                        ; v >> 4, arithmetic (v signed)
        .repeat 256, i
        .byte   (i >> 4) | ((i & $80) >> 3) | ((i & $80) >> 2) | ((i & $80) >> 1) | (i & $80)
        .endrepeat
.export shr4tab, shl4tab, bitlen, sar4tab

mul_init:
        lda     #>mul_sqr_lo
        sta     ms1+1
        lda     #>mul_nsqr_lo
        sta     ms2+1
        lda     #>mul_sqr_hi
        sta     ms3+1
        lda     #>mul_nsqr_hi
        sta     ms4+1
        rts

mulu_1_3_3:     MULU 1, 3, 3
                rts
mulu_3_2_5:     MULU 3, 2, 5
                rts
mulu_3_3_5:     MULU 3, 3, 5
                rts
mulu_3_3_4:     MULU 3, 3, 4
                rts
mulu_4_2_4:     MULU 4, 2, 4
                rts
mulu_4_2_5:     MULU 4, 2, 5
                rts
mulu_2_3_3:     MULU 2, 3, 3
                rts
muls_3_2_5:     MULS 3, 2, 5, mulu_3_2_5
muls_3_3_5:     MULS 3, 3, 5, mulu_3_3_5
muls_3_3_4:     MULS 3, 3, 4, mulu_3_3_4
muls_4_2_4:     MULS 4, 2, 4, mulu_4_2_4
muls_2_3_3:     MULS 2, 3, 3, mulu_2_3_3

.export mul_init, mulu_1_3_3, mulu_3_2_5, mulu_4_2_5, mulu_3_3_5
.export muls_3_2_5, muls_3_3_5, muls_3_3_4, muls_4_2_4, muls_2_3_3

; ---------------------------------------------------------------------------
; div_scale: q = (num << 6) / den, num = d_n (3 bytes, 0 < num < 2^21), den
; = d_d (3 bytes, > 0), q < 2^22 -> d_n (3 bytes)
;
; The 22-bit dividend register dq starts as num's low 16 bits followed by
; zeros (dq = num.lo16 << 8), the remainder as num >> 16: 22 steps shift
; one bit from dq into the remainder and one quotient bit into dq. While
; the remainder with the next whole byte is still below den, that byte is
; moved at once (8 steps of zero quotient bits).
div_scale:
        lda     d_n+2
        sta     drm
        stz     drm+1
        stz     drm+2
        stz     dq
        lda     d_n
        sta     dq+1
        lda     d_n+1
        sta     dq+2
        ldx     #22
@skip:  ; (drm << 8 | dq+2) < den ? (drm < 2^16 here)
        cpx     #9
        bcc     @loop
        lda     drm+1
        cmp     d_d+2
        bcc     @byte
        bne     @loop
        lda     drm
        cmp     d_d+1
        bcc     @byte
        bne     @loop
        lda     dq+2
        cmp     d_d
        bcs     @loop
@byte:  lda     drm+1
        sta     drm+2
        lda     drm
        sta     drm+1
        lda     dq+2
        sta     drm
        lda     dq+1
        sta     dq+2
        lda     dq
        sta     dq+1
        stz     dq
        txa
        sec
        sbc     #8
        tax
        bra     @skip
@loop:  ; the quotient bits enter dq through the carry as the dividend's
        ; bits leave it (the last one after the loop)
        clc
        lda     d_d+2
        bne     @l24
        ; den < 2^16: the remainder fits 16 bits and a carry
@l16:   rol     dq
        rol     dq+1
        rol     dq+2
        rol     drm
        rol     drm+1
        bcs     @s16                    ; past 16 bits: >= den
        lda     drm
        cmp     d_d
        lda     drm+1
        sbc     d_d+1
        bcc     @n16
@s16:   lda     drm
        sbc     d_d
        sta     drm
        lda     drm+1
        sbc     d_d+1
        sta     drm+1
        sec
@n16:   dex
        bne     @l16
        bra     @last
@l24:   rol     dq
        rol     dq+1
        rol     dq+2
        rol     drm
        rol     drm+1
        rol     drm+2
        lda     drm
        sec
        sbc     d_d
        tay
        lda     drm+1
        sbc     d_d+1
        sta     mfneg
        lda     drm+2
        sbc     d_d+2
        bcc     @no
        sta     drm+2
        lda     mfneg
        sta     drm+1
        sty     drm
@no:    dex
        bne     @l24
@last:  rol     dq
        rol     dq+1
        rol     dq+2
        lda     dq
        sta     d_n
        lda     dq+1
        sta     d_n+1
        lda     dq+2
        sta     d_n+2
        rts

; div_step: d_n (24-bit signed) / A (1..255), truncating toward zero -> d_n
div_step:
        sta     mfneg+0                 ; (reused: the divisor)
        stz     dq                      ; the sign
        lda     d_n+2
        bpl     :+
        NEGN    d_n, 3
        lda     #$80
        sta     dq
:       lda     #0
        ldx     #24
@l:     asl     d_n
        rol     d_n+1
        rol     d_n+2
        rol     a
        bcs     @sub
        cmp     mfneg
        bcc     @n
@sub:   sbc     mfneg
        inc     d_n
@n:     dex
        bne     @l
        bit     dq
        bpl     :+
        NEGN    d_n, 3
:       rts

.export div_scale, div_step
