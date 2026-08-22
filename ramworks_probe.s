.setcpu "65C02"

.export _ramworks_probe, _aux_clear_video, _aux_xor_byte
.import popax

RAMRDOFF = $C002
RAMRDON  = $C003
RAMWRTOFF = $C004
RAMWRTON = $C005
RAMWORKS = $C073
PROBE_ADDRESS = $1000
PROBE_ZP = $0020
CLEAR_PTR = $0030
AUX_XOR_CODE = $0040
AUX_XOR_PTR = $0060
AUX_XOR_VALUE = $0062

.segment "RODATA"
probe_code:
        sta RAMWORKS
        sta RAMRDON
        lda PROBE_ADDRESS
        sta RAMRDOFF
        rts
probe_code_end:

; RAMRD redirects instruction fetches above zero page. This tiny trampoline
; executes from zero page so an AUX read-modify-write can safely read and
; write the same physical byte without touching the cc65 software stack.
aux_xor_code:
        stz RAMWORKS
        stz RAMRDON
        stz RAMWRTON
        ldy #$00
        lda (AUX_XOR_PTR),y
        eor AUX_XOR_VALUE
        sta (AUX_XOR_PTR),y
        stz RAMRDOFF
        stz RAMWRTOFF
        rts
aux_xor_code_end:

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

; fastcall void aux_xor_byte(unsigned address, unsigned char value)
; A contains value and the address is on the cc65 software stack. Extract all
; parameters before the zero-page trampoline redirects RAM reads and writes.
_aux_xor_byte:
        sta AUX_XOR_VALUE
        jsr popax
        sta AUX_XOR_PTR
        stx AUX_XOR_PTR+1
        jsr AUX_XOR_CODE
        rts

; Clear AUX $2000-$5FFF while executing entirely without the cc65 software
; stack. RAMWRT redirects $0200-$BFFF, so an ordinary C pointer loop cannot
; safely update stack locals while this switch is active.
_aux_clear_video:
        ldx #(aux_xor_code_end-aux_xor_code)-1
@copy: lda aux_xor_code,x
        sta AUX_XOR_CODE,x
        dex
        bpl @copy
        stz RAMWORKS
        stz CLEAR_PTR
        lda #$20
        sta CLEAR_PTR+1
        stz RAMWRTON
        lda #$00
        ldy #$00
@byte: sta (CLEAR_PTR),y
        iny
        bne @byte
        inc CLEAR_PTR+1
        ldx CLEAR_PTR+1
        cpx #$60
        bne @byte
        stz RAMWRTOFF
        rts
