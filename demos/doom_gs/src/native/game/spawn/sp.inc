; game/spawn/sp.inc: part spawn's places (milestone 10, docs/GAME.md 2.4,
; 4.4; docs/game-parts/spawn.md). GPL-2, the port's own.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_6 (GT_7
; on is the object API's) and, inside a routine between its calls of other
; parts, the argument bytes GA_* it has read; its arguments GA_*. What a
; routine keeps across a call is in the scratch block SB_SPAWN (32 bytes).
; P_ZMovement's bytes and the spawners' never share: an explosion's death
; state could, in principle, reach a spawner while P_ZMovement is active.
;
; Conventions of the part's entries (each routine's own comment has the
; rest):
;   - a mobj is its slot (llayout: $FFFF none); a routine of upstream's
;     _Dp[0-3] or AP takes it in A:X
;   - a 32-bit value is little-endian, as upstream's
;   - a spawn's x, y, z are in GA_X, GA_Y, GA_Z (P_SpawnMobj's own
;     arguments); P_SpawnBlood's damage in GA_DMG

SP      = SB_SPAWN
        .assert SB_SPAWN_SIZE >= 32, error, "spawn's scratch block"
; the spawners (P_SpawnPuff, P_SpawnBlood and their helpers)
SP_X    = SP + 0                ; (4) saveXYZ's x, y, z (upstream's SP_X,
SP_Y    = SP + 4                ; (4)   SP_Y, SP_Z)
SP_Z    = SP + 8                ; (4)
SP_TH   = SP + 12               ; (2) the spawned mobj (upstream's SP_TH)
SP_DMG  = SP + 14               ; (2) P_SpawnBlood's damage (SP_DAMAGE)
; P_ZMovement
ZM_MO   = SP + 16               ; (2) its mobj
ZM_PL   = SP + 18               ; (1) 1: the player's (upstream's MV_PL)
; the attack's range, attackrange (upstream's p_attack65.s AT_RANGE: part
; attack's, wave 5, which sets it in P_LineAttack and P_AimLineAttack):
; GM_ATRANGE in GW (glayout.TIC_GW_FIELDS, never overlaid; request 1,
; wave 2 as integrated)
AT_RANGE = GM_ATRANGE
        .assert ZM_PL + 1 <= SP + 28, error, "spawn's scratch block"

GA_DMG  = GA_12                 ; (2) P_SpawnBlood's damage (upstream's 4,s)

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
LN_A    = MO_SIZE
LN_B    = 2 * MO_SIZE
LN_C    = 3 * MO_SIZE
D_RTH   = 1
D_A     = 2
D_B     = 4
D_C     = 8

; GRAVITY = FRACUNIT (upstream's p_mobj65.s:29 GRAVITY_HI, the high word)
GRAVITY_HI = 1

        .assert >UC_MF_NOGRAVITY_LO <> 0 && <UC_MF_NOGRAVITY_LO = 0, error,  "MF_NOGRAVITY's byte (1)"
        .assert >UC_MF_NOCLIP_LO <> 0 && <UC_MF_NOCLIP_LO = 0, error,  "MF_NOCLIP's byte (1)"
        .assert >UC_MF_MISSILE_HI = 0 && <UC_MF_MISSILE_HI <> 0, error,  "MF_MISSILE's byte (2)"
        .assert UC_MELEERANGE_LO = 0 && >UC_MELEERANGE_HI = 0, error, "MELEERANGE's bytes"
        .assert UC_VIEWHEIGHT_LO = 0 && >UC_VIEWHEIGHT_HI = 0, error, "VIEWHEIGHT's bytes"
