; game/trymove/trymove.inc: part trymove's places (docs/GAME.md). GPL-2,
; the port's own. Included after ggame.inc.
;
; The scratch block SB_TRYMOVE (32 B). P_TryMove's frame (upstream's TT,
; OX, OY, OS on the stack, p_map65.s:318-325) and the thing it moves;
; P_NightmareRespawn's NR_MO (p_spawn65.s:67) and the new mobj, in bytes of
; their own: P_NightmareRespawn's P_CheckPosition can run game logic (a
; check's PIT_CheckThing), and so could reach a P_TryMove by the dispatch
; tables, as P_TryMove's own check and its crossed lines could reach
; P_NightmareRespawn's callees; neither happens in a run (a corpse's check
; meets no missile and picks nothing up), but the bytes are apart anyway.
;
;   TM_SAVE  tmthing (2), tmx (4), tmy (4): P_TryMove's copy of
;            cpCopy's, taken back when PIT_CheckThing ran (G_MPCLOB), as
;            upstream takes them back from its frame (p_map65.s:340-352)
;   TM_OX, TM_OY  the thing's x, y before the move (only when numspechit
;            is not 0, as upstream)
;   TM_OS    the old side of the crossed line being tested
;   TM_LN    that line
;   TM_TH    the thing moved (upstream's TP, back from the frame after
;            P_CrossSpecialLine)
;   NR_MO    the dead monster (upstream's NR_MO)
;   NR_NEW   the respawned one (upstream's SP_TH after spawnXYZ)

TM              = SB_TRYMOVE
TM_SAVE         = TM + 0        ; 10
TM_OX           = TM + 10       ; 4
TM_OY           = TM + 14       ; 4
TM_OS           = TM + 18       ; 1
TM_LN           = TM + 19       ; 2
TM_TH           = TM + 21       ; 2
NR_MO           = TM + 23       ; 2
NR_NEW          = TM + 25       ; 2
TM_END          = TM + 27
        .assert TM_END <= SB_TRYMOVE + SB_TRYMOVE_SIZE, error, "trymove's scratch block"
        .assert TM_OY = TM_OX + 4, error, "oldx, oldy"

; the mobj line's groups (mo_get's GC_MP: RTHING, then A, B, C) and
; mo_dirty's group bits
LN_A            = MO_SIZE
LN_B            = 2 * MO_SIZE
LN_C            = 3 * MO_SIZE
D_RTH           = 1
D_A             = 2
D_B             = 4
D_C             = 8

; shared places that the code copies as blocks
        .assert GM_TMX = GM_TMTHING + 2 && GM_TMY = GM_TMX + 4, error, "tmthing, tmx, tmy"
        .assert GM_TMCEILZ = GM_TMFLOORZ + 4 && GM_TMDROPZ = GM_TMCEILZ + 4, error, "tmfloorz, tmceilingz, tmdropoffz"
        .assert MB_CEILZ = MB_FLOORZ + 4 && MB_DROPZ = MB_CEILZ + 4, error, "floorz, ceilingz, dropoffz"
        .assert TH_Y = TH_X + 4, error, "x, y"
        .assert GA_Y = GA_X + 4 && GA_Z = GA_X + 8, error, "GA_X, GA_Y, GA_Z"
        .assert GA_X = GA_0, error, "GA_X"
        .assert <UC_MF_NOCLIP_LO = 0 && <UC_MF_DROPOFF_LO = 0, error, "MF_NOCLIP, MF_DROPOFF: byte 1"
        .assert >UC_MF_NOSECTOR_LO = 0 && >UC_MF_NOBLOCKMAP_LO = 0, error, "MF_NOSECTOR, MF_NOBLOCKMAP: byte 0"
