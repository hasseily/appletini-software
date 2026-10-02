; game/damage/dtest.s: part damage's test routine (milestone 10, docs/GAME.md
; 2.4 "Arithmetic"; docs/game-parts/damage.md), in the part's checkpoint
; image only (DM_TEST=1) and in the card's driver area (test-only code
; leaves the core: wave 1 as integrated). GPL-2, the port's own.
;
;   dm_t_bulk   the thrust on many inputs, for the random check against
;               upstream's thrust on ref816 (tools/native/gparts/damage.py
;               --random): X:Y = the count; each input record (38 bytes,
;               from bank BULK_IN at $0200 on) is the damage (2), the
;               target's type (1), P_Random's index (1), the target's x, y,
;               z (12), health (2), momx, momy (8) and the inflictor's x,
;               y, z (12); the target is slot 0 (flags 0), the inflictor
;               slot 1, no source; each output record (17 bytes, to bank
;               BULK_OUT at $0200 on) the target's momx, momy (8), P_Random's
;               index (1), the thrust (4) and its angle (4)

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/damage/damage.inc"

        .import mo_get, mo_dirty, far_get, far_put, mt_init, fc_call
        .import fc_unbuilt

.ifdef TESTBUILD
        .export dm_t_bulk
        .segment "DRIVER"
FC_HERE .set 0

BULK_IN  = 93
BULK_OUT = 94
REC     = BL_BUF                ; an input record (main, scratch here)
OREC    = BL_BUF + 64           ; an output record
IN_SIZE = 38
OUT_SIZE = 17

dm_t_bulk:
        stx dt_n
        sty dt_n+1
        jsr mt_init             ; (a machine with no game: the math's
        lda #<$0200             ;   square pointers first)
        sta dt_ip
        sta dt_op
        lda #>$0200
        sta dt_ip+1
        sta dt_op+1
@next:  lda dt_n
        ora dt_n+1
        bne :+
        rts
:       lda dt_n
        bne :+
        dec dt_n+1
:       dec dt_n
        lda #IN_SIZE            ; the record
        sta FA_N
        lda dt_ip
        sta FA_SRC
        lda dt_ip+1
        sta FA_SRC+1
        lda #<REC
        sta FA_DST
        lda #>REC
        sta FA_DST+1
        lda #BULK_IN
        sta FA_BANK
        jsr far_get
        clc
        lda dt_ip
        adc #IN_SIZE
        sta dt_ip
        bcc :+
        inc dt_ip+1
:       lda #0                  ; the target: slot 0
        tax
        jsr mo_get
        ldy #11                 ; x, y, z
:       lda REC + 4,y
        sta (GC_MP),y
        dey
        bpl :-
        ldy #LN_A + MA_HEALTH
        lda REC + 16
        sta (GC_MP),y
        iny
        lda REC + 17
        sta (GC_MP),y
        ldy #LN_A + MA_TYPE
        lda REC + 2
        sta (GC_MP),y
        ldy #LN_B + MB_FLAGS + 3        ; flags 0
        lda #0
:       sta (GC_MP),y
        dey
        cpy #LN_B + MB_FLAGS - 1
        bne :-
        ldx #0                  ; momx, momy
        ldy #LN_C + MC_MOMX
:       lda REC + 18,x
        sta (GC_MP),y
        iny
        inx
        cpx #8
        bne :-
        lda #D_RTH | D_A | D_B | D_C
        jsr mo_dirty
        lda #1                  ; the inflictor: slot 1
        ldx #0
        jsr mo_get
        ldy #11
:       lda REC + 26,y
        sta (GC_MP),y
        dey
        bpl :-
        lda #D_RTH
        jsr mo_dirty
        stz DM_TGT              ; P_DamageMobj's: target, inflictor, no
        stz DM_TGT+1            ;   source, the damage, the type
        lda #1
        sta DM_INF
        stz DM_INF+1
        lda #$FF
        sta DM_SRC
        sta DM_SRC+1
        lda REC
        sta DM_DMG
        lda REC + 1
        sta DM_DMG+1
        lda REC + 2
        sta DM_TYPE
        lda #5                  ; the player's mobj: another one
        sta G_PLAYER + PL_MO
        stz G_PLAYER + PL_MO + 1
        lda REC + 3
        sta PRND
        FCALL thrust
        lda #0                  ; the outputs
        tax
        jsr mo_get
        ldx #0
        ldy #LN_C + MC_MOMX
:       lda (GC_MP),y
        sta OREC,x
        iny
        inx
        cpx #8
        bne :-
        lda PRND
        sta OREC + 8
        ldx #3
:       lda DM_THR,x
        sta OREC + 9,x
        lda DM_ANG,x
        sta OREC + 13,x
        dex
        bpl :-
        lda #OUT_SIZE
        sta FA_N
        lda #<OREC
        sta FA_SRC
        lda #>OREC
        sta FA_SRC+1
        lda dt_op
        sta FA_DST
        lda dt_op+1
        sta FA_DST+1
        lda #BULK_OUT
        sta FA_BANK
        jsr far_put
        clc
        lda dt_op
        adc #OUT_SIZE
        sta dt_op
        bcc :+
        inc dt_op+1
:       jmp @next

dt_n:   .res 2
dt_ip:  .res 2
dt_op:  .res 2
.endif
