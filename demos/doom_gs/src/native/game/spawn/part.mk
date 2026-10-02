# src/native/game/spawn/part.mk: part spawn of milestone 10 (wave 2;
# docs/GAME.md 2.4; docs/game-parts/spawn.md): the puffs and the blood
# (P_SpawnPuff, P_SpawnBlood, their noise and spawn helpers), the punch's
# test of the attack's range, and the height move (P_ZMovement: gravity,
# the floor and ceiling hits, a missile's explosion, the player's squat)
# with missileHit, shr3 and p_mobj65.s's isPlayer. sptest.s is the part's
# own image's only (SP_TEST=1: sp_bulk, shr3's random check), in the
# driver's area (wave 6 as integrated: with every part linked, the area
# had no room left for part damage's dtest.s)
PART := spawn
WAVE := 2
spawn_SRC := game/spawn/spawn.s game/spawn/zmove.s
ifeq ($(SP_TEST),1)
spawn_SRC += game/spawn/sptest.s
endif
spawn_ENTRIES := P_SpawnPuff P_SpawnBlood P_IsAttackRangeMeleeRange \
                 P_ZMovement missileHit shr3 p_mobj_isPlayer
