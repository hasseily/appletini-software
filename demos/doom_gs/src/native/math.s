; math.s: the native 65C02 math of the port (milestone 6; src/native/MATH.md).
;
; Bit-exact with upstream's routines (docs/NATIVE.md section 3.2 and 3.3),
; checked against them on ref816 (tools/native/mathcheck.py): the multiply
; family of m_fixed65.s and r_wall65.s, the reciprocals of m_recip65.s,
; FixedApproxDiv, P_AproxDistance, R_PointToAngle3 and R_PointToAngle16 of
; r_iigs65.s and p_path65.s, the sines and cosines of tables65.s, P_Random
; and M_Random of m_random65.s. A GPL-2 derivative of those files. The
; divides are the port's own, written from C semantics and the call sites
; only (never from upstream's vendor runtime), with the port's result for
; a division by zero (MATH.md).
;
; Interface: operands in M_A and M_B, results in M_R (math.inc), all
; little-endian; each routine lists what else it changes. None of them
; touches memory outside the math block ($B0-$D7), the stack, mt_far's two
; operand bytes in the card and, for the random numbers, their two indexes.
;
; Segments (src/native/math.cfg): MATHLC, the main card's bank 1
; $D800-$DBFF (the products, hot); MATHFAR, the RamWorks table reads (they
; run with RAMRD on, so they live in the card: the far layer's $DC00-$DFFF);
; MATHW, the rest, in a code window of main memory (W); MATHRND, the
; random table, page aligned in W.
;
; The render build (-D RENDER, src/native/render.mk; docs/RENDER.md 3.1):
; the same file for the render window, with the subset of MATHW the
; renderer calls (no R_PointToAngle3, P_AproxDistance, game sine and
; cosine or random numbers), and pta16 reading tantoangle from the aux
; card (ax_tanto of auxlc.s, MEMORY_MAP.md 4.3) instead of the tables
; bank: only that table read changes (MATH.md, "Not the aux card").

        .setcpu "65C02"
        .include "math.inc"

.ifdef GAMEMATH
; The game build (-D GAMEMATH): only mathgame.inc's routines, in the tic
; images' core (segment GCORE), beside the render build math-r.o, whose
; mt_far, udiv32 and octant table (pta_tab: OCTC, OCTMINUS) they use
; (docs/GAME.md "Wave 2 as integrated"; docs/game-parts/damage.md R1)
        .global pta3, pta_oct, finesine, finecosine, cosexc, aproxdist
        .import mt_far, udiv32, pta_tab
.else
        .export mt_init, mulw, umul16, umul16lo, mul8, qmulh, mul32
        .export fixmul, fixmul3216, fixmulang
        .export udiv16, sdiv16, udiv32, sdiv32
        .export recip, recipsmall, recipbig, approxdiv
.ifndef RENDER
        .export aproxdist
.endif
        .export pta16, sineapprox, cosineapprox
        .export mt_far, mt_recipe
        .export mt_far_count, mt_far_stride, pta_tab
.ifndef RENDER
        .export pta3, finesine, finecosine
        .export prandom, mrandom, mclearrandom, pta_oct
        .export rndtable, cosexc
.else
        .import ax_tanto
.endif
        ; for the harness (tools/native/mathrun.py reads the label file)
        .exportzp MZ, M_A, M_B, M_R, M_T, MT, MT_E, MT_P
        .export MT_PRND, MT_MRND, SQL
.endif

; ---------------------------------------------------------------------------
; Macros
; ---------------------------------------------------------------------------

; slot 0 (the multiplier's low byte) from A
.macro  SETW0
        sta PSL0
        sta PSH0
        eor #$FF
        sta PNL0
        sta PNH0
.endmacro

; slot 1 (the multiplier's high byte) from A
.macro  SETW1
        sta PSL1
        sta PSH1
        eor #$FF
        sta PNL1
        sta PNH1
.endmacro

; addr = -addr, 16 bits
.macro  NEG16 addr
        sec
        lda #0
        sbc addr
        sta addr
        lda #0
        sbc addr+1
        sta addr+1
.endmacro

; addr = -addr, 32 bits
.macro  NEG32 addr
        sec
        lda #0
        sbc addr
        sta addr
        lda #0
        sbc addr+1
        sta addr+1
        lda #0
        sbc addr+2
        sta addr+2
        lda #0
        sbc addr+3
        sta addr+3
.endmacro

; dst = src, 4 bytes
.macro  COPY32 src, dst
        lda src
        sta dst
        lda src+1
        sta dst+1
        lda src+2
        sta dst+2
        lda src+3
        sta dst+3
.endmacro

; ===========================================================================
; The products: main card bank 1, $D800-$DBFF
; ===========================================================================
.ifdef GAMEMATH
        .segment "GCORE"
OCTC     = pta_tab
OCTMINUS = pta_tab + 8
        .include "mathgame.inc"
.else
        .segment "MATHLC"

; ---------------------------------------------------------------------------
; mt_init: the high bytes of the quarter-square pointers. Once, before any
; product (the math block is the math's in every phase).
; ---------------------------------------------------------------------------
mt_init:
        lda #>SQL
        sta PSL0+1
        sta PSL1+1
        lda #>SQH
        sta PSH0+1
        sta PSH1+1
        lda #>NSL
        sta PNL0+1
        sta PNL1+1
        lda #>NSH
        sta PNH0+1
        sta PNH1+1
        rts

; ---------------------------------------------------------------------------
; umul16: M_R = M_A * M_B, unsigned 16 x 16 -> 32 (upstream's umul16,
; _Mul16, qmul). Changes A, X, Y, the slots, MT+8, MT+9.
; ---------------------------------------------------------------------------
umul16:
        lda M_A
        SETW0
        lda M_A+1
        SETW1
        ldy M_B
        ldx M_B+1
        ; fall into mulw

; ---------------------------------------------------------------------------
; mulw: M_R = (the word in the slots) * (X:Y), unsigned. A byte product is
; f(m + b) - f(|m - b|) (quarter squares), 16 bits from four table reads.
; The high byte of b at 0 skips its row. Changes A, X, Y, MT+8, MT+9.
; ---------------------------------------------------------------------------
mulw:
        stx MT+8                ; b1
        sec                     ; m0 * b0: bytes 0, 1
        lda (PSL0),y
        sbc (PNL0),y
        sta M_R
        lda (PSH0),y
        sbc (PNH0),y
        sta M_R+1
        sec                     ; m1 * b0: bytes 1, 2
        lda (PSL1),y
        sbc (PNL1),y
        tax
        lda (PSH1),y
        sbc (PNH1),y
        sta M_R+2               ; (at most $FE)
        txa
        clc
        adc M_R+1
        sta M_R+1
        bcc :+
        inc M_R+2
:       ldy MT+8
        bne @row1
        stz M_R+3
        rts
@row1:  sec                     ; m1 * b1: bytes 2, 3
        lda (PSL1),y
        sbc (PNL1),y
        sta MT+9
        lda (PSH1),y
        sbc (PNH1),y
        sta M_R+3               ; (at most $FE)
        sec                     ; m0 * b1: bytes 1, 2
        lda (PSL0),y
        sbc (PNL0),y
        tax
        lda (PSH0),y
        sbc (PNH0),y
        clc                     ; byte 2: its high byte + m1 b1's low byte
        adc MT+9
        bcc :+
        inc M_R+3
        clc
:       adc M_R+2
        sta M_R+2
        bcc :+
        inc M_R+3
:       txa                     ; byte 1: + its low byte
        clc
        adc M_R+1
        sta M_R+1
        bcc :+
        inc M_R+2
        bne :+
        inc M_R+3
:       rts

; ---------------------------------------------------------------------------
; umul16lo: M_R (16 bits) = the low word of M_A * M_B (upstream's umul16lo,
; IIGS_MulLo16). Three byte products, the two cross ones low bytes only.
; Changes A, Y, the slots (slot 1's high-byte pointers are left stale:
; every other user sets all four).
; ---------------------------------------------------------------------------
umul16lo:
        lda M_A
        SETW0
        ldy M_B
        sec                     ; a0 * b0
        lda (PSL0),y
        sbc (PNL0),y
        sta M_R
        lda (PSH0),y
        sbc (PNH0),y
        sta M_R+1
        ldy M_B+1               ; + the low byte of a0 * b1
        sec
        lda (PSL0),y
        sbc (PNL0),y
        clc
        adc M_R+1
        sta M_R+1
        lda M_A+1               ; + the low byte of a1 * b0
        sta PSL1
        eor #$FF
        sta PNL1
        ldy M_B
        sec
        lda (PSL1),y
        sbc (PNL1),y
        clc
        adc M_R+1
        sta M_R+1
        rts

; ---------------------------------------------------------------------------
; mul8: M_R (16 bits) = A * Y, unsigned bytes (the byte products of
; upstream's mul.inc). Changes A, slot 0.
; ---------------------------------------------------------------------------
mul8:
        SETW0
        sec
        lda (PSL0),y
        sbc (PNL0),y
        sta M_R
        lda (PSH0),y
        sbc (PNH0),y
        sta M_R+1
        rts

; ---------------------------------------------------------------------------
; qmulh: M_R (16 bits) = upstream's qmulh of M_A and M_B (r_wall65.s):
; hi(sq(a + b)) - hi(sq(|a - b|)), sq(n) = floor(n^2 / 4), from the high
; words only: the high word of a * b, plus 1 when the dropped borrow says
; so. Since sq(a + b) = a b + sq(d), d = |a - b|, that is hi(a b) plus
; the carry of lo(a b) + lo(sq(d)); with d = dh:dl, lo(sq(d)) = f(dl) +
; ((dh dl) mod 512) << 7 + (dh & 1) << 14, modulo 65536.
; Changes A, X, Y, the slots, MT+0 - MT+3, MT+8, MT+9.
; ---------------------------------------------------------------------------
qmulh:
        jsr umul16              ; M_R = a * b (M_A, M_B kept)
        sec                     ; d = |a - b|: X low, A high
        lda M_A
        sbc M_B
        tax
        lda M_A+1
        sbc M_B+1
        bcs @pos
        eor #$FF                ; negate A:X
        tay
        txa
        eor #$FF
        clc
        adc #1
        tax
        tya
        adc #0
@pos:   sta MT+2                ; dh
        stx MT+3                ; dl
        lda SQL,x               ; L = f(dl)
        sta MT+0
        lda SQH,x
        sta MT+1
        txa                     ; p = dh * dl
        SETW0
        ldy MT+2
        sec
        lda (PSL0),y
        sbc (PNL0),y
        tax
        lda (PSH0),y
        sbc (PNH0),y
        lsr a                   ; (p mod 512) << 7: the high byte is p's
        txa                     ;   bits 1-8, the low byte bit 0 at bit 7
        ror a
        tay
        lda #0
        ror a
        clc
        adc MT+0
        sta MT+0
        tya
        adc MT+1
        sta MT+1
        lda MT+2                ; + (dh & 1) << 14
        lsr a
        bcc @even
        lda MT+1
        adc #$3F                ; (carry set: + $40)
        sta MT+1
@even:  clc                     ; the carry of lo(a b) + L
        lda M_R
        adc MT+0
        lda M_R+1
        adc MT+1
        lda M_R+2
        adc #0
        sta M_R
        lda M_R+3
        adc #0
        sta M_R+1
        rts

; ---------------------------------------------------------------------------
; fixmul: M_R = FixedMul(M_A, M_B) = floor(a * b / 65536) modulo 2^32, a
; and b signed (upstream's FixedMul, FixedMul3232; exact). In magnitudes:
; P = |a| |b| from the 16 x 16 products of the halves that are not 0
; (bytes 0-5 of P only), then P >> 16, or -ceil(P / 65536) for a negative
; product. Changes M_A and M_B (to |a|, |b|), A, X, Y, the slots,
; MT+0 - MT+6, MT+8, MT+9.
; ---------------------------------------------------------------------------
; fixmul: M_R = FixedMul(M_A, M_B) = floor(a * b / 65536) modulo 2^32, a
; and b signed (upstream's FixedMul, FixedMul3232; exact). In magnitudes:
; P = |a| |b| from the 16 x 16 products of the halves that are not 0
; (bytes 0-5 of P only; b's halves in the slots, one setup each), then
; P >> 16, or -ceil(P / 65536) for a negative product. fixmul3216: b is
; the low word of M_B, unsigned (FixedMul3216). Changes M_A and M_B (to
; |a|, |b|), A, X, Y, the slots, MT+0 - MT+6, MT+8, MT+9.
; ---------------------------------------------------------------------------
fixmul3216:
        stz M_B+2
        stz M_B+3
fixmul:
        lda M_A+3
        eor M_B+3
        sta MT+6                ; the sign of the product
        bit M_B+3
        bpl :+
        NEG32 M_B
:       bit M_A+3
        bpl :+
        NEG32 M_A
:       stz MT+0                ; P = 0
        stz MT+1
        stz MT+2
        stz MT+3
        stz MT+4
        stz MT+5
        lda M_B                 ; BL
        ora M_B+1
        beq @bh
        lda M_B
        SETW0
        lda M_B+1
        SETW1
        ldy M_A                 ; BL * AL, at byte 0
        ldx M_A+1
        bne :+
        cpy #0
        beq @blah
:       jsr mulw
        lda M_R
        sta MT+0
        lda M_R+1
        sta MT+1
        lda M_R+2
        sta MT+2
        lda M_R+3
        sta MT+3
@blah:  ldy M_A+2               ; BL * AH, at byte 2
        ldx M_A+3
        bne :+
        cpy #0
        beq @bh
:       jsr mulw
        jsr fm_add2
@bh:    lda M_B+2               ; BH
        ora M_B+3
        beq @sign
        lda M_B+2
        SETW0
        lda M_B+3
        SETW1
        ldy M_A                 ; BH * AL, at byte 2
        ldx M_A+1
        bne :+
        cpy #0
        beq @bhah
:       jsr mulw
        jsr fm_add2
@bhah:  ldy M_A+2               ; BH * AH: its low word at byte 4
        ldx M_A+3
        bne :+
        cpy #0
        beq @sign
:       jsr mulw
        clc
        lda M_R
        adc MT+4
        sta MT+4
        lda M_R+1
        adc MT+5
        sta MT+5
@sign:  bit MT+6
        bmi @neg
        lda MT+2
        sta M_R
        lda MT+3
        sta M_R+1
        lda MT+4
        sta M_R+2
        lda MT+5
        sta M_R+3
        rts
@neg:   lda MT+0                ; -ceil(P / 65536) = ~(P >> 16) + (P's low
        ora MT+1                ;   word is 0)
        beq :+
        clc
        bra @not
:       sec
@not:   lda MT+2
        eor #$FF
        adc #0
        sta M_R
        lda MT+3
        eor #$FF
        adc #0
        sta M_R+1
        lda MT+4
        eor #$FF
        adc #0
        sta M_R+2
        lda MT+5
        eor #$FF
        adc #0
        sta M_R+3
        rts

; MT+2 - MT+5 += M_R
fm_add2:
        clc
        lda M_R
        adc MT+2
        sta MT+2
        lda M_R+1
        adc MT+3
        sta MT+3
        lda M_R+2
        adc MT+4
        sta MT+4
        lda M_R+3
        adc MT+5
        sta MT+5
        rts

; ---------------------------------------------------------------------------
; fixmulang: M_R = FixedMulAngle(M_A, M_B) = FixedMul3216(a, b & $FFFF),
; minus a when b < 0 (p_mobj65.s). Changes what fixmul changes.
; ---------------------------------------------------------------------------
fixmulang:
        lda M_B+3               ; b's sign, then a
        pha
        lda M_A+3
        pha
        lda M_A+2
        pha
        lda M_A+1
        pha
        lda M_A
        pha
        jsr fixmul3216
        pla
        sta MT+0
        pla
        sta MT+1
        pla
        sta MT+2
        pla
        sta MT+3
        pla
        bpl @done
        sec
        lda M_R
        sbc MT+0
        sta M_R
        lda M_R+1
        sbc MT+1
        sta M_R+1
        lda M_R+2
        sbc MT+2
        sta M_R+2
        lda M_R+3
        sbc MT+3
        sta M_R+3
@done:  rts

; ---------------------------------------------------------------------------
; mul32: M_R = M_A * M_B modulo 2^32 (upstream's _Mul32; signs do not
; matter modulo 2^32): AL BL + (AL BH + AH BL) << 16. Changes A, X, Y, the
; slots, MT+0 - MT+3, MT+8, MT+9.
; ---------------------------------------------------------------------------
mul32:
        lda M_A
        SETW0
        lda M_A+1
        SETW1
        ldy M_B
        ldx M_B+1
        jsr mulw                ; AL * BL
        lda M_R
        sta MT+0
        lda M_R+1
        sta MT+1
        lda M_R+2
        sta MT+2
        lda M_R+3
        sta MT+3
        ldy M_B+2
        ldx M_B+3
        bne :+
        cpy #0
        beq @ah
:       jsr mulw                ; AL * BH: its low word at byte 2
        jsr @add
@ah:    lda M_A+2
        ora M_A+3
        beq @done
        lda M_A+2
        SETW0
        lda M_A+3
        SETW1
        ldy M_B
        ldx M_B+1
        jsr mulw                ; AH * BL: its low word at byte 2
        jsr @add
@done:  COPY32 MT, M_R
        rts
@add:   clc
        lda M_R
        adc MT+2
        sta MT+2
        lda M_R+1
        adc MT+3
        sta MT+3
        rts

; ===========================================================================
; The RamWorks table reads: in the card, since they run with RAMRD on
; ===========================================================================
        .segment "MATHFAR"

; ---------------------------------------------------------------------------
; mt_far: read X byte planes (1-4) of RamWorks bank A: the byte at MT_P,
; then at MT_P + Y pages, + 2Y pages ..., into MT_E, MT_E+1 ... One RAMRD
; window; $C073 back to 0 after. Changes A, X, MT_P+1, its own two
; operands.
; ---------------------------------------------------------------------------
mt_far:
        sty mt_far_stride+1
        stx mt_far_count+1
        sta RWBANK
        sta RAMRDON
        ldx #0
mt_far_next:
        lda (MT_P)
        sta MT_E,x
        inx
mt_far_count:
        cpx #0                  ; (the count, patched)
        beq mt_far_done
        lda MT_P+1
        clc
mt_far_stride:
        adc #0                  ; (the stride, patched)
        sta MT_P+1
        bra mt_far_next
mt_far_done:
        sta RAMRDOFF
        stz RWBANK
        rts

; ---------------------------------------------------------------------------
; mt_recipe: MT_E (16 bits) = RECIP_TABLE at MT_P: its low byte from bank
; MT_RLO, its high byte from MT_RHI, one window. Changes A.
; ---------------------------------------------------------------------------
mt_recipe:
        lda #MT_RLO
        sta RWBANK
        sta RAMRDON
        lda (MT_P)
        sta MT_E
        lda #MT_RHI
        sta RWBANK
        lda (MT_P)
        sta MT_E+1
        sta RAMRDOFF
        stz RWBANK
        rts

; ===========================================================================
; The rest: a code window of main memory
; ===========================================================================
        .segment "MATHW"

; ---------------------------------------------------------------------------
; The divides, the port's own (MATH.md): C semantics, the quotient
; truncated toward zero, the remainder with the dividend's sign; by zero,
; the quotient saturates to the largest value of the dividend's sign (all
; ones unsigned) and the remainder is the dividend; INT_MIN / -1 wraps to
; INT_MIN, remainder 0. Restoring shift-and-subtract, whole leading zero
; bytes of the dividend skipped.
; ---------------------------------------------------------------------------

; udiv16: M_R = M_A / M_B, M_T = M_A % M_B, unsigned 16. Changes A, X, Y.
udiv16:
        lda M_B
        ora M_B+1
        bne ud16go
        lda #$FF
        sta M_R
        sta M_R+1
        lda M_A
        sta M_T
        lda M_A+1
        sta M_T+1
        rts
ud16go:                         ; (M_B != 0)
        stz M_T
        stz M_T+1
        lda M_A
        sta M_R
        ldx #16
        lda M_A+1
        sta M_R+1
        bne @loop
        lda M_R                 ; a leading zero byte: 8 steps fewer
        sta M_R+1
        stz M_R
        ldx #8
@loop:  asl M_R                 ; the dividend out of M_R, the quotient in
        rol M_R+1
        rol M_T
        rol M_T+1
        bcs @force              ; a 17-bit remainder: above the divisor
        lda M_T
        sec
        sbc M_B
        tay
        lda M_T+1
        sbc M_B+1
        bcc @next
@take:  sta M_T+1
        sty M_T
        inc M_R
@next:  dex
        bne @loop
        rts
@force: lda M_T                 ; (carry set)
        sbc M_B
        tay
        lda M_T+1
        sbc M_B+1
        bra @take

; sdiv16: M_R = M_A / M_B, M_T = M_A % M_B, signed 16 (for upstream's
; _Div16 and _Mod16). Changes M_A, M_B (magnitudes), A, X, Y, MT+4, MT+5.
sdiv16:
        lda M_B
        ora M_B+1
        bne @nz
        lda M_A                 ; by zero: the remainder is the dividend,
        sta M_T                 ;   the quotient $7FFF, or $8000 for a < 0
        lda M_A+1
        sta M_T+1
        ldx #$FF
        ldy #$7F
        bit M_A+1
        bpl :+
        ldx #$00
        ldy #$80
:       stx M_R
        sty M_R+1
        rts
@nz:    lda M_A+1
        sta MT+4                ; the remainder's sign
        eor M_B+1
        sta MT+5                ; the quotient's sign
        bit M_A+1
        bpl :+
        NEG16 M_A
:       bit M_B+1
        bpl :+
        NEG16 M_B
:       jsr ud16go
        bit MT+5
        bpl :+
        NEG16 M_R
:       bit MT+4
        bpl :+
        NEG16 M_T
:       rts

; udiv32: M_R = M_A / M_B, M_T = M_A % M_B, unsigned 32. Changes A, X, Y,
; MT+4, MT+5.
udiv32:
        lda M_B
        ora M_B+1
        ora M_B+2
        ora M_B+3
        bne ud32go
        lda #$FF
        sta M_R
        sta M_R+1
        sta M_R+2
        sta M_R+3
        COPY32 M_A, M_T
        rts
ud32go:                         ; (M_B != 0)
        stz M_T
        stz M_T+1
        stz M_T+2
        stz M_T+3
        COPY32 M_A, M_R
        ldx #32
@skip:  lda M_R+3               ; whole leading zero bytes: 8 steps each
        bne @loop
        lda M_R+2
        sta M_R+3
        lda M_R+1
        sta M_R+2
        lda M_R
        sta M_R+1
        stz M_R
        txa
        sec
        sbc #8
        tax
        bne @skip
        rts                     ; a dividend of 0
@loop:  asl M_R
        rol M_R+1
        rol M_R+2
        rol M_R+3
        rol M_T
        rol M_T+1
        rol M_T+2
        rol M_T+3
        bcs @force
        lda M_T
        sec
        sbc M_B
        sta MT+4
        lda M_T+1
        sbc M_B+1
        sta MT+5
        lda M_T+2
        sbc M_B+2
        tay
        lda M_T+3
        sbc M_B+3
        bcc @next
@take:  sta M_T+3
        sty M_T+2
        lda MT+5
        sta M_T+1
        lda MT+4
        sta M_T
        inc M_R
@next:  dex
        bne @loop
        rts
@force: lda M_T                 ; (carry set)
        sbc M_B
        sta MT+4
        lda M_T+1
        sbc M_B+1
        sta MT+5
        lda M_T+2
        sbc M_B+2
        tay
        lda M_T+3
        sbc M_B+3
        bra @take

; sdiv32: M_R = M_A / M_B, M_T = M_A % M_B, signed 32 (for upstream's
; _Div32). Changes M_A, M_B (magnitudes), A, X, Y, MT+4 - MT+7.
sdiv32:
        lda M_B
        ora M_B+1
        ora M_B+2
        ora M_B+3
        bne @nz
        COPY32 M_A, M_T         ; by zero: the remainder is the dividend,
        lda #$FF                ;   the quotient $7FFFFFFF, or $80000000
        ldy #$7F                ;   for a < 0
        bit M_A+3
        bpl :+
        lda #$00
        ldy #$80
:       sta M_R
        sta M_R+1
        sta M_R+2
        sty M_R+3
        rts
@nz:    lda M_A+3
        sta MT+6                ; the remainder's sign
        eor M_B+3
        sta MT+7                ; the quotient's sign
        bit M_A+3
        bpl :+
        NEG32 M_A
:       bit M_B+3
        bpl :+
        NEG32 M_B
:       jsr ud32go
        bit MT+7
        bpl :+
        NEG32 M_R
:       bit MT+6
        bpl :+
        NEG32 M_T
:       rts

; ---------------------------------------------------------------------------
; recip: M_R = FixedReciprocal(M_A), M_A unsigned (m_recip65.s): 0 gives
; $FFFFFFFF; else v shifted left by s until bit 31 is set, M its top 16
; bits, and RECIP_TABLE[M - 32768] = floor((2^31 - 1) / M) shifted by
; s - 15: right, 16 bits, for v >= $10000; left, 32 bits, below.
; recipsmall: the same of the low word of M_A (FixedReciprocalSmall);
; recipbig: M_A >= $10000 (FixedReciprocalBig), the same code.
; Changes A, X, Y, MT+0 - MT+4, MT_E, MT_P.
; ---------------------------------------------------------------------------
recipsmall:
        stz M_A+2
        stz M_A+3
recipbig:
recip:
        lda M_A
        ora M_A+1
        ora M_A+2
        ora M_A+3
        bne @nz
        lda #$FF
        sta M_R
        sta M_R+1
        sta M_R+2
        sta M_R+3
        rts
@nz:    COPY32 M_A, MT          ; V, shifted left by s (X) until bit 31
        ldx #0
@bytes: lda MT+3
        bne @bits
        lda MT+2
        sta MT+3
        lda MT+1
        sta MT+2
        lda MT
        sta MT+1
        stz MT
        txa
        clc
        adc #8
        tax
        bra @bytes
@bits:  bmi @norm
@bit:   inx
        asl MT
        rol MT+1
        rol MT+2
        rol MT+3
        bpl @bit
@norm:  stx MT+4                ; s
        lda MT+2                ; RECIP_TABLE[M & $7FFF]
        sta MT_P
        lda MT+3
        and #$7F
        clc
        adc #>RECIPT
        sta MT_P+1
        jsr mt_recipe
        lda MT_E
        sta M_R
        lda MT_E+1
        sta M_R+1
        stz M_R+2
        stz M_R+3
        lda M_A+2
        ora M_A+3
        beq @left
        lda #15                 ; v >= $10000: >> (15 - s)
        sec
        sbc MT+4
        tax
        beq @done
@right: lsr M_R+1
        ror M_R
        dex
        bne @right
@done:  rts
@left:  lda MT+4                ; v < $10000: << (s - 15), 1 to 16
        sec
        sbc #15
        tax
        cpx #8
        bcc @lbit
        lda M_R+1               ; a whole byte (the upper bytes are 0)
        sta M_R+2
        lda M_R
        sta M_R+1
        stz M_R
        txa
        sec
        sbc #8
        tax
        beq @done
@lbit:  asl M_R
        rol M_R+1
        rol M_R+2
        rol M_R+3
        dex
        bne @lbit
        rts

; ---------------------------------------------------------------------------
; approxdiv: M_R = FixedApproxDiv(M_A, M_B) (r_iigs65.s approxDiv): a b
; whose high word is 0, or a negative b (a signed compare in the C), gives
; FixedMul(a, FixedReciprocalSmall(b & $FFFF)); else FixedMul3216(a,
; FixedReciprocalBig(b)). Changes what recip and fixmul change.
; ---------------------------------------------------------------------------
approxdiv:
        lda M_A+3               ; keep a
        pha
        lda M_A+2
        pha
        lda M_A+1
        pha
        lda M_A
        pha
        lda M_B+3
        bmi @small
        ora M_B+2
        beq @small
        COPY32 M_B, M_A         ; FixedReciprocalBig(b), 16 bits
        jsr recip
        lda M_R
        sta M_B
        lda M_R+1
        sta M_B+1
        jsr @a
        jmp fixmul3216
@small: lda M_B                 ; FixedReciprocalSmall(b & $FFFF)
        sta M_A
        lda M_B+1
        sta M_A+1
        jsr recipsmall
        COPY32 M_R, M_B
        jsr @a
        jmp fixmul
@a:     ply                     ; a back into M_A, under the return address
        plx
        pla
        sta M_A
        pla
        sta M_A+1
        pla
        sta M_A+2
        pla
        sta M_A+3
        phx
        phy
        rts

.ifndef RENDER
; ---------------------------------------------------------------------------
; The octants of the angle routines: k = 4 (x < 0) + 2 (y < 0) + (x <= y),
; the angle C + T or C - T with T the table's angle of the slope. For
; R_PointToAngle3 C is 32 bits: its high byte OCTC, and its other bytes 0
; for + and $FF for - (so C - T needs no borrow below the top byte), but
; k = 2: 0 - T. R_PointToAngle16 uses the high word.
; ---------------------------------------------------------------------------
.endif

pta_tab:
OCTC:   .byte $00, $3F, $00, $C0, $7F, $40, $80, $BF
OCTMINUS:
        .byte $00, $FF, $FF, $00, $FF, $00, $00, $FF

.ifndef RENDER
        .include "mathgame.inc"   ; pta_oct, pta3, finesine, finecosine,
.endif                          ;   aproxdist, cosexc (the game's:
                                ;   GAMEMATH below)

; ---------------------------------------------------------------------------
; pta16: M_R (16 bits) = R_PointToAngle16 of (M_A, M_A+2) from (M_B,
; M_B+2): x, y, viewx, viewy, whole units (r_iigs65.s R_PointToAngle16 and
; pointAngle). dx = x - viewx, dy = y - viewy; (0, 0) gives 0; else the
; octant (signed 16-bit compares, as upstream's pointOld; inside -16384 to
; 16384 they agree with its fast path) and the high word of
; tantoangle[SlopeDiv16(num, den)]: 2048 for den = 0 or num = den,
; num * 2048 / den below (11 division steps), above the (uint16_t)
; quotient at most 2048 (udiv32) of upstream's dividend, whose high word
; is num >> 13 (slopeOld; the C's num << 11 would have num >> 5). Changes M_A, M_B, M_T, A, X, Y, MT+0 - MT+9,
; MT_P.
; ---------------------------------------------------------------------------
pta16:
        sec                     ; dx, dy
        lda M_A
        sbc M_B
        sta M_A
        lda M_A+1
        sbc M_B+1
        sta M_A+1
        sec
        lda M_A+2
        sbc M_B+2
        sta M_B
        lda M_A+3
        sbc M_B+3
        sta M_B+1
        ora M_B
        ora M_A
        ora M_A+1
        bne @go
        stz M_R
        stz M_R+1
        rts
@go:    ldx #0                  ; the octant, 16-bit as upstream: -(-32768)
        bit M_A+1               ;   stays $8000, negative in the compare
        bpl :+
        NEG16 M_A
        ldx #4
:       bit M_B+1
        bpl :+
        NEG16 M_B
        inx
        inx
:       lda M_B                 ; y < x (signed 16)?
        cmp M_A
        lda M_B+1
        sbc M_A+1
        bvc :+
        eor #$80
:       bmi :+
        inx                     ; x <= y: num = x, den = y
        lda M_A
        ldy M_B
        sta M_B
        sty M_A
        lda M_A+1
        ldy M_B+1
        sta M_B+1
        sty M_A+1
:       phx                     ; k
        lda M_A                 ; SlopeDiv16(n = M_B, d = M_A)
        ora M_A+1
        bne :+
        jmp @max                ; d = 0
:       lda M_B
        cmp M_A
        bne @ne
        lda M_B+1
        cmp M_A+1
        bne @ne
        jmp @max                ; n = d
@ne:    lda M_B                 ; n < d: 11 steps
        cmp M_A
        lda M_B+1
        sbc M_A+1
        bcs @over
        lda M_B
        sta MT
        lda M_B+1
        sta MT+1
        stz MT+2
        stz MT+3
        ldx #11
@step:  asl MT
        rol MT+1
        bcs @sub
        lda MT
        cmp M_A
        lda MT+1
        sbc M_A+1
        bcc @bit
@sub:   lda MT                  ; (carry set)
        sbc M_A
        sta MT
        lda MT+1
        sbc M_A+1
        sta MT+1
        sec
@bit:   rol MT+2
        rol MT+3
        dex
        bne @step
        ldx MT+2
        ldy MT+3
        bra @q
@over:  stz MT                  ; n > d: N / d, 32 bits, where N is
        lda M_B                 ;   upstream's n << 11: its low word
        and #$1F                ;   (n & $1F) << 11, but its high word
        asl a                   ;   n >> 13, not n >> 5 (slopeOld, 80$)
        asl a
        asl a
        sta MT+1
        lda M_B+1
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        sta MT+2
        stz MT+3
        lda M_A
        sta M_B
        lda M_A+1
        sta M_B+1
        stz M_B+2
        stz M_B+3
        COPY32 MT, M_A
        jsr udiv32
        ldx M_R                 ; (uint16_t) q, at most 2048
        ldy M_R+1
        cpy #>2049
        bcc @q
        bne @max
        cpx #<2049
        bcc @q
@max:   ldx #<2048
        ldy #>2048
.ifdef RENDER
@q:     cpy #>2048              ; the high word of tantoangle[q]: 2048,
        bne :+                  ;   ANG45 (checked by rtables.py), else
        stz MT_E                ;   the aux card's planes 2 and 3
        lda #>$2000
        sta MT_E+1
        bra :++
:       tya
        jsr ax_tanto
        sta MT_E
        sty MT_E+1
:       plx
.else
@q:     stx MT_P                ; the high word of tantoangle[q]
        tya
        clc
        adc #>TANTO0 + 2 * TANTO_STRIDE
        sta MT_P+1
        lda #MT_TBANK
        ldx #2
        ldy #TANTO_STRIDE
        jsr mt_far
        plx
.endif
        lda OCTMINUS,x
        bne @minus
        lda MT_E                ; C + T
        sta M_R
        lda MT_E+1
        clc
        adc OCTC,x
        sta M_R+1
        rts
@minus: lda OCTC,x              ; C - T, C = OCTC:$FF (0 for k = 2)
        cpx #2
        bne :+
        lda #0
        sec
        sbc MT_E
        sta M_R
        lda #0
        sbc MT_E+1
        sta M_R+1
        rts
:       sec
        lda #$FF
        sbc MT_E
        sta M_R
        lda OCTC,x
        sbc MT_E+1
        sta M_R+1
        rts

; ---------------------------------------------------------------------------
; sineapprox: M_R = finesineapprox(M_A), M_A unsigned 16 (tables65.s): the
; quarter table finesineTable_part_1 at c or 4095 - c; negated for x >=
; 4096 (with c = x & 4095). cosineapprox: sineapprox((x + 2048) & 8191).
; Change A, X, Y, M_A, MT_E, MT_P.
; ---------------------------------------------------------------------------
cosineapprox:
        lda M_A+1
        clc
        adc #>2048
        and #$1F
        sta M_A+1
sineapprox:
        lda M_A+1
        cmp #$10
        bcs @neg
        jsr @quarter
        stz M_R+2
        stz M_R+3
        rts
@neg:   and #$0F
        sta M_A+1
        jsr @quarter
        sec
        lda #0
        sbc M_R
        sta M_R
        lda #0
        sbc M_R+1
        sta M_R+1
        lda #0
        sbc #0
        sta M_R+2
        sta M_R+3
        rts
@quarter:                       ; M_R (16 bits) = the quarter table at c
        lda M_A+1               ;   < 2048 ? c : 4095 - c, c = M_A < 4096
        cmp #$08
        bcc :+
        eor #$0F
        sta M_A+1
        lda M_A
        eor #$FF
        sta M_A
:       lda M_A
        sta MT_P
        lda M_A+1
        clc
        adc #>QUARTLO
        sta MT_P+1
        lda #MT_TBANK
        ldx #2
        ldy #>(QUARTHI - QUARTLO)
        jsr mt_far
        lda MT_E
        sta M_R
        lda MT_E+1
        sta M_R+1
        rts

.ifndef RENDER
; ---------------------------------------------------------------------------
; prandom: A = P_Random(): rndtable[++index], the index a byte
; (m_random65.s); mrandom: M_Random, its own index; mclearrandom: both
; indexes 0. Change A, X.
; ---------------------------------------------------------------------------
prandom:
        ldx MT_PRND
        inx
        stx MT_PRND
        lda rndtable,x
        rts
mrandom:
        ldx MT_MRND
        inx
        stx MT_MRND
        lda rndtable,x
        rts
mclearrandom:
        stz MT_PRND
        stz MT_MRND
        rts

        .segment "MATHRND"
; P_Random's table (Doom's), from the reference's RAM
rndtable:
        .incbin "rndtable.bin"
.endif
.endif                          ; (GAMEMATH)
