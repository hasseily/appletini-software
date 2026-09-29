; The opcode handlers, h00 to hFF: the dispatch table names them. Each is
; entered with Y the low byte of the stored program counter (the opcode's
; address) and stores it in vpcl once its operands are fetched.

        .segment "HANDLERS"

; An addressing mode, then an operation.
.macro GH opc, mode, entry
.ident(.sprintf("h%02X", opc)):
        jsr mode
        jmp entry
.endmacro

; Read-modify-write on memory and on the accumulator.
.macro RMWH opc, mode, op
.ident(.sprintf("h%02X", opc)):
        jsr mode
        jsr rmw_rd
        jsr op
        jmp rmw_wr
.endmacro

.macro ACCH opc, op
.ident(.sprintf("h%02X", opc)):
        sty vpcl
        jsr rmw_acc
        jsr op
        jmp acc_wr
.endmacro

; The eight accumulator operations share the addressing modes of their
; columns; immediate (column $09) is written out below.
.macro GROUP base, entry
        GH base+$01, am_dpix, entry
        GH base+$03, am_sr, entry
        GH base+$05, am_dp, entry
        GH base+$07, am_dpil, entry
        GH base+$0D, am_abs, entry
        GH base+$0F, am_long, entry
        GH base+$11, am_dpiy, entry
        GH base+$12, am_dpi, entry
        GH base+$13, am_sriy, entry
        GH base+$15, am_dpx, entry
        GH base+$17, am_dpily, entry
        GH base+$19, am_absy, entry
        GH base+$1D, am_absx, entry
        GH base+$1F, am_longx, entry
.endmacro

        GROUP $00, op_ora_m
        GROUP $20, op_and_m
        GROUP $40, op_eor_m
        GROUP $60, op_adc_m
        GROUP $80, st_a
        GROUP $A0, op_lda_m
        GROUP $C0, op_cmp_m
        GROUP $E0, op_sbc_m

        GH $09, imm_m, op_ora
        GH $29, imm_m, op_and
        GH $49, imm_m, op_eor
        GH $69, imm_m, op_adc
        GH $89, imm_m, op_bit           ; BIT #
        GH $A9, imm_m, op_lda
        GH $C9, imm_m, op_cmp
        GH $E9, imm_m, op_sbc

; ---- other reads and stores ----

        GH $24, am_dp, op_bit_m
        GH $2C, am_abs, op_bit_m
        GH $34, am_dpx, op_bit_m
        GH $3C, am_absx, op_bit_m

        GH $64, am_dp, st_z
        GH $74, am_dpx, st_z
        GH $9C, am_abs, st_z
        GH $9E, am_absx, st_z
        GH $86, am_dp, st_x
        GH $8E, am_abs, st_x
        GH $96, am_dpy, st_x
        GH $84, am_dp, st_y
        GH $8C, am_abs, st_y
        GH $94, am_dpx, st_y

        GH $A2, imm_x, op_ldx
        GH $A6, am_dp, op_ldx_m
        GH $AE, am_abs, op_ldx_m
        GH $B6, am_dpy, op_ldx_m
        GH $BE, am_absy, op_ldx_m
        GH $A0, imm_x, op_ldy
        GH $A4, am_dp, op_ldy_m
        GH $AC, am_abs, op_ldy_m
        GH $B4, am_dpx, op_ldy_m
        GH $BC, am_absx, op_ldy_m

        GH $E0, imm_x, op_cpx
        GH $E4, am_dp, op_cpx_m
        GH $EC, am_abs, op_cpx_m
        GH $C0, imm_x, op_cpy
        GH $C4, am_dp, op_cpy_m
        GH $CC, am_abs, op_cpy_m

; ---- read-modify-write ----

        RMWH $06, am_dp, r_asl
        RMWH $0E, am_abs, r_asl
        RMWH $16, am_dpx, r_asl
        RMWH $1E, am_absx, r_asl
        RMWH $26, am_dp, r_rol
        RMWH $2E, am_abs, r_rol
        RMWH $36, am_dpx, r_rol
        RMWH $3E, am_absx, r_rol
        RMWH $46, am_dp, r_lsr
        RMWH $4E, am_abs, r_lsr
        RMWH $56, am_dpx, r_lsr
        RMWH $5E, am_absx, r_lsr
        RMWH $66, am_dp, r_ror
        RMWH $6E, am_abs, r_ror
        RMWH $76, am_dpx, r_ror
        RMWH $7E, am_absx, r_ror
        RMWH $C6, am_dp, r_dec
        RMWH $CE, am_abs, r_dec
        RMWH $D6, am_dpx, r_dec
        RMWH $DE, am_absx, r_dec
        RMWH $E6, am_dp, r_inc
        RMWH $EE, am_abs, r_inc
        RMWH $F6, am_dpx, r_inc
        RMWH $FE, am_absx, r_inc
        RMWH $04, am_dp, r_tsb
        RMWH $0C, am_abs, r_tsb
        RMWH $14, am_dp, r_trb
        RMWH $1C, am_abs, r_trb

        ACCH $0A, r_asl
        ACCH $2A, r_rol
        ACCH $4A, r_lsr
        ACCH $6A, r_ror
        ACCH $1A, r_inc
        ACCH $3A, r_dec

