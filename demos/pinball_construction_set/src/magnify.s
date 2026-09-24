; Pinball Construction Set for the Appletini -- the magnifier (stub).
;
; The original's HGR pixel editor is replaced by a 16-colour editor of the
; overlay layer (docs/DESIGN.md section 4). Not written yet: MAGSTART
; returns to the editor at once.

.setcpu "65C02"
.include "pcs.inc"
.macpack longbranch

.export MAGSTART

.segment "CODE"

MAGSTART:
        rts
