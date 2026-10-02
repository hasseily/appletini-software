# src/native/game/sight/part.mk: part sight of milestone 10 (wave 1;
# docs/GAME.md 2.4; docs/game-parts/sight.md): P_CheckSight with the same
# pair (CS_PREV), REJECT through RJROW, the same subsector, the walk of
# P_CrossBSPNode with its waiting children, the hint as a subsector of one
# seg, the seg and line tests with validcount; zSetup, sightSlope,
# interceptFrac and the opening of a two-sided line; smul48.
PART := sight
WAVE := 1
sight_SRC := game/sight/sight.s game/sight/sfrac.s
sight_ENTRIES := P_CheckSight zSetup sightSlope interceptFrac \
                 p_sight_opening
