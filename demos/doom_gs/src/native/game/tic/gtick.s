; game/tic/gtick.s: part tic's game tic (docs/GAME.md: the action table,
; the load protocol). A GPL-2 derivative of upstream's
; g_game65.s (G_Ticker with its action table) and p_map65.s (P_MapEnd)
; (Doom8088: Apple IIgs Edition).
;
;   G_Ticker    the reborn (PST_REBORN: gameaction ga_loadlevel), P_MapEnd;
;               the action loop: while gameaction is not 0 its target
;               (upstream's table jsr (actions-2,x): part flow's loadLevel,
;               doNewGame, doPlayDemo, doCompleted, victory, doWorldDone;
;               the saved games' are stops, GS_SAVEGAME; an action past
;               ga_worlddone, where upstream loops for ever, the stop
;               GS_ACTION); an action that reaches a load returns A =
;               GT_LOAD with G_LOADACT = that action (the load protocol,
;               GAME.md: the driver loads the level, then g_tresume);
;               then the tic's command: paused (the menu up, no demo)
;               basetic + 1, else the ring's command of gametic into the
;               player's, and in a demo readDemoTiccmd; WI_End when the
;               intermission is left (prevgamestate); the ticker of the game
;               state: a level's P_Ticker, ST_Ticker, the AM_Ticker hook,
;               HU_Ticker; the intermission's WI_Ticker; the F_Ticker and
;               D_PageTicker hooks. A = 0
;   P_MapEnd    no thing moves: tmthing none (GM_TMTHING $FFFF: upstream's
;               NULL)
;   g_ttick     (the driver's, not a routine of the part table: card
;               segment DRIVER) a driver's entry: G_Ticker through FCALL
;               (its group paged in); A as G_Ticker's. The playable game's
;               brain (dl_brain.s) calls G_Ticker and gt_loop itself
;   g_tresume   (the driver's, as g_ttick) the load protocol's resumption,
;               part flow's g_resume (the action's
;               continuation), then G_Ticker again at its action loop's
;               test of gameaction (gt_loop), as upstream goes on after the
;               action returns; A as G_Ticker's
;
; actions (upstream's table) has no code of its own: the loop's compares.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/tic/tic.inc"

        .export G_Ticker, P_MapEnd, gt_loop, g_ttick, g_tresume
        .import fc_call, fc_unbuilt, g_stop, g_resume
        .import AM_Ticker, F_Ticker, D_PageTicker

; ---------------------------------------------------------------------------
; G_Ticker
; ---------------------------------------------------------------------------
        ROUTINE G_Ticker
        lda G_PLAYER + PL_PLAYERSTATE   ; G_DoReborn
        cmp #UC_PST_REBORN
        bne gt_map
        lda G_PLAYER + PL_PLAYERSTATE + 1
        bne gt_map
        lda #UGA_LOADLEVEL
        sta G_GAMEACTION
        stz G_GAMEACTION+1
gt_map: FCALL P_MapEnd
gt_loop:                                ; each game action
        lda G_GAMEACTION+1
        bne gt_bad
        lda G_GAMEACTION
        bne :+
        jmp gt_cmd
:       cmp #UGA_WORLDDONE + 1
        bcs gt_bad
        sta TK_ACT
        cmp #UGA_LOADLEVEL
        bne :+
        FCALL loadLevel
        bra gt_back
:       cmp #UGA_NEWGAME
        bne :+
        FCALL doNewGame
        bra gt_back
:       cmp #UGA_PLAYDEMO
        bne :+
        FCALL doPlayDemo
        bra gt_back
:       cmp #UGA_COMPLETED
        bne :+
        FCALL doCompleted
        bra gt_back
:       cmp #UGA_VICTORY
        bne :+
        FCALL victory
        bra gt_back
:       cmp #UGA_WORLDDONE
        bne gt_save
        FCALL doWorldDone
gt_back:
        cmp #GT_LOAD            ; a load: the driver's (G_LOADACT the
        bne gt_loop             ;   action that started it)
        lda TK_ACT
        sta G_LOADACT
        lda #GT_LOAD
        rts
