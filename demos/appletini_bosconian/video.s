.setcpu "65C02"

; Appletini Bosconian -- SHR video driver (docs/DESIGN.md section 5).
;
; The framebuffer lives in AUX $2000-$9FFF. Every routine here turns RAMWRT
; on, writes only AUX addresses >= $0200 and zero page $20-$4F, then turns
; RAMWRT off before it touches any main-memory variable. C arguments are
; popped from the cc65 stack (popa/popax) before RAMWRT is switched on.
;
; Sprite data (build/assets.s) is read from main memory while RAMWRT is on,
; which is allowed because RAMRD stays off.

.include "bosco.inc"

.export _video_init, _video_shutdown, _video_wait_vbl, _video_speed_probe
.export _video_render, _video_clear_playfield, _video_clear_all
.export _video_set_panel_color
.export _panel_text, _panel_text_small, _panel_fill, _panel_dot, _panel_sprite
.export _field_text, _field_text_big
.export _dl_items, _dl_count
.export _star_x, _star_y, _star_color, _star_count
.export _video_frame_writes

.import _spr_even_lo, _spr_even_hi, _spr_odd_lo, _spr_odd_hi
.import _spr_width, _spr_height, _font8, _palette0
.import popa
.macpack longbranch

; ---------------------------------------------------------------------------
; zero page ($20-$4F belongs to video)
; ---------------------------------------------------------------------------
V_SRC     = ZP_VIDEO+$00   ; 2  run source pointer
V_DST     = ZP_VIDEO+$02   ; 2  row destination pointer
V_REC     = ZP_VIDEO+$04   ; 2  sprite row record pointer
V_TMP     = ZP_VIDEO+$06   ; 2  scratch
V_X       = ZP_VIDEO+$08   ; 2  sprite x (signed)
V_Y       = ZP_VIDEO+$0A   ; 2  sprite y (signed)
V_H       = ZP_VIDEO+$0C   ; sprite height
V_W       = ZP_VIDEO+$0D   ; sprite width in bytes (this variant)
V_BC      = ZP_VIDEO+$0E   ; byte column of the sprite (signed 8-bit)
V_ROWS    = ZP_VIDEO+$0F   ; rows left to draw
V_SY      = ZP_VIDEO+$10   ; current screen row
V_LEN     = ZP_VIDEO+$11   ; run length after clipping
V_START   = ZP_VIDEO+$12   ; first byte column of the clipped run
V_MODE    = ZP_VIDEO+$13   ; 0 = draw, 1 = erase
V_ID      = ZP_VIDEO+$14   ; sprite id
V_WR      = ZP_VIDEO+$15   ; 2  AUX bytes written (copied out after RAMWRT off)
V_CNT     = ZP_VIDEO+$17   ; loop counter
V_ITEM    = ZP_VIDEO+$18   ; 2  display list item pointer
V_COLOR   = ZP_VIDEO+$1A   ; color nibble (low)
V_COLHI   = ZP_VIDEO+$1B   ; color << 4
V_COL11   = ZP_VIDEO+$1C   ; color * $11 (both pixels)
V_PX      = ZP_VIDEO+$1D   ; byte column 0..159
V_PY      = ZP_VIDEO+$1E   ; row
V_STR     = ZP_VIDEO+$1F   ; 2  string pointer
V_BIG     = ZP_VIDEO+$21   ; text: 0 = 8 px glyphs, 1 = 16 px glyphs
V_GLY     = ZP_VIDEO+$22   ; 2  glyph pointer
V_FROW    = ZP_VIDEO+$24   ; font row index
V_ROWSTEP = ZP_VIDEO+$25   ; font row increment (1 or 2)
V_NROWS   = ZP_VIDEO+$26   ; font rows per glyph (8 or 4)
V_FBYTE   = ZP_VIDEO+$27   ; current font byte
V_WB      = ZP_VIDEO+$28   ; fill width in bytes
V_HH      = ZP_VIDEO+$29   ; fill height
V_GW      = ZP_VIDEO+$2A   ; glyph width in bytes (4 or 8)
V_PTR     = ZP_VIDEO+$2B   ; 2  generic pointer for clears/copies

