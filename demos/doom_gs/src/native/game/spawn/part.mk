# src/native/game/spawn/part.mk: part spawn of the game's tic code
# (docs/GAME.md): the puffs and the blood
# (P_SpawnPuff, P_SpawnBlood, their noise and spawn helpers), the punch's
# test of the attack's range, and the height move (P_ZMovement: gravity,
# the floor and ceiling hits, a missile's explosion, the player's squat)
# with missileHit, shr3 and p_mobj65.s's isPlayer.
PART := spawn
WAVE := 2
spawn_SRC := game/spawn/spawn.s game/spawn/zmove.s
spawn_ENTRIES := P_SpawnPuff P_SpawnBlood P_IsAttackRangeMeleeRange \
                 P_ZMovement missileHit shr3 p_mobj_isPlayer
