; lsetup.s: the native P_SetupLevel (milestone 9, stage C; docs/LEVELS.md
; 2.1). A GPL-2 derivative of upstream's p_setup65.s (P_SetupLevel) and
; p_map65.s (P_MapEnd).
;
;   nl_setup    P_SetupLevel(map A): upstream's order where it is
;               observable (2.1): the totals 0, wminfo.partime 180, the
;               player's counts 0 and viewz 1 (step 3); no sound here
;               (S_Start: milestone S4 and 11); the thinker list empty and
;               the pools free (Z_FreeTags, P_InitThinkers), leveltime 0
;               (step 4); the math's product tables' pointers (mt_init: the
;               load phase has used no product before); then the map's load program (lload.s nl_load)
;               with the game's steps on: its SPAWN step (gspawn.s: the
;               pool, the level's game globals, each map thing) and its
;               SPECIALS step (gspec.s); then P_MapEnd (tmthing NULL: the
;               native keeps no tmthing). One path: a new life on the same
;               map (upstream's RL_ON) runs it all too.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"

        .export nl_setup
        .import nl_game, gt_init, mt_init

PLR     = G_PLAYER

        .segment "LOADW"

nl_setup:
        pha
.ifdef LPROF
        lda #2 * 11             ; the cost phase of the setup's own steps
        sta PHASE
.endif
        ldx #G_TOTALSECRET + 4 - G_TOTALKILLS - 1  ; the totals 0
:       stz G_TOTALKILLS,x
        dex
        bpl :-
        .assert G_TOTALLIVE = G_TOTALKILLS + 4 && G_TOTALITEMS =  G_TOTALLIVE + 4 && G_TOTALSECRET = G_TOTALITEMS + 4,  error, "the totals' order"
        lda #<180               ; wminfo.partime = 180
        sta G_WMINFO + WM_PARTIME
        lda #>180
        sta G_WMINFO + WM_PARTIME + 1
        stz PLR + PL_KILLCOUNT   ; the player's counts
        stz PLR + PL_KILLCOUNT + 1
        stz PLR + PL_SECRETCOUNT
        stz PLR + PL_SECRETCOUNT + 1
        stz PLR + PL_ITEMCOUNT
        stz PLR + PL_ITEMCOUNT + 1
        lda #1                  ; viewz = 1: the player sets it
        sta PLR + PL_VIEWZ_G
        stz PLR + PL_VIEWZ_G + 1
        stz PLR + PL_VIEWZ_G + 2
        stz PLR + PL_VIEWZ_G + 3
        jsr gt_init             ; the thinkers and the pools
        jsr mt_init             ; (the math's products: the spawn's)
        stz G_LEVELTIME
        stz G_LEVELTIME+1
        stz G_LEVELTIME+2
        stz G_LEVELTIME+3
        pla
        jsr nl_game             ; the load with SPAWN and SPECIALS
        rts                     ; P_MapEnd: no tmthing natively
