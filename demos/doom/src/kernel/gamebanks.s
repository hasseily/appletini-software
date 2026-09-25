; Reentrant code-bank calls with independent suspended hardware stacks.
;
; GBANKCODE and GBANKBSS must remain in main $0200-$BFFF, even while a
; game code bank is mapped. GBANKCODE does not modify itself.
; Entry invariants: RAMRD/RAMWRT/80STORE off, LC bank 2 RAM readable.
; Code banks use ALTZP on and raw $C073 bank IDs; $80 denotes main context.
; Initialize all code-bank IRQ vectors to gb_irq before enabling IRQs.
;
; gb_init: once, ALTZP off, IRQs disabled, no suspended game calls; clobbers
; A/X/P. It initializes every suspended S to $FF and selects main context.
; The caller initializes the common cc65 software stack in the usual way.
;
; gb_call: reached by a GB_GATE (gamebanks.inc), whose three inline bytes
; are bank, address low, address high. All logical game zero-page state is
; passed into the callee and back, along with the kernel far arguments and
; ktmp scratch/results (54 bytes total), including the UPDATED cc65 software
; stack pointer. A/X/Y/P are passed both ways. The callee's RTS returns
; through gb_return and then to the gate's original caller. Each call's
; previous bank is stacked, so A->B->A and same-bank recursion are safe.
; The common software stack and all near data must stay in main memory.
;
; gb_irq: auxiliary-LC IRQ vector target. Saves registers on the interrupted
; auxiliary stack, borrows the suspended MAIN stack, and calls the imported
; gb_irq_service with main ZP/LC visible. The service returns with RTS,
; leaves RAMRD/RAMWRT/80STORE off and LC bank 2 selected, must not change
; $C073 or call banking gates, and must not enable nested IRQs. It may use
; main ZP/stack. gb_irq_status exposes the interrupted P byte (including
; BRK's B bit) so the service need not inspect the other context's stack.
; Main-context IRQ handling remains the kernel's responsibility.
;
; NMI sources must be disabled during banked execution: NMI's automatic
; stack pushes could occur between changing a bank and restoring S. The
; minimal gb_nmi is suitable only where the caller guarantees that rule;
; it does not make the bank-switch seam NMI-safe. Ordinary IRQs are masked
; for transitions, and every initialized bank has its own valid vectors.
;
; This module makes no TURBO timing assumptions. Non-base aux ZP, stack
; and code share the hardware's RamWorks cache and require measurement.

.include "kernel.inc"
.include "gamebanks.inc"
.include "zeropage.inc"
.importzp gmo, gth, gli, gpt
.import gb_irq_service
.export gb_init, gb_call, gb_return, gb_current, gb_saved_sp, gb_zp_shadow
.export gb_irq, gb_nmi, gb_irq_status, gb_export_zp, gb_import_zp
.assert gth = gmo+2, lderror, "game GZP must be contiguous"
.assert gli = gmo+4, lderror, "game GZP must be contiguous"
.assert gpt = gmo+6, lderror, "game GZP must be contiguous"
.assert regbank+regbanksize = sp+GB_C_ZP_SIZE, lderror, "unexpected cc65 zero-page layout"
.assert zpspace = GB_C_ZP_SIZE, error, "unexpected cc65 zero-page size"
.assert far_idx+2 = far_src+GB_FAR_ZP_SIZE, lderror, "kernel far arguments must be contiguous"
GB_FAR_OFFSET = GB_GAME_ZP_SIZE + GB_C_ZP_SIZE
GB_SCRATCH_OFFSET = GB_FAR_OFFSET + GB_FAR_ZP_SIZE

.segment "GBANKBSS"
gb_current:     .res 1
gb_saved_sp:    .res GB_CONTEXT_COUNT
gb_zp_shadow:   .res GB_ZP_SIZE
gb_a:           .res 1
gb_x:           .res 1
gb_y:           .res 1
gb_p:           .res 1
gb_target:      .res 3             ; bank, address lo, address hi
gb_previous:    .res 1             ; temporary, never live across callee
gb_irq_sp:      .res 1             ; IRQs cannot nest
gb_irq_status:  .res 1             ; interrupted P, including BRK's B bit

.macro GB_SAVE_REGS
    sta gb_a
    stx gb_x
    sty gb_y
    php
    sei
    pla
    sta gb_p
.endmacro
.macro GB_RESTORE_REGS
    lda gb_p
    pha
    lda gb_a
    ldx gb_x
    ldy gb_y
    plp
.endmacro

; Called inline, with IRQs off and Y = destination context. No stack use
; until TXS: the old S refers to a different physical stack after mapping.
.macro GB_SELECT_CONTEXT
    tya
    cmp #GB_MAIN_CONTEXT
    beq main
    sta RAMWORKS
    sta ALTZPON
    bra selected
main:
    sta ALTZPOFF
selected:
    ldx gb_saved_sp,y
    txs
.endmacro

.segment "GBANKCODE"
gb_init:
    lda #$FF
    ldx #GB_CONTEXT_COUNT-1
:   sta gb_saved_sp,x
    dex
    cpx #$FF
    bne :-
    lda #GB_MAIN_CONTEXT
    sta gb_current
    rts

; Each helper's own JSR/RTS completes in one mapping. Do not call either
; from an interrupt; they deliberately clobber the logical ZP shadow.
gb_export_zp:
    ldx #GB_GAME_ZP_SIZE-1
:   lda gmo,x
    sta gb_zp_shadow,x
    dex
    bpl :-
    ldx #GB_C_ZP_SIZE-1
:   lda sp,x
    sta gb_zp_shadow+GB_GAME_ZP_SIZE,x
    dex
    bpl :-
    ldx #GB_FAR_ZP_SIZE-1
:   lda far_src,x
    sta gb_zp_shadow+GB_FAR_OFFSET,x
    dex
    bpl :-
    ldx #GB_SCRATCH_ZP_SIZE-1
:   lda ktmp,x
    sta gb_zp_shadow+GB_SCRATCH_OFFSET,x
    dex
    bpl :-
    rts

gb_import_zp:
    ldx #GB_GAME_ZP_SIZE-1
:   lda gb_zp_shadow,x
    sta gmo,x
    dex
    bpl :-
    ldx #GB_C_ZP_SIZE-1
:   lda gb_zp_shadow+GB_GAME_ZP_SIZE,x
    sta sp,x
    dex
    bpl :-
    ldx #GB_FAR_ZP_SIZE-1
:   lda gb_zp_shadow+GB_FAR_OFFSET,x
    sta far_src,x
    dex
    bpl :-
    ldx #GB_SCRATCH_ZP_SIZE-1
:   lda gb_zp_shadow+GB_SCRATCH_OFFSET,x
    sta ktmp,x
    dex
    bpl :-
    rts

gb_call:
    GB_SAVE_REGS
    ; Preserve the complete logical context before borrowing ptr1 for the
    ; descriptor. The callee's import restores its original argument value.
    jsr gb_export_zp
    ; Remove only the stub's JSR return (descriptor address minus one).
    pla
    sta ptr1
    pla
    sta ptr1+1
    inc ptr1
    bne :+
    inc ptr1+1
:   ldy #2
read_descriptor:
    lda (ptr1),y
    sta gb_target,y
    dey
    bpl read_descriptor
    tsx
    ldy gb_current
    txa
    sta gb_saved_sp,y
    sty gb_previous
    ldy gb_target
    sty gb_current
    .scope enter
        GB_SELECT_CONTEXT
    .endscope
    jsr gb_import_zp
    lda gb_previous
    pha
    lda #>(gb_return-1)
    pha
    lda #<(gb_return-1)
    pha
    GB_RESTORE_REGS
    jmp (gb_target+1)

gb_return:
    GB_SAVE_REGS
    jsr gb_export_zp
    pla
    sta gb_previous
    tsx
    ldy gb_current
    txa
    sta gb_saved_sp,y
    ldy gb_previous
    sty gb_current
    .scope leave
        GB_SELECT_CONTEXT
    .endscope
    jsr gb_import_zp
    GB_RESTORE_REGS
    rts

gb_irq:
    pha
    phx
    phy
    tsx
    stx gb_irq_sp
    lda $0104,x                    ; P pushed by IRQ/BRK, below A/X/Y
    sta gb_irq_status
    sta ALTZPOFF
    ldx gb_saved_sp+GB_MAIN_CONTEXT
    txs
    jsr gb_irq_service
    sta ALTZPON
    ldx gb_irq_sp
    txs
    ply
    plx
    pla
    rti

gb_nmi:
    rti
