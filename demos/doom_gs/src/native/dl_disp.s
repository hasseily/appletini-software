; dl_disp.s: the frame's list (docs/PLAY.md 2.2), in the tic image's group
; DLG_DISP: d_main65.s's display (D_Display) as the steps the kernel runs
; once the tic image has left W (docs/m11-parts/design.md R7), the other
; lists the brain hands the kernel (the boot's, a load's, the menu's, the
; automap's responder, the quit), and the render inputs of the player's
; view (as the lockstep driver gdriver.s makes them: docs/GAME.md 3.4). A
; GPL-2 derivative of upstream's src/iigs/d_main65.s (Doom8088: Apple IIgs
; Edition, GPL-2).
;
;   c_display   the frame by the game state: the intermission (WIW), the
;               finale (FINW), the title page (FINW, when it is new), a
;               level's view (milestone 7's and 8's phases, OVLW with the
;               automap's overlay) or the full automap (AMAPW), then PALW
;               at a level's first frame or a new gamma, then P2DW's frame
;               (dl_p2d.s s2_frame: the poll, the effects, the palettes,
;               the status bar, the HUD); a frame with nothing to draw:
;               P2DW's poll alone (s2_poll)
;   c_loadlist  a level's load (the load protocol): F_LoadScreen's screen
;               when the world-done hook asked for it, the busy sign, the
;               load image's nl_setup of G_GAMEMAP, the sign off, then
;               K_TIC E_RESUME
;   c_bootlist, c_menulist, c_cplist, c_amlist, c_quitlist
;
; Each list ends the tic phase: the object API's caches back (go_flush)
; and the walk's planes back to MOBJP (the next image overwrites W).

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
        .include "playsym.inc"
        .include "playsym2.inc"
        .include "dl.inc"

        .import go_flush, mo_get, ss_get, sec_get, state_at, far_put
        .import fc_call, fc_unbuilt
        .export c_display, c_loadlist, c_bootlist, c_menulist, c_cplist
        .export c_amlist, c_quitlist, c_savelist, ri_make, planes_out

PLR = G_PLAYER

        .segment "DLGD"
FC_HERE .set DLG_DISP

; STLOAD img: a K_LOAD of an image's descriptor (playimg.inc: its bank,
; its page runs, 0)
.macro STLOAD img
        lda #<(img)
        ldy #>(img)
        jsr st_load
