; auxlc.s: the renderer's reads of the aux card's tables, F1.2.1
; (docs/MEMORY_MAP.md, docs/RENDER.md).
;
; The aux card holds read-only tables (tools/native/rtables.py writes
; them): finetangent part 3 (bank 1 $D000 low bytes, $D400 high bytes),
; viewangletox (bank 1 $D800, one plane of 2,042 bytes: upstream's
; values 0-160 are bytes, r_bsp65.s:524-534, :1106-1235), finetangent
; part 4 (bank 2 $D000, four planes of 1,024) and tantoangle entries
; 0-2047 ($E000, four planes of 2,048).
;
; A read is a window of straight-line code in W (MEMORY_MAP rule 7): SEI,
; ALTZP on, the loads into registers (or into main $0200-$BFFF, which
; ALTZP leaves main), ALTZP off, CLI. With ALTZP on, zero page, the stack
; and the card are the aux bank's, so nothing inside touches them, and the
; code runs from W: its operand's high byte is set before each window
; (self-modification in W only, RENDER.md). $C073 is 0 between
; windows, so the aux card is aux bank 0's.

        .setcpu "65C02"
        .include "rlayout.inc"

        .export ax_vtox, ax_tanto, ax_tan3, ax_tan4, ax_out
        ; the operands each window sets (self-modified operands)
        .export axv_rd, axt_b2, axt_b3, ax3_lo, ax3_hi
        .export ax4_b0, ax4_b1, ax4_b2, ax4_b3

ALTZPOFF = $C008
ALTZPON  = $C009
LCBANK2  = $C083
LCBANK1  = $C08B

        .segment "AUXW"         ; (both W images: RENDER-MASKED.md)

; ---------------------------------------------------------------------------
; ax_vtox: A = viewangletoxTable[i], i = A:X (A the high byte, 0-7; i at
; most 2,041). Changes nothing else.
; ---------------------------------------------------------------------------
ax_vtox:
        clc
        adc #>AX_VTOX
        sta axv_rd+2
        sei
        sta ALTZPON
axv_rd:    lda AX_VTOX,x
        sta ALTZPOFF
        cli
        rts

; ---------------------------------------------------------------------------
; ax_tanto: A = byte 2, Y = byte 3 of tantoangle[i], i = A:X (A the high
; byte, 0-7; entry 2,048 is not in the card: math.s's pta16 keeps it).
; Changes A, Y.
; ---------------------------------------------------------------------------
ax_tanto:
        pha
        clc
        adc #>(AX_TANTO + $1000)
        sta axt_b2+2
        pla
        clc
        adc #>(AX_TANTO + $1800)
        sta axt_b3+2
        sei
        sta ALTZPON
axt_b2:    lda AX_TANTO + $1000,x
axt_b3:    ldy AX_TANTO + $1800,x
        sta ALTZPOFF
        cli
        rts

; ---------------------------------------------------------------------------
; ax_tan3: A = low, Y = high byte of finetangentTable_part_3[i], i = A:X
; (A the high byte, 0-3). Changes A, Y.
; ---------------------------------------------------------------------------
ax_tan3:
        pha
        clc
        adc #>AX_TAN3
        sta ax3_lo+2
        pla
        clc
        adc #>(AX_TAN3 + $0400)
        sta ax3_hi+2
        sei
        sta ALTZPON
ax3_lo:    lda AX_TAN3,x
ax3_hi:    ldy AX_TAN3 + $0400,x
        sta ALTZPOFF
        cli
        rts

; ---------------------------------------------------------------------------
; ax_tan4: ax_out (4 bytes, W) = finetangentTable_part_4[i], i = A:X (A
; the high byte, 0-3), from the card's bank 2 (selected inside the window,
; bank 1 again before it closes). Changes A, Y.
; ---------------------------------------------------------------------------
ax_tan4:
        clc
        adc #>AX_TAN4
        sta ax4_b0+2
        adc #>$0400             ; (no carry out of the adds: $D0-$DF)
        sta ax4_b1+2
        adc #>$0400
        sta ax4_b2+2
        adc #>$0400
        sta ax4_b3+2
        sei
        sta ALTZPON
        lda LCBANK2             ; bank 2, RAM read and write
        lda LCBANK2
ax4_b0:    lda AX_TAN4,x
        sta ax_out
ax4_b1:    lda AX_TAN4 + $0400,x
        sta ax_out+1
ax4_b2:    lda AX_TAN4 + $0800,x
        sta ax_out+2
ax4_b3:    lda AX_TAN4 + $0C00,x
        sta ax_out+3
        lda LCBANK1             ; bank 1 again
        lda LCBANK1
        sta ALTZPOFF
        cli
        rts

ax_out: .res 4
