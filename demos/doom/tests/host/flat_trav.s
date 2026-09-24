; Doom for the Appletini -- recording callbacks for the unit tests of
; a_maputl.s in the py65 harness (tests/test_game_asm.py).
;
;   _rec_trav    a traverser_t: appends the intercept (its 9 bytes) to rec_buf; returns 0 once rec_n
;                reaches rec_stop, else 1
;   _rec_thing   a thing callback: appends the thing pointer (2 bytes)
;   _rec_line    a line callback: appends the line's index (2 bytes)

.setcpu "65C02"
.include "zeropage.inc"
.export _rec_trav, _rec_thing, _rec_line, rec_buf, rec_n, rec_stop

.segment "BSS"
rec_buf:    .res 1024
rec_n:      .res 1
rec_stop:   .res 1

.segment "CODE"
; ptr2 = rec_buf + rec_n * A
rec_slot:
        sta     tmp1
        lda     #<rec_buf
        sta     ptr2
        lda     #>rec_buf
        sta     ptr2+1
        ldx     rec_n
        beq     @done
@add:   clc
        lda     ptr2
        adc     tmp1
        sta     ptr2
        bcc     :+
        inc     ptr2+1
:       dex
        bne     @add
@done:  rts

_rec_trav:
        sta     ptr1
        stx     ptr1+1
        lda     #9
        jsr     rec_slot
        ldy     #8
:       lda     (ptr1),y
        sta     (ptr2),y
        dey
        bpl     :-
        inc     rec_n
        lda     rec_n
        cmp     rec_stop
        beq     @stop
        lda     #1
        ldx     #0
        rts
@stop:  lda     #0
        tax
        rts

_rec_thing:
        pha
        phx
        lda     #2
        jsr     rec_slot
        ldy     #1
        pla
        sta     (ptr2),y
        pla
        sta     (ptr2)
        inc     rec_n
        lda     #1
        ldx     #0
        rts

_rec_line:
        sta     ptr1
        stx     ptr1+1
        lda     #2
        jsr     rec_slot
        lda     (ptr1)
        sta     (ptr2)
        ldy     #1
        lda     (ptr1),y
        sta     (ptr2),y
        inc     rec_n
        lda     #1
        ldx     #0
        rts
