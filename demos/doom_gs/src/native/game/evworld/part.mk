# src/native/game/evworld/part.mk: part evworld of milestone 10 (docs/GAME.md
# 2.4, wave 3; docs/game-parts/evworld.md): the doors and the plats a line
# starts (upstream's p_doors65.s EV_DoDoor, newDoor, EV_VerticalDoor;
# p_plats65.s EV_DoPlat) and LSTAB's entries lnDoor, lnPlat, lnVDoor
# (p_switch65.s).
PART := evworld
WAVE := 3
evworld_SRC := game/evworld/evworld.s
evworld_ENTRIES := EV_DoDoor EV_VerticalDoor newDoor EV_DoPlat \
    lnDoor lnPlat lnVDoor
