.setcpu "65C02"

.export _ramworks_probe, _aux_clear_video, _aux_color_row

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

; fastcall void aux_color_row(unsigned address)
; Fill both AUX DHGR fields' 40 visible bytes for one scanline with Video-7's
; color selector. A/X contain the page-1 address. Keeping the loop in assembly
; avoids accessing cc65's software stack while AUX writes are enabled.
_aux_color_row:
        sta AUX_COLOR_PTR
        stx AUX_COLOR_PTR+1
        stz RAMWORKS
        stz RAMWRTON
        ldy #39
        lda #$80
@page_a:
        sta (AUX_COLOR_PTR),y
        dey
        bpl @page_a
        clc
        lda AUX_COLOR_PTR+1
        adc #$20
        sta AUX_COLOR_PTR+1
        ldy #39
        lda #$80
@page_b:
        sta (AUX_COLOR_PTR),y
        dey
        bpl @page_b
        stz RAMWRTOFF
        rts

; Clear AUX $2000-$5FFF while executing entirely without the cc65 software
; stack. RAMWRT redirects $0200-$BFFF, so an ordinary C pointer loop cannot
; safely update stack locals while this switch is active.
_aux_clear_video:
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
