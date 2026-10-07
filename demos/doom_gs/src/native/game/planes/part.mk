# src/native/game/planes/part.mk: part planes of the game's tic code
# (docs/GAME.md): the plane movers
# (T_MovePlaneFloor, T_MovePlaneCeiling), the check of the things in a
# moving sector (checkSector = P_CheckSector, changeSector =
# PIT_ChangeSector, heightClip = P_ThingHeightClip) and the floor thinker
# T_MoveFloor (THTAB's), from upstream's p_floor65.s.
PART := planes
WAVE := 4
planes_SRC := game/planes/planes.s
planes_ENTRIES := T_MovePlaneFloor T_MovePlaneCeiling checkSector \
    changeSector heightClip T_MoveFloor
