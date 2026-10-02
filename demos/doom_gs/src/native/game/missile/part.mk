# src/native/game/missile/part.mk: part missile of milestone 10 (wave 5;
# docs/GAME.md 2.4; docs/game-parts/missile.md): a monster's missile
# (P_SpawnMissile: the angle, a shadow target's P_Random, the speed, momz
# by the distance with math.s's sdiv32), its spawn check (checkMissile:
# the tics noise, the half step, P_TryMove, the explosion), halfMom, and
# the helpers part wfire's P_SpawnPlayerMissile shares (srcAbove,
# seeTarget, thSpeed, angleMom).
PART := missile
WAVE := 5
missile_SRC := game/missile/missile.s
missile_ENTRIES := P_SpawnMissile checkMissile halfMom srcAbove seeTarget \
                   thSpeed angleMom
# the part's test routine (mstest.s: ms_bulk, halfMom's random check, in the
# driver's area): only in the part's own checkpoint image
# (tools/native/gparts/missile.py builds it with MS_TEST=1), as damage's
# dtest.s and pspr's pstest.s
ifeq ($(MS_TEST),1)
missile_SRC += game/missile/mstest.s
endif