gt_save:
        lda #GS_SAVEGAME        ; ga_loadgame, ga_savegame: dl_brain.s's
        jmp g_stop
gt_bad: lda #GS_ACTION          ; no such action (upstream: for ever)
        jmp g_stop
        .assert UGA_LOADGAME < UGA_WORLDDONE && UGA_SAVEGAME < UGA_WORLDDONE, error, "the saved games' actions"

gt_cmd: lda G_DEMOPLAY          ; the tic's command
        ora G_DEMOPLAY+1
        bne gt_copy
        lda G_MENUACTIVE
        ora G_MENUACTIVE+1
        beq gt_copy
        inc G_BASETIC           ; paused: basetic + 1 (the demo sync), no
        bne gt_state            ;   command
        inc G_BASETIC+1
        bne gt_state
        inc G_BASETIC+2
        bne gt_state
        inc G_BASETIC+3
        bra gt_state
gt_copy:
        lda G_GAMETIC           ; the ring's command of this tic
        and #TK_CMDS - 1
        asl a
        asl a
        asl a
        tax
        ldy #0
:       lda G_CMDS,x
        sta G_PLAYER + PL_CMD_FORWARDMOVE,y
        inx
        iny
        cpy #5
        bne :-
        lda G_DEMOPLAY          ; a demo's instead
        ora G_DEMOPLAY+1
        beq gt_state
        FCALL readDemoTiccmd
gt_state:
        lda G_GAMESTATE         ; out of the intermission: WI_End
        cmp G_PREVSTATE
        bne :+
        lda G_GAMESTATE+1
        cmp G_PREVSTATE+1
        beq gt_tick
:       lda G_PREVSTATE
        cmp #UC_GS_INTERMISSION
        bne :+
        lda G_PREVSTATE+1
        bne :+
        FCALL WI_End
:       lda G_GAMESTATE
        sta G_PREVSTATE
        lda G_GAMESTATE+1
        sta G_PREVSTATE+1
gt_tick:
        lda G_GAMESTATE+1       ; the ticker of the game state
        bne gt_done
        lda G_GAMESTATE
        bne gt_inter
        FCALL P_Ticker
        FCALL ST_Ticker
        jsr AM_Ticker
        FCALL HU_Ticker
        bra gt_done
gt_inter:
        cmp #UC_GS_INTERMISSION
        bne :+
        FCALL WI_Ticker
        bra gt_done
:       cmp #UC_GS_FINALE
        bne :+
        jsr F_Ticker
        bra gt_done
:       cmp #UC_GS_DEMOSCREEN
        bne gt_done
        jsr D_PageTicker
gt_done:
        lda #0
        rts

; ---------------------------------------------------------------------------
; P_MapEnd
; ---------------------------------------------------------------------------
        ROUTINE P_MapEnd
        lda #$FF                ; tmthing = NULL (none)
        sta GM_TMTHING
        sta GM_TMTHING+1
        rts

; ---------------------------------------------------------------------------
; g_ttick, g_tresume: the driver's entries of the tic (in the card's
; driver area, called with no paging; G_Ticker's
; group is paged in by fc_call). g_ttick: G_Ticker. g_tresume: the load
; protocol's resumption, part flow's g_resume (the core: the action's
; continuation), then G_Ticker's action loop
; ---------------------------------------------------------------------------
        .segment "DRIVER"
FC_HERE .set 0
g_ttick:
        FCALL G_Ticker
        rts
g_tresume:
        jsr g_resume
.if GP_G_Ticker_G = 0
        jmp gt_loop
.else
        jsr fc_call             ; (FCALL's form, to G_Ticker's action loop
        .byte GP_G_Ticker_G     ;   in G_Ticker's group)
        .word gt_loop
        rts
.endif
