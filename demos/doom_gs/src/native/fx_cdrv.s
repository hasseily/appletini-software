; fx_cdrv.s: the a2vm test driver of part fxchan (milestone 11; docs/
; m11-parts/fxchan.md). Test only, never in the game. The port's own.
;
; It runs a stream of cases from main memory (fcd_in): each is an
; operation (0 sc_start, 1 sc_start2, 2 sc_stop, 3 sc_update, $FF the
; end), then the pokes the case makes before it (a count; each an address,
; a length 1-255 and the bytes: the channel table and mailboxes, the card's
; FM, LS_*, SND_SFXVOL, gamemap, the arguments, the stand-ins' tables, the
; scratch block's poison), then the call (the cost phase 30 around it),
; then each of the out ranges (fcd_olo/ohi/olen, fcd_nout of them) copied
; to fcd_out, one record after the other. A case with no pokes goes on
; from the state the last one left (a sequence). The end: fcd_halt, a2vm's
; stop.
;
;   -D FCD_PLAY  fx_isplaying: the reference's answer, fcd_play[X] (1:
;                playing), injected (docs/SCREENS.md 3, comparison 2)
;   -D FCD_POS   s2t_pos: the table fcd_pos (fcd_posn entries of 14 B:
;                the handle, x, y, angle), each ask logged in fcd_ask
;
; Without them the build links fxplay's fx_isplaying (fx.s's card part)
; and fx_pcache's s2t_pos.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "s2.inc"
        .include "math.inc"
        .include "fxchan.inc"

        .import sc_start, sc_start2, sc_stop, sc_update, mt_init
        .export fcd_start, fcd_halt, fcd_in, fcd_out, fcd_nout
        .export fcd_olo, fcd_ohi, fcd_olen, fxc_scr
        .export fxc_trace, fcd_ntr
.ifdef FCD_PLAY
        .export fx_isplaying, fcd_play
.endif
.ifdef FCD_POS
        .export s2t_pos, fcd_posn, fcd_pos, fcd_nask, fcd_ask
.endif

FCD_IP  = $F0                   ; the case pointer
FCD_OP  = $F2                   ; the out pointer
FCD_T   = $F4                   ; a poke's or an out range's address
FCD_K   = $F6
FCD_N   = $F7
FCD_K2  = $F8
TRACES  = 8
OUTS    = 8                     ; out ranges at most
POS     = 16                    ; s2t_pos entries at most
ASKS    = 32

        .segment "DRVCODE"

fcd_start:
        sei
        cld
        ldx #$FF
        txs
        jsr mt_init
        lda #<fcd_in
        sta FCD_IP
        lda #>fcd_in
        sta FCD_IP+1
        lda #<fcd_out
        sta FCD_OP
        lda #>fcd_out
        sta FCD_OP+1
@case:  jsr getb
        cmp #$FF
        beq fcd_halt
        sta fcd_opn
        jsr getb
        sta FCD_N
@poke:  lda FCD_N
        beq @call
        jsr getb
        sta FCD_T
        jsr getb
        sta FCD_T+1
        jsr getb
        tax
        ldy #0
@pb:    jsr getb
        sta (FCD_T),y
        iny
        dex
        bne @pb
        dec FCD_N
        bra @poke
@call:  stz fcd_ntr
.ifdef FCD_POS
        stz fcd_nask
.endif
        lda #PHV_2D
        sta PHASE
        lda fcd_opn
        asl a
        tax
        jsr @jump
        stz PHASE
        stz FCD_K
@out:   ldx FCD_K
        cpx fcd_nout
        bcs @case
        lda fcd_olo,x
        sta FCD_T
        lda fcd_ohi,x
        sta FCD_T+1
        ldy #0
@ob:    lda (FCD_T),y
        sta (FCD_OP),y
        iny
        tya
        cmp fcd_olen,x
        bne @ob
        clc
        lda FCD_OP
        adc fcd_olen,x
        sta FCD_OP
        bcc :+
        inc FCD_OP+1
:       inc FCD_K
        bra @out
@jump:  jmp (fcd_ops,x)

fcd_halt:
        bra fcd_halt

; fxc_trace: the channel logic's adjust (fx_chan.s -D FXC_TRACE): S_C,
; S_VOL, S_SEP, S_AUD (fx_chan.s's scratch offsets 17, 13, 15, 19) into
; fcd_tr; A, X, Y and P kept
fxc_trace:
        php
        pha
        phx
        phy
        lda fcd_ntr
        cmp #TRACES
        bcs @full
        asl a
        sta FCD_K2
        asl a
        adc FCD_K2              ; 6 a record
        tay
        lda fxc_scr + 17
        sta fcd_tr,y
        lda fxc_scr + 13
        sta fcd_tr+1,y
        lda fxc_scr + 14
        sta fcd_tr+2,y
        lda fxc_scr + 15
        sta fcd_tr+3,y
        lda fxc_scr + 16
        sta fcd_tr+4,y
        lda fxc_scr + 19
        sta fcd_tr+5,y
        inc fcd_ntr
@full:  ply
        plx
        pla
        plp
        rts

getb:   lda (FCD_IP)
        inc FCD_IP
        bne :+
        inc FCD_IP+1
:       rts

fcd_ops:
        .word sc_start, sc_start2, sc_stop, sc_update

.ifdef FCD_PLAY
; fx_isplaying: the injected answer; X kept
fx_isplaying:
        lda fcd_play,x
        cmp #1
        rts
.endif

.ifdef FCD_POS
; s2t_pos: A:X the handle; the table's x, y, angle into GT+0-11
s2t_pos:
        stx FCD_T
        sta FCD_T+1
        ldx fcd_nask            ; the ask, logged
        cpx #ASKS
        bcs :+
        txa
        asl a
        tay
        lda FCD_T
        sta fcd_ask,y
        lda FCD_T+1
        sta fcd_ask+1,y
        inc fcd_nask
:       ldy #0
        ldx fcd_posn
        beq @none
@l:     lda fcd_pos,y
        cmp FCD_T
        bne @n
        lda fcd_pos+1,y
        cmp FCD_T+1
        beq @hit
@n:     tya
        clc
        adc #14
        tay
        dex
        bne @l
@none:  sec
        rts
@hit:   ldx #0
:       lda fcd_pos+2,y
        sta FXC_GT,x
        iny
        inx
        cpx #12
        bne :-
        clc
        rts
.endif

        .segment "DRVDATA"

fcd_opn:  .res 1
fcd_nout: .res 1
fcd_olo:  .res OUTS
fcd_ohi:  .res OUTS
fcd_olen: .res OUTS
fxc_scr:  .res 32               ; the channel logic's scratch block
fcd_ntr:  .res 1                 ; the trace: count, then 6 B a record
fcd_tr:   .res 6 * TRACES
.ifdef FCD_PLAY
fcd_play: .res 8
.endif
.ifdef FCD_POS
fcd_nask: .res 1
fcd_ask:  .res 2 * ASKS
fcd_posn: .res 1
fcd_pos:  .res 14 * POS
.endif

        .segment "CASES"
fcd_in:   .res 1
        .segment "OUTS"
fcd_out:  .res 1
