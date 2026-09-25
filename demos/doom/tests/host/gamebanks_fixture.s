; Actual banked routines used by tests/test_game_banks.py.
.setcpu "65C02"
.include "gamebanks.inc"
.import gb_init, gb_current, gb_irq, gb_nmi
.export start, finished, error, shared, visits, boot_a, entry_b, callback_a
.export gb_irq_service, fixture_main_irq, irq_count
.exportzp gmo=$40, gth=$42, gli=$44, gpt=$46
.exportzp sp=$E0, ptr1=$E8, regbank=$F4
.exportzp far_src=$60, far_dst=$63, far_ptr=$66, far_len=$68, far_idx=$6A, ktmp=$70
GAMEZP = $40
CZP = $E0
sreg = CZP+2
irq_count=$30
.segment "FIXTURE"
start:
    sei
    cld
    ldx #$ff
    txs
    jsr gb_init
    lda #$ad
    pha
    cli
    jsr call_a
    pla
    cmp #$ad
    beq finished
    inc error
finished:
    nop
    bra finished
call_a: GB_GATE 1, $d000
call_b: GB_GATE 2, $d000
call_a_callback: GB_GATE 1, $d500
call_kernel: GB_GATE GB_MAIN_CONTEXT, kernel_service
.segment "COMMON"
error: .byte 0
shared: .byte 0
visits: .byte 0
.macro FAIL_IF_NE
    beq :+
    inc error
:
.endmacro
.macro FILL_CONTEXT mask
    ldx #7
:   txa
    eor #mask
    sta GAMEZP,x
    dex
    bpl :-
    ldx #25
:   txa
    eor #mask
    sta CZP,x
    dex
    bpl :-
    ldx #11
:   txa
    eor #mask
    sta far_src,x
    dex
    bpl :-
    ldx #7
:   txa
    eor #mask
    sta ktmp,x
    dex
    bpl :-
.endmacro
.macro CHECK_CONTEXT mask
    .local game_loop, c_loop, far_loop, scratch_loop
    ldx #7
game_loop:
    txa
    eor #mask
    cmp GAMEZP,x
    FAIL_IF_NE
    dex
    bpl game_loop
    ldx #25
c_loop:
    txa
    eor #mask
    cmp CZP,x
    FAIL_IF_NE
    dex
    cpx #1
    bne c_loop
    ldx #11
far_loop:
    txa
    eor #mask
    cmp far_src,x
    FAIL_IF_NE
    dex
    bpl far_loop
    ldx #7
scratch_loop:
    txa
    eor #mask
    cmp ktmp,x
    FAIL_IF_NE
    dex
    bpl scratch_loop
.endmacro
.macro CHECK_SP address
    lda sp
    cmp #<address
    FAIL_IF_NE
    lda sp+1
    cmp #>address
    FAIL_IF_NE
.endmacro
.macro SET_SP address
    lda #<address
    sta sp
    lda #>address
    sta sp+1
.endmacro

.segment "BANKA"
boot_a:
    FILL_CONTEXT $50
    SET_SP $affa
    ldy #0
    lda #$ca
    sta (sp),y
    iny
    lda #$fe
    sta (sp),y
    lda #$a1
    pha
    inc shared
    inc visits
    lda #$11
    ldx #$22
    ldy #$33
    sec
    jsr call_b
    bcc :+
    inc error
:   cmp #$ab
    FAIL_IF_NE
    cpx #$cd
    FAIL_IF_NE
    cpy #$ef
    FAIL_IF_NE
    CHECK_SP $b000
    lda sreg
    cmp #$34
    FAIL_IF_NE
    lda sreg+1
    cmp #$12
    FAIL_IF_NE
    pla
    cmp #$a1
    FAIL_IF_NE
    lda $affa
    cmp #$ca
    FAIL_IF_NE
    lda $affb
    cmp #$fe
    FAIL_IF_NE
    rts

.segment "CALLBACKA"
callback_a:
    bcc :+
    inc error
:   cmp #$44
    FAIL_IF_NE
    cpx #$55
    FAIL_IF_NE
    cpy #$66
    FAIL_IF_NE
    CHECK_CONTEXT $70
    CHECK_SP $aff6
    lda shared
    clc
    adc #4
    sta shared
    inc visits
    ; Cross to the real main LC and back while the kernel changes C073.
    lda #0
    sta far_src
    lda #$20
    sta far_src+1
    lda #3
    sta far_src+2
    lda #<ktmp
    sta far_ptr
    stz far_ptr+1
    lda #1
    sta far_len
    stz far_len+1
    jsr call_kernel
    lda ktmp
    cmp #$a6
    FAIL_IF_NE
    lda far_src
    cmp #$56
    FAIL_IF_NE
    lda far_src+1
    cmp #$34
    FAIL_IF_NE
    lda far_src+2
    cmp #$12
    FAIL_IF_NE
    FILL_CONTEXT $a0
    SET_SP $aff8
    lda #$77
    ldx #$88
    ldy #$99
    sec
    rts

.segment "BANKB"
entry_b:
    bcs :+
    inc error
:   cmp #$11
    FAIL_IF_NE
    cpx #$22
    FAIL_IF_NE
    cpy #$33
    FAIL_IF_NE
    CHECK_CONTEXT $50
    CHECK_SP $affa
    lda #$b2
    pha
    lda shared
    clc
    adc #2
    sta shared
    inc visits
    FILL_CONTEXT $70
    SET_SP $aff6
    ldy #0
    lda #$be
    sta (sp),y
    iny
    lda #$ef
    sta (sp),y
    lda #$44
    ldx #$55
    ldy #$66
    clc
    jsr call_a_callback
    bcs :+
    inc error
:   cmp #$77
    FAIL_IF_NE
    cpx #$88
    FAIL_IF_NE
    cpy #$99
    FAIL_IF_NE
    CHECK_CONTEXT $a0
    CHECK_SP $aff8
    pla
    cmp #$b2
    FAIL_IF_NE
    lda $aff6
    cmp #$be
    FAIL_IF_NE
    lda $aff7
    cmp #$ef
    FAIL_IF_NE
    SET_SP $b000
    lda #$34
    sta sreg
    lda #$12
    sta sreg+1
    lda #$ab
    ldx #$cd
    ldy #$ef
    clc
    rts

.segment "MAINLC"
; Both main-context vectors and the aux IRQ bridge execute real main-LC code.
fixture_main_irq:
    pha
    phx
    phy
    jsr gb_irq_service
    ply
    plx
    pla
    rti
gb_irq_service:
    inc irq_count
    lda #$ea
    pha
    ldx #$ed
    ldy #$ef
    pla
    rts
kernel_service:
    lda far_src+2
    cmp #3
    FAIL_IF_NE
    sta $c073
    sta $c003
    lda $2000
    sta $c002
    sta ktmp
    lda #$56
    sta far_src
    lda #$34
    sta far_src+1
    lda #$12
    sta far_src+2
    rts
