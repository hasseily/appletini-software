; s2_menu.s: the menu engine and the main pages in MENUW (docs/SCREENS.md,
; the menu; part s2menu1). GPL-2: rewritten from upstream's
; src/iigs/m_menu65.s (Doom8088: Apple IIgs Edition, GPL-2): M_Init,
; M_StartControlPanel, M_DrawVersion, M_SkullVersion, M_Ticker, M_Responder
; and its handlers, clearMenus, setupMenu, startMessage, the main, new game,
; skill and options pages, M_Drawer, menu, M_DrawSkull, skullPlace,
; M_SkullRect, drawMessage, lineWidth, writeLine [R m_menu65.s:518-1593],
; and the settings pages' frame uiSettings, uiAlign, uiCenter, bmWrite,
; bmBox, uiMain, vwKeys [R :1602-1631, :1661-1755, :2716-2738, :2842-3001],
; which the options page draws through; d_main65.s's uiDisplay [R
; i_viigs65.s:2047-2055].
;
; MENUW stays in W while a menu is up (the game is paused: no tic or
; render image runs [R d_main65.s:261-279]); its state is the block at
; $BF00 (s2layout's M_*, and the native M_*), PALST
; at S2M_PALST, both fetched by m_load and written
; back by m_save.
;
;   m_init      M_Init and uiInit's state (the lumps and the skulls' box
;               are the build's: tools/native/s2menu1.py)
;   m_startcp   M_StartControlPanel with uiMain
;   m_ticker    M_Ticker: the key setup's key (PL_BIND, taken by pl_poll;
;               bound by pl_bind), the skull's blink every 8 tics
;   m_responder M_Responder: A = the event's type, X = its data1 (a Doom
;               key below NUMKEYS, else a character); A = 1 when eaten.
;               The game's actions become a request (M_REQ, M_REQARG) for
;               the second half; the sounds go to sc_start (no origin)
;   m_savedone  saveDone after the second half's save: C clear, the
;               message and the menu closes; C set, the failed save's
;               message (M_SaveFailed)
;
; SAVE SETTINGS (bmItem's item 4; docs/PLAY.md, "The settings file"):
; setchg is G_SettingsChanged, the settings now (GAMMA, showMessages, the
; effects' volume, SS_SETTINGS, PL_KEYTAB) against those the disk has
; (SET_FILE in SET_BANK, which DLINIT keeps), into M_SETCHG before each
; full drawing and before the item's routine: the item dim while they are
; equal. Changed, the item requests REQ_SAVESET; the second half's
; DLINIT dli_save writes the block and answers in M_SAVERES, which the
; next m_frame takes (savedone): a failed write's message (M_SaveFailed),
; the menu staying for another try, as upstream's
;   m_display   uiDisplay: the static screen (mv_static), else M_Drawer
;               in bands (mv_open the first time, mv_full), staticDrawn,
;               the finish (s2_finish)
;   m_frame     a paused frame's work in the frame's order: pl_poll,
;               sc_update, fx_service, snd_refill, m_display (the second half
;               runs m_ticker for the frame's tics and m_responder for its
;               events before it)
;   m_page      M_Drawer's drawing into the band (mv_full calls it once a
;               band): the message, or the page, its items, uiSettings
;               and the skull
;   m_skullrect M_SkullRect: C = 1 and skx, sky, skw, skh when a skull
;   m_drawskull M_DrawSkull
;   m_drawver, m_skullver   M_DrawVersion, M_SkullVersion: A, X
;   m_load, m_save          the state block and PALST from and to S2STATE
;   m_close     I_MenuPaletteBack (mv_close)
;
; For part s2menu2's pages (drawn in the band m_page sets): m_dpatch, the
; patch A (P_*) at S2M_X, S2M_Y (V_DrawNumPatchNotScaled, skipped when it
; misses the band); m_wline, writeLine of S2M_P from S2M_TP at S2M_X,
; S2M_Y (S2M_X moves on); m_wstr, bmWrite of the string A (low), X
; (high); m_align, uiAlign of the string A, X at y S2M_Y, Y = 0 centred,
; else its right edge at 284.
;
; The settings pages' values past ON/OFF (the view, the thermometers), the
; slots of the load and save pages, the key setup page and the benchmark's
; result are part s2menu2's: m2_page, m2_value, m2_bench (s2_menu2.s, linked
; into the one MENUW). Zero page: S2M_* ($80-$AF), the drawers' S2_*;
; sc_start uses $48-$74. A, X, Y changed.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2menu1.inc"

        .export m_init, m_startcp, m_ticker, m_responder, m_savedone
        .export m_display, m_frame, m_page, m_skullrect, m_drawskull
        .export m_drawver, m_skullver, m_load, m_save, m_close
        .export m_dpatch, m_wline, m_wstr, m_align
        .import mv_open, mv_full, mv_close, mv_static, mv_drawn, mv_shade
        .import mv_tables
        .import s2_vpatch, s2_mark, s2_mul160, s2_finish, s2_setpal
        .import s2_palget, s2_palput, far_get, far_put
        .import sc_start, sc_update, fx_service, snd_refill
        .import m2_page, m2_value, m2_bench
        .import pl_poll, pl_bind, pl_defaults, pl_mouseup

