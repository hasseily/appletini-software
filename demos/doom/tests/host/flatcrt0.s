; Doom for the Appletini -- C start-up for the py65 harness (flat.cfg):
; the C stack, BSS cleared; the harness then calls _game_init itself.
.setcpu "65C02"
.export __STARTUP__ : absolute = 1
.export game_boot
.import zerobss, __STACKSTART__
.include "zeropage.inc"
.segment "STARTUP"
game_boot:
        lda     #<__STACKSTART__
        sta     sp
        lda     #>__STACKSTART__
        sta     sp+1
        jmp     zerobss
