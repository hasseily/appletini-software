; game/grec.s: the routine harness's recording callback and traverser
; (milestone 10, docs/GAME.md 2.2, 3.5; test builds only): ITTAB's and
; TRVTAB's own entries, which the harness passes to P_BlockLinesIterator,
; P_BlockThingsIterator and P_PathTraverse to see what they deliver.
; GPL-2, the port's own.
;
;   gt_record_it    an iterator's callback: GA_0..1 the line or mobj handle;
;                   it is appended (2 bytes) to GTEST GT_RECORD; C set
;                   (go on) unless rec_stop calls are made (C clear)
;   gt_record_trv   a traverser: GA_0 the intercept (its index in ICPT,
;                   TRVTAB's convention); its 6 bytes (frac, what) appended;
;                   the same stop
;
; rec_n counts the calls, rec_stop (0: never) the call that answers stop:
; the harness reads and writes them by their labels.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"

        .export gt_record_it, gt_record_trv, rec_n, rec_stop
        .import far_put

        .segment "LOADW"

gt_record_it:
        lda GA_0                ; the handle (ITTAB's convention: GA_0..1;
        sta rec_v               ;   wave 1 as integrated, geom.md R1)
        lda GA_1
        sta rec_v+1
        ldy #2
        bra record
gt_record_trv:
        lda GA_0                ; the intercept (TRVTAB's convention: GA_0;
        asl a                   ;   path.md R2): ICPT + 6 GA_0, 16 bits
        sta GO_I
        asl a
        clc
        adc GO_I
        ldx #>ICPT
        bcc :+
        inx
:       clc
        adc #<ICPT
        bcc :+
        inx
:       sta GO_P
        stx GO_P+1
        ldy #ICPT_SIZE - 1
:       lda (GO_P),y
        sta rec_v,y
        dey
        bpl :-
        ldy #ICPT_SIZE
record: sty FA_N
        lda rec_n               ; GT_RECORD + 8 rec_n (8 bytes a call)
        sta FA_DST
        lda rec_n+1
        asl FA_DST
        rol a
        asl FA_DST
        rol a
        asl FA_DST
        rol a
        clc
        adc #>GT_RECORD
        sta FA_DST+1
        clc
        lda FA_DST
        adc #<GT_RECORD
        sta FA_DST
        bcc :+
        inc FA_DST+1
:       lda #<rec_v
        sta FA_SRC
        lda #>rec_v
        sta FA_SRC+1
        lda #GTEST
        sta FA_BANK
        lda rec_n+1             ; (the log's room: 256 calls)
        bne :+
        jsr far_put
:       inc rec_n
        bne :+
        inc rec_n+1
:       lda rec_stop            ; the stop: the call rec_stop
        ora rec_stop+1
        beq @on
        lda rec_n
        cmp rec_stop
        bne @on
        lda rec_n+1
        cmp rec_stop+1
        bne @on
        clc
        rts
@on:    sec
        rts
        .assert ICPT_SIZE = 6, error, "an intercept"

rec_v:  .res 8
rec_n:  .res 2
rec_stop:
        .res 2