SCREEN_H  = 200
FIELD_H   = 200
ROW_BYTES = SHR_ROW
PANEL_COLOR_DEFAULT = 1    ; white
USE_PANEL_COLOR = $FF      ; color argument meaning "use video_set_panel_color"

; ---------------------------------------------------------------------------
; C globals and private state
; ---------------------------------------------------------------------------
.segment "BSS"

_dl_items:          .res DL_MAX*6      ; struct DlItem { u8 id; s16 x; s16 y; u8 pad; }
_dl_count:          .res 1
_star_x:            .res STAR_MAX
_star_y:            .res STAR_MAX
_star_color:        .res STAR_MAX
_star_count:        .res 1
_video_frame_writes: .res 2

prev_items:         .res DL_MAX*6      ; previous frame's display list
prev_count:         .res 1
prev_star_x:        .res STAR_MAX
prev_star_y:        .res STAR_MAX
prev_star_count:    .res 1
panel_color:        .res 1

; ---------------------------------------------------------------------------
; read-only tables
; ---------------------------------------------------------------------------
.segment "RODATA"

; AUX row addresses: $2000 + y*160 for y = 0..199
row_lo:
.repeat SCREEN_H, i
        .byte <(SHR_BASE + i*ROW_BYTES)
.endrepeat
row_hi:
.repeat SCREEN_H, i
        .byte >(SHR_BASE + i*ROW_BYTES)
.endrepeat

; Entry points into the unrolled copy/erase loops, indexed by 2*len (0..32).
copy_tab:
.repeat 33, n
        .word copy_run + (32-n)*5
.endrepeat
erase_tab:
.repeat 33, n
        .word erase_run + (32-n)*3
.endrepeat

.segment "CODE"

; ---------------------------------------------------------------------------
; Unrolled run copy. Enter with Y = len-1, X = len*2, V_SRC/V_DST set.
; Each step is 5 bytes (lda (zp),y / sta (zp),y / dey); the table above
; jumps to step (32-len) so exactly len bytes are copied.
; ---------------------------------------------------------------------------
copy_dispatch:
        jmp     (copy_tab,x)

copy_run:
.repeat 32
        lda     (V_SRC),y
        sta     (V_DST),y
        dey
.endrepeat
        rts

; Unrolled zero fill. Enter with A = 0, Y = len-1, X = len*2, V_DST set.
erase_dispatch:
        jmp     (erase_tab,x)

erase_run:
.repeat 32
        sta     (V_DST),y
        dey
.endrepeat
        rts

; ---------------------------------------------------------------------------
; blit_sprite: draw (V_MODE = 0) or erase (V_MODE = 1) sprite V_ID at
; signed V_X / V_Y, clipped to x bytes 0..127 and rows 0..199. Adds the
; number of AUX bytes written to V_WR. RAMWRT must already be on.
; ---------------------------------------------------------------------------
blit_sprite:
        ldx     V_ID
        lda     V_X
        lsr     a                       ; C = x & 1
        bcs     @odd
        lda     _spr_even_lo,x
        sta     V_REC
        lda     _spr_even_hi,x
        sta     V_REC+1
        bra     @have
@odd:
        lda     _spr_odd_lo,x
        sta     V_REC
        lda     _spr_odd_hi,x
        sta     V_REC+1
@have:
        lda     (V_REC)
        sta     V_H
        ldy     #1
        lda     (V_REC),y
        sta     V_W
        ; V_REC now points at the first row record
        lda     V_REC
        clc
        adc     #2
        sta     V_REC
        bcc     :+
        inc     V_REC+1
:
        ; byte column = x >> 1 (arithmetic) as a signed 16-bit value in X:A
        lda     V_X+1
        cmp     #$80
        ror     a
        tax
        lda     V_X
        ror     a
        cpx     #0
        beq     @bc_pos
        cpx     #$FF
        jne     @off
        ; negative column: visible only if bc + W > 0
        sta     V_BC
        clc
        adc     V_W
        jcc     @off                    ; bc + W <= 0
        jeq     @off                    ; bc + W == 0
        bra     @bc_done
@bc_pos:
        cmp     #FIELD_BYTES
        jcs     @off
        sta     V_BC
