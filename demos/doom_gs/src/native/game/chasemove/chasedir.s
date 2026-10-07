; game/chasemove/chasedir.s: part chasemove's new chase direction
; (docs/GAME.md, the parts). A GPL-2 derivative of upstream's p_enemy65.s
; with TICSTEP 1, the release's (P_NewChaseDir with newChaseDir,
; doNewChaseDir, setDir, absGreater, absD).
;
;   newChaseDir   GA_0-1 the actor (CM_AP; upstream's AP): with a tall
;                 drop-off under it (floorz - dropoffz > 24.0, signed), z <=
;                 floorz, no MF_DROPOFF and avoidDropoff's answer, the
;                 directions away from it (doNewChaseDir with dropoff_deltax,
;                 dropoff_deltay) and movecount = 1; else doNewChaseDir with
;                 the target's x, y less the actor's. A target is always
;                 there (A_Chase's calls; C Doom's I_Error): none stops with
;                 GS_ERROR
;   doNewChaseDir CM_AP the actor, CM_D deltax, deltay: olddir = movedir,
;                 turnaround its opposite (DI_NODIR stays); xdir east for
;                 deltax > 10.0, west for < -10.0; ydir south for deltay <
;                 -10.0, north for > 10.0 (signed 32 bits). With both, the
;                 diagonal is set and walked (tryWalk) unless it is the
;                 turnaround. Then P_Random() > 200, or |deltay| > |deltax|,
;                 swaps xdir and ydir (P_Random is taken first, |...| only
;                 for 200 or less); each of xdir, ydir that is not the
;                 turnaround, then olddir, is set and walked; then, by
;                 P_Random() & 1, every direction east to southeast or
;                 southeast to east but the turnaround; then the turnaround
;                 (set even when none), else DI_NODIR. A walk that moves
;                 ends the search
;   P_NewChaseDir upstream's public P_NewChaseDir: newChaseDir
;
; setDir, absGreater and absD have no code of their own: cm_setdir,
; cm_absgreater, cm_abs. Each routine's local code is in its own segment (its
; group): newChaseDir's cm_get, doNewChaseDir's dn_get. Records through the
; object API (mo_get, mo_dirty); P_Random is g_random. A routine changes A, X,
; Y, GA_*, GT_*, the math block, the API's temporaries and what its callees
; change.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/chasemove/chasemove.inc"

        .export newChaseDir, doNewChaseDir, P_NewChaseDir
        .import mo_get, mo_dirty, g_random, g_stop
        .import fc_call, fc_unbuilt

; ===========================================================================
; P_NewChaseDir, newChaseDir
; ===========================================================================
        ROUTINE P_NewChaseDir
        FCALL newChaseDir
        rts

        ROUTINE newChaseDir
        lda GA_0
        sta CM_AP
        ldx GA_1
        stx CM_AP+1
        jsr mo_get
        ldy #LN_B + MB_FLOORZ + 3       ; M_A = floorz
        ldx #3
:       lda (GC_MP),y
        sta M_A,x
        dey
        dex
        bpl :-
        ldy #LN_B + MB_DROPZ            ; GT_0-3 = floorz - dropoffz
        ldx #0
        sec
:       lda M_A,x
        sbc (GC_MP),y
        sta GT_0,x
        iny
        inx
        txa
        eor #4
        bne :-
        sec                             ; 24.0 < it: the sign of 24.0 - it
        lda #0
        sbc GT_0
        lda #0
        sbc GT_1
        lda #24
        sbc GT_2
        lda #0
        sbc GT_3
        bvc :+
        eor #$80
:       bpl @target
        ldy #TH_Z                       ; z <= floorz: not floorz < z
        lda M_A
        cmp (GC_MP),y
        iny
        lda M_A+1
        sbc (GC_MP),y
        iny
        lda M_A+2
        sbc (GC_MP),y
        iny
        lda M_A+3
        sbc (GC_MP),y
        bvc :+
        eor #$80
:       bmi @target
        ldy #LN_B + MB_FLAGS + 1        ; not MF_DROPOFF
        lda (GC_MP),y
        and #>UC_MF_DROPOFF_LO
        bne @target
        FCALL avoidDropoff
        bcc @target
        ldx #7                          ; doNewChaseDir(dropoff_deltax,
