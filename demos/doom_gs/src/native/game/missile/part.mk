# src/native/game/missile/part.mk: part missile of the game (wave 5;
# docs/GAME.md, the parts): a monster's missile
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
