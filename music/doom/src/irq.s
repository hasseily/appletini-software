; The interrupt entry and the card's vectors.
;
; The single interrupt handler:
; timer 1 of the Phasor's VIA-B, free-running, raises an IRQ once a video
; frame (music.s, timer_on: every 20,280 bus cycles on PAL, 17,030 on
; NTSC, the rate of the VBL). The handler reads VIA-B's IFR: with timer
; 1's flag (bit 6) set, it clears the flag by writing bit 6 back to IFR
; (in native mode a read of T1C-L would also step the counter once more),
; counts the interrupt (irq_count, the music's clock) and runs the player;
; with the flag clear the entry is spurious and it returns. It lives in
; the main language card with its vector at $FFFE, and touches only the
; zero page, the stack, the card and the Phasor, so RAMRD and RAMWRT may
; be anything when it comes. A BRK stops at snd_crash.

        .setcpu "65C02"
        .include "sound.inc"

        .import snd_tick
        .export snd_irq, snd_crash, irq_count

        .segment "SNDZP": zeropage
irq_count:      .res 2          ; timer interrupts since the start

        .segment "SNDCODE"

snd_irq:
        pha
        phx
        phy
        tsx
        lda     $0104,x                 ; the pushed P
        and     #$10
        bne     snd_crash               ; a BRK
        lda     VIA_B_IFR               ; the cause, before the ack
        and     #IFR_T1
        beq     @done                   ; not the timer: spurious
        sta     VIA_B_IFR               ; the ack: timer 1's flag cleared
        inc     irq_count
        bne     :+
        inc     irq_count+1
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
        .word   snd_nmi, snd_crash, snd_irq
