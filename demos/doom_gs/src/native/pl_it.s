; pl_it.s: test only, not part of the game (milestone 11, part plinput;
; docs/m11-parts/plinput.md). The input's test image: MENUW's room, the test
; driver s2_drv with pl_vbl the handler, S2's player in the card (snd_tick),
; part fxplay's effect player there (fx_step, fx_burst). GPL-2, the port's
; own.
;
;   plt_run     A = the polls N (1-255), X = the standard (pl_clkset's).
;               snd_init (the player's state is poison in the test
;               machine), fx_init (the effects on, none playing), the clock from 0, the mouse card on with its VBL
;               (mode $09, the boot's), pl_init. Then each of the N
;               entries of the schedule at PLT_SCHED (8 bytes, the
;               harness's):
;                 +0, +1  the tic of the poll: the loop waits (an a2vm
;                         idle loop on the VBL) until pl_time reaches it
;                 +2      pl_poll's A (a menu is up)
;                 +3      after the poll, in this order: bit 0 the queue
;                         drained (PL_QHEAD = PL_QTAIL), bit 1 PL_MDX taken
;                         (0), bit 2 pl_bind(+4, +5), bit 3 pl_defaults,
;                         bit 4 PL_BIND = $FF (the key setup waits), bit 5
;                         PL_BIND = $80 (its key taken), bit 6
;                         pl_action(+4) into +6, +7
;               The cost phase 31 around pl_poll; plt_polled, right after
;               it, is the run's boundary (a snapshot and a cost line a
;               poll; interrupts masked there, so one visit a poll).
;   plt_idle    the wait's loop (--idle plt_idle:vbl:eq=vbl_count,
;               plt_seen)

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "s2.inc"

        .import pl_poll, pl_init, pl_bind, pl_defaults, pl_action
        .import pl_time, pl_clkset, snd_init, fx_init
        .importzp vbl_count
        .export plt_run, plt_idle, plt_seen, plt_polled, plt_k
        .export PLT_SCHED, PLT_ENTRY

PLT_SCHED  = $A000              ; W's runtime part (none in this image)
PLT_ENTRY  = 8
PTR        = $80                ; the menus' zero page, free here
MOUSE_MODE = $C0AE
MODE_ON_VBL = $09

        .segment "S2CODE"

plt_run:
        sta plt_n
        phx
        jsr snd_init
        lda #0                  ; snd_probe's answer: native mode
        jsr fx_init             ;   (the effects on, none playing)
        pla
        jsr pl_clkset
        lda #MODE_ON_VBL
        sta MOUSE_MODE
        jsr pl_init
        lda #<PLT_SCHED
        sta PTR
        lda #>PLT_SCHED
        sta PTR+1
        stz plt_k
plt_next:
        lda plt_k
        cmp plt_n
        bcc plt_wait
        rts
plt_wait:
        sei                     ; the VBL count and the tics together
        lda vbl_count
        sta plt_seen
        lda vbl_count+1
        sta plt_seen+1
        jsr pl_time             ; the tics' low word in A:X
        cli
        ldy #0
        cmp (PTR),y
        txa
        iny
        sbc (PTR),y
        bcs plt_poll
plt_idle:
        lda vbl_count           ; until the next VBL
        cmp plt_seen
        beq plt_idle
        bra plt_wait
plt_poll:
        ldy #2
        lda #PHV_PLATFORM
        sta PHASE
        lda (PTR),y
        jsr pl_poll
        lda #PHV_2D
        sta PHASE
        sei
plt_polled:
        cli
        ldy #3
        lda (PTR),y
        sta plt_f
        lsr plt_f
        bcc :+
        lda PL_QTAIL            ; bit 0: the queue drained
        sta PL_QHEAD
:       lsr plt_f
        bcc :+
        stz PL_MDX              ; bit 1: the motion taken
        stz PL_MDX+1
:       lsr plt_f
        bcc :+
        ldy #5                  ; bit 2: pl_bind(+4, +5)
        lda (PTR),y
        tax
        dey
        lda (PTR),y
        jsr pl_bind
:       lsr plt_f
        bcc :+
        jsr pl_defaults         ; bit 3
:       lsr plt_f
        bcc :+
        lda #$FF                ; bit 4: the key setup waits for a key
        sta PL_DEFER+1
:       lsr plt_f
        bcc :+
        lda #$80                ; bit 5: its key taken
        sta PL_DEFER+1
:       lsr plt_f
        bcc :+
        ldy #4                  ; bit 6: pl_action(+4) into +6, +7
        lda (PTR),y
        jsr pl_action
        ldy #6
        sta (PTR),y
        txa
        iny
        sta (PTR),y
:       clc
        lda PTR
        adc #PLT_ENTRY
        sta PTR
        bcc :+
        inc PTR+1
:       inc plt_k
        jmp plt_next

        .segment "S2DATA"
plt_n:     .res 1
plt_k:     .res 1               ; the poll
plt_f:     .res 1
plt_seen:  .res 2               ; vbl_count when the wait looked
