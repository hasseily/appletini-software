; Optional callback for a complete stream already loaded in main RAM.
; Caller sets phs_mem_pos and exclusive phs_mem_end before phs_start.
; Refuses zero page, stack, ROM and I/O; never reads outside [$0200,$C000).
        .setcpu "65C02"
        .export phs_memory_read, phs_mem_end
        .exportzp phs_mem_pos
        .segment "ZEROPAGE"
phs_mem_pos:    .res 2
        .segment "BSS"
phs_mem_end:    .res 2
        .segment "CODE"
phs_memory_read:
        lda     phs_mem_pos+1
        cmp     #$02
        bcc     @end
        cmp     #$C0
        bcs     @end
        cmp     phs_mem_end+1
        bcc     @read
        bne     @end
        lda     phs_mem_pos
        cmp     phs_mem_end
        bcs     @end
@read:  lda     (phs_mem_pos)
        inc     phs_mem_pos
        bne     :+
        inc     phs_mem_pos+1
:       clc
        rts
@end:   sec
        rts