@bc_done:

        ; vertical clip: first row r0 and row count
        lda     V_Y+1
        beq     @y_pos
        cmp     #$FF
        jne     @off
        ; y in -256..-1: r0 = -y
        lda     #0
        sec
        sbc     V_Y
        jeq     @off                    ; y = -256
        cmp     V_H
        jcs     @off                    ; whole sprite above the screen
        sta     V_TMP                   ; r0
        sec
        lda     V_H
        sbc     V_TMP
        sta     V_ROWS
        stz     V_SY
        ; skip r0 row records
@skip:
        ldy     #1
        lda     (V_REC),y
        clc
        adc     #2
        adc     V_REC
        sta     V_REC
        bcc     :+
        inc     V_REC+1
:       dec     V_TMP
        bne     @skip
        bra     @rows
@y_pos:
        lda     V_Y
        cmp     #FIELD_H
        jcs     @off
        sta     V_SY
        lda     #FIELD_H
        sec
        sbc     V_Y                     ; rows available below y
        cmp     V_H
        bcc     :+
        lda     V_H
:       sta     V_ROWS

@rows:
        ; ---- one row per iteration ----
@row:
        lda     (V_REC)                 ; run_off
        cmp     #$FF
        jeq     @next                   ; empty row
        clc
        adc     V_BC                    ; start = bc + run_off
        bit     V_BC
        bmi     @neg_bc
        ; bc >= 0: start in 0..158
        cmp     #FIELD_BYTES
        jcs     @next                   ; run starts past the field
        sta     V_START
        ldy     #1
        lda     (V_REC),y
        sta     V_LEN
        lda     V_REC
        clc
        adc     #2
        sta     V_SRC
        lda     V_REC+1
        adc     #0
        sta     V_SRC+1
        bra     @clip_right
@neg_bc:
        ; bc < 0: start is a signed byte in -32..30 (test A, not the flags
        ; left by bit)
        cmp     #$80
        bcc     @start_pos
        eor     #$FF
        inc     a                       ; skip = -start
        sta     V_TMP
        ldy     #1
        lda     (V_REC),y               ; run_len
        sec
        sbc     V_TMP
        beq     @next
        bcc     @next                   ; run ends before column 0
        sta     V_LEN
        stz     V_START
        lda     V_TMP
        clc
        adc     #2
        adc     V_REC
        sta     V_SRC
        lda     V_REC+1
        adc     #0
        sta     V_SRC+1
        bra     @clip_right
@start_pos:
        sta     V_START
        ldy     #1
        lda     (V_REC),y
        sta     V_LEN
        lda     V_REC
        clc
        adc     #2
        sta     V_SRC
        lda     V_REC+1
        adc     #0
        sta     V_SRC+1
@clip_right:
        lda     #FIELD_BYTES
        sec
        sbc     V_START                 ; bytes available to the right edge
        cmp     V_LEN
        bcs     :+
        sta     V_LEN
:       ; destination = row + start
        ldx     V_SY
        lda     row_lo,x
        clc
        adc     V_START
        sta     V_DST
        lda     row_hi,x
        adc     #0
        sta     V_DST+1
        ; count the bytes
        lda     V_WR
        clc
        adc     V_LEN
        sta     V_WR
        bcc     :+
        inc     V_WR+1
:       lda     V_LEN
        asl     a
        tax
        ldy     V_LEN
        dey
        lda     V_MODE
        bne     @erase
        jsr     copy_dispatch
        bra     @next
@erase:
        lda     #0
        jsr     erase_dispatch
@next:
        ; advance to the next row record: rec += 2 + run_len
        ldy     #1
        lda     (V_REC),y
        clc
        adc     #2
        adc     V_REC
        sta     V_REC
        bcc     :+
        inc     V_REC+1
:       inc     V_SY
        dec     V_ROWS
        jne     @row
@off:
        rts

; ---------------------------------------------------------------------------
; blit_list: run blit_sprite over a display list. V_ITEM = list, V_CNT =
; item count, V_MODE = draw/erase. RAMWRT must be on.
; ---------------------------------------------------------------------------
blit_list:
        lda     V_CNT
        beq     @done
