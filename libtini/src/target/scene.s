; libtini band renderer: sprite list marking, composition and publication.
; State lives in scene.c; the sprite arrays and strip come from the game's
; TI_SCENE_STORAGE, so every array is reached at an absolute address.
;
; A sprite marks the blocks of 8 bytes by 8 lines it covers; a sprite that
; moved, changed or went away also marks where it was. ti_scene_draw takes
; each band with marked blocks, fills those blocks of the strip with the
; background, composes every sprite that touches the band and publishes the
; runs of marked blocks through _ti_cpu_write_rows. Bytes outside the marked
; blocks may hold anything; they are never published.
;
; Foreground and non-reentrant. Zero page ptr1, ptr2, ptr4 and tmp1-tmp4 are
; scratch only between calls out; no state is kept there.
.setcpu "65C02"
.include "zeropage.inc"
.macpack longbranch
.export _ti_scene_begin, _ti_scene_add, _ti_scene_draw, _ti_scene_invalidate
.import incsp5, callax, pushax, _ti_time_note_gap, _ti_near_valid
.import _ti_scene_strip, _ti_scene_strip_width
.import _ti_scene_x_lo, _ti_scene_x_hi, _ti_scene_y_lo, _ti_scene_y_hi
.import _ti_scene_image, _ti_scene_color, _ti_scene_top, _ti_scene_bottom
.import _ti_scene_capacity
.import _ti_scene_images, _ti_scene_image_count, _ti_scene_x0, _ti_scene_y0
.import _ti_scene_row_bytes, _ti_scene_lines, _ti_scene_bands, _ti_scene_blocks
.import _ti_scene_fill, _ti_scene_count, _ti_scene_end, _ti_scene_screen
.import _ti_scene_row_lo, _ti_scene_row_hi
.import _ti_scene_mask, _ti_scene_service
.import _ti_video_backup, _ti_cpu_write_rows
.import _ti_io_addr, _ti_io_near, _ti_io_width, _ti_io_rows, _ti_io_stride

; Changed-block masks: byte 0 of every band, then byte 1, then byte 2.
mask0 = _ti_scene_mask
mask1 = _ti_scene_mask+25
mask2 = _ti_scene_mask+50

TI_OK    = 0
TI_ARGUMENT = 1
TI_STATE = 2
TI_RANGE = 3
TI_FULL  = 11

.segment "BSS"
; ti_scene_begin: a copy of the configuration and the checks' near range.
config:     .res 14
cfg_x      = config
cfg_y      = config+2
cfg_width  = config+4
cfg_height = config+6
cfg_images = config+8
cfg_count  = config+10
cfg_background = config+11
cfg_service = config+12
near_ptr:   .res 2
near_len:   .res 2
images_left: .res 1
image_at:   .res 2
; ti_scene_add arguments.
new_x:      .res 2
new_y:      .res 2
new_image:  .res 1
new_color:  .res 1
; The sprite being marked or composed and its image.
item:       .res 1
work_x:     .res 2
work_y:     .res 2
work_image: .res 1
work_color: .res 1
pixels:     .res 2
image_bytes: .res 1
image_rows: .res 1
image_stride: .res 1
; Area-relative position: bytes across, lines down.
rel_x:      .res 2
rel_y:      .res 2
; One axis clip: position, length and limit in; first and last out.
clip_pos:   .res 2
clip_len:   .res 1
clip_limit: .res 1
clip_first: .res 1
clip_last:  .res 1
top:        .res 1
bottom:     .res 1
block0:     .res 1
block1:     .res 1
bits:       .res 3
; Drawing.
band:       .res 1
band_y:     .res 1
screen:     .res 2
runs:       .res 1
run_i:      .res 1
in_run:     .res 1
run_start:  .res 10
run_len:    .res 10
; Composition of one sprite into the strip.
src_row:    .res 1
dst_row:    .res 1
src_col:    .res 1
dst_col:    .res 1
rows_left:  .res 1
columns:    .res 1
ink:        .res 1

.segment "RODATA"
bit_table:  .byte 1, 2, 4, 8, 16, 32, 64, 128

