; dl_brain.s: the main loop's brain (docs/PLAY.md), in the tic image's
; group DLG_BRAIN: what upstream's d_main65.s does around the tics
; (D_DoomLoop's tryRunTics and runTic, D_PostEvent's routing, D_StartTitle)
; and g_game65.s's G_Responder and m_cheat65.s's matching of typed keys
; (C_Responder's effects are part pickup's). A GPL-2 derivative of
; upstream's src/iigs/d_main65.s, g_game65.s and m_cheat65.s (Doom8088:
; Apple IIgs Edition, GPL-2).
;
; The kernel (dl_kern.s) calls dl_brain with the tic image and its planes
; in W and DL_CODE the entry:
;
;   E_BOOT    the settings' defaults, ST_Init's state, G_ReloadDefaults,
;             D_StartTitle, then the boot's list (DLINIT: the static
;             tables; MENUW's, WIW's and FINW's inits)
;   E_FRAME   a frame: a new tic waited for; the events (the queue's);
;             buildNewTiccmds; the tics
;             (runTic: D_DoAdvanceDemo when due, G_Ticker, gametic + 1);
;             the frame's list (dl_disp.s)
;   E_RESUME  after a level's load (the load protocol, docs/GAME.md):
;             g_resume (part flow's continuation), the keys up, S_Start,
;             then G_Ticker again at its action loop (part tic's gt_loop,
;             as its driver's g_tresume), and the frame's other tics
;   E_EVENT   after AMAPW's am_responder had the queue's head: taken, or
;             on to G_Responder
;   E_MENU    after the menu's frames: its request (a new game, the end of
;             the game, the quit, the benchmark; SAVE SETTINGS: DLINIT's
;             dli_save, then the menu again; a game's load or save: none
;             in this version), then a frame
;
; The menu benchmark (m_menu65.s's bmStart, bmStop, bmDone; docs/PLAY.md,
; the benchmark): REQ_BENCH sets timingdemo and plays demo3 at the normal
; tic rate (G_DeferedPlayDemo); its frames are the level views drawn
; (DL_VIEWS, dl_disp.s's count) from then on. At demo3's end G_CheckDemo-
; Status's timingdemo branch calls the hook G_TimeDemoEnd (dl_hook.s): the
; FPS text into MENUW's M_BFPS, the message MSG_BENCH, DL_BENCH $80; the
; brain then opens the menu (its page m2_bench) before the frame's other
; tics, and the next tic ends the demo (the title loop goes on). Escape
; while it runs stops it with no result (bmStop), then opens the menu.
;
; Every byte that lives from one entry to the next is in main's DLM block
; (play.inc): the tic image's own bytes are reloaded with it every frame.

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

        .import go_reset, g_resume, fc_call, fc_unbuilt, pl_time
        .import fs_restore
        .import far_get, far_put
        .import c_build
        .import c_display, c_loadlist, c_bootlist, c_menulist, c_cplist
        .import c_amlist, c_quitlist, c_savelist, c_setlist
        .import h_sstart, sc_update, st_init, d_doadvance, s_rinit
        .import s_level
.if GP_G_Ticker_B
        .import gt_loop
.endif
        .export dl_brain, b_starttitle, dl_bwait, b_tick
        .import bt_rows, bt_start, bt_stop, bt_close
        .export DL_BENCH, DL_BVIEW, DL_BRT      ; (in the label file: the
                                                ;   tests' benchmark bytes)

        .segment "DLGB"
FC_HERE .set DLG_BRAIN

dl_brain:
        jsr go_reset            ; the caches' tags were another image's
        lda DL_CODE
        asl a
        tax
        jsr b_go
        jsr fs_restore          ; the frame slots' colormap bytes back
                                ;   (gcall.s): every way out of the tic
                                ;   phase to a replay passes here, the
                                ;   frame's, a load's, the menu's, the
                                ;   intermission's, the benchmark's
dl_rsback:                      ; (the restore's end)
        lda BT_PH               ; the benchmark timed: the tic phase ends
        beq :+                  ;   here (docs/PLAY.md, the benchmark)
        lda BT_NX
        DLCALL DLG_DISP, bt_close
:       rts
b_go:   jmp (b_ent,x)
b_ent:  .addr b_boot, b_frame, b_resume, b_event, b_menu

; ---------------------------------------------------------------------------
; E_BOOT (D_DoomMain's part after the subsystems: docs/PLAY.md)
; ---------------------------------------------------------------------------
b_boot:
        DLCALL DLG_SND, st_init         ; ST_Init's state
        DLCALL DLG_SND, s_rinit         ; the renderer's statics
        FCALL G_ReloadDefaults
        lda #1                          ; showMessages (m_menu65.s's 1)
        sta G_SHOWMSG
        stz G_SHOWMSG+1
        lda #15                         ; snd_SfxVolume (s_sound65.s's 15)
        sta SND_SFXVOL
        lda #$FF                        ; no song plays
        sta DL_SONG
        jsr pl_time
        sta DL_LASTM
        stx DL_LASTM+1
        lda G_GAMETIC
        sta DL_MAKETIC
        lda G_GAMETIC+1
        sta DL_MAKETIC+1
        jsr b_starttitle
        DLCALL DLG_DISP, c_bootlist
        rts

; b_starttitle: D_StartTitle: no game action, the demo sequence from its
; start (at the next tic: advancedemo)
b_starttitle:
        stz G_GAMEACTION
        stz G_GAMEACTION+1
        lda #$FF
        sta DL_DEMOSEQ
        lda #1
        sta DL_ADVDEMO
        rts

; ---------------------------------------------------------------------------
; E_FRAME: d_main65.s's doomLoop and tryRunTics
; ---------------------------------------------------------------------------
b_frame:
        jsr b_settings
dl_bwait:
        jsr pl_time             ; a new tic (35 frames a second at most;
        cmp DL_LASTM            ;   a2vm's idle loop)
        beq dl_bwait
b_cont: jsr b_events            ; C set: a list (the menu, the automap)
        bcs b_rts
        DLCALL DLG_CMD, c_build ; buildNewTiccmds
        stz DL_TICS
        sec                     ; runtics = maketic - gametic
        lda DL_MAKETIC
        sbc G_GAMETIC
        sta DL_RUN
b_run:  bit DL_BENCH              ; the benchmark's result: the menu's
        bmi b_bres              ;   page now (bmDone's uiOpen)
        lda DL_RUN
        beq b_disp
        jsr b_runtic
        bcs b_rts               ; (a load: its list)
        dec DL_RUN
        bra b_run
b_disp: DLCALL DLG_HOOK, sc_update      ; S_UpdateSounds (musFrame)
        DLCALL DLG_DISP, c_display      ; the frame's list
b_rts:  rts
b_bres: stz DL_BENCH
        DLCALL DLG_CMD, bt_rows         ; the phases' rows of the page
        DLCALL DLG_DISP, c_menulist
        rts

; b_runtic: runTic: the demo sequence when it advances, G_Ticker, gametic
; + 1 (M_Ticker: the menu's, MENUW's, runs in its paused frames only:
; docs/PLAY.md). C set: G_Ticker needs a load (its list is written).
b_runtic:
        lda DL_ADVDEMO
        beq b_tick
        DLCALL DLG_SND, d_doadvance
b_tick: GTICKER
b_after:
        cmp #GT_LOAD
        bne :+
        DLCALL DLG_DISP, c_loadlist
        sec
        rts
:       inc DL_TICS
        inc G_GAMETIC
        bne :+
        inc G_GAMETIC+1
        bne :+
        inc G_GAMETIC+2
        bne :+
        inc G_GAMETIC+3
:       clc
        rts

; ---------------------------------------------------------------------------
; E_RESUME: the load's continuation
; ---------------------------------------------------------------------------
b_resume:
        lda DL_BENCH            ; the benchmark's load done: its timing
        cmp #1                  ;   starts (docs/PLAY.md, the benchmark)
        bne :+
        lda BT_PH
        bne :+
        DLCALL DLG_DISP, bt_start
:       jsr g_resume            ; (part flow: the action's tail)
        ldx #NUMKEYS - 1        ; doLoadLevel: every key up
:       stz DL_KEYS,x
        dex
        bpl :-
        lda #DF_PALLEVEL        ; the level's tints at its first frame
        tsb DL_FLAGS
        DLCALL DLG_SND, s_level ; its frame block fields (nodes, sky)
        DLCALL DLG_HOOK, h_sstart       ; S_Start: the sounds stop, the
                                        ;   level's song
        jsr b_tickr             ; G_Ticker again, from its action loop
        bcs b_rts
        dec DL_RUN
        jmp b_run
b_tickr:
        GTRESUME
        bra b_after

; ---------------------------------------------------------------------------
; E_EVENT: AMAPW's answer for the queue's head
; ---------------------------------------------------------------------------
b_event:
        lda DL_RES
        beq :+
        jsr ev_pop              ; taken by the automap
        stz DL_EVST
        jmp b_cont
:       lda #1                  ; left: on to G_Responder
        sta DL_EVST
        jmp b_cont

; ---------------------------------------------------------------------------
; E_MENU: the menu's request (M_REQ, M_REQARG, M_RELOAD in MENUW's block in
; S2STATE, then 0 there)
; ---------------------------------------------------------------------------
b_menu:
        jsr m_reqarg
        jsr far_get
        stz GT_3
        stz GT_4
        stz GT_5
        jsr m_reqarg
        lda #<GT_3
        sta FA_SRC
        stz FA_SRC+1
        lda #<(SS_MENUW + M_REQ - MENUW_STATE)
        sta FA_DST
        lda #>(SS_MENUW + M_REQ - MENUW_STATE)
        sta FA_DST+1
        jsr far_put
        lda GT_2                ; a new gamma: PALW's tints before the
        beq :+                  ;   next level frame
        lda #DF_PALGAMMA
        tsb DL_FLAGS
:       lda GT_0
        cmp #REQ_NEWGAME        ; G_DeferedInitNew(the skill)
        bne :+
        lda GT_1
        ldx #0
        FCALL G_DeferedInitNew
        bra @frame
:       cmp #REQ_ENDGAME        ; G_CheckDemoStatus when a single demo
        bne :+                  ;   plays, then D_StartTitle
        lda GT_1
        beq @title
        FCALL G_CheckDemoStatus
@title: jsr b_starttitle
        bra @frame
:       cmp #REQ_QUIT
        bne :+
        DLCALL DLG_DISP, c_quitlist
        rts
:       cmp #REQ_SAVESET        ; G_SaveSettings: the menu stays
        bne :+
        DLCALL DLG_DISP, c_setlist
        rts
:       cmp #REQ_BENCH
        bne @frame
        jsr b_bench
@frame: jmp b_frame             ; (REQ_LOAD, REQ_SAVE: none in this
                                ;   version)

; b_bench: bmStart (the menu is closed: s2_menu.s's r_vwitem): timingdemo
; 1, the frames counted from the views drawn now, G_DeferedPlayDemo
; ("demo3": dl_snd.s's reference to its name). starttime is doPlayDemo's
; (I_GetTime after the load), as upstream's.
b_bench:
        lda #1
        sta G_TIMINGDEMO
        stz G_TIMINGDEMO+1
        sta DL_BENCH
        lda DL_VIEWS
        sta DL_BVIEW
        lda DL_VIEWS+1
        sta DL_BVIEW+1
        lda #1                  ; (tag 1, the symbol, offset 0)
        sta GA_0
        lda #<SYM_d_main_strDemo3
        sta GA_1
        lda #>SYM_d_main_strDemo3
        sta GA_2
        stz GA_3
        stz GA_4
        FCALL G_DeferedPlayDemo
        rts

; b_bstop: bmStop: Escape while the benchmark runs: timingdemo 0, no
; result, G_CheckDemoStatus (the demo ends: the title loop's next step)
b_bstop:
        DLCALL DLG_DISP, bt_stop        ; (its timing too)
        stz DL_BENCH
        stz G_TIMINGDEMO
        stz G_TIMINGDEMO+1
        FCALL G_CheckDemoStatus
        rts
; m_reqarg: far_get's arguments for the 3 request bytes into GT_0-2
m_reqarg:
        lda #S2STATE
        sta FA_BANK
        lda #<(SS_MENUW + M_REQ - MENUW_STATE)
        sta FA_SRC
        lda #>(SS_MENUW + M_REQ - MENUW_STATE)
        sta FA_SRC+1
        lda #GT_0
        sta FA_DST
        stz FA_DST+1
        lda #3
        sta FA_N
        rts
        .assert M_REQARG = M_REQ + 1 && M_RELOAD = M_REQ + 2, error, "M_REQ"

; b_settings: the menu's settings the tic command reads (SS_SETTINGS: +0
; always run, +2 the mouse on, +3 its speed)
b_settings:
        lda #S2STATE
        sta FA_BANK
        lda #<SS_SETTINGS
        sta FA_SRC
        lda #>SS_SETTINGS
        sta FA_SRC+1
        lda #GT_0
        sta FA_DST
        stz FA_DST+1
        lda #4
        sta FA_N
        jsr far_get
        lda GT_0
        sta DL_SETRUN
        lda GT_2
        sta DL_SETMOUSE
        lda GT_3
        sta DL_SETMSPD
        rts

; ---------------------------------------------------------------------------
; The events: the queue's, in order. C set: a step list was written (the
; queue's head waits for another image's responder). (The keys a menu up
; does not eat went to gamekeydown in the kernel's K_MENU: docs/PLAY.md)
; ---------------------------------------------------------------------------
b_events:
@queue: ldx PL_QHEAD
        cpx PL_QTAIL
        beq @none
        lda PL_QUEUE,x
        sta DL_EV
        lda PL_QUEUE+1,x
        sta DL_EV+1
        lda PL_QUEUE+2,x
        sta DL_EV+2
        jsr ev_route
        cmp #1
        beq @list
        pha
        jsr ev_pop
        stz DL_EVST
        pla
        beq @queue
@list:  sec
        rts
@none:  clc
        rts

; ev_pop: the queue's head taken (PL_QHEAD: the consumer's, D_PostEvent's)
ev_pop: lda PL_QHEAD
        clc
        adc #PL_EVENT_SIZE
        cmp #PL_EVENTS * PL_EVENT_SIZE
        bcc :+
        lda #0
:       sta PL_QHEAD
        rts

; ---------------------------------------------------------------------------
; ev_route: D_PostEvent of DL_EV: M_Responder with no menu (MENUW's vwKeys:
; Escape opens the menu; the view size's keys eaten), then in a level the
; cheats (C_Responder) and the automap (AM_Responder, AMAPW), then
; G_Responder. A = 0 done, 1 a list written (the event stays at the
; queue's head for that image's responder), 2 a list written, the event
; taken.
; ---------------------------------------------------------------------------
ev_route:
        lda G_GAMETIC+3         ; gametic < 3: no event (D_PostEvent)
        ora G_GAMETIC+2
        ora G_GAMETIC+1
        bne :+
        lda G_GAMETIC
        cmp #3
        bcs :+
        lda #0
        rts
:       lda DL_EV+2             ; (data1 past $FF: no key of ours)
        bne @game
        lda DL_EV
        bne @nomenu             ; (M_Responder takes key downs only)
        lda DL_EV+1
        cmp #KEY_ESCAPE
        bne @zoom
        lda DL_BENCH            ; the benchmark runs: bmStop first
        beq :+
        jsr b_bstop
:       DLCALL DLG_DISP, c_menulist
        lda #1
        rts
@zoom:  cmp #KEY_ZOOMOUT        ; the view's size: the full view only
        beq :+                  ;   (this version): eaten in a level
        cmp #KEY_ZOOMIN         ;   without the automap, as vwKeys
        bne @nomenu
:       lda G_GAMESTATE
        bne @nomenu
        lda AUTOMAP
        and #AM_ACTIVE
        bne @nomenu
        lda #0
        rts
@nomenu:
        lda G_GAMESTATE         ; a level: the cheats, the automap
        bne @game
        lda DL_EV
        bne @am
        lda DL_EV+2             ; a character key down: the cheats
        bne @am
        lda DL_EV+1
        cmp #NUMKEYS
        bcc @am
        jsr cht_match
        bcc @am
        FCALL C_Responder       ; (A: the cheat's number)
        lda #0
        rts
@am:    lda DL_EVST             ; the automap asked already: no
        bne @game
        jsr am_wants
        bcc @game
        DLCALL DLG_DISP, c_amlist
        lda #1
        rts
; G_Responder (g_game65.s:517-555)
@game:  lda G_GAMEACTION
        ora G_GAMEACTION+1
        bne @keys
        lda G_DEMOPLAY
        ora G_DEMOPLAY+1
        bne @demo
        lda G_GAMESTATE
        cmp #UC_GS_DEMOSCREEN
        bne @keys
@demo:  lda G_GAMESTATE         ; the title page: a key down opens the
        cmp #UC_GS_DEMOSCREEN   ;   menu (M_StartControlPanel), without
        bne @done               ;   the automap; a demo: nothing
        lda AUTOMAP
        and #AM_ACTIVE
        bne @done
        lda DL_EV
        bne @done
        DLCALL DLG_DISP, c_cplist
        lda #2
        rts
@keys:  lda DL_EV+2             ; gamekeydown of a Doom key
        bne @done
        ldx DL_EV+1
        cpx #NUMKEYS
        bcs @done
        lda DL_EV
        cmp #EV_KEYUP
        bne :+
        stz DL_KEYS,x
        bra @done
:       cmp #EV_KEYDOWN
        bne @done
        lda #1
        sta DL_KEYS,x
@done:  lda #0
        rts

; am_wants: carry set when AM_Responder may take DL_EV (am_map65.s:244-
; 360): the map key's key down when the map is off; when it is on, the
; keys it reads (the pans, the map key, follow, the zooms), down or up
am_wants:
        lda AUTOMAP
        and #AM_ACTIVE
        bne @on
        lda DL_EV
        bne @no
        lda DL_EV+1
        cmp #KEY_MAP
        beq @yes
@no:    clc
        rts
@on:    lda DL_EV+1
        ldx #AM_KEYS_N - 1
:       cmp am_keys,x
        beq @yes
        dex
        bpl :-
        clc
        rts
@yes:   sec
        rts
am_keys:
        .byte KEY_RIGHT, KEY_LEFT, KEY_UP, KEY_DOWN, KEY_MAP, CH_FOLLOW
        .byte KEY_ZOOMOUT, KEY_ZOOMIN
AM_KEYS_N = * - am_keys

; ---------------------------------------------------------------------------
; cht_match: m_cheat65.s's C_Responder's matching (m_cheat65.s:73-117):
; the character DL_EV+1 against each sequence, in the table's order; a
; character that does not match starts the sequence again (without a new
; match); carry set and A = the number of the first cheat it completes
; (its sequence starts again), else carry clear
; ---------------------------------------------------------------------------
cht_match:
        ldx #0
@each:  lda cht_start,x
        clc
        adc DL_CHT,x
        tay
        lda cht_seqs,y
        cmp DL_EV+1
        bne @miss
        inc DL_CHT,x
        iny
        bra @end
@miss:  stz DL_CHT,x
        ldy cht_start,x
@end:   lda cht_seqs,y
        bne @next
        stz DL_CHT,x
        txa
        sec
        rts
@next:  inx
        cpx #NUMCHEATS
        bne @each
        clc
        rts

cht_seqs:
c0:     .byte "idchoppers", 0
c1:     .byte "iddqd", 0
c2:     .byte "idkfa", 0
c3:     .byte "idfa", 0
c4:     .byte "idspispopd", 0
c5:     .byte "idbeholdv", 0
c6:     .byte "idbeholds", 0
c7:     .byte "idbeholdi", 0
c8:     .byte "idbeholdr", 0
c9:     .byte "idbeholda", 0
c10:    .byte "idbeholdl", 0
c11:    .byte "idclev", 0
c12:    .byte "idend", 0
c13:    .byte "idrocket", 0
c14:    .byte "idrate", 0
cht_end:
cht_start:
        .byte c0 - cht_seqs, c1 - cht_seqs, c2 - cht_seqs, c3 - cht_seqs
        .byte c4 - cht_seqs, c5 - cht_seqs, c6 - cht_seqs, c7 - cht_seqs
        .byte c8 - cht_seqs, c9 - cht_seqs, c10 - cht_seqs, c11 - cht_seqs
        .byte c12 - cht_seqs, c13 - cht_seqs, c14 - cht_seqs
        .assert cht_end - cht_seqs < 256, error, "the sequences"
        .assert * - cht_start = NUMCHEATS, error, "the cheats"
