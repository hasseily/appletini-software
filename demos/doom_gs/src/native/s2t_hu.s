; s2t_hu.s: the HUD's tic side (docs/SCREENS.md, the HUD; part s2hud). A
; tic-side module: the game's tic image links it and calls it with
; docs/GAME.md's conventions. GPL-2: rewritten from upstream's
; src/iigs/hu_stuff65.s (Doom8088: Apple IIgs Edition, GPL-2), HU_Ticker and
; HU_Start, without what the game makes (flow's hu_tick clears
; player.message and G_MSGKEEP; the HU_Start hook clears G_MSGKEEP).
;
;   hu_ticker  HU_Ticker [R hu_stuff65.s:244-276] but the clears: the
;              counter's decrement and message_on 0 at its end, then, when
;              messages are on or kept (G_SHOWMSG, G_MSGKEEP) and
;              player.message is set, the line's message id, message_on,
;              message_new and the counter HU_MSGTIMEOUT. Flow's
;              hu_tick calls it first, then makes its clears.
;              It runs on every tic: assembled with PLAY_TIC (play.mk's
;              tic image) the module's code is in the core's segment
;              LOADW, where dl_hook.s's HU_TickerHook jumps to it
;              without a group load (docs/SPEED.md); without PLAY_TIC it
;              is assembled in S2CODE.
;   hu_start   HU_Start's state [R hu_stuff65.s:94-118]: message_on 0, the
;              line empty (HU_MSGID $FFFF: upstream's strcpy of ""), the
;              title's map. The HU_Start hook calls it and clears
;              G_MSGKEEP.
;
; Their state is the card's tic-side block (s2layout S2T_FIELDS: HU_ON,
; HU_NEW, HU_COUNTER, HU_MSGID, HU_TITLEMAP at S2T_BASE); P2DW's HUD reads
; it at frame time. The message's id is the game's: player.message is
; a reference (tag, id, offset; tag 0 is NULL), its id the symbol's index
; in llayout.symbol_list(); tools/native/s2msgs.py gives each message id
; its text in P2DW. A changes; X, Y kept; no zero page.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2hud.inc"

        .export hu_ticker, hu_start

HU_MSGTIMEOUT = 4 * 35          ; 4 * TICRATE [R hu_stuff65.s:24]

.ifdef PLAY_TIC
        .segment "LOADW"        ; (the play build's tic image: the core)
.else
        .segment "S2CODE"
.endif

hu_ticker:
        lda HU_COUNTER          ; the counter, before a new message: at its
        ora HU_COUNTER+1        ;   end the line goes
        beq @take
        lda HU_COUNTER
        bne :+
        dec HU_COUNTER+1
:       dec HU_COUNTER
        lda HU_COUNTER
        ora HU_COUNTER+1
        bne @take
        stz HU_ON
@take:  lda HU_SHOWMSG          ; messages on, or kept ("Messages Off")
        ora HU_SHOWMSG+1
        ora HU_KEEP
        ora HU_KEEP+1
        beq @done
        lda HU_PLMSG            ; a message (its tag: 0 is NULL)
        beq @done
        lda HU_PLMSG+1          ; the line: the message's id
        sta HU_MSGID
        lda HU_PLMSG+2
        sta HU_MSGID+1
        lda #1
        sta HU_ON
        sta HU_NEW
        lda #<HU_MSGTIMEOUT
        sta HU_COUNTER
        lda #>HU_MSGTIMEOUT
        sta HU_COUNTER+1
@done:  rts

hu_start:
        stz HU_ON
        lda #<HU_NONE_ID        ; the line empty
        sta HU_MSGID
        lda #>HU_NONE_ID
        sta HU_MSGID+1
        lda HU_GAMEMAP          ; the title's map
        sta HU_TITLEMAP
        rts
