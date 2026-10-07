# src/native/game/damage/part.mk: part damage of the game (wave 2;
# docs/GAME.md, the parts): P_DamageMobj (god mode,
# the armour, the thrust, the pain chance, the threshold and the target,
# the player's counts and attacker), killMobj (P_KillMobj: the corpse, the
# counts, the death or extreme death state, the drops), P_DropWeapon,
# lowerWeapon, wInfo and wInfoOf with upstream's weaponinfo table.
PART := damage
WAVE := 2
damage_SRC := game/damage/dinter.s game/damage/dweap.s
damage_ENTRIES := P_DamageMobj killMobj P_DropWeapon lowerWeapon wInfo \
                  wInfoOf