; ---- branches ----

h10:    bit vN                  ; BPL
        bpl br_t
        bra br_n
h30:    bit vN                  ; BMI
        bmi br_t
        bra br_n
h50:    bit vV                  ; BVC
        bvc br_t
        bra br_n
h70:    bit vV                  ; BVS
        bvs br_t
        bra br_n
h90:    lda vC                  ; BCC
        beq br_t
        bra br_n
hB0:    lda vC                  ; BCS
        bne br_t
        bra br_n
hD0:    lda vZ                  ; BNE
        bne br_t
        bra br_n
hF0:    lda vZ                  ; BEQ
        beq br_t
br_n:   FETCH
        sty vpcl
        jmp loop
h80:                            ; BRA
br_t:   FETCH                   ; A = the offset, N its sign
        bpl :+
        dec vpch
:       sty tmp
        clc
        adc tmp
        sta vpcl
        bcc :+
        inc vpch
:       lda vpch
        cmp cpg_vpch
        beq :+
        lda #EV_PAGE
        tsb vm_event
:       jmp loop

h82:    FETCH                   ; BRL
        sta tmp
        FETCH
        sta tmp+1
        tya
        clc
        adc tmp
        sta vpcl
        lda vpch
        adc tmp+1
        sta vpch
        jsr pc_moved
        jmp loop

; ---- jumps, calls, returns ----

h4C:    FETCH                   ; JMP a
        sta tmp
        FETCH
        sta tmp+1
        jsr set_pc
        jmp loop

h5C:    FETCH                   ; JML al
        sta tmp
        FETCH
        sta tmp+1
        FETCH
        sta vPBR
        jsr set_pc
        jmp loop

h6C:    jsr abs_bank0           ; JMP (a)
        jsr rdptr16
        jsr set_pc
        jmp loop

hDC:    jsr abs_bank0           ; JML [a]
        jsr rdptr24
        lda tmp+2
        sta vPBR
        jsr set_pc
        jmp loop

h7C:    FETCH                   ; JMP (a,x)
        sta ea
        FETCH
        sta ea+1
        sty vpcl
        jsr pbr_x
        jsr rdptr16
        jsr set_pc
        jmp loop

h20:    FETCH                   ; JSR a: pushes the address of its last byte
        sta tmp
        FETCH
        sta tmp+1
        sty vpcl
        lda vpch
        jsr push8
        lda vpcl
        jsr push8
        jsr set_pc
        jmp loop

h22:    FETCH                   ; JSL al
        sta tmp
        FETCH
        sta tmp+1
        sty vpcl
        lda vPBR                ; pushed before the bank byte is fetched
        jsr pushl8
        ldy vpcl
        FETCH
        sta tmp+2
        sty vpcl
        lda vpch
        jsr pushl8
        lda vpcl
        jsr pushl8
        jsr page_one
        lda tmp+2
        sta vPBR
        jsr set_pc
        jmp loop

hFC:    FETCH                   ; JSR (a,x)
        sta tmp
        sty vpcl
        lda vpcl                ; pushes the address of the high byte,
        clc                     ; before fetching it
        adc #1
        sta tmp+2
        lda vpch
        adc #0
        jsr pushl8
        lda tmp+2
        jsr pushl8
        ldy vpcl
        FETCH
        sta ea+1
        sty vpcl
        lda tmp
        sta ea
        jsr pbr_x
        jsr rdptr16
        jsr page_one
        jsr set_pc
        jmp loop

h60:    sty vpcl                ; RTS
        jsr pull8
        sta tmp
        jsr pull8
        sta vpch
        lda tmp
        sta vpcl
        jsr pc_moved
        jmp loop

h6B:    sty vpcl                ; RTL
        jsr pulll8
        sta tmp
        jsr pulll8
        sta vpch
        jsr pulll8
        sta vPBR
        jsr page_one
        lda tmp
        sta vpcl
        jsr pc_moved
        jmp loop

