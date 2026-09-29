; The operations. An entry named op_xxx_m reads its operand at ea first
; (by the width of M or X); op_xxx takes it in dat. Each ends at loop.

        .segment "HANDLERS"

; ---- the accumulator group ----

op_ora_m:
        jsr rd_m
op_ora: lda vA
        ora dat
        sta vA
        sta vN
        sta vZ
        bit vMX
        bmi done8
        lda vA+1
        ora dat+1
; A = the new high byte of a 16-bit result whose low byte is in vA and vZ.
hi_done:
        sta vA+1
        sta vN
        ora vZ
        sta vZ
done8:  jmp loop

op_and_m:
        jsr rd_m
op_and: lda vA
        and dat
        sta vA
        sta vN
        sta vZ
        bit vMX
        bmi done8
        lda vA+1
        and dat+1
        bra hi_done

op_eor_m:
        jsr rd_m
op_eor: lda vA
        eor dat
        sta vA
        sta vN
        sta vZ
        bit vMX
        bmi done8
        lda vA+1
        eor dat+1
        bra hi_done

op_lda_m:
        jsr rd_m
op_lda: lda dat
        sta vA
        sta vN
        sta vZ
        bit vMX
        bmi done8
        lda dat+1
        bra hi_done

; C and V from the host's flags after the last ADC or SBC.
cv_out: rol vC                  ; vC was cleared by lsr vC
        lda #0
        bvc :+
        lda #$40
:       sta vV
        jmp loop

op_adc_m:
        jsr rd_m
op_adc: lda vP
        and #$08
        bne adc_dec
        lsr vC
        bit vMX
        bmi @8
        lda vA
        adc dat
        sta vA
        sta vZ
        lda vA+1
        adc dat+1
        sta vA+1
        sta vN
        ora vZ                  ; keeps C and V
        sta vZ
        bra cv_out
@8:     lda vA
        adc dat
        sta vA
        sta vN
        sta vZ
        bra cv_out

op_sbc_m:
        jsr rd_m
op_sbc: lda vP
        and #$08
        bne sbc_dec
        lsr vC
        bit vMX
        bmi @8
        lda vA
        sbc dat
        sta vA
        sta vZ
        lda vA+1
        sbc dat+1
        sta vA+1
        sta vN
        ora vZ
        sta vZ
        bra cv_out
@8:     lda vA
        sbc dat
        sta vA
        sta vN
        sta vZ
        bra cv_out

; Decimal mode, a digit at a time with the 65816's corrections, so that
; invalid digits give the chip's results (tools/ref816/cpu816.c, add()).
; SBC adds the complement of its operand. dt: +0 subtract flag (bit 7),
; +1 the carry into the digit, +2 A's digit, +3 the operand's digit,
; +4 the low digit of the byte, +5 the index of the last byte.
sbc_dec:
        lda dat
        eor #$FF
        sta dat
        lda dat+1
        eor #$FF
        sta dat+1
        lda #$80
        bra dec_go
adc_dec:
        lda #0
dec_go: sta dt
        lda vC
        sta dt+1
        lda #0
        bit vMX
        bmi :+
        inc a
:       sta dt+5
        ldx #0
@byte:  lda vA,x
        and #$0F
        sta dt+2
        lda dat,x
        and #$0F
        sta dt+3
        jsr dsum
        jsr dfix
        sta dt+4
        lda vA,x
        lsr a
        lsr a
        lsr a
        lsr a
        sta dt+2
        lda dat,x
        lsr a
        lsr a
        lsr a
        lsr a
        sta dt+3
        jsr dsum
        cpx dt+5
        bne @fix
        pha                     ; the top digit: V before its correction
        lda dt+2
        eor dt+3
        eor #$FF
        sta dt+3
        pla
        pha
        eor dt+2
        and dt+3
        and #$08
        beq :+
        lda #$40
:       sta vV
        pla
@fix:   jsr dfix
        asl a
        asl a
        asl a
        asl a
        ora dt+4
        sta vA,x
        inx
        cpx dt+5
        beq @byte
        bcc @byte
        lda dt+1
        sta vC
        lda vA
        sta vN
        sta vZ
        bit vMX
        bmi :+
        lda vA+1
        sta vN
        ora vZ
        sta vZ
:       jmp loop

; A = the carry in + the two digits.
dsum:   lda dt+1
        clc
        adc dt+2
        adc dt+3
        rts

; A = s, a digit sum: the corrected digit, and the carry out in dt+1.
dfix:   bit dt
        bmi @sub
        cmp #10
        bcc @nocarry
        adc #5                  ; C set: + 6
        and #$0F
        ldy #1
        sty dt+1
        rts
@nocarry:
        stz dt+1
        rts
@sub:   cmp #16
        bcs @carry
        sbc #5                  ; C clear: - 6
        and #$0F
        stz dt+1
        rts
@carry: and #$0F
        ldy #1
        sty dt+1
        rts

; ---- compare ----

op_cmp_m:
        jsr rd_m
op_cmp: ldx #vA
        bit vMX
        bmi cmp8
cmp16:  lda $00,x
        sec
        sbc dat
        sta vZ
        lda $01,x
        sbc dat+1
        sta vN
        ora vZ
        sta vZ
        bra cmpc
cmp8:   lda $00,x
        sec
        sbc dat
        sta vN
        sta vZ
cmpc:   lda #0
        rol a
        sta vC
        jmp loop

