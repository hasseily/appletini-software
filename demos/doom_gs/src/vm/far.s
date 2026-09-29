; The far layer: every access to the virtual 24-bit address space goes
; through far_rd and far_wr, which translate with the map of vm.s.
;
;   far_rd      A = the byte at ea
;   far_wr      the byte A to ea
;   ea_next     ea to the next byte of the operand, by eawrap
;   resolve     the translation of one virtual page
;
; All of them may change X and Y. A write to a page held in the code
; cache is written to the cached copy too (write-through), so code that
; changes itself runs as written. Main RAM is never cached: code there
; runs in place.

        .segment "FAR"

; A = virtual bank, X = virtual page. Out: rspace (also in A, with N and
; Z from it) and rptr+1, the physical page. The last translation is kept.
resolve:
        cmp rk_bank
        bne resolve_look
        cpx rk_hi
        bne resolve_look
        lda rspace
        rts
resolve_look:
        sta rk_bank
        stx rk_hi
        txa
        asl a                   ; C = page bit 7
        lda rk_bank
        rol a                   ; A = half-bank mod 256, C = bank bit 7
        tay
        bcs :+
        lda map0,y
        bra @entry
:       lda map1,y
@entry: bmi @paged
        sta rspace              ; a flat granule
        txa
        and #$7F
        clc
        adc #$40
        sta rptr+1
        lda rspace
        rts
@paged: cmp #SP_TRAP
        beq @trap
        and #$7F
        clc
        adc #>PTAB
        sta ptp+1
        txa
        asl a
        tay
        lda (ptp),y
        sta rspace
        iny
        lda (ptp),y
        sta rptr+1
        lda rspace
        rts
@trap:  sta rspace
        lda #SP_TRAP            ; N set, as the callers test
        rts

far_rd: lda ea+2
        ldx ea+1
        jsr resolve
        ldy ea
        tax
        bmi @special
        cmp curbank
        bne @select
@read:  sta RDAUX
        lda (rptr),y
        sta RDMAIN
        rts
@select:
        sta curbank
        sta BANKSEL
        bra @read
@special:
        cmp #SP_MAIN
        bne @trap
        lda (rptr),y
        rts
@trap:  jmp (vm_trap_rd)

far_wr: sta wval
        lda ea+2
        ldx ea+1
        jsr resolve
        ldy ea
        tax
        bmi @special
        cmp curbank
        beq :+
        sta curbank
        sta BANKSEL
:       sta WRAUX
        lda wval
        sta (rptr),y
        sta WRMAIN
        lda rptr+1              ; a cached page?
        eor rspace
        tax
        lda watch,x
        bne @watched
        rts
@special:
        cmp #SP_MAIN
        bne @trap
        lda wval
        sta (rptr),y
        rts
@trap:  lda wval
        jmp (vm_trap_wr)
@watched:
        ldx #NSLOT - 1
@scan:  lda ctag_page,x
        cmp rptr+1
        bne @next
        lda ctag_space,x
        cmp rspace
        beq @hit
@next:  dex
        bpl @scan
        rts
@hit:   txa
        clc
        adc #>CACHE
        sta ptp+1
        lda wval
        sta (ptp),y
        rts

; ea to the next byte: carry into the bank (WR_LINEAR), wrap in bank
; (WR_BANK0) or wrap in the page (WR_PAGE).
ea_next:
        inc ea
        bne @done
        bit eawrap
        bvs @done
        inc ea+1
        bne @done
        bit eawrap
        bmi @done
        inc ea+2
@done:  rts
