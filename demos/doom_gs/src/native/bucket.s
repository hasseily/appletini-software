; bucket.s: the bucket pass of the native renderer and the replay of its
; batches (docs/RENDER-MASKED.md). It turns the frame's staged records
; (aux 0 STAGE, then the spill banks RECSP, in production order, each with
; its column byte after its kind) into the replay's input (replay.s), batch
; by batch: whole columns of at most 8,192 bytes, each column's records in
; order without the column byte, the column starts in COLLO/COLHI, each
; covered range's record as its W address, the shadows that must be drawn
; in place marked K_FUZZNOW; and replays each batch (replay.s nat_replay).
; A GPL-2 derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/
; lists.inc: the records), written for the 65C02; the bucketing itself is
; the port's (upstream writes each record into its column's list at once).
;
;   nm_bkload   (the masked image, W) BKFAR and BKFAR2, the parts that run
;               with RAMRD off, from the masked image into main $0C00 and
;               $0200, dead after the masked phase. The caller runs it
;               after nm_masked.
;   nb_frame    once, after the masked phase, the whole replay of the
;               frame: nb_bucket, then for each group of up to three
;               batches its scatter (nb_scatter), and each of its batches'
;               nb_batch and nat_replay (A = its first column, X = the
;               column after its last). In: the staging, STG_BANK and
;               STG_PTR (the frame block), CVFIRST, CVEND and CVRECLO/HI
;               (the covering record's sequence number: its place among
;               the staged records, from 0). Card bank 1 selected, RAMRD,
;               RAMWRT off, $C073 0. Out: the 3D view drawn; the covered
;               ranges zeroed (by the replay, after each strip).
;   nb_bucket   each column's count of bytes (the producers': MCNTLO/HI,
;               rrec.s; speed wave 1, RENDER-MASKED.md:
;               no walk of the staging); the batches (runs of
;               whole columns of at most 8,192 bytes: the batch list,
;               BK_FIRST, BK_SZLO/HI, BK_NB of them, at most MAXB: rlayout.py
;               proves the bound); each column's cursor, its start in its
;               batch's region (W $6000 + $2000 (b mod 3)). A column of more
;               than 8,192 bytes, a broken staging: STATUS ST_BUCKET, BRK;
;               in the release build (-D RELEASE, render.mk's default) such
;               a column is cut instead: the counts are made again by walk
;               1 (walk1: a column keeps each record that leaves it under
;               8,192 bytes, CVDONE bit 7 when it refused one; a cut column
;               is alone in its batch), STATUS ST_RECORDS, and the frame
;               goes on; a frame whose batches were dropped (RECDROP) has
;               its counts made again the same way (the producers counted
;               them).
;   nb_scatter  walk 2 for the group's batches BK_G .. BK_GE - 1: each of
;               their records copied to its column's cursor, which steps
;               past it (a cut column's records that would end past its
;               region left out, as walk 1 left them out); a
;               covered column's record, when its sequence
;               number comes (CVDONE not yet set), gives the covered range
;               its W address in $6000-$7FFF (where its batch is
;               replayed) and sets CVDONE; the cursors moved one entry up
;               (the column starts), a covered column of the group whose
;               record was not staged has its range cleared (6.1); the
;               group's second and third batches parked in RamWorks bank
;               RECW at their regions ($8000, $A000: the replay's stage
;               takes W $8000-$BFFF).
;   nb_batch    X = a batch. Brought back from RECW into W $6000 when it
;               is not its group's first, its end entry in COLLO/COLHI,
;               its first column's entry $6000 again, and the fuzz marks
;               of its columns that hold a shadow (CVFIRST 255): a K_FUZZ
;               becomes K_FUZZNOW when a later record of its column paints
;               a row from R_ROW - 1 to R_ROW + R_COUNT (loader.mark_fuzz's
;               rule).
;
; How (RENDER-MASKED.md): inside a RAMRD window only zero page, the
; stack page and the card are near, and the per-column arrays the walks
; need are in main memory, so the staging is read in chunks of up to 180
; bytes into page 1 (chunk: one RAMRD window a chunk, the card's code),
; and walked there with RAMRD off (scan). A record cut by a chunk's end is
; moved to page 1's start before the next chunk. The staging's bytes left
; (BK_REM) are 24 bits: aux 0's 8 KB and four spill banks.
;
; Speed wave 1 (docs/SPEED.md, part bucket): the counts come from the
; producers (no walk 1, but in the release build's recount); a chunk's runs
; are copied by ZLOOP, ten bytes of code in zero page (BK_ZLOOP, after the
; batch list; nb_bucket writes them) whose absolute,y operands each run
; patches, Y counting up to 0; walk 2 is one loop with the walk (scan),
; each record copied by two zero-page pointers (page 1 and its column's
; cursor) counting Y down; a covered column whose record is not found yet
; is CVDONE 0 from nb_bucket on (1: no range), so the other columns' records
; take no range test.
;
; Where (RENDER-MASKED.md): the code that runs inside a window
; (cwin, the chunk's window; the batches' parking and bring-back: BKNEAR)
; in the card's $F900 part after the replay's; nb_bucket and, in the
; release build, its recount (bk_recount, walk 1) in the masked image
; (MASKW, W), which it runs before any scatter writes W; the rest in main
; memory the masked phase leaves dead, copied there by nm_bkload: BKFAR at
; $0C00-$0EFF (with bstop and the release build's rp_cut, the replay's
; cut), BKFAR2 at $0200-$02FF. Its zero page: overlay 1, BK_NB ($70) and
; the batch list, ZLOOP; the replay keeps to $48-$6F.
;
; The release build (-D RELEASE: render.mk's default, the disk's rcard;
; RENDER-MASKED.md 10) cuts instead of stopping, STATUS ST_RECORDS: after
; a dropped batch (rrec.s, RECDROP) or with a column past RECBUF_SPAN,
; walk 1 counts every column again from the staging, leaving out of a
; column each record that would take it to RECBUF_SPAN (CVDONE bit 7: the
; column is cut); a cut column is alone in its batch, at its region's
; start, so walk 2 keeps the same records: those that end inside the
; region. A covered range whose record was dropped or cut is cleared.
; Without it (render.mk's stops target) those stop the frame (bstop).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import nat_replay
        .import __BKFAR_LOAD__, __BKFAR_RUN__, __BKFAR_SIZE__
        .import __BKFAR2_LOAD__, __BKFAR2_RUN__, __BKFAR2_SIZE__
        .export nm_bkload, nb_frame, nb_bucket, nb_scatter, nb_batch
        .exportzp BK_NB, BK_G, BK_GE, BK_B
.ifdef RELEASE
        .export rp_cut
        .import run_descriptors, draw_strip, rp_drawn, gcol
        .importzp rp
.endif

RECBUF_SPAN = $2000             ; a batch's bytes at most (the replay's
REGION  = $2000                 ;   record buffer); the regions' spacing
CHUNK   = 180                   ; page 1 $0100-$01B3
P1      = $0100
K_FUZZNOW = 4
K_OVL   = 10                    ; (K_FUZZ, CVFIRST .. CVRECHI: rlayout.inc)

; zero page: overlay 1 and $70 (the replay keeps to $48-$6F)
BK_BANK  = $18                  ; the staging's area being read (0: aux 0)
BK_PTR   = $19                  ;   and its next byte (2)
BK_REM   = $1B                  ; staged bytes not yet read (3)
BK_LEN   = $1E                  ; bytes in page 1
BK_AT    = $1F                  ; the walk's record in page 1
BK_SIZE  = $20                  ; its size (the column byte included)
BK_C     = $21                  ; a chunk's run of bytes
BK_SEQ   = $22                  ; the record's sequence number (2)
BK_P     = $24                  ; a W pointer (2)
BK_Q     = $26                  ; another (2)
BK_T     = $28                  ; temporaries (2)
BK_E     = $2C                  ; a record's rows (2); scan: its last byte
                                ;   in W (its size less 2)
BK_G     = $2F                  ; the group's first batch, the batch after
BK_GE    = $30                  ;   its last
BK_LO    = $31                  ; the group's first column, the column
BK_HI    = $32                  ;   after its last
BK_B     = $33                  ; the batch being replayed
BK_MODE  = $34                  ; (the release build) scan: bit 7, walk 1
BK_V     = $35                  ; scan: a record's column byte in page 1
                                ;   (2; the high byte P1's, set by zl_put)
BK_NB    = $70                  ; the batches (BK_FIRST follows)
        .assert BK_NB = BK_NB_ZP && BK_FIRST = BK_NB + 1, error, "BK_NB"
        .assert RECBUF_SPAN <= REGION, error, "RECBUF_SPAN"
        .assert (RECBUF & (REGION - 1)) = 0, error, "the regions' alignment"
; ZLOOP (zero page, after the batch list): lda ZL_SRC,y / sta ZL_DST,y /
; iny / bne ZLOOP / rts
ZLOOP    = BK_ZLOOP
ZL_SRC   = ZLOOP + 1
ZL_DST   = ZLOOP + 4
        .assert BK_FIRST + MAXB + 1 <= ZLOOP, error, "ZLOOP"

.macro MARK n                   ; (A is free at each mark)
.ifdef RPROF
        lda #(n) * 2
        sta PHASE
.endif
.endmacro

; ===========================================================================
; nm_bkload (the masked image)
; ===========================================================================
        .segment "MASKW"
nm_bkload:
        lda #<__BKFAR_LOAD__
        ldx #>__BKFAR_LOAD__
        ldy #>__BKFAR_RUN__
        jsr @copy3
        lda #<__BKFAR2_LOAD__
        ldx #>__BKFAR2_LOAD__
        ldy #>__BKFAR2_RUN__
@copy3: sta BK_P                ; whole pages (the run areas are page
        stx BK_P+1              ;   aligned and dead)
        stz BK_Q
        sty BK_Q+1
        ldx #3
        cpy #>BKFAR2_RUN
        bne :+
        ldx #1
:       ldy #0
:       lda (BK_P),y
        sta (BK_Q),y
        iny
        bne :-
        inc BK_P+1
        inc BK_Q+1
        dex
        bne :-
        rts
.assert __BKFAR_RUN__ = BKFAR_RUN, lderror, "BKFAR does not run at BKFAR_RUN"
.assert __BKFAR_SIZE__ <= BKFAR_END - BKFAR_RUN, lderror, "BKFAR is too large"
.assert __BKFAR2_RUN__ = BKFAR2_RUN, lderror, "BKFAR2 does not run at BKFAR2_RUN"
.assert __BKFAR2_SIZE__ <= BKFAR2_END - BKFAR2_RUN, lderror, "BKFAR2 is too large"

; ===========================================================================
; nb_bucket (the masked image, W): it runs once, first in nb_frame, while W
; still holds the masked image (or OVLW, which links this file too): no
; scatter has written W yet
; ===========================================================================
nb_bucket:
        jsr zl_put              ; the chunk's copy loop into zero page
        ldx #VIEWWIDTH          ; CVDONE 0: a covered column (CVEND not 0,
@cv:    lda CVEND-1,x           ;   CVFIRST below it) whose record is not
        beq @nc                 ;   found yet; 1: no covered range; (the
        lda CVFIRST-1,x         ;   release build, walk 1) bit 7: cut
        cmp CVEND-1,x
        lda #0
        bcc :+
@nc:    lda #1
:       sta CVDONE-1,x
        dex
        bne @cv
.ifdef RELEASE
        stz BK_MODE             ; (scan: walk 2)
        lda RECDROP             ; a batch dropped: the counts again
        bne @recount
.endif
        ; the batches: runs of whole columns of at most RECBUF_SPAN bytes
@batches:
        ldx #0                  ; X = the column, Y = the batch
        ldy #0
@batch: cpy #MAXB
        bcs @maxb
        stx BK_FIRST,y
        lda #0
        sta BK_SZLO,y
        sta BK_SZHI,y
@col:   cpx #VIEWWIDTH
        beq @last
.ifdef RELEASE
        bit CVDONE,x            ; a cut column is alone in its batch (walk
        bpl @add                ;   2 keeps its records by their place in
        txa                     ;   its region): the batch before it ends
        cmp BK_FIRST,y          ;   (its bytes, less than RECBUF_SPAN by
        bne @next               ;   walk 1, fit an empty batch)
@add:
.endif
        clc                     ; + the column's bytes
        lda BK_SZLO,y
        adc MCNTLO,x
        sta BK_T
        lda BK_SZHI,y
        adc MCNTHI,x
        cmp #>RECBUF_SPAN
        bcc @fits
        bne @full
        lda BK_T
        bne @full
        lda #>RECBUF_SPAN
@fits:  sta BK_SZHI,y
        lda BK_T
        sta BK_SZLO,y
        inx
.ifdef RELEASE
        bit CVDONE-1,x          ; a cut column ends its batch
        bpl @col
        cpx #VIEWWIDTH
        beq @last
        bra @next
.else
        bra @col
.endif
@full:  txa                     ; a batch of no column: one column passes
        cmp BK_FIRST,y          ;   RECBUF_SPAN (the release build counts
        beq @stop               ;   again: walk 1 cuts it)
@next:  iny
        bra @batch
@maxb:
.ifndef RELEASE
@stop:
.endif
        jmp bstop               ; (more than MAXB: none, rlayout.py)
.ifdef RELEASE
@stop:
@recount:
        jsr bk_recount          ; each column's count from the staging
        bra @batches
.endif
@last:  iny
        sty BK_NB
        lda #VIEWWIDTH
        sta BK_FIRST,y
        ; the counts become the cursors: each column's start in its batch's
        ; region, RECBUF + $2000 (b mod 3)
        ldy #0
        ldx #0                  ; (b mod 3)
@cursor:
        stz BK_P
        txa
        asl a
        asl a
        asl a
        asl a
        asl a
        adc #>RECBUF            ; (carry clear)
        sta BK_P+1
        phx
        ldx BK_FIRST,y
@cs:    txa
        cmp BK_FIRST+1,y
        beq @nexb
        lda BK_P                ; cursor = start; start += count
        sta COLLO,x
        clc
        adc MCNTLO,x
        sta BK_P
        lda BK_P+1
        sta COLHI,x
        adc MCNTHI,x
        sta BK_P+1
        inx
        bra @cs
@nexb:  plx
        inx
        cpx #3
        bcc :+
        ldx #0
:       iny
        cpy BK_NB
        bne @cursor
        rts

.ifdef RELEASE
; bk_recount (6.1, the release build): each column's count again from the
; staging, walk 1 (scan with BK_MODE bit 7): after a dropped batch (the
; producers counted its records) or a column past RECBUF_SPAN
bk_recount:
        ldx #VIEWWIDTH
:       stz MCNTLO-1,x
        stz MCNTHI-1,x
        dex
        bne :-
        dec BK_MODE             ; (0 before: $FF)
        jsr scan
        stz BK_MODE
        rts

; walk 1 (scan's, Y: the record in page 1; RAMRD off): the column's count +
; the record's bytes in W (its size less the column byte) when that stays
; below RECBUF_SPAN; else the record is left out of the column, which is
; cut (CVDONE bit 7, STATUS ST_RECORDS). A later record that fits still
; counts. So a cut column keeps less than a region, and walk 2 keeps
; exactly these records: those that end inside the column's region.
; Changes A, X, BK_T.
walk1:  ldx P1+1,y
        lda BK_SIZE
        dec a
        clc
        adc MCNTLO,x
        sta BK_T
        lda MCNTHI,x
        adc #0
        cmp #>RECBUF_SPAN
        bcs @cut
        sta MCNTHI,x
        lda BK_T
        sta MCNTLO,x
        rts
@cut:   lda CVDONE,x
        ora #$80
        sta CVDONE,x
        lda #ST_RECORDS
        sta STATUS
        rts
.endif

; ===========================================================================
; BKNEAR: the code that runs inside a window (the card)
; ===========================================================================
        .segment "BKNEAR"

; ---------------------------------------------------------------------------
; cwin (one RAMRD window), chunk's part in the card: BK_C bytes of the
; staging from BK_BANK:BK_PTR into page 1 from X, across the areas' ends,
; each run by ZLOOP. Out: BK_LEN the bytes in page 1.
; ---------------------------------------------------------------------------
cwin:   lda BK_BANK
        sta RWBANK
        sta RAMRDON
@run:   lda BK_C
        beq @end
        sec                     ; a run: to the area's end ($C000) at most
        lda #0
        sbc BK_PTR
        sta BK_T
        lda #>STAGE_END
        sbc BK_PTR+1
        bne :+
        lda BK_T
        cmp BK_C
        bcs :+
        sta BK_T+1
        bra @part
:       lda BK_C
        sta BK_T+1
@part:  sec                     ; ZLOOP: Y from -n to 0, the operands
        lda #0                  ;   n before the run's end
        sbc BK_T+1
        tay
        clc
        lda BK_PTR
        adc BK_T+1
        sta ZL_SRC
        lda BK_PTR+1
        adc #$FF
        sta ZL_SRC+1
        txa
        clc
        adc BK_T+1
        sta ZL_DST
        tax                     ; (X past the run)
        jsr ZLOOP
        sec                     ; BK_C less the run
        lda BK_C
        sbc BK_T+1
        sta BK_C
        lda ZL_SRC              ; BK_PTR past it (ZL_SRC + $100); at the
        sta BK_PTR              ;   area's end, the next area
        ldy ZL_SRC+1
        iny
        sty BK_PTR+1
        cpy #>STAGE_END
        bne @run
        lda BK_BANK
        bne :+
        lda #RECSP_FIRST - 1
:       inc a
        sta BK_BANK
        sta RWBANK
        lda #>$0200
        sta BK_PTR+1
        bra @run
@end:   sta RAMRDOFF
        stz RWBANK
        stx BK_LEN
        rts

; ---------------------------------------------------------------------------
; park: BK_Q bytes (whole pages, rounded up) of W from BK_P to RamWorks
; bank RECW at the same address, one RAMWRT window; back: the same from
; RECW at BK_P to W from BK_E, one RAMRD window.
; ---------------------------------------------------------------------------
park:   lda BK_P
        sta BK_E
        lda BK_P+1
        sta BK_E+1
        lda #RECW
        sta RWBANK
        sta RAMWRTON
        jsr pages
        sta RAMWRTOFF
        stz RWBANK
        rts
back:   lda #RECW
        sta RWBANK
        sta RAMRDON
        jsr pages
        sta RAMRDOFF
        stz RWBANK
        rts
pages:  ldx BK_Q+1
        lda BK_Q
        beq :+
        inx
:       ldy #0
:       lda (BK_P),y
        sta (BK_E),y
        iny
        bne :-
        inc BK_P+1
        inc BK_E+1
        dex
        bne :-
        rts

; ===========================================================================
; BKFAR2 (main $0200): small routines of the walks and the marks, and the
; walks' handlers (RAMRD, RAMWRT off)
; ===========================================================================
        .segment "BKFAR2"

; region: BK_P = RECBUF + $2000 (y - BK_G) (batch y's region in its group),
; BK_Q = its bytes. Keeps Y.
region: stz BK_P
        tya
        sec
        sbc BK_G
        asl a
        asl a
        asl a
        asl a
        asl a
        clc
        adc #>RECBUF
        sta BK_P+1
        lda BK_SZLO,y
        sta BK_Q
        lda BK_SZHI,y
        sta BK_Q+1
        rts

; the size of each kind in W (the column byte dropped; K_FUZZNOW is
; K_FUZZ's), and staged (0: no staged record of that kind)
wsize:  .byte TEXREC_SIZE - 1, 0, FILLREC_SIZE - 1, 0, 4, 0, 7, 0, 4, 0, 4
ssize:  .byte TEXREC_SIZE, 0, FILLREC_SIZE, 0, 0, 0, 8, 0, 5, 0, 5

; the chunk's copy loop, written into zero page (ZLOOP) by nb_bucket: lda
; abs,y / sta abs,y (page 1: the high byte 0, the low byte with Y from -n
; reaches $0100 + it) / iny / bne / rts
zl_code:
        .byte $B9, 0, 0, $99, 0, 0, $C8, $D0, <(-9), $60
        .assert * - zl_code = BK_ZLOOP_SIZE, error, "zl_code"
zl_put: ldx #BK_ZLOOP_SIZE
:       lda zl_code-1,x
        sta ZLOOP-1,x
        dex
        bne :-
        lda #>P1                ; (and scan's pointer into page 1)
        sta BK_V+1
        rts

; ===========================================================================
; BKFAR (main $0C00): the rest (RAMRD and RAMWRT off)
; ===========================================================================
        .segment "BKFAR"

; ===========================================================================
; nb_batch: X = the batch
; ===========================================================================
nb_batch:
        txa
        tay
        cmp BK_G
        beq @here               ; the group's first is in place
        jsr region              ; a later one from RECW into W RECBUF
        stz BK_E
        lda #>RECBUF
        sta BK_E+1
        phy
        jsr back
        ply
@here:  ldx BK_FIRST,y          ; its first column's start RECBUF again
        stz COLLO,x             ;   (the batch before wrote its end there)
        lda #>RECBUF
        sta COLHI,x
        ldx BK_FIRST+1,y        ; its end: RECBUF + its bytes
        clc
        lda BK_SZLO,y
        sta COLLO,x
        lda BK_SZHI,y
        adc #>RECBUF
        sta COLHI,x
        ; the fuzz marks of its columns that hold a shadow
        ldx BK_FIRST,y
@mc:    txa
        cmp BK_FIRST+1,y
        beq @done
        lda CVFIRST,x
        cmp #$FF
        bne :+
        phy
        jsr marks
        ply
:       inx
        bra @mc
@done:  rts


; ---------------------------------------------------------------------------
; nb_frame
; ---------------------------------------------------------------------------
nb_frame:                       ; (the caller marks phase 18)
        jsr nb_bucket
        stz BK_G
@group: clc                     ; BK_GE = min(BK_G + 3, BK_NB)
        lda BK_G
        adc #3
        cmp BK_NB
        bcc :+
        lda BK_NB
:       sta BK_GE
        jsr nb_scatter
        lda BK_G
        sta BK_B
@batch: MARK 18
        ldx BK_B
        jsr nb_batch
        MARK 12                 ; the replay (upstream's phase 12)
        ldy BK_B
        ldx BK_FIRST+1,y
        lda BK_FIRST,y
        jsr nat_replay
        inc BK_B
        lda BK_B
        cmp BK_GE
        bcc @batch
        sta BK_G
        cmp BK_NB
        bcc @group
        rts

; ---------------------------------------------------------------------------
; nb_scatter: the group BK_G .. BK_GE - 1
; ---------------------------------------------------------------------------
nb_scatter:
        ldy BK_G                ; its columns
        ldx BK_FIRST,y
        stx BK_LO               ; its first column's cursor: the region's
        stz COLLO,x             ;   start (the group before wrote its end
        lda #>RECBUF            ;   there)
        sta COLHI,x
        ldy BK_GE
        ldx BK_FIRST,y
        stx BK_HI
        stz BK_SEQ
        stz BK_SEQ+1
        jsr scan
        ; each cursor holds the next column's start: one entry up, less its
        ; batch's region offset ($2000 (b - BK_G)), the last batch first (a
        ; batch reads its first column's cursor before the batch before
        ; writes its end there); then RECBUF at each batch's first column
        ldy BK_GE
@ub:    dey
        bmi @firsts
        cpy BK_G
        bcc @firsts
        tya
        sec
        sbc BK_G
        asl a
        asl a
        asl a
        asl a
        asl a
        sta BK_T                ; $20 (y - BK_G)
        lda BK_FIRST,y
        sta BK_T+1
        ldx BK_FIRST+1,y        ; from the batch's end entry down
@up:    cpx BK_T+1
        beq @ub
        lda COLLO-1,x
        sta COLLO,x
        sec
        lda COLHI-1,x
        sbc BK_T
        sta COLHI,x
        dex
        bra @up
@firsts:
        ldy BK_G
:       ldx BK_FIRST,y
        stz COLLO,x
        lda #>RECBUF
        sta COLHI,x
        iny
        cpy BK_GE
        bcc :-
        ; a covered column of the group whose record was not staged (6.1:
        ; a dropped record) has no range
        ldx BK_LO
@cv:    cpx BK_HI
        beq @park
        lda CVDONE,x            ; (0: covered, its record not found)
.ifdef RELEASE
        asl a                   ; (bit 7: the cut; a record cut is not
.endif                          ;   staged)
        bne @cvn
        stz CVFIRST,x
        stz CVEND,x
@cvn:   inx
        bra @cv
@park:  ldy BK_G                ; the group's later batches parked in RECW
@pk:    iny                     ;   (the replay's stage takes W
        cpy BK_GE               ;   $8000-$BFFF)
        bcs @done
        jsr region
        phy
        jsr park
        ply
        bra @pk
@done:  rts


; ---------------------------------------------------------------------------
; scan: each staged record, in production order, through page 1 (chunk):
; walk 2 (the release build: walk 1 when BK_MODE bit 7 is set). Walk 2: a
; record of the group's columns (BK_LO .. BK_HI - 1) without its column
; byte to the column's cursor, which steps past it (the release build: a
; cut column's records that would end past its region left out); a covered
; column's record
; (its sequence number CVRECLO/HI, BK_SEQ counting every record): the
; range's W address where its batch is replayed, CVDONE.
; ---------------------------------------------------------------------------
scan:   stz BK_BANK             ; the staging from its start
        lda #<STAGE
        sta BK_PTR
        lda #>STAGE
        sta BK_PTR+1
        stz BK_REM+2            ; its bytes (STAGE and $0200 are page
        lda STG_PTR             ;   aligned: the low byte is STG_PTR's)
        sta BK_REM
        lda STG_PTR+1
        ldx STG_BANK
        beq @aux
        clc                     ; a spill bank: STG_PTR - $0200 + the aux 0
        adc #>(STAGE_END - STAGE - $0200)   ; area's $2000, + $BE00 for
@k:     cpx #RECSP_FIRST        ;   each spill bank before it
        beq @hi
        dex
        clc
        adc #>(STAGE_END - $0200)
        bcc @k
        inc BK_REM+2
        bra @k
@aux:   sec                     ; aux 0: STG_PTR - STAGE
        sbc #>STAGE
@hi:    sta BK_REM+1
@go:    stz BK_LEN
        stz BK_AT
        bra scan_nx
scan_rf:
        lda BK_REM              ; nothing left to read: the scan's end (a
        ora BK_REM+1            ;   record cut there: the staging is
        ora BK_REM+2            ;   broken)
        bne :+
        ldy BK_AT
        cpy BK_LEN
        bne scan_bad
        rts
:       jsr chunk
scan_nx:
        ldy BK_AT               ; Y: the record in page 1
        cpy BK_LEN
        beq scan_rf
        lda P1,y                ; the kind's size
        cmp #K_OVL + 1
        bcs scan_bad
        tax
        lda ssize,x
        bne :+
scan_bad:
        jmp bstop
:       sta BK_SIZE
        clc
        adc BK_AT
        bcs scan_rf
        cmp BK_LEN
        beq :+
        bcs scan_rf
:       sta BK_AT               ; (the next record)
.ifdef RELEASE
        bit BK_MODE
        bpl walk2
        jsr walk1
        bra scan_nx
.endif
; walk 2 (Y: the record in page 1): its column, the group's?
walk2:  ldx P1+1,y
        cpx BK_LO
        bcc @seq
        cpx BK_HI
        bcs @seq
        lda COLLO,x             ; its place
        sta BK_P
        lda COLHI,x
        sta BK_P+1
.ifdef RELEASE
        bit CVDONE,x            ; (6.1) a cut column, alone in its batch
        bpl @whole              ;   from its region's start: a record that
        lda BK_SIZE             ;   would end past the region's last byte
        dec a                   ;   is left out (as walk 1 left it out of
        clc                     ;   the count): the record's end (BK_P +
        adc BK_P                ;   its bytes in W) in the next region,
        bcc @whole              ;   a carry out of the last page of BK_P's
        lda BK_P+1              ;   region
        ora #>(-REGION)
        inc a
        beq @seq
@whole:
.endif
        lda CVDONE,x            ; the column's covering record? (0: a
.ifdef RELEASE                  ;   covered range, its record not found)
        asl a                   ; (bit 7: the cut)
.endif
        bne @copy
        lda BK_SEQ
        cmp CVRECLO,x
        bne @copy
        lda BK_SEQ+1
        cmp CVRECHI,x
        bne @copy
        inc CVDONE,x            ; its address where the batch is replayed
        lda BK_P
        sta CVRECLO,x
        lda BK_P+1
        and #>(REGION - 1)
        ora #>RECBUF
        sta CVRECHI,x
@copy:  lda P1,y                ; the kind
        sta (BK_P)
        iny                     ; BK_V + j: byte j in W (the column byte
        sty BK_V                ;   at BK_V)
        ldy BK_SIZE
        dey
        dey                     ; Y: the record's last byte in W
        sty BK_E
@f:     lda (BK_V),y
        sta (BK_P),y
        dey
        bne @f
        sec                     ; the cursor past it (BK_E + 1)
        lda COLLO,x
        adc BK_E
        sta COLLO,x
        bcc @seq
        inc COLHI,x
@seq:   inc BK_SEQ              ; the next record's sequence number
        bne :+
        inc BK_SEQ+1
:       jmp scan_nx

; ---------------------------------------------------------------------------
; bstop: a limit of the pass, a broken staging: STATUS ST_BUCKET, BRK
; ---------------------------------------------------------------------------
bstop:  lda #ST_BUCKET
        sta STATUS
        brk
        .byte ST_BUCKET

.ifdef RELEASE
; ---------------------------------------------------------------------------
; rp_cut (-D RELEASE, RENDER-MASKED.md 10): replay.s's strip of one column
; that does not fit the stage (over 125 texture records), from nat_replay
; with RAMRD and RAMWRT off, card bank 2 selected. The column keeps its
; records before the one that did not fit (rp): its end is rp while the
; strip of that column alone is drawn with what was gathered, without its
; covered range (its covering record may be past the cut); STATUS
; ST_RECORDS; then nat_replay's next strip (rp_drawn)
; ---------------------------------------------------------------------------
rp_cut: inc gcol
        ldx gcol
        lda COLLO,x             ; the next column's start, kept
        pha
        lda COLHI,x
        pha
        lda rp
        sta COLLO,x
        lda rp+1
        sta COLHI,x
        stz CVFIRST-1,x
        stz CVEND-1,x
        lda #ST_RECORDS
        sta STATUS
        jsr run_descriptors
        jsr draw_strip
        ldx gcol
        pla
        sta COLHI,x
        pla
        sta COLLO,x
        jmp rp_drawn
.endif

; ---------------------------------------------------------------------------
; chunk: the record cut at page 1's end (from BK_AT) to page 1's start, then
; up to CHUNK - that many bytes of the staging after it (BK_C; BK_REM less
; them), read in the card's window (cwin)
; ---------------------------------------------------------------------------
chunk:  ldx #0
        ldy BK_AT
@mv:    cpy BK_LEN
        beq @mvd
        lda P1,y
        sta P1,x
        inx
        iny
        bra @mv
@mvd:   stz BK_AT
        txa                     ; BK_C = min(CHUNK - X, BK_REM)
        eor #$FF
        sec
        adc #CHUNK
        sta BK_C
        lda BK_REM+2
        ora BK_REM+1
        bne :+
        lda BK_REM
        cmp BK_C
        bcs :+
        sta BK_C
:       sec                     ; BK_REM less them
        lda BK_REM
        sbc BK_C
        sta BK_REM
        bcs :+
        lda BK_REM+1
        bne @d1
        dec BK_REM+2
@d1:    dec BK_REM+1
:       jmp cwin


; ===========================================================================
; BKFAR2 again: the batch's fuzz marks
; ===========================================================================
        .segment "BKFAR2"

; marks: the column X's K_FUZZ records in W that a later record of the
; column paints next to or over: K_FUZZNOW. Keeps X.
marks:  lda COLLO,x             ; BK_P: the record, from the column's start
        sta BK_P
        lda COLHI,x
        sta BK_P+1
        lda COLLO+1,x           ; BK_T: the column's end
        sta BK_T
        lda COLHI+1,x
        sta BK_T+1
@rec:   lda BK_P                ; the column's end
        cmp BK_T
        lda BK_P+1
        sbc BK_T+1
        bcs @done
        lda (BK_P)
        cmp #K_FUZZ
        bne @skip
        ldy #1                  ; its rows: a = R_ROW and a + R_COUNT
        lda (BK_P),y
        sta BK_E
        iny
        clc
        adc (BK_P),y
        sta BK_E+1
        jsr later               ; a later record over R_ROW - 1 .. a +
        bcc @skip               ;   R_COUNT?
        lda #K_FUZZNOW
        sta (BK_P)
@skip:  lda (BK_P)              ; the next record
        tay
        clc
        lda BK_P
        adc wsize,y
        sta BK_P
        bcc @rec
        inc BK_P+1
        bra @rec
@done:  rts

; later: C set when a record after BK_P (to BK_T) paints a row r with
; BK_E - 1 <= r <= BK_E+1: its first row <= BK_E+1 and its row after the
; last >= BK_E. Keeps X, BK_P.
later:  lda BK_P
        sta BK_Q
        lda BK_P+1
        sta BK_Q+1
@next:  lda (BK_Q)              ; past this record
        tay
        clc
        lda BK_Q
        adc wsize,y
        sta BK_Q
        bcc :+
        inc BK_Q+1
:       lda BK_Q                ; the column's end: none
        cmp BK_T
        lda BK_Q+1
        sbc BK_T+1
        bcc :+
        clc
        rts
:       lda (BK_Q)              ; its row after the last: R_END; a
        cmp #K_OVL              ;   shadow's R_ROW + R_COUNT; an automap
        beq @ovl                ;   pixel's R_ROW + 1
        cmp #K_FUZZ
        beq @fz
        cmp #K_FUZZNOW
        beq @fz
        ldy #2
        lda (BK_Q),y
        bra @end
@fz:    ldy #1
        lda (BK_Q),y
        iny
        clc
        adc (BK_Q),y
        bra @end
@ovl:   ldy #1
        lda (BK_Q),y
        inc a
@end:   cmp BK_E                ; its row after the last >= a
        bcc @next
        ldy #1
        lda BK_E+1              ; its first row <= a + count
        cmp (BK_Q),y
        bcc @next
        sec
        rts

