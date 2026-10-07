# src/native/game/movers/part.mk: part movers of the game (docs/GAME.md,
# the parts; wave 6): the door thinker T_VerticalDoor
# with partLight (the light of a tagged manual door) and the helper mulExt,
# from upstream's p_doors65.s, and the plat thinker T_PlatRaise, from
# p_plats65.s (THTAB's door and plat entries).
PART := movers
WAVE := 6
movers_SRC := game/movers/movers.s
movers_ENTRIES := T_VerticalDoor partLight T_PlatRaise
