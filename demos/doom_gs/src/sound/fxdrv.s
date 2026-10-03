; fxdrv.s: the effect player's test driver (milestone 11, part fxplay),
; the main program tools/sound/fxrun65.py runs on a2vm. Not part of the
; game: it stands in for the game's main loop around S2's music player,
; pl_vbl and the effect player (src/sound/fx.s). GPL-2, the port's own;
; written after S2's driver (src/sound/driver.s).
;
; Boot: the language card read and write; the mouse card's VBL on (mode
; $09); the clock's standard (pl_clkset with drv_std: the effects' tempo
; follows CLK_STD); snd_probe when drv_probe is set (else the answer is
; SND_MUSIC); snd_init; fx_init with the answer; with drv_mode bit 1, a
; calibration (drv_cal: the delay loop's iterations in one VBL, the
; interrupts on and idle); the actions due at VBL 0; then the loop. After
; each VBL interrupt the actions due, then every drv_frame VBLs a frame:
; fx_service, then snd_refill, as the game's frame images do (each behind
; its gate, drv_gate bit 0 and bit 1).
;
; Loops (drv_mode bit 0): 0 drv_idle, which fxrun65.py declares an idle
; loop to a2vm (fast, for the comparisons); 1 drv_count, which counts its
; iterations in drv_counter while it waits (the time left to the game,
; for the cost).
;
; drv_actions, written by fxrun65.py, ACT_SIZE bytes each, a kind of 0
; ends them: kind (1), vbl (2: due once this many VBLs have run), five
; arguments, a delay (2: iterations of the delay loop before the action).
;   1 SONG      bank, address (2), flags, attenuation: fx_song (skipped
;               without music, as the game never starts a song then)
;   2 SONGSTOP  snd_stop (without music: skipped)
;   3 START     channel, sound, volume, separation: the mailbox as the
;               channel logic writes it (tools/sound/README.md "The game
;               side"): start set, its sound, volume, separation
;   4 STOP      channel: stop set, start and volume cleared
;   5 VOLUME    channel, volume: volume set, the volume
;   6 GATE      the gates: bit 0 fx_service, bit 1 snd_refill
;   7 STOPALL   fx_stopall
;   8 QUERY     fx_isplaying of every channel: a byte (bit c: channel c
;               plays) into drv_qlog
;   9 FRAME     VBLs a frame (1-255); the next VBL is a frame's
;  10 SERVICE   fx_service now (a second one in the same gap)
;
; drv_mark, which fxrun65.py's write log reads with the time of each
; store: an action's kind while it runs, $80 while a frame's fx_service
; runs, $81 while its snd_refill runs, 0 between.
; A refused song start stops at drv_halt with A = snd_error.

        .setcpu "65C02"
        .include "s2.inc"

        .import snd_probe, snd_init, snd_stop, snd_refill
        .import snd_song_bank, snd_song_addr, snd_song_flags, snd_song_matt
        .import fx_init, fx_service, fx_song, fx_stopall, fx_isplaying
        .import pl_clkset
        .importzp vbl_count
        .export drv_start, drv_idle, drv_count, drv_halt, drv_seen
        .export drv_mode, drv_probe, drv_std, drv_found, drv_music
        .export drv_gate, drv_frame, drv_cal, drv_nq, drv_qlog
        .export drv_actions, drv_counter, drv_frames, drv_mark

MOUSE_MODE      = $C0AE
MOUSE_VBL_ON    = $09           ; enabled, the VBL interrupt
LC_RW_BANK2     = $C083
SND_MUSIC       = 0

ACT_SIZE        = 10
MAX_ACTIONS     = 96
QLOG            = 64

        .segment "DRVZP": zeropage
drv_seen:       .res 2          ; the VBL count the loop has served
drv_counter:    .res 4
aptr:           .res 2          ; the next action
drv_dl:         .res 2          ; the delay's count
drv_fc:         .res 1          ; VBLs to the next frame
drv_t:          .res 1
drv_frames:     .res 2          ; frames served
drv_mark:       .res 1          ; what the main loop is doing (above)

        .segment "DRVDATA"
drv_mode:       .byte 0
drv_probe:      .byte 0
drv_std:        .byte 0         ; 0 PAL, $80 NTSC
drv_found:      .byte $FF       ; snd_probe's answer
drv_music:      .byte 1         ; 0: no music (snd_probe said so)
drv_gate:       .byte 3
drv_frame:      .byte 1
drv_cal:        .byte 0, 0, 0   ; (24 bits)
drv_nq:         .byte 0
drv_qlog:       .res QLOG
drv_actions:    .res MAX_ACTIONS * ACT_SIZE + 1

        .segment "DRVCODE"

drv_start:
        sei
        cld
        ldx #$FF
        txs
        bit LC_RW_BANK2
        bit LC_RW_BANK2
        stz drv_seen
        stz drv_seen + 1
        stz drv_counter
        stz drv_counter + 1
        stz drv_counter + 2
        stz drv_counter + 3
        stz drv_frames
        stz drv_frames + 1
        stz drv_mark
        lda #1
        sta drv_fc
        lda #<drv_actions
        sta aptr
        lda #>drv_actions
        sta aptr + 1
        lda #MOUSE_VBL_ON
        sta MOUSE_MODE
        lda drv_std
        jsr pl_clkset           ; CLK_STD; vbl_count from 0
        lda #SND_MUSIC
        ldx drv_probe
        beq @init
        jsr snd_probe
        sta drv_found
@init:  pha
        cmp #SND_MUSIC
        beq :+
        stz drv_music           ; no music: no song starts
:       jsr snd_init
        pla
        jsr fx_init
        lda drv_mode
        and #2
        beq @go
        cli                     ; the calibration: one VBL of the delay
        lda vbl_count           ; loop's body
:       cmp vbl_count
        beq :-
        lda vbl_count
        sta drv_t
        stz drv_dl
        stz drv_dl + 1
        stz drv_cal + 2
@cal:   inc drv_dl              ; (24 bits: in TURBO a VBL holds more
        bne :+                  ;   than 65,535 turns, 78,209 on a2vm f121
        inc drv_dl + 1          ;   since 2026-10-03, 94,951 before)
        bne :+
        inc drv_cal + 2
:       lda vbl_count
        cmp drv_t
        beq @cal
        lda drv_dl
        sta drv_cal
        lda drv_dl + 1
        sta drv_cal + 1
        sei
        lda vbl_count
        sta drv_seen
        lda vbl_count + 1
        sta drv_seen + 1
@go:    jsr actions
        cli
        lda drv_mode
        lsr a
        bcs drv_count

drv_idle:
        lda vbl_count
        cmp drv_seen
        beq drv_idle
        jsr service
        bra drv_idle

drv_count:
        inc drv_counter
        bne :+
        inc drv_counter + 1
        bne :+
        inc drv_counter + 2
        bne :+
        inc drv_counter + 3
:       lda vbl_count
        cmp drv_seen
        beq drv_count
        jsr service
        bra drv_count

service:
        sei
        lda vbl_count
        sta drv_seen
        lda vbl_count + 1
        sta drv_seen + 1
        cli
        jsr actions
        dec drv_fc
        bne @rts
        lda drv_frame
        sta drv_fc
        inc drv_frames
        bne :+
        inc drv_frames + 1
:       lda #$80
        sta drv_mark
        lda drv_gate
        lsr a
        bcc :+
        jsr fx_service
:       lda #$81
        sta drv_mark
        lda drv_gate
        and #2
        beq :+
        lda drv_music
        beq :+
        jsr snd_refill
:       stz drv_mark
@rts:   rts

; the actions due: vbl <= drv_seen
actions:
        lda (aptr)
        beq @done
        ldy #2
        lda drv_seen + 1
        cmp (aptr),y
        bcc @done
        bne @due
        dey
        lda drv_seen
        cmp (aptr),y
        bcc @done
@due:   ldy #8                  ; the delay first
        lda (aptr),y
        sta drv_dl
        iny
        lda (aptr),y
        sta drv_dl + 1
        jsr delay
        lda (aptr)
        sta drv_mark
        asl a
        tax
        jsr @do
        stz drv_mark
        clc
        lda aptr
        adc #ACT_SIZE
        sta aptr
        bcc actions
        inc aptr + 1
        bra actions
@done:  rts
@do:    jmp (act_table - 2,x)

act_table:
        .word act_song, act_songstop, act_start, act_stop, act_volume
        .word act_gate, fx_stopall, act_query, act_frame, fx_service

; the argument k (3-7) of the action: A
.macro ARG k
        ldy #k
        lda (aptr),y
.endmacro

; the mailbox of the channel in argument 3: X
mailbox:
        ARG 3
        asl a
        asl a
        tax
        rts

act_song:
        lda drv_music
        beq @rts
        ARG 3
        sta snd_song_bank
        ARG 4
        sta snd_song_addr
        ARG 5
        sta snd_song_addr + 1
        ARG 6
        sta snd_song_flags
        ARG 7
        sta snd_song_matt
        jsr fx_song
        bcc @rts
        jmp drv_halt
@rts:   rts

act_songstop:
        lda drv_music
        beq :+
        jsr snd_stop
:       rts

act_start:
        jsr mailbox
        lda SC_MAIL + MX_FLAGS,x
        ora #MX_START
        sta SC_MAIL + MX_FLAGS,x
        ARG 4
        sta SC_MAIL + MX_SOUND,x
        ARG 5
        sta SC_MAIL + MX_VOL,x
        ARG 6
        sta SC_MAIL + MX_SEP,x
        rts

act_stop:
        jsr mailbox
        lda SC_MAIL + MX_FLAGS,x
        ora #MX_STOP
        and #<~(MX_START | MX_VOLUME)
        sta SC_MAIL + MX_FLAGS,x
        rts

act_volume:
        jsr mailbox
        lda SC_MAIL + MX_FLAGS,x
        ora #MX_VOLUME
        sta SC_MAIL + MX_FLAGS,x
        ARG 4
        sta SC_MAIL + MX_VOL,x
        rts

act_gate:
        ARG 3
        sta drv_gate
        rts

act_query:
        stz drv_t
        ldx #NUM_CHANNELS - 1
:       jsr fx_isplaying        ; carry: playing
        rol drv_t
        dex
        bpl :-
        ldx drv_nq              ; bit c: channel c (channel 0 last in)
        cpx #QLOG
        bcs :+
        lda drv_t
        sta drv_qlog,x
        inc drv_nq
:       rts

act_frame:
        ARG 3
        sta drv_frame
        lda #1
        sta drv_fc
        rts

; delay: drv_dl iterations of the calibration loop's kind
delay:
        lda drv_dl
        ora drv_dl + 1
        beq @done
        lda drv_dl
        bne :+
        dec drv_dl + 1
:       dec drv_dl
        lda vbl_count
        bra delay
@done:  rts

drv_halt:
        bra drv_halt
