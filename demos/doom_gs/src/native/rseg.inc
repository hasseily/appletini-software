; rseg.inc: the macros of the seg loops (src/native/rseg.s and the loops
; tools/native/seggen.py writes). docs/RENDER.md 3.2; upstream's
; r_seg65.s:113-186.

; STEP32 v, s: the 32-bit step v += s (genColumn's). Carry and A as the
; last add leaves them (A = the top byte).
.macro STEP32 v, s
        clc
        lda v
        adc s
        sta v
        lda v+1
        adc s+1
        sta v+1
        lda v+2
        adc s+2
        sta v+2
        lda v+3
        adc s+3
        sta v+3
.endmacro

; STEP8E v, s: upstream's STEP8E, the step of a wall edge in the loops of
; segvar.inc: bytes 1-3 only (the edge keeps its byte 0, 8 bits of
; fraction: r_seg65.s:171-186). A = the top byte, N and Z from it.
.macro STEP8E v, s
        clc
        lda v+1
        adc s+1
        sta v+1
        lda v+2
        adc s+2
        sta v+2
        lda v+3
        adc s+3
        sta v+3
.endmacro

; SLT16 a, b: N = (a < b), signed 16-bit. Changes A.
.macro SLT16 p_a, p_b
        lda p_a
        cmp p_b
        lda p_a+1
        sbc p_b+1
        bvc *+4                 ; (no label: a macro's own label would
        eor #$80                ;   end the caller's cheap local scope)
.endmacro

; MOV16 src, dst
.macro MOV16 p_src, p_dst
        lda p_src
        sta p_dst
        lda p_src+1
        sta p_dst+1
.endmacro
