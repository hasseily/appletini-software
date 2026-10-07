; game/pickup/pk.inc: part pickup's places and conventions (docs/GAME.md).
; GPL-2, the port's own.
;
; The part has no zero page of its own: it keeps what it needs across a
; call in its scratch block SB_PICKUP (32 bytes), and uses GT_0-GT_6 only
; between two calls (GT_7 on is the object API's). The calls out of the
; part: the object API (mo_get, mo_dirty), P_RemoveMobj (mobjstate),
; G_ExitLevel (flow), umul16lo (the math), the S_StartSound and I_Error
; hooks; none of them reaches back into the part, so the block's bytes
; are the part's for the whole of each entry's call.
;
; The entries:
;   P_TouchSpecialThing  GA_0-1 = the special thing (a mobj slot), GA_2-3
;                the toucher (the player's mobj); nothing back
;   P_GivePower  A = a power: A = 1 (C set) given, 0 (C clear) not
;   C_Responder  A = a cheat's event number (m_cheat65.s's table order:
;                see cheat.s): its effect; A = 1, or 0 for a number past
;                the table. Matching typed keys to the sequences is
;                dl_brain.s's
;   power        A = a power: P_GivePower's, the result dropped
;   m_cheat_giveAmmo  idfa's and idkfa's backpack, armour, weapons, ammo
; and the helpers, each with its arguments in registers or the block:
;   giveBody     A:X = the health to add: C set when taken
;   p_inter_giveAmmo  A = an ammo type, X = the clips (0: half a clip):
;                C set when taken
;   giveWeapon   A = a weapon, X = 0 placed, else dropped: C set when the
;                weapon or its ammo was taken
;   givePower    A = a power: C set when given
;   pkArmor ... pkWeapon  pickTab's cases: PK_ARG the entry's argument,
;                PK_SPEC the thing, PK_SND and PK_MSG to change: C set
;                when the player takes the thing

PK      = SB_PICKUP
        .assert SB_PICKUP_SIZE >= 32, error, "pickup's scratch block"
PK_SPEC = PK + 0                ; (2) the special thing
PK_TCH  = PK + 2                ; (2) the toucher
PK_SND  = PK + 4                ; (1) the pickup sound
PK_MSG  = PK + 5                ; (2) the message's symbol, $FFFF none
PK_ARG  = PK + 7                ; (2) pickTab's argument of the thing
PK_I    = PK + 9                ; (1) pkBackpack's ammo type
PK_WPN  = PK + 10               ; (1) giveWeapon's weapon
PK_DROP = PK + 11               ; (1) giveWeapon's "dropped"
PK_GAVE = PK + 12               ; (1) giveWeapon's "gave ammo"
PK_AMMO = PK + 13               ; (1) giveAmmo's ammo type, times 2
PK_NUM  = PK + 14               ; (1) giveAmmo's clips
PK_OLD  = PK + 15               ; (2) giveAmmo's ammo before
PK_PWR  = PK + 17               ; (1) givePower's power
PK_V    = PK + 18               ; (2) a health or a count to store
PK_CH   = PK + 20               ; (1) C_Responder's cheat
        .assert PK_CH + 1 <= PK + 32, error, "pickup's scratch block"

NO_MSG  = $FF                   ; PK_MSG's high byte: no message

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
LN_A    = MO_SIZE
LN_B    = 2 * MO_SIZE
D_RTH   = 1
D_A     = 2
D_B     = 4

; the S_StartSound hook's sound byte with upstream's PICKUP_SOUND (bit 15
; of its word) as bit 7
PICKUP_SOUND = $80

PLR     = G_PLAYER

        .assert >UC_MF_COUNTITEM_HI = 0 && >UC_MF_DROPPED_HI = 0 && >UC_MF_SHADOW_HI = 0, error, "the flags' byte 2"
        .assert >UC_CF_GODMODE = 0 && >UC_CF_NOCLIP = 0 && >UC_CF_ENEMY_ROCKETS = 0, error, "the cheats' low byte"
        .assert UC_SFX_GETPOW < $80 && UC_SFX_ITEMUP < $80 && UC_SFX_WPNUP < $80, error, "a sound with bit 7"
