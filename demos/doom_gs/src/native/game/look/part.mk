# src/native/game/look/part.mk: part look of milestone 10 (wave 3;
# docs/GAME.md 2.4; docs/game-parts/look.md): the monsters' senses (A_Look,
# lookForPlayers with behindFast's fast answer, the angle and the distance
# to the target, A_FaceTarget, the melee and missile range checks) and the
# simple actions (the screams, the pain sound, A_Fall), and the radius
# attack (P_RadiusAttack with its ITTAB callback PIT_RadiusAttack).
PART := look
WAVE := 3
look_SRC := game/look/look.s game/look/radius.s
look_ENTRIES := A_Look lookForPlayers behindFast A_FaceTarget \
                checkMeleeRange checkMissileRange P_CheckMeleeRange \
                P_CheckMissileRange A_Scream A_XScream A_Pain A_Fall \
                A_PlayerScream P_RadiusAttack PIT_RadiusAttack
