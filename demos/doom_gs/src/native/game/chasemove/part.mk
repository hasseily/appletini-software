# src/native/game/chasemove/part.mk: part chasemove of milestone 10 (wave 5;
# docs/GAME.md 2.4; docs/game-parts/chasemove.md): the monsters' walk
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
# the part's test routine (cmtest.s: cm_bulk, the random checks of
# umul16x, mulSpeed and times32, in the driver's area): only in the part's
# own checkpoint image (tools/native/gparts/chasemove.py builds it with
# CM_TEST=1), as damage's dtest.s and pspr's pstest.s
ifeq ($(CM_TEST),1)
chasemove_SRC += game/chasemove/cmtest.s
endif
