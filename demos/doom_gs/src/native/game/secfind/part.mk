# src/native/game/secfind/part.mk: part secfind of milestone 10 (docs/GAME.md
# 2.4, wave 1; docs/game-parts/secfind.md)
PART := secfind
WAVE := 1
secfind_SRC := game/secfind/secfind.s game/secfind/sftest.s
secfind_ENTRIES := getNextSector P_FindLowestFloorSurrounding \
    P_FindHighestFloorSurrounding P_FindLowestCeilingSurrounding \
    P_FindSectorFromLineTag P_CheckTag P_UpdateSpecials T_Scroll \
    P_FindNextHighestFloor T_LightFlash T_StrobeFlash T_Glow EV_LightTurnOn \
    lnLight
