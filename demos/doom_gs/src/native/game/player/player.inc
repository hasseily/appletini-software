; game/player/player.inc: part player's places (milestone 10, docs/GAME.md
; 2.4, 4.4; docs/game-parts/player.md). GPL-2, the port's own.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_6 (GT_7
; on is the object API's and gcall.s's), its arguments GA_*. What its
; routines keep across a call is in the scratch block SB_PLAYER (32 bytes).
;
; Conventions of the part's entries (each routine's comment has the rest):
;   - one player: upstream's player_t* argument is always &_g_player, the
;     native's G_PLAYER (llayout.player_layout)
;   - a mobj is its handle ($FFFF none), a sector its number, a line its
;     number; an intercept its index in ICPT (TRVTAB's convention)
;   - a 32-bit result of the game's math is in M_R (math.inc)

PY      = SB_PLAYER
        .assert SB_PLAYER_SIZE >= 32, error, "player's scratch block"
PY_ONG  = G_ONGROUND            ; (1) onground (upstream's PU_ONGROUND):
                                ;   the persistent global of request R1
                                ;   (wave 5 as integrated: it lives from
                                ;   one tic to the next, movePlayer is
                                ;   skipped while reactiontime counts
                                ;   down); the block's byte 0 is free
PY_THING = PY + 1               ; (2) usething (the player's mobj)
PY_LINE = PY + 3                ; (2) the traverser's line (US_LINE); the
                                ;   use trace's fine angle before it
PY_X1   = PY + 5                ; (4) the use trace: x1, y1, x2, y2 in
PY_Y1   = PY + 9                ; (4)   P_PathTraverse's order (GA_0-15);
PY_X2   = PY + 13               ; (4)   the death think's angle to the
PY_Y2   = PY + 17               ; (4)   attacker in PY_X1
PY_BOB  = PY + 21               ; (4) calcHeight's bob (PU_BOB)
PY_T    = PY + 25               ; (4) the thrust's m (PU_T); the death
                                ;   think's delta
PY_ANG  = PY + 29               ; (2) the thrust's fine angle (PU_ANGLE)
        .assert PY_ANG + 2 <= PY + 32, error, "player's scratch block"

; the player (llayout.player_layout: upstream's player_t, the mobj
; references as handles)
PLR     = G_PLAYER

; a mobj cache line (LW_MOB's layout): RTHING, then groups A, B, C, and
; their dirty bits (mo_dirty)
PO_A    = MO_SIZE
PO_B    = 2 * MO_SIZE
PO_C    = 3 * MO_SIZE
D_TH    = 1
D_A     = 2
D_B     = 4
D_C     = 8

; a sector cache line: the render record, then the game record
SEC_G   = SEC_SIZE

; upstream's constants of p_user65.s (its .equ, p_user65.s:36-41)
MAXBOB_HI = $10                 ; MAXBOB = $100000
ANG5    = $038E38E3             ; ANG90 / 18
NANG5   = $FC71C71D             ; -ANG5
INVERSECOLORMAP = 32
VIEWHALF_LO = $8000             ; VIEWHEIGHT / 2 = 20.5 FRACUNIT
VIEWHALF_HI = 20

        .assert >UC_MF_NOCLIP_LO <> 0 && <UC_MF_NOCLIP_LO = 0, error, "noclip"
        .assert >UC_MF_JUSTATTACKED_LO = 0, error, "justattacked"
        .assert >UC_MF_SHADOW_HI = 0, error, "shadow"
        .assert UC_PST_LIVE = 0 && >UC_PST_DEAD = 0, error, "playerstate"
        .assert UC_VIEWHEIGHT_LO = 0 && >UC_VIEWHEIGHT_HI = 0, error, "vh"
        .assert PL_CMD_SIDEMOVE = PL_CMD_FORWARDMOVE + 1, error, "cmd"
        .assert TH_Y = TH_X + 4, error, "x, y"
