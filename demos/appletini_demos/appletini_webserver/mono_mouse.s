; SPDX-License-Identifier: MIT
; Polled standard AppleMouse ROM driver. Protocol references:
; Apple II Mouse TN #1, plus Appletini software/mouse_card_slot2.a65.
; No shared ROM firmware or cc65 driver code is copied into this module.
.setcpu "6502"
.include "zeropage.inc"
.export _mono_mouse_init, _mono_mouse_poll, _mono_mouse_disable
.export _mono_mouse_available, _mono_mouse_x, _mono_mouse_y
.export _mono_mouse_down, _mono_mouse_pressed

SETMOUSE=$12
SERVEMOUSE=$13
READMOUSE=$14
POSMOUSE=$16
CLAMPMOUSE=$17
INITMOUSE=$19

.segment "BSS"
_mono_mouse_available: .res 1
_mono_mouse_x: .res 1
_mono_mouse_y: .res 1
_mono_mouse_down: .res 1
_mono_mouse_pressed: .res 1
mouse_slot: .res 1
mouse_page: .res 1
saved_cx: .res 1
saved_c3: .res 1
saved_zp: .res 2
host_holes: .res 8
card_holes: .res 8
clamp_holes: .res 4
events: .res 1
old_x: .res 1
old_y: .res 1
raw_x: .res 2

.segment "BROWSER"
id_offsets: .byte $05,$07,$0B,$0C,$FB
id_values: .byte $38,$18,$01,$20,$D6

; Each public call masks interrupts only while firmware/screen-hole state
; belongs to this driver. C8 is released on entry and exit. INITMOUSE needs
; the system ROM visible to detect an Apple //e; the caller's LC bank-2
; read-only mapping is restored before returning to the graphics backend.
lock:
    lda $C015
    sta saved_cx
    lda $C017
    sta saved_c3
    lda $06
    sta saved_zp
    lda $07
    sta saved_zp+1
    sta $C006
    sta $C00B
    bit $CFFF
    bit $C082
    rts
unlock:
    bit $CFFF
    lda saved_c3
    bmi :+
    sta $C00A
    jmp :++
:   sta $C00B
:   lda saved_cx
    bmi :+
    sta $C006
    jmp :++
:   sta $C007
:   lda saved_zp
    sta $06
    lda saved_zp+1
    sta $07
    bit $C080
    rts

; Swap all eight slot-owned screen holes so firmware state cannot overwrite
; the caller's text page. Caller bytes are unchanged at every public return.
hole_pointer:
    lda mouse_slot
    clc
    adc #$78
    sta ptr1
    lda #4
    sta ptr1+1
    ldx #0
    ldy #0
    rts
next_hole:
    lda ptr1
    clc
    adc #$80
    sta ptr1
    bcc :+
    inc ptr1+1
:   inx
    cpx #8
    rts
holes_in:
    jsr hole_pointer
:   lda (ptr1),y
    sta host_holes,x
    lda card_holes,x
    sta (ptr1),y
    jsr next_hole
    bne :-
    rts
holes_out:
    jsr hole_pointer
:   lda (ptr1),y
    sta card_holes,x
    lda host_holes,x
    sta (ptr1),y
    jsr next_hole
    bne :-
    rts

; A=argument, X=ROM vector-table byte offset. Repatch on every call so
; restoring MONO.WEB after an image overlay needs no mouse reinitialization.
firmware:
    pha
    lda mouse_page
    sta lookup+2
    sta jump+2
lookup:
    lda $FF00,x
    sta jump+1
    lda mouse_slot
    asl a
    asl a
    asl a
    asl a
    tay
    ldx mouse_page
    pla
jump:
    jmp $FFFF

_mono_mouse_init:
    php
    sei
    lda #0
    sta _mono_mouse_available
    sta _mono_mouse_down
    sta _mono_mouse_pressed
    ldx #7
:   sta card_holes,x
    dex
    bpl :-
    jsr lock
    lda #0
    sta ptr1
    lda #$C1
    sta ptr1+1
probe_slot:
    ldx #4
probe_id:
    ldy id_offsets,x
    lda (ptr1),y
    cmp id_values,x
    bne next_slot
    dex
    bpl probe_id
    ; Reject invalid vectors before executing any card code.
    ldy #$12
probe_vectors:
    lda (ptr1),y
    cmp #$1B
    bcc next_slot
    cmp #$FB
    bcs next_slot
    iny
    cpy #$1A
    bne probe_vectors
    lda ptr1+1
    sta mouse_page
    and #$0F
    sta mouse_slot
    jmp found
