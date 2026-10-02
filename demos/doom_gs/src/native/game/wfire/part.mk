# src/native/game/wfire/part.mk: part wfire of milestone 10 (wave 6;
# docs/GAME.md 2.2 ACTTAB, 2.4; docs/game-parts/wfire.md): the player's
# weapons firing: the ACTTAB actions A_FirePistol, A_FireShotgun,
# A_FireCGun, A_FireMissile, A_Punch, A_Saw, the rocket
# P_SpawnPlayerMissile (its aim retries), the hitscan's bulletSlope and
# gunShot, and the helpers meleeAngle, spread, meleeAttack, angleToTarget,
# randMod (p_pspr_randMod) and useAmmo.
PART := wfire
WAVE := 6
wfire_SRC := game/wfire/wfire.s
wfire_ENTRIES := A_FirePistol A_FireShotgun A_FireCGun A_FireMissile \
                 A_Punch A_Saw P_SpawnPlayerMissile bulletSlope gunShot
