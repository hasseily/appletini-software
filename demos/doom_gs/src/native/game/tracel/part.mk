# src/native/game/tracel/part.mk: part tracel of milestone 10 (wave 2;
# docs/GAME.md 1.9, 2.4 row tracel; docs/game-parts/tracel.md): the
# intercepts of the lines a trace crosses (PIT_AddLineIntercepts, the side
# of a point against the trace, P_InterceptVector3 with its FixedDiv and
# guards, the intercept list and its by-frac chain, ivSetup) and the
# helpers of SIDE1's setup; tracelt.s is its test driver for the random
# checks, the part's own image's only (TL_TEST=1, which tracel.py's build
# passes; in the driver's area, which the final integration's lockstep
# driver needed: docs/GAME.md "Acceptance", as spawn's sptest.s at wave 6).
PART := tracel
WAVE := 2
tracel_SRC := game/tracel/tracel.s
ifeq ($(TL_TEST),1)
tracel_SRC += game/tracel/tracelt.s
endif
tracel_ENTRIES := PIT_AddLineIntercepts interceptVector3 divlineSide \
    addIntercept icInsert ivSetup
