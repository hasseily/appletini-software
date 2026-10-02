# src/native/game/movers/part.mk: part movers of milestone 10 (docs/GAME.md
# 2.4, wave 6; docs/game-parts/movers.md): the door thinker T_VerticalDoor
# with partLight (the light of a tagged manual door) and the helper mulExt,
# from upstream's p_doors65.s, and the plat thinker T_PlatRaise, from
# p_plats65.s (THTAB's door and plat entries).
PART := movers
WAVE := 6
movers_SRC := game/movers/movers.s
movers_ENTRIES := T_VerticalDoor partLight T_PlatRaise
# the part's test routine (mvtest.s: mv_bulk, mulExt's random check, in the
# driver's area): only in the part's own checkpoint image
# (tools/native/gparts/movers.py builds it with MV_TEST=1), as teleport's
# tptest.s
ifeq ($(MV_TEST),1)
movers_SRC += game/movers/mvtest.s
endif
