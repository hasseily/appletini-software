; ghook.s: the hooks of the tic phase (milestone 10, docs/GAME.md 0.1,
; 3.4): what the game logic calls of the sound, the 2D screens, the
; platform and the zone, which milestones 11 and S4 build. GPL-2, the
; port's own.
;
;   S_StartSound   A = the sound, Y:X = the origin (a mobj handle; $FFFF
;                  none): in test builds the event (tic, kind 0, sound,
;                  origin) appended to the sound event log in GTEST
;                  (GT_SOUNDS, GT_SNDLOG events since the last snapshot);
;                  nothing in the release (milestone S4). Bit 7 of the
;                  sound is upstream's PICKUP_SOUND (bit 15 of its word,
;                  p_inter65.s:35: every sound number is below $40), which
;                  part pickup sets on the pickup sound (pickup.md P5)
;   S_StartSound2  the same, kind 1, the origin $8000 + a sector (its
;                  sound origin, upstream's degenmobj)
;   S_StopSound    Y:X = the origin: kind 2, sound 0
;   hl_add         P_CheckSight's same-pair hit (docs/GAME.md 1.8):
;                  (tic, t1 GT_0-1, t2 GT_2-3) appended to the hit log
;                  (GT_HITS, GT_HITLOG); part sight calls it
;   I_GetTime      test builds: the tic stream's next value (GT_TIMES, 4
;                  bytes each; GT_TIMEP the next) in GA_0-3, its low word in
;                  A:X; a stream at its end is a stop (GS_STREAM); the
;                  release: the platform's clock (milestone 11: a stop here)
;   AM_Stop, ST_Start, HU_Start, AM_Ticker, F_LoadScreen, Z_CheckHeap,
;   D_PageTicker, ST_TickerHook, HU_TickerHook
;                  nothing (milestone 11's screens; flow's st_tick and
;                  hu_tick call the last two, which the play build's
;                  dl_hook.s makes the status bar's and the HUD's tickers:
;                  docs/m11-parts/design.md R4, R5). Part damage's killMobj
;                  calls AM_Stop whatever the automap's state (upstream
;                  only when automapmode & AM_ACTIVE, p_inter65.s:1052-1056:
;                  the native keeps no automapmode), so milestone 11's
;                  AM_Stop must test the automap's state itself
;                  (damage.md R4)
;   D_AdvanceDemo  the demo has ended: GT_FLAGS bit 0 (the lockstep driver
;                  ends the run after the tic)
;   W_StartInter   the intermission's pictures and music are milestone 11's;
;                  then flow's WI_Start (FCALL)
;   W_StartFinale, F_Ticker
;                  stops (GS_FINALE): the finale is milestone 11's
;   I_Error        a stop (GS_ERROR)
;   Z_MallocLevel, Z_CallocLevel, Z_CallocLevSpec, Z_Free
;                  stops (GS_ZONE): the native pools are gthink.s's

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export S_StartSound, S_StartSound2, S_StopSound, hl_add
        .export I_GetTime, AM_Stop, ST_Start, HU_Start, AM_Ticker
        .export F_LoadScreen, Z_CheckHeap, D_PageTicker, D_AdvanceDemo
        .export W_StartInter, W_StartFinale, F_Ticker, I_Error
        .export Z_MallocLevel, Z_CallocLevel, Z_CallocLevSpec, Z_Free
        .export ST_TickerHook, HU_TickerHook
        .import g_stop, far_get, far_put, fc_call, fc_unbuilt
.ifdef TESTBUILD
        .import dg_tcount
.endif

        .segment "LOADW"

S_StartSound:
        sty hk_y
        ldy #0
        bra snd
S_StartSound2:
        sty hk_y
        ldy #1
        bra snd
S_StopSound:
        sty hk_y
        lda #0
        ldy #2
snd:
.ifdef TESTBUILD
        sta hk_ev+3             ; the event: tic, kind, sound, origin
        sty hk_ev+2
        stx hk_ev+4
        lda hk_y
        sta hk_ev+5
        lda G_GAMETIC
        sta hk_ev
        lda G_GAMETIC+1
        sta hk_ev+1
        lda #<GT_SOUNDS
        ldx #>GT_SOUNDS
        ldy #SOUND_EVENT
        jmp log_event
.else
        rts
.endif

; hl_add: a same-pair hit (GT_0-1 t1, GT_2-3 t2)
hl_add:
.ifdef TESTBUILD
        lda G_GAMETIC
        sta hk_ev
        lda G_GAMETIC+1
        sta hk_ev+1
        ldx #3