h40:    sty vpcl                ; RTI
        jsr pull8
        jsr setp
        jsr pull8
        sta tmp
        jsr pull8
        sta tmp+1
        lda vE
        bne :+
        jsr pull8
        sta vPBR
:       jsr set_pc
        jmp loop

h00:    FETCH                   ; BRK: the signature byte is skipped
        sty vpcl
        jsr getp                ; emulation: B is the X bit, set
        ldx #$E6
        ldy vE
        beq :+
        ldx #$FE
:       jsr interrupt
        jmp loop

h02:    FETCH                   ; COP
        sty vpcl
        jsr getp
        ldx #$E4
        ldy vE
        beq :+
        ldx #$F4
:       jsr interrupt
        jmp loop

; ea = the absolute operand in bank 0, wrapping there.
abs_bank0:
        FETCH
        sta ea
        FETCH
        sta ea+1
        sty vpcl
        stz ea+2
        lda #WR_BANK0
        sta eawrap
        rts

; ea += X in the bank of PBR, wrapping there.
pbr_x:  clc
        lda ea
        adc vX
        sta ea
        lda ea+1
        adc vX+1
        sta ea+1
        lda vPBR
        sta ea+2
        lda #WR_BANK0
        sta eawrap
        rts

; ---- the stack ----

h48:    sty vpcl                ; PHA
        ldx #vA
        bit vMX
        bmi push_lo
push_hl:
        lda $01,x
        phx
        jsr push8
        plx
push_lo:
        lda $00,x
        jsr push8
        jmp loop
hDA:    sty vpcl                ; PHX
        ldx #vX
        bit vMX
        bvs push_lo
        bra push_hl
h5A:    sty vpcl                ; PHY
        ldx #vY
        bit vMX
        bvs push_lo
        bra push_hl

h68:    sty vpcl                ; PLA
        jsr pull8
        sta dat
        bit vMX
        bmi :+
        jsr pull8
        sta dat+1
:       jmp op_lda
hFA:    sty vpcl                ; PLX
        jsr pull_x
        jmp op_ldx
h7A:    sty vpcl                ; PLY
        jsr pull_x
        jmp op_ldy
pull_x: jsr pull8
        sta dat
        bit vMX
        bvs :+
        jsr pull8
        sta dat+1
:       rts

h08:    sty vpcl                ; PHP
        jsr getp
        jsr push8
        jmp loop
h28:    sty vpcl                ; PLP
        jsr pull8
        jsr setp
        jmp loop
h8B:    sty vpcl                ; PHB
        lda vDBR
        jsr push8
        jmp loop
h4B:    sty vpcl                ; PHK
        lda vPBR
        jsr push8
        jmp loop
hAB:    sty vpcl                ; PLB
        jsr pulll8
        sta vDBR
        sta vN
        sta vZ
        jsr page_one
        jmp loop
h0B:    sty vpcl                ; PHD
        lda vD+1
        jsr pushl8
        lda vD
        jsr pushl8
        jsr page_one
        jmp loop
h2B:    sty vpcl                ; PLD
        jsr pulll8
        sta vD
        jsr pulll8
        sta vD+1
        jsr page_one
        ldx #vD
        jmp nz16x
hF4:    FETCH                   ; PEA
        sta tmp
        FETCH
        sty vpcl
push_word:                      ; A = high byte, tmp = low byte
        jsr pushl8
        lda tmp
        jsr pushl8
        jsr page_one
        jmp loop
hD4:    jsr am_dpl              ; PEI
        jsr rdptr16
        lda tmp+1
        bra push_word
h62:    FETCH                   ; PER
        sta tmp
        FETCH
        sta tmp+1
        sty vpcl
        sec                     ; + the program counter, stored + 1
        tya
        adc tmp
        sta tmp
        lda vpch
        adc tmp+1
        bra push_word

; ---- block moves: one byte a step ----

h54:    lda #1                  ; MVN
        bra block
h44:    lda #$FF                ; MVP
block:  sta tmp+3
        FETCH
        sta tmp                 ; destination bank
        FETCH
        sta tmp+1               ; source bank
        sty vpcl
        lda tmp
        sta vDBR
        lda vX
        sta ea
        lda vX+1
        sta ea+1
        lda tmp+1
        sta ea+2
        jsr far_rd
        pha
        lda vY
        sta ea
        lda vY+1
        sta ea+1
        lda tmp
        sta ea+2
        pla
        jsr far_wr
        ldx #vX
        jsr idx_step
        ldx #vY
        jsr idx_step
        lda vA                  ; A counts down; the move repeats itself
        bne :+                  ; until A passes zero
        dec vA+1