@loop:
        lda     (V_ITEM)
        sta     V_ID
        ldy     #1
        lda     (V_ITEM),y
        sta     V_X
        iny
        lda     (V_ITEM),y
        sta     V_X+1
        iny
        lda     (V_ITEM),y
        sta     V_Y
        iny
        lda     (V_ITEM),y
        sta     V_Y+1
        jsr     blit_sprite
        lda     V_ITEM
        clc
        adc     #6
        sta     V_ITEM
        bcc     :+
        inc     V_ITEM+1
:       dec     V_CNT
        bne     @loop
@done:
        rts

; ---------------------------------------------------------------------------
; stars: one byte each at row[y] + x/2. Even x = high nibble, odd x = low.
; ---------------------------------------------------------------------------
erase_stars:
        ldx     #0
@loop:
        cpx     prev_star_count
        bcs     @done
        ldy     prev_star_y,x
        cpy     #SCREEN_H
        bcs     @skip
        lda     row_lo,y
        sta     V_DST
        lda     row_hi,y
        sta     V_DST+1
        lda     prev_star_x,x
        lsr     a
        tay
        lda     #0
        sta     (V_DST),y
        inc     V_WR
        bne     @skip
        inc     V_WR+1
@skip:
        inx
        bra     @loop
@done:
        rts

draw_stars:
        ldx     #0
@loop:
        cpx     _star_count
        bcs     @done
        ldy     _star_y,x
        cpy     #SCREEN_H
        bcs     @skip
        lda     row_lo,y
        sta     V_DST
        lda     row_hi,y
        sta     V_DST+1
        lda     _star_x,x
        lsr     a
        tay
        lda     _star_color,x
        bcs     @odd
        asl     a
        asl     a
        asl     a
        asl     a
        bra     @put
@odd:
        and     #$0F
@put:
        sta     (V_DST),y
        inc     V_WR
        bne     @skip
        inc     V_WR+1
@skip:
        inx
        bra     @loop
@done:
        rts

; ---------------------------------------------------------------------------
; void video_render(void)
;   Erase every item of the previous frame, erase the previous stars, draw
;   the new stars, then draw every item of the current list. All old
;   pixels are removed before anything new is drawn, so overlapping items
;   never punch holes in each other. Then (RAMWRT off) remember the lists.
; ---------------------------------------------------------------------------
_video_render:
        stz     V_WR
        stz     V_WR+1
        sta     RAMWRTON

        lda     #1
        sta     V_MODE
        lda     #<prev_items
        sta     V_ITEM
        lda     #>prev_items
        sta     V_ITEM+1
        lda     prev_count
        sta     V_CNT
        jsr     blit_list

        jsr     erase_stars
        jsr     draw_stars

        stz     V_MODE
        lda     #<_dl_items
        sta     V_ITEM
        lda     #>_dl_items
        sta     V_ITEM+1
        lda     _dl_count
        sta     V_CNT
        jsr     blit_list

        sta     RAMWRTOFF

        ; main-memory bookkeeping (RAMWRT is off now)
        lda     V_WR
        sta     _video_frame_writes
        lda     V_WR+1
        sta     _video_frame_writes+1
        jmp     remember_lists

; copy the current display list and star positions to the private copies
remember_lists:
        ldx     #0
@l0:    lda     _dl_items,x
        sta     prev_items,x
        lda     _dl_items+$100,x
        sta     prev_items+$100,x
        inx
        bne     @l0
        ldx     #(DL_MAX*6-$200)-1
@l1:    lda     _dl_items+$200,x
        sta     prev_items+$200,x
        dex
        bpl     @l1
        lda     _dl_count
        sta     prev_count
        ldx     #STAR_MAX-1
@l2:    lda     _star_x,x
        sta     prev_star_x,x
        lda     _star_y,x
        sta     prev_star_y,x
        dex
        bpl     @l2
        lda     _star_count
        sta     prev_star_count
        rts

forget_lists:
        stz     prev_count
        stz     prev_star_count
        rts

; ---------------------------------------------------------------------------
; void video_init(void)
; ---------------------------------------------------------------------------
_video_init:
        sta     STORE80OFF
        sta     RAMWRTON
        ; zero AUX $2000-$9FFF
        stz     V_PTR
        lda     #>SHR_BASE
        sta     V_PTR+1
        lda     #0
        ldy     #0
