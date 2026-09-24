; Pinball Construction Set for the Appletini -- the table renderer.
;
; The screen is a function of the state (docs/DESIGN.md section 4). The
; upstream's draw calls become dirty rectangles; rd_render re-renders each
; dirty rectangle of the table (x 0..153, y 0..191) from:
;   1. the polygon database: the border object's colour outside its
;      spans, black inside, then every span record of the row in object
;      order (the span records are the collision geometry, so what is
;      drawn is what the ball hits);
;   2. the overlay layer (magnifier pixel edits) in RamWorks bank 1,
;      only for rows whose tiles hold edits;
;   3. the library objects' sprites at their L-record positions, balls at
;      their live positions during play, drop-target marks;
;   4. vertex dots, the floating object's spans (the object being
;      dragged), wires, highlight frames;
; into the arena, band by band (ARENA_ROWS rows), and copies each band to
; the SHR memory. The cursor (save-under) is hidden before any SHR write
; and shown again at the end of the frame.
;
; The panel (x >= 154) is drawn in immediate mode by panel_sprite and
; panel_fill; nothing there is ever erased except by drawing the panel
; colour over it.
;
; Zero page: the ZEROPAGE variables below and video.s's V_*; the upstream
; zero page is never touched (the object walk uses its own pointers), so
; the editor's state survives a render in the middle of a drag.

.setcpu "65C02"
.include "pcs.inc"
.include "assets.inc"
.macpack longbranch

.export rd_init, rd_mark, rd_mark_all, rd_mark_record, rd_render, rd_frame
.export rd_ax0, rd_ay0, rd_ax1, rd_ay1, rd_flags, rd_color, rd_count
.export cur_set, cur_move, cur_hide, cur_show, cur_x, cur_y, cur_id, cur_want
.export ov_tiles, ov_enabled
.export panel_sprite, panel_fill, panel_frame, ps_id, ps_x, ps_y
.export pf_x0, pf_y0, pf_x1, pf_y1, pf_color
.export float_clear, float_add, hl_toggle, wire_toggle, wire_clear
.export fl_n, wr_n, ov_tiles, ov_enabled
.export DOBAR, POLYPOINTS, SETCOLOR, SETCLR3
.export PORT_DRAWOBJ, PORT_REMOVEPOLY, PORT_DRAWDISPLAY, OBJREPAINT, FLOATCLEAR
.export DRAWPOINTS, DRAWPOLYS
.exportzp R_A, R_B, R_C

.import blit_sprite, sprite_bank, copy_arena, fill_arena, aux_fetch_rows
.import bl_id, bl_x, bl_y, bl_cx0, bl_cx1, bl_cy0, bl_cy1
.import arena_stride, cp_x0, cp_y0, cp_w, cp_rows, cp_count
.import af_bank, af_src, af_dst, af_len, af_rows, af_sstride, af_dstride
.import row_lo, row_hi, masktab
.importzp V_SRC, V_DST, V_REC, V_TMP, V_PTR
.import spr_dir, spr_w, spr_h, spr_hoty, spr_bank
.import PBDATA, PBDX, PPAK_GETBOUNDS, PPAK_DRAWOBJ, PPAK_REMOVEPOLY, PPAK_DRAWDISPLAY
.import SLEEPERS
.import PBBASE

RD_MAX    = 32                  ; dirty rectangles per frame
FL_MAX    = 128                 ; floating spans
WR_MAX    = 18                  ; wires
HL_MAX    = 8                   ; highlighted rectangles
OV_ROW_BYTES = TABLE_BYTES
OV_BANK   = 1
RD_HIDEPOLYS = $80              ; rd_flags
RD_POINTS    = $40
RD_INPLAY    = $20
RD_SLEEPERS  = $10