:       lda GT_0,x
        sta hk_ev+2,x
        dex
        bpl :-
        lda #<GT_HITS
        ldx #>GT_HITS
        ldy #HIT_EVENT
        ; (on into log_event with the hit log's counter)
        pha
        lda #<GT_HITLOG
        sta GO_P
        lda #>GT_HITLOG
        sta GO_P+1
        pla
        jmp log_to
.else
        rts
.endif

.ifdef TESTBUILD
; log_event: hk_ev (Y bytes) appended to the sound log at GTEST A:X
log_event:
        pha
        lda #<GT_SNDLOG
        sta GO_P
        lda #>GT_SNDLOG
        sta GO_P+1
        pla
; log_to: hk_ev (Y bytes) appended to the log at GTEST A:X whose count is
; at (GO_P); a full log is a stop (GS_DRIVER)
log_to: sta GO_T
        stx GO_T+1
        sty FA_N
        ldy #1                  ; the count
        lda (GO_P),y
        sta GO_J
        lda (GO_P)
        sta GO_I
        cmp #<GT_LOG_MAX
        lda GO_J
        sbc #>GT_LOG_MAX
        bcc :+
        lda #GS_DRIVER          ; (a full log)
        jmp g_stop
:       ldy FA_N                ; GTEST GO_T + count * size
        stz FA_DST
        stz FA_DST+1
:       clc
        lda FA_DST
        adc GO_I
        sta FA_DST
        lda FA_DST+1
        adc GO_J
        sta FA_DST+1
        dey
        bne :-
        clc
        lda FA_DST
        adc GO_T
        sta FA_DST
        lda FA_DST+1
        adc GO_T+1
        sta FA_DST+1
        lda #<hk_ev
        sta FA_SRC
        lda #>hk_ev
        sta FA_SRC+1
        lda #GTEST
        sta FA_BANK
        jsr far_put
        lda (GO_P)              ; the count + 1
        inc a
        sta (GO_P)
        bne :+
        ldy #1
        lda (GO_P),y
        inc a
        sta (GO_P),y
:       rts
GT_LOG_MAX = 160                ; events a tic in each log
        .assert GT_LOG_MAX * SOUND_EVENT <= GT_HITS - GT_SOUNDS, error,  "the sound log"
        .assert GT_LOG_MAX * HIT_EVENT <= $0400, error, "the hit log"
.endif

; I_GetTime: the stream's next value
I_GetTime:
.ifdef TESTBUILD
        lda GT_TIMEP            ; GTEST GT_TIMES + 4 (index + 1); its first
        sta GO_P                ;   word is the count of values
        lda GT_TIMEP+1
        sta GO_P+1
        lda GO_P
        cmp dg_tcount           ; (the driver's, in the card: core data
        lda GO_P+1              ;   is reloaded at each load)
        sbc dg_tcount+1
        bcc :+
        lda #GS_STREAM
        jmp g_stop
:       asl GO_P
        rol GO_P+1
        asl GO_P
        rol GO_P+1
        clc
        lda GO_P
        adc #<(GT_TIMES + 4)
        sta FA_SRC
        lda GO_P+1
        adc #>(GT_TIMES + 4)
        sta FA_SRC+1
        lda #GTEST
        sta FA_BANK
        lda #<GA_0
        sta FA_DST
        lda #>GA_0
        sta FA_DST+1
        lda #4
        sta FA_N
        jsr far_get
        inc GT_TIMEP
        bne :+
        inc GT_TIMEP+1
:       lda GA_0
        ldx GA_0+1
        rts
.else
        lda #GS_DRIVER
        jmp g_stop
.endif

AM_Stop:
ST_Start:
HU_Start:
AM_Ticker:
F_LoadScreen:
Z_CheckHeap:
D_PageTicker:
ST_TickerHook:
HU_TickerHook:
        rts

D_AdvanceDemo:
        lda GT_FLAGS
        ora #1
        sta GT_FLAGS
        rts

W_StartInter:
        FCALL WI_Start
        rts

W_StartFinale:
F_Ticker:
        lda #GS_FINALE
        jmp g_stop

I_Error:
        lda #GS_ERROR
        jmp g_stop

Z_MallocLevel:
Z_CallocLevel:
Z_CallocLevSpec:
Z_Free:
        lda #GS_ZONE
        jmp g_stop

; the event being logged, the origin's high byte
hk_ev:  .res 8
hk_y:   .res 1
        .export hk_y
