# src/native/game/chasemove/part.mk: part chasemove of the game (wave 5;
# docs/GAME.md, the parts): the monsters' walk
# (pMove: P_Move with speedStep, mulSpeed, umul16x and their tables;
# tryWalk and P_TryWalk), the new chase direction (newChaseDir, its
# doNewChaseDir with setDir, absGreater, absD, P_NewChaseDir) and the
# drop-off avoidance (avoidDropoff with boxPlus, boxMinus, blockOf; ITTAB's
# PIT_AvoidDropoff with boxAbove, boxBelow, sideFloor, signed, times32).
PART := chasemove
WAVE := 5
chasemove_SRC := game/chasemove/pmove.s game/chasemove/chasedir.s \
                 game/chasemove/dropoff.s
chasemove_ENTRIES := pMove tryWalk P_TryWalk newChaseDir doNewChaseDir \
                     P_NewChaseDir avoidDropoff PIT_AvoidDropoff
