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

; (only with the converted data: the stand-in data set builds the
; platform's GAME skeleton, src/game/game.c)
.ifdef DD_MAPDIR

.globalzp far_src, far_dst, far_ptr, far_len, ktmp
.import kjt_far_read, kjt_far_write, kjt_crash
.import incsp4
.import _kbanks
.import gtables_start, gtables_end
.import __BSS_RUN__, __BSS_SIZE__, __GFAR_RUN__, __GFAR_SIZE__, __GOVL_RUN__, __GOVL_SIZE__
.import __STACKSTART__, __STACKSIZE__
.ifdef BANKED_GAME
.import __ISCRATCH_START__
.endif

.export _FixedMul, _FixedDiv, _int2fix, _fine_sine, _fine_cosine, _tanto_angle
.export _game_farinit, _game_far_bank, _arena_bounds, _P_LoadOverlay
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
; the GFAR segment's bytes once game_farinit has copied them away; then
; the set-up overlay (GOVL, right after GFAR), whose bytes the actor pool
; takes after each level's set-up
_arena_bounds:
.ifdef BANKED_GAME
        ; The intercept/view scratch occupies the 1152 bytes immediately
        ; below the software stack, outside main's posted video windows.
        .word   __BSS_RUN__ + __BSS_SIZE__, __ISCRATCH_START__
        ; Tables are loaded directly into far memory and setup code remains
        ; in its auxiliary LC bank. The level owns one ordinary main arena.
        .word   0, 0, 0
.else
        .word   __BSS_RUN__ + __BSS_SIZE__, __STACKSTART__ - __STACKSIZE__
        .word   __GFAR_RUN__, __GOVL_RUN__, __GOVL_RUN__ + __GOVL_SIZE__
.assert __GOVL_RUN__ = __GFAR_RUN__ + __GFAR_SIZE__, lderror, "GOVL must follow GFAR"
.endif

; the operands and the result of fx_mul / fx_div are slots of W (gwork.s)
fxa     = W + W_FA
fxb     = W + W_FB
fxr     = W + W_FR

.segment "GOVL"
; (a byte so that the segment, and its __GOVL_*__ symbols, always exist)
        .byte   0

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
; BSET j, skip: the multiplier byte b_j in tmp1 and its square-table
; pointers, or on to skip when it is 0
.macro BSET j, skip
        lda     fb+j
        jeq     skip
        sta     tmp1
        clc
        adc     #<sqrlo
        sta     ptr1
        lda     #>sqrlo
        adc     #0
        sta     ptr1+1
        lda     tmp1
        clc
        adc     #<sqrhi
        sta     ptr2
        lda     #>sqrhi
        adc     #0
        sta     ptr2+1
.endmacro

; PROD i, k: acc[k..] += a_i * b_j (b_j set up by BSET), a_i = 0 skipped
.macro PROD i, k
        .local pos, done
        ldy     fa+i
        beq     done
        tya
        sec
        sbc     tmp1
        bcs     pos
        eor     #$FF
        adc     #1                      ; |a_i - b_j| (the carry was clear)
pos:    tax
        lda     (ptr1),y                ; sqr(a + b) - sqr(|a - b|)
        sec
        sbc     sqrlo,x
        sta     tmp2
        lda     (ptr2),y
        sbc     sqrhi,x
        tay
        clc
        lda     tmp2
        adc     acc+k
        sta     acc+k
        tya
        adc     acc+k+1
        sta     acc+k+1
    .if k + 2 <= 5
        bcc     done
        inc     acc+k+2
      .if k + 3 <= 5
        bne     done
        inc     acc+k+3
        .if k + 4 <= 5
        bne     done
        inc     acc+k+4
          .if k + 5 <= 5
        bne     done
        inc     acc+k+5
          .endif
        .endif
      .endif
    .endif
done:
.endmacro

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
        ; |a| * |b| by bytes, the products a_i * b_j with i + j <= 5 added at
        ; acc + i + j (what lies above bit 47 does not reach the result).
        ; For each non-zero b_j, ptr1/ptr2 = sqrlo/sqrhi + b_j, so that
        ; (ptr1),y with Y = a_i is sqr(a_i + b_j); then each product is
        ; sqr(a + b) - sqr(|a - b|), unrolled (see PROD).
        BSET    0, fm_j1
        PROD    0, 0
        PROD    1, 1
        PROD    2, 2
        PROD    3, 3
fm_j1:    BSET    1, fm_j2
        PROD    0, 1
        PROD    1, 2
        PROD    2, 3
        PROD    3, 4
fm_j2:    BSET    2, fm_j3
        PROD    0, 2
        PROD    1, 3
        PROD    2, 4
        PROD    3, 5
fm_j3:    BSET    3, fm_done
        PROD    0, 3
        PROD    1, 4
        PROD    2, 5
fm_done:
        ; result = acc[2..5]; a negative result is floor(-P / 65536) =
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
@ok:    ; |a| << 16 over |b|: the quotient is below 2^30, so its top 16 bits
        ; are 0 and the first 16 steps only move |a| >> 16 (< |b|) into
        ; the remainder: start from there, 32 steps with acc = |a| << 16
        ; low 32 bits
        lda     fa+2
        sta     fdrem
        lda     fa+3
        sta     fdrem+1
        stz     fdrem+2
        stz     fdrem+3
        stz     fdrem+4
        stz     acc
        stz     acc+1
        lda     fa
        sta     acc+2
        lda     fa+1
        sta     acc+3
        lda     #32
        sta     m_k
@loop:  asl     acc
        rol     acc+1
        rol     acc+2
        rol     acc+3
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
:
.ifdef BANKED_GAME
        ; GAME.TABLES was installed by the loader at GT_ADDR in this bank.
        rts
.else
        sta     far_dst+2
        lda     #<GT_ADDR
        sta     far_dst
        lda     #>GT_ADDR
        sta     far_dst+1
        lda     #<gtables_start
        sta     far_ptr
        lda     #>gtables_start
        sta     far_ptr+1
        ; the tables and the set-up overlay after them (GFAR, GOVL)
        lda     #<(__GFAR_SIZE__ + __GOVL_SIZE__)
        sta     far_len
        lda     #>(__GFAR_SIZE__ + __GOVL_SIZE__)
        sta     far_len+1
        jmp     kjt_far_write
.assert gtables_start = __GFAR_RUN__, lderror, "the tables start GFAR"
.endif

; void P_LoadOverlay(void): the set-up overlay back into place
_P_LoadOverlay:
.ifdef BANKED_GAME
        ; Setup routines are permanent banked code, addressed via their
        ; invariant entry stubs like every other game routine.
        rts
.else
        lda     _game_far_bank
        sta     far_src+2
        lda     #<(GT_ADDR + __GFAR_SIZE__)
        sta     far_src
        lda     #>(GT_ADDR + __GFAR_SIZE__)
        sta     far_src+1
        lda     #<__GOVL_RUN__
        sta     far_ptr
        lda     #>__GOVL_RUN__
        sta     far_ptr+1
        lda     #<__GOVL_SIZE__
        sta     far_len
        lda     #>__GOVL_SIZE__
        sta     far_len+1
        jmp     kjt_far_read
.endif

.endif ; DD_MAPDIR
