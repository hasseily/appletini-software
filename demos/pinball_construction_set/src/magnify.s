; Pinball Construction Set for the Appletini -- the magnifier.
;
; The original's HGR pixel editor is replaced by a 16-colour editor of the
; overlay layer (docs/DESIGN.md section 4, layer 2, and section 14): one
; nibble per table pixel in RamWorks bank 1 at $2000 + 160*y, byte x/2,
; high nibble = left pixel, 0 = no edit, 1..15 = that palette colour drawn
; over the polygons and the parts. The renderer merges the rows whose 8x8
; tile has its bit set in ov_tiles (byte (y/8)*3 + x/64, bit (x/8) & 7,
; the layout of render.s's overlay_row) while ov_enabled is set.
;
; Screen (the panel below the logo band, x 154..319, y 64..191):
;   window   32x24 table pixels at 4x (128x96) at (174,66) in a 2-pixel
;            grey frame; every table pixel is a 4x4 box, with its last
;            column and row in the panel colour when the grid is on
;   palette  16 boxes of 8x8 at y 168, x 158 + 10*i, each in a 1-pixel
;            black ring (colour 0, the eraser, as a checker); the current
;            colour's ring is COL_HILITE; a box is picked on press
;   QUIT     leaves (text, x 172..199); GRID toggles the grid (SPR_MAG_GRID
;            at 283,181, framed while on); both are DOMENU items
;            (highlighted while pressed)
; The brush cursor. Button held on the table (x < 154): the window follows
; the cursor (centred on it, clamped to the table); held inside the window:
; the pixel under the cursor takes the current colour (colour 0 erases),
; the table shows it in the same frame, the window's box a frame later
; (redrawn from the screen, so an erased pixel shows what was beneath).
; Keys: 0-9 and A-F pick a colour, G toggles the grid, Esc leaves.
;
; The window is drawn from the SHR screen itself (bank 0 rows of the
; table, which already show polygons, parts and edits merged) expanded
; into the arena three table rows at a time (3 x 4 rows x 64 bytes) and
; copied: 6 KB of posted bytes for a full redraw, once per recentre; a
; painted pixel costs one byte of bank 1, one dirty pixel and a 4x4 box.
;
; Zero page: BASE1/BASE2 (CDRAW's HGR base pointers, unused by the port's
; drawing library) as M_ROW/M_DST while a window routine runs; the
; upstream's CURSORX/CURSORY and YTEMP (DOMENU's item offset). Buffers in
; P1STATE (player state, unused outside a game). MB_STATE = MB_ST_MAG.

.setcpu "65C02"
.include "pcs.inc"
.include "assets.inc"
.macpack longbranch

.export MAGSTART, overlay_clear
.export mag_wx, mag_wy, mag_color, mag_grid, mag_tx, mag_ty
.export paint_pixel, recentre, window_draw

.import frame_step, DOMENU, CRSRINRECT, CHARTO, PRINT
.import input_getkey, in_btn
.import cur_set, cur_hide, cur_want
.import rd_mark, rd_mark_all, rd_ax0, rd_ay0, rd_ax1, rd_ay1, ov_tiles, ov_enabled
.import panel_sprite, panel_fill, panel_frame, ps_id, ps_x, ps_y
.import pf_x0, pf_y0, pf_x1, pf_y1, pf_color
.import aux_fetch_rows, aux_store_rows, copy_arena
.import af_bank, af_src, af_dst, af_len, af_rows, af_sstride, af_dstride
.import arena_stride, cp_x0, cp_y0, cp_w, cp_rows, row_lo, row_hi
.import P1STATE

