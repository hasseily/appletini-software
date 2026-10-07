# src/native/game/secfind/part.mk: part secfind of the game's tic code
# (docs/GAME.md): the sector searches, the specials' updates and the light
# thinkers. sftest.s assembles to nothing here (its routine is under
# .ifdef TESTBUILD, which no build defines).
PART := secfind
WAVE := 1
secfind_SRC := game/secfind/secfind.s game/secfind/sftest.s
secfind_ENTRIES := getNextSector P_FindLowestFloorSurrounding \
    P_FindHighestFloorSurrounding P_FindLowestCeilingSurrounding \
    P_FindSectorFromLineTag P_CheckTag P_UpdateSpecials T_Scroll \
    P_FindNextHighestFloor T_LightFlash T_StrobeFlash T_Glow EV_LightTurnOn \
    lnLight