next_slot:
    inc ptr1+1
    lda ptr1+1
    cmp #$C8
    bne probe_slot
    jsr unlock
    plp
    lda #0
    tax
    rts
found:
    jsr holes_in
    lda #0
    ldx #SETMOUSE
    jsr firmware
    ldx #SERVEMOUSE
    jsr firmware             ; release an IRQ left by the previous program
    ldx #INITMOUSE
    jsr firmware
    ; Clamp interchange uses slot-0 absolute holes, not the slot's holes.
    lda $0478
    sta clamp_holes
    lda $04F8
    sta clamp_holes+1
    lda $0578
    sta clamp_holes+2
    lda $05F8
    sta clamp_holes+3
    lda #0
    sta $0478
    sta $0578
    lda #$2F                 ; 559 = $022F
    sta $04F8
    lda #2
    sta $05F8
    lda #0
    ldx #CLAMPMOUSE
    jsr firmware
    lda #$7F                 ; 383 = $017F
    sta $04F8
    lda #1
    sta $05F8
    ldx #CLAMPMOUSE
    jsr firmware
    lda clamp_holes
    sta $0478
    lda clamp_holes+1
    sta $04F8
    lda clamp_holes+2
    sta $0578
    lda clamp_holes+3
    sta $05F8
    ldx mouse_slot
    lda #24                  ; x=280 -> cell 40
    sta $0478,x
    lda #1
    sta $0578,x
    lda #192                 ; y=192 -> cell 24
    sta $04F8,x
    lda #0
    sta $05F8,x
    ldx #POSMOUSE
    jsr firmware
    lda #1
    ldx #SETMOUSE
    jsr firmware             ; mouse enabled, every IRQ source disabled
    ldx #READMOUSE
    jsr firmware
    jsr update
    lda #0
    sta _mono_mouse_pressed
    jsr holes_out
    lda #1
    sta _mono_mouse_available
    jsr unlock
    plp
    lda #1
    ldx #0
    rts

_mono_mouse_poll:
    lda #0
    sta _mono_mouse_pressed
    lda _mono_mouse_available
    bne :+
    tax
    rts
:   php
    sei
    jsr lock
    jsr holes_in
    ldx #READMOUSE
    jsr firmware
    jsr update
    jsr holes_out
    jsr unlock
    plp
    lda events
    ldx #0
    rts

update:
    lda _mono_mouse_x
    sta old_x
    lda _mono_mouse_y
    sta old_y
    lda #0
    sta events
    ldx mouse_slot
    lda $0478,x
    sta raw_x
    lda $0578,x
    sta raw_x+1
    ; Defensive saturation also covers a card that ignores its clamp.
    cmp #3
    bcs x_max
    cmp #2
    bne x_divide
    lda raw_x
    cmp #$30
    bcs x_max
x_divide:
    ldy #0
x_loop:
    lda raw_x+1
    bne subtract
    lda raw_x
    cmp #7
    bcc x_done
subtract:
    lda raw_x
    sec
    sbc #7
    sta raw_x
    lda raw_x+1
    sbc #0
    sta raw_x+1
    iny
    bne x_loop
x_max:
    ldy #79
x_done:
    sty _mono_mouse_x
    lda $05F8,x
    cmp #2
    bcs y_max
    cmp #1
    bne y_divide
    lda $04F8,x
    cmp #$80
    bcs y_max
y_divide:
    lda $05F8,x
    lsr a
    lda $04F8,x
    ror a
    lsr a
    lsr a
    jmp y_done
y_max:
    lda #47
y_done:
    sta _mono_mouse_y
    cmp old_y
    bne moved
    lda _mono_mouse_x
    cmp old_x
    beq buttons
moved:
    lda #1
    sta events
buttons:
    lda $0778,x
    asl a
    lda #0
    rol a
    cmp _mono_mouse_down
    beq update_done
    sta _mono_mouse_down
    cmp #0
    beq released
    sta _mono_mouse_pressed
    lda events
    ora #2
    bne store_events
released:
    lda events
    ora #4
store_events:
    sta events
update_done:
    rts

_mono_mouse_disable:
    lda _mono_mouse_available
    beq disabled
    php
    sei
    jsr lock
    jsr holes_in
    lda #0
    ldx #SETMOUSE
    jsr firmware
    ldx #SERVEMOUSE
    jsr firmware
    ldx #READMOUSE
    jsr firmware
    jsr holes_out
    jsr unlock
    plp
disabled:
    lda #0
    sta _mono_mouse_available
    sta _mono_mouse_down
    sta _mono_mouse_pressed
    rts