; the window
MAG_W       = 32                ; table pixels shown
MAG_H       = 24
MAG_SCALE   = 4
SRC_BYTES   = MAG_W/2           ; screen bytes per table row of the window
WIN_X       = 174               ; the window on the screen
WIN_Y       = 66
WIN_W       = MAG_W*MAG_SCALE   ; 128
WIN_H       = MAG_H*MAG_SCALE   ; 96
WIN_BYTES   = WIN_W/2           ; 64: the arena stride of a window row
PASS_ROWS   = 3                 ; table rows per arena pass (3 x 4 x 64 = 768)
FRAME_X0    = WIN_X-2           ; the 2-pixel frame
FRAME_X1    = WIN_X+WIN_W+1
FRAME_Y0    = WIN_Y-2
FRAME_Y1    = WIN_Y+WIN_H+1
FRAME_COL   = COL_GREY
GRID_COL    = COL_PANEL
; the palette strip: 12x10 tiles (a 1-pixel ring round an 8x8 box, a
; panel-coloured column each side) at PAL_PITCH; the hit area is 12 rows
PAL_X0      = 156               ; first tile
PAL_Y0      = 166               ; hit area
PAL_TY      = 167               ; the tile's first row
PAL_PITCH   = 10
PAL_TILE    = 12                ; tile width and hit height
PAL_TILE_H  = 10
PAL_BYTES   = PAL_TILE/2
RING_COL    = COL_BLACK         ; the ring of a colour that is not current
; the bottom row: QUIT and GRID boxes (DOMENU rectangles)
BTN_Y0      = 180
BTN_Y1      = 191
QUIT_X0     = 172
QUIT_X1     = 199
GRID_X0     = 276
GRID_X1     = 303
OV_BANK     = 1

; held modes
HELD_PAN    = 1
HELD_PAINT  = 2
HELD_PICK   = 3

; zero page (see the header)
M_ROW       = BASE1             ; expand: the arena row being copied
M_DST       = BASE2             ; expand: the arena row group; fill_recs: record

; buffers in the player state page
M_BUF       = P1STATE           ; PASS_ROWS x SRC_BYTES fetched screen bytes
M_OVB       = P1STATE+64        ; the overlay byte being edited
M_ZERO      = P1STATE+128       ; TABLE_BYTES zero bytes (overlay_clear)

; the panel_fill inputs are copied from 7-byte records (fill_recs)
.assert pf_y0 = pf_x0+2 && pf_x1 = pf_x0+3 && pf_y1 = pf_x0+5 && pf_color = pf_x0+6, lderror, "pf_* layout"

; ---------------------------------------------------------------------------
.segment "DATA"
mag_wx:     .byte (TABLE_W-MAG_W)/2 & $FE   ; window origin, table pixels (x
mag_wy:     .byte (TABLE_H-MAG_H)/2         ; even): the table's centre at first

.segment "BSS"
mag_color:  .res 1              ; 0..15
mag_grid:   .res 1              ; bit 7: grid on
mag_held:   .res 1              ; what the held button does (HELD_*), 0 idle
mag_pend:   .res 1              ; bit 7: the box of (mag_tx, mag_ty) is redrawn after the next frame
mag_mark:   .res 1              ; colour whose frame is on the palette ($FF: none)
mag_tx:     .res 1              ; the pixel being painted, table pixels
mag_ty:     .res 1
mag_n:      .res 1              ; expand: source bytes
mag_end:    .res 1
mag_stride: .res 1
mag_pass:   .res 1
mag_p:      .res 1              ; scratch
mag_b0:     .res 1              ; pal_tile: the tile's edge bytes and fills
mag_b5:     .res 1
mag_f11:    .res 1
mag_c11:    .res 1

; ---------------------------------------------------------------------------
.segment "RODATA"

; a fill record: x0 lo, x0 hi, y0, x1 lo, x1 hi, y1, colour (the pf_* order)
.macro FILLREC x0, y0, x1, y1, c
        .byte   <(x0), >(x0), y0, <(x1), >(x1), y1, c
.endmacro
; a rectangle record: top, x lo, x hi, height-1, width lo, width hi
.macro RECT x0, y0, x1, y1
        .byte   y0, <(x0), >(x0), (y1)-(y0), <((x1)-(x0)), >((x1)-(x0))
.endmacro

frame_recs:                     ; the window frame: four bars
        FILLREC FRAME_X0, FRAME_Y0, FRAME_X1, FRAME_Y0+1, FRAME_COL
        FILLREC FRAME_X0, FRAME_Y1-1, FRAME_X1, FRAME_Y1, FRAME_COL
        FILLREC FRAME_X0, FRAME_Y0, FRAME_X0+1, FRAME_Y1, FRAME_COL
        FILLREC FRAME_X1-1, FRAME_Y0, FRAME_X1, FRAME_Y1, FRAME_COL
