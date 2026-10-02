; game/chasemove/chasemove.inc: part chasemove's places (milestone 10,
; docs/GAME.md 2.4 row chasemove, 4.4; docs/game-parts/chasemove.md).
; GPL-2, the port's own. Included after ggame.inc.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_6 (GT_7
; on is the object API's, which every API call may change) and the math
; block, its arguments GA_*. What its routines keep across a call is in
; the scratch block SB_CHASEMOVE (32 B), upstream's near scratch of
; p_enemy65.s (PM_TRY .. EN_LINE), overlaid where upstream's own uses do
; not meet:
;
;   CM_AP     the actor (upstream's AP: a far pointer on the direct page
;             there, the mobj's handle here); every entry sets it from
;             GA_0-1 (pMove inside newChaseDir's tryWalk sets the same
;             actor again)
;   CM_D      newChaseDir and doNewChaseDir: deltax, deltay (EN_D);
;             avoidDropoff's block loop: xh, yl, yh (EN_B+2 .. EN_B+6) and
;             PIT_AvoidDropoff's line (EN_LINE), dead before newChaseDir
;             writes the deltas
;   CM_DDX, CM_DDY  dropoff_deltax, dropoff_deltay (EN_DDX, EN_DDY)
;   CM_FLOORZ avoidDropoff's floorz (EN_FLOORZ: the actor's z); after it,
;             doNewChaseDir's xdir, ydir, olddir, turnaround (EN_DIR, a byte
;             each: upstream's words hold 0-8)
;   CM_BX, CM_BY  avoidDropoff's block (EN_BX, EN_BY); CM_BX's first byte
;             is then doNewChaseDir's search direction (EN_TDIR)
;   CM_GOOD   pMove: a special line opened (PM_GOOD)
;
; upstream's PM_TRY (tryx, tryy) is P_TryMove's arguments GA_2-9 here, its
; EN_T a temporary (GT_*), PIT_AvoidDropoff's front and back floors (EN_D
; there) in GT_* and the math block: no call comes between their making
; and their use but the object API's and the math's

CM      = SB_CHASEMOVE
CM_AP   = CM + 0                ; (2) the actor
CM_D    = CM + 2                ; (8) deltax, deltay
CM_XH   = CM + 2                ; (2) avoidDropoff: xh
CM_YL   = CM + 4                ; (2)   yl
CM_YH   = CM + 6                ; (2)   yh
CM_LINE = CM + 8                ; (2) PIT_AvoidDropoff: the line
CM_DDX  = CM + 10               ; (4) dropoff_deltax
CM_DDY  = CM + 14               ; (4) dropoff_deltay
CM_FLOORZ = CM + 18             ; (4) avoidDropoff: floorz (the actor's z)
CM_XDIR = CM + 18               ; (1) doNewChaseDir: xdir
CM_YDIR = CM + 19               ; (1)   ydir
CM_OLD  = CM + 20               ; (1)   olddir
CM_TURN = CM + 21               ; (1)   turnaround
CM_BX   = CM + 22               ; (2) avoidDropoff: bx
CM_TDIR = CM + 22               ; (1) doNewChaseDir: the search's direction
CM_BY   = CM + 24               ; (2) avoidDropoff: by
CM_GOOD = CM + 26               ; (1) pMove: a special line opened
CM_END  = CM + 27
        .assert CM_END <= SB_CHASEMOVE + SB_CHASEMOVE_SIZE, error, "chasemove's scratch block"
        .assert CM_DDY = CM_DDX + 4, error, "dropoff_deltax, dropoff_deltay"

; a mobj cache line's groups (mo_get's GC_MP: RTHING, then A, B, C) and
; mo_dirty's group bits
LN_A    = MO_SIZE
LN_B    = 2 * MO_SIZE
LN_C    = 3 * MO_SIZE
D_RTH   = 1
D_A     = 2
D_B     = 4
D_C     = 8

; the facts the code relies on
        .assert TH_X = 0 && TH_Y = 4, error, "RTHING's x, y first"
        .assert GA_X = GA_0, error, "GA_X"
        .assert UC_DI_EAST = 0 && UC_DI_NORTHEAST = 1 && UC_DI_NORTH = 2, error, "the directions"
        .assert UC_DI_NORTHWEST = 3 && UC_DI_WEST = 4 && UC_DI_SOUTHWEST = 5, error, "the directions"
        .assert UC_DI_SOUTH = 6 && UC_DI_SOUTHEAST = 7 && UC_DI_NODIR = 8, error, "the directions"
        .assert <UC_MF_DROPOFF_LO = 0 && UC_MF_DROPOFF_HI = 0, error, "MF_DROPOFF: flags' byte 1"
        .assert UC_BOXTOP = 0 && UC_BOXBOTTOM = 1 && UC_BOXLEFT = 2 && UC_BOXRIGHT = 3, error, "the box's order"
        .assert LN_BOTTOM = LN_TOP + 2 && LN_LEFT = LN_TOP + 4 && LN_RIGHT = LN_TOP + 6, error, "a line's box"
        .assert UC_MAPBLOCKSHIFT = 23, error, "MAPBLOCKSHIFT"
        .assert MB_DROPZ = MB_FLOORZ + 8, error, "floorz, dropoffz"
