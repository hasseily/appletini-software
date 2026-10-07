# src/native/game/mobjstate/part.mk: part mobjstate of the game (wave 1;
# docs/GAME.md, the parts): the lists of a mobj
# (P_UnsetThingPosition, the sector and block list helpers, the sector
# nodes' deletion), the thinker list's removals and the pools' frees, the
# states (P_SetMobjState with the ACTTAB dispatch and the rocket cheat, the
# brainless thinker) and the missiles' explosion.
PART := mobjstate
WAVE := 1
mobjstate_SRC := game/mobjstate/mslist.s game/mobjstate/msthink.s \
                 game/mobjstate/msstate.s
mobjstate_ENTRIES := P_UnsetThingPosition P_DelSeclist P_DelSecnode \
                     P_RemoveThinker P_RemoveThing P_RemoveThinkerDelayed \
                     P_RemoveThingDelayed P_NextThinker P_RemoveMobj \
                     poolFree linkRemove P_SetMobjState rocketCheat \
                     P_MobjBrainlessThinker P_ExplodeMissile explode \
                     P_MobjIsPlayer
