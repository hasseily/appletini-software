; Pinball Construction Set for the Appletini -- the drawing library the
; upstream modules call (CDRAW.S's entry points, new semantics).
;
; The register interface of every entry point is the original's
; (docs/DESIGN.md section 5): records are 7-byte bitmaps (sprite pointer,
; y, x lo, x hi, height, width) and 6-byte rectangles (top, x lo, x hi,
; height-1, width lo, width hi); text positions are 7-pixel columns plus
; an offset, as CHARTO's callers pass them. What changes is what they do:
;   XOFFDRAW   in the table: the sprite's box becomes dirty (the renderer
;              draws it); in the panel: the sprite is drawn at once
;   DRAWRECT   pen CLR: fill with the panel colour; pen XOR: toggle a
;              highlight frame (menus)
;   INITCRSR   set the cursor shape and show it
;   XDRAWCRSR  hide/show the cursor (the original XOR toggle)
;   UPDATECRSR one frame: line 0, input, render, cursor at the mouse
;   GETBUTNS   the button state; steps a frame when the caller spins
;   DOMENU     the original's press/highlight/release menu protocol
;   PRCHAR     5x7 glyphs in the text colour on the panel
;
; frame_step is the one place a video frame is paced (also used by the
; play loops in play.s). Zero page: ZEROPAGE variables only.

.setcpu "65C02"
.include "pcs.inc"
.include "assets.inc"
.macpack longbranch

.export SETMODE, XOFFDRAW, DRAWRECT, INIT, INITCRSR, XDRAWCRSR, UPDATECRSR
.export GETCURSORX, JSCTRL, CRSRINRECT, INRECT, DOMENU, GETBUTNS
.export CHARTO, PRCHAR, PRINT, CHARBITS
.export frame_step, frame_fresh, text_color, pen_mode, frame_count
.export DRAWQUIT, WQUIT, MCMDB, MQUITB

.import video_wait_vbl, rd_frame, rd_mark_record, cur_set, cur_move, cur_hide, cur_show
.import cur_x, cur_y, cur_id, cur_want, hl_toggle
.import panel_sprite, panel_fill, ps_id, ps_x, ps_y, pf_x0, pf_y0, pf_x1, pf_y1, pf_color
.import rd_mark_all, rd_ax0, rd_ax1, rd_ay0, rd_ay1, rd_mark, rd_count
.import blit_sprite, copy_arena, fill_arena, bl_id, bl_x, bl_y, bl_cx0, bl_cx1, bl_cy0, bl_cy1
.import arena_stride, cp_x0, cp_y0, cp_w, cp_rows, cp_count
.import aux_fetch_rows, aux_store_rows, af_bank, af_src, af_dst, af_len, af_rows, af_sstride, af_dstride
.import row_lo, row_hi, P1STATE, PBBASE
.import input_frame, input_getkey, in_mx, in_my, in_btn
.import snd_frame
.import spr_dir, spr_w, spr_h, spr_hoty, font7, font_adv
.importzp V_PTR

; ---------------------------------------------------------------------------
.segment "ZEROPAGE"
C_PTR:  .res 2
C_TMP:  .res 2

.segment "BSS"
pen_mode:   .res 1
text_color: .res 1
frame_fresh: .res 1             ; bit 7: a frame was stepped since the last GETBUTNS
frame_count: .res 2
menu_jump:  .res 2
CHARBITS:   .res 7              ; text position record: ptr, y, column, offset, 7, 1
glyph_buf:  .res 4*7

.segment "RODATA"
QUITMSG: .byte $1A,$1E,$12,$9D          ; "QUIT" in the font's codes
; the world/magnifier panel region and its QUIT box (rect records)
MCMDB:  .byte 64, <PANEL_X, >PANEL_X, 127, <(SCREEN_W-1-PANEL_X), >(SCREEN_W-1-PANEL_X)
MQUITB: .byte 176, <182, >182, 11, 30, 0

.segment "CODE"