.segment "CODE"
; ti_error ti_scene_begin(const ti_scene_config *config)
_ti_scene_begin:
        stz _ti_scene_bands
        sta near_ptr
        stx near_ptr+1
        lda #14
        sta near_len
        stz near_len+1
        jsr near_ok
        jeq argument
        lda near_ptr
        sta ptr1
        lda near_ptr+1
        sta ptr1+1
        ldy #13
@copy:  lda (ptr1),y
        sta config,y
        dey
        bpl @copy
        ; Even x and width; nonzero width; height a nonzero multiple of 8.
        lda cfg_x
        ora cfg_width
        and #1
        jne range
        lda cfg_width
        ora cfg_width+1
        jeq range
        lda cfg_height
        and #7
        jne range
        lda cfg_height
        ora cfg_height+1
        jeq range
        ; width <= 320 - x and height <= 200 - y, with x < 320 and y < 200.
        sec
        lda #<320
        sbc cfg_x
        tax
        lda #>320
        sbc cfg_x+1
        jcc range
        tay
        txa
        sec
        sbc cfg_width
        tya
        sbc cfg_width+1
        jcc range
        sec
        lda #200
        sbc cfg_y
        tax
        lda #0
        sbc cfg_y+1
        jcc range
        tay
        txa
        sec
        sbc cfg_height
        tya
        sbc cfg_height+1
        jcc range
        ; width is now at most 320: width / 2 fits a byte and the strip.
        lda cfg_width+1
        lsr a
        lda cfg_width
        ror a
        sta _ti_scene_row_bytes
        lda _ti_scene_strip_width
        cmp _ti_scene_row_bytes
        jcc range
        lda cfg_background
        cmp #16
        jcs range
        ; The image table, then each image's pixels.
        lda cfg_count
        jeq argument
        sta images_left
        sta tmp1
        stz tmp2
        asl a
        rol tmp2
        asl a
        rol tmp2
        clc
        adc tmp1
        sta near_len
        lda tmp2
        adc #0
        sta near_len+1
        lda cfg_images
        sta near_ptr
        sta image_at
        lda cfg_images+1
        sta near_ptr+1
        sta image_at+1
        jsr near_ok
        jeq argument
        bra image
argument:
        lda #TI_ARGUMENT
        ldx #0
        rts
range:  lda #TI_RANGE
        ldx #0
        rts
image:  lda image_at
        sta ptr1
        lda image_at+1
        sta ptr1+1
        ldy #2
        lda (ptr1),y
        jeq range
        sta image_bytes
        iny
        lda (ptr1),y
        jeq range
        sta image_rows
        iny
        lda (ptr1),y
        sta image_stride
        ldy #1
        lda (ptr1),y
        beq @next                  ; NULL pixels: a rectangle
        sta near_ptr+1
        dey
        lda (ptr1),y
        sta near_ptr
        lda image_stride
        cmp image_bytes
        jcc range
        ; (rows - 1) * stride + row_bytes bytes must be readable.
        ldx image_rows
        dex
        stx tmp1
        lda image_stride
        sta tmp2
        jsr multiply
        sta near_len+1
        lda tmp1
        clc
        adc image_bytes
        sta near_len
        bcc :+
        inc near_len+1
:       jsr near_ok
        jeq range
@next:  lda image_at
        clc
        adc #5
        sta image_at
        bcc :+
        inc image_at+1
:       dec images_left
        bne image
        ; Commit. x0 = x / 2, at most 159.
        lda cfg_images
        sta _ti_scene_images
        lda cfg_images+1
        sta _ti_scene_images+1
        lda cfg_count
        sta _ti_scene_image_count
        lda cfg_x+1
        lsr a
        lda cfg_x
        ror a
        sta _ti_scene_x0
        lda cfg_y
        sta _ti_scene_y0
        lda cfg_height
        sta _ti_scene_lines
        lsr a
        lsr a
        lsr a
        pha
        lda _ti_scene_row_bytes
        clc
        adc #7
        lsr a
        lsr a
        lsr a
        sta _ti_scene_blocks
        lda cfg_background
        sta tmp1
        asl a
        asl a
        asl a
        asl a
        ora tmp1
        sta _ti_scene_fill
        lda cfg_service
        sta _ti_scene_service
        lda cfg_service+1
        sta _ti_scene_service+1
        ; screen = $2000 + y * 160 + x0, with y * 160 = y * 32 + y * 128.
        lda cfg_y
        sta tmp1
        stz tmp2
        ldx #5
