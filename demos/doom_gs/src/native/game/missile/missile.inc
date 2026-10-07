; game/missile/missile.inc: part missile's places (docs/GAME.md, the parts;
; zero page and scratch). GPL-2, the port's own.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_1 and
; the math block (M_A, M_B, M_R: math.inc), its arguments GA_*. What a
; routine keeps across a call is in the scratch block SB_MISSILE (32
; bytes, ggame.inc); the missile itself also stays on the stack over
; checkMissile and P_TryMove, as upstream keeps it there (p_spawn65.s:
; 624-633, :870-889), since P_TryMove runs game logic.
;
; Conventions of the part's entries (each routine's own comment has the
; rest):
;   - a mobj is its slot (llayout: $FFFF none)
;   - a 32-bit value is little-endian, as upstream's

MSL     = SB_MISSILE
        .assert SB_MISSILE_SIZE >= 32, error, "missile's scratch block"
MSL_SRC  = MSL + 0              ; (2) P_SpawnMissile: the source (SP_SRC)
MSL_DEST = MSL + 2              ; (2)   the destination (SP_DEST)
MSL_TH   = MSL + 4              ; (2)   the missile (SP_TH)
MSL_AN   = MSL + 6              ; (4)   the angle (SP_AN)
MSL_T    = MSL + 10             ; (4)   P_AproxDistance over thSpeed
MSL_HT   = MSL + 14             ; (2) seeTarget, angleMom: the missile
MSL_HS   = MSL + 16             ; (2) seeTarget: the source
MSL_HA   = MSL + 18             ; (4) angleMom: the angle
MSL_SPD  = MSL + 22             ; (4) angleMom: the speed (thSpeed)
MSL_CK   = MSL + 26             ; (2) checkMissile's missile
        .assert MSL_CK + 2 <= MSL + 32, error, "missile's scratch block"

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
LN_A    = MO_SIZE
LN_B    = 2 * MO_SIZE
LN_C    = 3 * MO_SIZE
D_RTH   = 1
D_A     = 2
D_B     = 4
D_C     = 8

; the layouts this code relies on: x, y, z in a row at the line's start
; (srcAbove's and destDelta's copies), M_A then M_B (destDelta's pair),
; GA_X .. GA_Z in a row (P_SpawnMobj's place), the flag bytes
        .assert TH_X = 0 && TH_Y = 4 && TH_Z = 8, error, "RTHING's x, y, z"
        .assert M_B = M_A + 4, error, "M_A, M_B"
        .assert GA_Y = GA_X + 4 && GA_Z = GA_X + 8, error, "GA_X..GA_Z"
        .assert GA_6 = GA_2 + 4, error, "P_TryMove's x, y"
        .assert >UC_MF_SHADOW_HI = 0 && <UC_MF_SHADOW_HI <> 0, error,  "MF_SHADOW's byte (2)"
        .assert >UC_MF_MISSILE_HI = 0 && <UC_MF_MISSILE_HI <> 0, error,  "MF_MISSILE's byte (2)"
