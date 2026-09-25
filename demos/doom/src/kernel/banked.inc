; Physical bank allocation for the banked GAME build. Code uses auxiliary LC;
; the lower RAM in these banks has independent owners. The loader checks that
; all 128 RamWorks banks are available before taking over the machine.
.ifndef DOOM_BANKED_INC
DOOM_BANKED_INC = 1
GAME_HOME_BANK   = 125
RENDER_HOME_BANK = 122
PACKET_BANK      = 124
PACKET_BASE      = $0200
.endif
