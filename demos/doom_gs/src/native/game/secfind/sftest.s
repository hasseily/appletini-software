; game/secfind/sftest.s: part secfind's test routine (test builds only:
; TESTBUILD; docs/game-parts/secfind.md). GPL-2, the port's own.
;
;   sf_t_mod3   mod3 of every word from GA_0-1 up, 16,384 of them, into
;               main $2000-$5FFF (a byte each): the exhaustive check of the
;               part's arithmetic helper against upstream's mod3
;               (tools/native/gparts/secfind.py --mod3)

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

.ifdef TESTBUILD
        .export sf_t_mod3
        .import mod3, fc_call, fc_unbuilt

        ; test-only code goes in the card's driver area, not the core
        ; (wave 1 as integrated: the core's room is the game's)
        .segment "DRIVER"
FC_HERE .set 0

sf_t_mod3:
        stz GA_2
        lda #$20
        sta GA_3
@next:  lda GA_0
        ldx GA_1
        FCALL mod3
        sta (GA_2)
        inc GA_0
        bne :+
        inc GA_1
:       inc GA_2
        bne @next
        inc GA_3
        lda GA_3
        cmp #$60
        bne @next
        rts
.endif
