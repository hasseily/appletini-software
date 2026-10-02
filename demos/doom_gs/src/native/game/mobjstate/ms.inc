; game/mobjstate/ms.inc: part mobjstate's places (milestone 10, docs/GAME.md
; 2.4, 4.4; docs/game-parts/mobjstate.md). GPL-2, the port's own.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_6
; (GT_7 on is the object API's), its arguments GA_*. What a routine keeps
; across a call is in the scratch block SB_MOBJSTATE (32 bytes), each
; routine its own bytes but where no routine of one can be active while
; one of the other is (the overlaps below say which). P_SetMobjState and
; explode keep their mobj on the stack instead: an action may call
; P_SetMobjState again.
;
; Conventions of the part's entries (each routine's own comment has the
; rest):
;   - a mobj or a thinker is its handle (llayout: a mobj's slot, a special
;     SPEC_HANDLE + its slot, $FFFF none); a routine of upstream's _Dp[0-3]
;     takes it in A:X
;   - the object of an ACTTAB action (a mobj's state's action) and of a
;     THTAB thinker function is in GA_0-GA_1 (MS_OBJ): upstream's _Dp, which
;     the callFn of both dispatches leaves to the target
;   - P_SetMobjState: the mobj in MS_OBJ, the state in A:X; A = 1 (Z clear)
;     when the mobj is still there, 0 (Z set) when S_NULL removed it

MS_OBJ  = GA_MO                 ; (2) an action's or a thinker's object
                                ;   (ggame.inc GA_MO: request R4)
MS_W    = API_W                 ; (2) the object API's word (bk_get,
                                ;   bk_put, sn_putw, mi_get: request R2)

MS      = SB_MOBJSTATE
        .assert SB_MOBJSTATE_SIZE >= 32, error, "mobjstate's scratch block"
RM_MO   = MS + 0                ; (2) P_RemoveMobj's mobj
UT_MO   = MS + 2                ; (2) P_UnsetThingPosition's mobj;
MV_MO   = MS + 2                ;     mvSector's, mvBlock's (never active
                                ;     together)
UT_FL   = MS + 4                ; (1) P_UnsetThingPosition's flags (low)
MV_B    = MS + 5                ; (2) mvBlock's new block; mvSector's sector
UL_MO   = MS + 7                ; (2) unlist's and link's mobj
UL_NX   = MS + 9                ; (2) its next
UL_PV   = MS + 11               ; (2) its prev
UL_K    = MS + 13               ; (1) the list: 0 its sector's, 1 its block's
UL_HD   = MS + 14               ; (2) link's list: a sector, a block's index
DN_REC  = SN_BUF                ; (16) P_DelSecnode's node record (the
                                ;   object API's sn_get, sn_put)
UK_TH   = MS + 16               ; (2) unlink's thinker; its prev, its next
UK_PV   = MS + 18
UK_NX   = MS + 20
TD_MO   = MS + 22               ; (2) the delayed removers' thinker
LR_MO   = MS + 24               ; (2) linkRemove's mobj
RC_ST   = MS + 26               ; (2) rocketCheat's state
RC_T    = MS + 28               ; (1) rocketCheat's type
DS_TN   = MS + 29               ; (2) P_DelSecnode's result (tnext)
        .assert DS_TN + 2 <= MS + 32, error, "mobjstate's scratch block"

; the lists of unlist and link (UL_K)
K_SEC   = 0
K_BLK   = 1

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
LN_A    = MO_SIZE
LN_B    = 2 * MO_SIZE
LN_C    = 3 * MO_SIZE
D_RTH   = 1
D_A     = 2
D_B     = 4
D_C     = 8

        .assert >UC_MF_NOSECTOR = 0 && >UC_MF_NOBLOCKMAP = 0, error,  "the flags' low byte"
        .assert <UC_MF_POOLED_HI = 0 && >UC_CF_ENEMY_ROCKETS = 0, error,  "the flags' bytes"
        .assert >UC_MF_MISSILE_HI = 0, error, "MF_MISSILE's byte"