op_cpx_m:
        jsr rd_x
op_cpx: ldx #vX
cpidx:  bit vMX
        bvs cmp8
        bra cmp16
op_cpy_m:
        jsr rd_x
op_cpy: ldx #vY
        bra cpidx

; ---- BIT ----

op_bit_m:
        jsr rd_m
        bit vMX
        bmi :+
        lda dat+1               ; N and V from bits 15 and 14
        bra :++
:       lda dat
:       sta vN
        sta vV
op_bit: lda vA                  ; immediate: Z only
        and dat
        sta vZ
        bit vMX
        bmi :+
        lda vA+1
        and dat+1
        ora vZ
        sta vZ
:       jmp loop

; ---- index loads ----

op_ldx_m:
        jsr rd_x
op_ldx: ldx #vX
ldidx:  lda dat
        sta $00,x
        sta vN
        sta vZ
        bit vMX
        bvs :+
        lda dat+1
        sta $01,x
        sta vN
        ora vZ
        sta vZ
:       jmp loop
op_ldy_m:
        jsr rd_x
op_ldy: ldx #vY
        bra ldidx

; ---- stores ----

st_a:   lda vA
        sta dat
        lda vA+1
        sta dat+1
        jsr wr_m
        jmp loop
st_z:   stz dat
        stz dat+1
        jsr wr_m
        jmp loop
st_x:   ldx #vX
        bra st_idx
st_y:   ldx #vY
st_idx: lda $00,x
        sta dat
        lda $01,x
        sta dat+1
        jsr wr_x
        jmp loop

; ---- read-modify-write: rmw_rd, an r_ operation on dat, rmw_wr ----

rmw_rd: lda ea
        sta eas
        lda ea+1
        sta eas+1
        lda ea+2
        sta eas+2
        jmp rd_m

; The high byte first, as the 65816 writes them.
rmw_wr: bit vMX
        bmi :+
        lda dat+1
        jsr far_wr
        lda eas
        sta ea
        lda eas+1
        sta ea+1
        lda eas+2
        sta ea+2
:       lda dat
        jsr far_wr
        jmp loop

; The accumulator: the same operations on a copy.
rmw_acc:
        lda vA
        sta dat
        lda vA+1
        sta dat+1
        rts
acc_wr: lda dat
        sta vA
        bit vMX
        bmi :+
        lda dat+1
        sta vA+1
:       jmp loop

r_asl:  stz vC
        bit vMX
        bmi :+
        asl dat
        rol dat+1
        bra shf16
:       asl dat
        bra shf8
r_rol:  lsr vC
        bit vMX
        bmi :+
        rol dat
        rol dat+1
        bra shf16
:       rol dat
        bra shf8
r_lsr:  stz vC
        bit vMX
        bmi :+
        lsr dat+1
        ror dat
        bra shf16
:       lsr dat
        bra shf8
r_ror:  lsr vC
        bit vMX
        bmi :+
        ror dat+1
        ror dat
        bra shf16
:       ror dat
        bra shf8
shf16:  rol vC
nz16d:  lda dat+1
        sta vN
        ora dat
        sta vZ
        rts
shf8:   rol vC
nz8d:   lda dat
        sta vN
        sta vZ
        rts

r_inc:  bit vMX
        bmi :++
        inc dat
        bne :+
        inc dat+1
:       bra nz16d
:       inc dat
        bra nz8d
r_dec:  bit vMX
        bmi :++
        lda dat
        bne :+
        dec dat+1
:       dec dat
        bra nz16d
:       dec dat
        bra nz8d

; TSB and TRB: Z from A AND the operand; N and C unchanged.
r_tsb:  jsr tzero
        lda dat
        ora vA
        sta dat
        lda dat+1
        ora vA+1
        sta dat+1
        rts
r_trb:  jsr tzero
        lda vA
        eor #$FF
        and dat
        sta dat
        lda vA+1
        eor #$FF
        and dat+1
        sta dat+1
        rts
tzero:  lda dat
        and vA
        sta vZ
        bit vMX
        bmi :+
        lda dat+1
        and vA+1
        ora vZ
        sta vZ
:       rts

; ---- index registers ----

; X = the register's zero page address.
incidx: inc $00,x
        bne nzidx
        bit vMX
        bvs nzidx
        inc $01,x
nzidx:  lda $00,x
        sta vN
        sta vZ
        bit vMX
        bvs :+
        lda $01,x
        sta vN
        ora vZ
        sta vZ
:       jmp loop
decidx: lda $00,x
        bne :+
        bit vMX
        bvs :+
        dec $01,x
:       dec $00,x
        bra nzidx

; Transfers to an index register (X = destination, Y = source): the
; destination's width decides.
xfer_i: lda $0000,y
        sta $00,x
        sta vN
        sta vZ
        bit vMX
        bvs :+
        lda $0001,y
        sta $01,x
        sta vN
        ora vZ
        sta vZ
        jmp loop
:       stz $01,x
        jmp loop

; Transfers to A (Y = source): the width of M.
xfer_a: lda $0000,y
        sta vA
        sta vN
        sta vZ
        bit vMX
        bmi :+
        lda $0001,y
        sta vA+1
        sta vN
        ora vZ
        sta vZ
:       jmp loop

; N and Z of the 16-bit register at zero page X.
nz16x:  lda $00,x
        sta vZ
        lda $01,x
        sta vN
        ora vZ
        sta vZ
        jmp loop
