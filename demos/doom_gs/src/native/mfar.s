; mfar.s: the masked phase's card code (docs/RENDER-MASKED.md 3.2, 3.5;
; milestone 8, stage A), in the main card's bank 1 after far.s (segment
; MFAR): the loader of the masked phase's image and the loops that run
; inside its read windows, which must be card code (MEMORY_MAP.md rule 5).
;
;   far_mload   the masked image from RamWorks bank MCODE_BANK into W: its
;               code (from MCODE, after the shared MATHW and AUXW, which it
;               leaves in place: they are the front end's image's, loaded
;               at the frame's start) to the image's end (stage C: the
;               whole frame's builds carry the bucket pass's BKFAR after
;               the code), and its per-level table's pages (TXMP), through
;               far.s's far_pload. Changes A, X, Y, FA_SRC, FA_DST, FA_N.
;   far_dscopy  the dsw_n drawsegs of RENDB whose indexes are in dsw_idx
;               into W from DSW, DS_SIZE bytes each, in that order. One
;               RAMRD window. Changes A, X, Y, FA_SRC, FA_DST.
;   far_posts   (stage B) the posts of a patch column, as upstream's
;               visCol, fzCol and mwCol walk them (r_seg65.s:2906-2917,
;               :2953-2966; r_frame65.s:1351-1360, :1618-1625): FA_SRC =
;               the column's entry of columnofs, FA_DST = the patch's
;               address, FA_BANK its bank. The column is the patch's
;               address + the entry's low word (16 bits: no lump crosses a
;               bank of the store); each post (topdelta, length, the pad,
;               the texels, the pad; topdelta $FF ends the column) gives
;               pt_td, pt_len and its address pt_lo/pt_hi, at most PT_MAX:
;               pt_n posts, and pt_more bit 7 when the buffer is full
;               (far_postsc goes on from FA_SRC, the next post). One RAMRD
;               window. Changes A, X, Y, FA_SRC.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import far_pload
        .import __MASKW_RUN__, __WM_LAST__
        .import __AUXW_RUN__, __AUXW_SIZE__
        .export far_mload, far_dscopy, dsw_n, dsw_idx
        .export far_posts, far_postsc, pt_n, pt_more, pt_td, pt_len
        .export pt_lo, pt_hi, PT_MAX
.ifdef CLIPLOG
        .export m_hook
.endif

.assert __AUXW_RUN__ + __AUXW_SIZE__ <= MCODE, lderror, "the shared W part passes MCODE"
.assert __MASKW_RUN__ = MCODE, lderror, "the masked code is not at MCODE"

        .segment "MFAR"

MASK_FIRST = >MCODE
far_mload:
        lda #<wl_mask
        ldx #>wl_mask
        ldy #MCODE_BANK
        jmp far_pload
wl_mask:
        .byte MASK_FIRST, <(((__WM_LAST__ + $FF) >> 8) - MASK_FIRST)
        .byte MTABLES_PAGE, MTABLES_PAGES, 0
.assert >wl_mask = >(wl_mask + 4), lderror, "the loader's list crosses a page"

far_dscopy:
        lda #RENDB
        sta RWBANK
        sta RAMRDON
        lda #<DSW
        sta FA_DST
        lda #>DSW
        sta FA_DST+1
        ldx #0
@next:  cpx dsw_n
        beq @done
        lda dsw_idx,x           ; DRAWSEGS + 32 i
        stz FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        clc
        adc #<DRAWSEGS
        sta FA_SRC
        lda FA_SRC+1
        adc #>DRAWSEGS
        sta FA_SRC+1
        ldy #DS_SIZE - 1
:       lda (FA_SRC),y
        sta (FA_DST),y
        dey
        bpl :-
        clc
        lda FA_DST
        adc #DS_SIZE
        sta FA_DST
        bcc :+
        inc FA_DST+1
:       inx
        bra @next
@done:  sta RAMRDOFF
        stz RWBANK
        rts
dsw_n:  .res 1                  ; the drawsegs to copy, their indexes
dsw_idx: .res DSW_MAX

; ---------------------------------------------------------------------------
; far_posts, far_postsc: a column's posts into the card's buffer (above)
; ---------------------------------------------------------------------------
PT_MAX = 16
far_posts:
        lda FA_BANK
        sta RWBANK
        sta RAMRDON
        lda (FA_SRC)            ; the column: the patch + columnofs' low word
        clc
        adc FA_DST
        tax
        ldy #1
        lda (FA_SRC),y
        adc FA_DST+1
        sta FA_SRC+1
        stx FA_SRC
        bra fp_walk
far_postsc:
        lda FA_BANK
        sta RWBANK
        sta RAMRDON
fp_walk:
        ldx #0
@post:  lda (FA_SRC)            ; topdelta, $FF: no more posts
        cmp #$FF
        beq @end
        sta pt_td,x
        ldy #1
        lda (FA_SRC),y          ; length
        sta pt_len,x
        lda FA_SRC
        sta pt_lo,x
        lda FA_SRC+1
        sta pt_hi,x
        lda pt_len,x            ; the next post: + length + 4
        clc
        adc #4
        bcc :+
        inc FA_SRC+1
        clc
:       adc FA_SRC
        sta FA_SRC
        bcc :+
        inc FA_SRC+1
:       inx
        cpx #PT_MAX
        bne @post
        lda #$80                ; the buffer is full: FA_SRC the next post
        bra @out
@end:   lda #0
@out:   sta pt_more
        stx pt_n
        sta RAMRDOFF
        stz RWBANK
        rts
.ifdef CLIPLOG
; m_hook (test builds only): the harness's snapshot of the masked phase at
; the weapon's draw (nm_masked calls it first): a card address, which no
; code of the front end's image shares, as W's addresses are
m_hook: rts
.endif
pt_n:   .res 1
pt_more: .res 1
pt_td:  .res PT_MAX
pt_len: .res PT_MAX
pt_lo:  .res PT_MAX
pt_hi:  .res PT_MAX
