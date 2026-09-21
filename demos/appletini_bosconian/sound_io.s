.setcpu "65C02"

; Appletini Bosconian -- slot 4 Phasor (Mockingboard mode) I/O primitives.
;
; Each routine does exactly one fixed sequence of $C4xx accesses and nothing
; else. All of them are called from sound.c, and only from sound_init() or
; sound_update(), so every $C4xx access of the game happens in one burst per
; frame (any $C4xx access slows the virtual TransWarp to 1 MHz for a while).
;
; AY data goes through the "ORA no handshake" register ($C40F / $C48F). A
; write to plain ORA ($C401 / $C481) would clear the VIA CA1 flag, and the
; SSI-263 reports the end of a phoneme through CA1.
;
; cc65 fastcall: the last argument arrives in A, earlier ones are popped from
; the software stack with popa. u8 results return in A with X = 0.

.include "bosco.inc"

.import popa
.export _ay_write_a, _ay_write_b, _ssi_write
.export _via_a_prep, _via_b_prep, _via_a_ddr, _via_b_ddr

VIA_A_ORA_NH = $C40F
VIA_B_ORA_NH = $C48F

ZP_VAL = ZP_SOUND       ; $50: value being written

.segment "CODE"

; void __fastcall__ ay_write_a(u8 reg, u8 val)
; ORA=reg; ORB=7; ORB=4; ORA=val; ORB=6; ORB=4   (6 bus accesses)
_ay_write_a:
        sta     ZP_VAL
        jsr     popa
        sta     VIA_A_ORA_NH
        lda     #7
        sta     VIA_A_ORB
        lda     #4
        sta     VIA_A_ORB
        lda     ZP_VAL
        sta     VIA_A_ORA_NH
        lda     #6
        sta     VIA_A_ORB
        lda     #4
        sta     VIA_A_ORB
        rts

; void __fastcall__ ay_write_b(u8 reg, u8 val)
_ay_write_b:
        sta     ZP_VAL
        jsr     popa
        sta     VIA_B_ORA_NH
        lda     #7
        sta     VIA_B_ORB
        lda     #4
        sta     VIA_B_ORB
        lda     ZP_VAL
        sta     VIA_B_ORA_NH
        lda     #6
        sta     VIA_B_ORB
        lda     #4
        sta     VIA_B_ORB
        rts

; void __fastcall__ ssi_write(u8 reg, u8 val)
; reg is the SSI-263 register offset 0..4 from $C440 (DUR, INF, RATE, CTL, FILT).
; The write also lands in the VIA-A register with the same offset (ORB, ORA,
; DDRB, DDRA, T1C-L): the caller must restore VIA-A with via_a_ddr() and
; resend every AY-A register.
_ssi_write:
        sta     ZP_VAL
        jsr     popa
        and     #$07
        tax
        lda     ZP_VAL
        sta     SSI_DUR,x
        rts

; void via_a_prep(void)  -- IER=$7F (all interrupts off), PCR=0, IFR=$7F.
; Called before the SSI-263 setup, while the VIA-A port pins are still inputs.
_via_a_prep:
        lda     #$7F
        sta     VIA_A_IER
        stz     VIA_A_PCR
        sta     VIA_A_IFR
        rts

; void via_b_prep(void)
_via_b_prep:
        lda     #$7F
        sta     VIA_B_IER
        stz     VIA_B_PCR
        sta     VIA_B_IFR
        rts

; void via_a_ddr(void) -- DDRA=$FF, DDRB=$07, ORB=0 then ORB=4.
; ORB bit 2 is the AY reset line (low = reset), bits 1-0 are BDIR/BC1.
; The ORB 0 -> 4 pulse resets the AY: every register reads 0 afterwards.
_via_a_ddr:
        lda     #$FF
        sta     VIA_A_DDRA
        lda     #$07
        sta     VIA_A_DDRB
        stz     VIA_A_ORB
        lda     #$04
        sta     VIA_A_ORB
        rts

; void via_b_ddr(void)
_via_b_ddr:
        lda     #$FF
        sta     VIA_B_DDRA
        lda     #$07
        sta     VIA_B_DDRB
        stz     VIA_B_ORB
        lda     #$04
        sta     VIA_B_ORB
        rts
