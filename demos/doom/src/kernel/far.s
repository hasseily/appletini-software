; Doom for the Appletini -- far memory access (docs/DESIGN.md section 4).
;
; A far address is 3 bytes, lo, hi, bank: RamWorks bank `bank` (0..127),
; address $0200-$BFFF in it. A near address is one in the caller's own
; space ($0000-$01FF, the language card, or $0200-$BFFF of main memory in
; RENDER space / of bank 1 in GAME space). All routines work from both
; spaces (kspace) and return in the space they were called from, with
; $C073 = 1 again in GAME space. A transfer must not run past $BFFF of
; its bank: far arrays are chunked by element (descriptors, below), so no
; element and no chunk crosses a bank's end. far_len = 0 copies nothing.
;
;   far_read    far_len bytes from far_src to the near address far_ptr
;   far_write   far_len bytes from the near address far_ptr to far_dst
;   far_copy    far_len bytes from far_src to far_dst
;   far_elem    far_src = the address of element far_idx of the far array
;               whose descriptor is at the near address A/X
;
; RENDER space reads and writes directly: $C073 = the far bank, then RAMRD
; (read) or RAMWRT (write) on for the copy loop, which runs here in the
; language card. In GAME space RAMRD and RAMWRT are both on and both
; follow $C073, so a copy between bank 1 and another bank goes through
; kbuf, a 256-byte bounce buffer in the language card: per piece of up to
; 256 bytes, $C073 = the source bank and copy into kbuf, $C073 = the
; destination bank and copy out. far_copy always bounces. Every $C073
; write is a $Cxxx access (a 1 MHz bus cycle, and on the vTW it drains a
; pending motherboard mirror): the costs are measured in
; tests/test_platform.py and recorded in DESIGN.md section 8.
;
; Far array descriptor, 6 bytes (C: struct far_array in kernel.h):
;   +0 first bank, +1 base address (u16), +3 element size (u16),
;   +5 log2 of the elements per chunk (0..16)
; Element i lives in bank (first + (i >> log2)) at
; base + (i & (2^log2 - 1)) * size.
;
; Interrupts may stay on: the VBL handler touches neither $C073 nor RAMRD
; and RAMWRT.

.include "kernel.inc"

; ---------------------------------------------------------------------------
.segment "KZP": zeropage
far_src:    .res 3
far_dst:    .res 3
far_ptr:    .res 2
far_len:    .res 2
far_idx:    .res 2
fz_a:       .res 2              ; working source pointer
fz_b:       .res 2              ; working destination pointer
fz_rem:     .res 2              ; bytes left
fz_n:       .res 1              ; bytes in this piece (0 = 256)
fz_bank:    .res 1              ; the far bank of this transfer (bounce)

; ---------------------------------------------------------------------------
.segment "KBSS"
kbuf:       .res 256            ; the bounce buffer

; ---------------------------------------------------------------------------
.segment "KCODE"

; ---- far_read -------------------------------------------------------------
far_read:
        lda     far_src
        sta     fz_a
        lda     far_src+1
        sta     fz_a+1
        lda     far_ptr
        sta     fz_b
        lda     far_ptr+1
        sta     fz_b+1
        lda     kspace
        bne     @game
        lda     far_src+2
        sta     RAMWORKS
        sta     RAMRDON
        jsr     copy_len
        sta     RAMRDOFF
        rts
@game:  ; far (fz_a, bank far_src+2) -> kbuf -> near (fz_b, bank 1)
        lda     far_src+2
        sta     fz_bank
        jsr     start_pieces
@piece: jsr     next_piece
        bcs     @done
        lda     fz_bank
        sta     RAMWORKS
        jsr     a_to_kbuf
        lda     #GAME_BANK
        sta     RAMWORKS
        jsr     kbuf_to_b
        bra     @piece
@done:  rts

; ---- far_write ------------------------------------------------------------
far_write:
        lda     far_ptr
        sta     fz_a
        lda     far_ptr+1
        sta     fz_a+1
        lda     far_dst
        sta     fz_b
        lda     far_dst+1
        sta     fz_b+1
        lda     kspace
        bne     @game
        lda     far_dst+2
        sta     RAMWORKS
        sta     RAMWRTON
        jsr     copy_len
        sta     RAMWRTOFF
        rts
@game:  ; near (fz_a, bank 1) -> kbuf -> far (fz_b, bank far_dst+2)
        lda     far_dst+2
        sta     fz_bank
        jsr     start_pieces
@piece: jsr     next_piece
        bcs     @done
        lda     #GAME_BANK
        sta     RAMWORKS
        jsr     a_to_kbuf
        lda     fz_bank
        sta     RAMWORKS
        jsr     kbuf_to_b
        bra     @piece
@done:  lda     #GAME_BANK
        sta     RAMWORKS
        rts

