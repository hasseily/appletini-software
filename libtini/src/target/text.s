; Text in the built-in 5x7 font, for graphics_text.c, which has checked the
; surface and every argument. Each line is clipped once. Each pixel row of a
; line is then one read of the bytes it covers, unless opaque text covers
; them whole, and one write; the glyphs change the row buffer in between.
; target/surface.s moves the rows; graphics_text.c has located the surface.
;
; The row buffer has three guard bytes before it and two after, so a cell
; cut by an edge needs no per-pixel checks. The guards are never written
; back, and a byte split by the line's edge keeps its outside pixel.
.setcpu "65C02"
.include "zeropage.inc"
.macpack longbranch
.export _ti_text_draw, _ti_text_surface, _ti_text_x, _ti_text_y
.export _ti_text_string, _ti_text_ink, _ti_text_paper, _ti_text_opaque
.import pushax, _ti_near_valid
.import _ti_row_seek, _ti_row_next, _ti_row_read, _ti_row_write, _ti_row_bytes, _ti_row_stride
.import _ti_gfx_rows, _ti_font, _ti_font_index

TI_RANGE = 3
REREAD  = $80           ; flags: read each row first
OPAQUE  = $40           ; fill each row with the paper colour
RIGHT   = $02           ; the last byte keeps its low nibble
LEFT    = $01           ; the first byte keeps its high nibble
ROW     = _ti_gfx_rows + 3

.segment "BSS"
_ti_text_surface: .res 2
_ti_text_x:     .res 2
_ti_text_y:     .res 2  ; the current line's top
_ti_text_string: .res 2 ; the next character
_ti_text_ink:   .res 1  ; colours in both nibbles
_ti_text_paper: .res 1
_ti_text_opaque: .res 1 ; OPAQUE or 0
width:  .res 2          ; copied from the surface
height: .res 2
remaining: .res 2       ; characters left of the 1024 a call reads
line:   .res 2
count:  .res 2
ch:     .res 1
lo:     .res 2          ; the line's visible pixels, lo up to hi
hi:     .res 2
skip:   .res 1          ; pixels of the first visible cell left of 0
half_lo: .res 1
chars:  .res 2          ; the first visible cell's character
cells:  .res 1
start:  .res 1          ; that cell's first byte in _ti_gfx_rows
shift:  .res 1          ; 3 for an even x, 2 for an odd one
flags:  .res 1
row:    .res 1
row_end: .res 1
first:  .res 1
last:   .res 1
glyphs: .res 2
cell:   .res 1
at:     .res 1
bits:   .res 1
mask:   .res 1

.segment "CODE"
; ti_error ti_text_draw(void)
_ti_text_draw:
        lda _ti_text_surface
        sta ptr1
        lda _ti_text_surface+1
        sta ptr1+1
        ldy #9
:       lda (ptr1),y
        sta width-6,y
        dey
        cpy #5
        bne :-
        stz remaining
        lda #>1024
        sta remaining+1
next_line:
        lda _ti_text_string
        sta line
        lda _ti_text_string+1
        sta line+1
        stz count
        stz count+1
scan:   lda _ti_text_string
        ldx _ti_text_string+1
        jsr pushax
        lda #1
        ldx #0
        jsr pushax
        lda #0
        jsr _ti_near_valid
        cmp #0
        bne :+
        lda #TI_RANGE
        bra failed
:       lda _ti_text_string
        sta ptr1
        lda _ti_text_string+1
        sta ptr1+1
        lda (ptr1)
        sta ch
        inc _ti_text_string
        bne :+
        inc _ti_text_string+1
:       lda remaining
        bne :+
        dec remaining+1
:       dec remaining
        lda ch
        beq ended
        cmp #10
        beq ended
        inc count
        bne :+
        inc count+1
:       lda remaining
        ora remaining+1
        bne scan
ended:  lda count
        ora count+1
        beq :+
        jsr draw_line
