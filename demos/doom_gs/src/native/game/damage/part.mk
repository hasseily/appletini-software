# src/native/game/damage/part.mk: part damage of milestone 10 (wave 2;
# docs/GAME.md 2.4; docs/game-parts/damage.md): P_DamageMobj (god mode,
# the armour, the thrust, the pain chance, the threshold and the target,
# the player's counts and attacker), killMobj (P_KillMobj: the corpse, the
# counts, the death or extreme death state, the drops), P_DropWeapon,
# lowerWeapon, wInfo and wInfoOf with upstream's weaponinfo table.
PART := damage
WAVE := 2
damage_SRC := game/damage/dinter.s game/damage/dweap.s
damage_ENTRIES := P_DamageMobj killMobj P_DropWeapon lowerWeapon wInfo \
                  wInfoOf
# the part's test routine (dtest.s: the thrust's bulk driver): only in the
# part's own checkpoint image (tools/native/gparts/damage.py builds it with
# DM_TEST=1)
ifeq ($(DM_TEST),1)
damage_SRC += game/damage/dtest.s
endif