; ---------------------------------------------------------------------------
.segment "ZEROPAGE"
R_OBJ:   .res 2                 ; object record walk
R_ROW:   .res 2                 ; span record pointer of the current row
R_DST:   .res 2                 ; arena row pointer
R_TMP:   .res 2
R_N:     .res 1                 ; object index
R_CNT:   .res 1
R_X0:    .res 1                 ; rectangle being rendered, table pixels
R_X1:    .res 1
R_Y0:    .res 1
R_Y1:    .res 1
R_Y:     .res 1                 ; current row
R_A:     .res 1
R_B:     .res 1
R_C:     .res 1
R_D:     .res 2                 ; fill_span scratch (R_TMP is its callers')

; ---------------------------------------------------------------------------
.segment "BSS"
rd_ax0:  .res 1                 ; rd_mark inputs (table pixels, inclusive)
rd_ay0:  .res 1
rd_ax1:  .res 1
rd_ay1:  .res 1
rd_flags: .res 1
rd_color: .res 1                ; SETCOLOR's colour (0..15, $10 = inviso)
rd_count: .res 1                ; rectangles rendered by the last rd_render
rr_idx:  .res 1                 ; rd_render's rectangle index
dr_x0:   .res RD_MAX
dr_x1:   .res RD_MAX
dr_y0:   .res RD_MAX
dr_y1:   .res RD_MAX
dr_n:    .res 1
dr_all:  .res 1                 ; whole table dirty
objcolor: .res 128              ; per object: palette index, $10 = paint nothing
fl_y:    .res FL_MAX            ; floating spans
fl_x1:   .res FL_MAX
fl_x2:   .res FL_MAX
fl_c:    .res FL_MAX
fl_n:    .res 1
fl_bx0:  .res 1                 ; their bounding box (valid when fl_n > 0)
fl_bx1:  .res 1
fl_by0:  .res 1
fl_by1:  .res 1
wr_x1:   .res WR_MAX            ; wires: (x1,y1) -> (mx,y1) -> (mx,y2) -> (160,y2)
wr_y1:   .res WR_MAX
wr_mx:   .res WR_MAX
wr_y2:   .res WR_MAX
wr_n:    .res 1
hl_lo:   .res HL_MAX            ; highlighted rectangle records (6-byte records)
hl_hi:   .res HL_MAX
hl_n:    .res 1
ov_tiles: .res 72               ; 24 tile rows x 3 bytes (20 tiles of 8x8 used): bit set = edits
ov_enabled: .res 1
ov_row:  .res OV_ROW_BYTES      ; one fetched overlay row
cur_id:  .res 1
cur_x:   .res 2
cur_y:   .res 1
cur_vis: .res 1                 ; bit 7: the cursor is on the screen
cur_want: .res 1                ; bit 7: show it at the end of the frame
cur_sx:  .res 2                 ; where the save-under was taken (even x)
cur_sy:  .res 1
cur_sw:  .res 1                 ; bytes per row saved
cur_sh:  .res 1                 ; rows saved
cur_save: .res 12*16            ; up to 16 rows of 12 bytes (a 22-px cursor)
ps_id:   .res 1                 ; panel_sprite inputs
ps_x:    .res 2
ps_y:    .res 1
pf_x0:   .res 2                 ; panel_fill / panel_frame inputs (screen pixels)
pf_y0:   .res 1
pf_x1:   .res 2
pf_y1:   .res 1
pf_color: .res 1
pf_band: .res 1                 ; panel_fill rows per band
band_y0: .res 1
band_y1: .res 1
sl_cnt:  .res 1                 ; SLEEPCNT copied before ALTZP goes on

; ---------------------------------------------------------------------------
.segment "CODE"

rd_init:
        stz     dr_n
        stz     dr_all
        stz     fl_n
        stz     wr_n
        stz     hl_n
        stz     rd_flags
        stz     cur_vis
        stz     cur_want
        stz     ov_enabled
        ldx     #71
:       stz     ov_tiles,x
        dex
        bpl     :-
        rts

; ---------------------------------------------------------------------------
; rd_mark: add the rectangle rd_ax0..rd_ax1 x rd_ay0..rd_ay1 (table
; pixels, inclusive) to the dirty list. Clipped to the table; x0 rounded
; down to even, x1 up to odd. A full list marks the whole table.
; Preserves X and Y.
; ---------------------------------------------------------------------------
rd_mark:
        phx
        phy
        lda     rd_ax1
        cmp     #TABLE_W
        bcc     :+
        lda     #TABLE_W-1
:       ora     #1
        sta     rd_ax1
        lda     rd_ay1
        cmp     #TABLE_H
        bcc     :+
        lda     #TABLE_H-1
:       sta     rd_ay1
        lda     rd_ax0
        and     #$FE
        sta     rd_ax0
        cmp     rd_ax1
        bcs     @done                   ; empty or off the table
        lda     rd_ay0
        cmp     rd_ay1
        beq     :+
        bcs     @done
:       ldx     dr_n
        cpx     #RD_MAX
        bcc     :+
        lda     #$80
        sta     dr_all
        bra     @done
:       lda     rd_ax0
        sta     dr_x0,x
        lda     rd_ax1
        sta     dr_x1,x
        lda     rd_ay0
        sta     dr_y0,x
        lda     rd_ay1
        sta     dr_y1,x
        inc     dr_n
@done:  ply
        plx
        rts

rd_mark_all:
        lda     #$80
        sta     dr_all
        rts

; rd_mark_record: A/X = a 7-byte bitmap record (sprite pointer, y, x lo,
; x hi, h, w). Marks the sprite's box (size from the sprite tables, y
; less the sprite's hot y). Records in the panel (x >= 154) are ignored.
rd_mark_record:
        sta     R_TMP
        stx     R_TMP+1
        ldy     #4
        lda     (R_TMP),y
        bne     @done                   ; x >= 256: panel
        dey
        lda     (R_TMP),y
        cmp     #PANEL_X
        bcs     @done
        sta     rd_ax0
        jsr     record_sprite_id        ; X = id (or $FF)
        cpx     #$FF
        beq     @done
        ; the box comes from the record: RUN's HBALL/VBALL records cover
        ; the ball's old and new position (6 wide or 6 tall)
        ldy     #L_W
        lda     (R_TMP),y
        clc
        adc     rd_ax0
        dec     a
        sta     rd_ax1
        ldy     #L_Y
        lda     (R_TMP),y
        sec
        sbc     spr_hoty,x
        bcs     :+                      ; (y is unsigned: test the borrow)
        lda     #0
:       sta     rd_ay0
        ldy     #L_H
        lda     (R_TMP),y
        clc
        adc     rd_ay0
        dec     a
        sta     rd_ay1
        jsr     rd_mark
@done:  rts

; record_sprite_id: R_TMP = record; X = sprite id from its pointer
; (pointer - spr_dir) / 4, or $FF when the pointer is not a directory entry.
record_sprite_id:
        ldy     #0
        lda     (R_TMP),y
        sec
        sbc     #<spr_dir
        sta     R_A
        iny
        lda     (R_TMP),y
        sbc     #>spr_dir
        lsr     a
        ror     R_A
        lsr     a
        ror     R_A                   ; (sets Z from R_A, not A)
        cmp     #0
        bne     @bad
        ldx     R_A
        cpx     #SPR_COUNT
        bcs     @bad
        rts
@bad:   ldx     #$FF
        rts

; ---------------------------------------------------------------------------
; The upstream hooks
; ---------------------------------------------------------------------------

; SETCOLOR: Y = FILLCOLOR (0..15 palette index, $10 inviso).
SETCOLOR:
        sty     rd_color
SETCLR3:
        rts

; POLYPOINTS: vertex dots are derived at render time.
POLYPOINTS:
        rts

; DOBAR: A and X = the two ends of a span (inclusive, either order) on
; row SCANLINE in the colour rd_color. Table spans in merge mode are
; already in the database; in no-merge mode they are the floating object.
; Panel spans (the kit's polygon icons) are drawn at once.
DOBAR:
        cmp     #PANEL_X
        bcs     @panel
        cpx     #PANEL_X
        bcs     @panel
        bit     SCANMODE
        bpl     @done                   ; merge mode: the database has it
        jmp     float_add
@panel: ; a panel span: fill the row segment. An object of the database
        ; (one being dragged over the kit) draws nothing there: the panel
        ; is immediate mode and the original's XOR erase has no equivalent
        pha
        lda     OBJ+1
        cmp     #>PBBASE
        bcs     @skip
        pla
        pha
        cpx     #PANEL_X
        bcs     :+
        ldx     #PANEL_X
:       pla
        cmp     #PANEL_X
        bcs     :+
        lda     #PANEL_X
:       ; order the ends
        stx     R_A
        cmp     R_A
        bcc     :+
        pha
        txa
        sta     R_B
        pla
        sta     R_A
        lda     R_B
:       sta     pf_x0
        stz     pf_x0+1
        lda     R_A
        sta     pf_x1
        stz     pf_x1+1
        lda     SCANLINE
        sta     pf_y0
        sta     pf_y1
        lda     rd_color
        cmp     #16
        bcs     @done                   ; inviso
        sta     pf_color
        jmp     panel_fill
@skip:  pla
@done:  rts

; float_add: A, X = span ends on row SCANLINE, colour rd_color.
float_add:
        ldy     rd_color
        cpy     #16
        bcs     @done
        stx     R_A
        cmp     R_A
        bcc     :+
        pha
        lda     R_A
        sta     R_B
        pla
        sta     R_A
        lda     R_B                     ; A = min, R_A = max
:       ldx     fl_n
        cpx     #FL_MAX
        bcs     @done                   ; the preview is partial: acceptable
        sta     fl_x1,x
        lda     R_A
        sta     fl_x2,x
        lda     SCANLINE
        sta     fl_y,x
        tya
        sta     fl_c,x
        ; bounding box
        cpx     #0
        bne     @grow
        lda     fl_x1,x
        sta     fl_bx0
        lda     fl_x2,x
        sta     fl_bx1
        lda     SCANLINE
        sta     fl_by0
        sta     fl_by1
        bra     @count
@grow:  lda     fl_x1,x
        cmp     fl_bx0
        bcs     :+
        sta     fl_bx0
:       lda     fl_x2,x
        cmp     fl_bx1
        bcc     :+
        sta     fl_bx1
:       lda     SCANLINE
        cmp     fl_by0
        bcs     :+
        sta     fl_by0
:       lda     SCANLINE
        cmp     fl_by1
        bcc     :+
        sta     fl_by1
:
@count: inc     fl_n
@done:  rts

; float_clear: forget the floating spans; their box becomes dirty.
float_clear:
FLOATCLEAR:
        lda     fl_n
        beq     @done
        stz     fl_n
        lda     fl_bx0
        sta     rd_ax0
        lda     fl_bx1
        sta     rd_ax1
        lda     fl_by0
        sta     rd_ay0
        lda     fl_by1
        sta     rd_ay1
        jsr     rd_mark
@done:  rts

; mark_object: the current object's bounding box (polygon, and the sprite
; box of a library object) becomes dirty. Uses PARAM+0..3.
mark_object:
        jsr     PPAK_GETBOUNDS          ; PARAM: minY, maxY, minX, maxX
        lda     PARAM+2
        sta     rd_ax0
        lda     PARAM+3
        sta     rd_ax1
        lda     PARAM
        sta     rd_ay0
        lda     PARAM+1
        sta     rd_ay1
        jsr     rd_mark
        lda     OBJID
        cmp     #OBJ_LIBOBJ
        bne     @done
        lda     LBASE
        ldx     LBASE+1
        jmp     rd_mark_record
@done:  rts

; PORT_DRAWOBJ: the editor's draw/erase of the current object.
PORT_DRAWOBJ:
        jsr     float_clear
        jsr     mark_object
        jmp     PPAK_DRAWOBJ

PORT_REMOVEPOLY:
        jsr     float_clear
        jsr     mark_object
        jmp     PPAK_REMOVEPOLY

PORT_DRAWDISPLAY:
        stz     fl_n
        jsr     rd_mark_all
        jmp     PPAK_DRAWDISPLAY

OBJREPAINT:
        jmp     mark_object

; DRAWPOINTS (EDIT): toggle the vertex dots of every polygon.
DRAWPOINTS:
        lda     rd_flags
        eor     #RD_POINTS
        sta     rd_flags
        jmp     rd_mark_all

; DRAWPOLYS (WIRE): toggle the polygons on and off (the wiring kit shows
; only the parts and the wires).
DRAWPOLYS:
        lda     rd_flags
        eor     #RD_HIDEPOLYS
        sta     rd_flags
        jmp     rd_mark_all

; hl_toggle: A/X = a 6-byte rectangle record; toggles its highlight frame.
; Table rectangles are rendered; panel ones are drawn at once.
hl_toggle:
        sta     R_TMP
        stx     R_TMP+1
        ldx     hl_n
        beq     @add
@find:  dex
        lda     hl_lo,x
        cmp     R_TMP
        bne     :+
        lda     hl_hi,x
        cmp     R_TMP+1
        beq     @remove
:       cpx     #0
        bne     @find
@add:   ldx     hl_n
        cpx     #HL_MAX
        bcs     @done
        lda     R_TMP
        sta     hl_lo,x
        lda     R_TMP+1
        sta     hl_hi,x
        inc     hl_n
        lda     #COL_HILITE
        bra     @draw
@remove:
        ; close the gap
        dec     hl_n
:       cpx     hl_n
        beq     :+
        lda     hl_lo+1,x
        sta     hl_lo,x
        lda     hl_hi+1,x
        sta     hl_hi,x
        inx
        bra     :-
:       lda     #COL_PANEL
@draw:  sta     pf_color
        jsr     rect_to_pf
        lda     pf_x0+1
        bne     @panel
        lda     pf_x0
        cmp     #PANEL_X
        bcs     @panel
        ; a table rectangle: re-render it
        lda     pf_x0
        sta     rd_ax0
        lda     pf_x1
        sta     rd_ax1
        lda     pf_y0
        sta     rd_ay0
        lda     pf_y1
        sta     rd_ay1
        jmp     rd_mark
@panel: jmp     panel_frame
@done:  rts

; rect_to_pf: R_TMP = rectangle record (top, x lo, x hi, height-1, width
; lo, width hi) -> pf_x0/y0/x1/y1 (inclusive).
rect_to_pf:
        ldy     #0
        lda     (R_TMP),y
        sta     pf_y0
        iny
        lda     (R_TMP),y
        sta     pf_x0
        iny
        lda     (R_TMP),y
        sta     pf_x0+1
        iny
        lda     (R_TMP),y
        clc
        adc     pf_y0
        sta     pf_y1
        iny
        lda     (R_TMP),y
        clc
        adc     pf_x0
        sta     pf_x1
        iny
        lda     (R_TMP),y
        adc     pf_x0+1
        sta     pf_x1+1
        rts

; wire_toggle: R_A = x1, R_B = y1 (the object's top-right corner), R_C =
; y2 (the gate contact row); mx = (x1 + 160) / 2. An identical wire is
; removed, otherwise the wire is added. The table part is rendered; the
; panel part (x 154..160 of row y2) is drawn at once.
wire_toggle:
        lda     R_A
        clc
        adc     #160
        ror     a                       ; (x1 + 160) / 2, carry from the add
        sta     R_TMP
        ldx     wr_n
        beq     @add
@find:  dex
        lda     wr_x1,x
        cmp     R_A
        bne     :+
        lda     wr_y1,x
        cmp     R_B
        bne     :+
        lda     wr_y2,x
        cmp     R_C
        beq     @remove
:       cpx     #0
        bne     @find
@add:   ldx     wr_n
        cpx     #WR_MAX
        jcs     @done
        lda     R_A
        sta     wr_x1,x
        lda     R_B
        sta     wr_y1,x
        lda     R_TMP
        sta     wr_mx,x
        lda     R_C
        sta     wr_y2,x
        inc     wr_n
        lda     #COL_WHITE
        bra     @draw
@remove:
        dec     wr_n
:       cpx     wr_n
        beq     :+
        lda     wr_x1+1,x
        sta     wr_x1,x
        lda     wr_y1+1,x
        sta     wr_y1,x
        lda     wr_mx+1,x
        sta     wr_mx,x
        lda     wr_y2+1,x
        sta     wr_y2,x
        inx
        bra     :-
:       lda     #COL_PANEL
@draw:  sta     pf_color
        ; panel part: row y2, x 154..160
        lda     #PANEL_X
        sta     pf_x0
        stz     pf_x0+1
        lda     #160
        sta     pf_x1
        stz     pf_x1+1
        lda     R_C
        sta     pf_y0
        sta     pf_y1
        jsr     panel_fill
        ; table part: the box x1..153, min(y1,y2)..max
        lda     R_A
        sta     rd_ax0
        lda     #TABLE_W-1
        sta     rd_ax1
        lda     R_B
        cmp     R_C
        bcc     :+
        lda     R_C
        sta     rd_ay0
        lda     R_B
        sta     rd_ay1
        jmp     rd_mark
:       sta     rd_ay0
        lda     R_C
        sta     rd_ay1
        jmp     rd_mark
@done:  rts

wire_clear:
        stz     wr_n
        jmp     rd_mark_all

; ---------------------------------------------------------------------------
; rd_render: render every dirty rectangle and copy it to the screen. The
; cursor must be hidden (rd_frame does that).
; ---------------------------------------------------------------------------
rd_render:
        stz     rd_count
        bit     dr_all
        bpl     :+
        stz     dr_all
        stz     dr_n
        stz     rd_ax0
        stz     rd_ay0
        lda     #TABLE_W-1
        sta     rd_ax1
        lda     #TABLE_H-1
        sta     rd_ay1
        jsr     rd_mark
:       lda     dr_n
        jeq     @done
        jsr     build_objcolor
        lda     SLEEPCNT
        sta     sl_cnt
        jsr     merge_rects
        ldx     #0
@rect:  stx     rr_idx                  ; (R_N belongs to the passes)
        lda     dr_x0,x
        sta     R_X0
        lda     dr_x1,x
        sta     R_X1
        lda     dr_y0,x
        sta     R_Y0
        lda     dr_y1,x
        sta     R_Y1
        jsr     render_rect
        inc     rd_count
        ldx     rr_idx
        inx
        cpx     dr_n
        bcc     @rect
        stz     dr_n
@done:  rts

; merge_rects: join rectangles that overlap or touch (repeat until stable).
merge_rects:
@again: ldx     #0
@outer: cpx     dr_n
        jcs     @stable
        txa
        tay
        iny
@pair:  cpy     dr_n
        bcs     @nextx
        ; overlap or touch: x0[y] <= x1[x]+1, x0[x] <= x1[y]+1, same for y
        lda     dr_x1,x
        inc     a
        cmp     dr_x0,y
        bcc     @nexty
        lda     dr_x1,y
        inc     a
        cmp     dr_x0,x
        bcc     @nexty
        lda     dr_y1,x
        inc     a
        cmp     dr_y0,y
        bcc     @nexty
        lda     dr_y1,y
        inc     a
        cmp     dr_y0,x
        bcc     @nexty
        ; union into x
        lda     dr_x0,y
        cmp     dr_x0,x
        bcs     :+
        sta     dr_x0,x
:       lda     dr_x1,y
        cmp     dr_x1,x
        bcc     :+
        sta     dr_x1,x
:       lda     dr_y0,y
        cmp     dr_y0,x
        bcs     :+
        sta     dr_y0,x
:       lda     dr_y1,y
        cmp     dr_y1,x
        bcc     :+
        sta     dr_y1,x
:       ; remove y: move the last rectangle into its slot
        dec     dr_n
        lda     dr_n
        sta     R_B
        cpy     R_B
        beq     @again
        phx
        ldx     R_B
        lda     dr_x0,x
        sta     dr_x0,y
        lda     dr_x1,x
        sta     dr_x1,y
        lda     dr_y0,x
        sta     dr_y0,y
        lda     dr_y1,x
        sta     dr_y1,y
        plx
        jmp     @again
@nexty: iny
        jmp     @pair
@nextx: inx
        jmp     @outer
@stable: rts

; build_objcolor: objcolor[i] = the palette index of object i, $10 for
; nothing to paint (black, inviso).
build_objcolor:
        lda     #<PBDATA
        sta     R_OBJ
        lda     #>PBDATA
        sta     R_OBJ+1
        lda     PBDATA
        sta     R_CNT                   ; object count
        beq     @done
        ; records start at PBDATA + 1 + count
        clc
        adc     #1
        adc     R_OBJ
        sta     R_OBJ
        bcc     :+
        inc     R_OBJ+1
:       ldx     #0
@obj:   ldy     #1
        lda     (R_OBJ),y
        beq     @none
        cmp     #16
        bcc     :+
@none:  lda     #$10
:       sta     objcolor,x
        jsr     next_record
        inx
        cpx     R_CNT
        bcc     @obj
@done:  rts

; next_record: R_OBJ += size of object X (from PBDATA's size table).
next_record:
        lda     PBDATA+1,x
        clc
        adc     R_OBJ
        sta     R_OBJ
        bcc     :+
        inc     R_OBJ+1
:       rts

; ---------------------------------------------------------------------------
; render_rect: R_X0..R_X1 x R_Y0..R_Y1 (x0 even, x1 odd), in bands.
; ---------------------------------------------------------------------------
render_rect:
        lda     R_X1
        sec
        sbc     R_X0
        lsr     a
        inc     a
        sta     arena_stride            ; bytes per row
        sta     cp_w
        lda     R_X0
        sta     cp_x0
        sta     bl_cx0
        stz     cp_x0+1
        stz     bl_cx0+1
        lda     R_X1
        sta     bl_cx1
        stz     bl_cx1+1
        lda     R_Y0
        sta     band_y0
@band:  lda     band_y0
        clc
        adc     #ARENA_ROWS-1
        cmp     R_Y1
        bcc     :+
        lda     R_Y1
:       sta     band_y1
        lda     band_y0
        sta     bl_cy0
        sta     cp_y0
        lda     band_y1
        sta     bl_cy1
        sec
        sbc     band_y0
        inc     a
        sta     cp_rows
        jsr     render_band
        jsr     copy_arena
        lda     band_y1
        cmp     R_Y1
        bcs     @done
        inc     a
        sta     band_y0
        bra     @band
@done:  rts

; render_band: rows band_y0..band_y1 of the rectangle into the arena.
render_band:
        ; 1. background rows
        lda     #<ARENA
        sta     R_DST
        lda     #>ARENA
        sta     R_DST+1
        lda     band_y0
        sta     R_Y
        jsr     row_addr_init
@row:   jsr     render_row
        jsr     row_addr_next
        lda     R_DST
        clc
        adc     arena_stride
        sta     R_DST
        bcc     :+
        inc     R_DST+1
:       inc     R_Y
        lda     R_Y
        cmp     band_y1
        bcc     @row
        beq     @row
        ; 2. sprites
        jsr     sprite_pass
        ; 3. dots, floating spans, wires, highlights
        jsr     dots_pass
        jsr     float_pass
        jsr     wire_pass
        jmp     hl_pass

; ---------------------------------------------------------------------------
; Span records of a row: the gap buffer of the upstream. Rows 0..MIDY end
; at MIDBTM (contiguous), rows MIDY+1..191 start at MIDTOP. row_addr_init
; computes the address of row R_Y (as PPAK's GETSCAN does), row_addr_next
; advances to R_Y+1.
; ---------------------------------------------------------------------------
row_addr_init:
        lda     R_Y
        cmp     MIDY
        beq     @below
        bcc     @below
        ; above: MIDTOP + sum PBDX[MIDY+1 .. y-1]
        lda     MIDTOP
        sta     R_ROW
        lda     MIDTOP+1
        sta     R_ROW+1
        ldy     MIDY
        iny
@up:    cpy     R_Y
        bcs     @done
        lda     PBDX,y
        clc
        adc     R_ROW
        sta     R_ROW
        bcc     :+
        inc     R_ROW+1
:       iny
        bra     @up
@below: ; MIDBTM - sum PBDX[y .. MIDY]
        lda     MIDBTM
        sta     R_ROW
        lda     MIDBTM+1
        sta     R_ROW+1
        ldy     R_Y
@down:  lda     R_ROW
        sec
        sbc     PBDX,y
        sta     R_ROW
        bcs     :+
        dec     R_ROW+1
:       cpy     MIDY
        beq     @done
        iny
        bra     @down
@done:  rts

row_addr_next:
        ldy     R_Y
        cpy     MIDY
        bne     :+
        ; leaving the bottom chunk
        lda     MIDTOP
        sta     R_ROW
        lda     MIDTOP+1
        sta     R_ROW+1
        rts
:       lda     PBDX,y
        clc
        adc     R_ROW
        sta     R_ROW
        bcc     :+
        inc     R_ROW+1
:       rts

; ---------------------------------------------------------------------------
; render_row: row R_Y, pixels R_X0..R_X1 into the arena row at R_DST.
; ---------------------------------------------------------------------------
render_row:
        ; border colour outside the border polygon: objcolor[0]
        lda     objcolor
        bit     rd_flags
        bpl     :+
        lda     #$10                    ; polygons hidden
:       cmp     #16
        bcc     :+
        lda     #0
:       jsr     fill_row_all
        bit     rd_flags
        bmi     @overlay                ; polygons hidden: no spans
        ldy     R_Y
        lda     PBDX,y
        beq     @overlay
        lsr     a
        lsr     a
        sta     R_CNT                   ; records
        lda     R_ROW
        sta     R_TMP
        lda     R_ROW+1
        sta     R_TMP+1
@rec:   ldy     #1
        lda     (R_TMP),y
        tax                             ; object index
        lda     objcolor,x
        cpx     #0
        bne     :+
        lda     #0                      ; inside the border: black
:       cmp     #16
        bcs     @skip
        sta     R_C
        ldy     #0
        lda     (R_TMP),y
        sta     R_A
        ldy     #2
        lda     (R_TMP),y
        sta     R_B
        jsr     fill_span
@skip:  lda     R_TMP
        clc
        adc     #4
        sta     R_TMP
        bcc     :+
        inc     R_TMP+1
:       dec     R_CNT
        bne     @rec
@overlay:
        lda     ov_enabled
        beq     @done
        jsr     overlay_row
@done:  rts

; fill_row_all: fill the arena row with colour A.
fill_row_all:
        sta     R_C
        asl     a
        asl     a
        asl     a
        asl     a
        ora     R_C
        ldy     arena_stride
        dey
:       sta     (R_DST),y
        dey
        bpl     :-
        rts

; fill_span: pixels R_A..R_B (inclusive, table x) of the arena row at
; R_DST with colour R_C, clipped to R_X0..R_X1.
fill_span:
        lda     R_A
        cmp     R_X0
        bcs     :+
        lda     R_X0
:       sta     R_A
        lda     R_B
        cmp     R_X1
        bcc     :+
        beq     :+
        lda     R_X1
:       sta     R_B
        cmp     R_A
        bcc     @done
        ; byte offsets in the row: (x - x0) / 2, x0 even
        lda     R_A
        sec
        sbc     R_X0
        lsr     a
        tay                             ; first byte
        lda     R_B
        sec
        sbc     R_X0
        lsr     a
        sta     R_D                   ; last byte
        lda     R_C
        asl     a
        asl     a
        asl     a
        asl     a
        ora     R_C
        sta     R_D+1                 ; colour byte
        ; masks: an odd start keeps the left pixel of the first byte, an
        ; even end keeps the right pixel of the last byte
        cpy     R_D
        bne     @multi
        lda     #$FF
        sta     R_C
        lda     R_A
        and     #1
        beq     :+
        lda     #$0F
        sta     R_C
:       lda     R_B
        and     #1
        bne     :+
        lda     R_C
        and     #$F0
        sta     R_C
:       jsr     @masked
        bra     @done
@multi: lda     R_A
        and     #1
        beq     @left_done
        lda     #$0F
        sta     R_C
        jsr     @masked
        iny
@left_done:
        ; full bytes up to (not including) the last byte
@full:  cpy     R_D
        bcs     @last
        lda     R_D+1
        sta     (R_DST),y
        iny
        bra     @full
@last:  lda     R_B
        and     #1
        bne     @last_full
        lda     #$F0
        sta     R_C
        jmp     @masked
@last_full:
        lda     R_D+1
        sta     (R_DST),y
@done:  rts
; write the colour byte through mask R_C at byte y
@masked:
        lda     R_C
        eor     #$FF
        and     (R_DST),y
        sta     (R_DST),y
        lda     R_D+1
        and     R_C
        ora     (R_DST),y
        sta     (R_DST),y
        rts

; ---------------------------------------------------------------------------
; overlay_row: merge the magnifier's pixel edits of row R_Y into the arena
; row (nibble 0 = no edit). Rows whose tiles hold no edits cost nothing.
; The row is fetched from RamWorks bank 1 through the stack page.
; ---------------------------------------------------------------------------
overlay_row:
        ; tile row = y / 8 -> 3 bytes of ov_tiles; tiles x0/8 .. x1/8
        lda     R_Y
        lsr     a
        lsr     a
        lsr     a
        sta     R_A
        asl     a
        adc     R_A                     ; * 3
        sta     R_B                     ; offset of the tile row's bytes
        lda     R_X0
        lsr     a
        lsr     a
        lsr     a
        sta     R_A                     ; first tile
        lda     R_X1
        lsr     a
        lsr     a
        lsr     a
        sta     R_C                     ; last tile
@t:     lda     R_A
        lsr     a
        lsr     a
        lsr     a
        clc
        adc     R_B
        tay
        lda     ov_tiles,y
        sta     R_TMP
        lda     R_A
        and     #7
        tay
        lda     bitmask,y
        and     R_TMP
        bne     @has
        lda     R_A
        cmp     R_C
        bcs     @none
        inc     R_A
        bra     @t
@has:   ; fetch the row's bytes x0/2 .. x1/2 from bank 1
        ldy     R_Y
        lda     row_lo,y
        sta     af_src
        lda     row_hi,y
        sta     af_src+1
        lda     R_X0
        lsr     a
        clc
        adc     af_src
        sta     af_src
        bcc     :+
        inc     af_src+1
:       lda     #<ov_row
        sta     af_dst
        lda     #>ov_row
        sta     af_dst+1
        lda     arena_stride
        sta     af_len
        lda     #1
        sta     af_rows
        sta     af_bank                 ; OV_BANK
        stz     af_sstride
        stz     af_sstride+1
        stz     af_dstride
        jsr     aux_fetch_rows
        ; merge non-zero nibbles
        ldy     arena_stride
        dey
@m:     lda     ov_row,y
        beq     @n
        tax
        lda     masktab,x
        and     (R_DST),y
        sta     R_C
        txa
        ora     R_C
        sta     (R_DST),y
@n:     dey
        bpl     @m
@none:  rts

bitmask: .byte 1,2,4,8,16,32,64,128

; ---------------------------------------------------------------------------
; sprite_pass: every library object whose sprite box touches the band.
; ALTZP is switched on for the pass (card sprites); the zero page is then
; the auxiliary one, so the walk below sets its pointers after the switch
; and reads everything else from absolute memory.
; ---------------------------------------------------------------------------
sprite_pass:
        sta     ALTZPON
        lda     #<PBDATA
        sta     R_OBJ
        lda     #>PBDATA
        sta     R_OBJ+1
        lda     PBDATA
        sta     R_CNT
        beq     @sleepers
        clc
        adc     #1
        adc     R_OBJ
        sta     R_OBJ
        bcc     :+
        inc     R_OBJ+1
:       ldx     #0
@obj:   stx     R_N
        lda     (R_OBJ)
        cmp     #OBJ_LIBOBJ
        bne     @next
        ; L-record = record + 3 + 2*n
        ldy     #2
        lda     (R_OBJ),y
        asl     a
        adc     #3
        adc     R_OBJ
        sta     R_TMP
        lda     R_OBJ+1
        adc     #0
        sta     R_TMP+1
        jsr     draw_lrecord
@next:  ldx     R_N
        jsr     next_record
        inx
        cpx     R_CNT
        bcc     @obj
@sleepers:
        lda     rd_flags
        and     #RD_INPLAY|RD_SLEEPERS
        cmp     #RD_INPLAY|RD_SLEEPERS
        bne     @done
        lda     sl_cnt
        beq     @done
        sta     R_CNT
        lda     #<SLEEPERS
        sta     R_TMP
        lda     #>SLEEPERS
        sta     R_TMP+1
@sl:    jsr     draw_lrecord
        lda     R_TMP
        clc
        adc     #23
        sta     R_TMP
        bcc     :+
        inc     R_TMP+1
:       dec     R_CNT
        bne     @sl
@done:  sta     ALTZPOFF
        rts

; draw_lrecord: R_TMP = an L-record. Balls in play are drawn at their
; live position unless dead; drop-target banks get their marks.
draw_lrecord:
        ldy     #L_XH
        lda     (R_TMP),y
        bne     @done                   ; x >= 256: a kit icon, not on the table
        jsr     record_sprite_id
        cpx     #$FF
        beq     @done
        stx     bl_id
        ldy     #L_X
        lda     (R_TMP),y
        sta     bl_x
        stz     bl_x+1
        ldy     #L_Y
        lda     (R_TMP),y
        sta     bl_y
        stz     bl_y+1
        cpx     #SPR_BALL_0
        bne     @place
        lda     rd_flags
        and     #RD_INPLAY
        beq     @place
        ; a ball in play: dead balls vanish, live ones move
        ldy     #L_BST
        lda     (R_TMP),y
        bmi     @done
        ldy     #L_X1
        lda     (R_TMP),y
        sta     bl_x
        iny
        lda     (R_TMP),y
        sta     bl_y
@place: ; y -= hot y
        ldx     bl_id
        lda     bl_y
        sec
        sbc     spr_hoty,x
        sta     bl_y
        bcs     :+
        dec     bl_y+1
:       lda     bl_id
        jsr     sprite_bank
        jsr     blit_sprite
        ; drop-target marks
        lda     rd_flags
        and     #RD_INPLAY
        beq     @done
        ldx     bl_id
        cpx     #SPR_DROP1_0
        beq     @drop_h
        cpx     #SPR_DROP2_0
        beq     @drop_v
@done:  rts
@drop_h:
        ; state low nibble: bit 0 = rightmost target (offset 24), bit 3 =
        ; leftmost (offset 0); marks 7x3 at x + 8*i
        ldy     #L_STATE
        lda     (R_TMP),y
        and     #$0F
        sta     R_C
        lda     #3
        sta     R_B                     ; i = 3 - bit
@dh:    lsr     R_C
        bcc     @dh_next
        lda     R_B
        asl     a
        asl     a
        asl     a                       ; 8*i
        ldy     #L_X
        clc
        adc     (R_TMP),y
        sta     bl_x
        ldy     #L_Y
        lda     (R_TMP),y
        sta     bl_y
        lda     #SPR_DROPX_0
        sta     bl_id
        jsr     sprite_bank
        jsr     blit_sprite
@dh_next:
        dec     R_B
        bpl     @dh
        rts
@drop_v:
        ldy     #L_STATE
        lda     (R_TMP),y
        and     #$0F
        sta     R_C
        lda     #3
        sta     R_B                     ; bit 0 = bottom target
@dv:    lsr     R_C
        bcc     @dv_next
        lda     R_B
        asl     a
        asl     a
        asl     a
        ldy     #L_Y
        clc
        adc     (R_TMP),y
        sta     bl_y
        ldy     #L_X
        lda     (R_TMP),y
        sta     bl_x
        lda     #SPR_DROPY_0
        sta     bl_id
        jsr     sprite_bank
        jsr     blit_sprite
@dv_next:
        dec     R_B
        bpl     @dv
        rts

; ---------------------------------------------------------------------------
; dots_pass: 3x3 white dots at (x-1, y-1) of every vertex of every polygon
; whose colour is black, or of every polygon in points mode.
; ---------------------------------------------------------------------------
dots_pass:
        bit     rd_flags
        bmi     @done                   ; wiring kit: no dots
        lda     #<PBDATA
        sta     R_OBJ
        lda     #>PBDATA
        sta     R_OBJ+1
        lda     PBDATA
        sta     R_CNT
        beq     @done
        clc
        adc     #1
        adc     R_OBJ
        sta     R_OBJ
        bcc     :+
        inc     R_OBJ+1
:       ldx     #0
@obj:   stx     R_N
        lda     (R_OBJ)
        cmp     #OBJ_LIBOBJ
        bcs     @next
        ldy     #1
        lda     (R_OBJ),y
        beq     @dots
        lda     rd_flags
        and     #RD_POINTS
        beq     @next
@dots:  ldy     #2
        lda     (R_OBJ),y
        sta     R_C                     ; vertices
        ; vertex i: x at 3+i, y at 3+n+i
        lda     #0
@v:     sta     R_A
        clc
        adc     #3
        tay
        lda     (R_OBJ),y
        sta     R_B                     ; x
        tya
        clc
        adc     R_C
        tay
        lda     (R_OBJ),y               ; y
        jsr     dot
        lda     R_A
        inc     a
        cmp     R_C
        bcc     @v
@next:  ldx     R_N
        jsr     next_record
        inx
        cpx     R_CNT
        bcc     @obj
@done:  rts

; dot: 3x3 at (R_B-1, A-1) clipped to the band: rows A-1..A+1
dot:
        sec
        sbc     #1
        sta     R_Y
        ldx     #3
@row:   lda     R_Y
        cmp     band_y0
        bcc     @skip
        cmp     band_y1
        beq     :+
        bcs     @skip
:       ; arena row
        sec
        sbc     band_y0
        jsr     arena_row_ptr
        lda     R_B
        beq     :+                      ; x = 0: pixels 0..2
        dec     a
:       sta     R_A2
        lda     #COL_WHITE
        sta     R_C2
        ; pixels R_B-1 .. R_B+1
        lda     R_A2
        clc
        adc     #2
        sta     R_B2
        jsr     fill_span_ab
@skip:  inc     R_Y
        dex
        bne     @row
        rts

; arena_row_ptr: A = row index in the band -> R_DST
arena_row_ptr:
        tax
        lda     #<ARENA
        sta     R_DST
        lda     #>ARENA
        sta     R_DST+1
        cpx     #0
        beq     @done
:       lda     R_DST
        clc
        adc     arena_stride
        sta     R_DST
        bcc     :+
        inc     R_DST+1
:       dex
        bne     :--
@done:  rts

; fill_span_ab: R_A2..R_B2 in colour R_C2 (the dot/float/wire callers keep
; R_A/R_B/R_C for their loops)
.segment "BSS"
R_A2:   .res 1
R_B2:   .res 1
R_C2:   .res 1
.segment "CODE"
fill_span_ab:
        lda     R_A
        pha
        lda     R_B
        pha
        lda     R_C
        pha
        lda     R_A2
        sta     R_A
        lda     R_B2
        sta     R_B
        lda     R_C2
        sta     R_C
        jsr     fill_span
        pla
        sta     R_C
        pla
        sta     R_B
        pla
        sta     R_A
        rts

; ---------------------------------------------------------------------------
; float_pass: the floating object's spans that fall in the band.
; ---------------------------------------------------------------------------
float_pass:
        ldx     fl_n
        beq     @done
@span:  dex
        lda     fl_y,x
        cmp     band_y0
        bcc     @next
        cmp     band_y1
        beq     :+
        bcs     @next
:       sec
        sbc     band_y0
        phx
        jsr     arena_row_ptr
        plx
        lda     fl_x1,x
        sta     R_A2
        lda     fl_x2,x
        sta     R_B2
        lda     fl_c,x
        sta     R_C2
        phx
        jsr     fill_span_ab
        plx
@next:  cpx     #0
        bne     @span
@done:  rts

; ---------------------------------------------------------------------------
; wire_pass: 1-pixel wires: (x1,y1)-(mx,y1), (mx,y1)-(mx,y2), (mx,y2)-(153,y2)
; ---------------------------------------------------------------------------
wire_pass:
        ldx     wr_n
        beq     @done
@wire:  dex
        stx     R_N
        lda     #COL_WHITE
        sta     R_C2
        ; horizontal at y1: x1..mx
        lda     wr_y1,x
        ldy     wr_x1,x
        sty     R_A2
        ldy     wr_mx,x
        sty     R_B2
        jsr     hline_band
        ; horizontal at y2: mx..153
        ldx     R_N
        lda     wr_y2,x
        ldy     wr_mx,x
        sty     R_A2
        ldy     #TABLE_W-1
        sty     R_B2
        jsr     hline_band
        ; vertical at mx: min(y1,y2)..max
        ldx     R_N
        lda     wr_mx,x
        sta     R_A2
        sta     R_B2
        lda     wr_y1,x
        cmp     wr_y2,x
        bcc     :+
        lda     wr_y2,x
        sta     R_Y
        lda     wr_y1,x
        bra     @v
:       sta     R_Y
        lda     wr_y2,x
@v:     sta     R_A                     ; last row
@vl:    lda     R_Y
        jsr     hline_band
        lda     R_Y
        cmp     R_A
        bcs     @vdone
        inc     R_Y
        bra     @vl
@vdone: ldx     R_N
        cpx     #0
        bne     @wire
@done:  rts

; hline_band: row A, pixels R_A2..R_B2, colour R_C2, if the row is in the band
hline_band:
        cmp     band_y0
        bcc     @skip
        cmp     band_y1
        beq     :+
        bcs     @skip
:       sec
        sbc     band_y0
        jsr     arena_row_ptr
        jmp     fill_span_ab
@skip:  rts

; ---------------------------------------------------------------------------
; hl_pass: highlight frames of table rectangles.
; ---------------------------------------------------------------------------
hl_pass:
        ldx     hl_n
        beq     @done
@rect:  dex
        stx     R_N
        lda     hl_lo,x
        sta     R_TMP
        lda     hl_hi,x
        sta     R_TMP+1
        jsr     rect_to_pf
        lda     pf_x0+1
        bne     @next
        lda     pf_x0
        cmp     #PANEL_X
        bcs     @next
        lda     #COL_HILITE
        sta     R_C2
        ; top and bottom rows
        lda     pf_x0
        sta     R_A2
        lda     pf_x1
        cmp     #TABLE_W
        bcc     :+
        lda     #TABLE_W-1
:       sta     R_B2
        lda     pf_y0
        jsr     hline_band
        lda     pf_y1
        jsr     hline_band
        ; sides
        lda     pf_y0
        sta     R_Y
@side:  lda     pf_x0
        sta     R_A2
        sta     R_B2
        lda     R_Y
        jsr     hline_band
        lda     pf_x1
        cmp     #TABLE_W
        bcs     :+
        sta     R_A2
        sta     R_B2
        lda     R_Y
        jsr     hline_band
:       lda     R_Y
        cmp     pf_y1
        bcs     @next
        inc     R_Y
        bra     @side
@next:  ldx     R_N
        cpx     #0
        bne     @rect
@done:  rts

; ---------------------------------------------------------------------------
; The cursor: a sprite drawn last with save-under.
; ---------------------------------------------------------------------------
cur_set:                                ; A = sprite id
        sta     cur_id
        rts

cur_move:                               ; A/X = x, Y = y
        sta     cur_x
        stx     cur_x+1
        sty     cur_y
        rts

; cur_hide: restore the bytes under the cursor (if it is on the screen).
cur_hide:
        bit     cur_vis
        bpl     @done
        stz     cur_vis
        lda     cur_sh
        beq     @done
        ; copy cur_save rows back
        lda     cur_sx
        sta     cp_x0
        lda     cur_sx+1
        sta     cp_x0+1
        lda     cur_sy
        sta     cp_y0
        lda     cur_sw
        sta     cp_w
        sta     arena_stride
        lda     cur_sh
        sta     cp_rows
        jsr     save_to_arena
        jsr     copy_arena
@done:  rts

; save_to_arena: cur_save -> arena (cur_sh rows of cur_sw bytes)
save_to_arena:
        lda     cur_sh
        sta     R_CNT
        ldx     #0
        ldy     #0
        lda     #<ARENA
        sta     R_DST
        lda     #>ARENA
        sta     R_DST+1
@row:   ldy     #0
:       lda     cur_save,x
        sta     (R_DST),y
        inx
        iny
        cpy     cur_sw
        bcc     :-
        lda     R_DST
        clc
        adc     cur_sw
        sta     R_DST
        bcc     :+
        inc     R_DST+1
:       dec     R_CNT
        bne     @row
        rts

; cur_show: save the bytes under the cursor and draw it.
cur_show:
        bit     cur_vis
        jmi     @done
        ; box: x from cur_x (even), width = w + 1 pixel for the odd phase
        lda     cur_x
        and     #$FE
        sta     cur_sx
        lda     cur_x+1
        sta     cur_sx+1
        ldx     cur_id
        lda     spr_w,x
        clc
        adc     #2                      ; w + phase rounded up to bytes
        lsr     a
        sta     cur_sw
        ; clip on the right (320 px = 160 bytes)
        lda     cur_sx+1
        lsr     a
        lda     cur_sx
        ror     a                       ; byte column
        sta     R_A
        clc
        adc     cur_sw
        cmp     #SCREEN_W/2
        bcc     :+
        lda     #SCREEN_W/2
        sec
        sbc     R_A
        sta     cur_sw
:       lda     cur_y
        sta     cur_sy
        lda     spr_h,x
        sta     cur_sh
        clc
        adc     cur_y
        cmp     #SCREEN_H
        bcc     :+
        lda     #SCREEN_H
        sec
        sbc     cur_y
        sta     cur_sh
:       lda     cur_sh
        jeq     @done
        lda     cur_sw
        jeq     @done
        ; fetch the rows from the SHR (bank 0)
        ldy     cur_sy
        lda     row_lo,y
        clc
        adc     R_A
        sta     af_src
        lda     row_hi,y
        adc     #0
        sta     af_src+1
        lda     #<cur_save
        sta     af_dst
        lda     #>cur_save
        sta     af_dst+1
        lda     cur_sw
        sta     af_len
        sta     af_dstride
        lda     cur_sh
        sta     af_rows
        stz     af_bank
        lda     #SHR_ROW
        sta     af_sstride
        stz     af_sstride+1
        jsr     aux_fetch_rows
        ; compose: arena = saved bytes, sprite on top
        lda     cur_sw
        sta     arena_stride
        jsr     save_to_arena
        lda     cur_sx
        sta     bl_cx0
        lda     cur_sx+1
        sta     bl_cx0+1
        ; cx1 = cx0 + 2*sw - 1
        lda     cur_sw
        asl     a
        clc
        adc     cur_sx
        sta     bl_cx1
        lda     cur_sx+1
        adc     #0
        sta     bl_cx1+1
        lda     bl_cx1
        bne     :+
        dec     bl_cx1+1
:       dec     bl_cx1
        lda     cur_sy
        sta     bl_cy0
        clc
        adc     cur_sh
        dec     a
        sta     bl_cy1
        lda     cur_id
        sta     bl_id
        lda     cur_x
        sta     bl_x
        lda     cur_x+1
        sta     bl_x+1
        lda     cur_y
        sta     bl_y
        stz     bl_y+1
        sta     ALTZPON                 ; the cursors live in the card too
        lda     cur_id
        jsr     sprite_bank
        jsr     blit_sprite
        sta     ALTZPOFF
        lda     cur_sx
        sta     cp_x0
        lda     cur_sx+1
        sta     cp_x0+1
        lda     cur_sy
        sta     cp_y0
        lda     cur_sw
        sta     cp_w
        lda     cur_sh
        sta     cp_rows
        jsr     copy_arena
        lda     #$80
        sta     cur_vis
@done:  rts

; ---------------------------------------------------------------------------
; rd_frame: hide the cursor, render the dirty rectangles, show the cursor.
; ---------------------------------------------------------------------------
rd_frame:
        jsr     cur_hide
        jsr     rd_render
        bit     cur_want
        bpl     :+
        jsr     cur_show
:       rts

; ---------------------------------------------------------------------------
; Panel primitives (immediate mode). The cursor is hidden first so that
; its save-under never covers what is drawn.
; ---------------------------------------------------------------------------

; panel_sprite: sprite ps_id at (ps_x, ps_y) on a panel-coloured box.
panel_sprite:
        jsr     cur_hide
        ldx     ps_id
        lda     ps_x
        and     #$FE
        sta     bl_cx0
        sta     cp_x0
        lda     ps_x+1
        sta     bl_cx0+1
        sta     cp_x0+1
        lda     spr_w,x
        clc
        adc     #2
        lsr     a
        sta     arena_stride
        sta     cp_w
        asl     a
        clc
        adc     bl_cx0
        sta     bl_cx1
        lda     bl_cx0+1
        adc     #0
        sta     bl_cx1+1
        lda     bl_cx1
        bne     :+
        dec     bl_cx1+1
:       dec     bl_cx1
        lda     ps_y
        sta     bl_cy0
        sta     cp_y0
        clc
        adc     spr_h,x
        dec     a
        sta     bl_cy1
        lda     spr_h,x
        sta     cp_rows
        lda     #COL_PANEL*$11
        jsr     fill_arena
        lda     ps_id
        sta     bl_id
        lda     ps_x
        sta     bl_x
        lda     ps_x+1
        sta     bl_x+1
        lda     ps_y
        sta     bl_y
        stz     bl_y+1
        sta     ALTZPON
        lda     ps_id
        jsr     sprite_bank
        jsr     blit_sprite
        sta     ALTZPOFF
        jmp     copy_arena

; panel_fill: pf_x0..pf_x1 x pf_y0..pf_y1 (screen pixels, inclusive) in
; pf_color. Odd edges are handled with a read of the screen through the
; save-under path: to keep it simple the fill works on whole bytes and
; the callers use even x0 and odd x1 (the layout tool guarantees it for
; rectangles; DOBAR spans of the kit polygons may lose an edge pixel).
panel_fill:
        jsr     cur_hide
        lda     pf_x0
        and     #$FE
        sta     cp_x0
        lda     pf_x0+1
        sta     cp_x0+1
        ; width in bytes = (x1|1 - x0&~1 + 1)/2
        lda     pf_x1
        ora     #1
        sec
        sbc     cp_x0
        sta     R_D
        lda     pf_x1+1
        sbc     cp_x0+1
        lsr     a
        ror     R_D
        lda     R_D
        inc     a
        sta     cp_w
        sta     arena_stride
        ; rows per band: 13 rows of up to 78 bytes fit the 1 KB arena, a
        ; wider fill (the whole panel is 83 bytes) takes 12
        ldx     #ARENA_ROWS
        cmp     #ARENA_SIZE/ARENA_ROWS+1
        bcc     :+
        ldx     #ARENA_SIZE/((SCREEN_W-PANEL_X+1)/2)
:       stx     pf_band
        lda     pf_y0
        sta     cp_y0
        sta     bl_cy0
        lda     pf_y1
        sta     bl_cy1
        sec
        sbc     pf_y0
        inc     a
        sta     cp_rows
        ; rows may exceed the arena: do it in bands
@band:  lda     cp_rows
        cmp     pf_band
        bcc     @last
        beq     @last
        lda     pf_band
        sta     cp_rows
        lda     bl_cy0
        clc
        adc     pf_band
        dec     a
        sta     bl_cy1
        jsr     @one
        lda     bl_cy1
        inc     a
        sta     bl_cy0
        sta     cp_y0
        lda     pf_y1
        sec
        sbc     bl_cy0
        inc     a
        sta     cp_rows
        lda     pf_y1
        sta     bl_cy1
        bra     @band
@last:  jmp     @one
@one:   lda     pf_color
        and     #$0F
        sta     R_D
        asl     a
        asl     a
        asl     a
        asl     a
        ora     R_D
        jsr     fill_arena
        jmp     copy_arena

; panel_frame: a 1-pixel frame around pf_x0..pf_x1 x pf_y0..pf_y1.
panel_frame:
        lda     pf_x0
        pha
        lda     pf_x0+1
        pha
        lda     pf_x1
        pha
        lda     pf_x1+1
        pha
        lda     pf_y0
        pha
        lda     pf_y1
        pha
        ; top
        lda     pf_y0
        sta     pf_y1
        jsr     panel_fill
        ; bottom
        pla
        pha
        sta     pf_y0
        sta     pf_y1
        jsr     panel_fill
        ; left: x0..x0+1 (a whole byte, the fill is byte-wide)
        tsx
        lda     $0102,x                 ; pf_y0 (pushed 2nd from top)
        sta     pf_y0
        lda     $0101,x
        sta     pf_y1
        lda     $0106,x                 ; pf_x0 lo
        sta     pf_x0
        sta     pf_x1
        lda     $0105,x
        sta     pf_x0+1
        sta     pf_x1+1
        jsr     panel_fill
        tsx
        lda     $0104,x                 ; pf_x1 lo
        sta     pf_x0
        sta     pf_x1
        lda     $0103,x
        sta     pf_x0+1
        sta     pf_x1+1
        jsr     panel_fill
        pla
        sta     pf_y1
        pla
        sta     pf_y0
        pla
        sta     pf_x1+1
        pla
        sta     pf_x1
        pla
        sta     pf_x0+1
        pla
        sta     pf_x0
        rts
