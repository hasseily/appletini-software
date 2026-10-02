; s2_beginstub.s: a TEST DOUBLE of s2_begin, part s2draw's test images
; only (s2dt, s2pt: docs/m11-parts/s2draw.md). It was the stand-in for
; part s2pal's s2_begin (src/native/s2_pal.s: the black palettes when a
; picture is new, then newColors: docs/SCREENS.md 1.3); since the first
; half's final integration (SCREENS.md 8.13) every other image links the
; real one, and this file stays as s2_publish's unit test double: it
; writes a pattern the test predicts, SCB n = $50 | (n & $0F), to the 200
; SCBs of aux 0 ($9D00-$9DC7) in one RAMWRT window, so the write log shows
; where s2_publish called it (s2_publish with the real s2_begin is part
; s2pal's checkpoint, on every frame's write log).

        .setcpu "65C02"
        .include "math.inc"
        .include "s2.inc"

        .export s2_begin

        .segment "S2CODE"

s2_begin:
        sta RAMWRTON
        ldx #0
:       txa
        and #$0F
        ora #$50
        sta SCB,x
        inx
        cpx #200
        bne :-
        sta RAMWRTOFF
        rts
