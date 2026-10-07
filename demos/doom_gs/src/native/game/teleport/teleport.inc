; game/teleport/teleport.inc: part teleport's places (docs/GAME.md). GPL-2,
; the port's own.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_6
; (GT_7 on is the object API's) and the math block, its arguments GA_*.
; What its routines keep across a call is in the scratch block SB_TELEPORT
; (32 bytes, 27 used): upstream's TP_* of p_telept65.s and MP_TP*,
; MP_TELEFRAG of p_map65.s. P_TeleportMove keeps its block loop on the
; stack (5 bytes), as upstream does: stompThing's P_DamageMobj runs game
; logic.

TP      = SB_TELEPORT
        .assert SB_TELEPORT_SIZE >= 32, error, "teleport's scratch block"
; EV_Teleport, live across P_TeleportMove
TP_THING = TP + 0               ; (2) the thing                  TP_THING
TP_DEST = TP + 2                ; (2) the destination            TP_M
TP_OX   = TP + 4                ; (4) the old position           TP_OX
TP_OY   = TP + 8                ; (4)                            TP_OY
TP_OZ   = TP + 12               ; (4)                            TP_OZ
; P_TeleportMove (and stompThing under it)
TP_TPX  = TP + 16               ; (4) x                          MP_TPX
TP_TPY  = TP + 20               ; (4) y                          MP_TPY
TP_TF   = TP + 24               ; (1) telefrag (0: no)           MP_TELEFRAG
; (TP + 25 .. 27 free)
TP_TPT  = TP + 28               ; (2) the thing                  MP_TPT
        .assert TP_TPT + 2 <= TP + 32, error, "teleport's scratch block"
; EV_Teleport before P_TeleportMove (destination), over TP_TPX..
TP_LINE = TP + 16               ; (2) the line                   TP_LINE
TP_SEC  = TP + 18               ; (1) the tagged sector          TP_I
TP_TH   = TP + 19               ; (2) the thinker                (_Dp)
TP_NX   = TP + 21               ; (2) its next
; EV_Teleport after P_TeleportMove, over TP_TPX..
TP_AN   = TP + 16               ; (2) the destination's fine angle
        .assert TP_NX + 2 <= TP_TF, error, "destination's bytes"

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
LN_A    = MO_SIZE
LN_B    = 2 * MO_SIZE
LN_C    = 3 * MO_SIZE
D_RTH   = 1
D_A     = 2
D_B     = 4
D_C     = 8

        .assert TH_X = 0 && TH_Y = 4 && TH_Z = 8, error, "RTHING's x, y, z first"
        .assert GM_TMY = GM_TMX + 4, error, "tmx, tmy"
        .assert GM_TMCEILZ = GM_TMFLOORZ + 4 && GM_TMDROPZ = GM_TMFLOORZ + 8, error, "tmfloorz .."
        .assert MB_CEILZ = MB_FLOORZ + 4 && MB_DROPZ = MB_FLOORZ + 8, error, "floorz .."
        .assert MC_MOMY = MC_MOMX + 4 && MC_MOMZ = MC_MOMX + 8, error, "the momentum"
        .assert PL_MOMY = PL_MOMX + 4, error, "the player's momentum"
        .assert GA_Y = GA_X + 4 && GA_Z = GA_X + 8, error, "P_SpawnMobj's place"
; the flags' bytes this part reads (mobj_t flags: 4 bytes)
        .assert >UC_MF_SHOOTABLE_LO = 0 && UC_MF_SHOOTABLE_HI = 0, error, "flags' byte 0"
        .assert UC_MF_MISSILE_LO = 0 && >UC_MF_MISSILE_HI = 0, error, "flags' byte 2"
