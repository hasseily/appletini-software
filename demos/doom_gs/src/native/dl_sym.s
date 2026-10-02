; dl_sym.s: the card's routines the play build's tic image calls (docs/
; PLAY.md 4), exported at their addresses in the card's link (playsym.inc,
; tools/native/playlink.py: pl_time, fx_isplaying, fx_stopall are the
; card's, linked by DOOM.SYSTEM's link, not by the tic image's). GPL-2, the
; port's own.

        .include "playsym.inc"

        .export pl_time, fx_isplaying, fx_stopall

pl_time      = XS_pl_time
fx_isplaying = XS_fx_isplaying
fx_stopall   = XS_fx_stopall
