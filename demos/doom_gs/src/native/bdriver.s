; bdriver.s: the a2vm test driver of the bucket pass (docs/RENDER-MASKED.md
; 3.4, 5.1; not part of the game). The harness (tools/native/
; bucketcheck.py) puts a frame's staged records, its staging pointer and
; its covered ranges in the image; the driver runs nb_frame (stage C: the
; bucket pass and, for each batch, nb_batch then the replay), whose replay
; is the stand-in nat_replay below: a2vm snapshots the batch there.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import nb_frame
        .importzp BK_NB
        .export bdrv, bdrv_replay, bdrv_halt, bdrv_crash, bdrv_bucket
        .export nat_replay

        .segment "BDRIVER"

bdrv:   sei
        lda #<bdrv_crash        ; a BRK stops the run there
        sta $FFFE
        lda #>bdrv_crash
        sta $FFFF
        lda #36                 ; the cost phase 18: the bucket pass
        sta PHASE               ;   (RENDER-MASKED.md 4.4: 18 * 2 = 36)
bdrv_bucket:
        jsr nb_frame
bdrv_halt:
        stz PHASE
        bra bdrv_halt
bdrv_crash:
        bra bdrv_crash

; the replay's stand-in: A = the batch's first column, X = the column after
; its last (a2vm's snapshot here); the cost phase back to 18
nat_replay:
bdrv_replay:
        pha
        lda #36
        sta PHASE
        pla
        rts
