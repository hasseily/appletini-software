; Appletini Bosconian -- startup code.
;
; ProDOS loads BOSCO.SYSTEM at $2000 and jumps to $2000. This segment is
; linked first (STARTUP in bosconian.cfg), so the first byte of the file
; is the first instruction below.
;
; Order of work:
;   1. interrupts off, binary mode, hardware stack reset
;   2. copy the DATA segment from its load image ($2000+) to its run
;      address ($0C00+) and clear BSS
;   3. set the cc65 software stack pointer to __STACKSTART__
;   4. call main()
;   5. when main returns: text mode back on, SHR off, ProDOS QUIT
;
; Interrupts stay disabled for the whole program. Nothing in the game uses
; them and ProDOS's own QUIT path does not need them.

.setcpu "65C02"

.export __STARTUP__ : absolute = 1
.export _exit
.import _main, copydata, zerobss
.import __STACKSTART__
.include "zeropage.inc"

NEWVIDEO = $C029
TEXTON   = $C051
MLI      = $BF00

.segment "STARTUP"

start:
        sei
        cld
        ldx     #$FF
        txs
        jsr     copydata
        jsr     zerobss
        lda     #<__STACKSTART__
        sta     sp
        lda     #>__STACKSTART__
        sta     sp+1
        jsr     _main

; exit(): also reached when main() returns. Restore the text screen and
; hand control back to ProDOS. QUIT never returns; if it did, try again.
_exit:
        sei
        cld
        ldx     #$FF
        txs
        lda     #$01
        sta     NEWVIDEO        ; SHR off
        sta     TEXTON          ; text mode
quit:
        jsr     MLI
        .byte   $65             ; QUIT
        .word   quit_parms
        jmp     quit

quit_parms:
        .byte   $04             ; parameter count
        .byte   $00             ; quit type
        .word   $0000           ; reserved
        .byte   $00             ; reserved
        .word   $0000           ; reserved
