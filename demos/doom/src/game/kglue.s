; Doom for the Appletini -- the C interface to the kernel (GAME space).
;
; kernel.h declares these functions; each takes its C arguments (cc65's
; __fastcall__ convention: the last argument in A/X, or A/X/sreg for a
; long, the others on the C stack) into the kernel's zero-page parameters
; and calls the kernel through its jump table at $E000 (kstart.s), which
; stays where it is whatever the kernel's layout. A far_t is a C unsigned
; long: address in bits 0-15, bank in bits 16-23.

.setcpu "65C02"
.include "zeropage.inc"
.globalzp far_src, far_dst, far_ptr, far_len, far_idx, ktmp
.import kjt_far_read, kjt_far_write, kjt_far_copy, kjt_far_elem
.import kjt_set_palette, kjt_reboot, kjt_crash
.import popax, popeax

.export _far_read, _far_write, _far_copy, _far_elem, _far_peek
.export _set_palette, _kernel_reboot, _kernel_crash

.segment "CODE"

; void __fastcall__ far_read(far_t src, void *dst, unsigned int len)
_far_read:
        sta     far_len
        stx     far_len+1
        jsr     popax
        sta     far_ptr
        stx     far_ptr+1
        jsr     popeax
        sta     far_src
        stx     far_src+1
        lda     sreg
        sta     far_src+2
        jmp     kjt_far_read

; void __fastcall__ far_write(const void *src, far_t dst, unsigned int len)
_far_write:
        sta     far_len
        stx     far_len+1
        jsr     popeax
        sta     far_dst
        stx     far_dst+1
        lda     sreg
        sta     far_dst+2
        jsr     popax
        sta     far_ptr
        stx     far_ptr+1
        jmp     kjt_far_write

; void __fastcall__ far_copy(far_t src, far_t dst, unsigned int len)
_far_copy:
        sta     far_len
        stx     far_len+1
        jsr     popeax
        sta     far_dst
        stx     far_dst+1
        lda     sreg
        sta     far_dst+2
        jsr     popeax
        sta     far_src
        stx     far_src+1
        lda     sreg
        sta     far_src+2
        jmp     kjt_far_copy

; far_t __fastcall__ far_elem(const struct far_array *a, unsigned int index)
_far_elem:
        sta     far_idx
        stx     far_idx+1
        jsr     popax
        jsr     kjt_far_elem
        lda     far_src+2
        sta     sreg
        stz     sreg+1
        lda     far_src
        ldx     far_src+1
        rts

; unsigned char __fastcall__ far_peek(far_t a): one byte, through ktmp
_far_peek:
        sta     far_src
        stx     far_src+1
        lda     sreg
        sta     far_src+2
        lda     #1
        sta     far_len
        stz     far_len+1
        lda     #<ktmp
        sta     far_ptr
        stz     far_ptr+1
        jsr     kjt_far_read
        lda     ktmp
        ldx     #0
        rts

; void __fastcall__ set_palette(unsigned char n)
_set_palette    = kjt_set_palette
; void kernel_reboot(void), void __fastcall__ kernel_crash(unsigned char code)
_kernel_reboot  = kjt_reboot
_kernel_crash   = kjt_crash
