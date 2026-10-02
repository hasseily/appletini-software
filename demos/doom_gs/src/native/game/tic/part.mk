# src/native/game/tic/part.mk: part tic of milestone 10 (wave 6;
# docs/GAME.md 2.4, 1.3, 2.2 THTAB, 3.4, 5.1; docs/game-parts/tic.md): the
# game tic (upstream's g_game65.s G_Ticker with its action table and the
# load protocol's return; p_map65.s P_MapEnd) and the level's tic
# (p_think65.s P_Ticker; p_tick65.s P_RunThinkers, the walk over the
# planes with CLEAN, and THTAB's P_MobjThinker); g_tresume, the driver's
# resumption after a load (the card's driver area).
PART := tic
WAVE := 6
tic_SRC := game/tic/gtick.s game/tic/ptick.s
tic_ENTRIES := G_Ticker P_MapEnd P_Ticker P_RunThinkers P_MobjThinker
