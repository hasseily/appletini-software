; Doom for the Appletini -- fixed-point arithmetic and the game's far tables
; (docs/DESIGN.md sections 5 and 9). GAME space.
;
; For C (cc65 __fastcall__):
;   fixed_t FixedMul(fixed_t a, fixed_t b)   vanilla's ((int64) a * b) >> 16
;   fixed_t FixedDiv(fixed_t a, fixed_t b)   vanilla's, MAXINT/MININT on overflow
;   fixed_t int2fix(int16_t v)               v << 16
;   fixed_t fine_sine(uint16_t a), fine_cosine(uint16_t a)
;                                            vanilla finesine/finecosine[a & 8191]
;   angle_t tanto_angle(uint16_t s)          vanilla tantoangle[s] >> 16, s <= 2048
;   void game_farinit(void)                  once at boot (below)
; For the assembly (operands in absolute variables):
;   fx_mul      fxr = FixedMul(fxa, fxb)     (also in A/X/sreg)
;   fx_div      fxr = FixedDiv(fxa, fxb)     (also in A/X/sreg)
;   fx_sine     fxr = fine_sine(A/X)         (also in A/X/sreg)
;   fx_cosine   fxr = fine_cosine(A/X)
;   fxa and fxb are left as they were; the game's zero page (gmo, gth, gli,
;   gpt) is kept; cc65's ptr1/ptr2, tmp1/tmp2 and sreg are not.
;
; FixedMul multiplies the magnitudes by byte pairs (x*y = sqr(x+y) -
; sqr(|x-y|), sqr(n) = n*n/4 from a 1 KB table), skipping the pairs with a
; zero byte (most operands are small: a momentum, a sine, a speed) and
; those that only reach bits 48 and up; a negative result is floored as
; vanilla's 64-bit shift floors it. FixedDiv is a restoring division of
; the magnitudes (|a| << 16 by |b|) that skips the dividend's leading zero
; bytes, truncated toward zero as vanilla's 64-bit division.
;
; The sine and arctangent tables are far (4 KB each, read a few times a
; tic): each read is one far_read of 2 bytes into the kernel's scratch
; zero page, about 450 cycles in GAME space. game_farinit, once at boot,
; builds the multiply table and copies the GFAR segment (gtables.s) into
; the game's far bank, the machine's last RamWorks bank (game_far_bank);
; that bank must be above the converter's banks and the one after them
; (the renderer's), else kernel_crash CRASH_BANKS.

.include "gmacros.inc"
.include "gwork.inc"
.globalzp far_src, far_dst, far_ptr, far_len, ktmp
.import kjt_far_read, kjt_far_write, kjt_crash
.import incsp4
.import _kbanks
.import gtables_start, gtables_end
.import __BSS_RUN__, __BSS_SIZE__, __GFAR_RUN__, __GFAR_SIZE__
.import __STACKSTART__, __STACKSIZE__

.export _FixedMul, _FixedDiv, _int2fix, _fine_sine, _fine_cosine, _tanto_angle
.export _game_farinit, _game_far_bank, _arena_bounds
.export fx_mul, fx_div, fx_sine, fx_cosine, fxa, fxb, fxr
.export sqrlo, sqrhi

GT_ADDR     = $0200                 ; the tables in the far bank
GT_SINE     = GT_ADDR
GT_TAN      = GT_ADDR + 4096
CRASH_BANKS = $23

; the game's zero page
.segment "GZP": zeropage
gmo:    .res 2
gth:    .res 2
gli:    .res 2
gpt:    .res 2
.exportzp gmo, gth, gli, gpt

.segment "RODATA"
; the level arena (p_setup.c): the end of the C BSS up to the C stack, and
; the GFAR segment's bytes once game_farinit has copied them away
_arena_bounds:
        .word   __BSS_RUN__ + __BSS_SIZE__, __STACKSTART__ - __STACKSIZE__
        .word   __GFAR_RUN__, __GFAR_RUN__ + __GFAR_SIZE__

; the operands and the result of fx_mul / fx_div are slots of W (gwork.s)
fxa     = W + W_FA
fxb     = W + W_FB
fxr     = W + W_FR

.segment "BSS"
sqrlo:  .res 512
sqrhi:  .res 512
_game_far_bank: .res 1
fa:     .res 4                      ; |a|
fb:     .res 4                      ; |b|
acc:    .res 8                      ; the product; the division's dividend/quotient
fsign:  .res 1
fdrem:  .res 5
m_a:    .res 1
m_i:    .res 1
m_j:    .res 1
m_k:    .res 1
m_lo:   .res 1

.segment "CODE"

; fixed_t __fastcall__ int2fix(int16_t v)
_int2fix:
        sta     sreg
        stx     sreg+1
        lda     #0
        tax
        rts

; fa/fb = |fxa|/|fxb|, fsign bit 7 = the sign of the result
magnitudes:
        lda     fxa+3
        eor     fxb+3
        sta     fsign
        ldx     #3
@c:     lda     fxa,x
        sta     fa,x
        lda     fxb,x
        sta     fb,x
        dex
        bpl     @c
        lda     fa+3
        bpl     :+
        ldx     #fa-fa
        jsr     negate
:       lda     fb+3
        bpl     :+
        ldx     #fb-fa
        jsr     negate
:       rts

; negate the 4 bytes at fa+X
negate: sec
        lda     #0
        sbc     fa,x
        sta     fa,x
        lda     #0
        sbc     fa+1,x
        sta     fa+1,x
        lda     #0
        sbc     fa+2,x
        sta     fa+2,x
        lda     #0
        sbc     fa+3,x
        sta     fa+3,x
        rts

; the C arguments: a (4 bytes on the C stack, popped) -> fxa, b (A/X/sreg) -> fxb
c_args: sta     fxb
        stx     fxb+1
        lda     sreg
        sta     fxb+2
        lda     sreg+1
        sta     fxb+3
        ldy     #3
@a:     lda     (sp),y
        sta     fxa,y
        dey
        bpl     @a
        jmp     incsp4

; ---- FixedMul -------------------------------------------------------------
_FixedMul:
        jsr     c_args
fx_mul:
        jsr     magnitudes
        stz     acc
        stz     acc+1
        stz     acc+2
        stz     acc+3
        stz     acc+4
        stz     acc+5
        stz     acc+6
        stz     acc+7
        ; for each byte i of |a| (non-zero), each byte j of |b| (non-zero)
        ; with i + j <= 5: acc[i+j..] += a_i * b_j
        ldx     #0
@iloop: lda     fa,x
        bne     :+
        jmp     @inext
:       sta     m_a
        clc
        adc     #<sqrlo
        sta     ptr1
        lda     #>sqrlo
        adc     #0
        sta     ptr1+1
        lda     m_a
        clc
        adc     #<sqrhi
        sta     ptr2
        lda     #>sqrhi
        adc     #0
        sta     ptr2+1
        stx     m_i
        ldy     #0
@jloop: tya
        clc
        adc     m_i
        cmp     #6
        bcs     @inext_x
        sta     m_k
        lda     fb,y
        beq     @jnext
        ; |b_j - a_i| -> X
        sec
        sbc     m_a
        bcs     :+
        eor     #$FF
        adc     #1
:       tax
        sty     m_j
        lda     fb,y
        tay
        lda     (ptr1),y                ; sqr(a+b) - sqr(|a-b|)
        sec
        sbc     sqrlo,x
        sta     m_lo
        lda     (ptr2),y
        sbc     sqrhi,x
        ldx     m_k
        tay                             ; the product's high byte
        lda     m_lo
        clc
        adc     acc,x
        sta     acc,x
        tya
        adc     acc+1,x
        sta     acc+1,x
        bcc     @noc
@ripple:
        inc     acc+2,x
        bne     @noc
        inx
        cpx     #5
        bcc     @ripple
@noc:   ldy     m_j
@jnext: iny
        cpy     #4
        bne     @jloop
@inext_x:
        ldx     m_i
@inext: inx
        cpx     #4
        beq     :+
        jmp     @iloop
:       ; result = acc[2..5]; a negative result is floor(-P / 65536) =
        ; -((P + $FFFF) >> 16)
        lda     fsign
        bpl     @pos
        lda     acc
        ora     acc+1
        beq     @exact
        inc     acc+2
        bne     @exact
        inc     acc+3
        bne     @exact
        inc     acc+4
        bne     @exact
        inc     acc+5
@exact: ldx     #acc+2-fa
        jsr     negate
@pos:   mov32   fxr, acc+2
        ret32   fxr
        rts

; ---- FixedDiv ----------------------------------------------------------------
_FixedDiv:
        jsr     c_args
fx_div:
        jsr     magnitudes
        ; (|a| >> 14) >= |b| ?  compare |a| with |b| << 14 (46 bits):
        ; t = (|b| << 16) >> 2 in acc
        stz     acc
        stz     acc+1
        lda     fb
        sta     acc+2
        lda     fb+1
        sta     acc+3
        lda     fb+2
        sta     acc+4
        lda     fb+3
        sta     acc+5
        ldx     #2
@sh:    lsr     acc+5
        ror     acc+4
        ror     acc+3
        ror     acc+2
        ror     acc+1
        ror     acc
        dex
        bne     @sh
        lda     acc+5
        ora     acc+4
        bne     @ok                     ; t >= 2^32 > |a|
        lda     fa+3
        cmp     acc+3
        bne     @cmp
        lda     fa+2
        cmp     acc+2
        bne     @cmp
        lda     fa+1
        cmp     acc+1
        bne     @cmp
        lda     fa
        cmp     acc
@cmp:   bcc     @ok
        ; overflow: MAXINT or MININT
        lda     fsign
        bmi     @min
        ldi32   fxr, $7FFFFFFF
        ret32   fxr
        rts
@min:   ldi32   fxr, $80000000
        ret32   fxr
        rts
@ok:    stz     fdrem
        stz     fdrem+1
        stz     fdrem+2
        stz     fdrem+3
        stz     fdrem+4
        stz     acc
        stz     acc+1
        lda     fa
        sta     acc+2
        lda     fa+1
        sta     acc+3
        lda     fa+2
        sta     acc+4
        lda     fa+3
        sta     acc+5
        lda     #48
        sta     m_k
        ; leading zero bytes of the dividend: 8 steps each with nothing to
        ; subtract (the remainder stays 0 and |b| > 0)
@skip:  lda     acc+5
        bne     @loop
        lda     m_k
        cmp     #9
        bcc     @loop
        sbc     #8
        sta     m_k
        lda     acc+4
        sta     acc+5
        lda     acc+3
        sta     acc+4
        lda     acc+2
        sta     acc+3
        lda     acc+1
        sta     acc+2
        lda     acc
        sta     acc+1
        stz     acc
        bra     @skip
@loop:  asl     acc
        rol     acc+1
        rol     acc+2
        rol     acc+3
        rol     acc+4
        rol     acc+5
        rol     fdrem
        rol     fdrem+1
        rol     fdrem+2
        rol     fdrem+3
        rol     fdrem+4
        sec
        lda     fdrem
        sbc     fb
        sta     m_lo
        lda     fdrem+1
        sbc     fb+1
        sta     m_a
        lda     fdrem+2
        sbc     fb+2
        sta     m_i
        lda     fdrem+3
        sbc     fb+3
        tay
        lda     fdrem+4
        sbc     #0
        bcc     @next
        sta     fdrem+4
        sty     fdrem+3
        lda     m_i
        sta     fdrem+2
        lda     m_a
        sta     fdrem+1
        lda     m_lo
        sta     fdrem
        inc     acc                     ; the quotient bit
@next:  dec     m_k
        bne     @loop
        lda     fsign
        bpl     :+
        ldx     #acc-fa
        jsr     negate
:       mov32   fxr, acc
        ret32   fxr
        rts

; ---- the far tables ------------------------------------------------------------
; fine_sine(a): h = a & 4095; v = sine[h < 2048 ? h : 4095 - h]; negative
; when a & 4096.
_fine_cosine:
fx_cosine:
        clc
        adc     #<2048
        pha
        txa
        adc     #>2048
        tax
        pla
_fine_sine:
fx_sine:
        sta     m_lo
        txa
        and     #$1F
        sta     fsign                   ; bit 4: the second half turn
        and     #$0F
        tax                             ; X:m_lo = a & 4095
        cpx     #$08
        bcc     @first
        lda     #<4095                  ; 4095 - h
        sec
        sbc     m_lo
        sta     m_lo
        txa
        eor     #$FF
        and     #$0F
        tax
@first: lda     m_lo                    ; far_src = GT_SINE + 2 * index
        asl     a
        sta     far_src
        txa
        rol     a
        tax
        lda     far_src
        clc
        adc     #<GT_SINE
        sta     far_src
        txa
        adc     #>GT_SINE
        sta     far_src+1
        jsr     read2
        lda     ktmp
        sta     fxr
        lda     ktmp+1
        sta     fxr+1
        stz     fxr+2
        stz     fxr+3
        lda     fsign
        and     #$10
        beq     :+
        neg32   fxr, fxr                ; (the table has no zero)
:       ret32   fxr
        rts

; tanto_angle(slope): tantoangle16[slope], slope 0..2048
_tanto_angle:
        asl     a
        sta     far_src
        txa
        rol     a
        tax
        lda     far_src
        clc
        adc     #<GT_TAN
        sta     far_src
        txa
        adc     #>GT_TAN
        sta     far_src+1
        jsr     read2
        lda     ktmp
        ldx     ktmp+1
        rts

; 2 bytes from game_far_bank:far_src into ktmp
read2:  lda     _game_far_bank
        sta     far_src+2
        lda     #<ktmp
        sta     far_ptr
        stz     far_ptr+1
        lda     #2
        sta     far_len
        stz     far_len+1
        jmp     kjt_far_read

; ---- game_farinit --------------------------------------------------------------
_game_farinit:
        ; sqr(n) = n*n/4 for n = 0..511: n*n as the running sum of the odd
        ; numbers in 24 bits (m_lo, m_a, m_i), shifted right 2
        stz     m_lo
        stz     m_a
        stz     m_i
        lda     #1                      ; 2n+1 in m_j, m_k
        sta     m_j
        stz     m_k
        lda     #<sqrlo
        sta     ptr1
        lda     #>sqrlo
        sta     ptr1+1
        lda     #<sqrhi
        sta     ptr2
        lda     #>sqrhi
        sta     ptr2+1
        ldx     #2                      ; two pages of n
        ldy     #0
@sq:    lda     m_a
        sta     tmp1
        lda     m_i
        sta     tmp2
        lda     m_lo
        lsr     tmp2
        ror     tmp1
        ror     a
        lsr     tmp2
        ror     tmp1
        ror     a
        sta     (ptr1),y
        lda     tmp1
        sta     (ptr2),y
        clc
        lda     m_lo
        adc     m_j
        sta     m_lo
        lda     m_a
        adc     m_k
        sta     m_a
        lda     m_i
        adc     #0
        sta     m_i
        clc
        lda     m_j
        adc     #2
        sta     m_j
        bcc     :+
        inc     m_k
:       iny
        bne     @sq
        inc     ptr1+1
        inc     ptr2+1
        dex
        bne     @sq
        ; the far bank: the machine's last
        lda     _kbanks
        dec     a
        sta     _game_far_bank
        cmp     #DD_LAST_BANK+2
        bcs     :+
        lda     #CRASH_BANKS
        jmp     kjt_crash
:       sta     far_dst+2
        lda     #<GT_ADDR
        sta     far_dst
        lda     #>GT_ADDR
        sta     far_dst+1
        lda     #<gtables_start
        sta     far_ptr
        lda     #>gtables_start
        sta     far_ptr+1
        lda     #<(gtables_end - gtables_start)
        sta     far_len
        lda     #>(gtables_end - gtables_start)
        sta     far_len+1
        jmp     kjt_far_write
