; The VBL interrupt entry and the card's vectors (native-sound.md 4.2-4.3,
; NATIVE.md 10, "IRQ").
;
; The platform's single interrupt handler, as far as the music needs it:
; the mouse card in slot 2 raises an IRQ at the start of every vertical
; blanking (mode bit 3); the handler reads the card's status ($C0A0),
; acknowledges it ($C0AF), counts the VBL (vbl_count, the port's clock)
; and runs the player. It lives in the main language card with its vector
; at $FFFE, and touches only the zero page, the stack, the card and I/O,
; so RAMRD, RAMWRT and $C073 may be anything when it comes. A BRK stops
; at snd_crash.

        .setcpu "65C02"
        .include "sound.inc"

        .import snd_tick
        .export snd_vbl, snd_crash, vbl_count

        .segment "SNDZP": zeropage
vbl_count:      .res 2          ; VBL interrupts since the start

        .segment "SNDCODE"

snd_vbl:
        pha
        phx
        phy
        tsx
        lda     $0104,x                 ; the pushed P
        and     #$10
        bne     snd_crash               ; a BRK
        ldx     MOUSE_STATUS            ; the cause, read before the ack
        lda     #3
        sta     MOUSE_ACK
        txa
        and     #MOUSE_VBL
        beq     @done
        inc     vbl_count
        bne     :+
        inc     vbl_count+1
:       jsr     snd_tick
@done:  ply
        plx
        pla
        rti

snd_crash:
        bra     snd_crash

snd_nmi:
        rti

        .segment "VECTORS"
        .word   snd_nmi, snd_crash, snd_vbl
