; snd_probe: how many AY chips the card in slot 4 has, so that the boot
; code can pick the player's layout (docs/research/native-sound.md 5,
; item 2: "the probe must find 2 chips and select mb6").
;
; It asks for the Phasor's native mode ($C0C8, then $C0C5), resets the
; chips behind VIA-A, writes register 0 of chip 0 ($55), then register 0
; of chip 1 ($AA), and reads register 0 of chip 0 back (The Bilestoad's
; method, bilestoad/src/sound.s). A Phasor in native mode has two chips
; behind each VIA, so chip 0 keeps $55: 4 chips, native12. A Mockingboard,
; or the Appletini's Phasor locked to Mockingboard mode (its audio_control
; bit 26, mockingboard.sv:38-41), ignores the mode switch and the chip
; selects, so the second write lands on chip 0: $AA, 2 chips, mb6.
;
; Returns A = the layout's id (tables.py: 0 native12, 1 mb6). The chips
; behind VIA-A are left reset, the card in the mode it accepted; snd_init
; then sets the card up for the layout. Main loop, once, before snd_init.
; It is boot code, not part of the player in the card.

        .setcpu "65C02"
        .include "sound.inc"

        .export snd_probe

PROBE_NATIVE12  = 0
PROBE_MB6       = 1

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
        lda     #PROBE_NATIVE12
        cpx     #$55
        beq     :+
        lda     #PROBE_MB6
:       rts

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
