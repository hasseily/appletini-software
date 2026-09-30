; mathdrv.s: the a2vm test driver of the native math (not part of the
; game). tools/native/mathrun.py fills its descriptor (drv_desc) and the
; cases; for each case the driver copies the input bytes to their places
; (the math block, the random indexes, or the registers A, X, Y through
; DRV_IA-DRV_IY), calls the routine with the cost phase 1 around the call,
; and copies the output bytes (DRV_OA-DRV_OY: the registers after the
; call) to the results.
;
; Cases and results are records packed one after the other, in main
; memory (bank 0: from the base to the limit page) or in RamWorks banks
; (from the base of the first bank to the limit page, then the next
; bank), read and written with RAMRD and RAMWRT on. The driver runs from
; the card ($E000), which RAMRD and RAMWRT leave alone.

        .setcpu "65C02"
        .include "math.inc"

        .import mt_init
        .export drv_start, drv_halt, drv_stub, drv_desc, drv_call
        .exportzp DRV_IA, DRV_IX, DRV_IY, DRV_OA, DRV_OX, DRV_OY
        .export PHASE

PHASE   = $0300             ; the cost phase byte (a2vm --cost-phase)

DRV_IA  = $E0               ; the registers into the call
DRV_IX  = $E1
DRV_IY  = $E2
DRV_OA  = $E3               ; and out of it
DRV_OX  = $E4
DRV_OY  = $E5
IP      = $E6               ; the next case
OP      = $E8               ; the next result
IB      = $EA               ; their banks (0: main memory)
OB      = $EB
CNT     = $EC               ; cases left, 3 bytes
DP      = $F0               ; the place of a byte

        .segment "DRIVER"

drv_start:
        ldx #$FF
        txs
        jsr mt_init
        lda d_inbank
        sta IB
        lda d_outbank
        sta OB
        lda d_inbase
        sta IP
        lda d_inbase+1
        sta IP+1
        lda d_outbase
        sta OP
        lda d_outbase+1
        sta OP+1
        lda d_count
        sta CNT
        lda d_count+1
        sta CNT+1
        lda d_count+2
        sta CNT+2
@case:  lda CNT
        ora CNT+1
        ora CNT+2
        bne :+
        jmp drv_halt
:
        ldx IB                  ; the inputs
        beq :+
        stx RWBANK
        sta RAMRDON
:       ldy #0
@in:    cpy d_nin
        beq @indone
        lda d_inlo,y
        sta DP
        lda d_inhi,y
        sta DP+1
        lda (IP),y
        sta (DP)
        iny
        bra @in
@indone:
        ldx IB
        beq :+
        sta RAMRDOFF
        stz RWBANK
:       lda #2                  ; phase 1: the call
        sta PHASE
        lda DRV_IA
        ldx DRV_IX
        ldy DRV_IY
        jsr drv_call
        sta DRV_OA
        stx DRV_OX
        sty DRV_OY
        stz PHASE
        ldx OB                  ; the outputs
        beq :+
        stx RWBANK
        sta RAMWRTON
:       ldy #0
@out:   cpy d_nout
        beq @outdone
        lda d_outlo,y
        sta DP
        lda d_outhi,y
        sta DP+1
        lda (DP)
        sta (OP),y
        iny
        bra @out
@outdone:
        ldx OB
        beq :+
        sta RAMWRTOFF
        stz RWBANK
:       clc                     ; the next case
        lda IP
        adc d_nin
        sta IP
        bcc :+
        inc IP+1
        lda IP+1
        cmp d_limit
        bne :+
        lda d_inbase+1
        sta IP+1
        inc IB
:       clc                     ; the next result
        lda OP
        adc d_nout
        sta OP
        bcc :+
        inc OP+1
        lda OP+1
        cmp d_limit
        bne :+
        lda d_outbase+1
        sta OP+1
        inc OB
:       lda CNT                 ; one case fewer
        bne @c0
        lda CNT+1
        bne @c1
        dec CNT+2
@c1:    dec CNT+1
@c0:    dec CNT
        jmp @case

drv_call:
        jmp (d_entry)

drv_halt:
        bra drv_halt

drv_stub:
        rts

; the descriptor, filled by mathrun.py
        .segment "DESC"
drv_desc:
d_entry:    .res 2          ; the routine
d_nin:      .res 1          ; input bytes a case (a power of 2)
d_nout:     .res 1          ; output bytes a result (a power of 2)
d_count:    .res 3          ; cases
d_inbank:   .res 1          ; 0: main memory
d_outbank:  .res 1
d_inbase:   .res 2          ; the first case (page aligned)
d_outbase:  .res 2
d_limit:    .res 1          ; the page after a bank's cases or results
            .res 2
d_inlo:     .res 16         ; each input byte's place
d_inhi:     .res 16
d_outlo:    .res 16         ; each output byte's place
d_outhi:    .res 16
