# src/native/game/teleport/part.mk: part teleport of the game's tic code
# (docs/GAME.md): the teleporters
# (upstream's p_telept65.s EV_Teleport with fogSound, times20, destination;
# p_map65.s P_TeleportMove with stompThing, ITTAB's entry, and farFrom;
# p_switch65.s lnTele, LSTAB's entry).
PART := teleport
WAVE := 4
teleport_SRC := game/teleport/teleport.s
teleport_ENTRIES := EV_Teleport P_TeleportMove stompThing lnTele
