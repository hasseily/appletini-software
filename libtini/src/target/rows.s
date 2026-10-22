; Every row of a checked bank 0 rectangle in one call, for
; ti_gfx_present_rows. Destination rows are 160 bytes apart, as in SHR. Each
; row goes out in bursts of at most 128 bytes through _ti_cpu_write, so IRQ
; masking and mapping stay in memory.s.
;
; Entry: ti_io_addr first destination, ti_io_near first source byte,
; ti_io_width 1..160 bytes per row, ti_io_rows 1..200 rows, ti_io_stride
; source bytes from one row to the next. The caller has checked every range.
.setcpu "65C02"
.export _ti_cpu_write_rows, _ti_io_width, _ti_io_rows, _ti_io_stride
.import _ti_cpu_write, _ti_io_bank, _ti_io_len, _ti_io_addr, _ti_io_near

.segment "BSS"
_ti_io_width:  .res 1
_ti_io_rows:   .res 1
_ti_io_stride: .res 2
row_addr:  .res 2
row_near:  .res 2
remaining: .res 1

.segment "CODE"
_ti_cpu_write_rows:
        stz _ti_io_bank
row:    lda _ti_io_addr
        sta row_addr
        lda _ti_io_addr+1
        sta row_addr+1
        lda _ti_io_near
        sta row_near
        lda _ti_io_near+1
        sta row_near+1
        lda _ti_io_width
        sta remaining
burst:  lda remaining
        cmp #129
        bcc :+
        lda #128
:       sta _ti_io_len
        jsr _ti_cpu_write
        lda remaining
        sec
        sbc _ti_io_len
        beq next_row
        sta remaining
        ; The rest of this row follows the burst.
        lda _ti_io_len
        clc
        adc _ti_io_addr
        sta _ti_io_addr
        bcc :+
        inc _ti_io_addr+1
:       lda _ti_io_len
        clc
        adc _ti_io_near
        sta _ti_io_near
        bcc burst
        inc _ti_io_near+1
        bra burst
next_row:
        dec _ti_io_rows
        beq done
        lda row_addr
        clc
        adc #160
        sta _ti_io_addr
        lda row_addr+1
        adc #0
        sta _ti_io_addr+1
        lda row_near
        clc
        adc _ti_io_stride
        sta _ti_io_near
        lda row_near+1
        adc _ti_io_stride+1
        sta _ti_io_near+1
        jmp row
done:   rts