FRAME_RECS = 4
grid_rec:   FILLREC GRID_X0, BTN_Y0, GRID_X1, BTN_Y1, COL_PANEL

WINB:   RECT WIN_X, WIN_Y, WIN_X+WIN_W-1, WIN_Y+WIN_H-1
GRIDB:  RECT GRID_X0, BTN_Y0, GRID_X1, BTN_Y1
QUITB:  RECT QUIT_X0, BTN_Y0, QUIT_X1, BTN_Y1

mag_menu:
        .word   QUITB, mag_quit
        .word   GRIDB, grid_toggle
        .word   0

QUITMSG: .byte  FONT_A+16, FONT_A+20, FONT_A+8, (FONT_A+19)|$80     ; "QUIT"

; ---------------------------------------------------------------------------
.segment "CODE"

; ---------------------------------------------------------------------------
; MAGSTART: the magnifier until Esc or QUIT. EDIT's MAGPAINT calls it with
; the cursor hidden, the panel cleared and the logo band drawn; on return
; the editor redraws the kit and shows the hand.
; ---------------------------------------------------------------------------
MAGSTART:
        lda     #MB_ST_MAG
        sta     MB_STATE
        jsr     frame_step              ; render what the editor left dirty
        lda     #SPR_CUR_BRUSH
        jsr     cur_set
        lda     #$80
        sta     cur_want
        stz     mag_held
        stz     mag_pend
        lda     #$FF
        sta     mag_mark
        jsr     draw_panel
        jsr     window_draw
@loop:  jsr     frame_step
        bit     mag_pend
        bpl     :+
        stz     mag_pend
        jsr     box_draw
:       jsr     input_getkey
        beq     @nokey
        jsr     mag_key
        bcs     @quit
@nokey: lda     in_btn
        bmi     @down
        stz     mag_held
        bra     @loop
@quit:  jmp     mag_exit
@down:  lda     mag_held
        beq     @press
        cmp     #HELD_PAN
        beq     @pan
        cmp     #HELD_PAINT
        bne     @loop                   ; a picked colour: nothing more
        jsr     in_window
        bcc     @loop
@paint: jsr     paint_at_cursor
        bra     @loop
@press: ; a fresh press: table -> pan, window -> paint, palette -> pick,
        ; else the GRID/QUIT menu
        lda     CURSORXH
        bne     @panel
        lda     CURSORX
        cmp     #PANEL_X
        bcs     @panel
        lda     #HELD_PAN
        sta     mag_held
@pan:   jsr     recentre
        bra     @loop
@panel: jsr     in_window
        bcc     :+
        lda     #HELD_PAINT
        sta     mag_held
        bra     @paint
:       jsr     pal_hit
        bcc     @menu
        sta     mag_color
        lda     #HELD_PICK
        sta     mag_held
        jsr     draw_marks
        bra     @loop
@menu:  lda     #<mag_menu
        ldx     #>mag_menu
        jsr     DOMENU                  ; returns on release (mag_quit leaves)
        jsr     draw_marks              ; its highlight may have covered the grid frame
        bra     @loop

; mag_quit: the QUIT item; drops DOMENU's return (WQUIT's way out).
mag_quit:
        pla
        pla
mag_exit:
        lda     #MB_ST_EDIT
        sta     MB_STATE
        stz     cur_want
        jmp     cur_hide

; mag_key: A = the key. C set for Esc; 0-9/A-F pick a colour, G the grid.
mag_key:
        and     #$7F
        cmp     #$1B
        beq     @quit
        cmp     #'0'
        bcc     @done
        cmp     #'9'+1
        bcc     @digit
        and     #$DF                    ; letters: either case
        cmp     #'G'
        beq     @grid
        cmp     #'A'
        bcc     @done
        cmp     #'F'+1
        bcs     @done
        sbc     #'A'-10-1               ; (C clear) -> 10..15
        bra     @set
@digit: and     #$0F
@set:   sta     mag_color
@marks: jsr     draw_marks
@done:  clc
        rts
@grid:  jsr     grid_toggle
        bra     @marks
@quit:  sec
        rts