; ---------------------------------------------------------------------------
; frame_step: wait for line 0, read the input, render, sound, cursor.
; ---------------------------------------------------------------------------
frame_step:
        jsr     video_wait_vbl
        jsr     input_frame
        jsr     place_cursor
        jsr     rd_frame
        lda     rd_count
        sta     MB_RECTS
        jsr     snd_frame
        inc     frame_count
        bne     :+
        inc     frame_count+1
:       lda     frame_count
        sta     MB_FRAME
        lda     frame_count+1
        sta     MB_FRAME+1
        lda     cp_count
        sta     MB_WRITES
        lda     cp_count+1
        sta     MB_WRITES+1
        ; largest count seen
        lda     cp_count+1
        cmp     MB_MAXWRITES+1
        bcc     :+
        bne     @max
        lda     cp_count
        cmp     MB_MAXWRITES
        bcc     :+
@max:   lda     cp_count
        sta     MB_MAXWRITES
        lda     cp_count+1
        sta     MB_MAXWRITES+1
:       stz     cp_count
        stz     cp_count+1
        lda     #$80
        sta     frame_fresh
        rts

; place_cursor: the cursor follows the mouse, kept on the screen.
place_cursor:
        ldx     cur_id
        lda     in_mx+1
        sta     C_TMP+1
        lda     in_mx
        sta     C_TMP
        ; max x = 320 - w
        lda     #<SCREEN_W
        sec
        sbc     spr_w,x
        sta     C_PTR
        lda     #>SCREEN_W
        sbc     #0
        sta     C_PTR+1
        lda     C_TMP
        cmp     C_PTR
        lda     C_TMP+1
        sbc     C_PTR+1
        bcc     :+
        lda     C_PTR
        sta     C_TMP
        lda     C_PTR+1
        sta     C_TMP+1
:       lda     #SCREEN_H
        sec
        sbc     spr_h,x
        cmp     in_my
        bcs     :+
        sta     in_my
:       lda     C_TMP
        sta     CURSORX
        lda     C_TMP+1
        sta     CURSORXH
        lda     in_my
        sta     CURSORY
        lda     C_TMP
        ldx     C_TMP+1
        ldy     in_my
        jmp     cur_move

; ---------------------------------------------------------------------------
SETMODE:
        sty     pen_mode
        rts

; XOFFDRAW: A/X = record. Table: dirty; panel: draw now.
XOFFDRAW:
        sta     C_PTR
        stx     C_PTR+1
        ldy     #4
        lda     (C_PTR),y
        bne     @panel
        dey
        lda     (C_PTR),y
        cmp     #PANEL_X
        bcs     @panel
        lda     C_PTR
        ldx     C_PTR+1
        jmp     rd_mark_record
@panel: jsr     record_id
        cpx     #$FF
        beq     @done
        stx     ps_id
        ldy     #3
        lda     (C_PTR),y
        sta     ps_x
        iny
        lda     (C_PTR),y
        sta     ps_x+1
        ldy     #2
        lda     (C_PTR),y
        sec
        sbc     spr_hoty,x
        sta     ps_y
        ; a record inside the database is an object being dragged over the
        ; kit: the original XORed it (draw, erase, draw...); the port shows
        ; it with save-under and hides it on the next call
        lda     C_PTR+1
        cmp     #>PBBASE
        bcs     floater
        jmp     panel_sprite
@done:  rts