@clr:   sta     (V_PTR),y
        iny
        bne     @clr
        inc     V_PTR+1
        ldx     V_PTR+1
        cpx     #$A0
        bne     @clr
        ; palette 0
        ldx     #31
@pal:   lda     _palette0,x
        sta     SHR_PAL,x
        dex
        bpl     @pal
        sta     RAMWRTOFF
        lda     #$C1
        sta     NEWVIDEO
        stz     _video_frame_writes
        stz     _video_frame_writes+1
        lda     #PANEL_COLOR_DEFAULT
        sta     panel_color
        jmp     forget_lists

; ---------------------------------------------------------------------------
; void video_shutdown(void)
; ---------------------------------------------------------------------------
_video_shutdown:
        lda     #$01
        sta     NEWVIDEO
        sta     TEXTON
        rts

; ---------------------------------------------------------------------------
; void video_wait_vbl(void)
;   $C019 bit 7: 1 = display, 0 = blank. Return at the blank -> display edge,
;   right after line 0. The Appletini publishes the SHR shadow at line 0, so
;   a write burst that starts here and ends before the next line 0 lands
;   whole in one published frame (no tearing). If the call lands in the
;   display, it waits for the blank and then for the next line 0.
; ---------------------------------------------------------------------------
_video_wait_vbl:
@in_display:
        bit     RDVBLBAR
        bmi     @in_display             ; wait for the blank
@in_blank:
        bit     RDVBLBAR
        bpl     @in_blank               ; wait for line 0
        rts

; ---------------------------------------------------------------------------
; u16 video_speed_probe(void)
;   Count loop iterations from one line 0 to the next: through the display,
;   then through the blank (saturates at $FFFF).
; ---------------------------------------------------------------------------
_video_speed_probe:
        jsr     _video_wait_vbl
        stz     V_TMP
        stz     V_TMP+1
@display:
        inc     V_TMP
        bne     :+
        inc     V_TMP+1
        beq     @sat
:       bit     RDVBLBAR
        bmi     @display
@blank:
        inc     V_TMP
        bne     :+
        inc     V_TMP+1
        beq     @sat
:       bit     RDVBLBAR
        bpl     @blank
        lda     V_TMP
        ldx     V_TMP+1
        rts
@sat:
        lda     #$FF
        tax
        rts

; ---------------------------------------------------------------------------
; void video_clear_playfield(void)   black x bytes 0..127 of every row
; void video_clear_all(void)         black the whole 320x200 screen
; Both forget the previous frame.
; ---------------------------------------------------------------------------
_video_clear_playfield:
        lda     #FIELD_BYTES-1
        bra     clear_rows
_video_clear_all:
        lda     #ROW_BYTES-1
clear_rows:
        sta     V_TMP                   ; last byte index in each row
        sta     RAMWRTON
        ldx     #0
@row:   lda     row_lo,x
        sta     V_DST
        lda     row_hi,x
        sta     V_DST+1
        lda     #0
        ldy     V_TMP
@b:     sta     (V_DST),y
        dey
        cpy     #$FF                    ; Y may start above 127
        bne     @b
        inx
        cpx     #SCREEN_H
        bne     @row
        sta     RAMWRTOFF
        jmp     forget_lists

; ---------------------------------------------------------------------------
; void __fastcall__ video_set_panel_color(u8 color)
;   Stored color, used by panel_text/panel_text_small/panel_fill/panel_dot
;   when their color argument is $FF.
; ---------------------------------------------------------------------------
_video_set_panel_color:
        and     #$0F
        sta     panel_color
        rts

; set V_COLOR/V_COLHI/V_COL11 from the color in A ($FF = panel_color)
set_color:
        cmp     #USE_PANEL_COLOR
        bne     :+
        lda     panel_color
:       and     #$0F
        sta     V_COLOR
        asl     a
        asl     a
        asl     a
        asl     a
        sta     V_COLHI
        ora     V_COLOR
        sta     V_COL11
        rts

