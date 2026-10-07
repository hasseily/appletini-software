# src/native/game/evfloor/part.mk: part evfloor of the game (docs/GAME.md,
# the parts; wave 4): the floors, the stairs and the
# donut a line starts (upstream's p_floor65.s EV_DoFloor, EV_BuildStairs,
# EV_DoDonut, newFloor and the helpers floorUp, setDest, halfSpeed,
# stairStep, nextStep) and LSTAB's entries lnFloor, lnStairs, lnDonut
# (p_switch65.s).
PART := evfloor
WAVE := 4
evfloor_SRC := game/evfloor/evfloor.s
evfloor_ENTRIES := EV_DoFloor EV_BuildStairs EV_DoDonut newFloor \
    lnFloor lnStairs lnDonut
