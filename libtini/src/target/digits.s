; ti_digits: count decimal digits of a 32-bit value, zero padded, then a NUL.
; Decimal mode doubles a five-byte BCD number once for each bit of the
; value, high bit first, instead of dividing by ten for every digit. The
; 65C02 clears the decimal flag for an interrupt, so the audio IRQ is safe.
.setcpu "65C02"
.include "zeropage.inc"
.export _ti_digits
.import pushax, incsp6, _ti_near_valid

.segment "BSS"
value:  .res 4          ; the C arguments, value then text
text:   .res 2
count:  .res 1
bcd:    .res 5          ; ten digits, the last two in the first byte

.segment "CODE"
; char *ti_digits(char *text, uint32_t value, uint8_t count)
_ti_digits:
        sta count
        ldy #5
:       lda (c_sp),y
        sta value,y
        dey
        bpl :-
        jsr incsp6
        lda count
        beq fail
        cmp #11
        bcs fail
        lda text
        ldx text+1
        jsr pushax
        lda count
        inc a
        ldx #0
        jsr pushax
        lda #1
        jsr _ti_near_valid
        cmp #0
        beq fail
        ldx #4
:       stz bcd,x
        dex
        bpl :-
        ldx #32
        sed
double: asl value
        rol value+1
        rol value+2
        rol value+3
        ; Y runs from -5 to -1, so the carry passes from byte to byte.
        ldy #<-5
:       lda bcd+5-256,y
        adc bcd+5-256,y
        sta bcd+5-256,y
        iny
        bne :-
        dex
        bne double
        cld
        lda text
        sta ptr1
        lda text+1
        sta ptr1+1
        ldy count
        lda #0
        sta (ptr1),y
        ldx #0
digit:  dey
        lda bcd,x
        and #$0F
        ora #'0'
        sta (ptr1),y
        tya
        beq done
        dey
        lda bcd,x
        lsr a
        lsr a
        lsr a
        lsr a
        ora #'0'
        sta (ptr1),y
        inx
        tya
        bne digit
done:   lda ptr1
        ldx ptr1+1
        rts
fail:   lda #0
        tax
        rts