; ---------------------------------------------------------------------------
; text
;   V_PX = byte column (0..159), V_PY = row, V_STR = string, colors set,
;   V_BIG, V_ROWSTEP, V_NROWS, V_GW describe the glyph layout.
; ---------------------------------------------------------------------------
; void panel_text(u8 px, u8 py, u8 color, const char *s)
_panel_text:
        sta     V_STR
        stx     V_STR+1
        jsr     popa
        jsr     set_color
        jsr     popa
        sta     V_PY
        jsr     popa
        clc
        adc     #PANEL_BYTE0
        sta     V_PX
text_8x8:
        stz     V_BIG
        lda     #1
        sta     V_ROWSTEP
        lda     #8
        sta     V_NROWS
        lda     #4
        sta     V_GW
        bra     draw_text

; void panel_text_small(u8 px, u8 py, u8 color, const char *s)
_panel_text_small:
        sta     V_STR
        stx     V_STR+1
        jsr     popa
        jsr     set_color
        jsr     popa
        sta     V_PY
        jsr     popa
        clc
        adc     #PANEL_BYTE0
        sta     V_PX
        stz     V_BIG
        lda     #2
        sta     V_ROWSTEP
        lda     #4
        sta     V_NROWS
        sta     V_GW
        bra     draw_text

; void field_text(u8 x, u8 y, u8 color, const char *s)   x in pixels (even)
_field_text:
        sta     V_STR
        stx     V_STR+1
        jsr     popa
        jsr     set_color
        jsr     popa
        sta     V_PY
        jsr     popa
        lsr     a
        sta     V_PX
        jmp     text_8x8

; void field_text_big(u8 x, u8 y, u8 color, const char *s)   16x16 glyphs
_field_text_big:
        sta     V_STR
        stx     V_STR+1
        jsr     popa
        jsr     set_color
        jsr     popa
        sta     V_PY
        jsr     popa
        lsr     a
        sta     V_PX
        lda     #1
        sta     V_BIG
        sta     V_ROWSTEP
        lda     #8
        sta     V_NROWS
        sta     V_GW
        ; fall through

draw_text:
        sta     RAMWRTON
@char:
        lda     (V_STR)
        beq     @done
        ; fold a..z to A..Z
        cmp     #'a'
        bcc     :+
        cmp     #'z'+1
        bcs     :+
        sbc     #$1F                    ; carry is clear: A - $20
:       sec
        sbc     #32
        cmp     #64
        bcc     :+
        lda     #0                      ; outside 32..95: draw a space
:       stz     V_GLY+1
        asl     a
        rol     V_GLY+1
        asl     a
        rol     V_GLY+1
        asl     a
        rol     V_GLY+1
        clc
        adc     #<_font8
        sta     V_GLY
        lda     V_GLY+1
        adc     #>_font8
        sta     V_GLY+1
        ; stop at the right edge of the screen
        lda     V_PX
        clc
        adc     V_GW
        cmp     #ROW_BYTES+1
        bcs     @done
        jsr     draw_glyph
        lda     V_PX
        clc
        adc     V_GW
        sta     V_PX
        inc     V_STR
        bne     @char
        inc     V_STR+1
        bra     @char
@done:
        sta     RAMWRTOFF
        rts

; draw one glyph at V_PX / V_PY. V_SY only grows, so the first row at or
; past SCREEN_H ends the glyph (the one-byte row must not wrap to row 0).
draw_glyph:
        lda     V_PY
        sta     V_SY
        stz     V_FROW
        lda     V_NROWS
        sta     V_ROWS
@row:
        ldy     V_FROW
        lda     (V_GLY),y
        sta     V_FBYTE
        lda     V_SY
        cmp     #SCREEN_H
        bcs     @done
        jsr     glyph_dst
        lda     V_BIG
        bne     @big
        jsr     glyph_row_4
        bra     @skip
@big:
        jsr     glyph_row_8
        inc     V_SY
        lda     V_SY
        cmp     #SCREEN_H
        bcs     @done
        jsr     glyph_dst
        jsr     glyph_row_8
@skip:
        inc     V_SY
        lda     V_FROW
        clc
        adc     V_ROWSTEP
        sta     V_FROW
        dec     V_ROWS
        bne     @row
