.setcpu "65C02"

; Appletini Bosconian -- slot 4 Phasor I/O primitives.
;
; The card starts in Mockingboard mode. sound_init() switches it to Phasor
; native mode ($C0C8 then $C0C5, as appletini-one/hdl/apple/mockingboard.sv
; decodes it) and probes for the second AY behind VIA-A. Rules that hold in
; both modes: VIA-A answers at $C41x and VIA-B at $C48x. In native mode ORB
; bit 4 selects the first AY of a VIA and bit 3 the second, both active low,
; and the PSG clock is doubled (sound.c doubles every period). A plain
; Mockingboard ignores the mode switch and the select bits, so the probe
; sees its second-chip write land on the first chip and reports two chips.
; This follows the Bilestoad SHR port's driver.
;
; Each routine does one fixed sequence of $C4xx accesses and nothing else.
; All of them are called from sound.c, and only from sound_init() or
; sound_update(), so every $C4xx access of the game happens in one burst per
; frame (any $C4xx access slows the virtual TransWarp to 1 MHz for a while).
;
; AY data goes through the "ORA no handshake" register ($C41F / $C48F). A
; write to plain ORA would clear the VIA CA1 flag, and the SSI-263 reports
; the end of a phoneme through CA1.
;
; cc65 fastcall: the last argument arrives in A, earlier ones are popped from
; the software stack with popa. u8 results return in A with X = 0.

.include "bosco.inc"

.import popa
.export _phasor_probe, _ay_write, _ssi_write
.export _via_a_prep, _via_b_prep, _via_a_ddr, _via_b_ddr

ZP_VAL = ZP_SOUND       ; $50: value being written
ZP_REG = ZP_SOUND+1     ; $51: AY register

.segment "RODATA"
; ORB values by chip select: first AY of a VIA, second AY of a VIA
sel_latch:      .byte $0F, $17          ; BDIR=1 BC1=1: latch the address
sel_write:      .byte $0E, $16          ; BDIR=1 BC1=0: write data
sel_idle:       .byte $0C, $14          ; inactive, reset line high

.segment "CODE"

; u8 phasor_probe(void)
; Select Phasor native mode, then write register 0 of chip 0 ($55) and of
; chip 1 ($AA, the second AY behind VIA-A) and read chip 0 back. $AA means
; the second write landed on the first chip: a Mockingboard, two chips.
; Returns 1 for four chips (native mode), 0 for two. Call after via_a_ddr.
_phasor_probe:
        bit     PHASOR_MB
        bit     PHASOR_NATIVE
        ; chip 0, register 0 = $55
        stz     VIA_A_ORA_NH
        lda     #$0F
        sta     VIA_A_ORB
        lda     #$0C
        sta     VIA_A_ORB
        lda     #$55
        sta     VIA_A_ORA_NH
        lda     #$0E
        sta     VIA_A_ORB
        lda     #$0C
        sta     VIA_A_ORB
        ; chip 1, register 0 = $AA
        stz     VIA_A_ORA_NH
        lda     #$17
        sta     VIA_A_ORB
        lda     #$14
        sta     VIA_A_ORB
        lda     #$AA
        sta     VIA_A_ORA_NH
        lda     #$16
        sta     VIA_A_ORB
        lda     #$14
        sta     VIA_A_ORB
        ; read chip 0, register 0: port A as input, BDIR=0 BC1=1
        stz     VIA_A_ORA_NH
        lda     #$0F
        sta     VIA_A_ORB
        lda     #$0C
        sta     VIA_A_ORB
        stz     VIA_A_DDRA
        lda     #$0D
        sta     VIA_A_ORB
        lda     VIA_A_ORA_NH
        pha
        lda     #$0C
        sta     VIA_A_ORB
        lda     #$FF
        sta     VIA_A_DDRA
        pla
        ldx     #0
        cmp     #$AA
        beq     @two
        lda     #1
        rts
@two:   lda     #0
        rts

; void __fastcall__ ay_write(u8 chip, u8 reg, u8 val)
; chip 0/1 = first/second AY behind VIA-A, 2/3 behind VIA-B.
; ORA_NH=reg; ORB=latch; ORB=idle; ORA_NH=val; ORB=write; ORB=idle
; (6 bus accesses).
_ay_write:
        sta     ZP_VAL
        jsr     popa
        sta     ZP_REG
        jsr     popa
        tay                             ; Y = chip
        and     #1
        tax                             ; X = select index
        cpy     #2
        bcs     @via_b
        lda     ZP_REG
        sta     VIA_A_ORA_NH
        lda     sel_latch,x
        sta     VIA_A_ORB
        lda     sel_idle,x
        sta     VIA_A_ORB
        lda     ZP_VAL
        sta     VIA_A_ORA_NH
        lda     sel_write,x
        sta     VIA_A_ORB
        lda     sel_idle,x
        sta     VIA_A_ORB
        rts
@via_b:
        lda     ZP_REG
        sta     VIA_B_ORA_NH
        lda     sel_latch,x
        sta     VIA_B_ORB
        lda     sel_idle,x
        sta     VIA_B_ORB
        lda     ZP_VAL
        sta     VIA_B_ORA_NH
        lda     sel_write,x
        sta     VIA_B_ORB
        lda     sel_idle,x
        sta     VIA_B_ORB
        rts

; void __fastcall__ ssi_write(u8 reg, u8 val)
; reg is the SSI-263 register offset 0..4 from $C440 (DUR, INF, RATE, CTL, FILT).
; In Mockingboard mode the write also lands in the VIA-A register with the
; same offset (ORB, ORA, DDRB, DDRA, T1C-L): the caller then restores VIA-A
; with via_a_ddr() and resends every register of the chips behind it. In
; native mode VIA-A only answers when address bit 4 is set, so nothing
; aliases.
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

; void via_a_ddr(void) -- DDRA=$FF, DDRB=$1F, ORB=0 then ORB=$0C.
; ORB bit 2 is the AY reset line (low = reset), bits 1-0 are BDIR/BC1,
; bits 4-3 the active-low chip selects. The ORB 0 -> $0C pulse resets both
; AYs behind the VIA: every register reads 0 afterwards.
_via_a_ddr:
        lda     #$FF
        sta     VIA_A_DDRA
        lda     #$1F
        sta     VIA_A_DDRB
        stz     VIA_A_ORB
        lda     #$0C
        sta     VIA_A_ORB
        rts

; void via_b_ddr(void)
_via_b_ddr:
        lda     #$FF
        sta     VIA_B_DDRA
        lda     #$1F
        sta     VIA_B_DDRB
        stz     VIA_B_ORB
        lda     #$0C
        sta     VIA_B_ORB
        rts