.endmacro
; STCALL addr, arg: a K_CALL of addr with A = arg (#n or a byte's place),
; X = 0
.macro STCALL addr, arg
        ldx arg
        lda #<(addr)
        ldy #>(addr)
        jsr st_call
.endmacro
.macro STOP op
        lda #op
        jsr st_byte
.endmacro

; ---------------------------------------------------------------------------
; c_display: D_Display (d_main65.s:377-558)
; ---------------------------------------------------------------------------
c_display:
        stz DL_STP
        lda W_FSG               ; the old fill spans need the view shown
        sta W_FSW               ;   (WPAGE's W_FSG, W_FSW)
        stz W_FSG
        ldx #0                  ; wipe = gamestate != wipegamestate
        lda G_GAMESTATE
        cmp DL_WIPEGS
        beq :+
        inx
:       stx DL_WIPE
        stz DL_LEFT             ; not a level: I_SetPalette(0) when the
        lda G_GAMESTATE         ;   frame before showed one (bit 0)
        jeq c_level
        lda DL_OLDGS
        bne :+
        inc DL_LEFT
:       lda G_GAMESTATE
        cmp #UC_GS_INTERMISSION
        bne :+
        STLOAD img_wiw
        STCALL XS_wi_frame, DL_LEFT
        jmp c_done
:       cmp #UC_GS_FINALE
        bne :+
        STLOAD img_finw
        STCALL XS_fin_frame, DL_LEFT
        jmp c_done
:       lda DL_WIPE             ; the title page: drawn when new, else
        bne @page               ;   only the tic commands (the poll)
        lda DL_PAGEDRAWN
        beq @page
        lda DL_OLDGS
        cmp #UC_GS_DEMOSCREEN
        bne @page
        jsr c_poll
        jmp c_done
@page:  lda #1                  ; D_PageDrawer (bit 1)
        sta DL_PAGEDRAWN
        lda #2
        tsb DL_LEFT
        STLOAD img_finw
        STCALL XS_fin_frame, DL_LEFT
        jmp c_done

; a level
c_level:
        ldx #3                  ; gametic == basetic: nothing to draw
:       lda G_GAMETIC,x
        cmp G_BASETIC,x
        bne @draw
        dex
        bpl :-
        jsr c_poll
        jmp c_done
@draw:  stz DL_P2F
        lda AUTOMAP             ; the view shows: no automap, or its
        and #AM_ACTIVE          ;   overlay
        beq @view
        lda AUTOMAP
        and #AM_OVERLAY
        bne @view
        STLOAD img_amapw        ; the full automap (AMAPW, A = the tics:
        STCALL XS_am_frame, DL_TICS     ;   AM_Ticker each, the map)
        lda #1                  ; (P2DW: the view rows' palette AMAP_PAL)
        sta DL_P2F
        jmp @twod
@view:  lda #$FF                ; viewtop: rows 0-9 kept for a message
        ldx HU_ON
        beq :+
        lda #STRIP_ROWS - 1
:       sta VIEWTOP
        cmp #$FF
        bne :+
        lda #2                  ; (the HUD: the view drew rows 0-9)
        tsb DL_P2F
:       ldx #VIEWHEIGHT         ; viewbottom: the overlay's title band
        lda AUTOMAP             ;   keeps rows 160-167
        and #AM_OVERLAY
        beq :+
        ldx #AM_TITLEY
:       stx VIEWBOT
        inc DL_VIEWS            ; (the frame rate's count: docs/PLAY.md 8)
        bne :+
        inc DL_VIEWS+1
:       jsr ri_make
        STOP K_WLOAD            ; milestone 7's front end
        STCALL XS_nr_frame, #0
        STOP K_MLOAD            ; milestone 8's masked phase
        STCALL XS_nm_masked, #0
        lda AUTOMAP
        and #AM_OVERLAY
        beq @plain
        STLOAD img_ovlw         ; the overlay's records (OVLW, A = the
        STCALL OVLW_LO, DL_TICS ;   tics; it ends with nm_bkload)
        bra @bucket
@plain: STCALL XS_nm_bkload, #0
        lda #4                  ; (the HUD: the view drew the title's
        tsb DL_P2F              ;   rows; the automap: a view was drawn)
        lda #MAIL_AMVIEW
        tsb S2_MAIL
@bucket:
        STCALL XS_nb_frame, #0  ; the bucket pass and the replay
        lda DL_WIPE             ; the screen shows this view
        bne @twod
        lda #1
        sta W_FSG
@twod:  lda DL_FLAGS            ; a level's first frame: PALW's tints
        and #DF_PALLEVEL
        beq :+
        STLOAD img_palw
        STCALL XS_palw_level, #0
        lda #DF_PALLEVEL | DF_PALGAMMA
        trb DL_FLAGS
        bra @p2dw
:       lda DL_FLAGS            ; a new gamma (the menu's M_RELOAD)
        and #DF_PALGAMMA
        beq @p2dw
        STLOAD img_palw
        STCALL XS_palw_gamma, #0
        lda #DF_PALGAMMA
        trb DL_FLAGS
@p2dw:  STLOAD img_p2dw         ; the palettes, the status bar, the HUD
        STCALL XS_s2_frame, DL_P2F
c_done: lda G_GAMESTATE         ; wipegamestate = oldgamestate = gamestate
        sta DL_WIPEGS
        sta DL_OLDGS
        lda #1                  ; iigs_newframe = 1 (after display: the
        sta DL_NEWFRAME         ;   fine turns count frames, g_buildcmd)
        STOP K_END
; c_out: the tic phase's end: the caches back, the planes back
c_out:  jsr go_flush
        jmp planes_out

; c_poll: P2DW's poll alone (the input, the effects, the music's ring)
c_poll: STLOAD img_p2dw
        STCALL XS_s2_poll, #0
        rts

; ---------------------------------------------------------------------------
; The other lists
; ---------------------------------------------------------------------------

