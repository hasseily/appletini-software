# src/native/game/pickup/part.mk: part pickup of the game's tic code
# (docs/GAME.md): p_inter65.s's pickups (P_TouchSpecialThing, its pickTab
# cases, P_GivePower and the give functions) and m_cheat65.s's cheats'
# effects (C_Responder with the cheat as an event number, power, giveAmmo).
PART := pickup
WAVE := 2
pickup_SRC := game/pickup/pickup.s game/pickup/cheat.s
pickup_ENTRIES := P_TouchSpecialThing P_GivePower C_Responder power \
    m_cheat_giveAmmo giveBody p_inter_giveAmmo giveWeapon givePower \
    pkArmor pkHealthBonus pkSoul pkArmorBonus pkCard pkBody pkPower \
    pkClip pkAmmo pkBackpack pkWeapon