; upstream's numbers [R m_menu65.s:44-68, keys.inc]
SKULLXOFF   = 32
FONT_H      = 7                 ; HU_FONT_HEIGHT
FONT_SPACE  = 4                 ; HU_FONT_SPACE_WIDTH
NIGHTMARE   = 4
MENU_MAIN   = 0                 ; currentMenu
MENU_NEW    = 2
MENU_LOAD   = 4
MENU_OPTIONS = 6
MENU_CONTROLS = 8
MENU_SAVE   = 10
MENU_VIDEO  = 12
MENU_INPUT  = 16
MSG_NIGHTMARE = 0               ; messageKind
MSG_QUIT    = 4
MSG_ENDGAME = 8
MSG_SAVEDEAD = 12
MSG_BENCH   = 16
MSG_SAVEFAIL = 20
KEY_ESCAPE  = 9                 ; key_escape, key_menu_escape
KEY_FIRE    = 2                 ; key_fire
KEY_ZOOMOUT = 11                ; key_map_zoomout, key_map_zoomin
KEY_ZOOMIN  = 12
KEYC_UP     = $80               ; key_menu_up ... key_menu_back
KEYC_DOWN   = $81
KEYC_LEFT   = $82
KEYC_RIGHT  = $83
KEYC_ENTER  = $84
KEYC_BACK   = $85
BIND_ESC    = $1B               ; the //e's Esc (upstream's ADB_ESC $35)
I_SAVESET   = 23                ; SAVE SETTINGS, the options page's last
OPT_OFF     = 4                 ; uiKinds below 20: ON or OFF
OPT_VIEW    = 20
SET_ARUN    = 0                 ; SS_SETTINGS' bytes (s2layout's field map)
SET_MOUSE   = 2
SET_MSPEED  = 3
SET_MMOVE   = 4
SET_MUSVOL  = 5                 ; snd_MusicVolume
SET_N       = 6                 ; (detailLevel +1: the high detail only)
RES_FAIL    = 1                 ; M_SAVERES (dl_init.s's dli_save)
BOX_Y0      = 138               ; bmBox [R m_menu65.s:1661-1663]
BOX_Y1      = 138 + FONT_H
BOX_B0      = 30
BOX_B1      = 84

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; m_load, m_save: the state block and PALST from and to S2STATE.
; ---------------------------------------------------------------------------
m_load:
        jsr stateptr
        jsr far_get
        jmp s2_palget
m_save:
        jsr stateptr
        lda #<MENUW_STATE
        sta FA_SRC
        lda #>MENUW_STATE
        sta FA_SRC+1
        lda #<SS_MENUW
        sta FA_DST
        lda #>SS_MENUW
        sta FA_DST+1
        jsr far_put
        jmp s2_palput
stateptr:
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        lda #<SS_MENUW
        sta FA_SRC
        lda #>SS_MENUW
        sta FA_SRC+1
        lda #<MENUW_STATE
        sta FA_DST
        lda #>MENUW_STATE
        sta FA_DST+1
        rts

; ---------------------------------------------------------------------------
; m_init: M_Init [R m_menu65.s:582-635], uiInit [R :2676-2681].
; ---------------------------------------------------------------------------
m_init:
        stz M_CURRENT
        lda #$FF                ; (PL_BIND, upstream's iigs_bindwait, is
        sta M_BINDROW           ;   the input's: pl_init)
        stz SM_MENUACTIVE
        stz SM_MENUACTIVE+1
        stz M_WHICHSKULL
        lda #10
        sta M_SKULLCOUNT
        stz M_MSGPRINT
        stz M_MSGLAST
        stz M_PALON
        lda #$FF
        sta M_PICTURE
        sta M_PICTURE+1
        lda #5
        sta M_MAINN
        stz M_REQ
        stz M_RELOAD
        rts

; ---------------------------------------------------------------------------
; m_startcp: M_StartControlPanel [R :685-691] and uiMain [R :2717-2738].
; ---------------------------------------------------------------------------
m_startcp:
        lda SM_MENUACTIVE
        bne @main
        lda #1
        sta SM_MENUACTIVE
        stz SM_MENUACTIVE+1
        stz M_CURRENT
        jsr menuver
@main:  ldx #5                  ; the main menu's rows: QUIT, or END GAME
        lda SM_USERGAME         ;   and QUIT in a player's game
        ora SM_USERGAME+1
        beq :+
        inx
:       stx M_MAINN
        lda M_CURRENT
        bne @done
        lda M_ITEMON
        cmp M_MAINN
        bcc @done
        stz M_ITEMON
@done:  rts

menuver:
        inc M_MENUVER
        bne :+
        inc M_MENUVER+1
:       rts
skullver:
        inc M_SKULLVER
        bne :+
        inc M_SKULLVER+1
:       rts

m_drawver:
        lda M_MENUVER
        ldx M_MENUVER+1
        rts
m_skullver:
        lda M_SKULLVER
        ldx M_SKULLVER+1
        rts

; ---------------------------------------------------------------------------
; m_ticker: M_Ticker [R :710-735].
; ---------------------------------------------------------------------------
m_ticker:
        lda M_BINDROW
        bmi @skull
        ldx PL_BIND             ; the input layer's bind state (the poll
        cpx #PLB_WAIT           ;   writes the key it took over
        beq @skull              ;   PLB_WAIT)
        cpx #PLB_IDLE           ; (PLB_IDLE: no key taken, nothing to
        bcs :+                  ;   bind)
        cpx #BIND_ESC
        beq :+
        ldy M_BINDROW
        lda ctl_keys,y
        jsr pl_bind             ; I_BindKey(A the Doom key, X the key)
:       lda #PLB_IDLE
        sta PL_BIND
        lda #$FF
        sta M_BINDROW
        jsr menuver
@skull: dec M_SKULLCOUNT
        beq :+
        bpl @done
:       lda M_WHICHSKULL
        eor #1
        sta M_WHICHSKULL
        lda #8
        sta M_SKULLCOUNT
        jsr skullver
@done:  rts

; ---------------------------------------------------------------------------
; m_responder: M_Responder [R :743-775].
; ---------------------------------------------------------------------------
m_responder:
        stx S2M_CH
        ldx M_CURRENT           ; the state before
        stx S2M_MENU
        ldx M_ITEMON
        stx S2M_ITON
        ldx SM_MENUACTIVE
        stx S2M_ACT
        ldx M_MSGPRINT
        stx S2M_MSG
        jsr event
        bcs :+
        lda #0
        rts
:       lda M_CURRENT           ; only the skull moved: skullversion
        cmp S2M_MENU
        bne @menu
        lda SM_MENUACTIVE
        cmp S2M_ACT
        bne @menu
        lda M_MSGPRINT
        cmp S2M_MSG
        bne @menu
        lda SM_MENUACTIVE
        beq @menu
        lda M_MSGPRINT
        bne @menu
        lda M_ITEMON
        cmp S2M_ITON
        beq @menu
        jsr skullver
        bra @yes
@menu:  jsr menuver
@yes:   lda #1
        rts

; event: responderEvent [R :778-897]: C set when eaten.
no:     clc
        rts
event:
        cmp #0                  ; key downs only
        bne no
        lda M_MSGPRINT
        beq @menu
        lda M_MSGKIND           ; a message: any key, or Y, N or Esc
        cmp #MSG_SAVEDEAD
        bcs :+
        lda S2M_CH
        cmp #'n'
        beq :+
        cmp #'y'
        beq :+
        cmp #KEY_ESCAPE
        bne no
:       lda M_MSGLAST
        sta SM_MENUACTIVE
        stz SM_MENUACTIVE+1
        stz M_MSGPRINT
        ldx #0                  ; the answer: ch == 'y'
        lda S2M_CH
        cmp #'y'
        bne :+
        inx
:       txa
        jsr answer
        lda M_MSGKIND           ; a failed save: back to its menu
        cmp #MSG_SAVEFAIL
        beq :+
        jsr clearmenus
:       lda #SFX_SWTCHX
        jmp sound
@menu:  lda SM_MENUACTIVE
        bne @act
        jmp vwkeys