:       lda CM_DDX,x                    ;   dropoff_deltay)
        sta CM_D,x
        dex
        bpl :-
        FCALL doNewChaseDir
        jsr cm_get                      ; movecount = 1: small steps away
        ldy #LN_C + MC_MOVEC
        lda #1
        sta (GC_MP),y
        iny
        lda #0
        sta (GC_MP),y
        lda #D_C
        jmp mo_dirty

@target:
        jsr cm_get                      ; the target
        ldy #LN_A + MA_TARGET
        lda (GC_MP),y
        sta GT_0
        iny
        lda (GC_MP),y
        sta GT_1
        and GT_0
        cmp #$FF
        bne :+
        lda #GS_ERROR                   ; none (P_NewChaseDir: called with
        jmp g_stop                      ;   no target)
:       ldy #7                          ; deltax, deltay = the target's x,
:       lda (GC_MP),y                   ;   y less the actor's
        sta CM_D,y
        dey
        bpl :-
        lda GT_0
        ldx GT_1
        jsr mo_get
        ldy #0
        sec
:       lda (GC_MP),y
        sbc CM_D,y
        sta CM_D,y
        iny
        tya
        and #3
        bne :-
        sec
:       lda (GC_MP),y
        sbc CM_D,y
        sta CM_D,y
        iny
        tya
        and #3
        bne :-
        FCALL doNewChaseDir
        rts

; cm_get: GC_MP = the actor's line (CM_AP)
cm_get: lda CM_AP
        ldx CM_AP+1
        jmp mo_get

; ===========================================================================
; doNewChaseDir
; ===========================================================================
        ROUTINE doNewChaseDir
        jsr dn_get                      ; olddir, turnaround
        ldy #LN_C + MC_MOVEDIR
        lda (GC_MP),y
        sta CM_OLD
        cmp #UC_DI_NODIR
        beq :+
        eor #4
:       sta CM_TURN
        ; xdir: deltax > 10.0 east, < -10.0 west
        ldx #UC_DI_EAST
        sec                             ; the sign of 10.0 - deltax
        lda #0
        sbc CM_D
        lda #0
        sbc CM_D+1
        lda #10
        sbc CM_D+2
        lda #0
        sbc CM_D+3
        bvc :+
        eor #$80
:       bmi @xd
        ldx #UC_DI_WEST
        sec                             ; the sign of deltax + 10.0
        lda CM_D
        sbc #0
        lda CM_D+1
        sbc #0
        lda CM_D+2
        sbc #<-10
        lda CM_D+3
        sbc #>-10
        bvc :+
        eor #$80
:       bmi @xd
        ldx #UC_DI_NODIR
@xd:    stx CM_XDIR
        ; ydir: deltay < -10.0 south, > 10.0 north
        ldx #UC_DI_SOUTH
        sec                             ; the sign of deltay + 10.0
        lda CM_D+4
        sbc #0
        lda CM_D+5
        sbc #0
        lda CM_D+6
        sbc #<-10
        lda CM_D+7
        sbc #>-10
        bvc :+
        eor #$80
:       bmi @yd
        ldx #UC_DI_NORTH
        sec                             ; the sign of 10.0 - deltay
        lda #0
        sbc CM_D+4
        lda #0
        sbc CM_D+5
        lda #10
        sbc CM_D+6
        lda #0
        sbc CM_D+7
        bvc :+
        eor #$80
:       bmi @yd
        ldx #UC_DI_NODIR
@yd:    stx CM_YDIR
        ; the direct route: the diagonal
        lda CM_XDIR
        cmp #UC_DI_NODIR
        beq @other
        cpx #UC_DI_NODIR
        beq @other
        sec                             ; N: 0 < deltax
        lda #0
        sbc CM_D
        lda #0
        sbc CM_D+1
        lda #0
        sbc CM_D+2
        lda #0
        sbc CM_D+3
        bvc :+
        eor #$80
:       php
        lda CM_D+7                      ; deltay < 0: south
        bmi @south
        ldx #UC_DI_NORTHEAST
        plp
        bmi @diag
        ldx #UC_DI_NORTHWEST
        bra @diag
@south: ldx #UC_DI_SOUTHEAST
        plp
        bmi @diag
        ldx #UC_DI_SOUTHWEST
