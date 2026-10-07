; mathgame.inc: the game's math of math.s (src/native/MATH.md):
; R_PointToAngle3 (pta3, its octant pta_oct), finesine, finecosine,
; P_AproxDistance (aproxdist) and
; the cosine's exceptions (cosexc). GPL-2, the port's own (a derivative of
; upstream's r_iigs65.s and tables65.s, as math.s).
;
; Included by math.s in its game build (-D GAMEMATH, src/native/play.mk:
; the tic image, which links the render build math-r.o and this as
; math-g.o in the core, docs/GAME.md "Wave 2 as integrated"); without
; GAMEMATH and RENDER (a build none of the makefiles has now) it would
; sit in MATHW beside the rest. The tables are the tables bank's
; (MT_TBANK) through mt_far.

; pta_oct: X = k from M_A, M_B (x, y) and 4-byte magnitudes in them; for
; x <= y the two are swapped, so the slope is M_B / M_A (num / den).
; Changes A, X, Y.
pta_oct:
        ldx #0
        bit M_A+3
        bpl :+
        NEG32 M_A
        ldx #4
:       bit M_B+3
        bpl :+
        NEG32 M_B
        inx
        inx
:       lda M_B                 ; y < x (signed)?
        cmp M_A
        lda M_B+1
        sbc M_A+1
        lda M_B+2
        sbc M_A+2
        lda M_B+3
        sbc M_A+3
        bvc :+
        eor #$80
:       bmi @done
        inx                     ; x <= y: num = x, den = y
        ldy #3
@swap:  lda M_A,y
        pha
        lda M_B,y
        sta M_A,y
        pla
        sta M_B,y
        dey
        bpl @swap
@done:  rts

; ---------------------------------------------------------------------------
; pta3: M_R = R_PointToAngle3(M_A, M_B) (x, y): 0 for (0, 0); else the
; octant and tantoangle[SlopeDiv(num, den)], SlopeDiv = (uint16_t)((num
; << 3) / (den >> 8)) at most 2048, and 2048 for den >> 8 = 0. A quotient
; below 4096 (num <= den: always but at the ends of the range) takes 12
; division steps; else udiv32. Changes M_A, M_B, M_T, A, X, Y, MT+0 - MT+9,
; MT_P.
; ---------------------------------------------------------------------------
pta3:
        lda M_A
        ora M_A+1
        ora M_A+2
        ora M_A+3
        ora M_B
        ora M_B+1
        ora M_B+2
        ora M_B+3
        bne @go
        stz M_R
        stz M_R+1
        stz M_R+2
        stz M_R+3
        rts
@go:    jsr pta_oct
        phx                     ; k
        lda M_A+1               ; D = den >> 8 (24 bits, M_A+1 - M_A+3)
        ora M_A+2
        ora M_A+3
        bne @n
        ldx #<2048              ; D = 0: 2048
        ldy #>2048
        jmp @q
@n:     asl M_B                 ; N = num << 3, modulo 2^32
        rol M_B+1
        rol M_B+2
        rol M_B+3
        asl M_B
        rol M_B+1
        rol M_B+2
        rol M_B+3
        asl M_B
        rol M_B+1
        rol M_B+2
        rol M_B+3
        lda M_B+1               ; R = N >> 12 (MT+0 - MT+2), and the low
        sta MT                  ;   12 bits of N at the top of MT+3, MT+4
        lda M_B+2
        sta MT+1
        lda M_B+3
        sta MT+2
        lda M_B
        sta MT+3
        lda M_B+1
        sta MT+4
        ldx #4
@nib:   lsr MT+2
        ror MT+1
        ror MT
        asl MT+3
        rol MT+4
        dex
        bne @nib
        lda MT                  ; R < D: a quotient of 12 bits
        cmp M_A+1
        lda MT+1
        sbc M_A+2
        lda MT+2
        sbc M_A+3
        bcs @big
        stz MT+5
        stz MT+6
        ldx #12
@step:  asl MT+3                ; R = R << 1 | the next bit of N
        rol MT+4
        rol MT
        rol MT+1
        rol MT+2
        bcs @sub
        lda MT
        cmp M_A+1
        lda MT+1
        sbc M_A+2
        lda MT+2
        sbc M_A+3
        bcc @bit
@sub:   lda MT                  ; (carry set)
        sbc M_A+1
        sta MT
        lda MT+1
        sbc M_A+2
        sta MT+1
        lda MT+2
        sbc M_A+3
        sta MT+2
        sec
@bit:   rol MT+5
        rol MT+6
        dex
        bne @step
        ldx MT+5
        ldy MT+6
        bra @clamp
@big:   lda M_A+1               ; N / D, 32 bits: D from den's bytes 1-3
        pha
        lda M_A+2
        pha
        lda M_A+3
        pha
        COPY32 M_B, M_A
        pla
        sta M_B+2
        pla
        sta M_B+1
        pla
        sta M_B
        stz M_B+3
        jsr udiv32
        ldx M_R
        ldy M_R+1
@clamp: cpy #>2049              ; (uint16_t) q, at most 2048
        bcc @q
        bne @max
        cpx #<2049
        bcc @q
@max:   ldx #<2048
        ldy #>2048
@q:     stx MT_P                ; tantoangle[q], 4 planes
        tya
        clc
        adc #>TANTO0
        sta MT_P+1
        lda #MT_TBANK
        ldx #4
        ldy #TANTO_STRIDE
        jsr mt_far
        plx                     ; k
        lda OCTMINUS,x
        bne @minus
        lda MT_E                ; C + T
        sta M_R
        lda MT_E+1
        sta M_R+1
        lda MT_E+2
        sta M_R+2
        lda MT_E+3
        clc
        adc OCTC,x
        sta M_R+3
        rts
@minus: cpx #2
        bne @cmt
        NEG32 MT_E              ; 0 - T
        COPY32 MT_E, M_R
        rts
@cmt:   lda MT_E                ; C - T: the low 3 bytes of C are $FF
        eor #$FF
        sta M_R
        lda MT_E+1
        eor #$FF
        sta M_R+1
        lda MT_E+2
        eor #$FF
        sta M_R+2
        lda OCTC,x
        sec
        sbc MT_E+3
        sta M_R+3
        rts


; ---------------------------------------------------------------------------
; finesine: M_R = finesine[M_A], M_A = 0-8191 (tables65.s): the magnitude
; from the two sine planes, the sign bit 12 of x. finecosine: the 12
; entries where upstream's cosine is not the shifted sine from their list,
; else finesine[(x + 2048) & 8191]. Change A, X, Y, MT_E, MT_P (and M_A,
; finecosine).
; ---------------------------------------------------------------------------
finecosine:
        ldx cosexc              ; the exceptions
@e:     dex
        bmi @none
        lda M_A
        cmp cosexc+1,x
        bne @e
        lda M_A+1
        cmp cosexc+17,x
        bne @e
        lda cosexc+33,x
        sta M_R
        lda cosexc+49,x
        sta M_R+1
        lda cosexc+65,x
        sta M_R+2
        lda cosexc+81,x
        sta M_R+3
        rts
@none:  lda M_A+1
        clc
        adc #>2048
        sta M_A+1
finesine:
        lda M_A
        sta MT_P
        lda M_A+1
        and #$1F
        clc
        adc #>SINELO
        sta MT_P+1
        lda #MT_TBANK
        ldx #2
        ldy #>(SINEHI - SINELO)
        jsr mt_far
        lda MT_E
        sta M_R
        lda MT_E+1
        sta M_R+1
        lda M_A+1
        and #$10
        bne @neg
        stz M_R+2
        stz M_R+3
        rts
@neg:   sec                     ; -magnitude, 32 bits (0 stays 0)
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


; ---------------------------------------------------------------------------
; aproxdist: M_R = P_AproxDistance(M_A, M_B) (p_path65.s): dx = |dx|,
; dy = |dy| (32-bit two's complement), then dx + dy - m / 2 for the smaller
; (a signed compare) m, as m - (m >> 1) with an arithmetic shift. Changes
; M_A, M_B, A.
; ---------------------------------------------------------------------------
aproxdist:
        bit M_A+3
        bpl :+
        NEG32 M_A
:       bit M_B+3
        bpl :+
        NEG32 M_B
:       lda M_A                 ; dx < dy (signed)?
        cmp M_B
        lda M_A+1
        sbc M_B+1
        lda M_A+2
        sbc M_B+2
        lda M_A+3
        sbc M_B+3
        bvc :+
        eor #$80
:       bmi @dx
        lda M_B+3               ; no: dx + (dy >> 1) + (dy & 1)
        cmp #$80
        ror M_B+3
        ror M_B+2
        ror M_B+1
        ror M_B
        lda M_A
        adc M_B
        sta M_R
        lda M_A+1
        adc M_B+1
        sta M_R+1
        lda M_A+2
        adc M_B+2
        sta M_R+2
        lda M_A+3
        adc M_B+3
        sta M_R+3
        rts
@dx:    lda M_A+3               ; yes: dy + (dx >> 1) + (dx & 1)
        cmp #$80
        ror M_A+3
        ror M_A+2
        ror M_A+1
        ror M_A
        lda M_B
        adc M_A
        sta M_R
        lda M_B+1
        adc M_A+1
        sta M_R+1
        lda M_B+2
        adc M_A+2
        sta M_R+2
        lda M_B+3
        adc M_A+3
        sta M_R+3
        rts

; the cosine's exceptions (tools/native/mathtables.py): their count, then
; 16 low bytes of x, 16 high bytes, and the value's 4 bytes, 16 each
cosexc:
        .incbin "cosexc.bin"
