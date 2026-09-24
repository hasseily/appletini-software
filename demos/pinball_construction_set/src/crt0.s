; Pinball Construction Set for the Appletini -- start-up code.
;
; ProDOS loads PCS.SYSTEM at $2000 and jumps there. This segment is linked
; first (STARTUP in pcs.cfg), so the first byte of the file is the first
; instruction below. Order of work:
;   1. interrupts off, binary mode, hardware stack reset; the power-up
;      byte at $03F4 is cleared so CTRL-RESET restarts the machine
;   2. the virtual TransWarp is released from any 1 MHz lock ($C074 = 0),
;      RAMRD/RAMWRT off
;   3. DATA is copied from its load image to $0C00+, BSS is cleared
;   4. PCS.SPR (sprites) is loaded into the auxiliary language card
;   5. main (main.s) takes over and never returns except to quit
;
; Interrupts stay disabled for the whole program.

.setcpu "65C02"
.include "pcs.inc"

.export __STARTUP__ : absolute = 1
.export exit_to_prodos
.import main, load_sprites
.import __DATA_LOAD__, __DATA_RUN__, __DATA_SIZE__
.import __BSS_RUN__, __BSS_SIZE__

.segment "ZEROPAGE"
c_src:  .res 2
c_dst:  .res 2

.segment "STARTUP"

start:
        sei
        cld
        ldx     #$FF
        txs
        stz     $03F4                   ; CTRL-RESET restarts the machine
        stz     TWSPEED                 ; full speed
        sta     RAMRDOFF
        sta     RAMWRTOFF
        sta     ALTZPOFF
        jsr     copy_data
        jsr     clear_bss
        jsr     load_sprites
        jmp     main

; DATA: load image (after the code in the SYS file) -> run address in LOW.
copy_data:
        lda     #<__DATA_LOAD__
        sta     c_src
        lda     #>__DATA_LOAD__
        sta     c_src+1
        lda     #<__DATA_RUN__
        sta     c_dst
        lda     #>__DATA_RUN__
        sta     c_dst+1
        ldx     #>__DATA_SIZE__
        ldy     #<__DATA_SIZE__
        jmp     copy_bytes

clear_bss:
        lda     #<__BSS_RUN__
        sta     c_dst
        lda     #>__BSS_RUN__
        sta     c_dst+1
        ldx     #>__BSS_SIZE__
        ldy     #<__BSS_SIZE__
; fill X*256+Y bytes at c_dst with zero
        lda     #0
@page:  cpx     #0
        beq     @rest
        phy
        ldy     #0
:       sta     (c_dst),y
        iny
        bne     :-
        inc     c_dst+1
        dex
        ply
        bra     @page
@rest:  cpy     #0
        beq     @done
        dey
:       sta     (c_dst),y
        dey
        bpl     :-
@done:  rts

; copy X*256+Y bytes from c_src to c_dst (ascending)
copy_bytes:
@page:  cpx     #0
        beq     @rest
        phy
        ldy     #0
:       lda     (c_src),y
        sta     (c_dst),y
        iny
        bne     :-
        inc     c_src+1
        inc     c_dst+1
        dex
        ply
        bra     @page
@rest:  cpy     #0
        beq     @done
        dey
:       lda     (c_src),y
        sta     (c_dst),y
        dey
        bpl     :-
@done:  rts

; Restore the text screen and hand control back to ProDOS. QUIT never
; returns; if it did, try again.
exit_to_prodos:
        sei
        cld
        ldx     #$FF
        txs
        sta     RAMRDOFF
        sta     RAMWRTOFF
        sta     ALTZPOFF
        lda     #$01
        sta     NEWVIDEO                ; SHR off
        sta     TEXTON
quit:
        jsr     MLI
        .byte   MLI_QUIT
        .word   quit_parms
        jmp     quit

quit_parms:
        .byte   $04                     ; parameter count
        .byte   $00                     ; quit type
        .word   $0000
        .byte   $00
        .word   $0000