; grid_toggle: also the GRID item's handler (draw_marks follows).
grid_toggle:
        lda     mag_grid
        eor     #$80
        sta     mag_grid
        jmp     window_draw

; in_window: C set when the cursor is inside the window.
in_window:
        lda     #<WINB
        ldx     #>WINB
        jmp     CRSRINRECT

; pal_hit: C set and A = the colour when the cursor is on the palette strip
; (x 156..315 in tiles of PAL_PITCH, y 166..177).
pal_hit:
        lda     CURSORY
        cmp     #PAL_Y0
        bcc     @no
        cmp     #PAL_Y0+PAL_TILE
        bcs     @no
        lda     CURSORX
        ldx     CURSORXH
        beq     :+
        clc
        adc     #256-PAL_X0             ; x - PAL_X0 for x >= 256 (lo <= 63)
        bra     @div
:       sec
        sbc     #PAL_X0
        bcc     @no
@div:   cmp     #16*PAL_PITCH
        bcs     @no
        ldx     #$FF
        sec
:       inx
        sbc     #PAL_PITCH
        bcs     :-
        txa
        sec
        rts
@no:    clc
        rts

; ---------------------------------------------------------------------------
; recentre: the window centred on the cursor (CURSORX/CURSORY), clamped to
; the table, x even; redrawn when it moved.
; ---------------------------------------------------------------------------
recentre:
        lda     CURSORXH
        bne     @xmax
        lda     CURSORX
        sec
        sbc     #MAG_W/2
        bcs     :+
        lda     #0
:       cmp     #TABLE_W-MAG_W+1
        bcc     @xok
@xmax:  lda     #TABLE_W-MAG_W
@xok:   and     #$FE
        tax
        lda     CURSORY
        sec
        sbc     #MAG_H/2
        bcs     :+
        lda     #0
:       cmp     #TABLE_H-MAG_H+1
        bcc     :+
        lda     #TABLE_H-MAG_H
:       cmp     mag_wy
        bne     @moved
        cpx     mag_wx
        beq     @done
@moved: sta     mag_wy
        stx     mag_wx
        jmp     window_draw
@done:  rts

; ---------------------------------------------------------------------------
; paint_at_cursor: the table pixel under the cursor (inside the window) in
; the current colour. paint_pixel: (mag_tx, mag_ty) in mag_color: the
; overlay nibble in bank 1, the tile bit, the dirty pixel; the window box
; is redrawn after the frame has rendered it.
; ---------------------------------------------------------------------------
paint_at_cursor:
        lda     CURSORX
        sec
        sbc     #<WIN_X                 ; 0..127: the low byte suffices
        lsr     a
        lsr     a
        clc
        adc     mag_wx
        sta     mag_tx
        lda     CURSORY
        sec
        sbc     #WIN_Y
        lsr     a
        lsr     a
        clc
        adc     mag_wy
        sta     mag_ty
paint_pixel:
        ldy     mag_ty
        lda     mag_tx
        jsr     row_addr                ; af_src = the pixel's byte
        lda     af_src
        sta     M_DST                   ; kept for the store
        lda     af_src+1
        sta     M_DST+1
        lda     #<M_OVB
        sta     af_dst
        lda     #>M_OVB
        sta     af_dst+1
        lda     #1
        sta     af_len
        sta     af_rows
        sta     af_bank                 ; OV_BANK
        jsr     aux_fetch_rows
        ; the new byte: an even x is the high nibble
        lda     mag_tx
        lsr     a
        lda     mag_color
        bcs     @odd
        asl     a
        asl     a
        asl     a
        asl     a
        sta     mag_p
        lda     M_OVB
        and     #$0F
        bra     @join
@odd:   sta     mag_p
        lda     M_OVB
        and     #$F0
@join:  ora     mag_p
        cmp     M_OVB
        beq     @done                   ; already that colour
        sta     M_OVB
        lda     #<M_OVB
        sta     af_src
        lda     #>M_OVB
        sta     af_src+1
        lda     M_DST
        sta     af_dst
        lda     M_DST+1
        sta     af_dst+1
        jsr     aux_store_rows
        ; the tile's bit: byte (y/8)*3 + x/64, bit (x/8) & 7
        lda     mag_ty
        lsr     a
        lsr     a
        lsr     a
        sta     mag_p
        asl     a
        adc     mag_p                   ; * 3
        sta     mag_p
        lda     mag_tx
        lsr     a
        lsr     a
        lsr     a                       ; tile 0..19
        pha
        lsr     a
        lsr     a
        lsr     a
        clc
        adc     mag_p
        tay
        pla
        and     #7
        tax
        lda     #1
