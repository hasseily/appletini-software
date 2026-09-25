; The legacy image keeps its packet in GAME bank 1. The banked build streams
; it to a dedicated bank so renderer reads survive replacement of main RAM.
.ifdef BANKED_GAME
.include "banked.inc"
RV_PACKET_ADDR = PACKET_BASE
RV_PACKET_BANK = PACKET_BANK
.else
.global _rview
RV_PACKET_ADDR = _rview
RV_PACKET_BANK = GAME_BANK
.endif
