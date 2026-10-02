# src/native/game/player/part.mk: part player of milestone 10 (wave 5;
# docs/GAME.md 2.4, 1.5, 2.2 TRVTAB; docs/game-parts/player.md): the
# player's think each tic (upstream's p_user65.s: P_PlayerThink with the
# death think, movePlayer, calcHeight with fixedSquare, angleToAttacker,
# specialSector, onGround, thrustMul, hurt32) and the use of lines
# (p_use65.s: P_UseLines with times64, TRVTAB's PTR_UseTraverse and
# PTR_NoWayTraverse).
PART := player
WAVE := 5
player_SRC := game/player/puser.s game/player/puse.s
player_ENTRIES := P_PlayerThink fixedSquare specialSector movePlayer \
                  calcHeight angleToAttacker P_UseLines PTR_UseTraverse \
                  PTR_NoWayTraverse
# the part's test routine (pltest.s: pl_bulk, the random checks of
# thrustMul, fixedSquare, times64 and hurt32, in the driver's area): only in
# the part's own checkpoint image (tools/native/gparts/player.py builds it
# with PL_TEST=1), as damage's dtest.s and pspr's pstest.s
ifeq ($(PL_TEST),1)
player_SRC += game/player/pltest.s
endif