@bit:   dex
        bmi     :+
        asl     a
        bra     @bit
:       ora     ov_tiles,y
        sta     ov_tiles,y
        lda     #1
        sta     ov_enabled
        ; the table pixel is dirty; its box follows the frame
        lda     mag_tx
        sta     rd_ax0
        sta     rd_ax1
        lda     mag_ty
        sta     rd_ay0
        sta     rd_ay1
        jsr     rd_mark
        lda     #$80
        sta     mag_pend
@done:  rts

; row_addr: Y = table row, A = table x -> af_src = SHR row address + x/2
row_addr:
        lsr     a
        clc
        adc     row_lo,y
        sta     af_src
        lda     row_hi,y
        adc     #0
        sta     af_src+1
        rts

; ---------------------------------------------------------------------------
; window_draw: the whole window from the screen, PASS_ROWS table rows per
; arena pass. box_draw: the two boxes of the byte holding (mag_tx, mag_ty).
; Both hide the cursor (the frame shows it again).
; ---------------------------------------------------------------------------
window_draw:
        jsr     cur_hide
        stz     mag_pass
@pass:  lda     mag_pass
        asl     a
        adc     mag_pass                ; * PASS_ROWS
        clc
        adc     mag_wy
        tay
        lda     mag_wx
        jsr     row_addr
        jsr     fetch_setup
        lda     #SRC_BYTES
        sta     af_len
        sta     af_dstride
        sta     mag_n
        lda     #PASS_ROWS
        sta     af_rows
        lda     #SHR_ROW
        sta     af_sstride
        stz     af_sstride+1
        jsr     aux_fetch_rows
        ldx     #0                      ; source row offset in M_BUF
@row:   phx
        jsr     expand
        inc     M_DST+1                 ; MAG_SCALE rows of WIN_BYTES: a page
        pla
        clc
        adc     #SRC_BYTES
        tax
        cpx     #PASS_ROWS*SRC_BYTES
        bcc     @row
        ; copy the band
        lda     #<WIN_X
        sta     cp_x0
        lda     #>WIN_X
        sta     cp_x0+1
        lda     mag_pass
        asl     a
        asl     a
        sta     mag_p
        asl     a
        adc     mag_p                   ; * PASS_ROWS*MAG_SCALE
        adc     #WIN_Y
        sta     cp_y0
        lda     #WIN_BYTES
        sta     cp_w
        sta     arena_stride
        lda     #PASS_ROWS*MAG_SCALE
        sta     cp_rows
        jsr     copy_arena
        inc     mag_pass
        lda     mag_pass
        cmp     #MAG_H/PASS_ROWS
        bcc     @pass
        rts

box_draw:
        jsr     cur_hide
        ldy     mag_ty
        lda     mag_tx
        jsr     row_addr
        jsr     fetch_setup
        lda     #1
        sta     af_len
        sta     af_rows
        sta     mag_n
        jsr     aux_fetch_rows
        ldx     #0
        jsr     expand
        ; the boxes: x = WIN_X + 4 * ((tx & ~1) - wx), y = WIN_Y + 4 * (ty - wy)
        lda     mag_tx
        and     #$FE
        sec
        sbc     mag_wx
        asl     a
        asl     a
        clc
        adc     #<WIN_X
        sta     cp_x0
        lda     #>WIN_X
        adc     #0
        sta     cp_x0+1
        lda     mag_ty
        sec
        sbc     mag_wy
        asl     a
        asl     a
        clc
        adc     #WIN_Y
        sta     cp_y0
        lda     #MAG_SCALE              ; 2 boxes = 4 bytes, 4 rows
        sta     cp_w
        sta     arena_stride
        sta     cp_rows
        jmp     copy_arena

