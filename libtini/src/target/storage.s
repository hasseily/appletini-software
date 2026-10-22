; Private synchronous ProDOS MLI adapter, default cc65 ABI, no C arguments.
; The C owner validates buffers and restores AUX0 before calling the OS.
.setcpu "65C02"
.export _ti_mli_call
.import _ti_mli_command, _ti_mli_params
.segment "CODE"
_ti_mli_call:
        lda _ti_mli_command
        sta command
        lda _ti_mli_params
        sta parameters
        lda _ti_mli_params+1
        sta parameters+1
        ; ProDOS uses its legacy random-number bytes; keep application state.
        lda $4E
        pha
        lda $4F
        pha
        jsr $BF00
command: .byte 0
parameters: .word 0
        tax
        pla
        sta $4F
        pla
        sta $4E
        txa
        ldx #0
        rts
