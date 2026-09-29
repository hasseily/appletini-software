; Addressing modes, operand reads and writes by width, and the stack.
;
; An addressing mode routine is entered with Y the stored program
; counter's low byte (as a handler is), fetches its operand bytes, stores
; Y in vpcl, and leaves the effective address in ea with its wrap rule in
; eawrap (ea_next in far.s; README.md, "The far layer and the map").

        .segment "CORE"

; ---- immediate ----

imm_m:  FETCH
        sta dat
        bit vMX
        bmi imm_done
        FETCH
        sta dat+1
imm_done:
        sty vpcl
        rts

imm_x:  FETCH
        sta dat
        bit vMX
        bvs imm_done
        FETCH
        sta dat+1
        sty vpcl
        rts

; ---- direct page ----

am_dp:  FETCH
        sty vpcl
; ea = D + A in bank 0; in emulation mode with DL = 0, in the page of D.
dpea:   ldx vE
        beq dpea_n
        ldx vD
        bne dpea_n
        sta ea
        lda vD+1
        sta ea+1
        stz ea+2
        lda #WR_PAGE
        sta eawrap
        rts

; [d] and PEI: never in the page.
am_dpl: FETCH
        sty vpcl
dpea_n: clc
        adc vD
        sta ea
        lda vD+1
        adc #0
        sta ea+1
        stz ea+2
        lda #WR_BANK0
        sta eawrap
        rts

am_dpx: FETCH
        sty vpcl
        clc
        adc vX
        sta tmp
        lda vX+1
        bra dpidx
am_dpy: FETCH
        sty vpcl
        clc
        adc vY
        sta tmp
        lda vY+1
dpidx:  adc #0
        sta tmp+1
        lda tmp
        ldx vE
        beq :+
        ldx vD
        beq dpea                ; emulation, DL = 0: in the page
:       clc
        adc vD
        sta ea
        lda tmp+1
        adc vD+1
        sta ea+1
        stz ea+2
        lda #WR_BANK0
        sta eawrap
        rts

; ---- indirect ----

am_dpi: jsr am_dp
        jsr rdptr16
; ea = DBR:tmp
ptr_dbr:
        lda tmp
        sta ea
        lda tmp+1
        sta ea+1
        lda vDBR
        sta ea+2
        stz eawrap
        rts

am_dpix:
        jsr am_dpx
        jsr rdptr16
        bra ptr_dbr

am_dpiy:
        jsr am_dp
        jsr rdptr16
        jsr ptr_dbr
add_y:  ldx #vY
; ea += the word at zero page X, carrying into the bank.
ea_add: clc
        lda ea
        adc $00,x
        sta ea
        lda ea+1
        adc $01,x
        sta ea+1
        bcc :+
        inc ea+2
:       rts

am_dpil:
        jsr am_dpl
        jsr rdptr24
        lda tmp
        sta ea
        lda tmp+1
        sta ea+1
        lda tmp+2
        sta ea+2
        stz eawrap
        rts

am_dpily:
        jsr am_dpil
        bra add_y

am_sr:  FETCH
        sty vpcl
        clc
        adc vS
        sta ea
        lda vS+1
        adc #0
        sta ea+1
        stz ea+2
        lda #WR_BANK0
        sta eawrap
        rts

am_sriy:
        jsr am_sr
        jsr rdptr16
        jsr ptr_dbr
        bra add_y

; ---- absolute and long ----

am_abs: FETCH
        sta ea
        FETCH
        sta ea+1
        sty vpcl
        lda vDBR
        sta ea+2
        stz eawrap
        rts

am_absx:
        jsr am_abs
        ldx #vX
        jmp ea_add

am_absy:
        jsr am_abs
        jmp add_y

am_long:
        FETCH
        sta ea
        FETCH
        sta ea+1
        FETCH
        sta ea+2
        sty vpcl
        stz eawrap
        rts

am_longx:
        jsr am_long
        ldx #vX
        jmp ea_add

; A pointer at ea into tmp.
rdptr16:
        jsr far_rd
        sta tmp
        jsr ea_next
        jsr far_rd
        sta tmp+1
        rts

rdptr24:
        jsr rdptr16
        jsr ea_next
        jsr far_rd
        sta tmp+2
        rts

; ---- operands by width: M for the accumulator, X for the index ----

rd_m:   bit vMX
        bmi rd8
rd16:   jsr far_rd
        sta dat
        jsr ea_next
        jsr far_rd
        sta dat+1
        rts
rd_x:   bit vMX
        bvc rd16
rd8:    jsr far_rd
        sta dat
        rts

wr_m:   bit vMX
        bmi wr8
wr16:   lda dat
        jsr far_wr
        jsr ea_next
        lda dat+1
        jmp far_wr
wr_x:   bit vMX
        bvc wr16
wr8:    lda dat
        jmp far_wr

; ---- the stack ----
;
; push8 and pull8 are the 6502's: in emulation mode S stays in page 1.
; pushl8 and pulll8 are the 65816's own: S moves as 16 bits, and the
; instruction calls page_one at its end.

push8:  jsr stk_wr
        lda vE
        bne s_dec_lo
s_dec:  lda vS
        bne s_dec_lo
        dec vS+1
s_dec_lo:
        dec vS
        rts

pushl8: jsr stk_wr
        bra s_dec

stk_wr: ldx vS
        stx ea
        ldx vS+1
        stx ea+1
        stz ea+2
        jmp far_wr

pull8:  lda vE
        beq pulll8
        inc vS
        bra stk_rd
pulll8: inc vS
        bne stk_rd
        inc vS+1
stk_rd: lda vS
        sta ea
        lda vS+1
        sta ea+1
        stz ea+2
        jmp far_rd

page_one:
        lda vE
        beq :+
        lda #1
        sta vS+1
:       rts
