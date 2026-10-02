# src/native/game/teleport/part.mk: part teleport of milestone 10 (wave 4;
# docs/GAME.md 2.4; docs/game-parts/teleport.md): the teleporters
# (upstream's p_telept65.s EV_Teleport with fogSound, times20, destination;
# p_map65.s P_TeleportMove with stompThing, ITTAB's entry, and farFrom;
# p_switch65.s lnTele, LSTAB's entry).
PART := teleport
WAVE := 4
teleport_SRC := game/teleport/teleport.s
teleport_ENTRIES := EV_Teleport P_TeleportMove stompThing lnTele
# the part's test routine (tptest.s: tp_bulk, times20's random check, in
# the driver's area): only in the part's own checkpoint image
# (tools/native/gparts/teleport.py builds it with TP_TEST=1), as damage's
# dtest.s and pspr's pstest.s
ifeq ($(TP_TEST),1)
teleport_SRC += game/teleport/tptest.s
endif