; ---- far_copy -------------------------------------------------------------
far_copy:
        lda     far_src
        sta     fz_a
        lda     far_src+1
        sta     fz_a+1
        lda     far_dst
        sta     fz_b
        lda     far_dst+1
        sta     fz_b+1
        sta     RAMRDON
        sta     RAMWRTON
        jsr     start_pieces
@piece: jsr     next_piece
        bcs     @done
        lda     far_src+2
        sta     RAMWORKS
        jsr     a_to_kbuf
        lda     far_dst+2
        sta     RAMWORKS
        jsr     kbuf_to_b
        bra     @piece
@done:  lda     kspace
        bne     @game
        sta     RAMRDOFF
        sta     RAMWRTOFF
        rts
@game:  lda     #GAME_BANK
        sta     RAMWORKS
        rts

; ---- the pieces of a bounced transfer -------------------------------------
; start_pieces: fz_rem = far_len.
start_pieces:
        lda     far_len
        sta     fz_rem
        lda     far_len+1
        sta     fz_rem+1
        rts

; next_piece: C set when nothing is left; else fz_n = the next piece
; (256 as 0 when at least 256 bytes are left) and fz_rem is reduced.
next_piece:
        lda     fz_rem+1
        beq     @short
        dec     fz_rem+1
        stz     fz_n
        clc
        rts
@short: lda     fz_rem
        beq     @none
        sta     fz_n
        stz     fz_rem
        clc
        rts
@none:  sec
        rts

; a_to_kbuf: fz_n bytes (0 = 256) from (fz_a) into kbuf; fz_a advances.
a_to_kbuf:
        ldy     #0
@loop:  lda     (fz_a),y
        sta     kbuf,y
        iny
        cpy     fz_n
        bne     @loop
        ; fz_a += n (n = 0 means 256)
        tya
        beq     @page
        clc
        adc     fz_a
        sta     fz_a
        bcc     @done
@page:  inc     fz_a+1
@done:  rts

; kbuf_to_b: fz_n bytes (0 = 256) from kbuf to (fz_b); fz_b advances.
kbuf_to_b:
        ldy     #0
@loop:  lda     kbuf,y
        sta     (fz_b),y
        iny
        cpy     fz_n
        bne     @loop
        tya
        beq     @page
        clc
        adc     fz_b
        sta     fz_b
        bcc     @done
@page:  inc     fz_b+1
@done:  rts

; copy_len: far_len bytes from (fz_a) to (fz_b), whatever the switches say.
; Writes nothing but the destination and the zero page.
copy_len:
        ldy     #0
        ldx     far_len+1
        beq     @rest
@page:  lda     (fz_a),y
        sta     (fz_b),y
        iny
        bne     @page
        inc     fz_a+1
        inc     fz_b+1
        dex
        bne     @page
@rest:  ldx     far_len
        beq     @done
@byte:  lda     (fz_a),y
        sta     (fz_b),y
        iny
        dex
        bne     @byte
@done:  rts

; ---- far_elem -------------------------------------------------------------
; A/X = the descriptor (near), far_idx = the index -> far_src.
; Cost: about 30 cycles per bit of log2, plus 25 per bit of the in-chunk
; index up to its highest set bit (shift-and-add by the element size).
far_elem:
        sta     fz_a                    ; the descriptor
        stx     fz_a+1
        ldy     #5
        lda     (fz_a),y
        tax                             ; X = log2 (elements per chunk)
        ; chunk = idx >> log2 (fz_b), within = idx & (2^log2 - 1) (fz_rem)
        lda     far_idx
        sta     fz_b
        sta     fz_rem
        lda     far_idx+1
        sta     fz_b+1
        sta     fz_rem+1
        lda     #0
        sta     ktmp                    ; the mask, built as 2^log2 - 1
        sta     ktmp+1
        cpx     #0
        beq     @masked
@shift: lsr     fz_b+1
        ror     fz_b
        sec
        rol     ktmp
        rol     ktmp+1
        dex
        bne     @shift
@masked:
        lda     fz_rem
        and     ktmp
        sta     fz_rem
        lda     fz_rem+1
        and     ktmp+1
        sta     fz_rem+1
        ; bank = first + chunk
        lda     (fz_a)
        clc
        adc     fz_b
        sta     far_src+2
        ; product = within * size, 16 bits (ktmp+2..3 = size, shifted)
        ldy     #3
        lda     (fz_a),y
        sta     ktmp+2
        iny
        lda     (fz_a),y
        sta     ktmp+3
        ldy     #1                      ; far_src = base
        lda     (fz_a),y
        sta     far_src
        iny
        lda     (fz_a),y
        sta     far_src+1
@mul:   lda     fz_rem
        ora     fz_rem+1
        beq     @done
        lsr     fz_rem+1
        ror     fz_rem
        bcc     @next
        clc
        lda     far_src
        adc     ktmp+2
        sta     far_src
        lda     far_src+1
        adc     ktmp+3
        sta     far_src+1
@next:  asl     ktmp+2
        rol     ktmp+3
        bra     @mul
@done:  rts

.export kbuf
