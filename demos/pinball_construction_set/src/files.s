; Pinball Construction Set for the Appletini -- the file menu (stub).
;
; Replaces DISK.S: LOAD, SAVE, PLAY GAME, QUIT under ProDOS. This first
; version only offers PLAY GAME and QUIT; tables are the built-in one.

.setcpu "65C02"
.include "pcs.inc"
.macpack longbranch
.include "assets.inc"

.export files_menu, title_show

.segment "CODE"

files_menu:
        rts

title_show:
        rts
