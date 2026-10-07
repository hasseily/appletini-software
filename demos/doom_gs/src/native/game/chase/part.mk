# src/native/game/chase/part.mk: part chase of the game (wave 6;
# docs/GAME.md, the parts): the monsters' chase
# (A_Chase), their attacks (A_PosAttack, A_SPosAttack, A_TroopAttack,
# A_SargAttack, A_CyberAttack, A_BruisAttack with the helpers lineAttack,
# aimLine, spreadAngle, damageTarget, spawnMissile), the barrel's
# explosion (A_Explode) and the barons' death on E1M8 (A_BossDeath).
PART := chase
WAVE := 6
chase_SRC := game/chase/chase.s
chase_ENTRIES := A_Chase A_PosAttack A_SPosAttack A_TroopAttack \
                 A_SargAttack A_CyberAttack A_BruisAttack A_Explode \
                 A_BossDeath lineAttack aimLine spreadAngle damageTarget \
                 spawnMissile
