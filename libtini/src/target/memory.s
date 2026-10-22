; CPU-only AUX transfers. Entry parameters are private C globals.
; Near address and AUX address must already have been range checked by C.
; Length is 1..128. No call may cross $BFFF or a logical resource bank.
;
; RAMRD redirects instruction fetches above page 1. The two short loops
; therefore execute at $0140 while ALTZP stays off. Main ZP and the MAIN
; hardware stack remain selected. $0100-$013F is reserved for ProDOS;
; application hardware stack usage must remain in $0180-$01FF.
;
; Contract: entry/return RAMRD=RAMWRT=80STORE=ALTZP=0, selector=0.
; IRQs are masked only for a bounded burst and entry processor status is
; restored. No interrupt handler may change these switches or call libtini.
; NMI handlers must not touch AUX mappings or this non-reentrant backend.
; $C073 has no specified readback: ownership/entry bank0 is contractual.
; Bank 0 transfers therefore leave the selector alone. Every //e access to
; $C070-$C07F also strobes the paddle timers, and video publication makes
; bank 0 transfers constantly.
.setcpu "65C02"
.include "zeropage.inc"

.export _ti_cpu_read, _ti_cpu_write, _ti_platform_setup
.export ti_read_trampoline, ti_write_trampoline
.import _ti_io_bank, _ti_io_len, _ti_io_addr, _ti_io_near

TRAMP = $0140

.segment "RODATA"
trampoline:
.proc read_loop
        sta $C003                  ; AUX reads, MAIN writes
        ldy #0
loop:   lda (ptr1),y
        sta (ptr2),y
        iny
        dex
        bne loop
        sta $C002                  ; MAIN reads before returning
        rts
.endproc
.proc write_loop
        sta $C005                  ; MAIN reads, AUX writes
        ldy #0
loop:   lda (ptr2),y
        sta (ptr1),y
        iny
        dex
        bne loop
        sta $C004                  ; MAIN writes before returning
        rts
.endproc
trampoline_end:
.assert trampoline_end-trampoline <= $40, error, "AUX trampoline exceeds reservation"
ti_read_trampoline = TRAMP + (read_loop-trampoline)
ti_write_trampoline = TRAMP + (write_loop-trampoline)

.segment "CODE"
_ti_platform_setup:
        ldx #trampoline_end-trampoline-1
loop:   lda trampoline,x
        sta TRAMP,x
        dex
        bpl loop
        rts

; Configure MAIN ZP before mapping AUX. ptr1/ptr2 are cc65 scratch registers.
prepare:
        lda _ti_io_addr
        sta ptr1
        lda _ti_io_addr+1
        sta ptr1+1
        lda _ti_io_near
        sta ptr2
        lda _ti_io_near+1
        sta ptr2+1
        ldx _ti_io_len
        lda _ti_io_bank
        beq :+
        sta $C073
:       rts

_ti_cpu_read:
        php
        sei
        jsr prepare
        jsr ti_read_trampoline
        bra restore

_ti_cpu_write:
        php
        sei
        jsr prepare
        jsr ti_write_trampoline
restore:
        lda _ti_io_bank
        beq :+
        stz $C073                  ; owned selector always returns to base AUX
:       plp
        rts
