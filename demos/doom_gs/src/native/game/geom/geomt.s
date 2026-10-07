; game/geom/geomt.s: part geom's driver for random checks (100,000 random
; point-line and box-line pairs a map, 100,000 inputs of posMul). GPL-2,
; the port's own. Not game code: everything below is under TESTBUILD,
; which no current build defines, so it assembles to nothing in the disk
; build. It reads and writes its cases with the far layer.
;
;   geo_t_run   for each of geo_t_count records (from $0200 of bank
;               GEO_T_BANK, a spare bank of llayout.bank_map, to $BFFF
;               at most): the record into geo_t_buf, the routine of geo_t_kind
;               on it, its result into the record, the record back:
;                 0  x (4), y (4), line (2) -> P_PointOnLineSide's A (1)
;                 1  box (16), line (2) -> P_BoxOnLineSide's A (1)
;                 2  V (3), F (2) -> posMul's M_R (4)
;
; A host-side checker (no longer in the repository) wrote the records and
; the descriptor (geo_t_kind, geo_t_count by their labels) and read the
; results back from the run's snapshot.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

.ifdef TESTBUILD
        .export geo_t_run, geo_t_kind, geo_t_count, geo_t_buf
        .import far_get, far_put, fc_call, fc_unbuilt
        .import P_PointOnLineSide, P_BoxOnLineSide, posMul

GEO_T_BANK = 93                 ; (spare: llayout.bank_map)

        ; test-only code goes in the card's driver area, not the core
        ; (the core's room is the game's)
        .segment "DRIVER"
FC_HERE .set 0

geo_t_run:
        stz t_at
        lda #$02
        sta t_at+1
        ldx geo_t_kind
        lda size,x
        sta t_size
@next:  lda geo_t_count
        ora geo_t_count+1
        bne @here
        rts
@here:  lda #GEO_T_BANK                 ; the record
        sta FA_BANK
        lda t_at
        sta FA_SRC
        lda t_at+1
        sta FA_SRC+1
        lda #<geo_t_buf
        sta FA_DST
        lda #>geo_t_buf
        sta FA_DST+1
        lda t_size
        sta FA_N
        jsr far_get
        lda geo_t_kind
        bne :+
        jsr t_pos
        bra @put
:       cmp #1
        bne :+
        jsr t_box
        bra @put
:       jsr t_mul
@put:   lda #GEO_T_BANK
        sta FA_BANK
        lda #<geo_t_buf
        sta FA_SRC
        lda #>geo_t_buf
        sta FA_SRC+1
        lda t_at
        sta FA_DST
        lda t_at+1
        sta FA_DST+1
        lda t_size
        sta FA_N
        jsr far_put
        clc
        lda t_at
        adc t_size
        sta t_at
        bcc :+
        inc t_at+1
:       lda geo_t_count
        bne :+
        dec geo_t_count+1
:       dec geo_t_count
        jmp @next

t_pos:  ldx #7
:       lda geo_t_buf,x
        sta GA_X,x
        dex
        bpl :-
        lda geo_t_buf+8
        ldx geo_t_buf+9
        FCALL P_PointOnLineSide
        sta geo_t_buf+10
        rts

t_box:  ldx #15
:       lda geo_t_buf,x
        sta GA_0,x
        dex
        bpl :-
        lda geo_t_buf+16
        ldx geo_t_buf+17
        FCALL P_BoxOnLineSide
        sta geo_t_buf+18
        rts

t_mul:  ldx #2
:       lda geo_t_buf,x
        sta M_A,x
        dex
        bpl :-
        lda geo_t_buf+3
        sta M_B
        lda geo_t_buf+4
        sta M_B+1
        FCALL posMul
        ldx #3
:       lda M_R,x
        sta geo_t_buf+5,x
        dex
        bpl :-
        rts

size:   .byte 11, 19, 9
geo_t_kind:  .res 1
geo_t_count: .res 2
geo_t_buf:   .res 20
t_at:   .res 2
t_size: .res 1

.endif
