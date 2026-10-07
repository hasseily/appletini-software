# src/native/game/path/part.mk: part path of the game's tic code
# (docs/GAME.md, TRVTAB): P_PathTraverse, its walk through the block map
# (ptBody with offLine, fromOrigin, axisStep, a1Shr7, ptStuck), the early
# traversal (early) and P_TraverseIntercepts (traverseTo) with TRVTAB's
# dispatch (upstream's callTrav: no code of its own).
PART := path
WAVE := 4
path_SRC := game/path/path.s
path_ENTRIES := P_PathTraverse ptBody traverseTo ptStuck offLine axisStep \
                early
