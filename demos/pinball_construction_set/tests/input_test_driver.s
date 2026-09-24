.setcpu "65C02"

; Test driver for tests/test_input.py: one caller per entry point of
; src/input.s. Python sets `param`, sets PC to a t_* label and runs until
; PC reaches `halt`. t_getkey loads X and Y with marker values and stores
; A, X and Y in `result` so the test can see the registers it must keep.

.import input_init, input_frame, input_getkey, input_set_cursor

.export param, result, halt
.export t_init, t_frame, t_getkey, t_set_cursor

.segment "BSS"
param:          .res 3
result:         .res 3

.segment "CODE"

halt:
        jmp     halt

t_init:
        jsr     input_init
        jmp     halt

t_frame:
        jsr     input_frame
        jmp     halt

t_getkey:
        ldx     #$5A
        ldy     #$A5
        jsr     input_getkey
        sta     result
        stx     result+1
        sty     result+2
        jmp     halt

t_set_cursor:
        lda     param
        ldx     param+1
        ldy     param+2
        jsr     input_set_cursor
        jmp     halt
