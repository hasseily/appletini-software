# src/native/game/pspr/part.mk: part pspr of the game's tic code
# (docs/GAME.md): the weapon's and the flash's
# sprites each tic (P_MovePsprites, tickPsprite), the weapon actions
# A_WeaponReady (the bob, the attack, the chainsaw's idle sound), A_ReFire,
# A_Lower, A_GunFlash, A_Light0-2, fireWeapon with the noise alert, the
# sound flood recursiveSound (iterative, its 512-entry work stack in its
# group), checkAmmo and P_CheckAmmo, and the helpers startSound,
# setMoState, signExt4, signExt0, fireSomething.
PART := pspr
WAVE := 3
pspr_SRC := game/pspr/pspr.s game/pspr/pflood.s
pspr_ENTRIES := P_MovePsprites tickPsprite A_WeaponReady A_ReFire A_Lower \
                A_GunFlash A_Light0 A_Light1 A_Light2 fireWeapon checkAmmo \
                recursiveSound P_CheckAmmo
