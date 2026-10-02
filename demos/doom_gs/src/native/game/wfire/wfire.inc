; game/wfire/wfire.inc: part wfire's places (milestone 10, docs/GAME.md 2.4
; row wfire, 4.4; docs/game-parts/wfire.md). GPL-2, the port's own.
; Included after ggame.inc.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_6 (GT_7
; on is the object API's) and the math block (M_A, M_B, M_R), its
; arguments GA_*. What a routine keeps across a call is in the scratch
; block SB_WFIRE (32 bytes, ggame.inc): upstream's near scratch of
; p_pspr65.s (WP_SLOPE, WP_ANGLE, WP_T, WP_DAMAGE, WP_I) and of
; p_spawn65.s (SP_SRC, SP_AN, SP_SLOPE, SP_TH) that P_SpawnPlayerMissile
; uses. No routine of the part can be entered again while it is active
; (an action's own calls reach no weapon action: P_SetMobjState of the
; player's S_PLAY_ATK2 runs none, the flash's actions are A_Light*), so
; the block needs no stack.
;
; Conventions of the part's entries (each routine's comment has the rest):
;   - a mobj is its handle ($FFFF none); linetarget is the shared
;     GM_LINETARGET (part attack's P_AimLineAttack writes it)
;   - an angle, a slope, a fixed_t: 4 bytes, little-endian, as upstream's
;   - a weapon action takes its psprite in GS_PSP (0 the weapon, 1 the
;     flash: milestone 9's gw_setpsprite)

WF      = SB_WFIRE
        .assert SB_WFIRE_SIZE >= 32, error, "wfire's scratch block"
WF_SLOPE = WF + 0               ; (4) bulletslope (WP_SLOPE)
WF_ANGLE = WF + 4               ; (4) the shot's or the melee's angle
                                ;   (WP_ANGLE)
WF_T    = WF + 8                ; (4) A_Saw's d = angle - mo->angle (WP_T)
WF_DMG  = WF + 12               ; (2) the damage (WP_DAMAGE)
WF_I    = WF + 14               ; (1) the shotgun's pellets left (WP_I)
WF_K    = WF + 15               ; (1) the aim's try: 0 straight, 1 left,
                                ;   2 right (bulletSlope, P_SpawnPlayer-
                                ;   Missile)
WF_PSP  = WF + 16               ; (1) A_FireCGun's psprite (upstream's
                                ;   pei of _Dp[4])
WF_ACC  = WF + 17               ; (1) gunShot's accurate (upstream's pha)
WF_RNG  = WF + 18               ; (1) meleeAttack's range's low byte
                                ;   (upstream's pha: MELEERANGE + it)
WF_SRC  = WF + 19               ; (2) P_SpawnPlayerMissile: the source
                                ;   (SP_SRC)
WF_AN   = WF + 21               ; (4)   the angle (SP_AN)
WF_SLP  = WF + 25               ; (4)   the slope (SP_SLOPE)
WF_TH   = WF + 29               ; (2)   the missile (SP_TH)
WF_NEED = 31
        .assert WF_NEED <= SB_WFIRE_SIZE, error, "wfire's scratch block"

; the player (llayout.player_layout: upstream's player_t)
PLR     = G_PLAYER
PSP_SIZE = PL_PSPRITES_1_STATE - PL_PSPRITES_0_STATE
        .assert PSP_SIZE = 10, error, "a psprite: state, tics, sx, sy"
PSTATE  = PLR + PL_PSPRITES_0_STATE     ; psprite k's state at + 10 k
STRENGTH = PLR + PL_POWERS_0 + 2 * UC_PW_STRENGTH       ; powers[pw_strength]
        .assert PL_POWERS_1 - PL_POWERS_0 = 2, error, "powers: words"

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
LN_A    = MO_SIZE
LN_B    = 2 * MO_SIZE
LN_C    = 3 * MO_SIZE
D_RTH   = 1
D_B     = 4
D_C     = 8

; the ranges (fixed_t: the high words) and the aim's distance
WF_MISSILE_HI = UC_MISSILERANGE_HI      ; MISSILERANGE (2048 FRACUNIT)
WF_MELEE_HI   = UC_MELEERANGE_HI        ; MELEERANGE (64 FRACUNIT)
WF_AIM_HI     = 16 * 64                 ; 16 * 64 * FRACUNIT (the aims)

; A_Saw's turn (p_pspr65.s:27-29): ANG90 / 20, ANG90 / 21, and the
; addends of its four results
WF_ANG90_20  = $03333333
WF_NANG90_20 = $FCCCCCCD        ; -ANG90 / 20
WF_ANG90_21  = $030C30C3
WF_NANG90_21 = $FCF3CF3D        ; -ANG90 / 21
WF_ANG180    = $80000000

; the layouts this code relies on
        .assert TH_X = 0 && TH_Y = 4, error, "RTHING's x, y first"
        .assert M_B = M_A + 4, error, "M_A, M_B"
        .assert >UC_S_CHAIN1 = 0, error, "S_CHAIN1 below 256"
        .assert UC_MF_JUSTATTACKED_HI = 0 && UC_MF_JUSTATTACKED_LO < 256, error, "MF_JUSTATTACKED in the flags' byte 0"
        .assert UO_WI_AMMO = 0, error, "weaponinfo's ammo first"
