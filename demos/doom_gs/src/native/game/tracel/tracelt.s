; game/tracel/tracelt.s: part tracel's test driver for the random checks
; (docs/GAME.md 2.4 row tracel: interceptVector3 and divlineSide on
; 1,000,000 random inputs, the arithmetic helpers ivProd and smul on
; 100,000, and the part's other pure routines), test builds only. GPL-2,
; the port's own. Not game code: it reads and writes its records with the
; far layer, as geom's geomt.s and the harness's grec.s do.
;
;   tl_t_run    for each of tl_t_count records (from $0200 of bank
;               TL_T_BANK0, on to the next bank when a record would pass
;               $BFFF; banks TL_T_BANK0 .. TL_T_BANK0 + 4, spare banks of
;               llayout.bank_map): the record into tl_t_buf, its inputs to
;               their places (the kind's input list), the routine of
;               tl_t_kind, its outputs after the inputs in the record, the
;               record back. GT_DIV0 is 0 before each call; an output
;               "div0" is its low byte after.
;
; The kinds (inputs; outputs), each place a run of bytes:
;   0 interceptVector3   trace 16, dl 16, IV_ON 1, IV_M 8; frac 4, div0 1
;   1 divlineSide        trace 16, x 4, y 4; side 1
;   2 ivTest             num 4, den 4; frac 4, div0 1
;   3 ivAxis             trace 16, dl 16, IV_ON 1; C 1, frac 4, div0 1
;   4 ivProd             trace 16, dl 16, IV_ON 1, IV_M 8, axis 1; M_R 4
;   5 smul               a 2, b 2; M_R 4
;   6 ivSetup            trace 16, IV_M 8; A 1, IV_M 8
;   7 gOf                f 2; A:X 2
;   8 vsC                SQ 2, axis 1, g of y 2, g of x 2; VT_CV 2, VT_CT 2
;
; tools/native/gparts/tracel.py writes the records and the descriptor
; (tl_t_kind, tl_t_count by their labels) and reads the results back from
; the run's snapshot.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/tracel/tracel.inc"

.ifdef TESTBUILD
        .export tl_t_run, tl_t_kind, tl_t_count, tl_t_buf
        .import far_get, far_put, fc_call, fc_unbuilt

; the copies' pointers: temporaries of the zero page (GAME.md 4.4), used
; only between the calls (the object API's GO_* bytes: no API call runs
; while they live)
t_d     = GT_20
t_p     = GT_22

TL_T_BANK0 = 93                 ; (spare: llayout.bank_map; 93-97)
TL_T_FIRST = $0200
TL_T_END   = $C000

        ; test-only code goes in the card's driver area, not the core
        ; (wave 1 as integrated: the core's room is the game's)
        .segment "DRIVER"
FC_HERE .set 0

tl_t_run:
        lda #TL_T_BANK0
        sta t_bank
        lda #<TL_T_FIRST
        sta t_at
        lda #>TL_T_FIRST
        sta t_at+1
        ldx tl_t_kind
        lda size,x
        sta t_size
@next:  lda tl_t_count
        ora tl_t_count+1
        bne @here
        rts
@here:  clc                             ; this bank's end: the next bank
        lda t_at
        adc t_size
        tay
        lda t_at+1
        adc #0
        cpy #$01                        ; (past $C000: $C001 or more)
        sbc #$C0
        bcc @fits
        inc t_bank
        lda #<TL_T_FIRST
        sta t_at
        lda #>TL_T_FIRST
        sta t_at+1
@fits:  lda t_bank                      ; the record
        sta FA_BANK
        lda t_at
        sta FA_SRC
        lda t_at+1
        sta FA_SRC+1
        lda #<tl_t_buf
        sta FA_DST
        lda #>tl_t_buf
        sta FA_DST+1
        lda t_size
        sta FA_N
        jsr far_get
        ldx tl_t_kind                   ; its inputs
        lda ins_lo,x
        sta t_d
        lda ins_hi,x
        sta t_d+1
        stz t_i
        jsr copy_in
        stz GT_DIV0
        stz GT_DIV0+1
        lda tl_t_kind
        asl a
        tax
        jsr @call
        php                             ; (C: ivAxis's answer)
        pla
        and #1
        sta t_c
        ldx tl_t_kind                   ; its outputs
        lda outs_lo,x
        sta t_d
        lda outs_hi,x
        sta t_d+1
        jsr copy_out
        lda t_bank                      ; the record back
        sta FA_BANK
        lda #<tl_t_buf
        sta FA_SRC
        lda #>tl_t_buf
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
:       lda tl_t_count
        bne :+
        dec tl_t_count+1
:       dec tl_t_count
        jmp @next
@call:  jmp (calls,x)

calls:  .word c_iv3, c_side, c_test, c_axis, c_prod, c_smul, c_setup
        .word c_gof, c_vsc

c_iv3:  FCALL interceptVector3
        rts
c_side: FCALL divlineSide
        sta t_r
        rts
c_test: FCALL ivTest
        rts
c_axis: FCALL ivAxis
        rts
c_prod: ldx t_ax
        FCALL ivProd
        rts
c_smul: FCALL smul
        rts
c_setup:
        FCALL ivSetup
        sta t_r
        rts
c_gof:  lda t_f
        ldx t_f+1
        FCALL gOf
        sta t_r
        stx t_r+1
        rts
c_vsc:  FCALL vsC
        rts

; copy_in: the runs of list t_d (address, length; length 0 ends) from
; tl_t_buf + t_i on; copy_out: the same into tl_t_buf after the inputs
copy_in:
        ldy #0
@run:   lda (t_d),y
        sta t_p
        iny
        lda (t_d),y
        sta t_p+1
        iny
        lda (t_d),y
        beq @end
        sta t_n
        iny
        phy
        ldy #0
        ldx t_i
:       lda tl_t_buf,x
        sta (t_p),y
        inx
        iny
        dec t_n
        bne :-
        stx t_i
        ply
        bra @run
@end:   rts

copy_out:
        ldy #0
@run:   lda (t_d),y
        sta t_p
        iny
        lda (t_d),y
        sta t_p+1
        iny
        lda (t_d),y
        beq @end
        sta t_n
        iny
        phy
        ldy #0
        ldx t_i
:       lda (t_p),y
        sta tl_t_buf,x
        inx
        iny
        dec t_n
        bne :-
        stx t_i
        ply
        bra @run
@end:   rts

; the places: (address, length) runs, 0 ending each list
in_iv3:  .word TL_TRACE
         .byte 16
         .word TL_X1
         .byte 16
         .word TL_IVON
         .byte 1
         .word TL_IVM
         .byte 8
         .word 0
         .byte 0
out_frac:
         .word TL_F
         .byte 4
         .word GT_DIV0
         .byte 1
         .word 0
         .byte 0
in_side: .word TL_TRACE
         .byte 16
         .word TL_PX
         .byte 8
         .word 0
         .byte 0
out_r1:  .word t_r
         .byte 1
         .word 0
         .byte 0
in_test: .word TL_A
         .byte 8
         .word 0
         .byte 0
in_axis: .word TL_TRACE
         .byte 16
         .word TL_X1
         .byte 16
         .word TL_IVON
         .byte 1
         .word 0
         .byte 0
out_axis:
         .word t_c
         .byte 1
         .word TL_F
         .byte 4
         .word GT_DIV0
         .byte 1
         .word 0
         .byte 0
in_prod: .word TL_TRACE
         .byte 16
         .word TL_X1
         .byte 16
         .word TL_IVON
         .byte 1
         .word TL_IVM
         .byte 8
         .word t_ax
         .byte 1
         .word 0
         .byte 0
out_mr:  .word M_R
         .byte 4
         .word 0
         .byte 0
in_smul: .word M_A
         .byte 2
         .word M_B
         .byte 2
         .word 0
         .byte 0
in_setup:
         .word TL_TRACE
         .byte 16
         .word TL_IVM
         .byte 8
         .word 0
         .byte 0
out_setup:
         .word t_r
         .byte 1
         .word TL_IVM
         .byte 8
         .word 0
         .byte 0
in_gof:  .word t_f
         .byte 2
         .word 0
         .byte 0
out_gof: .word t_r
         .byte 2
         .word 0
         .byte 0
in_vsc:  .word TL_VSQ
         .byte 2
         .word TL_VAX
         .byte 1
         .word TL_VG
         .byte 2
         .word TL_VG + 4
         .byte 2
         .word 0
         .byte 0
out_vsc: .word TL_VCV
         .byte 2
         .word TL_VCT
         .byte 2
         .word 0
         .byte 0

ins_lo:  .byte <in_iv3, <in_side, <in_test, <in_axis, <in_prod, <in_smul
         .byte <in_setup, <in_gof, <in_vsc
ins_hi:  .byte >in_iv3, >in_side, >in_test, >in_axis, >in_prod, >in_smul
         .byte >in_setup, >in_gof, >in_vsc
outs_lo: .byte <out_frac, <out_r1, <out_frac, <out_axis, <out_mr, <out_mr
         .byte <out_setup, <out_gof, <out_vsc
outs_hi: .byte >out_frac, >out_r1, >out_frac, >out_axis, >out_mr, >out_mr
         .byte >out_setup, >out_gof, >out_vsc
size:    .byte 46, 25, 13, 39, 46, 8, 33, 4, 11

tl_t_kind:  .res 1
tl_t_count: .res 2
tl_t_buf:   .res 64
t_bank: .res 1
t_at:   .res 2
t_size: .res 1
t_i:    .res 1
t_n:    .res 1
t_c:    .res 1
t_r:    .res 2
t_ax:   .res 1
t_f:    .res 2


.endif
