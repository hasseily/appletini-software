# src/native/game/checkpos/part.mk: part checkpos of the game (wave 3;
# docs/GAME.md, the parts): P_CheckPosition and its
# check (checkPos: the box, the point's floor and ceiling, the things' walk
# with PIT_CheckThing, the lines' walk with PIT_CheckLine, spechit and the
# line record of lineBlocks), setBox, walkRange and cpCopy.
PART := checkpos
WAVE := 3
checkpos_SRC := game/checkpos/checkpos.s
checkpos_ENTRIES := P_CheckPosition checkPos setBox checkThing lineBlocks \
                    walkRange cpCopy
