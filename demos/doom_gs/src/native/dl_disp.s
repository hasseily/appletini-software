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
; and the walk's planes back to MOBJP (the next image overwrites W); and
; it sets the kernel's two load lists for the next K_TIC (dl_kern.s, at
; KLISTS): the core from $66 when the list's last image is P2DW (st_load,
; kc_from: P2DW leaves the tic image's MATHW and AUXW in $6000-$65FF, and
; no list has a W step after P2DW's load; playdisk.py checks the bytes and
; P2DW's writes there), else from $60; each plane's pages below G_MOHWM
; (planes_out; all three after a load, which sets a new G_MOHWM). The
; speed plan's part ticloads (docs/speed-parts/ticloads.md).
;
; While the menu benchmark is timed (docs/PLAY.md 15) a level frame's list
; also calls the kernel's bt_mark at three boundaries (before K_MLOAD,
; after nb_frame, before K_END), and this group holds the timing's own
; routines (bt_start, bt_stop, bt_close: at the end of this file).

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

        .import go_flush, mo_get, ss_get, sec_get, state_at
        .import fc_call, fc_unbuilt
        .export c_display, c_loadlist, c_bootlist, c_menulist, c_cplist
        .export c_amlist, c_quitlist, c_savelist, ri_make, planes_out
        .export bt_start, bt_stop, bt_close

PLR = G_PLAYER
KLISTS = BT_REPLAY - 12         ; the kernel's k_core and k_planes
KCORE = KLISTS                  ;   (dl_kern.s: their place asserted there
KPLANES = KLISTS + 3            ;   and in playdisk.py)
KC_ALL = $60                    ; k_core's first page: W and the core
KC_SKIP = $66                   ;   the core alone (P2DW's W kept)

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
        lda #PH_REST            ; (the benchmark's timing: the phase after
        sta BT_NX               ;   the tic phase, docs/PLAY.md 15)
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
        lda #PH_3D              ; (timed: the front end after the tic
        sta BT_NX               ;   phase)
        STOP K_WLOAD            ; milestone 7's front end
        STCALL XS_nr_frame, #0
        lda #PH_MASK            ; (timed: the masked phase and the
        jsr st_mark             ;   bucket pass from here)
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
        lda #PH_REST            ; (timed: the rest from here)
        jsr st_mark
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
        lda #PH_TIC             ; (timed: the tic phase from here)
        jsr st_mark
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
        jsr c_out
        lda #PLANE_SLOTS >> 8   ; nl_setup sets a new G_MOHWM: the planes
        jmp kpl_set             ;   whole at E_RESUME

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
; st_mark: while the benchmark is timed (BT_PH not 0), a K_CALL of the
; kernel's bt_mark with A = the phase that starts (docs/PLAY.md 15)
st_mark:
        ldx BT_PH
        beq @off
        tax
        lda #<BT_MARK
        ldy #>BT_MARK
        jmp st_call
