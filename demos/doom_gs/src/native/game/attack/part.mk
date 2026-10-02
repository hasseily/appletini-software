# src/native/game/attack/part.mk: part attack of milestone 10 (wave 5;
# docs/GAME.md 2.2 TRVTAB, 2.4 row attack; docs/game-parts/attack.md): the
# hitscan attacks (P_LineAttack, P_AimLineAttack), their traversers
# (PTR_ShootTraverse, PTR_AimTraverse: TRVTAB's entries 1 and 2), the gun
# special (shootSpecial), the puff's place (puffPos) and the products
# mul3 (FixedMul3) and rangeMul.
PART := attack
WAVE := 5
attack_SRC := game/attack/attack.s
attack_ENTRIES := P_AimLineAttack PTR_AimTraverse P_LineAttack \
                  PTR_ShootTraverse shootSpecial puffPos
# the part's test routine (aktest.s: ak_bulk, rangeMul's and mul3's
# random checks), in the driver's area: only in the part's own image
# (tools/native/gparts/attack.py builds it with AK_TEST=1), as damage's
# dtest.s and path's pttest.s
ifeq ($(AK_TEST),1)
attack_SRC += game/attack/aktest.s
endif
