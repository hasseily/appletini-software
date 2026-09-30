; rrec.s: the records of the native renderer's front end (docs/RENDER.md
; 3.6; milestone 7, stage B): the batch buffer in W and its staging.
;
; The seg loops write each record into a 256-byte batch buffer in W
; (BATCH, RB bytes used), upstream's record with the column after the
; kind (a K_TEX 12 bytes, a K_FILL 6: lists.inc's fields, R_SRC the
; native texel slot). rec_flush copies the batch into the staging, aux 0
; $A000-$BFFF, then the spill banks RECSP_FIRST..RECSP_LAST ($0200-$BFFF
; each), one RAMWRT window an area; STG_BANK (0: aux 0) and STG_PTR, in
; the frame block, say where the next byte goes. When the staging and the
; spill are full the frame stops: STATUS = ST_RECORDS and BRK, in every
; build (RENDER.md 3.6: nothing is dropped silently; what the game does
; instead is milestone 8's decision). Upstream's
; lists and their early flush are not reproduced: the native front end
; stages the whole frame (RENDER.md 3.6), and milestone 8 buckets it by
; column for the replay.
;
;   rec_start   the frame's start (stage C): an empty batch and staging
;               (upstream's lists are empty when a frame starts: the replay
;               of the frame before emptied them)
;   rec_room    before a record of A bytes: the batch flushed when it has
;               no room for it. Keeps X. Out: Y = RB.
;   rec_flush   the batch into the staging (RB = 0 after). Keeps X.
;
; A GPL-2 derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/
; lists.inc, r_seg65.s: texRec, PLANEFILL): the same records.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .export rec_start, rec_room, rec_flush

        .segment "RENDERW"

; ---------------------------------------------------------------------------
; rec_start: no record yet: STG_BANK 0 (aux 0), STG_PTR = STAGE, RB = 0.
; ---------------------------------------------------------------------------
rec_start:
        stz STG_BANK
        lda #<STAGE
        sta STG_PTR
        lda #>STAGE
        sta STG_PTR+1
        stz RB
        rts

; ---------------------------------------------------------------------------
; rec_room: Y = RB, after a flush when the batch has no room for A bytes.
; ---------------------------------------------------------------------------
rec_room:
        clc
        adc RB
        bcs rec_flush_y         ; past 256 bytes: flush first
        ldy RB
        rts
rec_flush_y:
        jsr rec_flush
        ldy RB
        rts

; ---------------------------------------------------------------------------
; rec_flush: BATCH[0 .. RB) to the staging. Changes A, Y, FA_DST.
; ---------------------------------------------------------------------------
rec_flush:
        ldy RB
        beq @none
        lda STG_PTR
        sta FA_DST
        lda STG_PTR+1
        sta FA_DST+1
        ldy #0
@window:
        lda STG_BANK            ; one window an area
        sta RWBANK
        sta RAMWRTON
@byte:  lda BATCH,y
        sta (FA_DST)
        iny
        inc FA_DST
        bne @more
        inc FA_DST+1
        lda FA_DST+1
        cmp #>STAGE_END         ; the area's end ($C000 for all of them)
        beq @full
@more:  cpy RB
        bne @byte
        sta RAMWRTOFF
        stz RWBANK
        lda FA_DST
        sta STG_PTR
        lda FA_DST+1
        sta STG_PTR+1
        stz RB
@none:  rts

@full:  sta RAMWRTOFF           ; the next area: aux 0, then the spill banks
        stz RWBANK
        lda STG_BANK
        bne @spill
        lda #RECSP_FIRST - 1
@spill: cmp #RECSP_LAST
        bcs @over
        inc a
        sta STG_BANK
        stz FA_DST
        lda #>$0200
        sta FA_DST+1
        cpy RB
        bne @window
        lda FA_DST
        sta STG_PTR
        lda FA_DST+1
        sta STG_PTR+1
        stz RB
        rts
@over:  lda #ST_RECORDS         ; the staging and the spill are full
        sta STATUS
        brk
        .byte ST_RECORDS