@off:   rts
; st_load: K_LOAD of the descriptor at Y:A (its bank, its page runs, 0);
; the next K_TIC's core from $66 when it is P2DW's, else from $60 (the
; list's last load decides)
st_load:
        sta GT_0
        sty GT_1
        ldx #KC_ALL
        cmp #<img_p2dw
        bne :+
        cpy #>img_p2dw
        bne :+
        ldx #KC_SKIP
:       txa
        jsr kc_from
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

; kc_from: the kernel's k_core from page A (KC_ALL or KC_SKIP), its count
; changed by as many pages (it is the boot's, XS_CORE_PAGES, from KC_ALL).
; Changes A, X.
kc_from:
        tax
        sec
        sbc KCORE               ; the first page's change
        stx KCORE
        eor #$FF                ; the count less the change
        sec
        adc KCORE+1
        sta KCORE+1
        rts

; planes_out: the walk's four planes back to MOBJP, each plane's pages
; below G_MOHWM (1-3: one when it is 0, all three past the planes, as at the
; boot before a level's state is set), in one RAMWRT window run from this
; group's code in W (the fetches read main; the IRQ contract allows any
; RAMWRT: pl_irq.s); and the next K_TIC's planes list, the same pages
; (kpl_set). The slots past G_MOHWM in W then hold another image's bytes,
; never read: a slot becomes used (gt_pooltake raises G_MOHWM) before its
; planes are written (gt_mosave). Changes A, X, Y, GT_0-3.
PO_N = GT_0                     ; the pages of a plane
PO_P = GT_1                     ; (2) the page
PO_S = GT_3                     ; the plane's first page
planes_out:
        lda G_MOHWM             ; (G_MOHWM + 255) >> 8
        cmp #1
        lda G_MOHWM+1
        adc #0
        bne :+
        lda #1
:       cmp #(PLANE_SLOTS >> 8) + 1
        bcc :+
        lda #PLANE_SLOTS >> 8
:       sta PO_N
        jsr kpl_set
        lda #MOBJP
        sta RWBANK
        sta RAMWRTON
        stz PO_P
        ldy #0
        lda #>PL_TNL
@plane: sta PO_S
        sta PO_P+1
        ldx PO_N
:       lda (PO_P),y            ; main W to the bank's same address
        sta (PO_P),y
        iny
        lda (PO_P),y
        sta (PO_P),y
        iny
        bne :-
        inc PO_P+1
        dex
        bne :-
        lda PO_S                ; the next plane
        clc
        adc #>PLANE_SLOTS
        cmp #>(PL_TICS + PLANE_SLOTS)
        bne @plane
        sta RAMWRTOFF
        stz RWBANK
        rts
; kpl_set: the kernel's k_planes, A pages of each plane (1-3)
kpl_set:
        sta KPLANES+1
        sta KPLANES+3
        sta KPLANES+5
        sta KPLANES+7
        rts
        .assert PL_TNH = PL_TNL + PLANE_SLOTS && PL_KIND = PL_TNH + PLANE_SLOTS && PL_TICS = PL_KIND + PLANE_SLOTS, error, "the planes"
        .assert <PL_TNL = 0 && <PLANE_SLOTS = 0, error, "the planes' pages"

; the images (playimg.inc, generated by tools/native/playlink.py from the
; links: each image's bank, its page runs, 0)
        .include "playimg.inc"

; ---------------------------------------------------------------------------
; The benchmark's phase timing (docs/PLAY.md 15). While it runs (from its
; load's E_RESUME to G_TimeDemoEnd or Escape), the Phasor's VIA-A timer 1
; (pl_detect's; it counts the Apple bus cycles down, 65,536 a turn) is read
; at the frame's phase boundaries and the cycles go to five sums in DLM
; (BT_S): PH_TIC the tic phase (the tic image back, the brain, the tics, the
; list, its caches back), PH_3D K_WLOAD and nr_frame, PH_MASK K_MLOAD,
; nm_masked, nm_bkload and nb_frame's bucket pass, PH_DRAW nb_frame's
; replays (nat_replay), PH_REST the rest (PALW, P2DW, s2_frame, the poll).
; The kernel's bt_mark times the short phases (each interval mod 65,536);
; bt_close, at the brain's end, times the tic phase, which is longer than
; the timer's turn, with vbl_count's help (bt_span), and checks the short
; phases' sums over the same span: the turns an interval of 3 VBLs or
; more lost go back to its phase (BT_LP), any other is counted in BT_OVF
; (shown). The page's rows: dl_cmd.s's bt_rows. This code is in DLG_DISP,
; which is loaded about once a frame, not in the brain's group, which is
; loaded again after each tic (its size costs a load each time).
; ---------------------------------------------------------------------------
BT_T1CL  = $C414                ; the Phasor's VIA-A timer 1 (dl_kern.s's
BT_T1CH  = $C415                ;   bt_mark's)
BT_CPAL  = 20280                ; Apple bus cycles a VBL: 312 lines of 65
BT_CNTSC = 17030                ;   (PAL), 262 (NTSC): pl_detect's
; zero page: the math's temporaries (udiv32 changes MT+0 - MT+5)
BZ_OT    = MT                   ; a span's first reading (2), its VBL byte
BZ_OV    = MT + 2
BZ_NT    = MT + 3               ; its last reading (2), its VBL byte
BZ_NV    = MT + 5
BZ_E     = MT + 6               ; bt_close: the short span (4)
        .assert BT_J = BT_S + 25 && BT_SS = BT_S + 20, error, "BT_S .. BT_J"

; bt_ext: bt_mark's middle part (dl_kern.s), assembled for BT_EXT (main
; $0844, free: MEMORY_MAP.md 3.2), where bt_start copies it. Y:X = the
; cycles since the last boundary (mod 65,536). vbl_count's low byte kept;
; an interval of 3 VBLs or more may have passed the timer's turn (one of
; 2 or fewer lasts under 3 x 20,280 cycles and the VBL interrupt's
; lateness, which stays below the 4,696 left of the turn on PAL): its
; phase into BT_LP for bt_close (a second one in the same span counted in
; BT_OVF). Then bt_mark's last part with A = X, X = the phase that ran.
bt_ext_img:
        .org BT_EXT
bt_ext:
        lda XS_vbl_count
        sec
        sbc BT_V
        cmp #3
        bcc @ok
        lda BT_LP
        beq :+
        inc BT_OVF
:       lda BT_PH
        sta BT_LP
@ok:    lda XS_vbl_count
        sta BT_V
        txa
        ldx BT_PH
        jmp BT_MARK2            ; (Z: no phase)
bt_ext_end:
        .reloc
BT_EXT_SIZE = bt_ext_end - bt_ext
        .assert BT_EXT_SIZE <= BT_EXT_END - BT_EXT, error, "bt_ext"

; bt_read: the timer into Y:X (low first, both again past a borrow, as
; bt_mark), A = vbl_count's low byte
bt_read:
        ldx BT_T1CL
        ldy BT_T1CH
        cpx #8
        bcs :+
        ldx BT_T1CL
        ldy BT_T1CH
:       lda XS_vbl_count
        rts

; bt_start: the timing from here, in the tic phase: the sums 0, the
; readings now, nat_replay's entry to the kernel's bt_replay (when its
; first instruction is sta abs, as built: sta gcol; else no PH_DRAW), its
; 3 bytes into BT_J with jmp nat_replay + 3 after them
bt_start:
        ldx #BT_EXT_SIZE - 1    ; bt_mark's middle part
:       lda bt_ext_img,x
        sta BT_EXT,x
        dex
        bpl :-
        ldx #BT_J - BT_S - 1    ; BT_S, BT_SS, BT_OVF
:       stz BT_S,x
        dex
        bpl :-
        stz BT_LP
        jsr bt_read
        stx BT_T
        sty BT_T+1
        stx BT_CT
        sty BT_CT+1
        sta BT_V
        sta BT_CV
        lda #PH_TIC
        sta BT_PH
        lda XS_nat_replay
        cmp #$8D
        bne @no
        ldx #2
:       lda XS_nat_replay,x
        sta BT_J,x
        dex
        bpl :-
        lda #$4C                ; jmp nat_replay + 3
        sta BT_J+3
        lda #<(XS_nat_replay + 3)
        sta BT_J+4
        lda #>(XS_nat_replay + 3)
        sta BT_J+5
        lda #$4C                ; jmp bt_replay over its first instruction
        sta XS_nat_replay
        lda #<BT_REPLAY
        sta XS_nat_replay+1
        lda #>BT_REPLAY
        sta XS_nat_replay+2
@no:    rts

; bt_stop: the timing's end (G_TimeDemoEnd's, Escape's): the phase that
; runs closed, none after it; nat_replay's entry back
bt_stop:
        lda BT_PH
        beq :+
        lda #0
        jsr bt_close
:       lda BT_J+3
        cmp #$4C
        bne @done
        ldx #2
:       lda BT_J,x
        sta XS_nat_replay,x
        dex
        bpl :-
        stz BT_J+3
@done:  rts

; bt_close: A = the phase from now (0: none). First the span from the last
; close to the last boundary (BT_CT .. BT_T, the short phases'), exactly,
; against their sums' growth (each interval mod 65,536): the turns lost go
; to the phase of the span's long interval (BT_LP, bt_ext's), or, with
; none, are counted (BT_OVF). Then the cycles since the last boundary to
; BT_PH's sum, exactly (the tic phase: longer than a turn); this reading
; the last boundary and close.
bt_close:
        pha
        lda BT_CT
        sta BZ_OT
        lda BT_CT+1
        sta BZ_OT+1
        lda BT_CV
        sta BZ_OV
        lda BT_T
        sta BZ_NT
        lda BT_T+1
        sta BZ_NT+1
        lda BT_V
        sta BZ_NV
        jsr bt_span
        ldx #3
:       lda M_R,x
        sta BZ_E,x
        dex
        bpl :-
        jsr bt_short            ; M_A = the short sums; their growth
        ldx #0
        ldy #4
        sec
:       lda M_A,x
        sbc BT_SS,x
        sta M_B,x
        inx
        dey
        bne :-
        ldx #0                  ; the span - the growth: the turns the
        ldy #4                  ;   short phases lost (65,536 each)
        sec
:       lda BZ_E,x
        sbc M_B,x
        sta BZ_E,x
        inx
        dey
        bne :-
        lda BZ_E+3
        ora BZ_E+2
        ora BZ_E+1
        ora BZ_E
        beq @tic
        ldx BT_LP               ; to the long interval's phase (bt_ext's)
        bne @lost
        inc BT_OVF              ; (none: counted)
        bra @tic
@lost:  clc
        lda BT_S-4,x
        adc BZ_E
        sta BT_S-4,x
        lda BT_S-3,x
        adc BZ_E+1
        sta BT_S-3,x
        lda BT_S-2,x
        adc BZ_E+2
        sta BT_S-2,x
        lda BT_S-1,x
        adc BZ_E+3
        sta BT_S-1,x
@tic:   stz BT_LP
        lda BT_T                ; the last boundary to now
        sta BZ_OT
        lda BT_T+1
        sta BZ_OT+1
        lda BT_V
        sta BZ_OV
        jsr bt_read
        stx BZ_NT
        sty BZ_NT+1
        sta BZ_NV
        jsr bt_span
        ldx BT_PH
        clc
        lda BT_S-4,x
        adc M_R
        sta BT_S-4,x
        lda BT_S-3,x
        adc M_R+1
        sta BT_S-3,x
        lda BT_S-2,x
        adc M_R+2
        sta BT_S-2,x
        lda BT_S-1,x
        adc M_R+3
        sta BT_S-1,x
        lda BZ_NT               ; this reading: the last boundary, the
        sta BT_T                ;   last close
        sta BT_CT
        lda BZ_NT+1
        sta BT_T+1
        sta BT_CT+1
        lda BZ_NV
        sta BT_V
        sta BT_CV
        jsr bt_short
        ldx #3
:       lda M_A,x
        sta BT_SS,x
        dex
        bpl :-
        pla
        sta BT_PH
        rts

; bt_short: M_A = the four short phases' sums (PH_3D .. PH_REST)
bt_short:
        ldx #3
:       stz M_A,x
        dex
        bpl :-
        ldx #PH_3D
@sum:   clc
        lda M_A
        adc BT_S-4,x
        sta M_A
        lda M_A+1
        adc BT_S-3,x
        sta M_A+1
        lda M_A+2
        adc BT_S-2,x
        sta M_A+2
        lda M_A+3
        adc BT_S-1,x
        sta M_A+3
        inx
        inx
        inx
        inx
        cpx #PH_REST + 4
        bne @sum
        rts

; bt_span: M_R = the bus cycles from the reading BZ_OT, BZ_OV to BZ_NT,
; BZ_NV: d = the timer's difference (mod 65,536), v = the VBLs between;
; the cycles are d + 65,536 k with k = (v C - d + 32,768) >> 16 (C a VBL's
; cycles, CLK_STD's PAL or NTSC): the span is within a VBL and the VBL
; interrupt's lateness of v C, far less than half a turn. Exact for a span
; under 256 VBLs (5.1 s on PAL).
bt_span:
        sec
        lda BZ_OT
        sbc BZ_NT
        sta M_R
        lda BZ_OT+1
        sbc BZ_NT+1
        sta M_R+1
        sec                     ; M_A = 32,768 - d (24 bits)
        lda #0
        sbc M_R
        sta M_A
        lda #$80
        sbc M_R+1
        sta M_A+1
        lda #0
        sbc #0
        sta M_A+2
        ldx #<BT_CPAL
        ldy #>BT_CPAL
        bit CLK_STD
        bpl :+
        ldx #<BT_CNTSC
        ldy #>BT_CNTSC
:       stx M_B
        sty M_B+1
        sec
        lda BZ_NV
        sbc BZ_OV
        tax
        beq @k
@vbl:   clc                     ; + C for each VBL
        lda M_A
        adc M_B
        sta M_A
        lda M_A+1
        adc M_B+1
        sta M_A+1
        bcc :+
        inc M_A+2
:       dex
        bne @vbl
@k:     lda M_A+2
        sta M_R+2
        stz M_R+3
        rts