; c_loadlist: a load (GAME.md 3.4): G_GAMEMAP's level, then E_RESUME
c_loadlist:
        stz DL_STP
        lda DL_FLAGS            ; F_LoadScreen (doWorldDone's)
        and #DF_LOADSCR
        beq :+
        lda #DF_LOADSCR
        trb DL_FLAGS
        STLOAD img_finw
        STCALL XS_fin_load, #0
:       STLOAD img_finw         ; bmLoad: the busy sign around the load
        STCALL XS_fin_signon, #0
        STLOAD img_lcode
        STCALL XS_nl_setup, G_GAMEMAP
        STLOAD img_finw
        STCALL XS_fin_signoff, #0
        STOP K_TIC
        STOP E_RESUME
        jmp c_out

; c_bootlist: DLINIT (the static tables, the screen), the 2D images'
; inits (D_DoomMain's M_Init, WI_Init, F_Init), then the first frame
c_bootlist:
        stz DL_STP
        lda #UC_GS_DEMOSCREEN   ; (upstream's wipegamestate at the start)
        sta DL_WIPEGS
        STLOAD img_dlinit
        STCALL XS_dli_main, #0
        STLOAD img_menuw
        STCALL XS_m_load, #0
        STCALL XS_m_init, #0
        STCALL XS_m_save, #0
        STLOAD img_wiw
        STCALL XS_wi_init, #0
        STLOAD img_finw
        STCALL XS_fin_init, #0
        STOP K_TIC
        STOP E_FRAME
        jmp c_out

; c_menulist: the menu's frames, the queue's head (Escape) its first event
c_menulist:
        stz DL_STP
        STLOAD img_menuw
        STCALL XS_m_load, #0
        bra c_menu2
; c_cplist: M_StartControlPanel (G_Responder on the title page), then the
; menu's frames
c_cplist:
        stz DL_STP
        STLOAD img_menuw
        STCALL XS_m_load, #0
        STCALL XS_m_startcp, #0
c_menu2:
        STOP K_MENU
        STCALL XS_m_save, #0
        STOP K_TIC
        STOP E_MENU
        jmp c_out

; c_amlist: AM_Responder (AMAPW) of the event the brain routes (DL_EV:
; A the type, X its key; am_responder's Y, the key's high byte, is 0),
; its answer in DL_RES, then E_EVENT
c_amlist:
        stz DL_STP
        STLOAD img_amapw
        STCALL XS_am_load, #0
        lda DL_EV+1
        sta GT_2
        ldx DL_EV
        lda #<XS_am_responder
        ldy #>XS_am_responder
        jsr st_callx
        STCALL XS_am_save, #0
        STOP K_TIC
        STOP E_EVENT
        jmp c_out

; c_savelist: the failed save's message (k_sdfail at KMAIN: m_savedone
; with C set), then the menu's frames again
c_savelist:
        stz DL_STP
        STLOAD img_menuw
        STCALL XS_m_load, #0
        STCALL KMAIN, #0
        jmp c_menu2

; c_quitlist: I_Quit: DLINIT's quit (the music stops, the text screen),
; then the end
c_quitlist:
        stz DL_STP
        STLOAD img_dlinit
        STCALL XS_dli_quit, #0
        STOP K_HALT
        jmp c_out

; ---------------------------------------------------------------------------
; The writer: DLBUF from DL_STP on
; ---------------------------------------------------------------------------
; st_byte: A into the list (X changes; A, Y kept)
st_byte:
        ldx DL_STP
        sta DLBUF,x
        inx
        stx DL_STP
        rts
; st_call: K_CALL of Y:A with A = X and X = 0; st_callx: with X = GT_2
st_call:
        stz GT_2
st_callx:
        phx
        pha
        lda #K_CALL
        jsr st_byte
        pla
        jsr st_byte
        tya
        jsr st_byte
        pla
        jsr st_byte
        lda GT_2
        jmp st_byte
; st_load: K_LOAD of the descriptor at Y:A (its bank, its page runs, 0)
st_load:
        sta GT_0
        sty GT_1
        lda #K_LOAD
        jsr st_byte
        ldy #0
        lda (GT_0),y            ; the bank
        jsr st_byte
@run:   iny
        lda (GT_0),y            ; a run's first page, 0: the end
        pha
        jsr st_byte
        pla
        beq @done
        iny
        lda (GT_0),y            ; its count
        jsr st_byte
        bra @run
@done:  rts

; ---------------------------------------------------------------------------
; ri_make: the render inputs (rlayout.py RENDER_INPUTS) from the game
; state, as gdriver.s's (RENDER-MASKED.md 2.3): the player's mobj's x, y
; and angle; viewz, extralight, the fixed colormap, the invisibility power;
; each psprite's sprite, frame, sx, sy and PSPF; the player's sector's
; light. GAMMA is the menu's (it writes the render input).
; ---------------------------------------------------------------------------
ri_make:
        lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #3
:       lda (GC_MP),y           ; (TH_X 0, TH_Y 4)
        sta PL_X,y
        dey
        bpl :-
        ldy #TH_Y + 3
        ldx #3
:       lda (GC_MP),y
        sta PL_Y,x
        dey
        dex
        bpl :-
        ldy #TH_ANGLO
        lda (GC_MP),y
        sta PL_ANGLE
        iny
        lda (GC_MP),y
        sta PL_ANGLE+1
        ldy #TH_ANG
        lda (GC_MP),y
        sta PL_ANGLE+2
        iny
        lda (GC_MP),y
        sta PL_ANGLE+3
        ldy #MO_SIZE + MA_SUBSEC        ; its subsector, for the light
        lda (GC_MP),y
        sta GT_2
        iny
        lda (GC_MP),y
        sta GT_3
        ldx #3
:       lda PLR + PL_VIEWZ_G,x
        sta PL_VIEWZ,x
        dex
        bpl :-
        ldx #1
:       lda PLR + PL_EXTRALIGHT,x
        sta PL_XLIGHT,x
        lda PLR + PL_FIXEDCOLORMAP,x
        sta PL_FIXCM,x
        lda PLR + PL_POWERS_0 + 2 * UC_PW_INVISIBILITY,x
        sta PL_INVIS,x
        dex
        bpl :-
        lda GT_2                ; the subsector's sector, its light
        ldx GT_3
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        jsr sec_get
        ldy #SEC_LIGHT
        lda (GC_SP),y
        sta PL_SECLIGHT
        stz PSPF
        ldx #0                  ; psprite 0, then 1
        jsr ri_psp
        ldx #PL_PSPRITES_1_STATE - PL_PSPRITES_0_STATE
        ; (on into ri_psp)

; ri_psp: psprite X (its offset in the player): PSPn_*, PSPF
ri_psp: stx GT_4
        lda PLR + PL_PSPRITES_0_STATE,x
        sta GT_5
        lda PLR + PL_PSPRITES_0_STATE + 1,x
        sta GT_6
        and GT_5
        cmp #$FF
        bne @state
        lda #$FF                ; none
        sta GT_0
        sta GT_1
        sta GT_2
        bra @put
@state: lda GT_5
        ldx GT_6
        jsr state_at            ; LW_STATE
        lda LW_STATE + U_ST_SPRITE
        sta GT_0
        lda LW_STATE + U_ST_FRAME
        sta GT_1
        lda LW_STATE + U_ST_FRAME + 1
        sta GT_2
        lda #1                  ; PSPF: bit 0 psprite 0, bit 1 psprite 1
        ldx GT_4
        beq :+
        lda #2
:       tsb PSPF
@put:   ldx GT_4
        ldy #0
        cpx #0
        beq :+
        ldy #PSP1_SPR - PSP0_SPR
:       lda GT_0
        sta PSP0_SPR,y
        lda GT_1
        sta PSP0_FRAME,y
        lda GT_2
        sta PSP0_FRAME+1,y
        lda PLR + PL_PSPRITES_0_SX,x
        sta PSP0_SX,y
        lda PLR + PL_PSPRITES_0_SX + 1,x
        sta PSP0_SX+1,y
        lda PLR + PL_PSPRITES_0_SY,x
        sta PSP0_SY,y
        lda PLR + PL_PSPRITES_0_SY + 1,x
        sta PSP0_SY+1,y
        lda PLR + PL_PSPRITES_0_SY + 2,x
        sta PSP0_SY+2,y
        lda PLR + PL_PSPRITES_0_SY + 3,x
        sta PSP0_SY+3,y
        rts
        .assert PSP1_SPR - PSP0_SPR = PSP1_SY - PSP0_SY, error, "the psprite inputs"
        .assert TH_X = 0 && TH_Y = 4, error, "RTHING's x, y"

; planes_out: W's planes back to MOBJP (a page at a time; gdriver.s's)
planes_out:
        lda #MOBJP
        sta FA_BANK
        stz FA_SRC
        stz FA_DST
        stz FA_N
        lda #>PL_TNL
:       sta FA_SRC+1
        sta FA_DST+1
        jsr far_put
        lda FA_SRC+1
        inc a
        cmp #>(PL_TICS + PLANE_SLOTS)
        bne :-
        rts

; the images (playimg.inc, generated by tools/native/playlink.py from the
; links: each image's bank, its page runs, 0)
        .include "playimg.inc"
