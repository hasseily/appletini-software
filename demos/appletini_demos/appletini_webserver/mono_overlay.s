; SPDX-License-Identifier: MIT
; Resident overlay loader. ProDOS rejects file buffers in text-screen RAM.
; Borrow $1C00-$1FFF from the inactive codec workspace while a file is open.
; A decoder initializes its workspace after its overlay has loaded, and it
; has finished before MONO.WEB is restored. No file stays open during decode.
.setcpu "6502"
.include "zeropage.inc"
.export _mono_overlay_load, _mono_prefix_init
.export _mono_overlay_error, _mono_overlay_stage
.import _mono_overlay_expected
IOBUF = $1C00

.segment "BSS"
pathname: .res 16
extra: .res 1
result: .res 1
_mono_overlay_error: .res 1
_mono_overlay_stage: .res 1

.segment "DATA"
open_params:
    .byte 3
    .word pathname
    .word IOBUF
    .byte 0
read_params:
    .byte 4,0
    .word $8B00,$2C00,0
extra_params:
    .byte 4,0
    .word extra,1,0
close_params:
    .byte 1,0
prefix_params:
    .byte 1
    .word IOBUF
online_params:
    .byte 2,0
    .word IOBUF+$50

.segment "CODE"
_mono_prefix_init:
    lda #0
    sta IOBUF
    jsr $BF00
    .byte $C7
    .word prefix_params
    bcs prefix_done
    lda IOBUF
    bne prefix_done
    lda $BF30
    sta online_params+1
    jsr $BF00
    .byte $C5
    .word online_params
    bcs prefix_done
    lda IOBUF+$50
    and #$0F
    beq prefix_done
    sta extra
    clc
    adc #1
    sta IOBUF
    lda #'/'
    sta IOBUF+1
    ldx #0
prefix_copy:
    inx
    lda IOBUF+$50,x
    sta IOBUF+1,x
    cpx extra
    bne prefix_copy
    jsr $BF00
    .byte $C6
    .word prefix_params
prefix_done:
    rts

_mono_overlay_load:
    sta ptr1
    stx ptr1+1
    lda #0
    sta result
    sta pathname
    sta _mono_overlay_error
    lda #'O'
    sta _mono_overlay_stage
    ldy #0
name_loop:
    lda (ptr1),y
    beq name_done
    cpy #15
    bcc :+
    jmp fail
:
    iny
    sta pathname,y
    jmp name_loop
name_done:
    cpy #0
    bne :+
    jmp fail
:
    sty pathname
    jsr $BF00
    .byte $C8
    .word open_params
    bcc :+
    sta _mono_overlay_error
    jmp fail
:
    lda open_params+5
    sta read_params+1
    sta extra_params+1
    sta close_params+1
    lda #0
    sta read_params+6
    sta read_params+7
    lda #'R'
    sta _mono_overlay_stage
    jsr $BF00
    .byte $CA
    .word read_params
    bcc read_ok
    cmp #$4C
    beq read_ok
    sta _mono_overlay_error
    jmp close
read_ok:
    lda #'S'
    sta _mono_overlay_stage
    lda read_params+6
    ora read_params+7
    beq size_error
    lda read_params+6
    cmp _mono_overlay_expected
    bne size_error
    lda read_params+7
    cmp _mono_overlay_expected+1
    bne size_error
    lda read_params+7
    cmp #$2C
    bne complete
    lda read_params+6
    bne size_error
    lda #0
    sta extra_params+6
    sta extra_params+7
    jsr $BF00
    .byte $CA
    .word extra_params
    bcc extra_ok
    cmp #$4C
    beq extra_ok
    sta _mono_overlay_error
    lda #'R'
    sta _mono_overlay_stage
    bne close
extra_ok:
    lda extra_params+6
    ora extra_params+7
    bne size_error
complete:
    lda #1
    sta result
    lda #'C'
    sta _mono_overlay_stage
    bne close
size_error:
    lda #$FF
    sta _mono_overlay_error
close:
    jsr $BF00
    .byte $CC
    .word close_params
    bcc :+
    sta _mono_overlay_error
    lda #'C'
    sta _mono_overlay_stage
    jmp fail
:
    lda result
    ldx #0
    rts
fail:
    lda #0
    tax
    rts
