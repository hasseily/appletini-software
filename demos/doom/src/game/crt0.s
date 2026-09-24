; Doom for the Appletini -- C run-time start-up of the GAME space
; (docs/DESIGN.md sections 4 and 9).
;
; The GAME space is RamWorks bank 1 seen at $0200-$BFFF (RAMRD and RAMWRT
; on, $C073 = 1). The loader put GAME.BIN there already linked at its run
; addresses, so DATA needs no copy. The kernel (kstart.s) calls game_boot
; once, in GAME space, through call_game:
;   1. the cc65 software stack: sp = __STACKSTART__ ($C000, growing down
;      to $B800, src/doom.cfg), in bank 1;
;   2. BSS cleared (cc65's zerobss, none.lib);
;   3. game_init(), and back to the kernel.
; After that the kernel calls game_tic() through call_game once per tic.
; cc65's zero page (sp, sreg, ptr1.., 26 bytes) is at $E0-$FF, shared by
; both spaces: only GAME-space code uses it.
;
; The C runtime is none.lib (cc65's target "none": the runtime helpers and
; the C library without any ROM or operating-system calls). This module
; exports __STARTUP__, so none.lib's own crt0 is not linked.

.setcpu "65C02"
.export __STARTUP__ : absolute = 1
.export game_boot
.import _game_init, zerobss
.import __STACKSTART__
.include "zeropage.inc"

.segment "STARTUP"

game_boot:
        lda     #<__STACKSTART__
        sta     sp
        lda     #>__STACKSTART__
        sta     sp+1
        jsr     zerobss
        jmp     _game_init
