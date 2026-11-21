; ONEWWW for Appletini (firmware F1.3.9dev3 or later).
; The card gets each web page, lays it out and draws it. This program
; switches Super Hi-Res on and sends each key and the mouse to the card.
; ProDOS SYS file at $2000. 6502 code only: II+, //e and enhanced //e.

KBD       = $C000
KBDSTRB   = $C010
NEWVIDEO  = $C029       ; the card decodes this address on a II+ and //e
TEXTON    = $C051
COUT      = $FDED
HOME      = $FC58
MLI       = $BF00
SELECTOR  = $88         ; ONEWWW SmartPort selector, unit 0
OP_OPEN   = 1
OP_CLOSE  = 2
OP_KEY    = 3
OP_MOUSE  = 4

PTR       = $06         ; $Cn00 of the mouse card

; Mouse firmware: entry offsets are in $Cn12.. in this order.
M_SET     = 0
M_READ    = 2
M_POS     = 4
M_CLAMP   = 5
M_INIT    = 7
; Mouse screen holes, indexed by the slot number.
M_XL      = $0478
M_YL      = $04F8
M_XH      = $0578
M_YH      = $05F8
M_STATUS  = $0778

        .org $2000

start:  ldx #$FF
        txs
        lda $C701               ; SmartPort ROM in slot 7?
        cmp #$20
        bne absent
        lda $C705
        cmp #$03
        bne absent
        lda $C707
        bne absent
        lda $C7FF               ; SmartPort entry = $C700 + ($C7FF) + 3
        clc
        adc #3
        sta spvec
        jsr status              ; is the ONEWWW service there?
        bcs absent
        lda stat_buf
        cmp #'A'
        bne absent
        lda stat_buf+3
        cmp #'W'
        bne absent

        lda #OP_OPEN
        ldx #3
        jsr control
        bcs absent
        lda #$C1                ; Super Hi-Res on, colour
        sta NEWVIDEO
        jsr mouse_start
        jmp loop

absent: jsr HOME
        ldx #0
@next:  lda message,x
        beq @wait
        ora #$80
        jsr COUT
        inx
        bne @next
@wait:  lda KBD
        bpl @wait
        bit KBDSTRB
        jmp exit

loop:   lda KBD
        bpl @mouse
        bit KBDSTRB
        and #$7F
        sta ctl_arg
        lda #OP_KEY
        ldx #3
        jsr control
        jsr status              ; the card closes on the Q key
        bcs quit
        lda stat_buf+5
        beq quit
@mouse: lda mslot
        beq loop
        jsr mouse_read
        jmp loop

quit:   lda #OP_CLOSE
        ldx #3
        jsr control
        lda mslot
        beq @video
        lda #0                  ; mouse off
        sta marg
        lda #M_SET
        jsr mcall
@video: lda #$01                ; Super Hi-Res off
        sta NEWVIDEO
        bit TEXTON
        jsr HOME
exit:   jsr MLI
        .byte $65
        .word quit_list
        brk

; A = operation, X = payload length.
control:
        sta ctl_op
        stx ctl_buf
        jsr sp
        .byte $04
        .word ctl_list
        rts

status: jsr sp
        .byte $00
        .word stat_list
        rts

sp:     jmp (spvec)

; ---- Mouse ---------------------------------------------------------------

; Finds a mouse card in slots 6 to 1 and starts it. mslot = 0: no mouse.
mouse_start:
        lda #0
        sta PTR
        ldx #6
@slot:  txa
        ora #$C0
        sta PTR+1
        ldy #$0C
        lda (PTR),y
        cmp #$20
        bne @no
        ldy #$FB
        lda (PTR),y
        cmp #$D6
        beq @found
@no:    dex
        bne @slot
        rts                     ; mslot stays 0
@found: stx mslot
        txa
        asl
        asl
        asl
        asl
        sta mslot16
        lda #M_INIT
        jsr mcall
        lda #1                  ; passive mode
        sta marg
        lda #M_SET
        jsr mcall
        lda #0                  ; clamp X to 0..639
        sta M_XL
        sta M_XH
        lda #<639
        sta M_YL
        lda #>639
        sta M_YH
        lda #0
        sta marg
        lda #M_CLAMP
        jsr mcall
        lda #0                  ; clamp Y to 0..399
        sta M_XL
        sta M_XH
        lda #<399
        sta M_YL
        lda #>399
        sta M_YH
        lda #1
        sta marg
        lda #M_CLAMP
        jsr mcall
        ldx mslot               ; start at the centre
        lda #<320
        sta M_XL,x
        lda #>320
        sta M_XH,x
        lda #200
        sta M_YL,x
        lda #0
        sta M_YH,x
        lda #M_POS
        jmp mcall

; Reads the mouse. Sends its state when it changed.
mouse_read:
        lda #M_READ
        jsr mcall
        ldx mslot
        lda M_XL,x
        sta mnow
        lda M_XH,x
        sta mnow+1
        lda M_YL,x
        sta mnow+2
        lda M_YH,x
        sta mnow+3
        lda M_STATUS,x
        asl                     ; bit 7 (button down) to bit 0
        lda #0
        rol
        sta mnow+4
        ldx #4
@same:  lda mnow,x
        cmp ctl_arg,x
        bne @send
        dex
        bpl @same
        lda mlast               ; the key path also uses ctl_arg
        bne @done
@send:  ldx #4
@copy:  lda mnow,x
        sta ctl_arg,x
        dex
        bpl @copy
        lda #1
        sta mlast
        lda #OP_MOUSE
        ldx #7
        jsr control
@done:  rts

; Calls mouse firmware routine A with marg in A, interrupts off.
mcall:  clc
        adc #$12
        tay
        lda (PTR),y
        sta mvec
        lda PTR+1
        sta mvec+1
        php
        sei
        ldx PTR+1               ; $Cn
        ldy mslot16             ; $n0
        lda marg
        jsr @go
        plp
        rts
@go:    jmp (mvec)

; ---- Data ----------------------------------------------------------------

spvec:  .word $C700
mvec:   .word 0
mslot:  .byte 0
mslot16:
        .byte 0
marg:   .byte 0
mlast:  .byte 0
mnow:   .res 5
stat_list:
        .byte 3, 0
        .word stat_buf
        .byte SELECTOR, 0, 0, 0, 0
ctl_list:
        .byte 3, 0
        .word ctl_buf
        .byte SELECTOR, 0, 0, 0, 0
ctl_buf:
        .word 3                 ; payload length
        .byte 1                 ; version
ctl_op: .byte 0
ctl_arg:
        .res 5
quit_list:
        .byte 4, 0, 0, 0, 0, 0, 0
message:
        .byte "ONEWWW NEEDS APPLETINI FIRMWARE", $0D
        .byte "F1.3.9DEV3 OR LATER. PRESS A KEY.", 0
stat_buf:
        .res 32