@shift: asl tmp1
        rol tmp2
        dex
        bne @shift
        lda tmp1                   ; y * 32
        sta tmp3
        lda tmp2
        sta tmp4
        asl tmp1
        rol tmp2
        asl tmp1
        rol tmp2                   ; y * 128
        lda tmp1
        clc
        adc tmp3
        sta tmp1
        lda tmp2
        adc tmp4
        sta tmp2
        lda tmp1
        clc
        adc _ti_scene_x0
        sta _ti_scene_screen
        lda tmp2
        adc #$20
        sta _ti_scene_screen+1
        ; Strip rows row_bytes apart.
        lda #<_ti_scene_strip
        ldy #>_ti_scene_strip
        ldx #0
@rows:  sta _ti_scene_row_lo,x
        pha
        tya
        sta _ti_scene_row_hi,x
        pla
        clc
        adc _ti_scene_row_bytes
        bcc :+
        iny
:       inx
        cpx #8
        bne @rows
        ldx #74
@masks: stz _ti_scene_mask,x
        dex
        bpl @masks
        stz _ti_scene_count
        stz _ti_scene_end
        pla
        sta _ti_scene_bands
        lda #TI_OK
        tax
        rts

; ti_near_valid(near_ptr, near_len, read): Z set when the range is not
; readable near memory.
near_ok:
        lda near_ptr
        ldx near_ptr+1
        jsr pushax
        lda near_len
        ldx near_len+1
        jsr pushax
        lda #0
        jsr _ti_near_valid
        cmp #0
        rts

; A:tmp1 = tmp1 * tmp2, eight bits by eight.
multiply:
        lda #0
        ldx #8
        lsr tmp1
@m:     bcc :+
        clc
        adc tmp2
:       ror a
        ror tmp1
        dex
        bne @m
        rts

; ti_error ti_scene_add(int16_t x, int16_t y, uint8_t image, uint8_t color)
_ti_scene_add:
        sta new_color
        ldy #0
        lda (c_sp),y
        sta new_image
        iny
        lda (c_sp),y
        sta new_y
        iny
        lda (c_sp),y
        sta new_y+1
        iny
        lda (c_sp),y
        and #$FE                   ; sprites sit on even x
        sta new_x
        iny
        lda (c_sp),y
        sta new_x+1
        jsr incsp5
        lda _ti_scene_bands
        bne :+
        lda #TI_STATE
        ldx #0
        rts
:       lda new_image
        cmp _ti_scene_image_count
        bcc :+
        lda #TI_RANGE
        ldx #0
        rts
:       ldx _ti_scene_count
        cpx _ti_scene_capacity
        bcc :+
        lda #TI_FULL
        ldx #0
        rts
:       cpx _ti_scene_end
        bcs fresh                  ; nothing listed at this index yet
        ; The entry here is on screen or already marked: unchanged costs nothing.
        lda new_x
        cmp _ti_scene_x_lo,x
        bne moved
        lda new_x+1
        cmp _ti_scene_x_hi,x
        bne moved
        lda new_y
        cmp _ti_scene_y_lo,x
        bne moved
        lda new_y+1
        cmp _ti_scene_y_hi,x
        bne moved
        lda new_image
        cmp _ti_scene_image,x
        bne moved
        lda new_color
        cmp _ti_scene_color,x
        beq kept
moved:  jsr mark_item              ; where it was
        ldx _ti_scene_count
fresh:  lda new_x
        sta _ti_scene_x_lo,x
        lda new_x+1
        sta _ti_scene_x_hi,x
        lda new_y
        sta _ti_scene_y_lo,x
        lda new_y+1
        sta _ti_scene_y_hi,x
        lda new_image
        sta _ti_scene_image,x
        lda new_color
        sta _ti_scene_color,x
        jsr mark_item              ; where it is now
kept:   ldx _ti_scene_count
        inx
        stx _ti_scene_count
        cpx _ti_scene_end
        bcc :+
        stx _ti_scene_end
:       lda #TI_OK
        tax
        rts

