; snd_probe: can the card in slot 4 play the music? The music needs the
; Phasor's native mode, 4 AY chips (the layout native12); a card that
; cannot switch to it has no music: the game runs without music and says
; so (there is no 6-voice fallback).
;
; It asks for the Phasor's native mode ($C0C8, then $C0C5), resets the
; chips behind VIA-A, writes register 0 of chip 0 ($55), then register 0
; of chip 1 ($AA), and reads register 0 of chip 0 back (The Bilestoad's
; method, bilestoad/src/sound.s). A Phasor in native mode has two chips
; behind each VIA, so chip 0 keeps $55: 4 chips, music. A Mockingboard,
; or the Appletini's Phasor locked to Mockingboard mode (its audio_control
; bit 26, mockingboard.sv:38-41), ignores the mode switch and the chip
; selects, so the second write lands on chip 0: $AA, 2 chips, no music.
;
; Returns carry clear and A = SND_MUSIC (sound.inc) when the card is in
; native mode: the boot code calls snd_init, and the game may call
; snd_start. Otherwise carry set and A = SND_NO_MUSIC: the game says it
; has no music and never calls snd_start (nor snd_refill or snd_stop, which
; would do nothing); it still calls snd_init once, which leaves the player
; stopped, so the VBL interrupt counts its VBLs and snd_tick returns at
; once. The chips behind VIA-A are left reset, the card in the mode it
; accepted. Main loop, once, before snd_init. It is boot code, not part of
; the player in the card.

        .setcpu "65C02"
        .include "sound.inc"

        .export snd_probe

        .segment "SNDBOOT"

snd_probe:
        bit     PHASOR_MB
        bit     PHASOR_NATIVE
        lda     #$FF
        sta     VIA_A_DDRA
        lda     #$1F
        sta     VIA_A_DDRB
        stz     VIA_A_ORB               ; reset both chips of VIA-A
        lda     #ORB_IDLE0
        sta     VIA_A_ORB
        ldx     #$55                    ; chip 0, R0 = $55
        lda     #ORB_LATCH0
        ldy     #ORB_WRITE0
        jsr     probe_write
        ldx     #$AA                    ; chip 1, R0 = $AA
        lda     #ORB_LATCH1
        ldy     #ORB_WRITE1
        jsr     probe_write
        stz     VIA_A_ORA_NH            ; chip 0: latch R0, then read it
        lda     #ORB_LATCH0
        sta     VIA_A_ORB
        lda     #ORB_IDLE0
        sta     VIA_A_ORB
        stz     VIA_A_DDRA
        lda     #ORB_READ0
        sta     VIA_A_ORB
        ldx     VIA_A_ORA
        lda     #ORB_IDLE0
        sta     VIA_A_ORB
        lda     #$FF
        sta     VIA_A_DDRA
        stz     VIA_A_ORB               ; the chips reset again
        lda     #ORB_IDLE0
        sta     VIA_A_ORB
        cpx     #$55
        bne     @none
        lda     #SND_MUSIC              ; chip 0 kept $55: 4 chips
        clc
        rts
@none:  lda     #SND_NO_MUSIC           ; $AA reached chip 0: 2 chips
        sec
        rts

; register 0 of a chip of VIA-A = X; A = its latch ORB, Y = its write ORB
probe_write:
        stz     VIA_A_ORA_NH
        sta     VIA_A_ORB
        lda     #ORB_IDLE0
        sta     VIA_A_ORB
        stx     VIA_A_ORA_NH
        sty     VIA_A_ORB
        sta     VIA_A_ORB
        rts
