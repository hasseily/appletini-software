; Doom for the Appletini -- the renderer's multiply macros (rfmul.s has the
; method: quarter squares through the zero-page pointers ms1..ms4).

.globalzp ms1, ms2, ms3, ms4, mfneg

; MULU na, nb, nr: the unrolled unsigned product (see the header)
.macro MULU na, nb, nr
        MULUB   na, nb, nr, m_b
.endmacro

; MULUB na, nb, nr, b: MULU with the second operand at b
.macro MULUB na, nb, nr, b
        .repeat nr, k
        stz     m_r+k
        .endrepeat
        .repeat na, i
        .if i < nr
        .scope
        lda     m_a+i
        jeq     row_done
        sta     ms1
        sta     ms3
        eor     #$FF
        sta     ms2
        sta     ms4
        .repeat nb, j
        .if i + j < nr
        .scope
        ldy     b+j
        beq     prod_done
        sec
        lda     (ms1),y
        sbc     (ms2),y
        .if i + j + 1 < nr
        tax
        lda     (ms3),y
        sbc     (ms4),y
        tay
        txa
        clc
        adc     m_r+i+j
        sta     m_r+i+j
        tya
        adc     m_r+i+j+1
        sta     m_r+i+j+1
        .if i + j + 2 < nr
        bcc     prod_done
        .repeat nr - (i + j + 2), c
        inc     m_r+i+j+2+c
        .if c < nr - (i + j + 3)
        bne     prod_done
        .endif
        .endrepeat
        .endif
        .else
        clc
        adc     m_r+i+j
        sta     m_r+i+j
        .endif
prod_done:
        .endscope
        .endif
        .endrepeat
row_done:
        .endscope
        .endif
        .endrepeat
.endmacro

; NEG zp, n: two's complement of n bytes at zp
.macro NEGN addr, n
        sec
        .repeat n, k
        lda     #0
        sbc     addr+k
        sta     addr+k
        .endrepeat
.endmacro

; MULS na, nb, nr, unsigned routine
.macro MULS na, nb, nr, uroutine
        .scope
        stz     mfneg
        lda     m_a+na-1
        bpl     apos
        NEGN    m_a, na
        lda     #$80
        sta     mfneg
apos:   lda     m_b+nb-1
        bpl     bpos
        NEGN    m_b, nb
        lda     mfneg
        eor     #$80
        sta     mfneg
bpos:   jsr     uroutine
        bit     mfneg
        bpl     done
        NEGN    m_r, nr
done:   rts
        .endscope
.endmacro