; fetch_setup: a screen fetch into M_BUF; the arena as expand's destination
fetch_setup:
        lda     #<M_BUF
        sta     af_dst
        lda     #>M_BUF
        sta     af_dst+1
        stz     af_bank
        lda     #<ARENA
        sta     M_DST
        lda     #>ARENA
        sta     M_DST+1
        rts

; ---------------------------------------------------------------------------
; expand: mag_n screen bytes of M_BUF from index X (two pixels each) become
; MAG_SCALE arena rows of 4*mag_n bytes at M_DST: every pixel a box of its
; colour; when the grid is on the box's last column and row are GRID_COL.
; ---------------------------------------------------------------------------
expand:
        lda     mag_n
        asl     a
        asl     a
        sta     mag_stride
        txa
        clc
        adc     mag_n
        sta     mag_end
        ldy     #0
@byte:  lda     M_BUF,x
        pha
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        jsr     put_pixel
        pla
        and     #$0F
        jsr     put_pixel
        inx
        cpx     mag_end
        bcc     @byte
        ; rows 1..3 copy row 0; the last is solid grid colour when it is on
        lda     M_DST
        sta     M_ROW
        lda     M_DST+1
        sta     M_ROW+1
        ldx     #MAG_SCALE-1
@copy:  lda     M_ROW
        clc
        adc     mag_stride
        sta     M_ROW
        bcc     :+
        inc     M_ROW+1
:       ldy     mag_stride
        dey
        cpx     #1
        bne     @cp
        bit     mag_grid
        bpl     @cp
        lda     #GRID_COL*$11
@gl:    sta     (M_ROW),y
        dey
        bpl     @gl
        bra     @next
@cp:    lda     (M_DST),y
        sta     (M_ROW),y
        dey
        bpl     @cp
@next:  dex
        bne     @copy
        rts

; put_pixel: A = a nibble -> two bytes at (M_DST),y (a 4-pixel row of it)
put_pixel:
        sta     mag_p
        asl     a
        asl     a
        asl     a
        asl     a
        ora     mag_p
        sta     (M_DST),y
        iny
        bit     mag_grid
        bpl     :+
        and     #$F0
        ora     #GRID_COL
:       sta     (M_DST),y
        iny
        rts

; ---------------------------------------------------------------------------
; draw_panel: the frame, the palette, the GRID icon and QUIT, the marks.
; ---------------------------------------------------------------------------
draw_panel:
        lda     #<frame_recs
        sta     M_DST
        lda     #>frame_recs
        sta     M_DST+1
        ldx     #FRAME_RECS
        jsr     fill_recs
        ; the palette tiles, none current
        lda     #0
@tile:  pha
        ldx     #RING_COL
        jsr     pal_tile
        pla
        inc     a
        cmp     #16
        bcc     @tile
        ; the grid icon, centred in its box
        lda     #SPR_MAG_GRID
        sta     ps_id
        lda     #<(GRID_X0+7)
        sta     ps_x
        lda     #>(GRID_X0+7)
        sta     ps_x+1
        lda     #BTN_Y0+1
        sta     ps_y
        jsr     panel_sprite
        ; QUIT, centred in its box: x = 7*24 + 6 = 174 (PRCHAR's column
        ; arithmetic is 8-bit: columns above 31 cannot be printed)
        lda     #6
        ldx     #24
        ldy     #BTN_Y0+2
        jsr     CHARTO
        lda     #<QUITMSG
        ldx     #>QUITMSG
        jsr     PRINT
        ; fall into draw_marks

; draw_marks: the current colour's frame (the previous one erased) and
; the grid box's frame (on while the grid is on).
draw_marks:
        lda     mag_mark
        cmp     mag_color
        beq     @grid
        cmp     #16
        bcs     :+                      ; none on the screen yet
        ldx     #RING_COL
        jsr     pal_tile
:       lda     mag_color
        sta     mag_mark
        ldx     #COL_HILITE
        jsr     pal_tile
@grid:  lda     #<grid_rec
        sta     M_DST
        lda     #>grid_rec
        sta     M_DST+1
        jsr     rec_pf
        bit     mag_grid
        bpl     :+
        lda     #COL_HILITE
        sta     pf_color
:       jmp     panel_frame