@act:   jsr page                ; X = the page, S2M_N its items
        jsr menunum
        sta S2M_N
        lda S2M_CH
        cmp #KEYC_DOWN
        bne @up
        lda M_ITEMON            ; down: the next item, or the first
        inc a
        cmp S2M_N
        bcc :+
        lda #0
:       sta M_ITEMON
        lda #SFX_PSTOP
        jmp sound
@up:    cmp #KEYC_UP
        bne @left
        lda M_ITEMON            ; up: the item before, or the last
        bne :+
        lda S2M_N
:       dec a
        sta M_ITEMON
        lda #SFX_PSTOP
        jmp sound
@left:  cmp #KEYC_LEFT
        bne @right
        lda #0                  ; left: an item with arrows, 0
        bra @arrow
@right: cmp #KEYC_RIGHT
        bne @enter
        lda #1                  ; right: 1
@arrow: sta S2M_K
        jsr item
        jsr arrows
        bne @eaten
        lda #SFX_STNMOV
        jsr sound
        lda S2M_K
        jsr routine
@eaten: sec
        rts
@enter: cmp #KEYC_ENTER
        bne @esc
        jsr item                ; enter: the item's routine
        jsr arrows
        bne :+
        lda #1                  ; (with arrows: right)
        jsr routine
        lda #SFX_STNMOV
        jmp sound
:       lda M_ITEMON
        jsr routine
        lda #SFX_PISTOL
        jmp sound
@esc:   cmp #KEY_ESCAPE         ; Esc, fire or Delete: back
        beq @back
        cmp #KEY_FIRE
        beq @back
        cmp #KEYC_BACK
        beq @back
        clc
        rts
@back:  jsr page                ; to the parent and its item; the main
        lda t_prev,x            ;   menu closes instead
        bpl :+
        jsr clearmenus
        bra @sw
:       ldy t_previ,x
        jsr setupmenu
        sty M_ITEMON
@sw:    lda #SFX_SWTCHX
        ; (on to sound)

; sound: S_StartSound(NULL, A) through sc_start [R :910-913]; C set
; (the event eaten). With -D S2M_SNDLOG (no build here defines it) each
; sound is also logged.
sound:
        sta SM_GA
        stz SM_GA+1
        lda #ORG_NONE
        sta SM_GA+2
        lda #$FF
        sta SM_GA+3
        sta SM_GA+4
.ifdef S2M_SNDLOG
        lda SM_GA
        jsr m_sndlog
.endif
        jsr sc_start
        sec
        rts

; page: X = the page (currentMenu / 2). Keeps A, Y.
page:
        pha
        lda M_CURRENT
        lsr a
        tax
        pla
        rts

; item: X = the item under the skull, S2M_ITEM too [R :901-907]
item:
        jsr page
        lda t_items,x
        clc
        adc M_ITEMON
        sta S2M_ITEM
        tax
        rts

; arrows: Z set when the item S2M_ITEM has arrows (itemStatus 2: MESSAGES,
; and the settings rows 44-51 [R :3084-3086])
arrows:
        lda S2M_ITEM
        cmp #19
        beq @yes
        cmp #44
        bcc @no
        cmp #52
        bcs @no
@yes:   lda #0
        rts
@no:    lda #1
        rts

; routine: the item S2M_ITEM's routine with A = the choice
routine:
        pha
        lda S2M_ITEM
        asl a
        tax
        pla
        jmp (t_routine,x)

; clearmenus: M_ClearMenus [R :942-945]
clearmenus:
        jsr m_close
        stz SM_MENUACTIVE
        stz SM_MENUACTIVE+1
        stz M_ITEMON
        rts
