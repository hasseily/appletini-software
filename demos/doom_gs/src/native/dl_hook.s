; dl_hook.s: the hooks of the tic phase in the playable game (docs/PLAY.md
; 2.3): the play build links this file in place of ghook.s, the test
; builds' (milestone 10's skeleton, docs/GAME.md 3.4), with every one of its
; exports (tests/test_play_glue.py checks the two lists). GPL-2, the
; port's own; the hooks' targets are upstream's routines, rewritten by
; milestones 11 and S4 (the status bar's, the HUD's, the finale's tickers,
; the sound channels) and here.
;
; The core holds only the hooks' entries (the core is the placement's: as
; few bytes as ghook.s's); their bodies are in the group DLG_HOOK, reached
; through fc_call:
;
;   S_StartSound  A the sound (bit 7 upstream's PICKUP_SOUND), Y:X the
;                 origin (a mobj handle, $FFFF none): fx_chan's sc_start
;                 with the origin's kind (none, the player's mobj, a mobj),
;                 its handle and its x, y (the object API)
;   S_StartSound2 the same, Y:X $8000 + a sector: its sound origin (LVG1's
;                 SG_SOUNDX, SG_SOUNDY): sc_start2 (the fake mobj FM)
;   S_StopSound   Y:X the origin: sc_stop
;   I_GetTime     the platform's clock (pl_time): GA_0-3 the tics, A:X the
;                 low word (ghook.s's contract)
;   AM_Stop       the automap off (request R6): AUTOMAP's AM_ACTIVE clear
;                 and S2_MAIL's MAIL_AMSTOP set, only when it was on (part
;                 damage calls it whatever the automap's state: damage.md
;                 R4)
;   ST_Start      s2t_st's st_start (request R4)
;   HU_Start      s2t_hu's hu_start, then G_MSGKEEP 0 (request R5)
;   AM_Ticker, Z_CheckHeap   nothing (the automap's ticker runs at the
;                 frame, A = the frame's tics: AMAPW's am_frame, OVLW's
;                 am_ovl; the zone is the native pools)
;   F_LoadScreen  the loading screen at the load (DF_LOADSCR: the load's
;                 list draws it with FINW's fin_load before the sign)
;   D_PageTicker  d_main65.s's: pagetic - 1 while no menu is up; below 0
;                 the demo sequence advances (advancedemo)
;   D_AdvanceDemo advancedemo = 1 (G_CheckDemoStatus at a demo's end)
;   W_StartInter  the intermission's music (D_INTER, looping; its pictures
;                 are WIW's at its first frame), then part flow's WI_Start
;   W_StartFinale the finale's music (D_VICTOR, looping), then s2t_fin's
;                 f_start (F_StartFinale: the game state GS_FINALE)
;   F_Ticker      part flow's WI_checkForAccelerate, then s2t_fin's
;                 f_ticker (request S2FIN-4)
;   ST_TickerHook, HU_TickerHook   requests R4 and R5 for part flow: its
;                 st_tick ends with jmp ST_TickerHook with A = M_Random's
;                 value (s2t_st's st_ticker); its hu_tick starts with jsr
;                 HU_TickerHook (s2t_hu's hu_ticker)
;   I_Error, Z_MallocLevel, Z_CallocLevel, Z_CallocLevSpec, Z_Free
;                 stops (GS_ERROR, GS_ZONE), as ghook.s's
;   hl_add        nothing (the test builds' same-pair log)
;
; The core also holds the callback s2t_pos (A:X a handle, A the high
; byte: its x, y, angle into GT_0-11, carry clear; carry set: none;
; FXC_LISTENER the player's mobj), which fx_chan.s (group DLG_HOOK) and
; s2t_st.s (group DLG_SND) call with jsr. The group DLG_HOOK holds the
; hooks' bodies, fx_chan.s's scratch block fxc_scr (live only inside a
; call, and nothing it calls pages a group) and h_sstart (S_Start: every
; channel stopped, then the level's song).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "s2.inc"
        .include "play.inc"
        .include "dl.inc"
        .include "fxchan.inc"

        .export S_StartSound, S_StartSound2, S_StopSound, hl_add
        .export I_GetTime, AM_Stop, ST_Start, HU_Start, AM_Ticker
        .export F_LoadScreen, Z_CheckHeap, D_PageTicker, D_AdvanceDemo
        .export W_StartInter, W_StartFinale, F_Ticker, I_Error
        .export Z_MallocLevel, Z_CallocLevel, Z_CallocLevSpec, Z_Free
        .export hk_y, ST_TickerHook, HU_TickerHook
        .export s2t_pos, fxc_scr, h_sstart
        .import g_stop, fc_call, fc_unbuilt, pl_time, mo_get, sec_get
        .import fx_stopall
        .import sc_start, sc_start2, sc_stop, st_start, st_ticker
        .import hu_start, hu_ticker, f_start, f_ticker, s_song, s_levelsong

; ===========================================================================
; The core's entries
; ===========================================================================
        .segment "LOADW"

S_StartSound:
        jsr fc_call
        .byte DLG_HOOK
        .word h_start
        rts
S_StartSound2:
        jsr fc_call
        .byte DLG_HOOK
        .word h_start2
        rts
S_StopSound:
        jsr fc_call
        .byte DLG_HOOK
        .word h_stop
        rts
I_GetTime:
        jsr pl_time
        sta GA_0
        stx GA_1
        sty GA_2
        lda CLK_TIME3
        sta GA_3
        lda GA_0
        rts
AM_Stop:
        lda AUTOMAP
        and #AM_ACTIVE
        beq AM_Ticker
        lda #AM_ACTIVE
        trb AUTOMAP
        lda #MAIL_AMSTOP
        tsb S2_MAIL
AM_Ticker:
Z_CheckHeap:
hl_add:
        rts
F_LoadScreen:
        lda #DF_LOADSCR
        tsb DL_FLAGS
        rts
D_PageTicker:
        lda G_MENUACTIVE        ; the page waits while the menu is up
        ora G_MENUACTIVE+1
        bne AM_Ticker
        lda DL_PAGETIC          ; pagetic - 1; below 0: advancedemo
        bne :+
        dec DL_PAGETIC+1
:       dec DL_PAGETIC
        lda DL_PAGETIC+1
        bpl AM_Ticker
D_AdvanceDemo:
        lda #1
        sta DL_ADVDEMO
        rts
ST_Start:                       ; s2t_st's st_start (group DLG_SND)
        jsr fc_call
        .byte DLG_SND
        .word st_start
        rts
ST_TickerHook:                  ; A = M_Random's value: st_ticker
        jsr fc_call
        .byte DLG_SND
        .word st_ticker
        rts
HU_Start:
        ldy #HK_HUSTART
        bra hook
W_StartInter:
        ldy #HK_INTER
        bra hook
W_StartFinale:
        ldy #HK_FINALE
        bra hook
F_Ticker:
        ldy #HK_FTICKER
        bra hook
HU_TickerHook:
        ldy #HK_HUTICK
hook:   jsr fc_call
        .byte DLG_HOOK
        .word h_hook
        rts
I_Error:
        lda #GS_ERROR
        jmp g_stop
Z_MallocLevel:
Z_CallocLevel:
Z_CallocLevSpec:
Z_Free:
        lda #GS_ZONE
        jmp g_stop

; ---------------------------------------------------------------------------
; s2t_pos: A:X a handle (A the high byte): x, y, angle into GT_0-11
; ---------------------------------------------------------------------------
s2t_pos:
        cmp #>FXC_LISTENER
        bne @mo
        cpx #<FXC_LISTENER
        bne @mo
        lda G_PLAYER + PL_MO + 1        ; the listener: the player's mobj
        ldx G_PLAYER + PL_MO
@mo:    cmp #$FF                        ; none
        bne :+
        cpx #$FF
        bne :+
        sec
        rts
:       sta GT_0                        ; (mo_get: A low, X high)
        txa
        ldx GT_0
        jsr mo_get
        ldy #7
:       lda (GC_MP),y
        sta GT_0,y
        dey
        bpl :-
        ldy #TH_ANGLO
        lda (GC_MP),y
        sta GT_8
        iny
        lda (GC_MP),y
        sta GT_9
        ldy #TH_ANG
        lda (GC_MP),y
        sta GT_10
        iny
        lda (GC_MP),y
        sta GT_11
        clc
        rts


; ===========================================================================
; The bodies (group DLG_HOOK)
; ===========================================================================
        .segment "DLGH"
FC_HERE .set DLG_HOOK

HK_HUSTART = 0
HK_INTER   = 2
HK_FINALE  = 4
HK_FTICKER = 6
HK_HUTICK  = 8

h_hook: lda hk_tab,y
        sta hk_ret
        lda hk_tab+1,y
        sta hk_ret+1
        jmp (hk_ret)
hk_tab: .addr hk_hustart, hk_inter, hk_finale, hk_fticker, hu_ticker
hk_ret: .res 2

hk_hustart:                     ; HU_Start: hu_start, then G_MSGKEEP 0
        jsr hu_start
        stz G_MSGKEEP
        stz G_MSGKEEP+1
        rts
hk_inter:                       ; W_StartInter: musInter, then WI_Start
        lda #SONG_INTER
        ldx #SONG_LOOP
        DLCALL DLG_SND, s_song
        FCALL WI_Start
        rts
hk_finale:                      ; W_StartFinale: musFinale, F_StartFinale
        lda #SONG_VICTOR
        ldx #SONG_LOOP
        DLCALL DLG_SND, s_song
        jmp f_start
hk_fticker:                     ; F_Ticker: WI_checkForAccelerate first
        FCALL WI_checkForAccelerate
        jmp f_ticker

; ---------------------------------------------------------------------------
; h_start, h_start2, h_stop: the sound hooks' arguments for fx_chan.s
; ---------------------------------------------------------------------------
A_SFX  = FXC_GA + 0
A_KIND = FXC_GA + 2
A_HND  = FXC_GA + 3
A_X    = FXC_GA + 5
A_Y    = FXC_GA + 9

h_start:
        jsr h_sound             ; the sound, the origin's kind and handle
        lda A_KIND
        cmp #ORG_MOBJ
        bne @go
        lda A_HND               ; a mobj: its x, y
        ldx A_HND+1
        jsr mo_get
        ldy #7
:       lda (GC_MP),y           ; (TH_X 0-3, TH_Y 4-7)
        sta A_X,y
        dey
        bpl :-
@go:    jmp sc_start
        .assert TH_X = 0 && TH_Y = 4 && A_Y = A_X + 4, error, "x, y"

h_start2:
        jsr h_sound             ; the sound; the origin a sector's
        txa                     ;   (Y:X = $8000 + the sector)
        jsr sec_get
        ldy #SEC_SIZE + SG_SOUNDY + 3
        ldx #7
:       lda (GC_SP),y
        sta A_X,x
        dey
        dex
        bpl :-
        jmp sc_start2
        .assert SG_SOUNDY = SG_SOUNDX + 4, error, "the sound origin"

h_stop: jsr h_kind
        jmp sc_stop

; h_sound: A_SFX = A's sound (bit 7: PICKUP_SOUND, the word's bit 15),
; then h_kind of Y:X. X kept.
h_sound:
        pha
        and #$7F
        sta A_SFX
        pla
        and #$80
        sta A_SFX+1
; h_kind: the origin Y:X's kind and handle: $FFFF none, the player's mobj,
; another mobj (X kept)
h_kind: stx A_HND
        sty A_HND+1
        lda #ORG_NONE
        cpx #$FF
        bne :+
        cpy #$FF
        beq @set
:       lda #ORG_PLAYER
        cpx G_PLAYER + PL_MO
        bne :+
        cpy G_PLAYER + PL_MO + 1
        beq @set
:       lda #ORG_MOBJ
@set:   sta A_KIND
        rts

; ---------------------------------------------------------------------------
; h_sstart: S_Start [R s_sound65.s:158-172]: every channel stopped (the
; table's channels free, fx.s's fx_stopall: every voice ends, every mailbox
; empty), then the level's song (musLevel)
; ---------------------------------------------------------------------------
h_sstart:
        lda G_GAMESTATE         ; a level's: a demo's or a game's
        bne @rts
        ldx #NUM_CHANNELS * CHAN_SIZE - CHAN_SIZE
:       stz SC_BASE + CH_SFX,x  ; (stopChannel's: each channel free)
        txa
        sec
        sbc #CHAN_SIZE
        tax
        bcs :-
        jsr fx_stopall          ; (the voices end, the mailboxes empty)
        DLCALL DLG_SND, s_levelsong
@rts:   rts

; the channel logic's scratch block (fx_chan.s)
fxc_scr:
        .res 32
hk_y:   .res 1
