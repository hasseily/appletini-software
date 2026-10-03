; pl_irq.s: the platform's interrupt entry, the tic clock, I_GetTime and
; the PAL or NTSC detection (milestone 11, part plclock; docs/SCREENS.md
; 2.2, 2.3, 4.4). GPL-2, the port's own: written from the design, the
; //e kernel's IRQ entry (demos/doom/src/kernel/kstart.s, irq_entry and
; irq_mouse_service) and S2's snd_vbl (src/sound/irq.s), which it replaces
; as the IRQ vector (irq.s itself is unchanged: MUSIC.SYSTEM keeps it).
;
;   pl_vbl      the IRQ vector of the main card ($FFFE). SCREENS.md 2.3's
;               seven steps: (1) A, X, Y saved; a BRK (the B bit of the
;               pushed P) goes to the crash stop; (2) the mouse card's
;               status read, then acknowledged; only the VBL cause counts
;               (a second entry with no VBL pending, which the card can make
;               in TURBO [R kstart.s:267-270], changes nothing); (3) the
;               clock; (4) fx_step; (5) snd_tick, S2's music player
;               unchanged; (6) fx_burst; (7) restore and RTI.
;   pl_vbody    steps 2-6 as a subroutine: pl_vbl's body, and what the aux
;               card's bridge (pl_bridge.s) calls with ALTZP off. Without
;               the Appletini's mouse card DOOM.SYSTEM writes its first 13
;               bytes over (pl_boot.s mo_recs, docs/PLAY.md 20): the cause
;               is then the Phasor's VIA-B timer 1 flag, cleared by
;               writing it back to IFR, the branch to pl_vnone the same;
;               pl_crash's mode and ACK become VIA-B's IER off
;   pl_crash    the crash stop: interrupts masked, the VBL off, a loop.
;               The code that stops writes its code to PL_STATUS first,
;               then BRK (MEMORY_MAP.md 15's rule)
;   pl_time     I_GetTime: the tics since pl_clkset, read with interrupts
;               masked: A bits 0-7, X 8-15, Y 16-23, and bits 24-31 copied
;               to CLK_TIME3 in the same masked read; P's I bit as it was
;   pl_clkset   A = the standard (STD_PAL 0, STD_NTSC $80, SONG_NTSC's
;               bit): its fraction a VBL into CLK_STEP; the fraction, the
;               tics and the VBL count from 0
;   pl_detect   PAL or NTSC as MUSIC.SYSTEM decides it [R tools/sound/
;               README.md:395-405]: VIA-A's timer 1 over one VBL, 20,280
;               bus cycles PAL, 17,030 NTSC, the nearer wins; then
;               pl_clkset. Interrupts on, the VBL running, pl_vbl the
;               handler. Returns A = the standard, X:Y = the count (high,
;               low)
;
; The clock (SCREENS.md 2.2, 0.1 F2): a 16-bit fraction a VBL, TIC_FRAC
; 45,743 (PAL) or 38,229 (NTSC) / 65,536; a carry out of the fraction is
; a tic. 50.0801 x 45,743 / 65,536 = 34.9551 and 59.9227 x 38,229 /
; 65,536 = 34.9546 tics a second, upstream's 34.955. After pl_clkset, at
; VBL n the fraction is n x F mod 65,536 and the tics n x F >> 16
; (tools/native/plclock.py, the host model).
;
; The IRQ contract (MEMORY_MAP.md rule 2): zero page $D8-$FF, the stack,
; $E000-$FFFF, $C0A0-$C0AF, $C400-$C4FF; nothing else, so RAMRD, RAMWRT,
; $C073 may be anything when it comes.
;
; The VBL count is S2's vbl_count, in the IRQ's zero page (S2's 31 bytes
; at $D8 hold it), not in the card: S2's driver, MUSIC.SYSTEM and the
; timing test import it as a zero-page word, and the music's comparison
; links S2's driver unchanged (request PLCLOCK-1 in
; docs/m11-parts/plclock.md, applied in wave 2's integration: the card's
; clock is CLK_STEP, CLK_FRAC, CLK_TICS, CLK_STD, CLK_TIME3 of s2.inc).

        .setcpu "65C02"
        .include "s2.inc"

        .import fx_step, fx_burst, snd_tick
        .export pl_vbl, pl_vbody, pl_crash, pl_halt, pl_time, pl_clkset
        .export pl_detect, pl_wait, pl_nmi, pl_vnone
        .exportzp vbl_count
        .export CLK_STEP, CLK_TIME3

MOUSE_STATUS = $C0A0            ; the mouse card in slot 2
MOUSE_MODE   = $C0AE
MOUSE_ACK    = $C0AF
MOUSE_VBL    = $08              ; status and mode bit: the VBL interrupt
ACK_ALL      = $03
VIA_A_T1CL   = $C414            ; the Phasor's VIA-A, timer 1 (both modes)
VIA_A_T1CH   = $C415
VIA_A_T1LL   = $C416

