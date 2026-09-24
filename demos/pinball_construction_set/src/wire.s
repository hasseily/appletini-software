; Pinball Construction Set for the Appletini -- wiring kit glue.
;
; Everything the wiring kit needs from the port lives in render.s
; (DRAWPOLYS, wire lists) and main.s (DRAWWIRE). This file is the place
; for the kit's SOUND/INITSOUND hooks when the sound driver is absent in
; a test build; nothing here yet.

.setcpu "65C02"
.include "pcs.inc"
.macpack longbranch

.segment "CODE"
