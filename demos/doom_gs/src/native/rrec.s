; rrec.s: the records of the native renderer (docs/RENDER.md 3.6;
; milestone 7, stage B; milestone 8, stage B: docs/RENDER-MASKED.md 3.4):
; the batch buffer in W and its staging, and the model of upstream's list
; pages.
;
; The producers write each record into a 256-byte batch buffer in W
; (BATCH, RBV bytes used), upstream's record with the column after the
; kind (a K_TEX 12 bytes, a K_FILL 6, a K_TEXC 8, a K_FUZZ 5: lists.inc's
; fields, R_SRC the native texel slot or patch store address). rec_flush
; copies the batch into the staging, aux 0 $A000-$BFFF, then the spill
; banks RECSP_FIRST..RECSP_LAST ($0200-$BFFF each), one RAMWRT window an
; area; STG_BANK (0: aux 0) and STG_PTR, in the frame block, say where the
; next byte goes. When the staging and the spill are full the frame stops:
; STATUS = ST_RECORDS and BRK, in the test and lockstep builds (RENDER.md
; 3.6: nothing is dropped silently). The game's build (-D RELEASE,
; RENDER-MASKED.md 6.1, stage C) never stops: a batch that does not fit
; the last spill bank's room is dropped whole, and every later one (the
; sticky RECDROP), with STATUS = ST_RECORDS; the frame completes with the
; records staged (a covered range whose record was dropped is cleared by
; the bucket pass), and the display treats it as not shown. Upstream's
; lists and their early flush are not reproduced: the native renderer
; stages the whole frame, and the bucket pass sorts it by column for the
; replay.
;
; The page model (RENDER-MASKED.md 0.3 row 2, 3.4): a masked post's kind
; (K_TEXC or K_TEX) depends on the room left in upstream's page of its
; column's list, so rec_room keeps, for each record every producer makes,
; UPOFS[c] (the offset upstream's next record of column c takes in its
; page, 0-254) and XPUSED (the extra pages upstream has taken, 0-50): a
; record of upstream size s (the native size less the column byte) that
; fits (UPOFS[c] + s <= 254) adds s; else, with an extra page left,
; XPUSED + 1 and UPOFS[c] = s (a K_NEXT ends the old page); else upstream
; draws all lists early (flush, r_list65.s:272-323): every UPOFS 0, XPUSED
; 0, UPFLUSH + 1, and the record takes offset 0 of its home page. The model
; never draws early: the staging keeps every record. RECSEQ counts the
; records staged (their sequence numbers from 0: the covered ranges name
; their record by it until the bucket pass turns it into a W address).
;
; The file is assembled twice (render.mk): for the front end's image
; (RENDERW: rec_start, rec_room, rec_flush, the batch count RB of the seg
; page) and, with -D MREC, for the masked phase's image (MASKW:
; mrec_room, mrec_flush, the count MRB of the draw phase's zero page, and
; the record's sequence number left in RSEQ for the covered ranges).
;
;   rec_start   the frame's start (stage C): an empty batch and staging,
;               no record, every UPOFS 0, no extra page, no flush
;               (upstream's lists are empty when a frame starts: the
;               replay of the frame before emptied them)
;   rec_room    before a record of A bytes (native) in column X: the page
;               model, RECSEQ + 1, the batch flushed when it has no room
;               for it. Keeps X. Out: Y = the batch's free byte.
;   rec_flush   the batch into the staging (the count 0 after). Keeps X.
;
; A GPL-2 derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/
; lists.inc, r_list65.s recAlloc and newPage, r_seg65.s texRec and
; PLANEFILL): the same records and the same allocation.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

LAST_AREA = RECSP_LAST          ; the staging's last area (RELEASE: 6.1)

.ifdef MREC
        .define REC_ROOM mrec_room
        .define REC_FLUSH mrec_flush
        .define RBV MRB
        .export mrec_room, mrec_flush
        .segment "MASKW"
