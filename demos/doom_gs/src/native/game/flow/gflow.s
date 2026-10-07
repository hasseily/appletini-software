; game/flow/gflow.s: part flow of the game (docs/GAME.md, the parts; wave
; 1), g_game65.s's game flow game-side: the action table's targets, the
; level load up to the load and the load protocol's continuations
; (docs/GAME.md, the load protocol),
; the exits, the new game, the demo playback, the completed level.
; GPL-2: rewritten from upstream's g_game65.s (Doom8088: Apple IIgs
; Edition, GPL-2); every product and divide is math.s's.
;
; The native calls:
;
;   G_ExitLevel, G_SecretExitLevel, G_WorldDone, G_ReloadDefaults: none
;   G_DeferedInitNew   A:X = the skill (upstream's C)
;   G_DeferedPlayDemo  GA_0-4 = the demo's name: defdemoname's native
;                      reference (tag, symbol number, offset: the bridge's
;                      "ref" encoding of a symbol, as G_DEFDEMO holds it)
;   loadLevel, doNewGame, doWorldDone, doPlayDemo, doLoadLevel
;                      the action targets that load a level: each runs up
;                      to the load (doLoadLevel's part before bmLoad), sets
;                      G_LOADACT to the action (gameaction) and returns
;                      A = GT_LOAD; the kernel loads the level (dl_disp.s:
;                      nl_setup) and calls g_resume, the continuation
;                      (dl_brain.s's E_RESUME)
;   initNew            A:X = the skill, GA_0-1 = the map; A = GT_LOAD
;   readDemoHeader     A = GT_LOAD
;   checkOverrun       A:X = the header bytes needed
;   doCompleted        A = 0
;   victory            the finale (W_StartFinale's stop, GS_FINALE)
;   readDemoTiccmd, G_CheckDemoStatus: none
;   signLong           A:X = a value, Y = an offset in G_WMINFO: the value
;                      there, sign extended to 32 bits
;   div1000            GA_0-3 = n: GA_4-7 = n / 1000, GA_0-3 = n % 1000
;                      (unsigned, udiv32)
;   g_resume           the continuation of G_LOADACT's action; A = 0. The
;                      brain's E_RESUME calls it after a load; part tic's
;                      G_Ticker then goes on at its action loop's test of
;                      gameaction (the brain's group: not the core, below)
;
; What is not here, by design (docs/GAME.md): the keys' state
; (gamekeydown), wipegamestate and automapmode are the screens' and the
; input's (docs/SCREENS.md, docs/PLAY.md: none is canonical state);
; P_SetSecnodeFirstpoolToNull
; is the load's (lsetup.s gt_init frees the node pools); bmLoad is the
; kernel's load; W_GetNumForName is the demo bank's directory (DEMOB,
; below); the timed demo's report (bmDone) is the hook G_TimeDemoEnd (the
; play build's menu benchmark, dl_hook.s) and I_Quit a stop.
;
; The demo bank (docs/GAME.md: DEMOB holds the demo lump that plays). Its
; layout is glayout.py's (DEMOB_LAYOUT): a directory at DM_DIR, the count
; (1 byte),
; then DM_ESIZE bytes an entry: the name (the symbol number and the
; offset of the reference defdemoname holds, 2 + 2), the lump's number in
; the WAD directory (2), its length (2) and its address in DEMOB (2).
; demobuffer and demo_p are references to the lump (lump, offset), so a
; demo's byte k is at the entry's address + k.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export loadLevel, victory, doNewGame, doWorldDone, doPlayDemo
        .export doCompleted, doLoadLevel, G_ExitLevel, G_SecretExitLevel
        .export G_WorldDone, G_DeferedInitNew, G_ReloadDefaults, initNew
        .export readDemoTiccmd, G_DeferedPlayDemo, readDemoHeader
        .export checkOverrun, G_CheckDemoStatus, signLong, div1000
        .export g_resume
        .import udiv32, umul16lo, mul32
        .import far_get, far_put, g_stop, fc_call, fc_unbuilt
        .import ST_Start, HU_Start, Z_CheckHeap, F_LoadScreen, I_GetTime
        .import D_AdvanceDemo, W_StartInter, W_StartFinale, I_Error
        .import WI_Start, g_mclearrandom, G_TimeDemoEnd
        .export fl_realtics := FL_U     ; (the realtics, for G_TimeDemoEnd)

PLR     = G_PLAYER

; the demo bank's directory: ggame.inc's DM_DIR, DM_ESIZE, DME_NAME (the
; symbol number (2), the offset (2)), DME_LUMP, DME_LEN, DME_ADDR (glayout
; .py DEMOB_LAYOUT)
DEMOMARKER = $80
HEADER_BYTES = 13               ; version, skill, episode, map, 5 more,
                                ;   the player, 3 (demo_p after them)

; the scratch block (SB_FLOW, 32 bytes): what a routine keeps across its
; calls
FL_ENT  = SB_FLOW               ; a directory entry (10)
FL_K    = SB_FLOW + 10          ; entries left (1)
FL_KEY  = SB_FLOW + 11          ; the key looked for (4)
FL_CMD  = SB_FLOW + 15          ; the demo's bytes read (4)
FL_U    = SB_FLOW + 19          ; a 32-bit value (4)
FL_SKILL = SB_FLOW + 23         ; (2)
        .assert SB_FLOW_SIZE >= 25, error, "flow's scratch block"

; ---------------------------------------------------------------------------
; DM_FIND n, at: find the directory entry whose n bytes at offset `at`
; equal FL_KEY: carry clear and the entry in FL_ENT, else carry set
; ---------------------------------------------------------------------------
.macro DM_FIND n, at
        .local loop, next, none, done
        lda #DEMOB
        sta FA_BANK
        lda #<DM_DIR
        sta FA_SRC
        lda #>DM_DIR
        sta FA_SRC+1
        lda #<FL_ENT
        sta FA_DST
        lda #>FL_ENT
        sta FA_DST+1
        lda #1
        sta FA_N
        jsr far_get             ; the count
        lda FL_ENT
        sta FL_K
        inc FA_SRC              ; the first entry
        lda #DM_ESIZE
        sta FA_N
loop:   lda FL_K
        beq none
        jsr far_get
        ldx #n - 1
:       lda FL_ENT + at,x
        cmp FL_KEY,x
        bne next
        dex
        bpl :-
        clc
        bra done
next:   dec FL_K
        clc
        lda FA_SRC
        adc #DM_ESIZE
        sta FA_SRC
        bcc loop
        inc FA_SRC+1
        bra loop
none:   sec
done:
.endmacro
        .assert <DM_DIR <> $FF, error, "DM_DIR + 1 in one page"

; ===========================================================================
; G_ExitLevel, G_SecretExitLevel: the level is completed (the next level,
; or the secret one)
; ===========================================================================
        ROUTINE G_ExitLevel
        stz G_SECRETEXIT
        stz G_SECRETEXIT+1
        lda #UGA_COMPLETED
        sta G_GAMEACTION
        stz G_GAMEACTION+1
        rts

        ROUTINE G_SecretExitLevel
        lda #1
        sta G_SECRETEXIT
        stz G_SECRETEXIT+1
        lda #UGA_COMPLETED
        sta G_GAMEACTION
        stz G_GAMEACTION+1
        rts

; ===========================================================================
; G_WorldDone: after the intermission, the next level (after map 8 the
; finale)
; ===========================================================================
        ROUTINE G_WorldDone
        lda #UGA_WORLDDONE
        sta G_GAMEACTION
        stz G_GAMEACTION+1
        lda G_SECRETEXIT
        ora G_SECRETEXIT+1
        beq :+
        lda #1
        sta PLR + PL_DIDSECRET
        stz PLR + PL_DIDSECRET + 1
:       lda G_GAMEMAP
        cmp #8
        bne :+
        lda G_GAMEMAP+1
        bne :+
        lda #UGA_VICTORY
        sta G_GAMEACTION
:       rts

; ===========================================================================
; G_DeferedInitNew (A:X the skill): a new game at the next tic
; ===========================================================================
        ROUTINE G_DeferedInitNew
        sta G_DSKILL
        stx G_DSKILL+1
        lda #UGA_NEWGAME
        sta G_GAMEACTION
        stz G_GAMEACTION+1
        rts

; ===========================================================================
; G_ReloadDefaults: no demo
; ===========================================================================
        ROUTINE G_ReloadDefaults
        stz G_DEMOPLAY
        stz G_DEMOPLAY+1
        stz G_SINGLEDEMO
        stz G_SINGLEDEMO+1
        rts

; ===========================================================================
; G_DeferedPlayDemo (GA_0-4 the name's reference): the demo at the next
; tic
; ===========================================================================
        ROUTINE G_DeferedPlayDemo
        ldx #4
:       lda GA_0,x
        sta G_DEFDEMO,x
        dex
        bpl :-
        lda #UGA_PLAYDEMO
        sta G_GAMEACTION
        stz G_GAMEACTION+1
        rts

; ===========================================================================
; victory: ga_victory, the finale (W_StartFinale: a stop, GS_FINALE)
; ===========================================================================
        ROUTINE victory
        jsr W_StartFinale
        lda #0
        rts

; ===========================================================================
; loadLevel: ga_loadlevel, the player reborn in the level
; ===========================================================================
        ROUTINE loadLevel
        lda #UC_PST_REBORN
        sta PLR + PL_PLAYERSTATE
        stz PLR + PL_PLAYERSTATE + 1
        FCALL doLoadLevel
        rts

; ===========================================================================
; doLoadLevel: G_DoLoadLevel up to the load: the level's game state, a
; dead player reborn; then the load (the kernel's, docs/GAME.md) with the
; action that started it. A = GT_LOAD.
; ===========================================================================
        ROUTINE doLoadLevel
        stz G_GAMESTATE         ; GS_LEVEL
        stz G_GAMESTATE+1
        lda PLR + PL_PLAYERSTATE
        cmp #UC_PST_DEAD
        bne :+
        lda PLR + PL_PLAYERSTATE + 1
        bne :+
        lda #UC_PST_REBORN
        sta PLR + PL_PLAYERSTATE
:       lda G_GAMEACTION        ; the load, then the action's continuation
        sta G_LOADACT
        lda #GT_LOAD
        rts

; ===========================================================================
; doNewGame: G_DoNewGame, a new game of d_skill from map 1
; ===========================================================================
        ROUTINE doNewGame
        FCALL G_ReloadDefaults
        lda #1
        sta GA_0
        stz GA_0+1
        lda G_DSKILL
        ldx G_DSKILL+1
        FCALL initNew
        rts                     ; (A = GT_LOAD; the rest is g_resume's)

; ===========================================================================
; initNew (A:X the skill, GA_0-1 the map): G_InitNew, the skill up to
; nightmare, the map 1 to 9, the random numbers from the start, the level
; ===========================================================================
        ROUTINE initNew
        sta FL_SKILL
        stx FL_SKILL+1
        sec                     ; skill - 5 negative (upstream's bmi)
        sbc #UC_SK_NIGHTMARE + 1
        txa
        sbc #0
        bmi :+
        lda #UC_SK_NIGHTMARE
        sta FL_SKILL
        stz FL_SKILL+1
:       lda FL_SKILL
        sta G_GAMESKILL
        lda FL_SKILL+1
        sta G_GAMESKILL+1
        lda GA_0                ; map - 1 negative: 1
        sec
        sbc #1
        lda GA_0+1
        sbc #0
        bpl :+
        lda #1
        sta GA_0
        stz GA_0+1
:       lda GA_0                ; map - 10 not negative: 9
        sec
        sbc #10
        lda GA_0+1
        sbc #0
        bmi :+
        lda #9
        sta GA_0
        stz GA_0+1
:       lda GA_0
        sta G_GAMEMAP
        lda GA_0+1
        sta G_GAMEMAP+1
        jsr g_mclearrandom      ; M_ClearRandom: both indexes 0 (gthink.s)
        stz G_RESPAWN
        stz G_RESPAWN+1
        lda G_GAMESKILL
        cmp #UC_SK_NIGHTMARE
        bne :+
        lda G_GAMESKILL+1
        bne :+
        inc G_RESPAWN
:       lda #UC_PST_REBORN
        sta PLR + PL_PLAYERSTATE
        stz PLR + PL_PLAYERSTATE + 1
        lda #1
        sta G_USERGAME
        stz G_USERGAME+1
        stz G_TOTALTIMES
        stz G_TOTALTIMES+1
        stz G_TOTALTIMES+2
        stz G_TOTALTIMES+3
        FCALL doLoadLevel
        rts

; ===========================================================================
; doWorldDone: G_DoWorldDone, the level after the intermission
; ===========================================================================
        ROUTINE doWorldDone
        jsr F_LoadScreen
        stz G_GAMESTATE         ; GS_LEVEL
        stz G_GAMESTATE+1
        clc                     ; gamemap = wminfo.next + 1
        lda G_WMINFO + WM_NEXT
        adc #1
        sta G_GAMEMAP
        lda G_WMINFO + WM_NEXT + 1
        adc #0
        sta G_GAMEMAP+1
        FCALL doLoadLevel
        rts

; ===========================================================================
; doPlayDemo: G_DoPlayDemo, the demo lump of defdemoname (DEMOB's
; directory: W_GetNumForName's), its header, the playback
; ===========================================================================
        ROUTINE doPlayDemo
        lda G_DEFDEMO           ; a null name: W_GetNumForName's error
        jeq pd_none
        ldx #3
:       lda G_DEFDEMO+1,x
        sta FL_KEY,x
        dex
        bpl :-
        DM_FIND 4, DME_NAME
        jcs pd_none
        lda #1                  ; demobuffer: the lump, offset 0
        sta G_DEMOBUF
        lda FL_ENT + DME_LUMP
        sta G_DEMOBUF+1
        lda FL_ENT + DME_LUMP + 1
        sta G_DEMOBUF+2
        stz G_DEMOBUF+3
        stz G_DEMOBUF+4
        lda FL_ENT + DME_LEN
        sta G_DEMOLEN
        lda FL_ENT + DME_LEN + 1
        sta G_DEMOLEN+1
        FCALL readDemoHeader
        rts                     ; (A = GT_LOAD; the rest is g_resume's)
pd_none:
        jmp I_Error

; ===========================================================================
; readDemoHeader: G_ReadDemoHeader, the skill and map of the demo (a new
; game); demo_p after the header. A = GT_LOAD (the cheats' clear is
; g_resume's).
; ===========================================================================
        ROUTINE readDemoHeader
        ldx #3                  ; basetic = gametic
:       lda G_GAMETIC,x
        sta G_BASETIC,x
        dex
        bpl :-
        lda #1                  ; the version
        ldx #0
        FCALL checkOverrun
        lda #1 + 8              ; skill, episode, map, 5 more
        ldx #0
        FCALL checkOverrun
        lda #1 + 8 + 1          ; the player
        ldx #0
        FCALL checkOverrun
        lda G_DEMOBUF+1         ; the lump's bytes 0-3
        sta FL_KEY
        lda G_DEMOBUF+2
        sta FL_KEY+1
        DM_FIND 2, DME_LUMP
        bcc :+
        jmp I_Error
:       clc
        lda FL_ENT + DME_ADDR
        adc G_DEMOBUF+3
        sta FA_SRC
        lda FL_ENT + DME_ADDR + 1
        adc G_DEMOBUF+4
        sta FA_SRC+1
        lda #<FL_CMD
        sta FA_DST
        lda #>FL_CMD
        sta FA_DST+1
        lda #4
        sta FA_N
        lda #DEMOB              ; (the demo bank: no cached kind's)
        sta FA_BANK
        jsr far_get
        lda G_DEMOBUF           ; demo_p = demobuffer + 13
        sta G_DEMOP
        lda G_DEMOBUF+1
        sta G_DEMOP+1
        lda G_DEMOBUF+2
        sta G_DEMOP+2
        clc
        lda G_DEMOBUF+3
        adc #HEADER_BYTES
        sta G_DEMOP+3
        lda G_DEMOBUF+4
        adc #0
        sta G_DEMOP+4
        lda G_GAMEACTION        ; a loaded game: the menus'
        cmp #UGA_LOADGAME
        bne :+
        lda G_GAMEACTION+1
        bne :+
        lda #GS_SAVEGAME
        jmp g_stop
:       lda FL_CMD+3            ; G_InitNew(skill, map)
        sta GA_0
        stz GA_0+1
        lda FL_CMD+1
        ldx #0
        FCALL initNew
        rts

; ===========================================================================
; checkOverrun (A:X the bytes): CheckForOverrun, I_Error when the header
; passes the demo's length
; ===========================================================================
        ROUTINE checkOverrun
        sta GT_0
        stx GT_1
        lda G_DEMOLEN           ; demolength - A:X borrows: A:X is past
        cmp GT_0                ;   the length (unsigned), the error
        lda G_DEMOLEN+1
        sbc GT_1
        bcc :+
        rts
:       jmp I_Error

; ===========================================================================
; readDemoTiccmd: G_ReadDemoTiccmd, the tic command from the demo, or at
; its end the demo status
; ===========================================================================
        ROUTINE readDemoTiccmd
        lda G_DEMOP+1           ; the lump of demo_p in DEMOB
        sta FL_KEY
        lda G_DEMOP+2
        sta FL_KEY+1
        DM_FIND 2, DME_LUMP
        bcc :+
        jmp I_Error
:       clc
        lda FL_ENT + DME_ADDR
        adc G_DEMOP+3
        sta FA_SRC
        lda FL_ENT + DME_ADDR + 1
        adc G_DEMOP+4
        sta FA_SRC+1
        lda #<FL_CMD
        sta FA_DST
        lda #>FL_CMD
        sta FA_DST+1
        lda #4
        sta FA_N
        lda #DEMOB              ; (the demo bank: no cached kind's)
        sta FA_BANK
        jsr far_get
        lda FL_CMD              ; DEMOMARKER: the end
        cmp #DEMOMARKER
        beq @end
        lda G_DEMOPLAY          ; past the end with no marker (the
        ora G_DEMOPLAY+1        ;   demo's 16-bit offsets, as upstream's
        beq @read               ;   low words)
        clc
        lda G_DEMOP+3
        adc #4
        sta GT_0
        lda G_DEMOP+4
        adc #0
        sta GT_1
        sec
        lda GT_0
        sbc G_DEMOBUF+3
        sta GT_0
        lda GT_1
        sbc G_DEMOBUF+4
        sta GT_1
        ora GT_0
        beq @read
        lda GT_0                ; (the message is the screens' printf)
        cmp G_DEMOLEN
        lda GT_1
        sbc G_DEMOLEN+1
        bcc @read               ; below the length
        lda GT_0
        eor G_DEMOLEN
        bne @end
        lda GT_1
        eor G_DEMOLEN+1
        bne @end                ; past it: the end
@read:  lda FL_CMD              ; forwardmove, sidemove
        sta PLR + PL_CMD_FORWARDMOVE
        lda FL_CMD+1
        sta PLR + PL_CMD_SIDEMOVE
        stz PLR + PL_CMD_ANGLETURN      ; angleturn = byte << 8
        lda FL_CMD+2
        sta PLR + PL_CMD_ANGLETURN + 1
        lda FL_CMD+3            ; buttons
        sta PLR + PL_CMD_BUTTONS
        clc                     ; demo_p += 4
        lda G_DEMOP+3
        adc #4
        sta G_DEMOP+3
        bcc :+
        inc G_DEMOP+4
:       rts
@end:   FCALL G_CheckDemoStatus
        rts

; ===========================================================================
; G_CheckDemoStatus: at a demo's end, the next demo of the title loop
; (D_AdvanceDemo), or a timed demo's report (the hook G_TimeDemoEnd, the
; realtics at fl_realtics), or the quit of a single demo (a stop)
; ===========================================================================
        ROUTINE G_CheckDemoStatus
        lda G_TIMINGDEMO
        ora G_TIMINGDEMO+1
        beq @play
        jsr I_GetTime           ; realtics = now - starttime
        sec
        ldx #0
        ldy #4
:       lda GA_0,x
        sbc G_STARTTIME,x
        sta FL_U,x
        inx
        dey
        bne :-
        ldx #3                  ; resultfps = 35000 * gametic / realtics
:       lda G_GAMETIC,x
        sta M_A,x
        dex
        bpl :-
        lda #<(UC_TICRATE * 1000)
        sta M_B
        lda #>(UC_TICRATE * 1000)
        sta M_B+1
        stz M_B+2
        stz M_B+3
        jsr mul32
        ldx #3
:       lda M_R,x
        sta M_A,x
        lda FL_U,x
        sta M_B,x
        dex
        bpl :-
        jsr udiv32
        ldx #3
:       lda M_R,x
        sta GA_0,x
        dex
        bpl :-
        FCALL div1000           ; resultfps % 1000 and / 1000: bmDone's
        lda #GS_DEMOEND         ;   (the hook: the play build's menu
        jmp G_TimeDemoEnd       ;   benchmark)
@play:  lda G_DEMOPLAY
        ora G_DEMOPLAY+1
        beq @rts
        lda G_SINGLEDEMO        ; a single demo: I_Quit (the screens')
        ora G_SINGLEDEMO+1
        beq :+
        lda #GS_DEMOEND
        jmp g_stop
:       FCALL G_ReloadDefaults
        jsr D_AdvanceDemo
@rts:   rts

; ===========================================================================
; div1000 (GA_0-3 = n): GA_4-7 = n / 1000, GA_0-3 = n % 1000 (unsigned)
; ===========================================================================
        ROUTINE div1000
        ldx #3
:       lda GA_0,x
        sta M_A,x
        dex
        bpl :-
        lda #<1000
        sta M_B
        lda #>1000
        sta M_B+1
        stz M_B+2
        stz M_B+3
        jsr udiv32
        ldx #3
:       lda M_R,x
        sta GA_0+4,x
        lda M_T,x
        sta GA_0,x
        dex
        bpl :-
        rts

; ===========================================================================
; doCompleted: G_DoCompleted, the player finishes the level; the
; intermission with the counts, the times and the next level. A = 0.
; ===========================================================================
        ROUTINE doCompleted
        stz G_GAMEACTION
        stz G_GAMEACTION+1
        ldx #2 * UC_NUMPOWERS - 1       ; the level's powers and cards
:       stz PLR + PL_POWERS_0,x
        dex
        bpl :-
        ldx #2 * UC_NUMCARDS - 1
:       stz PLR + PL_CARDS_0,x
        dex
        bpl :-
        lda #$FF                ; mo = NULL (no handle)
        sta PLR + PL_MO
        sta PLR + PL_MO + 1
        stz PLR + PL_EXTRALIGHT
        stz PLR + PL_EXTRALIGHT + 1
        stz PLR + PL_FIXEDCOLORMAP
        stz PLR + PL_FIXEDCOLORMAP + 1
        stz PLR + PL_DAMAGECOUNT
        stz PLR + PL_DAMAGECOUNT + 1
        stz PLR + PL_BONUSCOUNT
        stz PLR + PL_BONUSCOUNT + 1
        lda G_GAMEMAP           ; (the automap's stop: the screens')
        cmp #9                  ; map 9 counts as the secret
        bne :+
        lda G_GAMEMAP+1
        bne :+
        lda #1
        sta PLR + PL_DIDSECRET
        stz PLR + PL_DIDSECRET + 1
:       lda PLR + PL_DIDSECRET
        sta G_WMINFO + WM_DIDSECRET
        lda PLR + PL_DIDSECRET + 1
        sta G_WMINFO + WM_DIDSECRET + 1
        sec                     ; last = gamemap - 1
        lda G_GAMEMAP
        sbc #1
        sta G_WMINFO + WM_LAST
        lda G_GAMEMAP+1
        sbc #0
        sta G_WMINFO + WM_LAST + 1
        lda #8                  ; next: the secret level 9 (8), or 4 (3)
        ldx #0                  ;   after 9, or the next one (gamemap)
        ldy G_SECRETEXIT
        bne @next
        ldy G_SECRETEXIT+1
        bne @next
        lda #3
        ldy G_GAMEMAP+1
        bne :+
        ldy G_GAMEMAP
        cpy #9
        beq @next
:       lda G_GAMEMAP
        ldx G_GAMEMAP+1
@next:  sta G_WMINFO + WM_NEXT
        stx G_WMINFO + WM_NEXT + 1
        ldx #3                  ; the totals
:       lda G_TOTALKILLS,x
        sta G_WMINFO + WM_MAXKILLS,x
        lda G_TOTALITEMS,x
        sta G_WMINFO + WM_MAXITEMS,x
        lda G_TOTALSECRET,x
        sta G_WMINFO + WM_MAXSECRET,x
        dex
        bpl :-
        ldx G_GAMEMAP           ; partime = TICRATE * pars[gamemap]
        lda pars,x
        sta M_A
        stz M_A+1
        lda #UC_TICRATE
        sta M_B
        stz M_B+1
        jsr umul16lo
        lda M_R
        sta G_WMINFO + WM_PARTIME
        lda M_R+1
        sta G_WMINFO + WM_PARTIME + 1
        lda PLR + PL_KILLCOUNT  ; the player's counts
        ldx PLR + PL_KILLCOUNT + 1
        ldy #WM_SKILLS
        FCALL signLong
        lda PLR + PL_ITEMCOUNT
        ldx PLR + PL_ITEMCOUNT + 1
        ldy #WM_SITEMS
        FCALL signLong
        lda PLR + PL_SECRETCOUNT
        ldx PLR + PL_SECRETCOUNT + 1
        ldy #WM_SSECRET
        FCALL signLong
        ldx #3                  ; stime = leveltime
:       lda G_LEVELTIME,x
        sta G_WMINFO + WM_STIME,x
        sta M_A,x
        dex
        bpl :-
        lda #UC_TICRATE         ; leveltime down to whole seconds: its
        sta M_B                 ;   remainder by TICRATE (0-34)
        stz M_B+1
        stz M_B+2
        stz M_B+3
        jsr udiv32
        sec                     ; totalleveltimes += leveltime - the
        lda G_LEVELTIME         ;   remainder (its low word: upstream's)
        sbc M_T
        sta M_A
        lda G_LEVELTIME+1
        sbc M_T+1
        sta M_A+1
        lda G_LEVELTIME+2
        sbc #0
        sta M_A+2
        lda G_LEVELTIME+3
        sbc #0
        sta M_A+3
        clc
        ldx #0
        ldy #4
:       lda G_TOTALTIMES,x
        adc M_A,x
        sta G_TOTALTIMES,x
        sta G_WMINFO + WM_TOTALTIMES,x
        inx
        dey
        bne :-
        lda #UC_GS_INTERMISSION
        sta G_GAMESTATE
        stz G_GAMESTATE+1
        jsr W_StartInter        ; (the pictures and music; WI_Start)
        lda #0
        rts
; pars: the par times of maps 0-9 in seconds (Doom's, by the map's
; number)
pars:   .byte 0, 30, 75, 120, 90, 165, 180, 180, 30, 165

; ===========================================================================
; signLong (A:X a value, Y an offset of G_WMINFO): the value there, sign
; extended to 32 bits
; ===========================================================================
        ROUTINE signLong
        sta G_WMINFO,y
        txa
        sta G_WMINFO+1,y
        lda #0
        cpx #$80
        bcc :+
        lda #$FF
:       sta G_WMINFO+2,y
        sta G_WMINFO+3,y
        rts

; ===========================================================================
; g_resume: the load protocol's continuation (docs/GAME.md): doLoadLevel's
; tail, then the tail of G_LOADACT's action. A = 0. Not in the core (the
; frame slots, docs/SPEED.md: it runs once a load, so its 163 B went to
; the placeable code): in the play build the brain's group (dl_brain.s's
; E_RESUME calls it there, play.mk's PLAY_TIC); without PLAY_TIC (no
; current build) the card's DRIVER segment. Its calls are the hooks', in
; the core.
; ===========================================================================
.ifdef PLAY_TIC
        .segment "DLGB"
FC_HERE .set $FF                ; (a glue group's: an FCALL from here goes
                                ;   through fc_call, the brain's group
                                ;   restored on its return)
.else
        .segment "DRIVER"
FC_HERE .set 0
.endif
g_resume:
        ; the load's textures: upstream's R_GetTexture set
        ; texturetranslation[n] = n for each texture the load made: the
        ; setup's (TXR_Ln) at every load, W_LevelDone's (TXR_Mn) only for
        ; another map than the window's (bmLoad's W_SET: G_WSET); only
        ; basepic .. basepic + 2 can differ (glayout.py txr_compute)
        ldx G_GAMEMAP
        lda G_GAMEMAP+1
        bne @txd
        cpx #10
        bcs @txd
        lda txr_load,x
        cpx G_WSET
        beq :+
        ora txr_more,x
:       stx G_WSET
        tay                     ; the mask, bit k for TXR_BASE + k
        ldx #TXR_BASE
@tx:    tya
        beq @txd
        lsr a
        tay
        bcc :+
        txa
        sta TEXTRANS,x
:       inx
        bra @tx
@txd:   stz G_GAMEACTION        ; doLoadLevel: gameaction 0, Z_CheckHeap,
        stz G_GAMEACTION+1      ;   (the keys up: the input's), ST_Start,
        jsr Z_CheckHeap         ;   HU_Start
        jsr ST_Start
        jsr HU_Start
        lda G_LOADACT
        cmp #UGA_LOADLEVEL      ; loadLevel: nothing more
        beq @done
        cmp #UGA_NEWGAME        ; doNewGame: gameaction 0, ST_Start
        bne :+
        stz G_GAMEACTION
        stz G_GAMEACTION+1
        jsr ST_Start
        bra @done
:       cmp #UGA_PLAYDEMO       ; readDemoHeader: no cheats; doPlayDemo:
        bne :+                  ;   gameaction 0, usergame 0,
        stz PLR + PL_CHEATS     ;   demoplayback 1, starttime =
        stz PLR + PL_CHEATS + 1 ;   I_GetTime
        stz G_GAMEACTION
        stz G_GAMEACTION+1
        stz G_USERGAME
        stz G_USERGAME+1
        lda #1
        sta G_DEMOPLAY
        stz G_DEMOPLAY+1
        jsr I_GetTime
        ldx #3
@time:  lda GA_0,x
        sta G_STARTTIME,x
        dex
        bpl @time
        bra @done
:       cmp #UGA_WORLDDONE      ; doWorldDone: gameaction 0
        bne @bad
        stz G_GAMEACTION
        stz G_GAMEACTION+1
@done:  lda #0
        rts
@bad:   lda #GS_ACTION
        jmp g_stop

; the masks of the load's textures by map (0 none), glayout.py's TXR_*
txr_load:
        .byte 0, TXR_L1, TXR_L2, TXR_L3, TXR_L4, TXR_L5, TXR_L6, TXR_L7
        .byte TXR_L8, TXR_L9
txr_more:
        .byte 0, TXR_M1, TXR_M2, TXR_M3, TXR_M4, TXR_M5, TXR_M6, TXR_M7
        .byte TXR_M8, TXR_M9

.ifdef TESTBUILD
; ===========================================================================
; Only with -D TESTBUILD, which no current build defines: the entries of
; the part's old check harness (a driver's routine mode called them); they
; are not part of the game.
;
;   fl_timed    the routine fl_tgt (group fl_tgrp) with the driver's A, X, Y:
;               its group loaded into its slot, then the cost phase
;               FL_PH_ENTRY around the call (its own time, with the paging
;               of the groups it calls)
;   fl_tresume  g_resume in the cost phase FL_PH_RESUME (the driver's
;               dg_resume in the load protocol's runs)
;   fl_sweep    many calls of one routine (GTEST from SW_HDR: the count
;               (2), the routine (2), its group (1), the inputs' and the
;               outputs' item counts (1 each), a record's length (1), then
;               the items: a main address (2) and a length (1) each; the
;               records from SW_REC, each the inputs' bytes then room for
;               the outputs'): per record the inputs into their places, the
;               call, the outputs into the record
; ===========================================================================
        ; test-only code goes in the card's driver area, not the core
        ; (the core's room is the game's)
        .segment "DRIVER"
FC_HERE .set 0
        .export fl_timed, fl_tresume, fl_sweep, fl_tgt, fl_tgrp, fl_buf
        .export fl_hdr, fl_ra
        .import fc_go, gr_load
FL_PH_ENTRY  = 30
FL_PH_RESUME = 31
SW_HDR  = GT_SCHEDULE           ; (the schedule's and the stream's room:
SW_REC  = SW_HDR + $80          ;   unused by the driver's routine mode)
SW_ITEMS = 24
SW_HDRLEN = 8 + 3 * SW_ITEMS
SW_RECMAX = 192

fl_timed:
        sta FC_A
        stx FC_X
        sty FC_Y
        lda fl_tgrp             ; the routine's group in its slot first
        beq :+                  ;   (its own time: the paging of the
        jsr gr_load             ;   groups it calls is in it)
:       lda #2 * FL_PH_ENTRY    ; (a2vm's phase: PHASE / 2)
        sta PHASE
        jsr fl_call
        php
        pha
        stz PHASE
        pla
        plp
        rts

fl_tresume:
        lda #2 * FL_PH_RESUME
        sta PHASE
        jsr g_resume
        pha
        stz PHASE
        pla
        rts

; fl_call: fl_tgt in its group with A, X, Y = FC_A, FC_X, FC_Y
fl_call:
        lda fl_tgt
        sta FC_T
        lda fl_tgt+1
        sta FC_T+1
        lda fl_tgrp
        sta FC_GRP
        bne :+
        lda FC_A
        ldx FC_X
        ldy FC_Y
        jmp (FC_T)
:       jmp fc_go

fl_sweep:
        lda #<SW_HDR
        sta FA_SRC
        lda #>SW_HDR
        sta FA_SRC+1
        lda #<fl_hdr
        sta FA_DST
        lda #>fl_hdr
        sta FA_DST+1
        lda #SW_HDRLEN
        jsr sw_get
        lda fl_hdr+2
        sta fl_tgt
        lda fl_hdr+3
        sta fl_tgt+1
        lda fl_hdr+4
        sta fl_tgrp
        lda #<SW_REC
        sta fl_cur
        lda #>SW_REC
        sta fl_cur+1
@loop:  lda fl_hdr
        ora fl_hdr+1
        bne :+
        rts
:       lda fl_cur              ; the record
        sta FA_SRC
        lda fl_cur+1
        sta FA_SRC+1
        lda #<fl_buf
        sta FA_DST
        lda #>fl_buf
        sta FA_DST+1
        lda fl_hdr+7
        jsr sw_get
        stz FC_A                ; (A, X, Y 0 unless the inputs say)
        stz FC_X
        stz FC_Y
        stz fl_off              ; the inputs into their places
        stz fl_dir
        stz fl_i0
        lda fl_hdr+5
        sta fl_i1
        jsr sw_move
        jsr fl_call
        sta fl_ra               ; (the routine's A, X, Y)
        stx fl_ra+1
        sty fl_ra+2
        lda #1                  ; the outputs into the record
        sta fl_dir
        lda fl_hdr+5
        sta fl_i0
        clc
        adc fl_hdr+6
        sta fl_i1
        jsr sw_move
        lda #GTEST
        sta FA_BANK
        lda #<fl_buf
        sta FA_SRC
        lda #>fl_buf
        sta FA_SRC+1
        lda fl_cur
        sta FA_DST
        lda fl_cur+1
        sta FA_DST+1
        lda fl_hdr+7
        sta FA_N
        jsr far_put
        clc
        lda fl_cur
        adc fl_hdr+7
        sta fl_cur
        bcc :+
        inc fl_cur+1
:       lda fl_hdr
        bne :+
        dec fl_hdr+1
:       dec fl_hdr
        jmp @loop

; sw_get: A bytes of GTEST at FA_SRC to FA_DST
sw_get: sta FA_N
        lda #GTEST
        sta FA_BANK
        jmp far_get

; sw_move: items fl_i0 .. fl_i1 - 1, fl_dir 0: fl_buf to their places, 1:
; their places to fl_buf; the buffer from fl_off on
sw_move:
        ldx fl_i0
@item:  cpx fl_i1
        bcs @done
        stx fl_t
        txa
        asl a
        adc fl_t
        tay
        lda fl_hdr+8,y
        sta GT_0
        lda fl_hdr+9,y
        sta GT_1
        lda fl_hdr+10,y
        sta fl_len
        ldy #0
@byte:  cpy fl_len
        beq @next
        ldx fl_off
        lda fl_dir
        bne @out
        lda fl_buf,x
        sta (GT_0),y
        bra @adv
@out:   lda (GT_0),y
        sta fl_buf,x
@adv:   inc fl_off
        iny
        bra @byte
@next:  ldx fl_t
        inx
        bra @item
@done:  rts

fl_tgt:  .res 2
fl_ra:   .res 3
fl_tgrp: .res 1
fl_cur:  .res 2
fl_off:  .res 1
fl_dir:  .res 1
fl_i0:   .res 1
fl_i1:   .res 1
fl_t:    .res 1
fl_len:  .res 1
fl_hdr:  .res SW_HDRLEN
fl_buf:  .res SW_RECMAX
.endif