; fill_recs: X fill records at M_DST, each filled
fill_recs:
        phx
        jsr     rec_pf
        jsr     panel_fill
        lda     M_DST
        clc
        adc     #7
        sta     M_DST
        bcc     :+
        inc     M_DST+1
:       plx
        dex
        bne     fill_recs
        rts

; rec_pf: the fill record at M_DST -> pf_x0..pf_color
rec_pf:
        ldy     #6
:       lda     (M_DST),y
        sta     pf_x0,y
        dey
        bpl     :-
        rts

; ---------------------------------------------------------------------------
; pal_tile: A = colour, X = ring colour: the 12x10 tile of that palette
; box (the ring round the 8x8 box, a panel-coloured column each side)
; built in the arena and copied. Colour 0 is a checker of black and panel
; colour (the eraser).
; ---------------------------------------------------------------------------
pal_tile:
        sta     mag_p
        stx     mag_f11
        jsr     cur_hide
        ; x = PAL_X0 + PAL_PITCH * colour (16-bit)
        lda     mag_p
        asl     a
        asl     a
        asl     a
        adc     mag_p
        adc     mag_p
        clc
        adc     #<PAL_X0
        sta     cp_x0
        lda     #>PAL_X0
        adc     #0
        sta     cp_x0+1
        ; the bytes: edges (panel, ring) and (ring, panel), the fills
        lda     mag_f11
        asl     a
        asl     a
        asl     a
        asl     a
        sta     mag_b5
        ora     mag_f11
        sta     mag_f11
        lda     mag_b5
        ora     #COL_PANEL
        sta     mag_b5
        lda     mag_f11
        and     #$0F
        ora     #COL_PANEL*16
        sta     mag_b0
        lda     mag_p
        asl     a
        asl     a
        asl     a
        asl     a
        ora     mag_p
        sta     mag_c11
        lda     #<ARENA
        sta     M_DST
        lda     #>ARENA
        sta     M_DST+1
        ldx     #0                      ; row
        ldy     #0
@row:   lda     mag_f11                 ; rows 0 and 9: the ring
        cpx     #0
        beq     @have
        cpx     #PAL_TILE_H-1
        beq     @have
        lda     mag_c11                 ; rows 1..8: the box
        bne     @have
        txa                             ; colour 0: the checker
        and     #1
        beq     :+
        lda     #$10
        bra     @have
:       lda     #$01
@have:  sta     mag_p
        lda     mag_b0
        sta     (M_DST),y
        iny
        lda     mag_p
        sta     (M_DST),y
        iny
        sta     (M_DST),y
        iny
        sta     (M_DST),y
        iny
        sta     (M_DST),y
        iny
        lda     mag_b5
        sta     (M_DST),y
        iny
        inx
        cpx     #PAL_TILE_H
        bcc     @row
        lda     #PAL_TY
        sta     cp_y0
        lda     #PAL_BYTES
        sta     cp_w
        sta     arena_stride
        lda     #PAL_TILE_H
        sta     cp_rows
        jmp     copy_arena

; ---------------------------------------------------------------------------
; overlay_clear: no edits: the tile map and ov_enabled cleared, the 192
; rows of the layer zeroed from a zeroed row buffer (source pitch 0), the
; table marked. Called at start-up (RamWorks memory is undefined at
; power-on) and by the file code for a fresh table.
; ---------------------------------------------------------------------------
overlay_clear:
        ldx     #71
:       stz     ov_tiles,x
        dex
        bpl     :-
        stz     ov_enabled
        ldx     #TABLE_BYTES-1
:       stz     M_ZERO,x
        dex
        bpl     :-
        lda     #<M_ZERO
        sta     af_src
        lda     #>M_ZERO
        sta     af_src+1
        lda     #<SHR_BASE
        sta     af_dst
        lda     #>SHR_BASE
        sta     af_dst+1
        lda     #TABLE_BYTES
        sta     af_len
        lda     #TABLE_H
        sta     af_rows
        lda     #OV_BANK
        sta     af_bank
        stz     af_sstride
        stz     af_sstride+1
        lda     #SHR_ROW
        sta     af_dstride
        jsr     aux_store_rows
        jmp     rd_mark_all