.else
        .define REC_ROOM rec_room
        .define REC_FLUSH rec_flush
        .define RBV RB
        .export rec_start, rec_room, rec_flush
        .segment "RENDERW"

; ---------------------------------------------------------------------------
; rec_start: no record yet: STG_BANK 0 (aux 0), STG_PTR = STAGE, RB = 0;
; the page model's start.
; ---------------------------------------------------------------------------
rec_start:
        stz STG_BANK
        lda #<STAGE
        sta STG_PTR
        lda #>STAGE
        sta STG_PTR+1
        stz RB
        stz RECSEQ
        stz RECSEQ+1
        stz XPUSED
        stz UPFLUSH
        stz RECDROP             ; (6.1: nothing dropped yet)
        ldx #VIEWWIDTH
:       stz UPOFS-1,x
        dex
        bne :-
        rts
.endif

; ---------------------------------------------------------------------------
; REC_ROOM: the page model for a record of A bytes (native) in column X,
; RECSEQ + 1 (the masked copy: the record's number in RSEQ); Y = the
; batch's free byte, after a flush when the batch has no room for A bytes.
; Changes A, Y (a model's flush: every UPOFS). Keeps X.
; ---------------------------------------------------------------------------
REC_ROOM:
        pha
.ifdef MREC
        lda RECSEQ
        sta RSEQ
        lda RECSEQ+1
        sta RSEQ+1
.endif
        inc RECSEQ
        bne :+
        inc RECSEQ+1
:       pla
        pha
        dec a                   ; s, upstream's size
        clc
        adc UPOFS,x             ; UPOFS + s <= PAGE_ROOM: it fits
        bcs @page
        cmp #PAGE_ROOM + 1
        bcc @fits
@page:  lda XPUSED              ; an extra page left: a K_NEXT, the record
        cmp #XP_PAGES           ;   at its offset 0
        bcs @flush
        inc XPUSED
        bra @first
@flush: ldy #VIEWWIDTH          ; none: upstream draws all lists and starts
        lda #0                  ;   them again (flush)
:       sta UPOFS-1,y
        dey
        bne :-
        stz XPUSED
        inc UPFLUSH
@first: pla
        pha
        dec a                   ; UPOFS = s
@fits:  sta UPOFS,x
        pla
        clc                     ; the batch
        adc RBV
        bcs rec_flush_y         ; past 256 bytes: flush first
        ldy RBV
        rts
rec_flush_y:
        jsr REC_FLUSH
        ldy RBV
        rts

; ---------------------------------------------------------------------------
; REC_FLUSH: BATCH[0 .. RBV) to the staging. Changes A, Y, FA_DST.
; ---------------------------------------------------------------------------
REC_FLUSH:
        ldy RBV
        beq @none
.ifdef RELEASE
        lda RECDROP             ; (6.1) dropping: this batch too
        bne @drop
        lda STG_BANK            ; the last area: the batch whole, or none
        cmp #LAST_AREA
        bne @go
        clc
        lda STG_PTR
        adc RBV
        lda STG_PTR+1
        adc #0
        cmp #>STAGE_END         ; its end at STAGE_END or past it: dropped
        bcc @go                 ;   (the copy's step to the next area at
                                ;   $C000 would find none: @over; the last
                                ;   area's last byte is never used)
        lda #1
        sta RECDROP
        lda #ST_RECORDS
        sta STATUS
@drop:  stz RBV
        rts
@go:
.endif
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
@more:  cpy RBV
        bne @byte
        sta RAMWRTOFF
        stz RWBANK
        lda FA_DST
        sta STG_PTR
        lda FA_DST+1
        sta STG_PTR+1
        stz RBV
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
        cpy RBV
        bne @window
        lda FA_DST
        sta STG_PTR
        lda FA_DST+1
        sta STG_PTR+1
        stz RBV
        rts
@over:  lda #ST_RECORDS         ; the staging and the spill are full: a
        sta STATUS              ;   batch reached the last area's end
        brk                     ;   (RELEASE: never reached, a batch that
                                ;   would is dropped first)
        .byte ST_RECORDS
