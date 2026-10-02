; fx_pcache.s: MENUW's position callback for the channel logic (milestone
; 11, part fxchan; docs/SCREENS.md 4.7). The port's own.
;
;   s2t_pos   A:X a handle (A the high byte): its x, y (and angle) into
;             GT+0-11 with carry clear, from what the channel logic kept
;             when the tic image last asked milestone 10's s2t_pos: the
;             listener (FXC_LISTENER) from LS_X, LS_Y, LS_ANGLE while
;             LS_ON says there is one; a mobj from the first busy channel
;             whose origin it is (CH_X, CH_Y). Carry set: none.
;
; While a menu is up the game is paused (no tic runs [R d_main65.s:
; 261-279]), so these are the positions upstream's S_UpdateSounds reads in
; a paused frame: fx_chan's sc_update after the frame's tics refreshed
; every playing channel's origin and the listener.

        .setcpu "65C02"
        .include "s2.inc"
        .include "fxchan.inc"

        .export s2t_pos

.ifdef FXC_MSCR
; -D FXC_MSCR (the linkage image fxcmw only): the channel logic's scratch
; block in MENUW, the last 32 B of its fetch buffer ($BD00-$BEFF), dead
; outside a patch's draw. STANDIN: request FXCHAN-4 (s2menu1, s2lay)
        .export fxc_scr
fxc_scr = $BEE0
.endif

        .segment "S2CODE"

s2t_pos:
        cmp #>FXC_LISTENER
        bne @mo
        cpx #<FXC_LISTENER
        bne @mo
        bit LS_ON
        bpl @none
        ldx #11
:       lda LS_X,x
        sta FXC_GT,x
        dex
        bpl :-
        clc
        rts
@mo:    stx FXC_GT              ; the handle, for the compares
        sta FXC_GT+1
        ldy #0
@l:     lda SC_BASE+CH_SFX,y
        beq @n
        lda SC_BASE+CH_KIND,y
        and #CHF_KIND
        cmp #ORG_MOBJ
        bne @n
        lda SC_BASE+CH_HANDLE,y
        cmp FXC_GT
        bne @n
        lda SC_BASE+CH_HANDLE+1,y
        cmp FXC_GT+1
        bne @n
        ldx #0
:       lda SC_BASE+CH_X,y
        sta FXC_GT,x
        iny
        inx
        cpx #8
        bne :-
        clc
        rts
@n:     tya
        clc
        adc #CHAN_SIZE
        tay
        cpy #NUM_CHANNELS * CHAN_SIZE
        bcc @l
@none:  sec
        rts
