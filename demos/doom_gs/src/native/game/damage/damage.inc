; game/damage/damage.inc: part damage's places (milestone 10, docs/GAME.md
; 2.4, 4.4; docs/game-parts/damage.md). GPL-2, the port's own.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_6
; (GT_7 on is the object API's), its arguments GA_*. What its routines
; keep across a call is in the scratch block SB_DAMAGE (32 bytes):
; upstream's DM_* of p_inter65.s, a mobj as its handle. setState keeps
; the target, the source and the type on the stack around
; P_SetMobjState, as upstream's setState does (a state's action may run
; game logic that damages again); P_DamageMobj keeps its justhit there.
;
; Conventions of the part's entries (each routine's comment has the rest):
;   - a mobj is its handle (a slot; $FFFF none)
;   - P_DamageMobj: GA_0-1 the target, GA_2-3 the inflictor, GA_4-5 the
;     source, GA_6-7 the damage (upstream's _Dp[0-3], _Dp[4-7], 4,s and C)
;   - wInfoOf: A = a weapon; wInfo: the ready weapon's; both give X (and
;     A) = the offset of the weapon's record in weaponinfo (12 a weapon:
;     upstream's X, the record's near address)
;   - P_DropWeapon, lowerWeapon: the player's (there is one)

DM      = SB_DAMAGE
        .assert SB_DAMAGE_SIZE >= 32, error, "damage's scratch block"
DM_TGT  = DM + 0                ; (2) the target (upstream's DM_TARGET)
DM_INF  = DM + 2                ; (2) the inflictor ($FFFF none)
DM_SRC  = DM + 4                ; (2) the source ($FFFF none)
DM_DMG  = DM + 6                ; (2) the damage
        .assert DM_INF = DM_TGT + 2 && DM_SRC = DM_TGT + 4 && DM_DMG = DM_TGT + 6, error, "GA_0-7's order"
DM_PLY  = DM + 8                ; (1) 1: the target is the player's mobj
DM_TYPE = DM + 9                ; (1) the target's type (DM_INFO: its
                                ;   mobjinfo record through mi_get)
DM_ANG  = DM + 10               ; (4) the thrust's angle
DM_THR  = DM + 14               ; (4) the thrust
DM_T    = DM + 18               ; (4) a temporary (dz; -spawnhealth)
DM_FA   = DM + 22               ; (2) the fine angle of DM_ANG
DM_K    = DM + 24               ; (1) killMobj's type
        .assert DM_K + 1 <= DM + 32, error, "damage's scratch block"

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
LN_A    = MO_SIZE
LN_B    = 2 * MO_SIZE
LN_C    = 3 * MO_SIZE
D_RTH   = 1
D_A     = 2
D_B     = 4
D_C     = 8

; weaponinfo's records (upstream's weaponinfo_t: 6 words a weapon,
; offsets.inc OFS_WI_*)
WI_AMMO  = 0
WI_UP    = 2
WI_DOWN  = 4
WI_READY = 6
WI_ATK   = 8
WI_FLASH = 10
WI_SIZE  = 12

; the flags' bytes this part changes (mobj_t flags: 4 bytes, MB_FLAGS)
        .assert >UC_MF_SHOOTABLE_LO = 0 && >UC_MF_SOLID_LO = 0 && >UC_MF_JUSTHIT_LO = 0, error, "flags' byte 0"
        .assert <UC_MF_NOGRAVITY_LO = 0 && <UC_MF_DROPOFF_LO = 0 && <UC_MF_NOCLIP_LO = 0, error, "flags' byte 1"
        .assert >UC_MF_CORPSE_HI = 0 && >UC_MF_COUNTKILL_HI = 0 && >UC_MF_DROPPED_HI = 0, error, "flags' byte 2"
        .assert UC_SK_BABY = 0 && UC_PW_INVULNERABILITY = 0, error, "baby, invulnerability"
        .assert >UC_CF_GODMODE = 0 && >UC_CF_ENEMY_ROCKETS = 0, error, "the cheats' low byte"