; ti_error ti_scene_draw(void)
_ti_scene_draw:
        lda _ti_scene_bands
        beq no_scene
        lda _ti_video_backup
        ora _ti_video_backup+1
        bne :+
no_scene:
        lda #TI_STATE
        ldx #0
        rts
        ; Entries past the new list went away: erase where they were.
:       ldx _ti_scene_count
removed:
        cpx _ti_scene_end
        bcs listed
        jsr mark_item
        ldx item
        inx
        bra removed
listed: lda _ti_scene_count
        sta _ti_scene_end
        stz band
        lda _ti_scene_y0
        sta band_y
        lda _ti_scene_screen
        sta screen
        lda _ti_scene_screen+1
        sta screen+1
next_band:
        ldx band
        lda mask0,x
        ora mask1,x
        ora mask2,x
        beq serviced
        jsr find_runs
        jsr clear_runs
        jsr compose_band
        jsr publish_runs
serviced:
        lda band
        and #3
        cmp #3
        bne :+
        lda _ti_scene_service
        ldx _ti_scene_service+1
        beq :+                     ; no code lives in page zero: NULL
        jsr callax
:       inc band
        lda band
        cmp _ti_scene_bands
        bcs drawn
        lda screen+1               ; eight SHR lines: 1280 = $0500 bytes
        clc
        adc #5
        sta screen+1
        lda band_y
        clc
        adc #8
        sta band_y
        bra next_band
drawn:  jsr _ti_time_note_gap
        lda #TI_OK
        tax
        rts

; void ti_scene_invalidate(void)
_ti_scene_invalidate:
        lda _ti_scene_bands
        beq @done
        stz block0
        stz top
        ldx _ti_scene_blocks
        dex
        stx block1
        ldx _ti_scene_bands
        dex
        stx bottom
        jmp mark_blocks
@done:  rts

; Marked blocks of this band as runs of start byte and length; clears its masks.
find_runs:
        ldx band
        lda mask0,x
        sta bits
        lda mask1,x
        sta bits+1
        lda mask2,x
        sta bits+2
        stz mask0,x
        stz mask1,x
        stz mask2,x
        stz runs
        stz in_run
        ldx #0
@block: cpx _ti_scene_blocks
        bcs @end
        txa
        and #7
        tay
        lda bit_table,y
        sta tmp1
        txa
        lsr a
        lsr a
        lsr a
        tay
        lda bits,y
        and tmp1
        beq @clear
        lda in_run
        bne @next
        ldy runs
        txa
        asl a
        asl a
        asl a
        sta run_start,y
        inc in_run
        bra @next
@clear: lda in_run
        beq @next
        jsr close_run
@next:  inx
        bra @block
@end:   lda in_run
        beq @done
        jsr close_run
@done:  rts
; A run ends before block X; its last block may be cut by the area's edge.
close_run:
        ldy runs
        txa
        asl a
        asl a
        asl a
        cmp _ti_scene_row_bytes
        bcc :+
        lda _ti_scene_row_bytes
:       sec
        sbc run_start,y
        sta run_len,y
        inc runs
        stz in_run
        rts

; Background in every run of every strip row.
clear_runs:
        stz run_i
@run:   lda run_i
        cmp runs
        bcs @done
        tay
        lda run_start,y
        sta tmp2
        lda run_len,y
        sta tmp3
        ldx #7
@row:   lda _ti_scene_row_lo,x
        clc
        adc tmp2
        sta ptr1
        lda _ti_scene_row_hi,x
        adc #0
        sta ptr1+1
        lda _ti_scene_fill
        ldy tmp3
@byte:  dey
        sta (ptr1),y
        bne @byte
        dex
        bpl @row
        inc run_i
        bra @run
@done:  rts

; Publish each run: eight rows, SHR rows 160 bytes apart, strip rows
; row_bytes apart.
publish_runs:
        stz run_i
@run:   lda run_i
        cmp runs
        bcs @done
        tay
        lda run_start,y
        clc
        adc screen
        sta _ti_io_addr
        lda screen+1
        adc #0
        sta _ti_io_addr+1
        lda run_start,y
        clc
        adc _ti_scene_row_lo
        sta _ti_io_near
        lda _ti_scene_row_hi
        adc #0
        sta _ti_io_near+1
        lda run_len,y
        sta _ti_io_width
        lda #8
        sta _ti_io_rows
        lda _ti_scene_row_bytes
        sta _ti_io_stride
        stz _ti_io_stride+1
        jsr _ti_cpu_write_rows
        inc run_i
        bra @run
