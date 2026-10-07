; dl.inc: the playable game's glue in the tic image (docs/PLAY.md):
; its groups' numbers, after glayout's GROUPS (gplace.inc), and the call
; between them. GPL-2, the port's own.
;
; The glue's code is in four groups of its own (the tic image's core is
; full): the brain DLG_BRAIN, the tic command and the frame's list DLG_CMD,
; the hooks' bodies DLG_HOOK, the status bar's ticker and the songs DLG_SND
; (play.inc: DLG_B .. DLG_S, their offsets and slots). A call to another
; group goes through gcall.s's fc_call (the target's slot's group saved and
; restored, 5 bytes of stack), as FCALL does for the game's routines.

DLG_BRAIN = GROUPS + DLG_B
DLG_CMD   = GROUPS + DLG_C
DLG_DISP  = GROUPS + DLG_D
DLG_HOOK  = GROUPS + DLG_H
DLG_SND   = GROUPS + DLG_S

; DLCALL group, target: jsr when the target is in the caller's group
; (FC_HERE), else through fc_call
.macro DLCALL grp, target
  .if (grp) = FC_HERE
        jsr target
  .else
        jsr fc_call
        .byte grp
        .word target
  .endif
.endmacro

; GTICKER: G_Ticker (part tic's); a play build without it is refused here
.macro GTICKER
  .if GP_G_Ticker_B
        FCALL G_Ticker
  .else
        .error "G_Ticker is not built: a play build needs part tic"
  .endif
.endmacro

; GTRESUME: after a load (E_RESUME), G_Ticker again at its action loop's
; test of gameaction (part tic's gt_loop, through G_Ticker's group, as its
; driver's g_tresume does), as upstream goes on after the action returns
.macro GTRESUME
  .if GP_G_Ticker_B
    .if GP_G_Ticker_G = 0
        jsr gt_loop
    .else
        jsr fc_call
        .byte GP_G_Ticker_G
        .word gt_loop
    .endif
  .else
        .error "G_Ticker is not built: a play build needs part tic"
  .endif
.endmacro

; The menu benchmark's bytes in DLM (DL_BENCH, DL_BVIEW, DL_BRT) are
; playlayout.py's DLM_FIELDS, in play.inc (docs/PLAY.md, the benchmark)
MSG_BENCH  = 16                 ; MENUW's messageKind of the result page
                                ;   (s2_menu.s MSG_BENCH)

; the upstream event types (keys.inc, g_game65.s)
EV_KEYDOWN = 0
EV_KEYUP   = 1
; upstream's Doom keys (keys.inc)
KEY_SPEED  = 0
KEY_USE    = 1
KEY_FIRE   = 2
KEY_STRAFELEFT = 3
KEY_STRAFERIGHT = 4
KEY_UP     = 5
KEY_DOWN   = 6
KEY_LEFT   = 7
KEY_RIGHT  = 8
KEY_ESCAPE = 9
KEY_MAP    = 10
KEY_ZOOMOUT = 11
KEY_ZOOMIN = 12
KEY_WEAPONDOWN = 13
KEY_WEAPONUP = 14
KEY_STRAFE = 15
KEY_WEAPON1 = 16
CH_FOLLOW  = 'f'                ; key_map_follow (a character)
; the automap's mode bits (am_map65.s; the frame block's AUTOMAP)
AM_ACTIVE  = 1
AM_OVERLAY = 2
AMAP_PAL   = 11                 ; i_viigs65.s AMAP_PAL (d_main65.s)
STRIP_ROWS = 10
AM_TITLEY  = VIEWHEIGHT - 1 - 7 ; CONST_VIEWHEIGHT - 1 - 7 (rlayout.inc)
