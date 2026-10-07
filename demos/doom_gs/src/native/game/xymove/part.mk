# src/native/game/xymove/part.mk: part xymove of the game's tic code
# (docs/GAME.md): the horizontal move
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
