.setcpu "6502"
.include "zeropage.inc"
.export _ti_net_exchange, _ti_net_lock, _ti_net_unlock
.import _ti_net_parameters, _ti_net_tx_count, _ti_net_tx, _ti_net_tx_length
.import _ti_net_rx, _ti_net_rx_capacity, _ti_net_rx_length
.import _ti_net_rc
.export _ti_net_poisoned
.segment "BSS"
_ti_net_poisoned: .res 1
.export _ti_net_ready, _ti_net_rom_crc
.segment "BSS"
_ti_net_ready: .res 1
.segment "BSS"
saved_p: .res 1
saved_cx: .res 1
left: .res 2
segment: .res 1
vbl: .res 1
changes: .res 1
watchdog: .res 3
.ifdef MONO_NET_OVERLAY
.segment "NET"
.else
.segment "CODE"
.endif
_ti_net_lock:
    php
    pla
    sta saved_p
    sei
    cld
    lda $C015
    sta saved_cx
    sta $C006
    bit $CFFF
    bit $C700
    rts
_ti_net_unlock:
    bit $CFFF
    lda saved_cx
    bpl :+
    sta $C007
:   lda saved_p
    pha
    plp
    rts
; CRC-16/CCITT-FALSE over the selected slot ROM. Caller owns the C8 lock.
_ti_net_rom_crc:
    lda #$FF
    sta left
    sta left+1
    ldy #0
crc_byte:
    lda $C700,y
    eor left+1
    sta left+1
    ldx #8
crc_bit:
    asl left
    rol left+1
    bcc crc_next
    lda left
    eor #$21
    sta left
    lda left+1
    eor #$10
    sta left+1
crc_next:
    dex
    bne crc_bit
    iny
    bne crc_byte
    lda left
    ldx left+1
    rts
_ti_net_exchange:
    jsr _ti_net_lock
    ; READY remains set after a fully drained reply. EXECUTE clears it.
    ; A local timeout poisons the module; READY alone is not a busy flag.
submit:
    lda #0
    sta segment
next_segment:
    lda segment
    asl
    tax
    lda _ti_net_tx,x
    sta ptr1
    lda _ti_net_tx+1,x
    sta ptr1+1
    lda _ti_net_tx_length,x
    sta left
    lda _ti_net_tx_length+1,x
    sta left+1
    ldy #0
    ora left
    beq sent
send_byte:
    lda (ptr1),y
    sta $CFF0
    iny
    bne :+
    inc ptr1+1
:   lda left
    bne :+
    dec left+1
:   dec left
    lda left
    ora left+1
    bne send_byte
sent:
    inc segment
    lda segment
    cmp _ti_net_tx_count
    bcc next_segment
    lda #2
    sta $CFF1
    lda $C019
    and #$80
    sta vbl
    lda #0
    sta changes
    lda #0
    sta watchdog
    lda #0
    sta watchdog+1
    lda #0
    sta watchdog+2
wait_ready:
    lda $CFF1
    bmi receive
    inc watchdog
    bne :+
    inc watchdog+1
    bne :+
    inc watchdog+2
    bne :+
    jmp poison
:   lda $C019
    and #$80
    cmp vbl
    beq wait_ready
    sta vbl
    inc changes
    lda changes
    cmp #240
    bcc wait_ready
    jmp poison
receive:
    jsr pop
    sta _ti_net_rc
    bne finish
    lda _ti_net_parameters
    bne finish
    jsr pop
    sta _ti_net_rx_length
    sta left
    jsr pop
    sta _ti_net_rx_length+1
    sta left+1
    cmp _ti_net_rx_capacity+1
    bcc copy
    bne poison
    lda left
    cmp _ti_net_rx_capacity
    bcc copy
    bne poison
copy:
    lda _ti_net_rx
    sta ptr1
    lda _ti_net_rx+1
    sta ptr1+1
    ldy #0
    ldx left+1
    beq copy_tail
copy_page:
    lda $CFF0
    sta $CFF2
    sta (ptr1),y
    iny
    bne copy_page
    inc ptr1+1
    dex
    bne copy_page
copy_tail:
    ldx left
    beq finish
copy_byte:
    lda $CFF0
    sta $CFF2
    sta (ptr1),y
    iny
    dex
    bne copy_byte
finish:
    jmp _ti_net_unlock
poison:
    lda #1
    sta _ti_net_poisoned
    lda #$67
    sta _ti_net_rc
    jmp finish
pop:
    lda $CFF0
    sta $CFF2
    rts
