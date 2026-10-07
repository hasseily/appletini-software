; game/xymove/xymove.inc: part xymove's places (docs/GAME.md). GPL-2, the
; port's own.
; Included after ggame.inc.
;
; The scratch block SB_XYMOVE (32 B): what P_XYMovement and the slide keep
; across their calls (upstream's near scratch MV_*, SL_*, p_mobj65.s:31-51,
; which they keep in its znear section):
;
;   XY_MO    the mobj moved (upstream's AP; slidemo, SL_MO)
;   XY_PL    1 when it is the player's mobj (MV_PL)
;   XY_XM    xmove, ymove (MV_XM: 4 bytes each)
;   XY_HIT   P_SlideMove's hitcount (SL_HIT)
;   XY_BEST  bestslidefrac (SL_BEST)
;   XY_LINE  bestslideline (SL_LINE: a line number)
;   XY_TM    tmxmove, tmymove (SL_TMX, SL_TMY)
;   XY_FRAC, XY_LI  PTR_SlideTraverse's intercept: its frac and its line
;            (SL_FRAC, SL_LI), over XY_TM: the traces run before tmxmove
;            is made and none runs while it is live
;
; Upstream's corners (SL_LEAD, SL_TRAIL) are not kept: each trace makes its
; start from the mobj (x, y, radius and the momentum's signs), which no
; trace changes. hitSlideLine's lineangle, deltaangle and lengths
; (HS_LA, HS_DA, HS_LEN) are GT_0-11: between its products only
; the native math runs, which keeps to the math block.

XY              = SB_XYMOVE
XY_MO           = XY + 0        ; 2
XY_PL           = XY + 2        ; 1
XY_XM           = XY + 3        ; 8
XY_HIT          = XY + 11       ; 1
XY_BEST         = XY + 12       ; 4
XY_LINE         = XY + 16       ; 2
XY_TM           = XY + 18       ; 8
XY_FRAC         = XY_TM         ; 4 (over XY_TM)
XY_LI           = XY_TM + 4     ; 2 (over XY_TM)
XY_END          = XY + 26
        .assert XY_END <= SB_XYMOVE + SB_XYMOVE_SIZE, error, "xymove's scratch block"

; the mobj line's groups (mo_get's GC_MP: RTHING, then A, B, C) and
; mo_dirty's group bits
LN_A            = MO_SIZE
LN_B            = 2 * MO_SIZE
LN_C            = 3 * MO_SIZE
D_RTH           = 1
D_C             = 8

; levelconv.py's SKY_PIC: a ceiling pic of -2, upstream's skyflatnum
; (r_data65.s; tools/native/levelconv.py pic_byte): ggame.inc's SKY_PIC
XY_SKYPIC       = SKY_PIC

; MAXMOVE (30.0) and its half, STOPSPEED ($1000), FRACUNIT / 4 ($4000):
; p_mobj65.s:28 and its tests (clampMove, isBig, slow, quarterOut)
XY_MAXMOVE_HI   = 30

; the layouts the code copies as blocks
        .assert TH_Y = TH_X + 4, error, "x, y"
        .assert MC_MOMY = MC_MOMX + 4, error, "momx, momy"
        .assert PL_MOMY = PL_MOMX + 4, error, "the player's momx, momy"
        .assert GA_Y = GA_X + 4 && GA_X = GA_0, error, "GA_X, GA_Y"
        .assert PL_CMD_SIDEMOVE = PL_CMD_FORWARDMOVE + 1, error, "forwardmove, sidemove"
        .assert SEC_FLOOR = 0, error, "the sector line starts with the render record"
        .assert (UC_ORIG_FRICTION & $FFFF) = $E800, error, "ORIG_FRICTION"
        .assert UC_MF_MISSILE_LO = 0 && UC_MF_CORPSE_LO = 0, error, "MF_MISSILE, MF_CORPSE: the flags' high word"
        .assert UC_MF_MISSILE_HI < $100 && UC_MF_CORPSE_HI < $100, error, "MF_MISSILE, MF_CORPSE: byte 2"
        .assert ICPT_SIZE = 6, error, "an intercept: frac 4, what 2"