:       dec vA
        lda vA
        and vA+1
        inc a
        beq @done
        lda vpcl
        sec
        sbc #3
        sta vpcl
        bcs @done
        dec vpch
        jsr pc_moved
@done:  jmp loop

; X = an index register's address: one step by tmp+3, at its width.
idx_step:
        bit tmp+3
        bmi @down
        inc $00,x
        bne :+
        bit vMX
        bvs :+
        inc $01,x
:       rts
@down:  lda $00,x
        bne :+
        bit vMX
        bvs :+
        dec $01,x
:       dec $00,x
        rts

; ---- registers ----

hE8:    sty vpcl                ; INX
        ldx #vX
        jmp incidx
hC8:    sty vpcl                ; INY
        ldx #vY
        jmp incidx
hCA:    sty vpcl                ; DEX
        ldx #vX
        jmp decidx
h88:    sty vpcl                ; DEY
        ldx #vY
        jmp decidx

hAA:    sty vpcl                ; TAX
        ldx #vX
        ldy #vA
        jmp xfer_i
hA8:    sty vpcl                ; TAY
        ldx #vY
        ldy #vA
        jmp xfer_i
hBA:    sty vpcl                ; TSX
        ldx #vX
        ldy #vS
        jmp xfer_i
h9B:    sty vpcl                ; TXY
        ldx #vY
        ldy #vX
        jmp xfer_i
hBB:    sty vpcl                ; TYX
        ldx #vX
        ldy #vY
        jmp xfer_i
h8A:    sty vpcl                ; TXA
        ldy #vX
        jmp xfer_a
h98:    sty vpcl                ; TYA
        ldy #vY
        jmp xfer_a

h9A:    sty vpcl                ; TXS
        lda vX
        sta vS
        lda vX+1
        ldx vE
        beq :+
        lda #1
:       sta vS+1
        jmp loop
h1B:    sty vpcl                ; TCS
        lda vA
        sta vS
        lda vA+1
        sta vS+1
        jsr page_one
        jmp loop
h3B:    sty vpcl                ; TSC: all 16 bits
        lda vS
        sta vA
        lda vS+1
        sta vA+1
        ldx #vA
        jmp nz16x
h5B:    sty vpcl                ; TCD
        lda vA
        sta vD
        lda vA+1
        sta vD+1
        ldx #vD
        jmp nz16x
h7B:    sty vpcl                ; TDC
        lda vD
        sta vA
        lda vD+1
        sta vA+1
        ldx #vA
        jmp nz16x
hEB:    sty vpcl                ; XBA: N and Z of the new low byte
        lda vA
        ldx vA+1
        sta vA+1
        stx vA
        stx vN
        stx vZ
        jmp loop

; ---- flags ----

h18:    sty vpcl                ; CLC
        stz vC
        jmp loop
h38:    sty vpcl                ; SEC
        lda #1
        sta vC
        jmp loop
hB8:    sty vpcl                ; CLV
        stz vV
        jmp loop
h58:    sty vpcl                ; CLI
        lda #$04
        trb vP
        jmp loop
h78:    sty vpcl                ; SEI
        lda #$04
        tsb vP
        jmp loop
hD8:    sty vpcl                ; CLD
        lda #$08
        trb vP
        jmp loop
hF8:    sty vpcl                ; SED
        lda #$08
        tsb vP
        jmp loop
hC2:    FETCH                   ; REP
        sty vpcl
        eor #$FF
        sta tmp
        jsr getp
        and tmp
        jsr setp
        jmp loop
hE2:    FETCH                   ; SEP
        sty vpcl
        sta tmp
        jsr getp
        ora tmp
        jsr setp
        jmp loop
hFB:    sty vpcl                ; XCE
        lda vC
        ldx vE
        stx vC
        sta vE
        jsr normalise
        jmp loop

; ---- the rest ----

hEA:    sty vpcl                ; NOP
        jmp loop
h42:    iny                     ; WDM: skips a byte without reading it
        sty vpcl
        bne :+
        inc vpch
        jsr pc_moved
:       jmp loop
hCB:    sty vpcl                ; WAI
        lda #1
        bra halt
hDB:    sty vpcl                ; STP
        lda #2
halt:   sta vm_state
        lda #EV_HALT
        tsb vm_event
        jmp loop
