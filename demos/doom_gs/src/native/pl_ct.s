; pl_ct.s: test only, not part of the game (milestone 11, part plclock;
; docs/m11-parts/plclock.md). Routines the test driver s2_drv calls in the
; clock's test image (P2DW's room, pl_vbl the handler, S2's player in the
; card, part fxplay's effect player there: fx_init with the effects on and
; none playing, the release's state). GPL-2, the port's own.
;
;   plt_mode    A = the mouse card's mode (the second-entry test turns on
;               the button interrupt beside the VBL's: $0D)
;   plt_clock   A:X = N (low, high), Y = the standard: $FF detects it
;               (pl_detect), else pl_clkset Y. snd_init first (the
;               player's state is poison in the test machine). Then after
;               each of N VBLs, the clock into the log at PLT_LOG, 4 bytes
;               a VBL: the tics' low word (pl_time), the fraction, all
;               read in one masked window; the VBL count must be k at the
;               k-th, else the stop PLT_MISSED (a VBL the log did not see,
;               or one counted twice before it looked)
;   plt_idle    the wait for the next VBL: an a2vm idle loop
;               (--idle plt_idle:vbl:eq=vbl_count,plt_seen)

        .setcpu "65C02"
        .include "s2.inc"

        .import pl_time, pl_clkset, pl_detect, snd_init, fx_init
        .importzp vbl_count
        .export plt_mode, plt_clock, plt_idle, plt_seen, plt_std, plt_count
        .export PLT_LOG, PLT_MAX

PLT_LOG    = $7000              ; up to $BFFF: 4,096 VBLs (W, this image's)
PLT_MAX    = ($C000 - PLT_LOG) / 4
PLT_MISSED = $7C                ; the log's stop code (PL_STATUS)
PTR        = $48                ; the 2D images' zero page (S2_*)
MOUSE_MODE = $C0AE
MOUSE_ACK  = $C0AF

        .segment "S2CODE"

plt_mode:
        sta MOUSE_MODE
        lda #3
        sta MOUSE_ACK
        rts

plt_clock:
        sta plt_n
        stx plt_n+1
        phy
        jsr snd_init
        lda #0                  ; snd_probe's answer: native mode
        jsr fx_init             ;   (the effects on, none playing)
        pla
        cmp #$FF
        bne @set
        jsr pl_detect           ; A = the standard, X:Y = the count
        sta plt_std
        stx plt_count+1
        sty plt_count
        bra @go
@set:   sta plt_std
        jsr pl_clkset
@go:    lda #<PLT_LOG
        sta PTR
        lda #>PLT_LOG
        sta PTR+1
        stz plt_seen
        stz plt_seen+1
plt_next:  lda plt_seen            ; k = N: done
        cmp plt_n
        lda plt_seen+1
        sbc plt_n+1
        bcs plt_done
plt_idle:
        lda vbl_count
        cmp plt_seen
        beq plt_idle
        php
        sei
        inc plt_seen
        bne :+
        inc plt_seen+1
:       lda vbl_count           ; the VBL count is k
        cmp plt_seen
        bne plt_miss
        lda vbl_count+1
        cmp plt_seen+1
        bne plt_miss
        jsr pl_time             ; the tics' low word in A:X
        ldy #0
        sta (PTR),y
        iny
        txa
        sta (PTR),y
        iny
        lda CLK_FRAC
        sta (PTR),y
        iny
        lda CLK_FRAC+1
        sta (PTR),y
        plp
        clc
        lda PTR
        adc #4
        sta PTR
        bcc plt_next
        inc PTR+1
        bra plt_next
plt_miss:  lda #PLT_MISSED
        sta PL_STATUS
        brk
        .byte $00
plt_done:  rts

        .segment "S2DATA"
plt_n:     .res 2               ; N
plt_seen:  .res 2               ; the VBLs logged
plt_std:   .res 1               ; the standard set
plt_count: .res 2               ; pl_detect's count (bus cycles a VBL)