:       lda ch
        beq done
        lda remaining
        ora remaining+1
        beq done
        clc
        lda _ti_text_y
        adc #8
        sta _ti_text_y
        jcc next_line
        inc _ti_text_y+1
        jmp next_line
done:   lda #0
failed: ldx #0
        rts

; Draws count characters from line at (_ti_text_x, _ti_text_y).
draw_line:
        ; The cell rows on the surface: 0..7, of which transparent text
        ; leaves row 7 alone. The top must be -7 to height-1.
        ldx #7
        bit _ti_text_opaque
        bvc :+
        inx
:       stx row_end
        lda _ti_text_y+1
        bmi above
        lda _ti_text_y
        cmp height
        lda _ti_text_y+1
        sbc height+1
        jcs nothing
        stz row
        bra visible
above:  cmp #$FF
        jne nothing
        lda _ti_text_y
        cmp #<-7
        jcc nothing
        eor #$FF
        inc a
        sta row
visible:
        sec
        lda height
        sbc _ti_text_y          ; height - top, 1..207
        cmp row_end
        bcs :+
        sta row_end
:       lda row
        cmp row_end
        jcs nothing
        ; Columns. With x < 0, -x = 6 * hidden cells + skip.
        lda line
        sta chars
        lda line+1
        sta chars+1
        stz skip
        lda _ti_text_x
        sta lo
        ldx _ti_text_x+1
        stx lo+1
        bpl :+
        sec
        lda #0
        sbc _ti_text_x
        pha
        lda #0
        sbc _ti_text_x+1
        tax
        pla
        jsr div6
        sta skip
        tya
        clc
        adc chars
        sta chars
        bcc :+
        inc chars+1
:       lda lo+1
        bpl :+
        stz lo
        stz lo+1
        ; hi = x + 6 * count, at most 7168.
:       lda count
        asl a
        sta tmp1
        lda count+1
        rol a
        sta tmp2
        lda tmp1
        asl a
        sta hi
        lda tmp2
        rol a
        sta hi+1
        clc
        lda hi
        adc tmp1
        sta hi
        lda hi+1
        adc tmp2
        sta hi+1
        clc
        lda hi
        adc _ti_text_x
        sta hi
        lda hi+1
        adc _ti_text_x+1
        sta hi+1
        jmi nothing
        lda width
        cmp hi
        lda width+1
        sbc hi+1
        bcs :+
        lda width
        sta hi
        lda width+1
        sta hi+1
:       lda lo
        cmp hi
        lda lo+1
        sbc hi+1
        jcs nothing
        ; bytes = (hi - 1) / 2 - lo / 2 + 1, at most 160.
        lda hi
        sec
        sbc #1
        tax
        lda hi+1
        sbc #0
        lsr a
        txa
        ror a
        sta tmp1
        lda lo+1
        lsr a
        lda lo
        ror a
        sta half_lo
        lda tmp1
        sec
        sbc half_lo
        inc a
        sta _ti_row_bytes
        ; Opaque text reads only to keep a split edge byte.
        lda hi
        and #1
        asl a
        sta flags
        lda lo
        and #1
        ora flags
        ora _ti_text_opaque
        cmp #OPAQUE
        beq :+
        ora #REREAD
:       sta flags
        ; cells = (hi - lo - 1 + skip) / 6 + 1, at most 55.
        clc
        lda hi
        sbc lo
        tay
        lda hi+1
        sbc lo+1
        tax
        tya
        clc
        adc skip
        bcc :+
        inx
:       jsr div6
        iny
        sty cells
        ; The first cell starts (skip + 1) / 2 bytes before the buffer.
        lda skip
        inc a
        lsr a
        sta tmp1
        lda #3
        sec
        sbc tmp1
        sta start
        lda _ti_text_x
        and #1
        eor #3
        sta shift
        ; The first row is byte (top + row) * stride + lo / 2 of the
        ; surface. The row is 0..199, the offset at most 31999.
        clc
        lda _ti_text_y
        adc row
        sta tmp1
        stz ptr1
        stz ptr1+1
        ldx #8
