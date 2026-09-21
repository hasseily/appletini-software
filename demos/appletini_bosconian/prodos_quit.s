; Appletini Bosconian -- ProDOS QUIT helper (docs/DESIGN.md section 10).
; void prodos_quit(void): call the MLI QUIT function. main.c shuts video
; down first. Does not return.
        .setcpu "65C02"
        .export _prodos_quit

MLI = $BF00

.segment "CODE"
_prodos_quit:
        sta     $C004                   ; RAMWRT off
        sta     $C002                   ; RAMRD off
        jsr     MLI
        .byte   $65                     ; QUIT
        .word   quit_parms
        rts                             ; not reached

.segment "RODATA"
quit_parms:
        .byte   4                       ; parameter count
        .byte   0                       ; quit type
        .word   0                       ; reserved
        .byte   0                       ; reserved
        .word   0                       ; reserved
