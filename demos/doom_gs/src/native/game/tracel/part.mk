# src/native/game/tracel/part.mk: part tracel of the game's tic code
# (docs/GAME.md): the
# intercepts of the lines a trace crosses (PIT_AddLineIntercepts, the side
# of a point against the trace, P_InterceptVector3 with its FixedDiv and
# guards, the intercept list and its by-frac chain, ivSetup) and the
# helpers of SIDE1's setup.
PART := tracel
WAVE := 2
tracel_SRC := game/tracel/tracel.s
tracel_ENTRIES := PIT_AddLineIntercepts interceptVector3 divlineSide \
    addIntercept icInsert ivSetup
