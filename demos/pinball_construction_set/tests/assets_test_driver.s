; Pinball Construction Set for the Appletini -- test driver for tests/test_assets.py.
;
; Walks the generated build/assets.s tables in a 65C02 (py65) the way the
; renderer will: t_lookup selects the language-card bank an id lives in
; from spr_bank, reads the variant address from spr_dir and copies the
; variant's header (height, width in bytes) out of the card or RODATA;
; t_glyph copies a glyph and its advance out of font7 / font_adv;
; t_palette copies one palette entry.
;
; Interface: Python sets `param` (+0 id or glyph code or palette index,
; +1 x phase: 0 even, 1 odd), sets PC to a t_* label and runs until PC
; reaches `halt`; the answer is in `result`. Zero page: 2 bytes reserved
; in ZEROPAGE (the pointer). Bus cost: none, this never runs on the card.

.setcpu "65C02"
.include "assets.inc"
.import spr_dir, spr_w, spr_h, spr_hoty, spr_bank, font7, font_adv, palette0

.export t_lookup, t_glyph, t_palette, param, result, halt

ALTZPOFF  = $C008
ALTZPON   = $C009
LCBANK2RD = $C080
LCROM     = $C082
LCBANK1RD = $C088

.segment "ZEROPAGE"
ptr:    .res 2

.segment "BSS"
param:  .res 2
result: .res 8

.segment "CODE"

; result: +0 height, +1 width in bytes (the variant's own header),
; +2 spr_w, +3 spr_h, +4 spr_hoty, +5 spr_bank
t_lookup:
        ldx     param
        lda     spr_w,x
        sta     result+2
        lda     spr_h,x
        sta     result+3
        lda     spr_hoty,x
        sta     result+4
        lda     spr_bank,x
        sta     result+5
        and     #SPR_BANK_AUX
        beq     @point                  ; main memory: nothing to switch
        sta     ALTZPON                 ; the auxiliary set's card
        lda     spr_bank,x
        and     #SPR_BANK_1
        beq     @bank2
        lda     LCBANK1RD
        bra     @point
@bank2: lda     LCBANK2RD
@point:
        ; ptr = spr_dir + 4*id + 2*phase (id may be over 63: 16-bit)
        stz     ptr+1
        txa
        asl
        rol     ptr+1
        asl
        rol     ptr+1
        sta     ptr
        lda     param+1
        asl
        clc
        adc     ptr
        sta     ptr
        bcc     :+
        inc     ptr+1
:       clc
        lda     ptr
        adc     #<spr_dir
        sta     ptr
        lda     ptr+1
        adc     #>spr_dir
        sta     ptr+1
        lda     (ptr)
        tax
        ldy     #1
        lda     (ptr),y
        stx     ptr
        sta     ptr+1                   ; ptr -> the variant
        lda     (ptr)
        sta     result
        lda     (ptr),y
        sta     result+1
        bit     LCROM                   ; back to ROM reads and the main set,
        sta     ALTZPOFF                ; as the real code leaves things
        jmp     halt

; result: +0..6 the glyph rows, +7 its advance
t_glyph:
        lda     param
        asl
        asl
        asl
        sec
        sbc     param                   ; code*7, as the upstream PRCHAR
        clc
        adc     #<font7
        sta     ptr
        lda     #0
        adc     #>font7
        sta     ptr+1
        ldy     #FONT_ROWS-1
:       lda     (ptr),y
        sta     result,y
        dey
        bpl     :-
        ldx     param
        lda     font_adv,x
        sta     result+7
        jmp     halt

; result: +0, +1 the palette entry (little-endian $0RGB)
t_palette:
        lda     param
        asl
        tax
        lda     palette0,x
        sta     result
        lda     palette0+1,x
        sta     result+1
        jmp     halt

halt:   bra     halt
