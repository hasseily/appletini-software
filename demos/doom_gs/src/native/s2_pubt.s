; s2_pubt.s: part s2draw's second test image (docs/m11-parts/s2draw.md):
; s2_pub.s linked alone in AMAPW's room, as AMAPW links it (docs/SCREENS.md
; 4.1's size table: s2_pub 200 B there). Not part of the game.
;
;   s2x_p       s2_publish of the band the caller set up

        .setcpu "65C02"
        .include "s2.inc"

        .export s2x_p, s2_marks, s2_begun
        .import s2_publish

s2_marks = AMAPW_MARKS                 ; a page of AMAPW's marks

        .segment "S2CODE"

s2x_p:  jmp s2_publish

        .segment "S2DATA"
s2_begun:
        .byte 0
