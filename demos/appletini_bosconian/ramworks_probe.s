.setcpu "65C02"

.export _ramworks_probe

RAMRDOFF = $C002
RAMRDON  = $C003
RAMWRTOFF = $C004
RAMWRTON = $C005
RAMWORKS = $C073
PROBE_ADDRESS = $1000
PROBE_ZP = $0020
CLEAR_PTR = $0030
AUX_COLOR_PTR = $0064

.segment "RODATA"
probe_code:
        sta RAMWORKS
        sta RAMRDON
        lda PROBE_ADDRESS
        sta RAMRDOFF
        rts
probe_code_end:

.segment "CODE"

; fastcall unsigned char ramworks_probe(unsigned char bank)
; A contains the bank.  RAMRD redirects instruction fetches above page 1,
; so copy the actual probe to zero page before enabling it.
_ramworks_probe:
        pha
        ldx #(probe_code_end-probe_code)-1
@copy: lda probe_code,x
        sta PROBE_ZP,x
        dex
        bpl @copy
        pla
        jsr PROBE_ZP
        sta RAMWRTOFF
        ldx #$00
        rts

