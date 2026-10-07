# src/native/game/attack/part.mk: part attack of the game (wave 5;
# docs/GAME.md: TRVTAB, the parts): the
# hitscan attacks (P_LineAttack, P_AimLineAttack), their traversers
# (PTR_ShootTraverse, PTR_AimTraverse: TRVTAB's entries 1 and 2), the gun
# special (shootSpecial), the puff's place (puffPos) and the products
# mul3 (FixedMul3) and rangeMul.
PART := attack
WAVE := 5
attack_SRC := game/attack/attack.s
attack_ENTRIES := P_AimLineAttack PTR_AimTraverse P_LineAttack \
                  PTR_ShootTraverse shootSpecial puffPos
