; SPDX-License-Identifier: MIT
.setcpu "6502"
.include "zeropage.inc"
.export _mono_hw_init, _mono_hw_begin, _mono_hw_commit, _mono_hw_end
.export _mono_hw_clear, _mono_hw_row, _mono_hw_read, _mono_hw_write
.import _mono_address, _mono_source, _mono_value
.import _mono_count, _mono_parity, _mono_bank
.import _mono_destination, _mono_length
.export _mono_hw_read_block, _mono_hw_write_block

.segment "LC"

; The launch contract owns base RamWorks AUX, MAIN RD/WR, and ALTZP off.
; Only individual transfers mask interrupts; drawing keeps the caller's
; interrupt policy. C073 always returns to bank 0 before any transfer returns.
_mono_hw_init:
    php
    sei
    lda #0
    sta $C000
    sta $C002
    sta $C004
    sta $C008
    sta $C073
    sta $087C             ; disarm any prior lores load-hold marker
    lda #1
    sta $C029
    bit $C050
    bit $C052
    bit $C054
    bit $C057
    sta $C07E
    ; Video-7 MONO560: clock !80COL=1 on both AN3 rising edges,
    ; then turn 80COL on and finish with DHGR enabled.
    sta $C00C
    bit $C05E
    bit $C05F
    bit $C05E
    bit $C05F
    sta $C00D
    bit $C05E
    plp
    jmp _mono_hw_begin

_mono_hw_begin:
    lda #$C1
    sta $4078
    lda #$B2
    sta $4079
    lda #$CC
    sta $407A
    lda #$E9
    sta $407B
    lda #$FF
    sta $407C
    sta $087C             ; both marker holes are reserved by the SYS
    rts

_mono_hw_commit:
    lda #1
    sta $407C
    rts

_mono_hw_end:
    php
    sei
    lda #0
    sta $C000
    sta $C002
    sta $C004
    sta $C073
    sta $407C
    ; Reset Video-7 mode to normal before restoring text.
    sta $C00D
    bit $C052
    bit $C05E
    bit $C05F
    bit $C05E
    bit $C05F
    bit $C05E
    bit $C05F
    bit $C054
    bit $C056
    bit $C051
    lda #1
    sta $C029
    plp
    rts

; Clear both 16 KiB display banks. Preserve the five-byte MAIN A2Li
; marker while clearing so the previous complete frame remains held.
_mono_hw_clear:
    php
    sei
    lda #0
    sta $C000
    sta $C002
    sta $C004
    sta $C073
    sta ptr1
    lda #$20
    sta ptr1+1
    ldy #0
clear_main:
    lda ptr1+1
    cmp #$40
    bne clear_store
    cpy #$78
    bcc clear_store
    cpy #$7D
    bcc clear_next
clear_store:
    lda _mono_value
    sta (ptr1),y
clear_next:
    iny
    bne clear_main
    inc ptr1+1
    lda ptr1+1
    cmp #$60
    bne clear_main
    lda #$20
    sta ptr1+1
    lda _mono_value
    sta $C005
clear_aux:
    sta (ptr1),y
    iny
    bne clear_aux
    inc ptr1+1
    ldx ptr1+1
    cpx #$60
    bne clear_aux
    sta $C004
    plp
    rts

_mono_hw_row:
    php
    sei
    lda #0
    sta $C000
    sta $C004
    sta $C073
    lda _mono_address
    sta ptr1
    lda _mono_address+1
    sta ptr1+1
    lda _mono_source
    sta ptr2
    lda _mono_source+1
    sta ptr2+1
    ldy #0
row_loop:
    lda (ptr2),y
    and #$7F
    ldx _mono_parity
    bne row_main
    sta $C005
    sta (ptr1),y
    sta $C004
    jmp row_toggle
row_main:
    sta (ptr1),y
    inc ptr1
    bne row_toggle
    inc ptr1+1
row_toggle:
    lda _mono_parity
    eor #1
    sta _mono_parity
    inc ptr2
    bne row_count
    inc ptr2+1
row_count:
    dec _mono_count
    bne row_loop
    plp
    rts

_mono_hw_write:
    php
    sei
    lda _mono_address
    sta ptr1
    lda _mono_address+1
    sta ptr1+1
    lda _mono_bank
    sta $C073
    lda _mono_value
    ldy #0
    sta $C005
    sta (ptr1),y
    sta $C004
    lda #0
    sta $C073
    plp
    rts

; Graphics routines execute in MAIN language-card bank 2, loaded by the
; stock cc65 CRT. RAMRD therefore cannot bank out instructions. Parameters
; are loaded before selecting AUX reads; the helper restores MAIN reads.
_mono_hw_read:
    php
    sei
    lda _mono_address
    sta ptr1
    lda _mono_address+1
    sta ptr1+1
    lda _mono_bank
    sta $C073
    ldy #0
    bit $C080
    jmp aux_read_lc

; Block moves use ZP counters so RAMRD/RAMWRT can remain selected for the
; entire operation. MAIN instruction reads are safe during AUX writes.
block_setup:
    lda _mono_address
    sta ptr1
    lda _mono_address+1
    sta ptr1+1
    lda _mono_length
    sta ptr3
    lda _mono_length+1
    sta ptr3+1
    lda _mono_bank
    sta $C073
    ldy #0
    rts
_mono_hw_write_block:
    php
    sei
    jsr block_setup
    lda _mono_source
    sta ptr2
    lda _mono_source+1
    sta ptr2+1
    sta $C005
write_block_loop:
    lda (ptr2),y
    sta (ptr1),y
    inc ptr1
    bne :+
    inc ptr1+1
:   inc ptr2
    bne :+
    inc ptr2+1
:   lda ptr3
    bne :+
    dec ptr3+1
:   dec ptr3
    lda ptr3
    ora ptr3+1
    bne write_block_loop
    sta $C004
    sta $C073
    plp
    rts
_mono_hw_read_block:
    php
    sei
    jsr block_setup
    lda _mono_destination
    sta ptr2
    lda _mono_destination+1
    sta ptr2+1
    bit $C080
    jmp aux_read_block_lc
.segment "LC"
aux_read_lc:
    sta $C003
    lda (ptr1),y
    sta $C002
    tax
    lda #0
    sta $C073
    txa
    ldx #0
    plp
    rts
aux_read_block_lc:
    sta $C003
read_block_loop:
    lda (ptr1),y
    sta (ptr2),y
    inc ptr1
    bne :+
    inc ptr1+1
:   inc ptr2
    bne :+
    inc ptr2+1
:   lda ptr3
    bne :+
    dec ptr3+1
:   dec ptr3
    lda ptr3
    ora ptr3+1
    bne read_block_loop
    sta $C002
    sta $C073
    ldx #0
    plp
    rts
