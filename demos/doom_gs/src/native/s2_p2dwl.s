; s2_p2dwl.s: the integration's link of P2DW (docs/SCREENS.md 4.1, 8.13;
; milestone 11, first half). Not the frame: P2DW's frame glue s2_frame is
; the second half's (docs/m11-parts/design.md R7 items 3, 7 and 14). This
; file links every object of 4.1's P2DW column in its room, so the size
; table holds for P2DW as the release will link it: part s2stbar's s2_st,
; part s2hud's s2_hu, part s2draw's s2_draw and s2_pub, part s2pal's s2_pal,
; part plinput's pl_poll, part fxplay's fx_service (the card's routines
; resolved from fx-card.o, pl_irq.o and S2's player.o, not stored). It
; gives the drawers P2DW's places and names each entry the frame calls, in
; R7 item 7's order. GPL-2, the port's own.

        .setcpu "65C02"
        .include "s2.inc"

        .export s2_marks, s2_fbuf, s2_begun, s2_palst
        .exportzp s2_fbpages
        .import pl_poll, fx_service, s2_palget, s2_viewpal, s2_stripearly
        .import st_palette, st_drawer, hu_drawer, s2_finish, s2_palput

s2_marks   = P2DW_MARKS
s2_fbuf    = P2DW_FBUF
s2_fbpages = P2DW_FBPAGES
s2_palst   = PALST_W
s2_begun   = PALST_W + PS_BEGUN

        .segment "S2CODE"

; the frame's calls (R7 items 3 and 7; S2's snd_refill is the card's):
; a table only, never run
p2dw_calls:
        .addr pl_poll, fx_service, s2_palget, s2_viewpal, s2_stripearly
        .addr st_palette, st_drawer, hu_drawer, s2_finish, s2_palput
