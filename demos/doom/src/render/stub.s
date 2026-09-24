; Doom for the Appletini -- render_frame stand-in (docs/DESIGN.md section 8).
;
; The platform's test pattern until the renderer (src/render/, section 7)
; replaces this file: it fills the view buffer (VIEWBUF, 160x84, column
; major) with a colour gradient that scrolls with the tic counter,
;       pixel(x, y) = x + y + 2 * ktics   (mod 256, a PLAYPAL index)
; and draws column stub_col in colour STUB_MARK: the mouse's running X
; (kmouse_x, input.s) followed modulo 160, at most 127 columns per frame.
; It runs in RENDER space from main memory, like the renderer will.

.include "kernel.inc"

.import ktics, kmouse_x

STUB_MARK   = 4                 ; PLAYPAL 4: white

.segment "RBSS"
stub_col:   .res 1              ; the marked column, 0..159
stub_last:  .res 2              ; kmouse_x when last drawn
.export stub_col

.segment "KZP": zeropage
sz_p:       .res 2
sz_v:       .res 1

.segment "RCODE"

render_frame:
        ; the marked column follows the mouse
        sec
        lda     kmouse_x
        sbc     stub_last
        tax
        lda     kmouse_x+1
        sbc     stub_last+1
        ; clamp the motion to -128..127
        bmi     @neg
        bne     @maxpos
        cpx     #$80
        bcc     @move
@maxpos:
        ldx     #$7F
        bra     @move
@neg:   cmp     #$FF
        bne     @maxneg
        cpx     #$80
        bcs     @move
@maxneg:
        ldx     #$80
@move:  lda     kmouse_x
        sta     stub_last
        lda     kmouse_x+1
        sta     stub_last+1
        txa
        bmi     @left
        clc
        adc     stub_col
        bcs     @wrap                   ; past 255
        cmp     #VIEW_W
        bcc     @set
@wrap:  sbc     #VIEW_W                 ; carry set on both paths
        bra     @set
@left:  clc
        adc     stub_col                ; col + motion (motion < 0)
        bcs     @set                    ; no borrow: still >= 0
        adc     #VIEW_W
@set:   sta     stub_col

        ; the gradient, column by column
        lda     #<VIEWBUF
        sta     sz_p
        lda     #>VIEWBUF
        sta     sz_p+1
        lda     ktics
        asl     a
        sta     sz_v                    ; 2 * ktics + x
        ldx     #0
@col:   lda     sz_v
        ldy     #0
        cpx     stub_col
        bne     @row
        lda     #STUB_MARK
:       sta     (sz_p),y
        iny
        cpy     #VIEW_H
        bne     :-
        bra     @next
@row:   sta     (sz_p),y
        inc     a
        iny
        cpy     #VIEW_H
        bne     @row
@next:  inc     sz_v
        clc
        lda     sz_p
        adc     #VIEW_H
        sta     sz_p
        bcc     :+
        inc     sz_p+1
:       inx
        cpx     #VIEW_W
        bne     @col
        rts
