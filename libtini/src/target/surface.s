; Rows of a banked surface, moved between a resource bank and the near row
; buffer without the per-call checks of ti_res_read and ti_res_write. The C
; callers have checked the surface and the rectangle. A surface is at most
; 32000 bytes, so it lies in at most two consecutive banks. Each burst is at
; most 128 bytes and ends at the bank's end: IRQs stay masked for one burst
; at a time, as for every other transfer.
;
; _ti_row_base_bank and _ti_row_base_addr locate the surface's first byte;
; _ti_row_bank and _ti_row_addr, $0200-$BFFF, the current row's first byte.
; _ti_row_bytes is 1..160 bytes a row, _ti_row_stride 1..160 between rows.
.setcpu "65C02"
.export _ti_row_seek, _ti_row_next, _ti_row_read, _ti_row_write
.export _ti_row_base_bank, _ti_row_base_addr, _ti_row_bank, _ti_row_addr
.export _ti_row_bytes, _ti_row_stride
.import _ti_cpu_read, _ti_cpu_write, _ti_io_bank, _ti_io_len, _ti_io_addr, _ti_io_near
.import _ti_gfx_rows

ROW       = _ti_gfx_rows + 3
BANK_END  = $C000       ; one past the last byte of a bank's window
BANK_SIZE = $BE00       ; 48640 bytes from $0200

.segment "BSS"
_ti_row_base_bank: .res 1
_ti_row_base_addr: .res 2
_ti_row_bank:   .res 1
_ti_row_addr:   .res 2
_ti_row_bytes:  .res 1
_ti_row_stride: .res 2
writing: .res 1
left:    .res 1

.segment "CODE"
; void ti_row_seek(uint16_t offset): the current row starts at the
; surface's byte offset, below 32000.
_ti_row_seek:
        clc
        adc _ti_row_base_addr
        sta _ti_row_addr
        txa
        adc _ti_row_base_addr+1
        ldx _ti_row_base_bank
        bcs over
        cmp #>BANK_END
        bcc found
        sbc #>BANK_SIZE         ; the carry is set
        bra next_bank
        ; Past $FFFF: $10000 - $BE00 = $4200 into the next bank.
over:   clc
        adc #>($10000 - BANK_SIZE)
next_bank:
        inx
found:  sta _ti_row_addr+1
        stx _ti_row_bank
        rts

; void ti_row_next(void): the current row moves _ti_row_stride bytes on.
_ti_row_next:
        clc
        lda _ti_row_addr
        adc _ti_row_stride
        sta _ti_row_addr
        lda _ti_row_addr+1
        adc _ti_row_stride+1
        cmp #>BANK_END
        bcc :+
        sbc #>BANK_SIZE
        inc _ti_row_bank
:       sta _ti_row_addr+1
        rts

; void ti_row_read(void) and ti_row_write(void): the current row's bytes
; to or from the row buffer.
_ti_row_read:
        lda #0
        bra move
_ti_row_write:
        lda #1
move:   sta writing
        lda _ti_row_bank
        sta _ti_io_bank
        lda _ti_row_addr
        sta _ti_io_addr
        lda _ti_row_addr+1
        sta _ti_io_addr+1
        lda #<ROW
        sta _ti_io_near
        lda #>ROW
        sta _ti_io_near+1
        lda _ti_row_bytes
        sta left
burst:  lda left
        cmp #129
        bcc :+
        lda #128
:       sta _ti_io_len
        sec
        lda #<BANK_END
        sbc _ti_io_addr
        tax
        lda #>BANK_END
        sbc _ti_io_addr+1
        bne :+
        cpx _ti_io_len
        bcs :+
        stx _ti_io_len
:       lda writing
        beq :+
        jsr _ti_cpu_write
        bra moved
:       jsr _ti_cpu_read
moved:  sec
        lda left
        sbc _ti_io_len
        beq done
        sta left
        clc
        lda _ti_io_near
        adc _ti_io_len
        sta _ti_io_near
        bcc :+
        inc _ti_io_near+1
:       clc
        lda _ti_io_addr
        adc _ti_io_len
        sta _ti_io_addr
        bcc :+
        inc _ti_io_addr+1
        ; A burst that reached the bank's end continues at $0200 of the next.
:       lda _ti_io_addr+1
        cmp #>BANK_END
        bcc burst
        lda #>$0200
        sta _ti_io_addr+1
        inc _ti_io_bank
        bra burst
done:   rts
