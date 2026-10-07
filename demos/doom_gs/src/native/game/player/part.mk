# src/native/game/player/part.mk: part player of the game's tic code
# (docs/GAME.md, TRVTAB): the
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
