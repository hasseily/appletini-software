# src/native/game/trymove/part.mk: part trymove of milestone 10 (wave 4;
# docs/GAME.md 2.4; docs/game-parts/trymove.md): P_TryMove (the floor,
# ceiling, step and drop-off rules, the move, mvNodes with its shortcut,
# the crossed special lines) and P_NightmareRespawn.
PART := trymove
WAVE := 4
trymove_SRC := game/trymove/trymove.s game/trymove/nightmare.s
trymove_ENTRIES := P_TryMove P_NightmareRespawn
