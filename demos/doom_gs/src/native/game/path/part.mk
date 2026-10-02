# src/native/game/path/part.mk: part path of milestone 10 (wave 4;
# docs/GAME.md 0.3 fact 4, 1.9, 2.2 TRVTAB, 2.4 row path;
# docs/game-parts/path.md): P_PathTraverse, its walk through the block map
# (ptBody with offLine, fromOrigin, axisStep, a1Shr7, ptStuck), the early
# traversal (early) and P_TraverseIntercepts (traverseTo) with TRVTAB's
# dispatch (upstream's callTrav: no code of its own, request R3).
PART := path
WAVE := 4
path_SRC := game/path/path.s
path_ENTRIES := P_PathTraverse ptBody traverseTo ptStuck offLine axisStep \
                early
# the part's test routines (pttest.s: pt_bulk, a1Shr7's random check;
# pt_rec_trv, the recording traverser's stand-in of request R2), in the
# driver's area: only in the part's own checkpoint image
# (tools/native/gparts/path.py builds it with PT_TEST=1), as damage's
# dtest.s and pspr's pstest.s
ifeq ($(PT_TEST),1)
path_SRC += game/path/pttest.s
endif