@done:  rts

; Every listed sprite that touches this band, in list order.
compose_band:
        ldx #0
@item:  cpx _ti_scene_count
        bcs @done
        lda band
        cmp _ti_scene_top,x        ; hidden sprites have top 255
        bcc @skip
        lda _ti_scene_bottom,x
        cmp band
        bcc @skip
        stx item
        jsr compose
        ldx item
@skip:  inx
        bra @item
@done:  rts

; X: entry to mark from its stored fields. Stores its band range, or top
; 255 when no part of it lies in the area.
mark_item:
        stx item
        jsr load_item
        jsr geometry
        ldx item
        bcc :+
        lda #255
        sta _ti_scene_top,x
        rts
:       lda top
        sta _ti_scene_top,x
        lda bottom
        sta _ti_scene_bottom,x
; One bit a block from block0 to block1, into every band top to bottom.
mark_blocks:
        stz bits
        stz bits+1
        stz bits+2
        ldx block0
@bit:   txa
        and #7
        tay
        lda bit_table,y
        sta tmp1
        txa
        lsr a
        lsr a
        lsr a
        tay
        lda bits,y
        ora tmp1
        sta bits,y
        cpx block1
        beq @bands
        inx
        bra @bit
@bands: ldx top
@band:  lda mask0,x
        ora bits
        sta mask0,x
        lda mask1,x
        ora bits+1
        sta mask1,x
        lda mask2,x
        ora bits+2
        sta mask2,x
        cpx bottom
        beq @done
        inx
        bra @band
@done:  rts

; X: entry to load into the work fields, with its image.
load_item:
        lda _ti_scene_x_lo,x
        sta work_x
        lda _ti_scene_x_hi,x
        sta work_x+1
        lda _ti_scene_y_lo,x
        sta work_y
        lda _ti_scene_y_hi,x
        sta work_y+1
        lda _ti_scene_color,x
        sta work_color
        lda _ti_scene_image,x
        sta work_image
        ; ptr4 = images + image * 5
        sta tmp1
        stz tmp2
        asl a
        rol tmp2
        asl a
        rol tmp2
        clc
        adc tmp1
        bcc :+
        inc tmp2
:       clc
        adc _ti_scene_images
        sta ptr4
        lda tmp2
        adc _ti_scene_images+1
        sta ptr4+1
        ldy #0
        lda (ptr4),y
        sta pixels
        iny
        lda (ptr4),y
        sta pixels+1
        iny
        lda (ptr4),y
        sta image_bytes
        iny
        lda (ptr4),y
        sta image_rows
        iny
        lda (ptr4),y
        sta image_stride
        ; Area-relative bytes across and lines down. x is even.
        lda work_x+1
        cmp #$80
        ror a
        sta rel_x+1
        lda work_x
        ror a
        sec
        sbc _ti_scene_x0
        sta rel_x
        lda rel_x+1
        sbc #0
        sta rel_x+1
        lda work_y
        sec
        sbc _ti_scene_y0
        sta rel_y
        lda work_y+1
        sbc #0
        sta rel_y+1
        rts

; The work sprite's bands and blocks; carry set when it misses the area.
geometry:
        lda rel_y
        sta clip_pos
        lda rel_y+1
        sta clip_pos+1
        lda image_rows
        sta clip_len
        lda _ti_scene_lines
        sta clip_limit
        jsr clip
        bcs @off
        lda clip_first
        lsr a
        lsr a
        lsr a
        sta top
        lda clip_last
        lsr a
        lsr a
        lsr a
        sta bottom
        lda rel_x
        sta clip_pos
        lda rel_x+1
        sta clip_pos+1
        lda image_bytes
        sta clip_len
        lda _ti_scene_row_bytes
        sta clip_limit
        jsr clip
        bcs @off
        lda clip_first
        lsr a
        lsr a
        lsr a
        sta block0
        lda clip_last
        lsr a
        lsr a
        lsr a
        sta block1
        clc
@off:   rts