; floater: toggle the dragged object's image in the panel. The bytes
; under its box (panel_sprite's box: even x, (w+2)/2 bytes, h rows) are
; kept in P1STATE, unused outside a game.
floater:
        bit     fl_shown
        bmi     @hide
        jsr     cur_hide                ; the cursor is redrawn at frame end
        lda     ps_x
        and     #$FE
        sta     fl_x
        lda     ps_x+1
        sta     fl_x+1
        lda     ps_y
        sta     fl_y
        ldx     ps_id
        lda     spr_w,x
        clc
        adc     #2
        lsr     a
        sta     fl_w
        lda     spr_h,x
        sta     fl_h
        jsr     @setup                  ; af_dst = screen, af_src = buffer
        ; save: screen -> buffer (swap the ends)
        lda     af_src
        ldx     af_dst
        stx     af_src
        sta     af_dst
        lda     af_src+1
        ldx     af_dst+1
        stx     af_src+1
        sta     af_dst+1
        lda     #SHR_ROW
        sta     af_sstride
        lda     fl_w
        sta     af_dstride
        jsr     aux_fetch_rows
        lda     #$80
        sta     fl_shown
        jmp     panel_sprite
@hide:  stz     fl_shown
        jsr     cur_hide                ; its save-under holds floater pixels
        jsr     @setup
        lda     fl_w
        sta     af_sstride
        lda     #SHR_ROW
        sta     af_dstride
        jmp     aux_store_rows          ; buffer -> screen
; the box's screen address and the buffer, bank 0, fl_w bytes x fl_h rows
@setup: ldy     fl_y
        lda     fl_x+1
        lsr     a
        lda     fl_x
        ror     a
        clc
        adc     row_lo,y
        sta     af_dst
        lda     row_hi,y
        adc     #0
        sta     af_dst+1
        lda     #<P1STATE
        sta     af_src
        lda     #>P1STATE
        sta     af_src+1
        lda     fl_w
        sta     af_len
        lda     fl_h
        sta     af_rows
        stz     af_bank
        stz     af_sstride+1
        rts

.segment "BSS"
fl_shown: .res 1                ; bit 7: the floater is on the screen
fl_x:    .res 2
fl_y:    .res 1
fl_w:    .res 1                 ; bytes per row
fl_h:    .res 1
.segment "CODE"

; record_id: C_PTR = record -> X = sprite id (from the directory pointer), $FF if none
record_id:
        ldy     #0
        lda     (C_PTR),y
        sec
        sbc     #<spr_dir
        sta     C_TMP
        iny
        lda     (C_PTR),y
        sbc     #>spr_dir
        lsr     a
        ror     C_TMP
        lsr     a
        ror     C_TMP                   ; (sets Z from C_TMP, not A)
        cmp     #0
        bne     @bad
        ldx     C_TMP
        cpx     #SPR_COUNT
        bcs     @bad
        rts
@bad:   ldx     #$FF
        rts

; DRAWRECT: A/X = rectangle record.
DRAWRECT:
        ldy     pen_mode
        cpy     #2
        beq     @xor
        sta     C_PTR
        stx     C_PTR+1
        jsr     rect_to_pf
        ldy     pen_mode
        lda     #COL_PANEL
        cpy     #3
        beq     :+
        lda     #COL_TEXT               ; pen OR: white-ish (unused)
:       sta     pf_color
        ; table rectangles are never filled this way; clip to the panel
        lda     pf_x0+1
        bne     :+
        lda     pf_x0
        cmp     #PANEL_X
        bcs     :+
        lda     #PANEL_X
        sta     pf_x0
:       jmp     panel_fill
@xor:   jmp     hl_toggle

; rect_to_pf: C_PTR = rectangle -> pf_x0/y0/x1/y1 (inclusive)
rect_to_pf:
        ldy     #0
        lda     (C_PTR),y
        sta     pf_y0
        iny
        lda     (C_PTR),y
        sta     pf_x0
        iny
        lda     (C_PTR),y
        sta     pf_x0+1
        iny
        lda     (C_PTR),y
        clc
        adc     pf_y0
        sta     pf_y1
        iny
        lda     (C_PTR),y
        clc
        adc     pf_x0
        sta     pf_x1
        iny
        lda     (C_PTR),y
        adc     pf_x0+1
        sta     pf_x1+1
        rts

; INIT: clear the screen: the table is re-rendered, the panel filled.
INIT:
        jsr     cur_hide
        stz     cur_want
        lda     #PANEL_X
        sta     pf_x0
        stz     pf_x0+1
        lda     #<(SCREEN_W-1)
        sta     pf_x1
        lda     #>(SCREEN_W-1)
        sta     pf_x1+1
        stz     pf_y0
        lda     #SCREEN_H-1
        sta     pf_y1
        lda     #COL_PANEL
        sta     pf_color
        jsr     panel_fill
        jmp     rd_mark_all

; ---------------------------------------------------------------------------
; The cursor
; ---------------------------------------------------------------------------
; INITCRSR: A/X = cursor record; set the shape and show it (the original
; falls through into XDRAWCRSR).
INITCRSR:
        sta     C_PTR
        stx     C_PTR+1
        jsr     record_id
        cpx     #$FF
        beq     @done
        txa
        jsr     cur_set
        lda     #$80
        sta     cur_want
        jmp     cur_show
@done:  rts

; XDRAWCRSR: toggle.
XDRAWCRSR:
        bit     cur_want
        bmi     @hide
        lda     #$80
        sta     cur_want
        jmp     cur_show
@hide:  stz     cur_want
        jmp     cur_hide

; UPDATECRSR: one frame.
UPDATECRSR:
        jmp     frame_step

GETCURSORX:
        lda     CURSORXH
        bne     @far
        lda     CURSORX
        rts
@far:   lda     #$FF
        rts

; JSCTRL: the original inverted the joystick axes on X/Y; keys are read
; by input_frame, nothing to do.
JSCTRL:
        rts

; GETBUTNS: N set while the button is down. A caller that spins on
; GETBUTNS without UPDATECRSR still gets one frame per call.
GETBUTNS:
        bit     frame_fresh
        bmi     :+
        phx
        phy
        jsr     frame_step
        ply
        plx
:       stz     frame_fresh
        lda     in_btn
        rts

; CRSRINRECT: A/X = rectangle; C set when the cursor's hot spot is inside.
; NEWITEM = the rectangle (for DOMENU). Keeps A and X.
CRSRINRECT:
        sta     NEWITEM
        stx     NEWITEM+1
        ldy     CURSORX
        sty     PARAM+3
        ldy     CURSORXH
        sty     PARAM+4
        ldy     CURSORY
        sty     PARAM+5
; INRECT: A/X = rectangle; PARAM+3/4 = x, PARAM+5 = y.
INRECT:
        pha
        phx
        sta     C_PTR
        stx     C_PTR+1
        jsr     rect_to_pf
        ; x0 <= x <= x1
        lda     PARAM+3
        cmp     pf_x0
        lda     PARAM+4
        sbc     pf_x0+1
        bcc     @no
        lda     pf_x1
        cmp     PARAM+3
        lda     pf_x1+1
        sbc     PARAM+4
        bcc     @no
        lda     PARAM+5
        cmp     pf_y0
        bcc     @no
        cmp     pf_y1
        beq     @yes
        bcs     @no
@yes:   plx
        pla
        sec
        rts
@no:    plx
        pla
        clc
        rts

; ---------------------------------------------------------------------------
; DOMENU: A/X = list of (rectangle, handler) pairs ended by a zero byte.
; While the button is held the item under the cursor is highlighted;
; releasing it over an item jumps to the handler with YTEMP = the item's
; offset; releasing elsewhere returns with X = 0.
; ---------------------------------------------------------------------------
DOMENU:
        sta     PARAM
        stx     PARAM+1
@again: ldy     #0
@item:  lda     (PARAM),y
        iny
        ora     (PARAM),y               ; a zero word ends the list
        dey                             ; (sets Z from Y, not A)
        cmp     #0
        bne     @have
        ; end of the list: un-highlight, frame, check the button
        ldx     LASTITEM+1
        beq     :+
        lda     LASTITEM
        jsr     hl_toggle
        stz     LASTITEM+1
:       jsr     frame_step
        lda     in_btn
        bmi     @again
        ldx     #0
        rts
@have:  sty     YTEMP
        lda     (PARAM),y               ; the record: lo, hi
        pha
        iny
        lda     (PARAM),y
        tax
        pla
        jsr     CRSRINRECT
        bcc     @next
        jsr     select
        ldy     YTEMP
        bcc     @item
        iny
        iny
        lda     (PARAM),y
        sta     menu_jump
        iny
        lda     (PARAM),y
        sta     menu_jump+1
        jmp     (menu_jump)
@next:  lda     YTEMP
        clc
        adc     #4
        tay
        bne     @item
        rts

; select: the cursor is over NEWITEM. Highlight it (un-highlighting the
; previous one), step a frame; C set when the button was released here.
select:
        lda     LASTITEM+1
        beq     @on
        cmp     NEWITEM+1
        bne     @switch
        lda     LASTITEM
        cmp     NEWITEM
        beq     @frame
@switch:
        lda     NEWITEM
        ldx     NEWITEM+1
        jsr     hl_toggle
        lda     LASTITEM
        ldx     LASTITEM+1
        ldy     NEWITEM
        sty     LASTITEM
        ldy     NEWITEM+1
        sty     LASTITEM+1
        jsr     hl_toggle
        bra     @frame
@on:    lda     NEWITEM
        ldx     NEWITEM+1
        jsr     hl_toggle
        lda     NEWITEM
        sta     LASTITEM
        lda     NEWITEM+1
        sta     LASTITEM+1
@frame: jsr     frame_step
        lda     in_btn
        bmi     @held
        lda     LASTITEM
        ldx     LASTITEM+1
        jsr     hl_toggle
        stz     LASTITEM+1
        sec
        rts
@held:  clc
        rts

; ---------------------------------------------------------------------------
; Text: CHARTO (A = offset, X = column of 7 pixels, Y = row), PRCHAR
; (A = code 0..35, 36 = space), PRINT (A/X = codes, bit 7 on the last).
; ---------------------------------------------------------------------------
CHARTO:
        sta     CHARBITS+4
        stx     CHARBITS+3
        sty     CHARBITS+2
        rts

PRCHAR:
        sta     TEMP
        cmp     #36
        bcs     @advance
        ; x = column*7 + offset (16-bit: columns 37-45 lie beyond x 255)
        stz     C_TMP+1
        lda     CHARBITS+3
        asl     a
        rol     C_TMP+1
        asl     a
        rol     C_TMP+1
        asl     a
        rol     C_TMP+1                 ; column*8
        sec
        sbc     CHARBITS+3
        bcs     :+
        dec     C_TMP+1
:       clc
        adc     CHARBITS+4
        sta     C_TMP
        bcc     :+
        inc     C_TMP+1
:       ; panel only
        lda     C_TMP+1
        bne     :+
        lda     C_TMP
        cmp     #PANEL_X
        bcc     @advance
:       jsr     draw_glyph
@advance:
        ldy     TEMP
        lda     font_adv,y
        clc
        adc     CHARBITS+4
:       cmp     #7
        bcc     :+
        inc     CHARBITS+3
        sbc     #7
        bra     :-
:       sta     CHARBITS+4
        rts

; draw_glyph: glyph TEMP at (C_TMP, CHARBITS+2) in the text colour on the
; panel colour: 7 rows of 4 bytes in the arena, then copied. The 7-pixel
; cell leaves one edge pixel outside it in this 8-pixel copy. Preserve that
; pixel so a later score digit drawn to the left cannot erase its neighbour.
draw_glyph:
        jsr     cur_hide
        lda     #4
        sta     arena_stride
        sta     cp_w
        lda     CHARBITS+2
        sta     bl_cy0
        clc
        adc     #6
        sta     bl_cy1
        ; Fetch the byte containing the pixel just outside the glyph cell
        ; from each screen row. Even x preserves the last low nibble; odd x
        ; preserves the first high nibble.
        lda     C_TMP
        and     #$FE
        sta     cp_x0
        lda     C_TMP+1
        sta     cp_x0+1
        ldy     CHARBITS+2
        lda     row_lo,y
        sta     af_src
        lda     row_hi,y
        sta     af_src+1
        lda     cp_x0+1
        lsr     a
        lda     cp_x0
        ror     a
        clc
        adc     af_src
        sta     af_src
        bcc     :+
        inc     af_src+1
:       lda     C_TMP
        and     #1
        bne     :+
        lda     af_src
        clc
        adc     #3
        sta     af_src
        bcc     :+
        inc     af_src+1
:       stz     af_bank
        lda     #<glyph_buf
        sta     af_dst
        lda     #>glyph_buf
        sta     af_dst+1
        lda     #1
        sta     af_len
        sta     af_dstride
        lda     #SHR_ROW
        sta     af_sstride
        stz     af_sstride+1
        lda     #7
        sta     af_rows
        jsr     aux_fetch_rows
        lda     #COL_PANEL*$11
        jsr     fill_arena
        ; glyph pointer = font7 + code*7
        lda     TEMP
        asl     a
        asl     a
        asl     a
        sec
        sbc     TEMP
        clc
        adc     #<font7
        sta     C_PTR
        lda     #0
        adc     #>font7
        sta     C_PTR+1
        lda     #<ARENA
        sta     V_PTR
        lda     #>ARENA
        sta     V_PTR+1
        ldx     #0                      ; row
@row:   txa
        tay
        lda     (C_PTR),y               ; bit 7 = leftmost pixel
        sta     TEMP2
        lda     C_TMP
        and     #1
        beq     @edge_even
        lda     glyph_buf,x
        and     #$F0
        ora     #COL_PANEL
        ldy     #0
        sta     (V_PTR),y
        bra     @edge_done
@edge_even:
        lda     glyph_buf,x
        and     #$0F
        ora     #(COL_PANEL*$10)
        ldy     #3
        sta     (V_PTR),y
@edge_done:
        lda     C_TMP
        and     #1
        sta     glyph_idx               ; pixel index in the arena row
        ldy     #8
@pix:   asl     TEMP2
        bcc     @clear
        ; pixel glyph_idx: byte = idx/2, high nibble when even
        lda     glyph_idx
        lsr     a
        phy
        tay
        bcs     @low
        lda     (V_PTR),y
        and     #$0F
        ora     text_hi
        sta     (V_PTR),y
        bra     @done_pix
@low:   lda     (V_PTR),y
        and     #$F0
        ora     text_lo
        sta     (V_PTR),y
@done_pix:
        ply
@clear: inc     glyph_idx
        dey
        bne     @pix
        lda     V_PTR
        clc
        adc     #4
        sta     V_PTR
        bcc     :+
        inc     V_PTR+1
:       inx
        cpx     #7
        bcc     @row
        ; copy: 4 bytes x 7 rows at x & ~1
        lda     CHARBITS+2
        sta     cp_y0
        lda     #7
        sta     cp_rows
        jmp     copy_arena

.segment "BSS"
glyph_idx: .res 1
text_hi: .res 1                 ; text colour in the high nibble
text_lo: .res 1                 ; and in the low nibble
.segment "CODE"

; set the text colour (A) -- also called at start-up
.export set_text_color
set_text_color:
        and     #$0F
        sta     text_color
        sta     text_lo
        asl     a
        asl     a
        asl     a
        asl     a
        sta     text_hi
        rts

PRINT:
        sta     C_PTR
        stx     C_PTR+1
        ldy     #0
@next:  lda     (C_PTR),y
        bmi     @last
        sty     YTEMP
        phy
        lda     C_PTR
        pha
        lda     C_PTR+1
        pha
        lda     (C_PTR),y
        jsr     PRCHAR
        pla
        sta     C_PTR+1
        pla
        sta     C_PTR
        ply
        iny
        bne     @next
@last:  and     #$7F
        jmp     PRCHAR

; the world screen's QUIT: text and the handler (pops DOMENU's return and
; returns from WORLDSTART, as the original's WQUIT did)
DRAWQUIT:
        lda     #3
        ldx     #26
        ldy     #178
        jsr     CHARTO
        lda     #<QUITMSG
        ldx     #>QUITMSG
        jmp     PRINT

WQUIT:
        pla
        pla
        rts
