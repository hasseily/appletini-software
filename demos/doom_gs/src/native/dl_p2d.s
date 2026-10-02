; dl_p2d.s: P2DW's frame glue (docs/PLAY.md 2.2; docs/m11-parts/design.md
; R7 items 3 and 7: s2_frame, "the second half's"), linked in P2DW's room
; with part s2stbar's s2_st, part s2hud's s2_hu, part s2draw's s2_draw and
; s2_pub, part s2pal's s2_pal, part plinput's pl_poll and part fxplay's
; fx_service (src/native/m11/s2int.mk's list, whose s2_p2dwl.s it
; replaces: the same places). GPL-2, the port's own.
;
;   s2_frame  a level frame's 2D (SCREENS.md 2.1; R7 item 7's order): the
;             input poll, the effect service and S2's snd_refill first;
;             PALST and P2DW's own block from S2STATE; I_ViewPalette (0,
;             or AMAP_PAL in a full-map frame: A bit 0); stripEarly's
;             palette (DD_PAUSED 0: a menu pauses with its own frames);
;             ST_doPaletteStuff, ST_Drawer, HU_Drawer; s2_finish; PALST and
;             the own block back. HU_Drawer's flags (part s2hud's rules):
;             bit 0 stripEarly's C; bit 1 the view drew rows 0-9 (A bit 1)
;             or the full map cleared the strip (S2_MAIL's MAIL_AMSTRIP);
;             bit 2 a view without the overlay drew the title's rows (A
;             bit 2) or the map cleared them (MAIL_AMTITLE); P2DW clears
;             the two mail bits
;   s2_poll   the poll, the effect service and snd_refill alone (a frame
;             that draws nothing: a static title page, gametic = basetic)

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"

        .export s2_frame, s2_poll
        .export s2_marks, s2_fbuf, s2_begun, s2_palst
        .exportzp s2_fbpages
        .import pl_poll, fx_service, snd_refill, s2_palget, s2_viewpal
        .import s2_stripearly, st_palette, st_drawer, hu_drawer, s2_finish
        .import s2_palput, far_get, far_put

s2_marks   = P2DW_MARKS
s2_fbuf    = P2DW_FBUF
s2_fbpages = P2DW_FBPAGES
s2_palst   = PALST_W
s2_begun   = PALST_W + PS_BEGUN
OWN        = PALST_W + PALST_SIZE       ; P2DW's own block, W $BF00
AMAP_PAL   = 11

        .segment "S2CODE"

s2_poll:
        lda #0                  ; (no menu: P2DW runs only without one)
        jsr pl_poll
        jsr fx_service
        jmp snd_refill

s2_frame:
        sta p2_flags
        jsr s2_poll
        jsr s2_palget
        jsr own_arg             ; the own block from S2STATE
        lda #<SS_P2DW
        sta FA_SRC
        lda #>SS_P2DW
        sta FA_SRC+1
        lda #<OWN
        sta FA_DST
        lda #>OWN
        sta FA_DST+1
        jsr far_get
        lda p2_flags            ; I_ViewPalette
        and #1
        beq :+
        lda #AMAP_PAL
:       jsr s2_viewpal
        lda #0                  ; stripEarly (DD_PAUSED 0)
        jsr s2_stripearly
        lda #0
        rol a                   ; (its C: bit 0)
        sta p2_hud
        lda p2_flags
        and #6
        tsb p2_hud
        lda S2_MAIL             ; the full map's mail
        and #MAIL_AMSTRIP
        beq :+
        lda #2
        tsb p2_hud
:       lda S2_MAIL
        and #MAIL_AMTITLE
        beq :+
        lda #4
        tsb p2_hud
:       lda #MAIL_AMSTRIP | MAIL_AMTITLE
        trb S2_MAIL
        jsr st_palette
        jsr st_drawer
        lda p2_hud
        jsr hu_drawer
        jsr s2_finish
        jsr s2_palput
        jsr own_arg             ; the own block back
        lda #<OWN
        sta FA_SRC
        lda #>OWN
        sta FA_SRC+1
        lda #<SS_P2DW
        sta FA_DST
        lda #>SS_P2DW
        sta FA_DST+1
        jmp far_put

own_arg:
        lda #S2STATE
        sta FA_BANK
        stz FA_N                ; (256 bytes)
        rts

        .segment "S2DATA"
p2_flags: .res 1
p2_hud:   .res 1