:       asl ptr1
        rol ptr1+1
        asl tmp1
        bcc :+
        clc
        lda ptr1
        adc _ti_row_stride
        sta ptr1
        lda ptr1+1
        adc _ti_row_stride+1
        sta ptr1+1
:       dex
        bne :--
        clc
        lda ptr1
        adc half_lo
        ldx ptr1+1
        bcc :+
        inx
:       jsr _ti_row_seek
        ; The rows.
next_row:
        bit flags
        bpl fill
        jsr _ti_row_read
        lda ROW
        sta first
        ldx _ti_row_bytes
        lda ROW-1,x
        sta last
fill:   bit flags
        bvc glyph_row
        lda _ti_text_paper
        ldx _ti_row_bytes
:       sta ROW-1,x
        dex
        bne :-
glyph_row:
        lda row
        cmp #7
        bcs edges
        ; glyphs = _ti_font + row: this row of glyph 0.
        adc #<_ti_font
        sta glyphs
        lda #0
        adc #>_ti_font
        sta glyphs+1
        jsr cells_row
edges:  lda flags
        lsr a
        bcc :+
        tay
        lda ROW
        and #$0F
        sta mask
        lda first
        and #$F0
        ora mask
        sta ROW
        tya
:       lsr a
        bcc :+
        ldx _ti_row_bytes
        lda ROW-1,x
        and #$F0
        sta mask
        lda last
        and #$0F
        ora mask
        sta ROW-1,x
:       jsr _ti_row_write
        jsr _ti_row_next
        inc row
        lda row
        cmp row_end
        jne next_row
nothing:
        rts

; The rest runs from LOWCODE, which the full game places in low MAIN.
.segment "LOWCODE"
; Y = (A + 256 * X) / 6 and A = the remainder, for values below 1536.
div6:   ldy #0
        stx tmp4
:       ldx tmp4
        bne :+
        cmp #6
        bcc :++
:       sec
        sbc #6
        iny
        bcs :--
        dec tmp4
        bra :--
:       rts

; The cells of this pixel row: lit pixels take the ink colour.
cells_row:
        lda chars
        sta ptr1
        lda chars+1
        sta ptr1+1
        lda start
        sta at
        stz cell
glyph:  ldy cell
        lda (ptr1),y
        ; Lower case shows as upper case, codes outside ' '.._ as '?'.
        cmp #'a'
        bcc :+
        cmp #'z'+1
        bcs :+
        sbc #31                 ; the carry is clear, so this subtracts 32
:       sec
        sbc #' '
        cmp #64
        bcc :+
        lda #'?'-' '
:       tax
        lda _ti_font_index,x
        ; ptr2 = glyphs + 7 * glyph; 8 * glyph needs nine bits.
        sta tmp1
        stz ptr2+1
        asl a
        asl a
        asl a
        rol ptr2+1
        sec
        sbc tmp1
        bcs :+
        dec ptr2+1
:       clc
        adc glyphs
        sta ptr2
        lda ptr2+1
        adc glyphs+1
        sta ptr2+1
        lda (ptr2)
        beq unlit_cell
        ldx shift
:       asl a
        dex
        bne :-
        sta bits
        ; Three bytes, each a pair of pixels from the top of bits.
        ldx at
        ldy #3
pair:   lda #0
        asl bits
        bcc :+
        lda #$F0
:       asl bits
        bcc :+
        ora #$0F
:       cmp #0
        beq unlit
        sta mask
        lda _ti_gfx_rows,x
        eor _ti_text_ink
        and mask
        eor _ti_gfx_rows,x
        sta _ti_gfx_rows,x
unlit:  inx
        dey
        bne pair
unlit_cell:
        lda at
        clc
        adc #3
        sta at
        inc cell
        lda cell
        cmp cells
        jne glyph
        rts
