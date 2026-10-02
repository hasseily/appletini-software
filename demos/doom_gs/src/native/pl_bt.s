; pl_bt.s: test only, not part of the game (milestone 11, part plclock;
; docs/m11-parts/plclock.md): the main program of the bridge's synthetic
; machine. The main card holds S2's player, pl_irq.s, the effect player
; (fx.s's card part) and the bridge; the aux card holds only the bridge's bytes at $FF00 and
; its vectors. GPL-2, the port's own.
;
;   bt_start    the main stack (S = $FF), snd_init, fx_init (the effects
;               on, none playing), the clock (PAL), eight
;               marker bytes pushed on the main stack ($01F8-$01FF: S is
;               $F7 after them), the mouse card's VBL on, then ALTZP on and
;               CLI: the loop runs on the aux zero page and the aux stack
;               with S from $F7, as the pair build's tic window would
;   bt_loop     pushes three values on the aux stack, counts in the aux
;               zero page ($10-$11), pulls and checks the values and the
;               registers: a value or a register an interrupt changed ends
;               at bt_fail (a2vm's stop). When the count's high byte
;               reaches bt_brkat (main memory; 0 never), a BRK with ALTZP
;               on: the bridge must reach pl_crash with ALTZP off

        .setcpu "65C02"

        .import snd_init, pl_clkset, fx_init
        .export bt_start, bt_loop, bt_fail, bt_brkat

ALTZPON     = $C009
MOUSE_MODE  = $C0AE
MOUSE_ACK   = $C0AF
MODE_VBL    = $09               ; enabled, the VBL interrupt
COUNT       = $10               ; the loop's count, aux zero page

        .segment "BTCODE"

bt_start:
        sei
        cld
        ldx #$FF
        txs
        jsr snd_init
        lda #0                  ; snd_probe's answer: native mode
        jsr fx_init             ;   (the effects on, none playing)
        lda #$00                ; PAL
        jsr pl_clkset
        ldx #7                  ; the markers $B7 .. $B0 at $01FF .. $01F8
:       txa
        ora #$B0
        pha
        dex
        bpl :-
        lda #MODE_VBL
        sta MOUSE_MODE
        lda #3
        sta MOUSE_ACK
        sta ALTZPON             ; the aux zero page and stack from here
        stz COUNT
        stz COUNT+1
        cli
bt_loop:
        ldx #$5A
        ldy #$A5
        lda #$3C
        pha
        phx
        phy
        cmp #$3C
        bne bt_fail
        inc COUNT
        bne :+
        inc COUNT+1
        lda COUNT+1
        cmp bt_brkat
        bne :+
        brk
        .byte $00
:       cpx #$5A
        bne bt_fail
        cpy #$A5
        bne bt_fail
        ply
        cpy #$A5
        bne bt_fail
        plx
        cpx #$5A
        bne bt_fail
        pla
        cmp #$3C
        beq bt_loop
bt_fail:
        bra bt_fail

        .segment "BTDATA"
bt_brkat:  .byte 0