; m_close: I_MenuPaletteBack (the frame driver's part, displayCall and
; singletics, is the second half's)
m_close:
        jmp mv_close

; setupmenu: M_SetupNextMenu(A) [R :946-948]. Keeps X, Y.
setupmenu:
        sta M_CURRENT
        stz M_ITEMON
        rts

; startmessage: M_StartMessage of the message A [R :951-958] (uiOpen,
; the display's switch to the menu's, is the second half's)
startmessage:
        sta M_MSGKIND
        lda SM_MENUACTIVE
        sta M_MSGLAST
        lda #1
        sta M_MSGPRINT
        sta SM_MENUACTIVE
        stz SM_MENUACTIVE+1
        rts

; request: the action A with the argument X for the second half
request:
        sta M_REQ
        stx M_REQARG
        rts

; answer: the message's routine, A = 1 for yes [R :916-939]
answer:
        ldx M_MSGKIND
        cpx #MSG_NIGHTMARE
        bne @quit
        cmp #0                  ; nightmare: a new game
        beq @done
        lda #REQ_NEWGAME
        ldx #NIGHTMARE
        jmp request
@quit:  cpx #MSG_QUIT
        bne @end
        cmp #0
        beq @done
        lda #REQ_QUIT           ; I_Quit
        ldx #0
        jmp request
@end:   cpx #MSG_SAVEDEAD
        bcs @done
        cmp #0                  ; end game: the demo ends, the title comes
        beq @done
        jsr clearmenus
        lda #REQ_ENDGAME        ; G_CheckDemoStatus when a single demo
        ldx SM_SINGLEDEMO       ;   plays, then D_StartTitle
        beq :+
        ldx #1
:       jmp request
@done:  rts

; vwkeys: M_Responder with no menu [R :1602-1631]: the view size's keys in
; a level (the full view only: no change, the key eaten), Esc opens the
; menu
vwkeys:
        lda SM_GAMESTATE
        ora SM_GAMESTATE+1
        bne @esc
        lda SM_AUTOMAP          ; the automap takes its zoom keys
        and #1
        bne @esc
        lda S2M_CH
        cmp #KEY_ZOOMOUT
        beq :+
        cmp #KEY_ZOOMIN
        bne @esc
:       lda #SFX_STNMOV         ; uiViewChange: the full view only
        jmp sound
@esc:   lda S2M_CH
        cmp #KEY_ESCAPE
        beq :+
        clc
        rts
:       jsr m_startcp           ; (bmStop: the brain's ev_route, first)
        lda #SFX_SWTCHN
        jmp sound

; ---------------------------------------------------------------------------
; The items' routines, A = the choice [R :963-1079, :1214-1235, :2180-2188]
; ---------------------------------------------------------------------------
r_newgame:
        lda #MENU_NEW           ; the skills at "hurt me plenty"
        jsr setupmenu
        lda #2
        sta M_ITEMON
        rts
r_options:
        lda #MENU_OPTIONS
        jmp setupmenu
r_loadgame:
        lda #MENU_LOAD
        jmp setupmenu
r_controls:
        lda #MENU_CONTROLS
        jmp setupmenu
r_video:
r_sound:
        lda #MENU_VIDEO
        jmp setupmenu
r_input:
        lda #MENU_INPUT
        jmp setupmenu
r_savegame:
        lda SM_USERGAME         ; a player's game, or a demo
        ora SM_USERGAME+1
        ora SM_DEMOPLAY
        ora SM_DEMOPLAY+1
        bne :+
        lda #MSG_SAVEDEAD
        jmp startmessage
:       lda SM_GAMESTATE        ; in a level
        ora SM_GAMESTATE+1
        bne :+
        lda #MENU_SAVE
        jmp setupmenu
:       rts
r_main4:
        lda M_MAINN             ; uiMain's row 4: END GAME in a game
        cmp #6
        bne r_quit
        lda #MSG_ENDGAME
        jmp startmessage
r_quit:
        lda #MSG_QUIT
        jmp startmessage
r_skill:
        cmp #NIGHTMARE          ; nightmare: are you sure
        bne :+
        lda #MSG_NIGHTMARE
        jsr startmessage
        stz M_ITEMON
        rts
:       tax                     ; G_DeferedInitNew
        lda #REQ_NEWGAME
        jsr request
        jmp clearmenus
r_loadsel:
        tax                     ; G_LoadGame
        lda #REQ_LOAD
        jsr request
        jmp clearmenus
r_savesel:
        tax                     ; G_SaveGame, G_SaveSettings: the second
        lda #REQ_SAVE           ;   half, then m_savedone
        jmp request
r_messages:
        lda SM_SHOWMSG          ; messages on or off
        eor #1
        sta SM_SHOWMSG
        stz SM_SHOWMSG+1
        ldx #<SM_ID_MSGON
        ldy #>SM_ID_MSGON
        cmp #0
        bne :+
        ldx #<SM_ID_MSGOFF
        ldy #>SM_ID_MSGOFF
:       jsr message
        lda #1
        sta SM_MSGKEEP
        stz SM_MSGKEEP+1
        rts
r_arun:
        ldx #SET_ARUN           ; always run on or off
        jsr toggle
        ldx #<SM_ID_RUNON
        ldy #>SM_ID_RUNON
        cmp #0
        bne :+
        ldx #<SM_ID_RUNOFF
        ldy #>SM_ID_RUNOFF
:       jmp message
r_mouse:
        ldx #SET_MOUSE          ; the mouse on or off, its buttons up
        jsr toggle
        jmp pl_mouseup
r_mmove:
        ldx #SET_MMOVE
        jmp toggle
r_mspeed:
        sta S2M_K               ; the mouse speed 0-9
        ldx #SET_MSPEED
        jsr getset
        ldx S2M_K
        bne @up
        cmp #0
        beq @done
        dec a
        bra @put
@up:    cmp #9
        bcs @done
        inc a
@put:   ldx #SET_MSPEED
        jmp putset
@done:  rts
r_gamma:
        tax                     ; gammatab's rows: 0-4
        bne @up
        lda SM_GAMMA
        beq @set
        dec SM_GAMMA
        bra @set
@up:    cpx #1
        bne @set
        lda SM_GAMMA
        cmp #4
        bcs @set
        inc SM_GAMMA
@set:   lda #0                  ; (uiReload: after the close) I_SetPalette(0)
        jmp s2_setpal
r_sfxvol:
        tax                     ; uiVolume: SFX 0-15, S_SetSfxVolume
        lda SND_SFXVOL
        cpx #0
        beq @down
        cmp #15
        bcs @set
        inc a
        bra @set
@down:  cmp #0
        beq @set
        dec a
@set:   sta SND_SFXVOL
        rts
r_musvol:
        sta S2M_K               ; uiVolume: the music's 0-15 in
        ldx #SET_MUSVOL         ;   SS_SETTINGS (S_SetMusicVolume: the
        jsr getset              ;   owner's mix stays as it is; the
        ldx S2M_K               ;   release's MUSIC_MENU is 1)
        bne @up
        cmp #0
        beq @done
        dec a
        bra @put
@up:    cmp #15
        bcs @done
        inc a
@put:   ldx #SET_MUSVOL
        jmp putset
@done:  rts
r_viewsize:
        rts                     ; the full view only (s2menu2's uiView*)
r_bind:
        sta M_BINDROW           ; the next key is for this action: the
        lda #PLB_WAIT           ;   poll takes it into PL_BIND
        sta PL_BIND
        rts
r_defkeys:
        jmp pl_defaults
r_vwitem:
        cmp #3                  ; bmItem: BENCHMARK closes the menu and
        bne @save               ;   times demo3
        jsr clearmenus
        lda #REQ_BENCH
        ldx #0
        jmp request
@save:  jsr setchg               ; SAVE SETTINGS when they changed
        lda M_SETCHG
        beq :+
        lda #REQ_SAVESET
        ldx #0
        jmp request
:       rts

; message: player.message = the symbol X (low), Y (high)
message:
        lda #SM_TAG_SYMBOL
        sta SM_PLMSG
        stx SM_PLMSG+1
        sty SM_PLMSG+2
        stz SM_PLMSG+3
        stz SM_PLMSG+4
        rts

; toggle: the setting X = 1 - itself; A its new value
toggle:
        phx
        jsr getset
        eor #1
        plx
        pha
        jsr putset
        pla
        rts

; getset: A = SS_SETTINGS + X. putset: SS_SETTINGS + X = A.
getset:
        jsr setptr
        lda #<S2M_T
        sta FA_DST
        stz FA_DST+1
        jsr far_get
        lda S2M_T
        rts
putset:
        sta S2M_T
        jsr setptr
        lda FA_SRC
        sta FA_DST
        lda FA_SRC+1
        sta FA_DST+1
        lda #<S2M_T
        sta FA_SRC
        stz FA_SRC+1
        jmp far_put
setptr:
        lda #S2STATE
        sta FA_BANK
        lda #1
        sta FA_N
        txa
        clc
        adc #<SS_SETTINGS
        sta FA_SRC
        lda #>SS_SETTINGS
        adc #0
        sta FA_SRC+1
        rts

; ---------------------------------------------------------------------------
; m_savedone: saveDone [R :1579-1589]: C clear, "game saved" and the menu
; closes; C set, the failed write's message (the slots as the disk has
; them are the second half's: G_SaveUndo, G_UpdateSaveGameStrings).
; ---------------------------------------------------------------------------
m_savedone:
        bcs :+
        ldx #<SM_ID_SAVED
        ldy #>SM_ID_SAVED
        jsr message
        jmp clearmenus
:       lda #MSG_SAVEFAIL
        jmp startmessage

; ---------------------------------------------------------------------------
; m_frame: a paused frame (docs/SCREENS.md); m_display: uiDisplay
; [R i_viigs65.s:2047-2055] without the tic commands (the second half's).
; ---------------------------------------------------------------------------
m_frame:
        lda SM_MENUACTIVE       ; (pl_poll's A: the menu's repeat while
        jsr pl_poll             ;   _g_menuactive, as upstream's repeat)
        jsr sc_update
        jsr fx_service
        jsr snd_refill
        lda M_SAVERES           ; SAVE SETTINGS's answer
        beq m_display
        jsr savedone
m_display:
        lda M_PALON
        beq @draw
        jsr mv_static
        bcc @draw
        rts
@draw:  lda M_MSGPRINT          ; M_Drawer: a message or a menu
        bne :+
        lda SM_MENUACTIVE
        beq @drawn
:       lda M_PALON
        bne :+
        jsr mv_open
:       jsr setchg              ; (SAVE SETTINGS's shade)
        jsr mv_full
@drawn: jsr mv_drawn
        jmp s2_finish

; savedone: dli_save's answer M_SAVERES taken, in the first frame after
; MENUW came back into W with the menu's palette on: the gray map, the
; menu palette's nibble table and the font's (mv_tables: W's, outside
; the state block) built again from the saved screen's palettes, the
; page drawn again (the item's shade); a failed write, M_SaveFailed's
; message
savedone:
        lda M_PALON
        beq :+
        jsr mv_tables
:       ldx M_SAVERES
        stz M_SAVERES
        jsr menuver
        cpx #RES_FAIL
        bne :+
        lda #MSG_SAVEFAIL
        jmp startmessage
:       rts

; setchg: G_SettingsChanged into M_SETCHG (0 the same, 1 changed): each
; byte collect (dl_init.s) writes from the game's places against SET_FILE's
setchg:
        lda #SET_BANK
        sta FA_BANK
        lda #<(SET_FILE + SETF_GAMMA)       ; the settings' bytes 12-20
        sta FA_SRC
        lda #>(SET_FILE + SETF_GAMMA)
        sta FA_SRC+1
        lda #<set_kn
        sta FA_DST
        lda #>set_kn
        sta FA_DST+1
        lda #SETF_DETAIL + 1 - SETF_GAMMA
        sta FA_N
        jsr far_get
        lda #<(SET_FILE + SETF_KEYS)        ; the keys
        sta FA_SRC
        lda #>(SET_FILE + SETF_KEYS)
        sta FA_SRC+1
        lda #<set_kk
        sta FA_DST
        lda #>set_kk
        sta FA_DST+1
        lda #128
        sta FA_N
        jsr far_get
        ldx #0
        jsr setptr              ; SS_SETTINGS' bytes
        lda #SET_N
        sta FA_N
        lda #<set_ss
        sta FA_DST
        lda #>set_ss
        sta FA_DST+1
        jsr far_get
        lda SM_GAMMA
        cmp set_kn + SETF_GAMMA - SETF_GAMMA
        bne @diff
        lda SM_SHOWMSG
        cmp set_kn + SETF_MESSAGES - SETF_GAMMA
        bne @diff
        lda SND_SFXVOL
        cmp set_kn + SETF_SFXVOL - SETF_GAMMA
        bne @diff
        ldx #SET_N - 1
@ss:    ldy ss_at,x
        lda set_ss,x
        cmp set_kn,y
        bne @diff
        dex
        bpl @ss
        ldx #127
@key:   lda PL_KEYTAB,x
        cmp set_kk,x
        bne @diff
        dex
        bpl @key
        lda #0
        bra @set
@diff:  lda #1
@set:   sta M_SETCHG
        rts

; ---------------------------------------------------------------------------
; m_page: M_Drawer [R m_menu65.s:1086-1128] into the band.
; ---------------------------------------------------------------------------
m_page:
        lda M_MSGPRINT
        beq @menu
        lda M_MSGKIND           ; uiMessage [R :3007-3011]
        cmp #MSG_BENCH
        bne :+
        jmp m2_bench
:       jmp drawmsg
@menu:  lda SM_MENUACTIVE
        bne :+
        rts
:       jsr page                ; menuDraw
        stx S2M_MENU
        cpx #0
        bne @new
        lda #2                  ; drawMain: M_DOOM
        ldy #P_M_DOOM
        jsr center
        bra @items
@new:   cpx #1
        bne @other
        lda #14                 ; drawNewGame: M_NEWG, M_SKILL
        ldy #P_M_NEWG
        jsr center
        lda #38
        ldy #P_M_SKILL
        jsr center
        bra @items
@other: cpx #2                  ; the load, save and key setup pages:
        beq @m2                 ;   s2menu2's
        cpx #4
        beq @m2
        cpx #5
        bne @items
@m2:    txa
        jsr m2_page
@items: ldx S2M_MENU            ; the items' patches
        lda t_x,x
        sta S2M_X
        stz S2M_X+1
        lda t_y,x
        sta S2M_Y
        stz S2M_Y+1
        jsr menunum
        sta S2M_LEFT
        lda t_items,x
        sta S2M_ITEM
@item:  ldx S2M_ITEM
        jsr itemlump
        bmi :+
        jsr dpatch
:       ldx S2M_MENU
        lda S2M_Y
        clc
        adc t_line,x
        sta S2M_Y
        bcc :+
        inc S2M_Y+1
:       inc S2M_ITEM
        dec S2M_LEFT
        bne @item
        jmp settings

; menunum: A = the page X's menuNum (the main menu's: uiMain's M_MAINN).
; Keeps X.
menunum:
        lda t_num,x
        cpx #0
        bne :+
        lda M_MAINN
:       rts

; itemlump: A = the item X's patch, N set for none [R :3087-3094]
itemlump:
        cpx #4
        bne :+
        ldy M_MAINN             ; uiMain's row 4
        lda #P_M_ENDGAM
        cpy #6
        beq @done
        lda #P_M_QUITG
        rts
:       cpx #11
        bcs @none
        lda t_lump,x
@done:  rts
@none:  lda #$FF
        rts

; center: the patch Y centred at x 160 - width / 2, y A [R :1248-1258]
center:
        sta S2M_Y
        stz S2M_Y+1
        lda mp_w,y              ; (every width is below 256)
        lsr a
        eor #$FF                ; 160 - w / 2
        sec
        adc #160
        sta S2M_X
        lda #0
        sbc #0
        sta S2M_X+1
        tya
        ; (on to dpatch)

; dpatch: V_DrawNumPatchNotScaled of the patch A at S2M_X, S2M_Y [R
; :1191-1198]: drawn into the band when its rows meet the band's
m_dpatch:
dpatch:
        tax
        lda mp_top,x
        ldy mp_h,x
        jsr vis
        bcc @skip
        lda mp_bank,x
        sta S2_PBANK
        lda mp_lo,x
        sta S2_PADDR
        lda mp_hi,x
        sta S2_PADDR+1
        lda S2M_X
        sta S2_X
        lda S2M_X+1
        sta S2_X+1
        lda S2M_Y
        sta S2_Y
        lda S2M_Y+1
        sta S2_Y+1
        jmp s2_vpatch
@skip:  rts

; dglyph: the glyph A of the font at S2M_X, S2M_Y (V_DrawPatchNotScaled
; of a character [R :1540-1548])
dglyph:
        tax
        lda mf_top,x
        ldy mf_h,x
        jsr vis
        bcc @skip
        lda mf_bank,x
        sta S2_PBANK
        lda mf_lo,x
        sta S2_PADDR
        lda mf_hi,x
        sta S2_PADDR+1
        lda S2M_X
        sta S2_X
        lda S2M_X+1
        sta S2_X+1
        lda S2M_Y
        sta S2_Y
        lda S2M_Y+1
        sta S2_Y+1
        jmp s2_vpatch
@skip:  rts

; vis: C set when the rows S2M_Y - top .. + height - 1 (A the top offset,
; a signed byte; Y the height) meet the band's S2_Y0 .. S2_Y1 - 1. Keeps X.
vis:
        sta S2M_T
        stz S2M_T+1
        cmp #$80
        bcc :+
        dec S2M_T+1
:       sec                     ; the first row (signed)
        lda S2M_Y
        sbc S2M_T
        sta S2M_T
        lda S2M_Y+1
        sbc S2M_T+1
        sta S2M_T+1
        bmi @bottom             ; above the screen: its bottom decides
        bne @no                 ; 256 and below: past the band
        lda S2M_T
        cmp S2_Y1
        bcs @no
@bottom:
        tya                     ; the row after its last > S2_Y0
        clc
        adc S2M_T
        sta S2M_T
        lda S2M_T+1
        adc #0
        bmi @no
        bne @yes
        lda S2M_T
        cmp S2_Y0
        beq @no
        bcc @no
@yes:   sec
        rts
@no:    clc
        rts

; ---------------------------------------------------------------------------
; M_DrawSkull, skullPlace, M_SkullRect [R :1134-1189]
; ---------------------------------------------------------------------------
m_drawskull:
        jsr skullplace
        lda M_WHICHSKULL
        clc
        adc #P_M_SKULL1
        jmp dpatch

; skullplace: S2M_X, S2M_Y the skull's place: x menuX - 32, y menuY +
; itemOn * menuLine - 5
skullplace:
        jsr page
        lda t_y,x
        sta S2M_Y
        stz S2M_Y+1
        ldy M_ITEMON
        beq @y
:       lda S2M_Y
        clc
        adc t_line,x
        sta S2M_Y
        bcc :+
        inc S2M_Y+1
:       dey
        bne :--
@y:     sec
        lda S2M_Y
        sbc #5
        sta S2M_Y
        bcs :+
        dec S2M_Y+1
:       sec
        lda t_x,x
        sbc #SKULLXOFF
        sta S2M_X
        lda #0
        sbc #0
        sta S2M_X+1
        rts

m_skullrect:
        lda M_MSGPRINT
        bne @none
        lda SM_MENUACTIVE
        beq @none
        jsr skullplace
        clc
        lda S2M_X
        adc #<SK_DX
        sta M_SKX
        lda S2M_X+1
        adc #>SK_DX
        sta M_SKX+1
        clc
        lda S2M_Y
        adc #SK_DY
        sta M_SKY
        lda #SK_W
        sta M_SKW
        lda #SK_H
        sta M_SKH
        sec
        rts
@none:  clc
        rts

; ---------------------------------------------------------------------------
; settings: uiSettings [R :2872-2999], the settings pages' frame (the
; options page here; the values past ON/OFF are m2_value's), then the
; skull.
; ---------------------------------------------------------------------------
settings:
        ldx S2M_MENU
        lda t_title,x
        bne :+
        jmp m_drawskull
:       tay                     ; the title, centred at y 20
        lda #20
        sta S2M_Y
        stz S2M_Y+1
        lda s_lo-1,y
        ldx s_hi-1,y
        ldy #0
        jsr align
        jsr shaded              ; the options page with the settings saved:
        bne :+                  ;   SAVE SETTINGS's box black
        jsr bmbox
:       ldx S2M_MENU
        lda t_items,x
        sta S2M_ITEM
        jsr menunum
        sta S2M_LEFT
        lda t_y,x
        sta S2M_UIY
        stz S2M_UIY+1
@row:   lda S2M_UIY
        sta S2M_Y
        lda S2M_UIY+1
        sta S2M_Y+1
        lda #60
        sta S2M_X
        stz S2M_X+1
        lda S2M_ITEM            ; SAVE SETTINGS dim while saved
        cmp #I_SAVESET
        bne :+
        lda M_SETCHG
        bne :+
        lda #1
        jsr mv_shade
:       ldx S2M_ITEM            ; the label
        ldy t_label,x
        beq @kind
        lda s_lo-1,y
        ldx s_hi-1,y
        jsr wstr
@kind:  ldx S2M_ITEM
        lda t_kind,x
        beq @next
        sta S2M_KIND
        cmp #OPT_VIEW
        bcs @m2
        jsr optvalue            ; ON or OFF at the right edge 284
        ldy #S_OFF
        cmp #0
        beq :+
        ldy #S_ON
:       lda s_lo-1,y
        ldx s_hi-1,y
        ldy #1
        jsr align
        bra @next
@m2:    ldx S2M_ITEM            ; the view and the thermometers: s2menu2's
        jsr m2_value
@next:  inc S2M_ITEM
        ldx S2M_MENU
        lda S2M_UIY
        clc
        adc t_line,x
        sta S2M_UIY
        bcc :+
        inc S2M_UIY+1
:       dec S2M_LEFT
        bne @row
        jsr shaded
        bne :+
        lda #0
        jsr mv_shade
:       jmp m_drawskull

; shaded: Z set on the options page while the settings are saved
; (G_SettingsChanged 0: M_SETCHG, the second half's)
shaded:
        lda S2M_MENU
        cmp #MENU_OPTIONS / 2
        bne :+
        lda M_SETCHG
:       rts

; optvalue: A = the ON/OFF value of the kind S2M_KIND [R :3107-3110]:
; showMessages (4), and SS_SETTINGS' alwaysRun (8), mouse (12), mouse
; move (16)
optvalue:
        lda S2M_KIND
        cmp #OPT_OFF
        bne :+
        lda SM_SHOWMSG
        ora SM_SHOWMSG+1
        rts
:       ldx #SET_ARUN
        cmp #8
        beq :+
        ldx #SET_MOUSE
        cmp #12
        beq :+
        ldx #SET_MMOVE
:       jmp getset

; bmbox: bmBox(0) [R :1670-1711]: SAVE SETTINGS's box black, marked
bmbox:
        lda #BOX_Y0
        sta S2M_R0
@row:   lda S2M_R0
        cmp S2_Y0
        bcc @next
        cmp S2_Y1
        bcs @next
        sec
        sbc S2_Y0
        jsr s2_mul160
        clc
        adc S2_BAND
        sta S2M_A
        txa
        adc S2_BAND+1
        sta S2M_A+1
        lda #0
        ldy #BOX_B0
:       sta (S2M_A),y
        iny
        cpy #BOX_B1 + 1
        bne :-
@next:  inc S2M_R0
        lda S2M_R0
        cmp #BOX_Y1
        bcc @row
        lda #BOX_B0
        sta S2_MB0
        lda #BOX_B1
        sta S2_MB1
        lda #BOX_Y0
        ldx #BOX_Y1
        jmp s2_mark

; ---------------------------------------------------------------------------
; Text [R :1454-1573, :1714-1755, :2846-2869]
; ---------------------------------------------------------------------------

; align: uiAlign: the string A (low), X (high) at y S2M_Y; Y = 0 centred
; at x 160, else its right edge at 284 (the two edges upstream uses)
m_align:
align:
        sta S2M_P
        stx S2M_P+1
        sty S2M_EDGE
        stz S2M_TP
        jsr lwidth
        lda S2M_EDGE
        bne @right
        lsr S2M_W+1
        ror S2M_W
        sec
        lda #160
        sbc S2M_W
        sta S2M_X
        lda #0
        sbc S2M_W+1
        sta S2M_X+1
        jmp wline
@right: sec
        lda #<284
        sbc S2M_W
        sta S2M_X
        lda #>284
        sbc S2M_W+1
        sta S2M_X+1
        jmp wline

; wstr: bmWrite: the whole string A (low), X (high) at S2M_X, S2M_Y; the
; characters off the font (a line break too) are spaces
m_wstr:
wstr:
        sta S2M_P
        stx S2M_P+1
        stz S2M_TP
@next:  ldy S2M_TP
        lda (S2M_P),y
        beq @done
        inc S2M_TP
        jsr glyph
        bra @next
@done:  rts

; wline: writeLine: from S2M_TP to a 0 or a line break, S2M_X moves on
m_wline:
wline:
        ldy S2M_TP
        lda (S2M_P),y
        beq @done
        cmp #10
        beq @done
        inc S2M_TP
        jsr glyph
        bra wline
@done:  rts

; glyph: the character A at S2M_X, S2M_Y, then S2M_X past it
glyph:
        jsr fontc
        bcc @space
        pha
        jsr dglyph
        plx
        lda mf_w,x
        bra @move
@space: lda #FONT_SPACE
@move:  clc
        adc S2M_X
        sta S2M_X
        bcc :+
        inc S2M_X+1
:       rts

; lwidth: lineWidth: S2M_W = the line's width from S2M_TP (to a 0 or a
; line break)
lwidth:
        stz S2M_W
        stz S2M_W+1
        ldy S2M_TP
@next:  lda (S2M_P),y
        beq @done
        cmp #10
        beq @done
        iny
        jsr fontc
        bcc @space
        tax
        lda mf_w,x
        bra @add
@space: lda #FONT_SPACE
@add:   clc
        adc S2M_W
        sta S2M_W
        bcc @next
        inc S2M_W+1
        bra @next
@done:  rts

; fontc: fontLump: C set and A the glyph (0 is '!') of the character A as
; upper case; C clear when it is not in the font. Keeps X, Y.
fontc:
        cmp #'a'
        bcc :+
        cmp #'z' + 1
        bcs :+
        sbc #'a' - 'A' - 1      ; (C clear)
:       cmp #'!'
        bcc @no
        cmp #'_' + 1
        bcs @no
        sbc #'!' - 1            ; (C clear: A - '!')
        sec
        rts
@no:    clc
        rts

; drawmsg: drawMessage [R :1456-1503]: each line centred at x 160, the
; block centred at y 100
drawmsg:
        lda M_MSGKIND
        lsr a
        lsr a
        tax
        lda msg_lo,x
        sta S2M_P
        lda msg_hi,x
        sta S2M_P+1
        lda #FONT_H             ; M_StringHeight
        sta S2M_N
        ldy #0
@count: lda (S2M_P),y
        beq @top
        cmp #10
        bne :+
        lda S2M_N
        clc
        adc #FONT_H
        sta S2M_N
:       iny
        bra @count
@top:   lda S2M_N               ; y = 100 - height / 2
        lsr a
        eor #$FF
        sec
        adc #100
        sta S2M_Y
        stz S2M_Y+1
        stz S2M_TP
@line:  ldy S2M_TP
        lda (S2M_P),y
        beq @done
        jsr lwidth              ; x = 160 - width / 2
        lsr S2M_W+1
        ror S2M_W
        sec
        lda #160
        sbc S2M_W
        sta S2M_X
        lda #0
        sbc S2M_W+1
        sta S2M_X+1
        jsr wline
        lda S2M_Y
        clc
        adc #FONT_H
        sta S2M_Y
        ldy S2M_TP              ; after a line break the next line
        lda (S2M_P),y
        beq @done
        inc S2M_TP
        bra @line
@done:  rts

.ifdef S2M_SNDLOG
; m_sndlog (-D S2M_SNDLOG only): the sound A appended to the log at S2M_SNDBUF
; (a count, then the sounds); keeps nothing
        .import s2m_sndbuf
m_sndlog:
        ldx s2m_sndbuf
        cpx #63
        bcs :+
        sta s2m_sndbuf+1,x
        inc s2m_sndbuf
:       rts
.endif

        .segment "S2RODATA"

; the pages' tables by page (currentMenu / 2) [R :3070-3083]
t_num:   .byte 6, 5, 8, 5, 11, 8, 4, 2, 5
t_items: .byte 0, 6, 11, 19, 25, 36, 44, 46, 48
t_x:     .byte 97, 48, 112, 60, 48, 112, 60, 60, 60
t_y:     .byte 64, 63, 25, 48, 24, 25, 56, 48, 48
t_line:  .byte 16, 16, 13, 18, 16, 13, 24, 28, 20
t_prev:  .byte $FF, MENU_MAIN, MENU_MAIN, MENU_MAIN, MENU_INPUT
         .byte MENU_MAIN, MENU_OPTIONS, MENU_OPTIONS, MENU_OPTIONS
t_previ: .byte 0, 0, 2, 1, 4, 3, 1, 1, 2
t_title: .byte 0, 0, 0, S_OPTIONS, 0, 0, S_VIDEO, S_SOUND, S_INPUT
; the items' patches 0-10 (row 4 is uiMain's) [R :3087-3088]
t_lump:  .byte P_M_NGAME, P_M_OPTION, P_M_LOADG, P_M_SAVEG, P_M_QUITG
         .byte P_M_QUITG, P_M_JKILL, P_M_ROUGH, P_M_HURT, P_M_ULTRA
         .byte P_M_NMARE
; the items' routines [R :519-572]
t_routine:
        .addr r_newgame, r_options, r_loadgame, r_savegame, r_main4, r_quit
        .addr r_skill, r_skill, r_skill, r_skill, r_skill
        .addr r_loadsel, r_loadsel, r_loadsel, r_loadsel, r_loadsel
        .addr r_loadsel, r_loadsel, r_loadsel
        .addr r_messages, r_video, r_input, r_vwitem, r_vwitem, r_sound
        .addr r_bind, r_bind, r_bind, r_bind, r_bind
        .addr r_bind, r_bind, r_bind, r_bind, r_bind, r_defkeys
        .addr r_savesel, r_savesel, r_savesel, r_savesel, r_savesel
        .addr r_savesel, r_savesel, r_savesel
        .addr r_viewsize, r_gamma, r_sfxvol, r_musvol, r_arun, r_mouse
        .addr r_mspeed, r_mmove, r_controls
T_ITEMS = (* - t_routine) / 2
        .assert T_ITEMS = 53, error, "53 items"
; the items' labels and kinds (uiSettings') [R :3097-3106]
t_label: .res 19, 0
         .byte S_MESSAGES, S_VIDEO, S_INPUT, S_BENCH, S_SAVESET, S_SOUND
         .res 19, 0
         .byte S_VIEW, S_GAMMA, S_SFX, S_MUSIC, S_RUN, S_MOUSE, S_SPEED
         .byte S_MOVE, S_KEYS
t_kind:  .res 19, 0
         .byte 4
         .res 24, 0
         .byte 20, 28, 36, 40, 8, 12, 32, 16, 0
        .assert * - t_kind = 53, error, "53 kinds"
; the key setup's Doom keys [R :232-233]
ctl_keys: .byte 2, 1, 5, 6, 7, 8, 3, 4, 15, 0

; the strings, numbered from 1
s_lo:   .lobytes str_options, str_messages, str_video, str_sound, str_input
        .lobytes str_bench, str_saveset, str_view, str_gamma, str_sfx
        .lobytes str_music, str_run, str_mouse, str_speed, str_move, str_keys
        .lobytes str_off, str_on
s_hi:   .hibytes str_options, str_messages, str_video, str_sound, str_input
        .hibytes str_bench, str_saveset, str_view, str_gamma, str_sfx
        .hibytes str_music, str_run, str_mouse, str_speed, str_move, str_keys
        .hibytes str_off, str_on
S_OPTIONS = 1
S_MESSAGES = 2
S_VIDEO = 3
S_SOUND = 4
S_INPUT = 5
S_BENCH = 6
S_SAVESET = 7
S_VIEW  = 8
S_GAMMA = 9
S_SFX   = 10
S_MUSIC = 11
S_RUN   = 12
S_MOUSE = 13
S_SPEED = 14
S_MOVE  = 15
S_KEYS  = 16
S_OFF   = 17
S_ON    = 18
; [R :3000-3001, :3111-3124, :1650-1651]
str_options:  .asciiz "OPTIONS"
str_messages: .asciiz "MESSAGES"
str_video:    .asciiz "DISPLAY & SOUND"
str_sound:    .asciiz "SOUND"
str_input:    .asciiz "CONTROLS"
str_bench:    .asciiz "BENCHMARK"
str_saveset:  .asciiz "SAVE SETTINGS"
str_view:     .asciiz "VIEW"
str_gamma:    .asciiz "GAMMA"
str_sfx:      .asciiz "SFX VOLUME"
str_music:    .asciiz "MUSIC VOLUME"
str_run:      .asciiz "ALWAYS RUN"
str_mouse:    .asciiz "MOUSE"
str_speed:    .asciiz "MOUSE SPEED"
str_move:     .asciiz "MOUSE MOVE"
str_keys:     .asciiz "KEY SETUP"
str_off:      .asciiz "OFF"
str_on:       .asciiz "ON"

; the messages by messageKind / 4 (MSG_BENCH's is m2_bench's) [R :214-224,
; :511-513, :1648-1649]
msg_lo: .lobytes msg_nightmare, msg_quit, msg_endgame, msg_savedead
        .lobytes msg_savedead, msg_savefail
msg_hi: .hibytes msg_nightmare, msg_quit, msg_endgame, msg_savedead
        .hibytes msg_savedead, msg_savefail
msg_nightmare:
        .byte "Are you sure? This skill level", 10
        .byte "isn't even remotely fair.", 10, 10
        .asciiz "Press Y or N."
msg_quit:
        .byte "Are you sure you want to", 10
        .byte "quit this great game?", 10, 10
        .asciiz "Press Y or N."
msg_endgame:
        .byte "Are you sure you want to", 10
        .byte "end the game?", 10, 10
        .asciiz "Press Y or N."
msg_savedead:
        .byte "You can't save if you aren't playing!", 10, 10
        .asciiz "Press a key."
msg_savefail:
        .byte "Not saved: the disk is write", 10
        .byte "protected or cannot be written.", 10, 10
        .asciiz "Press a key."

; the patches and the font (tools/native/s2menu1.py)
        S2M_PATCHES
        S2M_FONT

; setchg's places: where each SS_SETTINGS byte (SET_ARUN .. SET_MUSVOL:
; always run, detail, mouse, mouse speed, mouse move, music volume) is in
; the file's bytes from SETF_GAMMA
ss_at:  .byte SETF_RUN - SETF_GAMMA, SETF_DETAIL - SETF_GAMMA
        .byte SETF_MOUSE - SETF_GAMMA, SETF_MSPEED - SETF_GAMMA
        .byte SETF_MMOVE - SETF_GAMMA, SETF_MUSICVOL - SETF_GAMMA
        .assert * - ss_at = SET_N, error, "ss_at"
        .assert SET_ARUN = 0 && SET_MOUSE = 2 && SET_MSPEED = 3 && SET_MMOVE = 4 && SET_MUSVOL = 5, error, "SS_SETTINGS' bytes"

        .segment "S2DATA"
set_kn: .res SETF_DETAIL + 1 - SETF_GAMMA       ; SET_FILE's bytes 12-20,
set_kk: .res 128                                ;   its keys,
set_ss: .res SET_N                              ;   SS_SETTINGS' bytes
