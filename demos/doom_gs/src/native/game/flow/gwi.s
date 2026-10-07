; game/flow/gwi.s: part flow of the game (docs/GAME.md, the parts; wave 1),
; the intermission's game side (wi_stuff65.s: WI_Start, WI_End,
; WI_checkForAccelerate, WI_Ticker and the counts, without drawing) and the
; game effects of the status bar's and the HUD's tickers (st_stuff65.s
; ST_Ticker: M_Random; hu_stuff65.s HU_Ticker: the message's clear).
; GPL-2: rewritten from upstream's wi_stuff65.s, st_stuff65.s and
; hu_stuff65.s (Doom8088: Apple IIgs Edition, GPL-2); every divide is
; math.s's.
;
; The intermission's counters are the globals WI_* (llayout.py, docs/GAME.md,
; the globals: they decide the tic of the next load), the level's numbers
; G_WMINFO; the sounds go to the S_StartSound hook (no origin: $FFFF). No
; routine takes an argument: WI_Start reads G_WMINFO (upstream's _Dp[0-3]
; is always _g_wminfo, G_DoCompleted's).
;
;   ST_Ticker (st_tick)  M_Random's call, once a tic in a level, then the
;                        hook ST_TickerHook with A = its value (the face,
;                        the widgets and st_oldhealth are the status bar's:
;                        s2t_st.s)
;   HU_Ticker (hu_tick)  the hook HU_TickerHook first (the HUD's
;                        message line, which reads the message), then
;                        player.message cleared, and
;                        _g_message_dontfuckwithme (G_MSGKEEP), when a
;                        message is set and showMessages (G_SHOWMSG) or
;                        G_MSGKEEP is (the message line, its counter and
;                        its drawing are the HUD's)

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export WI_Start, WI_End, WI_checkForAccelerate, WI_Ticker
        .export ST_Ticker, HU_Ticker, st_tick, hu_tick
        .export times100        ; (for the random check of the helper)
        .import sdiv32, S_StartSound, g_mrandom
        .import ST_TickerHook, HU_TickerHook
        .import fc_call, fc_unbuilt
        .import G_WorldDone

PLR     = G_PLAYER
BT_ATTACK = 1
BT_USE  = 2
SHOWNEXTLOC = 1
SHOWNEXTLOCDELAY = 4

; the scratch block (SB_FLOW: gflow.s's routines are never active with
; these, so the bytes are shared)
WT      = SB_FLOW               ; a total (WI_T, 4)
WN      = SB_FLOW + 4           ; the count being raised: its address (2)
WR      = SB_FLOW + 6           ; a total's value (4)
        .assert SB_FLOW_SIZE >= 10, error, "flow's scratch block"

; ===========================================================================
; WI_Start: the counts from the start (at least 1 kill and 1 item to
; count). WI_End: the counts do not show.
; ===========================================================================
        ROUTINE WI_Start
        stz WI_ACCEL            ; WI_initVariables
        stz WI_ACCEL+1
        stz WI_CNT
        stz WI_CNT+1
        stz WI_BCNT
        stz WI_BCNT+1
        lda G_WMINFO + WM_MAXKILLS
        ora G_WMINFO + WM_MAXKILLS + 1
        ora G_WMINFO + WM_MAXKILLS + 2
        ora G_WMINFO + WM_MAXKILLS + 3
        bne :+
        lda #1                  ; (the low word: 1)
        sta G_WMINFO + WM_MAXKILLS
:       lda G_WMINFO + WM_MAXITEMS
        ora G_WMINFO + WM_MAXITEMS + 1
        ora G_WMINFO + WM_MAXITEMS + 2
        ora G_WMINFO + WM_MAXITEMS + 3
        bne :+
        lda #1
        sta G_WMINFO + WM_MAXITEMS
:       stz WI_STATE            ; WI_initStats: StatCount
        stz WI_STATE+1
        lda #1
        sta WI_SPSTATE
        stz WI_SPSTATE+1
        lda #$FF
        ldx #1
:       sta WI_CNTKILLS,x
        sta WI_CNTSECRET,x
        sta WI_CNTITEMS,x
        sta WI_CNTPAR,x
        dex
        bpl :-
        ldx #3
:       sta WI_CNTTIME,x
        sta WI_CNTTOTAL,x
        dex
        bpl :-
        lda #UC_TICRATE
        sta WI_CNTPAUSE
        stz WI_CNTPAUSE+1
        rts

        ROUTINE WI_End
        lda #$FF
        sta WI_CNTKILLS
        sta WI_CNTKILLS+1
        sta WI_CNTSECRET
        sta WI_CNTSECRET+1
        sta WI_CNTITEMS
        sta WI_CNTITEMS+1
        rts

; ===========================================================================
; WI_checkForAccelerate: a new press of fire or use asks to go on
; ===========================================================================
        ROUTINE WI_checkForAccelerate
        lda PLR + PL_CMD_BUTTONS
        and #BT_ATTACK
        beq @noatk
        lda PLR + PL_ATTACKDOWN
        ora PLR + PL_ATTACKDOWN + 1
        bne :+
        lda #1
        sta WI_ACCEL
        stz WI_ACCEL+1
:       lda #1
        sta PLR + PL_ATTACKDOWN
        stz PLR + PL_ATTACKDOWN + 1
        bra @use
@noatk: stz PLR + PL_ATTACKDOWN
        stz PLR + PL_ATTACKDOWN + 1
@use:   lda PLR + PL_CMD_BUTTONS
        and #BT_USE
        beq @nouse
        lda PLR + PL_USEDOWN
        ora PLR + PL_USEDOWN + 1
        bne :+
        lda #1
        sta WI_ACCEL
        stz WI_ACCEL+1
:       lda #1
        sta PLR + PL_USEDOWN
        stz PLR + PL_USEDOWN + 1
        rts
@nouse: stz PLR + PL_USEDOWN
        stz PLR + PL_USEDOWN + 1
        rts

; ===========================================================================
; WI_Ticker: the stage of the state
; ===========================================================================
        ROUTINE WI_Ticker
        inc WI_BCNT
        bne :+
        inc WI_BCNT+1
:       FCALL WI_checkForAccelerate
        lda WI_STATE
        ora WI_STATE+1
        jeq update_stats
        lda WI_STATE+1
        bmi @nostate
        lda WI_CNT              ; ShowNextLoc: the delay, or a request:
        bne :+                  ;   NoState
        dec WI_CNT+1
:       dec WI_CNT
        lda WI_CNT
        ora WI_CNT+1
        beq @init
        lda WI_ACCEL
        ora WI_ACCEL+1
        bne @init
        lda WI_CNT              ; the pointer blinks
        and #31
        ldx #0
        cmp #20
        bcs :+
        inx
:       stx WI_SNLPTR
        stz WI_SNLPTR+1
        rts
@init:  lda #$FF                ; WI_initNoState
        sta WI_STATE
        sta WI_STATE+1
        stz WI_ACCEL
        stz WI_ACCEL+1
        lda #10
        sta WI_CNT
        stz WI_CNT+1
        rts
@nostate:                       ; updateNoState
        lda WI_CNT
        bne :+
        dec WI_CNT+1
:       dec WI_CNT
        lda WI_CNT
        ora WI_CNT+1
        bne :+
        FCALL G_WorldDone
:       rts

; initShowNextLoc: WI_initShowNextLoc: after map 8 the next world; else
; the map with the next level for 4 s
init_show:
        lda G_GAMEMAP
        cmp #8
        bne :+
        lda G_GAMEMAP+1
        bne :+
        FCALL G_WorldDone
        rts
:       lda #SHOWNEXTLOC
        sta WI_STATE
        stz WI_STATE+1
        stz WI_ACCEL
        stz WI_ACCEL+1
        lda #SHOWNEXTLOCDELAY * UC_TICRATE
        sta WI_CNT
        stz WI_CNT+1
        rts

; spstate_is k: Z set when sp_state is k (16 bits)
.macro SPSTATE_IS k
        .local done
        lda WI_SPSTATE+1
        bne done
        lda WI_SPSTATE
        cmp #k
done:
.endmacro

; update_stats: WI_updateStats: the counts go up in turn (a pause between
; them); a request shows them all at once; then a request goes on
update_stats:
        lda WI_ACCEL
        ora WI_ACCEL+1
        jeq ws_stage
        SPSTATE_IS 10
        jeq ws_stage
        stz WI_ACCEL            ; all at once
        stz WI_ACCEL+1
        jsr kills_total
        lda WR
        sta WI_CNTKILLS
        lda WR+1
        sta WI_CNTKILLS+1
        jsr items_total
        lda WR
        sta WI_CNTITEMS
        lda WR+1
        sta WI_CNTITEMS+1
        jsr secret_total
        lda WR
        sta WI_CNTSECRET
        lda WR+1
        sta WI_CNTSECRET+1
        jsr total_time_total
        ldx #3
:       lda WR,x
        sta WI_CNTTOTAL,x
        dex
        bpl :-
        jsr time_total
        ldx #3
:       lda WR,x
        sta WI_CNTTIME,x
        dex
        bpl :-
        jsr par_total
        lda WR
        sta WI_CNTPAR
        lda WR+1
        sta WI_CNTPAR+1
        jsr sound_barexp
        lda #10
        sta WI_SPSTATE
        stz WI_SPSTATE+1
ws_stage:
        SPSTATE_IS 2
        bne :+
        jsr kills_total         ; kills
        lda #<WI_CNTKILLS
        ldx #>WI_CNTKILLS
        jmp count_up
:       SPSTATE_IS 4
        bne :+
        jsr items_total         ; items
        lda #<WI_CNTITEMS
        ldx #>WI_CNTITEMS
        jmp count_up
:       SPSTATE_IS 6
        bne :+
        jsr secret_total        ; secret
        lda #<WI_CNTSECRET
        ldx #>WI_CNTSECRET
        jmp count_up
:       SPSTATE_IS 8
        bne :+
        jmp count_times
:       SPSTATE_IS 10
        bne @odd
        lda WI_ACCEL            ; the end: a request goes on
        ora WI_ACCEL+1
        beq @rts
        lda #UC_SFX_SGCOCK
        jsr sound
        jmp init_show
@odd:   lda WI_SPSTATE          ; odd: a pause
        and #1
        beq @rts
        lda WI_CNTPAUSE
        bne :+
        dec WI_CNTPAUSE+1
:       dec WI_CNTPAUSE
        lda WI_CNTPAUSE
        ora WI_CNTPAUSE+1
        bne @rts
        inc WI_SPSTATE
        bne :+
        inc WI_SPSTATE+1
:       lda #UC_TICRATE
        sta WI_CNTPAUSE
        stz WI_CNTPAUSE+1
@rts:   rts

; count_up (A:X the address of a count, WR its total): the count goes up
; by 2 (a pistol sound every 4 tics); at the total (int32) or more: the
; total, a sound, the next stage
count_up:
        sta WN
        stx WN+1
        ldx #3                  ; the total
:       lda WR,x
        sta WT,x
        dex
        bpl :-
        lda WN
        sta GT_0
        lda WN+1
        sta GT_1
        clc
        lda (GT_0)
        adc #2
        sta (GT_0)
        ldy #1
        lda (GT_0),y
        adc #0
        sta (GT_0),y
        jsr pistol_sound
        lda WN                  ; count >= total (int16 as int32)
        sta GT_0
        lda WN+1
        sta GT_1
        ldy #1
        lda (GT_0),y
        sta GT_2
        ldx #0
        cmp #$80
        bcc :+
        dex
:       stx GT_3
        lda (GT_0)
        cmp WT
        lda GT_2
        sbc WT+1
        lda GT_3
        sbc WT+2
        lda GT_3
        sbc WT+3
        bvc :+
        eor #$80
:       bmi @rts
        lda WT
        sta (GT_0)
        lda WT+1
        sta (GT_0),y
        jsr sound_barexp
        inc WI_SPSTATE
        bne @rts
        inc WI_SPSTATE+1
@rts:   rts

; count_times: sp_state 8: the times go up by 3 to their totals; then (par
; at its total and the others too) the next stage
count_times:
        jsr pistol_sound
        clc                     ; time += 3, at most its total
        lda WI_CNTTIME
        adc #3
        sta WI_CNTTIME
        bcc :+
        inc WI_CNTTIME+1        ; (upstream's: the high word + 1)
        bne :+
        inc WI_CNTTIME+2
        bne :+
        inc WI_CNTTIME+3
:       jsr time_total
        lda #<WI_CNTTIME
        ldx #>WI_CNTTIME
        jsr cmp_count
        bmi :+
        ldx #3
@t1:    lda WR,x
        sta WI_CNTTIME,x
        dex
        bpl @t1
:       clc                     ; total += 3, at most its total
        lda WI_CNTTOTAL
        adc #3
        sta WI_CNTTOTAL
        bcc :+
        inc WI_CNTTOTAL+1
        bne :+
        inc WI_CNTTOTAL+2
        bne :+
        inc WI_CNTTOTAL+3
:       jsr total_time_total
        lda #<WI_CNTTOTAL
        ldx #>WI_CNTTOTAL
        jsr cmp_count
        bmi :+
        ldx #3
@t2:    lda WR,x
        sta WI_CNTTOTAL,x
        dex
        bpl @t2
:       clc                     ; par += 3
        lda WI_CNTPAR
        adc #3
        sta WI_CNTPAR
        lda WI_CNTPAR+1
        adc #0
        sta WI_CNTPAR+1
        jsr par_total           ; par >= its total: the end
        sec
        lda WI_CNTPAR
        sbc WR
        lda WI_CNTPAR+1
        sbc WR+1
        bvc :+
        eor #$80
:       bmi @rts
        lda WR
        sta WI_CNTPAR
        lda WR+1
        sta WI_CNTPAR+1
        jsr time_total          ; and the times at theirs
        lda #<WI_CNTTIME
        ldx #>WI_CNTTIME
        jsr cmp_count
        bmi @rts
        jsr total_time_total
        lda #<WI_CNTTOTAL
        ldx #>WI_CNTTOTAL
        jsr cmp_count
        bmi @rts
        jsr sound_barexp
        inc WI_SPSTATE
        bne @rts
        inc WI_SPSTATE+1
@rts:   rts

; cmp_count (A:X the address of an int32, WR a value): N set when the
; int32 < WR (signed); WR stays
cmp_count:
        sta GT_0
        stx GT_1
        ldy #0
        lda (GT_0),y
        cmp WR
        iny
        lda (GT_0),y
        sbc WR+1
        iny
        lda (GT_0),y
        sbc WR+2
        iny
        lda (GT_0),y
        sbc WR+3
        bvc :+
        eor #$80
:       ora #0                  ; (N from A)
        rts

; pistol_sound: a pistol sound every 4 tics
pistol_sound:
        lda WI_BCNT
        and #3
        bne :+
        lda #UC_SFX_PISTOL
        jmp sound
:       rts

; sound_barexp: S_StartSound(NULL, sfx_barexp); sound: of A
sound_barexp:
        lda #UC_SFX_BAREXP
sound:  ldx #$FF
        ldy #$FF
        jmp S_StartSound

; kills_total, items_total, secret_total: WR = the total percent (count *
; 100 / maximum, int32; 100 for no secret)
kills_total:
        ldx #WM_SKILLS
        ldy #WM_MAXKILLS
        bra percent
items_total:
        ldx #WM_SITEMS
        ldy #WM_MAXITEMS
        bra percent
secret_total:
        lda G_WMINFO + WM_MAXSECRET
        ora G_WMINFO + WM_MAXSECRET + 1
        ora G_WMINFO + WM_MAXSECRET + 2
        ora G_WMINFO + WM_MAXSECRET + 3
        bne :+
        lda #100
        sta WR
        stz WR+1
        stz WR+2
        stz WR+3
        rts
:       ldx #WM_SSECRET
        ldy #WM_MAXSECRET
percent:
        lda G_WMINFO,y          ; M_B: the maximum
        sta M_B
        lda G_WMINFO+1,y
        sta M_B+1
        lda G_WMINFO+2,y
        sta M_B+2
        lda G_WMINFO+3,y
        sta M_B+3
        lda G_WMINFO,x          ; M_A: the count
        sta M_A
        lda G_WMINFO+1,x
        sta M_A+1
        lda G_WMINFO+2,x
        sta M_A+2
        lda G_WMINFO+3,x
        sta M_A+3
        jsr times100
        jmp div_out

; times100: M_A *= 100 (int32): * 4 + * 32 + * 64 (upstream's times100)
times100:
        jsr @x2
        jsr @x2
        ldx #3                  ; GT_2-5 = * 4
:       lda M_A,x
        sta GT_2,x
        dex
        bpl :-
        jsr @x2                 ; * 32
        jsr @x2
        jsr @x2
        jsr @add
        jsr @x2                 ; * 64
        jsr @add
        ldx #3
:       lda GT_2,x
        sta M_A,x
        dex
        bpl :-
        rts
@x2:    asl M_A
        rol M_A+1
        rol M_A+2
        rol M_A+3
        rts
@add:   clc
        ldx #0
        ldy #4
:       lda GT_2,x
        adc M_A,x
        sta GT_2,x
        inx
        dey
        bne :-
        rts

; time_total, total_time_total: WR = stime / TICRATE, totaltimes / TICRATE
; (int32); par_total: WR = partime / TICRATE (int16 sign extended)
time_total:
        ldx #WM_STIME
        bra seconds
total_time_total:
        ldx #WM_TOTALTIMES
seconds:
        lda G_WMINFO,x
        sta M_A
        lda G_WMINFO+1,x
        sta M_A+1
        lda G_WMINFO+2,x
        sta M_A+2
        lda G_WMINFO+3,x
        sta M_A+3
        bra div_ticrate
par_total:
        lda G_WMINFO + WM_PARTIME
        sta M_A
        lda G_WMINFO + WM_PARTIME + 1
        sta M_A+1
        ldx #0
        cmp #$80
        bcc :+
        dex
:       stx M_A+2
        stx M_A+3
div_ticrate:
        lda #UC_TICRATE
        sta M_B
        stz M_B+1
        stz M_B+2
        stz M_B+3
div_out:
        jsr sdiv32
        ldx #3
:       lda M_R,x
        sta WR,x
        dex
        bpl :-
        rts

; ===========================================================================
; ST_Ticker (st_tick): the status bar's ticker's game effect, M_Random
; ===========================================================================
        ROUTINE ST_Ticker
st_tick:
        jsr g_mrandom           ; M_Random (gthink.s; st_randomnumber is
                                ;   the face's, s2t_st.s)
        jmp ST_TickerHook       ; with A = its value: the status
                                ;   bar's st_ticker (dl_hook.s)

; ===========================================================================
; HU_Ticker (hu_tick): a message of the player taken (cleared) when
; messages are on or the message is kept for the "Messages Off" message
; ===========================================================================
        ROUTINE HU_Ticker
hu_tick:
        jsr HU_TickerHook       ; the HUD's hu_ticker first, which
                                ;   reads the message before the clear
                                ;   (dl_hook.s)
        lda G_SHOWMSG
        ora G_SHOWMSG+1
        ora G_MSGKEEP
        ora G_MSGKEEP+1
        beq @rts
        lda PLR + PL_MESSAGE    ; (its tag: 0 is NULL)
        beq @rts
        ldx #PL_DAMAGECOUNT - PL_MESSAGE - 1
:       stz PLR + PL_MESSAGE,x  ; message = NULL
        dex
        bpl :-
        stz G_MSGKEEP
        stz G_MSGKEEP+1
@rts:   rts
