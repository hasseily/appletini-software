# src/native/game/evfloor/part.mk: part evfloor of milestone 10 (docs/GAME.md
# 2.4, wave 4; docs/game-parts/evfloor.md): the floors, the stairs and the
# donut a line starts (upstream's p_floor65.s EV_DoFloor, EV_BuildStairs,
# EV_DoDonut, newFloor and the helpers floorUp, setDest, halfSpeed,
# stairStep, nextStep) and LSTAB's entries lnFloor, lnStairs, lnDonut
# (p_switch65.s).
PART := evfloor
WAVE := 4
evfloor_SRC := game/evfloor/evfloor.s
evfloor_ENTRIES := EV_DoFloor EV_BuildStairs EV_DoDonut newFloor \
    lnFloor lnStairs lnDonut