@done:
        rts

; V_DST = row[V_SY] + V_PX
glyph_dst:
        ldx     V_SY
        lda     row_lo,x
        clc
        adc     V_PX
        sta     V_DST
        lda     row_hi,x
        adc     #0
        sta     V_DST+1
        rts

; 8 font bits -> 4 bytes (two pixels per byte)
glyph_row_4:
        lda     V_FBYTE
        sta     V_TMP
        ldy     #0
@b:     lda     #0
        asl     V_TMP
        bcc     :+
        ora     V_COLHI
:       asl     V_TMP
        bcc     :+
        ora     V_COLOR
:       sta     (V_DST),y
        iny
        cpy     #4
        bne     @b
        rts

; 8 font bits -> 8 bytes (each bit is two pixels wide)
glyph_row_8:
        lda     V_FBYTE
        sta     V_TMP
        ldy     #0
@b:     lda     #0
        asl     V_TMP
        bcc     :+
        lda     V_COL11
:       sta     (V_DST),y
        iny
        cpy     #8
        bne     @b
        rts

; ---------------------------------------------------------------------------
; void panel_fill(u8 px, u8 py, u8 wbytes, u8 h, u8 color)
; void panel_dot(u8 px, u8 py, u8 color)      2x2 dot = fill 1 byte x 2 rows
; ---------------------------------------------------------------------------
_panel_fill:
        jsr     set_color
        jsr     popa
        sta     V_HH
        jsr     popa
        sta     V_WB
        bra     fill_common

_panel_dot:
        jsr     set_color
        lda     #2
        sta     V_HH
        lda     #1
        sta     V_WB
fill_common:
        jsr     popa
        sta     V_PY
        jsr     popa
        clc
        adc     #PANEL_BYTE0
        sta     V_PX
        lda     V_HH
        beq     @done
        lda     V_WB
        beq     @done
        sta     RAMWRTON
        ldx     V_PY
@row:   cpx     #SCREEN_H
        bcs     @end
        lda     row_lo,x
        clc
        adc     V_PX
        sta     V_DST
        lda     row_hi,x
        adc     #0
        sta     V_DST+1
        lda     V_COL11
        ldy     V_WB
        dey
@b:     sta     (V_DST),y
        dey
        bpl     @b
        inx
        dec     V_HH
        bne     @row
@end:
        sta     RAMWRTOFF
@done:
        rts

; ---------------------------------------------------------------------------
; void panel_sprite(u8 px, u8 py, u8 id)
;   Even variant at byte column 128+px, no horizontal clipping; rows past
;   199 are skipped.
; ---------------------------------------------------------------------------
_panel_sprite:
        tax
        lda     _spr_even_lo,x
        sta     V_REC
        lda     _spr_even_hi,x
        sta     V_REC+1
        jsr     popa
        sta     V_SY
        jsr     popa
        clc
        adc     #PANEL_BYTE0
        sta     V_PX
        lda     (V_REC)
        sta     V_ROWS
        beq     @done
        ; skip the two header bytes
        lda     V_REC
        clc
        adc     #2
        sta     V_REC
        bcc     :+
        inc     V_REC+1
:       sta     RAMWRTON
@row:
        lda     (V_REC)                 ; run_off
        cmp     #$FF
        beq     @next
        ldx     V_SY
        cpx     #SCREEN_H
        bcs     @next
        clc
        adc     V_PX
        adc     row_lo,x
        sta     V_DST
        lda     row_hi,x
        adc     #0
        sta     V_DST+1
        lda     V_REC
        clc
        adc     #2
        sta     V_SRC
        lda     V_REC+1
        adc     #0
        sta     V_SRC+1
        ldy     #1
        lda     (V_REC),y
        sta     V_LEN
        asl     a
        tax
        ldy     V_LEN
        dey
        jsr     copy_dispatch
@next:
        ldy     #1
        lda     (V_REC),y
        clc
        adc     #2
        adc     V_REC
        sta     V_REC
        bcc     :+
        inc     V_REC+1
:       inc     V_SY
        dec     V_ROWS
        bne     @row
        sta     RAMWRTOFF
@done:
        rts
