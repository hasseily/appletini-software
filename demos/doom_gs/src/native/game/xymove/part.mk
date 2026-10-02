# src/native/game/xymove/part.mk: part xymove of milestone 10 (wave 5;
# docs/GAME.md 2.4; docs/game-parts/xymove.md): the horizontal move
# (upstream's p_mobj65.s P_XYMovement with clampMove, isBig, wholeMove,
# halfMove, skyHit, quarterOut, slow, frictionAP, frictionNear, friction)
# and the player's wall slide (slideMove with corners, slideTrace, bestMul,
# addCoord, bobClip, labs; PTR_SlideTraverse, TRVTAB's entry;
# hitSlideLine).
PART := xymove
WAVE := 5
xymove_SRC := game/xymove/xymove.s game/xymove/slide.s
xymove_ENTRIES := P_XYMovement slideMove PTR_SlideTraverse hitSlideLine \
                  friction bestMul labs
# the part's test routine (xytest.s: xy_bulk, the helpers' random checks,
# in the driver's area): only in the part's own checkpoint image
# (tools/native/gparts/xymove.py builds it with XY_TEST=1), as damage's
# dtest.s and teleport's tptest.s
ifeq ($(XY_TEST),1)
xymove_SRC += game/xymove/xytest.s
endif