; Signed 16-bit clip_pos, length 1..255 and limit 1..255: carry set when
; nothing overlaps 0..limit-1, else the first and last overlapping units.
clip:   lda clip_pos+1
        bmi @negative
        bne @off
        lda clip_pos
        cmp clip_limit
        bcs @off
        sta clip_first
        clc
        adc clip_len
        bcs @limit
        cmp clip_limit
        bcs @limit
        sbc #0                     ; carry clear: end - 1
        sta clip_last
        clc
        rts
@negative:
        cmp #$FF
        bne @off
        lda clip_pos
        beq @off                   ; -256
        clc
        adc clip_len
        bcc @off                   ; still before the area
        beq @off                   ; ends exactly at its start
        stz clip_first
        cmp clip_limit
        bcs @limit
        sbc #0                     ; carry clear: end - 1
        sta clip_last
        clc
        rts
@limit: ldx clip_limit
        dex
        stx clip_last
        clc
        rts
@off:   sec
        rts

; Compose sprite `item` into the strip for the current band. Both axes go
; through clip: the skipped source rows or bytes are first - position.
compose:
        ldx item
        jsr load_item
        sec
        lda work_y
        sbc band_y
        sta clip_pos
        lda work_y+1
        sbc #0
        sta clip_pos+1
        lda image_rows
        sta clip_len
        lda #8
        sta clip_limit
        jsr clip
        bcs @out
        lda clip_first
        sta dst_row
        sec
        sbc clip_pos
        sta src_row
        lda clip_last
        sec
        sbc clip_first
        inc a
        sta rows_left
        lda rel_x
        sta clip_pos
        lda rel_x+1
        sta clip_pos+1
        lda image_bytes
        sta clip_len
        lda _ti_scene_row_bytes
        sta clip_limit
        jsr clip
        bcc :+
@out:   rts
:       lda clip_first
        sta dst_col
        sec
        sbc clip_pos
        sta src_col
        lda clip_last
        sec
        sbc clip_first
        inc a
        sta columns
        ; ptr1 = strip row dst_row + dst_col
        ldx dst_row
        lda _ti_scene_row_lo,x
        clc
        adc dst_col
        sta ptr1
        lda _ti_scene_row_hi,x
        adc #0
        sta ptr1+1
        lda pixels+1
        bne sprite                 ; no image lives in page zero: NULL is a rectangle
        lda work_color
        and #15
        sta tmp1
        asl a
        asl a
        asl a
        asl a
        ora tmp1
        sta ink
@fill:  lda ink
        ldy columns
@fbyte: dey
        sta (ptr1),y
        bne @fbyte
        dec rows_left
        beq @done
        lda ptr1
        clc
        adc _ti_scene_row_bytes
        sta ptr1
        bcc @fill
        inc ptr1+1
        bra @fill
@done:  rts

; ptr2 = pixels + src_row * stride + src_col
sprite: lda src_row
        beq @offset
        sta tmp1
        lda image_stride
        sta tmp2
        jsr multiply
@offset:
        sta ptr2+1                 ; high byte of the product, or 0
        lda src_row
        beq :+
        lda tmp1                   ; low byte of the product
:       clc
        adc src_col
        bcc :+
        inc ptr2+1
:       clc
        adc pixels
        sta ptr2
        lda ptr2+1
        adc pixels+1
        sta ptr2+1
@row:   ldy #0
@byte:  lda (ptr2),y
        beq @next                  ; both pixels transparent
        tax
        and #$F0
        beq @low
        txa
        and #$0F
        beq @high
        txa
        sta (ptr1),y               ; both opaque
        bra @next
@low:   lda (ptr1),y               ; only the right pixel
        and #$F0
        sta tmp2
        txa
        ora tmp2
        sta (ptr1),y
        bra @next
@high:  lda (ptr1),y               ; only the left pixel
        and #$0F
        sta tmp2
        txa
        ora tmp2
        sta (ptr1),y
@next:  iny
        cpy columns
        bne @byte
        dec rows_left
        beq @done
        lda ptr1
        clc
        adc _ti_scene_row_bytes
        sta ptr1
        bcc :+
        inc ptr1+1
:       lda ptr2
        clc
        adc image_stride
        sta ptr2
        bcc @row
        inc ptr2+1
        bra @row
@done:  rts
