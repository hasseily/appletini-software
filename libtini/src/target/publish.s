; The rows of a banked surface rectangle to the screen, for ti_gfx_present,
; which has checked them. target/surface.s reads each row into the near row
; buffer; this file writes it to SHR in bursts of at most 128 bytes.
;
; Entry: the surface.s current row at the rectangle's first source byte,
; with its row bytes and a stride of 160; _ti_pub_to the first screen byte;
; _ti_pub_rows 1..200 rows.
.setcpu "65C02"
.macpack longbranch
.export _ti_cpu_publish_rows, _ti_pub_to, _ti_pub_rows
.import _ti_row_read, _ti_row_next, _ti_row_bytes
.import _ti_cpu_write, _ti_io_bank, _ti_io_len, _ti_io_addr, _ti_io_near
.import _ti_gfx_rows

BUFFER = _ti_gfx_rows + 3

.segment "BSS"
_ti_pub_to:   .res 2
_ti_pub_rows: .res 1
left:   .res 1

.segment "LOWCODE"
_ti_cpu_publish_rows:
row:    jsr _ti_row_read
        stz _ti_io_bank
        lda _ti_pub_to
        sta _ti_io_addr
        lda _ti_pub_to+1
        sta _ti_io_addr+1
        lda #<BUFFER
        sta _ti_io_near
        lda #>BUFFER
        sta _ti_io_near+1
        lda _ti_row_bytes
        sta left
write:  lda left
        cmp #129
        bcc :+
        lda #128
:       sta _ti_io_len
        jsr _ti_cpu_write
        sec
        lda left
        sbc _ti_io_len
        beq next
        sta left
        clc
        lda _ti_io_addr
        adc _ti_io_len
        sta _ti_io_addr
        bcc :+
        inc _ti_io_addr+1
:       clc
        lda _ti_io_near
        adc _ti_io_len
        sta _ti_io_near
        bcc write
        inc _ti_io_near+1
        bra write
next:   jsr _ti_row_next
        clc
        lda _ti_pub_to
        adc #160
        sta _ti_pub_to
        bcc :+
        inc _ti_pub_to+1
:       dec _ti_pub_rows
        jne row
        rts