@diag:  txa                             ; movedir = the diagonal; walked
        jsr cm_setdir                   ;   unless it is the turnaround
        cmp CM_TURN
        beq @other
        jsr cm_try
        jne @ret
        ; the other directions
@other: jsr g_random                    ; P_Random() > 200 || |deltay| >
        cmp #201                        ;   |deltax|: xdir, ydir swapped
        bcs @swap
        jsr cm_absgreater
        bcc @x
@swap:  lda CM_XDIR
        ldx CM_YDIR
        sta CM_YDIR
        stx CM_XDIR
@x:     lda CM_XDIR                     ; xdir, unless the turnaround
        cmp CM_TURN
        bne :+
        lda #UC_DI_NODIR
        sta CM_XDIR
:       cmp #UC_DI_NODIR
        beq @y
        jsr cm_setdir
        jsr cm_try
        jne @ret
@y:     lda CM_YDIR                     ; ydir, unless the turnaround
        cmp CM_TURN
        bne :+
        lda #UC_DI_NODIR
        sta CM_YDIR
:       cmp #UC_DI_NODIR
        beq @old
        jsr cm_setdir
        jsr cm_try
        jne @ret
@old:   lda CM_OLD                      ; the old direction
        cmp #UC_DI_NODIR
        beq @rand
        jsr cm_setdir
        jsr cm_try
        jne @ret
@rand:  jsr g_random                    ; a random search order
        and #1
        beq @down
        lda #UC_DI_EAST                 ; east .. southeast
@up:    sta CM_TDIR
        cmp CM_TURN
        beq :+
        jsr cm_setdir
        jsr cm_try
        jne @ret
:       lda CM_TDIR
        inc a
        cmp #UC_DI_SOUTHEAST + 1
        bcc @up
        bra @turn
@down:  lda #UC_DI_SOUTHEAST            ; southeast .. east
@dn:    sta CM_TDIR
        cmp CM_TURN
        beq :+
        jsr cm_setdir
        jsr cm_try
        jne @ret
:       lda CM_TDIR
        dec a
        bpl @dn
@turn:  lda CM_TURN                     ; the turnaround, or no direction
        jsr cm_setdir
        cmp #UC_DI_NODIR
        jeq @ret
        jsr cm_try
        jne @ret
        lda #UC_DI_NODIR
        jsr cm_setdir
@ret:   rts

; dn_get: GC_MP = the actor's line (CM_AP): doNewChaseDir's own (its group
; is not newChaseDir's: a routine's local code is in its own segment)
dn_get: lda CM_AP
        ldx CM_AP+1
        jmp mo_get

; cm_setdir (setDir): the actor's movedir = A; A kept
cm_setdir:
        pha
        jsr dn_get
        pla
        ldy #LN_C + MC_MOVEDIR
        sta (GC_MP),y
        pha
        lda #D_C
        jsr mo_dirty
        pla
        rts

; cm_try: tryWalk(the actor); Z clear (A = 1) when it moved
cm_try: lda CM_AP
        sta GA_0
        lda CM_AP+1
        sta GA_1
        FCALL tryWalk
        cmp #0
        rts

; cm_absgreater (absGreater): C set when |deltax| < |deltay| (signed 32
; bits: |-2^31| stays negative, as upstream's absD)
cm_absgreater:
        ldx #0                          ; M_A = |deltax|
        jsr cm_abs
        ldx #4                          ; M_B = |deltay|
        jsr cm_abs
        lda M_A
        cmp M_B
        lda M_A+1
        sbc M_B+1
        lda M_A+2
        sbc M_B+2
        lda M_A+3
        sbc M_B+3
        bvc :+
        eor #$80
:       asl a                           ; (the sign)
        rts

; cm_abs (absD): M_A + X .. + 3 = |CM_D + X .. + 3|, two's complement
        .assert M_B = M_A + 4, error, "M_A, M_B"
cm_abs: ldy #4
        lda CM_D+3,x
        bmi @neg
:       lda CM_D,x
        sta M_A,x
        inx
        dey
        bne :-
        rts
@neg:   sec
:       lda #0
        sbc CM_D,x
        sta M_A,x
        inx
        dey
        bne :-
        rts
