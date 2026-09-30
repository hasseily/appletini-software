; The test driver of the music player: the main program tools/sound/run65.py
; runs on a2vm. It is not part of the game; it stands in for the game's
; main loop around the player.
;
; It sets the language card for read and write, turns on the mouse card's
; VBL interrupt, calls snd_probe when drv_probe is set, calls snd_init,
; runs the actions due at VBL 0 (a song's start), enables interrupts, then
; loops. After each VBL interrupt it runs
; the actions due and, unless a GATE_OFF action closed the gate, calls
; snd_refill once, as the game's frame loop would.
;
; Two loops (drv_mode):
;   0  drv_idle: waits for the next VBL. run65.py declares it an idle loop
;      (a2vm --idle drv_idle:vbl:eq=vbl_count,drv_seen), so a2vm skips to
;      the next VBL: fast, for the comparisons.
;   1  drv_count: counts its iterations in drv_counter (32 bits) while it
;      waits: the time the player leaves to the game, for the cost report.
;
; drv_actions, written by run65.py: 8 bytes each, a kind of 0 ends them.
;   kind (1): 1 START, 2 STOP, 3 GATE_OFF (no refill), 4 GATE_ON
;   vbl (2): due once this many VBL interrupts have run
;   START: bank (1), address (2), flags (1), music attenuation (1)
; A refused start stops at drv_halt with A = snd_error.
;
; drv_probe, written by run65.py: 1 runs snd_probe (probe.s) first and
; keeps its answer in drv_found; a card of the other layout than this
; build's stops at drv_halt with A = $10 + the layout found.

        .setcpu "65C02"
        .include "sound.inc"
        .include "tables.inc"

        .import snd_probe, snd_init, snd_start, snd_stop, snd_refill
        .import snd_song_bank, snd_song_addr, snd_song_flags, snd_song_matt
        .importzp vbl_count
        .export drv_start, drv_idle, drv_count, drv_halt
        .export drv_mode, drv_probe, drv_found, drv_actions, drv_counter
        .export drv_seen

ACT_START       = 1
ACT_STOP        = 2
ACT_GATE_OFF    = 3
ACT_GATE_ON     = 4
MAX_ACTIONS     = 32

        .segment "DRVZP": zeropage
drv_seen:       .res 2          ; the VBL count the loop has served
drv_counter:    .res 4
aptr:           .res 2          ; the next action
gate:           .res 1

        .segment "DRVDATA"
drv_mode:       .byte   0
drv_probe:      .byte   0
drv_found:      .byte   $FF             ; snd_probe's answer
drv_actions:    .res    MAX_ACTIONS * 8 + 1

        .segment "DRVCODE"

drv_start:
        sei
        cld
        ldx     #$FF
        txs
        bit     LC_RW_BANK2
        bit     LC_RW_BANK2
        stz     vbl_count
        stz     vbl_count+1
        stz     drv_seen
        stz     drv_seen+1
        stz     drv_counter
        stz     drv_counter+1
        stz     drv_counter+2
        stz     drv_counter+3
        lda     #1
        sta     gate
        lda     #<drv_actions
        sta     aptr
        lda     #>drv_actions
        sta     aptr+1
        lda     #$01 | MOUSE_VBL        ; enabled, VBL interrupt
        sta     MOUSE_MODE
        lda     drv_probe
        beq     @init
        jsr     snd_probe
        sta     drv_found
        cmp     #LAYOUT_ID
        beq     @init
        ora     #$10                    ; the card has the other layout
        jmp     drv_halt
@init:  jsr     snd_init
        jsr     actions
        cli
        lda     drv_mode
        bne     drv_count

drv_idle:
        lda     vbl_count
        cmp     drv_seen
        beq     drv_idle
        jsr     service
        bra     drv_idle

drv_count:
        inc     drv_counter
        bne     :+
        inc     drv_counter+1
        bne     :+
        inc     drv_counter+2
        bne     :+
        inc     drv_counter+3
:       lda     vbl_count
        cmp     drv_seen
        beq     drv_count
        jsr     service
        bra     drv_count

service:
        sei
        lda     vbl_count
        sta     drv_seen
        lda     vbl_count+1
        sta     drv_seen+1
        cli
        jsr     actions
        lda     gate
        beq     :+
        jsr     snd_refill
:       rts

; the actions due: vbl <= drv_seen
actions:
        lda     (aptr)
        beq     @done
        ldy     #2
        lda     drv_seen+1
        cmp     (aptr),y
        bcc     @done
        bne     @due
        dey
        lda     drv_seen
        cmp     (aptr),y
        bcc     @done
@due:   lda     (aptr)
        cmp     #ACT_START
        bne     @stop
        ldy     #3
        lda     (aptr),y
        sta     snd_song_bank
        iny
        lda     (aptr),y
        sta     snd_song_addr
        iny
        lda     (aptr),y
        sta     snd_song_addr+1
        iny
        lda     (aptr),y
        sta     snd_song_flags
        iny
        lda     (aptr),y
        sta     snd_song_matt
        jsr     snd_start
        bcs     drv_halt
        bra     @next
@stop:  cmp     #ACT_STOP
        bne     @gate
        jsr     snd_stop
        bra     @next
@gate:  cmp     #ACT_GATE_OFF
        bne     @open
        stz     gate
        bra     @next
@open:  lda     #1
        sta     gate
@next:  clc
        lda     aptr
        adc     #8
        sta     aptr
        bcc     actions
        inc     aptr+1
        bra     actions
@done:  rts

drv_halt:
        bra     drv_halt