STD_PAL      = $00
STD_NTSC     = $80              ; S2's SONG_NTSC (src/sound/sound.inc)
TIC_FRAC_PAL = 45743
TIC_FRAC_NTSC = 38229
PAL_NTSC_CUT = 18655            ; cycles a VBL: halfway, 17,030 to 20,280

        .segment "SNDZP": zeropage
vbl_count:      .res 2          ; VBL interrupts since pl_clkset

        .segment "FXCODE"

; ---------------------------------------------------------------------------
; the interrupt entry
; ---------------------------------------------------------------------------
pl_vbl:
        pha                     ; (1)
        phx
        phy
        tsx
        lda $0104,x             ; the pushed P
        and #$10
        bne pl_crash            ; a BRK
        jsr pl_vbody
        ply                     ; (7)
        plx
        pla
pl_nmi: rti

pl_vbody:
        ldx MOUSE_STATUS        ; (2) the cause, read before the ack
        lda #ACK_ALL
        sta MOUSE_ACK
        txa
        and #MOUSE_VBL
        beq pl_vnone            ; no VBL pending: nothing counts
        inc vbl_count
        bne :+
        inc vbl_count+1
:       clc                     ; (3) the fraction; its carry is a tic
        lda CLK_FRAC
        adc CLK_STEP
        sta CLK_FRAC
        lda CLK_FRAC+1
        adc CLK_STEP+1
        sta CLK_FRAC+1
        bcc @steps
        inc CLK_TICS
        bne @steps
        inc CLK_TICS+1
        bne @steps
        inc CLK_TICS+2
        bne @steps
        inc CLK_TICS+3
@steps: jsr fx_step             ; (4) the effects' steps, no I/O
        jsr snd_tick            ; (5) the music's burst, chips 0-2
        jmp fx_burst            ; (6) chip 3's, right after (its RTS)
pl_vnone:
        rts

; the crash stop: a BRK lands here (from pl_vbl, or from the aux card's
; bridge with ALTZP off). Writes nothing outside the IRQ contract.
pl_crash:
        sei
        stz MOUSE_MODE          ; no more VBL interrupts
        lda #ACK_ALL
        sta MOUSE_ACK
pl_halt:
        bra pl_halt

; ---------------------------------------------------------------------------
; I_GetTime
; ---------------------------------------------------------------------------
pl_time:
        php
        sei
        lda CLK_TICS+3
        sta CLK_TIME3
        ldy CLK_TICS+2
        ldx CLK_TICS+1
        lda CLK_TICS
        plp
        rts

; ---------------------------------------------------------------------------
; the clock's start, PAL or NTSC
; ---------------------------------------------------------------------------
pl_clkset:
        php
        sei
        sta CLK_STD
        ldx #<TIC_FRAC_PAL
        ldy #>TIC_FRAC_PAL
        cmp #STD_NTSC
        bcc :+
        ldx #<TIC_FRAC_NTSC
        ldy #>TIC_FRAC_NTSC
:       stx CLK_STEP
        sty CLK_STEP+1
        stz CLK_FRAC
        stz CLK_FRAC+1
        stz CLK_TICS
        stz CLK_TICS+1
        stz CLK_TICS+2
        stz CLK_TICS+3
        stz CLK_TIME3
        stz vbl_count
        stz vbl_count+1
        plp
        rts

; pl_detect: timer 1 counts the Apple bus cycles of one VBL; returns A =
; the standard, X:Y = the count, high and low byte (MUSIC.SYSTEM shows
; it). Its two reads of the counter are low byte then high byte, as
; MUSIC.SYSTEM's: a borrow between them errs by at most 256 cycles of the
; 1,625 that separate either standard from the cut.
pl_detect:
        lda #$FF
        sta VIA_A_T1LL
        sta VIA_A_T1CH          ; $FFFF, counting down
        jsr pl_wait
        lda VIA_A_T1CL
        ldy VIA_A_T1CH
        phy                     ; the first reading, high then low
        pha
        jsr pl_wait
        lda VIA_A_T1CL
        ldy VIA_A_T1CH
        phy                     ; the second
        pha
        tsx
        sec                     ; the cycles: first - second
        lda $0103,x
        sbc $0101,x
        tay
        lda $0104,x
        sbc $0102,x
        tax                     ; X:Y = the count, high:low
        pla
        pla
        pla
        pla
        cpy #<PAL_NTSC_CUT
        txa
        sbc #>PAL_NTSC_CUT
        lda #STD_PAL            ; at least the cut: PAL
        bcs :+
        lda #STD_NTSC
:       phx
        phy
        pha
        jsr pl_clkset
        pla
        ply
        plx
        rts

; pl_wait: until the next VBL's count
pl_wait:
        lda vbl_count
:       cmp vbl_count
        beq :-
        rts

; the main card's vectors: NMI an RTI, reset unused (the ROM's), IRQ/BRK
        .segment "VECTORS"
        .word pl_nmi, pl_crash, pl_vbl
