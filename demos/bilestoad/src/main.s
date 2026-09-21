; The Bilestoad SHR port: one assembly unit.
; game.s is generated from the upstream disk by tools/lisa2ca65.py. It
; comes first so that its zero-page equates are known to the port code.
.setcpu "65C02"
.include "game.s"
.include "engine.s"
.include "sound.s"
.include "boot.s"
